"""Investigation Copilot — the "I'd use this Monday morning" feature.

Given an open case: a chronological timeline, the top-5 similar past cases with their
outcomes, ranked investigative leads, and a paste-ready case-diary paragraph.

Policy is enforced INSIDE this, not on its output: `officer_role` caps the graph traversal
and masks victim-identifying fields *before* they reach `_draft_summary`. Redacting a name
out of already-generated prose is not something you can do reliably, so the prose is never
allowed to contain it.

Similarity is over the case narrative. The organizers' ER has no modus-operandi column —
the method is stated inside `BriefFacts` — so MO similarity *is* narrative similarity, and a
separate MO index would have been two names for one thing.
"""
from data import ds, queries
from data.vectors import hybrid_search
from policy import can_view_fir, mask_person_fields, mask_person_name, max_traversal_depth

from ..agents.sql_agent import fir_by_id
from ..llm import available, generate
from ..state import CopilotBrief


class NotPermitted(PermissionError):
    """The case exists, but not within this officer's station scope."""


def _case(fir_id: str) -> dict | None:
    """Unscoped read. The policy check is applied by generate_copilot_brief, immediately
    below, so that a case outside the officer's scope is refused as 403 rather than
    reported as nonexistent — exactly what GET /fir/{id} does."""
    rows = fir_by_id(fir_id, "SHO", "")
    return rows[0] if rows else None


def _accused_on_case(fir_id: str) -> list[dict]:
    """The people accused on this case, resolved to their cross-case identity."""
    return ds.query(
        'SELECT "vx_person"."PersonUID", "vx_person"."CanonicalName", '
        '       "vx_person"."CommunityID", "vx_person"."GangAffiliation", '
        '       "vx_person"."PageRank", "Accused"."AccusedName" '
        'FROM "Accused" '
        'JOIN "vx_accused_identity" '
        '  ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID" '
        'JOIN "vx_person" '
        '  ON "vx_accused_identity"."PersonUID" = "vx_person"."PersonUID" '
        'WHERE "Accused"."CaseMasterID" = :cid', {"cid": int(fir_id)})


