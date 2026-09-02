"""GET /analytics/* — the workspace's analytical tabs, read straight from the records.

WHY THIS EXISTS, given that /chat can already answer all of it.

Every one of these views used to be filled by the console firing a canned English
question ("Show me crime hotspots") through the LangGraph orchestrator and reading the
answer's evidence items back out. That is the right mechanism for a QUESTION and the
wrong one for a TAB, for three reasons that are properties of the design rather than
bugs in it:

  * a turn's evidence is the LAST turn's evidence — so opening a second tab destroyed
    the first one's contents, and returning to it showed an empty view;
  * the preload appeared in the officer's own transcript and evidence column, so the
    console showed questions nobody asked and citations for them;
  * an intent classification, a retrieval pass and a CRAG evaluation are real work, and
    none of it is needed to answer "count these rows" — which is all a tab is.

So each endpoint calls exactly the same policy-scoped function the corresponding
orchestrator handler calls (`sql_agent.ranked_offenders`, `status_breakdown`,
`flagged_transactions`, `station_workload`, `prediction_agent.hotspots`, ...) and returns
the STRUCTURED rows instead of sentences built from them. The conversational path is
untouched and still authoritative for anything with a subject in it: ask about hotspots
in Mandya and the chat answer, with its citations, still drives the same view.

RBAC is the officer's own role and station passed into those same functions — the
filter is inside the query, exactly as it is for /chat. There is no wider scope here.
"""
from fastapi import APIRouter, Depends
from policy import mask_person_name
from rag_agent.agents import prediction_agent, sql_agent

from ..auth.jwt_auth import Officer, current_officer

router = APIRouter(prefix="/analytics")


def _code(district: str | None) -> str | None:
    """A district name -> its KAnn code, defaulting to the busiest district in the
    data. Same fallback the orchestrator's `_district_code` makes for a question that
    names no district: a statewide KDE surface is not something the model produces, so
    something has to be chosen, and "where the most cases are" is the defensible one.
    """
    from data.districts import canonical_code

    if district:
        return canonical_code(district)
    top = sql_agent.crime_counts_by_district(limit=1)
    return top[0]["district_code"] if top else None


@router.get("/statistics")
async def statistics(district: str | None = None, crime_type: str | None = None,
                     officer: Officer = Depends(current_officer)):
    """Every count the dashboard draws, from one scan (`sql_agent.dashboard`)."""
    return sql_agent.dashboard(officer.role, officer.ps_code,
                               district=district, crime_type=crime_type)


@router.get("/offenders")
async def offenders(district: str | None = None, crime_type: str | None = None,
                    habitual: bool = False, limit: int = 20, q: str | None = None,
                    officer: Officer = Depends(current_officer)):
    """Ranked by RECORDED CASE COUNT — never PageRank, never a risk score. Same rule,
    and the same function, as the OFFENDER_RANKING intent.

    `q` searches by name over every offender in scope, not just the top-ranked page —
    most people are outside the top 20 by case count, and that must not mean
    unfindable."""
    people = sql_agent.ranked_offenders(officer.role, officer.ps_code, district=district,
                                        crime_type=crime_type, habitual_only=habitual,
                                        limit=min(limit, 100), q=q)
    return {"scope": {"district": district, "crime_type": crime_type,
                      "habitual_only": habitual, "q": q},
            "offenders": [{**p, "name": mask_person_name(officer.role, p["name"])}
                          for p in people]}


@router.get("/hotspots")
async def hotspots(district: str | None = None,
                   officer: Officer = Depends(current_officer)):
    """KDE + DBSCAN clusters plus the incident scatter underneath them — the same two
    calls, in the same order, that the HOTSPOT intent makes, returned as the map payload
    the console's MapView already renders. A hull with no points beneath it is an
    assertion rather than a hotspot, which is why both halves are always sent."""
    dc = _code(district)
    if not dc:
        return {"district": None, "district_code": None, "polygons": [], "fir_points": []}
    from data.districts import canonical_name

    polys, _ = prediction_agent.hotspots(dc)
    return {
        "district": canonical_name(dc), "district_code": dc,
        "polygons": [h.model_dump() if hasattr(h, "model_dump") else h for h in polys],
        "fir_points": sql_agent.fir_points(dc),
    }


