"""Fellegi-Sunter probabilistic record linkage (1969).

The real fix for Indian-name duplication: the same person entered as "Ramesh Gowda"
and "Ramesha Gouda" under different SCRB ids. Unsupervised — the m/u probabilities
(P(field agrees | match) and P(field agrees | non-match)) are estimated by EM over
the candidate pairs themselves, so no labelled training data is needed.

Pipeline: block (so it isn't O(n^2)) -> comparison vector per pair -> EM -> match
weight + posterior -> link / possible_link / non_link -> union-find into canonical
entities -> write SAME_AS edges and canonical_entity_id via data's write helpers.

Called ONLY as a batch pass from data/generator/ — never live per query.
"""
import math
import random
import re
from dataclasses import dataclass
from itertools import combinations

from sqlalchemy import text

from data.db import get_session
from data.nlp import transliterate
from data.transactions import set_canonical_entity, write_same_as_edge

from ..types import MatchResult

# Posterior thresholds. Above LINK we write a SAME_AS edge; between the two we
# surface a possible link for human review; below, nothing. Explicit error-rate
# style thresholds, per the FS decision rule.
LINK_THRESHOLD = 0.90
POSSIBLE_THRESHOLD = 0.55

# Expected share of person records that are duplicate re-registrations. Drives the
# match prior over the FULL cross-product (see _prior_match_prob).
PRIOR_DUPLICATE_RATE = 0.10


def _prior_match_prob(n_records: int) -> float:
    """P(a pair is a match) over the full cross-product, NOT over the blocked set.

    This has to live in the same space as `u`, which is measured on random pairs.
    Fellegi-Sunter's decision rule is defined over all pairs; blocking is only a
    computational shortcut for skipping pairs that would score low anyway. Feeding
    a candidate-set prior (~0.1) into a random-pair u makes mere name agreement look
    decisive — every name-blocked stranger then scores as a link. With ~10% of n
    records being duplicates, expected matches ~= 0.1n out of C(n,2) pairs.
    """
    if n_records < 2:
        return 0.0
    return min(0.5, (PRIOR_DUPLICATE_RATE * n_records) / (n_records * (n_records - 1) / 2))

# Multi-level comparison, not binary agree/disagree. Two reasons this matters:
#   1. A mis-keyed/transposed birth day is the commonest real duplicate defect, so
#      DOB needs a "same year, different day" level between agree and disagree.
#      Modelling that as a *separate binary field* (dob + dob_year) breaks FS's
#      conditional-independence assumption — the two are almost perfectly
#      correlated, so DOB evidence gets counted twice and an accidental birthday
#      collision between two different people outweighs a name AND address
#      disagreement. One field, three levels, is the correct formulation.
#   2. Address likewise: same-locality / same-region / elsewhere carries more
#      signal than a single 1km threshold.
# Level 0 is always the strongest agreement.
_FIELDS = ("name", "dob", "gender", "address")
_N_LEVELS = {"name": 3, "dob": 3, "gender": 2, "address": 3}
_SMOOTH = 1e-4


@dataclass
class _Rec:
    person_id: str
    name_en: str
    dob: object
    gender: str
    lat: float | None
    lng: float | None


# --- field comparators -------------------------------------------------------