def _timeline(fir_id: str, case: dict, officer_role: str) -> list[dict]:
    filed = ds.to_dt(case["date_filed"])
    events: list[dict] = []
    if filed:
        events.append({"date": str(filed.date()),
                       "event": f"FIR {case['fir_number']} registered at "
                                f"{case.get('ps_name') or case['ps_code']}"})

    arrests = ds.query(
        'SELECT "ArrestSurrender"."ArrestSurrenderDate", '
        '       "ArrestSurrender"."ArrestSurrenderTypeID", "Accused"."AccusedName" '
        'FROM "ArrestSurrender" '
        'JOIN "Accused" '
        '  ON "ArrestSurrender"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        'WHERE "ArrestSurrender"."CaseMasterID" = :cid', {"cid": int(fir_id)})
    for a in arrests:
        d = ds.to_dt(a["ArrestSurrenderDate"])
        if not d:
            continue
        kind = "surrendered" if a["ArrestSurrenderTypeID"] == 2 else "arrested"
        who = mask_person_name(officer_role, a["AccusedName"])
        events.append({"date": str(d.date()), "event": f"{who} {kind}"})

    for cs in ds.query('SELECT "csdate", "cstype" FROM "ChargesheetDetails" '
                       'WHERE "CaseMasterID" = :cid', {"cid": int(fir_id)}):
        d = ds.to_dt(cs["csdate"])
        if not d:
            continue
        label = {"A": "Chargesheet filed", "B": "Closed as false",
                 "C": "Closed as undetected"}.get(cs["cstype"], "Final report filed")
        events.append({"date": str(d.date()), "event": label})

    return sorted(events, key=lambda e: e["date"])


def _similar_cases(case: dict, limit: int = 5) -> list[dict]:
    """Narrative similarity over the vector index, each with its recorded outcome."""
    probe = f"{case.get('crime_type') or ''}. {case.get('narrative') or ''}"
    hits = hybrid_search(probe, collection="fir_narrative", k=limit + 1)
    ids = [h["source_id"] for h in hits if h["source_id"] != str(case["fir_id"])][:limit]
    if not ids:
        return []

    scores = {h["source_id"]: h["score"] for h in hits}
    out = []
    for cid in ids:
        rows = fir_by_id(cid, "SHO", "")
        if not rows:
            continue
        r = rows[0]
        out.append({**r, "outcome": r["case_status"],
                    "similarity": round(scores.get(cid, 0.0), 3)})
    return out


def _leads(fir_id: str, officer_role: str) -> list[str]:
    """Investigative leads for the accused on this case.

    DIRECT co-accused only — deliberately. At the 4-hop policy cap this would name most of
    the connected component ("857 associates"), which is true and useless: you cannot canvass
    857 people. A lead has to be actionable this week, so it names the people who actually
    offended alongside them. The depth cap is still read, because it is the ceiling this
    query is allowed to reach even if we choose to stop short of it.
    """
    from data.graph import load_graph

    max_traversal_depth(officer_role)          # policy ceiling; this query stays inside it
    accused = _accused_on_case(fir_id)
    if not accused:
        return []

    g = load_graph()
    leads: list[str] = []
    for a in accused:
        node = f"person:{a['PersonUID']}"
        associates = ([dst for _, dst, d in g.out_edges(node, data=True)
                       if d["rel"] == "CO_ACCUSED_WITH"] if node in g else [])
        name = mask_person_name(officer_role, a["CanonicalName"] or a["AccusedName"])
        pagerank = float(a["PageRank"] or 0.0)

        if associates:
            names = _names_of([n.split(":", 1)[1] for n in associates[:3]])
            named = ", ".join(x for x in (mask_person_name(officer_role, n)
                                          for n in names if n) if x)
            leads.append(f"{name} has {len(set(associates))} direct co-accused "
                         f"associate(s) — start with {named}.")
        if a["CommunityID"] is not None:
            leads.append(f"{name} belongs to network community {a['CommunityID']} — review "
                         f"other members for a linked series.")
        if pagerank > 0 and pagerank * 1000 > 1.0:
            leads.append(f"{name} ranks high for network influence "
                         f"(PageRank {pagerank:.4f}) — likely an organiser, not a runner.")

        priors = len(queries.cases_for_person(a["PersonUID"]))
        if priors > 1:
            leads.append(f"{name} appears in {priors} cases in total — pull the prior files "
                         f"before the next interview.")
    return leads[:6]


def _names_of(person_uids: list[str]) -> list[str]:
    if not person_uids:
        return []
    rows = ds.query('SELECT "CanonicalName" FROM "vx_person" WHERE "PersonUID" IN :ids',
                    {"ids": [int(p) for p in person_uids]})
    return [r["CanonicalName"] for r in rows if r["CanonicalName"]]


def _draft_summary(case: dict, timeline: list[dict], similar: list[dict],
                   officer_role: str) -> str:
    # Mask BEFORE generation. Post-hoc redaction of generated prose is unreliable.
    safe = mask_person_fields(officer_role, dict(case))
    convicted = sum(1 for s in similar if s["outcome"] == "Convicted")
    filed = ds.to_dt(safe.get("date_filed"))

    facts = (
        f"FIR {safe['fir_number']}, {safe.get('crime_type') or 'offence'}, registered at "
        f"{safe.get('ps_name') or safe['ps_code']} ({safe.get('district')}) on "
        f"{filed:%d %b %Y}. " if filed else
        f"FIR {safe['fir_number']}, {safe.get('crime_type') or 'offence'}, registered at "
        f"{safe.get('ps_name') or safe['ps_code']} ({safe.get('district')}). ")
    facts += (
        f"Current status: {safe.get('case_status')}. "
        f"{len(timeline)} recorded events in the case timeline. "
        f"{len(similar)} past cases share this pattern; {convicted} ended in conviction."
    )

    if available():
        try:
            out = generate(
                f"Write one paste-ready case-diary paragraph for an Investigating Officer, "
                f"using only these facts:\n{facts}\n"
                f"Formal Indian police register style. No speculation about guilt.",
                system="You draft factual case-diary entries. Never invent details.",
            )
            if out:
                return out
        except Exception:
            pass
    return facts


def generate_copilot_brief(fir_id: str, officer_role: str,
                           officer_ps_code: str = "") -> CopilotBrief:
    case = _case(fir_id)
    if not case:
        raise KeyError(f"Case {fir_id} not found")

    # The station rule is enforced HERE, not only at the router, because this function is
    # the thing that reads the case. It previously read with a hardcoded ("SHO", "") scope
    # on the argument that "the copilot is opened from a case the officer already has in
    # hand" — but fir_id arrives from the URL, so an IO could read any station's brief
    # (names, associates, leads) through /copilot after being refused the same case by
    # /fir. One endpoint enforcing a rule its neighbour does not is not a rule.
    if not can_view_fir(officer_role, officer_ps_code, case["ps_code"]):
        raise NotPermitted(f"Case {fir_id} was filed at another police station")

    timeline = _timeline(fir_id, case, officer_role)
    similar = _similar_cases(case)
    leads = _leads(fir_id, officer_role)
    return CopilotBrief(
        fir_id=fir_id,
        timeline=timeline,
        similar_cases=similar,
        leads=leads,
        draft_summary=_draft_summary(case, timeline, similar, officer_role),
    )
