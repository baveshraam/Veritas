"""Fellegi-Sunter probabilistic record linkage (1969).

**This is what makes the KSP schema queryable.** Their ER has no person: an `Accused`
row belongs to exactly one FIR, carries a free-text name, and `Accused.PersonID` is a
per-case sort label ("A1", "A2"). There is no key that says the Ramesh Gowda arrested in
Kolar last year is the Ramesha Gouda arrested in Hubballi today. So "does he have priors?"
— the single most basic question a police officer asks — is not a lookup in this schema.
It is an inference, and this module is the inference.

We reconstruct the missing entity: cluster the Accused rows into people, write them to
vx_person, and map every Accused row to its person in vx_accused_identity. Everything
downstream — recidivism, the co-accused graph, gang communities, "top-5 similar cases" —
is built on that reconstruction, and is only as good as it.

Unsupervised: the m/u probabilities (P(field agrees | match) and P(field agrees | non-match))
are estimated by EM, so no labelled training data is needed.

Pipeline: block (so it isn't O(n^2)) -> comparison vector per pair -> EM -> match weight +
posterior -> link / possible_link / non_link -> union-find into people -> write vx_person +
vx_accused_identity.

Called ONLY as a batch pass from data/generator/ — never live per query.
"""
import math
import random
import re
from dataclasses import dataclass
from itertools import combinations

from data import ds
from data.nlp import transliterate

from ..types import MatchResult

# Posterior thresholds. Above LINK we write a SAME_AS edge; between the two we
# surface a possible link for human review; below, nothing. Explicit error-rate
# style thresholds, per the FS decision rule.
LINK_THRESHOLD = 0.90
POSSIBLE_THRESHOLD = 0.55

# Share of true matches expected to agree on name at the strongest level. Used only to
# turn an observed count of name-agreeing pairs into an estimate of how many matches exist
# (see _prior_match_prob). Not a tuning knob — it is the claim "the same man is usually
# recorded under the same name", which the variant rate makes ~2/3 true, plus the variants
# transliterate() recognises.
M_NAME_AGREE = 0.8


def _prior_match_prob(recs: list["_Rec"], gammas: list[tuple[int, ...]],
                      u: list[list[float]]) -> float:
    """P(a pair is a match) over the full cross-product, NOT over the blocked set.

    This has to live in the same space as `u`, which is measured on non-matching pairs.
    Fellegi-Sunter's decision rule is defined over all pairs; blocking is only a
    computational shortcut for skipping pairs that would score low anyway. Feeding a
    candidate-set prior into a non-match u makes mere name agreement look decisive.

    It is the one quantity EM cannot recover here (see _em), and it cannot be guessed
    either: understate it and every posterior falls below the link threshold and NOTHING
    links; overstate it and strangers get merged. So it is estimated by method of moments
    on the most discriminating field.

    Among all pairs, the number that agree on name at the strongest level is
        observed  =  matches * m_name_agree  +  non_matches * u_name_agree
    We have measured u on pairs that cannot be matches, and we observe the count directly.
    Solving for the number of matches gives the prior. Everything on the right-hand side is
    either counted or measured; only m_name_agree is assumed, and it is assumed once.
    """
    n = len(recs)
    if n < 2 or not gammas:
        return 0.0
    total_pairs = n * (n - 1) / 2
    observed = sum(1 for g in gammas if g[0] == 0)      # blocking never misses these
    by_chance = total_pairs * u[0][0]
    matches = max(observed - by_chance, 1.0) / M_NAME_AGREE
    return min(0.5, matches / total_pairs)


# Multi-level comparison, not binary agree/disagree. Two reasons this matters:
#   1. A stated age is noisy — an FIR records what the accused said, and the same man is
#      "34" in a 2023 case and "37" in a 2026 one. So we never compare ages; we compare
#      the birth year each case *implies* (case year - stated age), and give it a middle
#      level for "within a couple of years". Modelling that as a separate binary field
#      would break FS's conditional-independence assumption — two near-identical fields
#      count the same evidence twice, and an accidental birth-year collision between two
#      strangers would then outweigh a name AND location disagreement. One field, three
#      levels, is the correct formulation.
#   2. Location likewise: same-locality / same-region / elsewhere carries more signal than
#      a single 5km threshold.
# Level 0 is always the strongest agreement.
_FIELDS = ("name", "birth_year", "gender", "location")
_N_LEVELS = {"name": 4, "birth_year": 3, "gender": 2, "location": 3}
_SMOOTH = 1e-4


