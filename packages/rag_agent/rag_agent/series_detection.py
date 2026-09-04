"""Cross-case series discovery — the capability FBI ViCAP has needed since 1985 and
still names as its own weakness: reliance on manual entry, requiring a trained analyst
to notice that crimes in different jurisdictions share a pattern. The academic name for
this is Comparative Case Analysis (Burrell & Bull): identifying DISTINCTIVE but
consistent behaviour across crimes to decide whether the same actor is behind them.

This is deliberately NOT a new similarity engine. `copilot.brief.similar_cases_for`
already does the real work — structured overlap (crime type, shared act sections,
district, and a direct match on the case-specific MO clause) ranked ahead of the raw
narrative-embedding score, exactly what CCA theory says is diagnostic ("pickpocketing
in a crowded market" is common; a shared exact MO clause plus shared sections is not).

What is new here is the layer CROSS_STATION_LINKAGE and SIMILAR_CASES don't provide:
- restricted to candidates from a DIFFERENT police station (the linkage-blindness
  case — an officer already sees their own station's cases; the value is in the ones
  nobody would otherwise cross-reference);
- excludes any candidate that ALREADY shares a resolved accused with the anchor case
  (that overlap is CROSS_STATION_LINKAGE's job; a series is interesting precisely
  because nobody has been named yet);
- requires a MINIMUM cluster size before calling it a series at all — one matching
  case elsewhere is coincidence, not a pattern, and CCA's own literature is explicit
  that a pattern claim needs multiple corroborating instances.
"""
from datetime import datetime, timedelta

from data import ds
from pydantic import BaseModel, Field

from .agents import sql_agent
from .copilot import brief as copilot_brief

# A candidate needs at least this many independently-matched structural features
# (crime type + shared sections + district + exact MO clause, from
# copilot_brief._explain_similarity) to count as more than "same crime type" — the
# exact bar §1.5 of docs/CAPABILITY_TARGET_AND_GAPS.md named as the difference between
# genuine MO-based linkage and "same crime type, same district" wearing its label.
MIN_MATCH_STRENGTH = 2

# Not sufficient on its own: several crime types have a fixed, narrow section
# vocabulary (Criminal Breach of Trust cites only 406/409, Robbery only 392/394 —
# see data/data/seed/derived/crime_types.csv), so EVERY case of that type shares
# BOTH sections with every other case of the same type, and "same crime type" +
# "shares sections" alone already clears MIN_MATCH_STRENGTH for pairs that have
# nothing genuinely distinctive in common — caught by this module's own test suite
# finding real unrelated cases in the ambient dataset satisfying the count alone.
# Comparative Case Analysis is explicit that a link needs DISTINCTIVE, not merely
# consistent, behaviour (Burrell & Bull) — the exact MO-clause match is the one
# signal in _explain_similarity's output that is actually distinctive, so it is
# required outright, not just counted alongside the others.
_MO_MATCH_PREFIX = "matching modus operandi"


def _has_distinctive_match(matched_features: list[str]) -> bool:
    return any(f.startswith(_MO_MATCH_PREFIX) for f in matched_features)

# Below this many total cases (the anchor plus its matches), this is a coincidence, not
# a series — CCA's own principle: a pattern claim rests on multiple corroborating
# instances, not one lucky match.
MIN_CLUSTER_SIZE = 3

MAX_CANDIDATES = 8


class SeriesMember(BaseModel):
    fir_id: str
    fir_number: str
    ps_code: str
    ps_name: str | None = None
    district: str | None = None
    date_filed: str | None = None
    case_status: str | None = None
    matched_features: list[str] = Field(default_factory=list)
    similarity: float = 0.0


class SeriesResult(BaseModel):
    anchor_fir_id: str
    anchor_ps_code: str      # so a caller (e.g. GET /alerts) can can_view_fir the
                             # anchor itself before deciding whether to surface this
                             # to a given officer at all
    members: list[SeriesMember]
    stations: list[str]
    districts: list[str]


def _shared_known_accused(fir_id_a: str, fir_id_b: str) -> bool:
    a = {r["PersonUID"] for r in sql_agent.accused_on_case(fir_id_a)}
    if not a:
        return False
    b = {r["PersonUID"] for r in sql_agent.accused_on_case(fir_id_b)}
    return bool(a & b)