def _jaro_winkler(s1: str, s2: str) -> float:
    s1, s2 = s1.lower(), s2.lower()
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    window = max(len(s1), len(s2)) // 2 - 1
    window = max(window, 0)
    s1_m = [False] * len(s1)
    s2_m = [False] * len(s2)
    matches = 0
    for i, c in enumerate(s1):
        for j in range(max(0, i - window), min(len(s2), i + window + 1)):
            if not s2_m[j] and s2[j] == c:
                s1_m[i] = s2_m[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    k = 0
    transpositions = 0
    for i, matched in enumerate(s1_m):
        if matched:
            while not s2_m[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
    t = transpositions / 2
    jaro = (matches / len(s1) + matches / len(s2) + (matches - t) / matches) / 3
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a != b:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def _norm_key(name: str) -> str:
    """Aggressively collapse romanisation drift so variants share a blocking key:
    Ramesh/Ramesha and Geetha/Geeta/Githa each collapse to one key."""
    s = name.lower()
    for a, b in (("ksh", "x"), ("th", "t"), ("sh", "s"), ("ee", "i"),
                 ("oo", "u"), ("ph", "f"), ("v", "w")):
        s = s.replace(a, b)
    s = re.sub(r"(.)\1", r"\1", s)          # collapse doubles
    s = re.sub(r"[aeiouy]+$", "", s)        # drop trailing vowels (Ramesh/Ramesha)
    return re.sub(r"[^a-z ]", "", s)


def _haversine_km(a: _Rec, b: _Rec) -> float | None:
    if None in (a.lat, a.lng, b.lat, b.lng):
        return None
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _compare(a: _Rec, b: _Rec) -> tuple[int, ...]:
    """Agreement *level* per field (0 = strongest agreement)."""
    jw = _jaro_winkler(a.name_en, b.name_en)
    if jw >= 0.92 or b.name_en in set(transliterate(a.name_en)):
        name = 0                       # same name, or a known romanisation variant
    elif jw >= 0.85:
        name = 1                       # close but not a recognised variant
    else:
        name = 2

    if a.dob and b.dob and a.dob == b.dob:
        dob = 0                        # exact
    elif a.dob and b.dob and a.dob.year == b.dob.year:
        dob = 1                        # same year, mis-keyed day/month
    else:
        dob = 2

    gender = 0 if a.gender == b.gender else 1

    dist = _haversine_km(a, b)
    if dist is None:
        address = 2
    elif dist <= 1.0:
        address = 0                    # same locality
    elif dist <= 25.0:
        address = 1                    # same broad area
    else:
        address = 2

    return (name, dob, gender, address)


# --- EM estimation of m / u --------------------------------------------------

Params = tuple[list[list[float]], list[list[float]], float]   # m[field][level], u[...], p


def _init_params() -> Params:
    m, u = [], []
    for f in _FIELDS:
        n = _N_LEVELS[f]
        # matches concentrate on level 0 (agreement); non-matches on the last level
        m.append([0.8] + [0.2 / (n - 1)] * (n - 1))
        u.append([0.1] + [0.9 / (n - 1)] * (n - 1))
    return m, u, 0.1


def _likelihoods(g: tuple[int, ...], m, u, p) -> tuple[float, float]:
    pm, pu = p, 1 - p
    for i in range(len(_FIELDS)):
        pm *= m[i][g[i]]
        pu *= u[i][g[i]]
    return pm, pu


def estimate_u(recs: list[_Rec], rng: random.Random, n_samples: int = 20000) -> list[list[float]]:
    """u[field][level] = P(agreement level | NON-match), from a random sample of the
    full cross-product.

    Deliberately NOT estimated from the blocked candidate set. Blocking selects pairs
    that already agree on the blocking key, so u learned there is wildly wrong — and
    worse, letting EM fit u on candidates creates a self-reinforcing local optimum:
    it absorbs a handful of coincidental same-birthday strangers into the match class,
    which drives u[dob][exact] to ~0, which "proves" they were matches. Random pairs
    are ~all non-matches (duplicate prevalence over the full cross-product is <0.02%),
    so this measures u directly. Held fixed during EM; only m and p are learned.
    """
    counts = [[0.0] * _N_LEVELS[f] for f in _FIELDS]
    n = len(recs)
    for _ in range(n_samples):
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j:
            continue
        g = _compare(recs[i], recs[j])
        for fi in range(len(_FIELDS)):
            counts[fi][g[fi]] += 1
    u = []
    for fi, f in enumerate(_FIELDS):
        total = sum(counts[fi]) or 1.0
        k = _N_LEVELS[f]
        u.append([(c + _SMOOTH) / (total + k * _SMOOTH) for c in counts[fi]])
    return u


def _em(gammas: list[tuple[int, ...]], u: list[list[float]],
        p: float, iters: int = 100) -> Params:
    """Learn m with u and p held fixed.

    p is fixed, not learned, because it is **not identifiable** here: u describes
    *random* non-match pairs, but every candidate is a blocked pair that already
    agrees on the blocking key. Under that mismatch EM drives p -> 1.0 (every
    candidate "looks like" a match relative to a random pair) and links everything.
    Splink exposes the same quantity as a user-set prior (lambda) for this reason.
    With u and p pinned, EM recovers a clean m: true duplicates always agree on
    name, so m[name][disagree] -> ~0, which is exactly what rejects the
    coincidental same-birthday strangers.
    """
    m, _, _ = _init_params()
    for _ in range(iters):
        gs = []
        for g in gammas:
            pm, pu = _likelihoods(g, m, u, p)
            gs.append(pm / (pm + pu) if (pm + pu) > 0 else 0.0)
        sg = sum(gs)
        if sg <= 1e-9:
            break
        for i, f in enumerate(_FIELDS):
            k = _N_LEVELS[f]
            for l in range(k):
                mi = sum(g_ for g_, gm in zip(gs, gammas) if gm[i] == l)
                m[i][l] = (mi + _SMOOTH) / (sg + k * _SMOOTH)
            # FS axiom: the strongest-agreement level must be more likely among
            # matches than among non-matches.
            if m[i][0] <= u[i][0]:
                m[i][0] = min(0.999, u[i][0] + 0.01)
    return m, u, p


def _posterior(g: tuple[int, ...], m, u, p: float) -> float:
    pm, pu = _likelihoods(g, m, u, p)
    return pm / (pm + pu) if (pm + pu) > 0 else 0.0


# --- candidate generation ----------------------------------------------------

def _load(person_ids: list[str]) -> list[_Rec]:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT person_id, name_en, dob, gender, "
            "  ST_Y(address_geom) AS lat, ST_X(address_geom) AS lng "
            "FROM person WHERE person_id = ANY(CAST(:ids AS uuid[]))"
        ), {"ids": person_ids}).all()
    return [_Rec(str(r.person_id), r.name_en or "", r.dob, r.gender or "",
                 r.lat, r.lng) for r in rows]