@dataclass
class _Rec:
    """One `Accused` row, as the ER stores it — plus where the crime happened.

    The ER gives us a name, a stated age and a gender, and nothing else about the human.
    There is no address, no ID number, no DOB. Location is the *case's* location, which is
    a real signal (offenders re-offend near where they operate) but a weak one, and it is
    weighted as such by EM rather than by us guessing.
    """
    accused_id: int
    case_id: int                 # two accused on the SAME case are different people
    name: str                    # the person's own name, as recorded
    patronym: str                # the father's name from the S/o / D/o form
    birth_year: int | None       # case year - stated age; NOT the stated age itself
    gender: int
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


def _agrees(x: str, y: str) -> bool:
    """Same name, allowing for romanisation drift."""
    if not x or not y:
        return False
    return _jaro_winkler(x, y) >= 0.92 or y in set(transliterate(x))


def _compare(a: _Rec, b: _Rec) -> tuple[int, ...]:
    """Agreement *level* per field (0 = strongest agreement).

    Name is compared *structurally* — own name and father's name as two assertions — and
    never as one concatenated string. An FIR records "Ramesh Gowda S/o Krishnappa", and
    running an edit-distance over that whole string lets the literal " S/o " that every
    record shares inflate the similarity of total strangers (measured: it put 1% of random
    pairs at full name agreement, which makes a name match nearly worthless as evidence).
    Splitting it restores the patronymic to what it is in real police work: the field that
    tells two men with the same common name apart.

    Kept as ONE field with four levels rather than two binary fields, because own-name and
    father's-name agreement are strongly dependent given a match — as two fields, FS's
    conditional-independence assumption would count the same evidence twice.
    """
    own, pat = _agrees(a.name, b.name), _agrees(a.patronym, b.patronym)
    if own and pat:
        name = 0                       # same man, same father
    elif own:
        name = 1                       # same name, different father — a namesake, usually
    elif _jaro_winkler(a.name, b.name) >= 0.85 and pat:
        name = 2                       # name drifted past recognition, but the father holds
    else:
        name = 3

    if a.birth_year and b.birth_year:
        gap = abs(a.birth_year - b.birth_year)
        birth_year = 0 if gap == 0 else (1 if gap <= 2 else 2)   # stated age is noisy
    else:
        birth_year = 2

    gender = 0 if a.gender == b.gender else 1

    dist = _haversine_km(a, b)
    if dist is None:
        location = 2
    elif dist <= 5.0:
        location = 0                   # same locality — offenders work a patch
    elif dist <= 50.0:
        location = 1                   # same broad area
    else:
        location = 2

    return (name, birth_year, gender, location)


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
    """u[field][level] = P(agreement level | NON-match).

    The pairs this is measured on decide whether the whole model works, and the obvious
    choice — random pairs — is wrong here in a way that is invisible until you measure it.

    Random pairs are NOT non-matches under this schema. One habitual offender contributes
    ~6 Accused rows, so ~1% of random pairs are the same man, and those pairs essentially
    always agree on name. Measured: u[name][strongest] came out at 0.0101 when the true
    false-agreement rate over 40,000 random pairs was exactly ZERO. That 50x inflation
    lands on the single most informative field and collapses its likelihood ratio, which
    is why linkage silently found almost nothing. (The previous version of this file
    assumed contamination was <0.02%, which was true when persons were their own table
    with a few percent duplicates. The ER has no person table, and the assumption broke.)

    So we do not guess at non-matches — we use pairs that CANNOT be matches. **Two accused
    on the same FIR are different people by construction**: they are A1 and A2 on one
    charge sheet. That is a zero-contamination non-match sample, handed to us by the
    domain.

    Location is the exception and must still come from random pairs: two co-accused were
    arrested for the *same crime at the same place*, so within-case pairs would put
    u[location] at certain agreement and destroy the field. Its residual contamination is
    harmless — location's m and u are close either way, so it was never carrying much.
    """
    by_case: dict[int, list[int]] = {}
    for i, r in enumerate(recs):
        by_case.setdefault(r.case_id, []).append(i)
    known_non_matches = [(a, b) for members in by_case.values() if len(members) > 1
                         for a, b in combinations(members, 2)]

    loc_i = _FIELDS.index("location")
    counts = [[0.0] * _N_LEVELS[f] for f in _FIELDS]

    # Identity fields, from pairs that are provably different people.
    if len(known_non_matches) >= 30:
        for a, b in known_non_matches:
            g = _compare(recs[a], recs[b])
            for fi in range(len(_FIELDS)):
                if fi != loc_i:
                    counts[fi][g[fi]] += 1
    else:                                      # too few co-accused to measure: fall back
        for _ in range(n_samples):
            a, b = rng.randrange(len(recs)), rng.randrange(len(recs))
            if a == b:
                continue
            g = _compare(recs[a], recs[b])
            for fi in range(len(_FIELDS)):
                if fi != loc_i:
                    counts[fi][g[fi]] += 1

    # Location, from random pairs — see the docstring.
    for _ in range(n_samples):
        a, b = rng.randrange(len(recs)), rng.randrange(len(recs))
        if a == b:
            continue
        counts[loc_i][_compare(recs[a], recs[b])[loc_i]] += 1

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