def find_series(anchor_case: dict, *, min_cluster: int = MIN_CLUSTER_SIZE,
                max_candidates: int = MAX_CANDIDATES) -> SeriesResult | None:
    """Given an already-fetched case (the shape `sql_agent._case` produces), look for
    a genuine cross-station pattern. Returns None when the evidence doesn't clear the
    bar — a missing series is a correct, common answer, not a failure.

    Every candidate returned here is UNSCOPED (`similar_cases_for` reads without a
    station filter, the same discipline `sql_agent.accused_on_case` documents) —
    callers must apply `policy.can_view_fir` per member before naming a case outside
    the officer's own scope, exactly as `CROSS_STATION_LINKAGE` already does for the
    identical partial-visibility situation.
    """
    anchor_id = str(anchor_case["fir_id"])
    anchor_ps = anchor_case.get("ps_code")

    pool = copilot_brief.similar_cases_for(anchor_case, limit=max(max_candidates * 4, 20))

    members: list[SeriesMember] = []
    for c in pool:
        features = c.get("matched_features") or []
        if c.get("ps_code") == anchor_ps:
            continue                                   # same station: not a blind spot
        if c.get("match_strength", 0) < MIN_MATCH_STRENGTH:
            continue                                   # too weak to call a pattern
        if not _has_distinctive_match(features):
            continue                                   # consistent, but not distinctive
        if _shared_known_accused(anchor_id, str(c["fir_id"])):
            continue                                   # already linked by identity
        date_filed = c.get("date_filed")
        members.append(SeriesMember(
            fir_id=str(c["fir_id"]), fir_number=c.get("fir_number") or "",
            ps_code=c.get("ps_code") or "", ps_name=c.get("ps_name"),
            district=c.get("district"), date_filed=str(date_filed) if date_filed else None,
            case_status=c.get("case_status"),
            matched_features=c.get("matched_features") or [],
            similarity=float(c.get("similarity") or 0.0)))
        if len(members) >= max_candidates:
            break

    if len(members) + 1 < min_cluster:                 # +1 for the anchor itself
        return None

    stations = sorted({m.ps_name or m.ps_code for m in members} |
                      {anchor_case.get("ps_name") or anchor_ps or ""})
    districts = sorted({m.district for m in members if m.district} |
                       ({anchor_case.get("district")} if anchor_case.get("district") else set()))
    return SeriesResult(anchor_fir_id=anchor_id, anchor_ps_code=anchor_ps or "",
                        members=members, stations=[s for s in stations if s],
                        districts=districts)


def scan_for_new_series(days: int = 14, min_cluster: int = MIN_CLUSTER_SIZE) -> list[SeriesResult]:
    """Cases filed in the last `days`, checked for a cross-station series. This is
    what makes the capability PROACTIVE rather than something an officer has to think
    to ask about — the same "unprompted" property the Isolation Forest district-spike
    alerts already have (ml_models.risk.anomalies), applied to case-level pattern
    discovery instead of a district-level count.

    Bounded to recently-filed cases on purpose, not to "cases with no accused yet" —
    Fellegi-Sunter resolves every Accused row to SOME person, including a one-off
    singleton (see fellegi_sunter.cluster's own docstring), so "has a resolved
    accused" is true of nearly every case and is not the signal that matters here.
    What matters — whether THIS case already shares a KNOWN accused with a specific
    candidate — is a pairwise question, checked inside find_series itself
    (_shared_known_accused). Bounding by recency instead keeps the scan cheap: an
    older case was either never part of an open series or has already been surfaced,
    and re-checking the full 10,000-case dataset on every alert poll would be real,
    needless compute for no new information.
    """
    cutoff = (datetime.now() - timedelta(days=days)).date()
    recent = ds.query(
        'SELECT "CaseMasterID" FROM "CaseMaster" WHERE "CrimeRegisteredDate" >= :cutoff',
        {"cutoff": cutoff})

    out: list[SeriesResult] = []
    for r in recent:
        fir_id = str(r["CaseMasterID"])
        case_rows = sql_agent.fir_by_id(fir_id, "SHO", "")
        if not case_rows:
            continue
        result = find_series(case_rows[0], min_cluster=min_cluster)
        if result:
            out.append(result)
    return out