@router.get("/forecast")
async def forecast(district: str | None = None, horizon: int = 30,
                   officer: Officer = Depends(current_officer)):
    """Prophet + MinT, as a series. A projection, never a record — the console draws it
    on the MODEL provenance channel for exactly that reason."""
    dc = _code(district)
    if not dc:
        return {"district": None, "district_code": None, "series": [], "reconciled": False}
    from data.districts import canonical_name

    fc, _ = prediction_agent.forecast(dc, horizon)
    return {"district": canonical_name(dc), "district_code": dc,
            "reconciled": bool(getattr(fc, "reconciled", False)),
            "series": [[str(d), p, lo, hi] for d, p, lo, hi in fc.series]}


@router.get("/area")
async def area(district: str | None = None,
               officer: Officer = Depends(current_officer)):
    """The recorded offence mix beside real Census 2011 ground truth for the same
    district — side by side, never combined into one score (CLAUDE.md §9)."""
    from data.districts import canonical_name

    name = district or canonical_name(_code(None) or "")
    if not name:
        return {"district": None, "total": 0, "mix": [], "status": [], "census": None}
    mix = sql_agent.counts_by(officer.role, officer.ps_code, "crime_type", district=name)
    status = sql_agent.status_breakdown(officer.role, officer.ps_code, district=name)
    return {
        "district": name,
        "total": sum(n for _, n in mix),
        "mix": [{"name": k, "cases": v} for k, v in mix],
        "status": [{"name": k, "cases": v}
                   for k, v in sorted(status.items(), key=lambda kv: -kv[1])],
        "census": sql_agent.district_socioeconomic(name),
    }


def _largest_community() -> int | None:
    """The community with the most members. A tab has to show something, and the
    biggest group is the one defensible pick when no person is in focus."""
    from data import ds

    rows = ds.query('SELECT "CommunityID" FROM "vx_person" WHERE "CommunityID" IS NOT NULL')
    counts: dict[int, int] = {}
    for r in rows:
        counts[int(r["CommunityID"])] = counts.get(int(r["CommunityID"]), 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else None


@router.get("/community")
async def community(id: int | None = None, person_id: str | None = None,
                    officer: Officer = Depends(current_officer)):
    """A Louvain community as a group object. Named "community", never "gang": the ER
    records no gang, and membership is derived by the graph rather than stated by any
    record. Ranked by network influence — a graph-position fact, not a threat score."""
    from data.gds import community_members

    cid = id
    if cid is None and person_id:
        cid = sql_agent.person_community(person_id)
    if cid is None:
        cid = _largest_community()
    if cid is None:
        return {"community_id": None, "members": [], "profile": None, "defaulted": True}
    members = community_members(cid, limit=25)
    profile = sql_agent.community_case_profile(
        [str(m["PersonUID"]) for m in members], officer.role, officer.ps_code)
    return {
        "community_id": cid, "profile": profile,
        "defaulted": id is None and person_id is None,
        "members": [{"person_id": str(m["PersonUID"]),
                     "name": mask_person_name(officer.role, m["CanonicalName"]),
                     "influence": float(m["PageRank"] or 0.0)} for m in members],
    }


@router.get("/watchlist")
async def watchlist(limit: int = 25, officer: Officer = Depends(current_officer)):
    """Flagged transactions, each labelled by WHICH detector flagged it: the rule-based
    structuring detector is court-auditable, the GNN is an investigative lead only.
    Collapsing the two would erase the thing that makes the list trustworthy rather
    than merely alarming (CLAUDE.md §6)."""
    rows = sql_agent.flagged_transactions(officer.role, officer.ps_code,
                                          limit=min(limit, 100))
    out = []
    for t in rows:
        gnn = "gnn" in (t.get("Detector") or "").lower()
        out.append({
            "txn_id": str(t["TxnID"]), "src": str(t["SrcAccountID"]),
            "dst": str(t["DstAccountID"]), "amount": float(t.get("Amount") or 0),
            "date": t.get("TxnDate"),
            "fir_id": str(t["CaseMasterID"]) if t.get("CaseMasterID") else None,
            "flag_type": t.get("FlagType") or "suspicious",
            "detector": "gnn" if gnn else "rule",
            "confidence": float(t.get("FlagConfidence") or 0),
        })
    return {"total": len(out),
            "rule": sum(1 for t in out if t["detector"] == "rule"),
            "gnn": sum(1 for t in out if t["detector"] == "gnn"),
            "transactions": out}


@router.get("/workload")
async def workload(officer: Officer = Depends(current_officer)):
    """Open caseload per station and how much of it has gone stale. Says where to look;
    never allocates anything."""
    stations = sql_agent.station_workload(officer.role, officer.ps_code)
    return {"stale_days": sql_agent.STALE_DAYS,
            "open_cases": sum(s["open_cases"] for s in stations),
            "stalled": sum(s["stalled_count"] for s in stations),
            "stations": stations}