def _load() -> list[_Rec]:
    """Every Accused row, with the birth year its case implies and where the crime was."""
    rows = ds.query(
        'SELECT "Accused"."AccusedMasterID", "Accused"."CaseMasterID", '
        '       "Accused"."AccusedName", "Accused"."AgeYear", "Accused"."GenderID", '
        '       "CaseMaster"."latitude", "CaseMaster"."longitude", '
        '       "CaseMaster"."CrimeRegisteredDate" '
        'FROM "Accused" '
        'JOIN "CaseMaster" ON "Accused"."CaseMasterID" = "CaseMaster"."CaseMasterID"')
    recs = []
    for r in rows:
        year = _year_of(r.get("CrimeRegisteredDate"))
        age = r.get("AgeYear")
        name, patronym = split_name(r.get("AccusedName") or "")
        recs.append(_Rec(
            accused_id=int(r["AccusedMasterID"]),
            case_id=int(r["CaseMasterID"]),
            name=name, patronym=patronym,
            birth_year=(year - int(age)) if (year and age) else None,
            gender=int(r.get("GenderID") or 0),
            lat=r.get("latitude"), lng=r.get("longitude")))
    return recs


def split_name(recorded: str) -> tuple[str, str]:
    """"Ramesh Gowda S/o Krishnappa" -> ("Ramesh Gowda", "Krishnappa").

    Real FIRs are not consistent about this, so anything we do not recognise falls back to
    (whole string, "") rather than guessing — a wrong split is worse than no split.
    """
    for sep in (" S/o ", " D/o ", " s/o ", " d/o ", " S/O ", " D/O "):
        if sep in recorded:
            own, _, pat = recorded.partition(sep)
            return own.strip(), pat.strip()
    return recorded.strip(), ""


def _year_of(v: object) -> int | None:
    if v is None:
        return None
    if hasattr(v, "year"):
        return int(v.year)                      # date / datetime
    s = str(v)[:4]                              # sqlite and Data Store both hand back "YYYY-..."
    return int(s) if s.isdigit() else None


def _candidate_pairs(recs: list[_Rec]) -> set[tuple[int, int]]:
    """Block on the collapsed name key and on (gender, birth year) — a pair only needs to
    collide in one block to be scored. Keeps this far below O(n^2) while still catching
    variants whose age was misstated, and age-identical pairs whose names drifted past the
    key."""
    blocks: dict[tuple, list[int]] = {}
    for i, r in enumerate(recs):
        keys = [("name", _norm_key(r.name))]
        if r.birth_year:
            keys.append(("by", r.gender, r.birth_year))
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
    m, u, p = _em(gammas, u, _prior_match_prob(recs, gammas, u))

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
        results.append(MatchResult(person_id_a=str(recs[a].accused_id),
                                   person_id_b=str(recs[b].accused_id),
                                   decision=decision, confidence=round(conf, 4)))
    return results, links