def _candidate_pairs(recs: list[_Rec]) -> set[tuple[int, int]]:
    """Block on the collapsed name key and on (gender, dob) — a pair only needs to
    collide in one block to be scored. Keeps this far below O(n^2) while still
    catching variants whose DOB was mis-keyed and DOB-identical pairs whose names
    drifted past the key."""
    blocks: dict[tuple, list[int]] = {}
    for i, r in enumerate(recs):
        keys = [("name", _norm_key(r.name_en))]
        if r.dob:
            keys.append(("dob", r.gender, r.dob))
        if r.lat is not None and r.lng is not None:
            # ~100m cell. A re-registered person keeps their address, so this block
            # catches the pairs whose name drifted AND whose DOB was mis-keyed —
            # the ones name/DOB blocking alone never even scores.
            keys.append(("addr", round(r.lat, 3), round(r.lng, 3)))
        for key in keys:
            blocks.setdefault(key, []).append(i)

    pairs: set[tuple[int, int]] = set()
    for members in blocks.values():
        if len(members) < 2 or len(members) > 200:   # skip degenerate mega-blocks
            continue
        for a, b in combinations(sorted(members), 2):
            pairs.add((a, b))
    return pairs


# --- public entrypoint -------------------------------------------------------

def score_records(recs: list[_Rec]) -> tuple[list[MatchResult], list[tuple[int, int]]]:
    """Pure scoring: block -> compare -> estimate u -> EM for m -> posterior.

    No I/O, so the linkage model is testable without a database. Returns the
    per-pair results and the index pairs that crossed LINK_THRESHOLD.
    """
    pairs = sorted(_candidate_pairs(recs))
    if not pairs:
        return [], []
    gammas = [_compare(recs[a], recs[b]) for a, b in pairs]
    u = estimate_u(recs, random.Random(0))     # fixed seed: reproducible linkage
    m, u, p = _em(gammas, u, _prior_match_prob(len(recs)))

    results: list[MatchResult] = []
    links: list[tuple[int, int]] = []
    for (a, b), g in zip(pairs, gammas):
        conf = _posterior(g, m, u, p)
        if conf >= LINK_THRESHOLD:
            decision = "link"
            links.append((a, b))
        elif conf >= POSSIBLE_THRESHOLD:
            decision = "possible_link"
        else:
            decision = "non_link"
        results.append(MatchResult(person_id_a=recs[a].person_id,
                                   person_id_b=recs[b].person_id,
                                   decision=decision, confidence=round(conf, 4)))
    return results, links


def resolve_entities(candidate_person_ids: list[str]) -> list[MatchResult]:
    """Score candidate pairs, write SAME_AS edges + canonical_entity_id for links."""
    recs = _load(candidate_person_ids)
    if len(recs) < 2:
        return []
    results, links = score_records(recs)
    _write_links(recs, links, results)
    return results


def _write_links(recs: list[_Rec], links: list[tuple[int, int]],
                 results: list[MatchResult]) -> None:
    """Union-find the linked pairs into entities; every member of a cluster gets the
    same canonical_entity_id (the cluster's lowest person_id, so it's stable)."""
    parent = list(range(len(recs)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in links:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    conf_by_pair = {(r.person_id_a, r.person_id_b): r.confidence for r in results}
    for a, b in links:
        c = conf_by_pair.get((recs[a].person_id, recs[b].person_id), 1.0)
        write_same_as_edge(recs[a].person_id, recs[b].person_id, c)

    clusters: dict[int, list[int]] = {}
    for i in range(len(recs)):
        clusters.setdefault(find(i), []).append(i)
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        canonical = min(recs[i].person_id for i in members)
        for i in members:
            set_canonical_entity(recs[i].person_id, canonical, 1.0)