def cluster(recs: list[_Rec], links: list[tuple[int, int]]) -> dict[int, int]:
    """Union-find the linked pairs into people. Returns accused_id -> PersonUID.

    Every Accused row gets a person, including singletons — a man seen once is still a
    man, and vx_person has to be total over the record layer or half the joins go empty.
    """
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

    # PersonUID is the cluster's lowest AccusedMasterID: stable across reruns, and
    # traceable back to the record it was derived from.
    return {recs[i].accused_id: recs[find(i)].accused_id for i in range(len(recs))}


def resolve_entities(_unused: list | None = None) -> list[MatchResult]:
    """Reconstruct people from Accused rows; write vx_person + vx_accused_identity.

    Batch pass, run by the generator after the record layer is loaded. Wipes and rebuilds
    both tables — they are derived data, and a stale identity is worse than no identity.
    """
    recs = _load()
    if len(recs) < 2:
        return []
    results, links = score_records(recs)
    uid_of = cluster(recs, links)
    conf_of = {int(r.person_id_a): r.confidence for r in results if r.decision == "link"}
    by_id = {r.accused_id: r for r in recs}

    ds.truncate(["vx_person", "vx_accused_identity"])
    people = []
    for uid in sorted(set(uid_of.values())):
        r = by_id[uid]
        people.append({
            "PersonUID": uid, "CanonicalName": r.name, "NameKn": None,
            "DOB": f"{r.birth_year}-01-01" if r.birth_year else None,
            "GenderID": r.gender, "RiskScore": None,
            "IsHabitualOffender": sum(1 for v in uid_of.values() if v == uid) > 2,
            "GangAffiliation": None})
    ds.insert("vx_person", people)
    ds.insert("vx_accused_identity", [
        {"AccusedMasterID": aid, "PersonUID": uid,
         "MatchConfidence": 1.0 if aid == uid else conf_of.get(aid, LINK_THRESHOLD)}
        for aid, uid in sorted(uid_of.items())])
    return results


if __name__ == "__main__":
    # Score the reconstruction against the generator's answer key. This is the only test
    # that matters for this module: not "does it run" but "does it find the same people".
    import random as _r

    from data.generator.build import generate
    from data.generator.load import load_dataset

    ds.reset_for_tests()
    dataset = generate(_r.Random(7), 600)
    load_dataset(dataset)
    resolve_entities()

    truth = dataset.accused_truth                       # AccusedMasterID -> TruePerson.uid
    got = {int(r["AccusedMasterID"]): int(r["PersonUID"])
           for r in ds.query('SELECT "AccusedMasterID", "PersonUID" FROM "vx_accused_identity"')}
    assert set(got) == set(truth), "vx_accused_identity must cover every Accused row"

    # Pairwise precision/recall over co-reference decisions, which is how record linkage
    # is actually evaluated — cluster ids are arbitrary, the partition is what's judged.
    ids = sorted(truth)
    tp = fp = fn = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            same_true = truth[a] == truth[b]
            same_got = got[a] == got[b]
            tp += same_true and same_got
            fp += (not same_true) and same_got
            fn += same_true and not same_got
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    people = ds.scalar('SELECT COUNT("PersonUID") AS c FROM "vx_person"')
    print(f"entity resolution: {len(truth)} accused rows -> {people} people "
          f"(truth: {len(set(truth.values()))}) | "
          f"precision={precision:.3f} recall={recall:.3f} f1={f1:.3f}")
    # A linkage that links nothing has perfect precision, and a linkage that links
    # everything has perfect recall. Both must hold, or the reconstruction is worthless.
    assert precision >= 0.80, f"too many false links: precision={precision:.3f}"
    assert recall >= 0.50, f"missing most true links: recall={recall:.3f}"
