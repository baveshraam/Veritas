"""Investigation Copilot — the "I'd use this Monday morning" feature.

Given an open FIR: a chronological timeline, the top-5 MO-similar past cases with
their outcomes, ranked investigative leads, and a paste-ready case-diary paragraph.

Policy is enforced INSIDE this, not on its output: `officer_role` caps the graph
traversal depth and masks victim-identifying fields *before* they reach
`draft_summary`. Redacting a name out of already-generated prose is not something
you can do reliably, so the prose is never allowed to contain it.
"""
from datetime import date

from data.db import get_session
from data.vectors import hybrid_search
from policy import mask_person_fields, max_traversal_depth
from sqlalchemy import text

from ..llm import available, generate
from ..state import CopilotBrief


def _fir(fir_id: str) -> dict | None:
    with get_session() as s:
        r = s.execute(text(
            "SELECT fir_id, fir_number, crime_type, ipc_sections, date_filed, "
            "       occurrence_from, district, taluk, ps_code, case_status, "
            "       modus_operandi, narrative "
            "FROM fir WHERE fir_id = CAST(:f AS uuid)"), {"f": fir_id}).mappings().first()
    return dict(r) if r else None


def _timeline(fir_id: str, fir: dict) -> list[dict]:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT p.person_id, p.name_en, cr.role, cr.arrest_date, cr.bail_status, "
            "       cr.conviction "
            "FROM criminal_record cr JOIN person p ON p.person_id = cr.person_id "
            "WHERE cr.fir_id = CAST(:f AS uuid)"), {"f": fir_id}).mappings().all()

    events: list[dict] = []
    if fir.get("occurrence_from"):
        events.append({"date": str(fir["occurrence_from"].date()),
                       "event": f"Offence occurred ({fir['crime_type']})"})
    events.append({"date": str(fir["date_filed"].date()),
                   "event": f"FIR {fir['fir_number']} registered at {fir['ps_code']}"})
    for r in rows:
        if r["arrest_date"]:
            events.append({"date": str(r["arrest_date"]),
                           "event": f"{r['name_en']} arrested ({r['role']})"})
        if r["bail_status"] and r["bail_status"] != "Not Applied":
            events.append({"date": str(r["arrest_date"] or fir["date_filed"].date()),
                           "event": f"{r['name_en']} — bail {r['bail_status'].lower()}"})
        if r["conviction"]:
            events.append({"date": str(fir["date_filed"].date()),
                           "event": f"{r['name_en']} convicted"})
    return sorted(events, key=lambda e: e["date"])


def _similar_cases(fir: dict, limit: int = 5) -> list[dict]:
    """MO-similarity over the vector store, each with its recorded outcome."""
    probe = f"{fir['crime_type']}. {fir.get('modus_operandi') or ''}"
    hits = hybrid_search(probe, collection="mo", k=limit + 1)
    ids = [h["source_id"] for h in hits if h["source_id"] != str(fir["fir_id"])][:limit]
    if not ids:
        return []
    with get_session() as s:
        rows = s.execute(text(
            "SELECT fir_id, fir_number, crime_type, district, case_status, "
            "       modus_operandi, date_filed "
            "FROM fir WHERE fir_id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids}).mappings().all()
    scores = {h["source_id"]: h["score"] for h in hits}
    return [{**dict(r),
             "fir_id": str(r["fir_id"]),
             "date_filed": str(r["date_filed"].date()),
             "outcome": r["case_status"],
             "similarity": round(scores.get(str(r["fir_id"]), 0.0), 3)} for r in rows]


def _leads(fir_id: str, officer_role: str) -> list[str]:
    from data.graph import get_driver

    depth = max_traversal_depth(officer_role)
    with get_driver().session() as g:
        rows = g.run(
            "MATCH (c:CrimeEvent {fir_id: $f})<-[:ACCUSED_IN]-(p:Person) "
            # DIRECT co-accused only. At the 4-hop policy cap this counts most of the
            # connected component ("857 associates"), which is true and useless — you
            # cannot canvass 857 people. A lead has to be something an IO can act on
            # this week, so it names the people who actually offended alongside them.
            "OPTIONAL MATCH (p)-[:CO_ACCUSED_WITH]-(o:Person) "
            "RETURN p.name_en AS name, p.community AS community, "
            "  p.gang_affiliation AS gang, coalesce(p.pagerank,0.0) AS pagerank, "
            "  count(DISTINCT o) AS direct_associates, "
            "  collect(DISTINCT o.name_en)[..3] AS names", f=fir_id).data()

    leads: list[str] = []
    for r in rows:
        if r["direct_associates"]:
            named = ", ".join(n for n in r["names"] if n)
            leads.append(f"{r['name']} has {r['direct_associates']} direct co-accused "
                         f"associate(s) — start with {named}.")
        if r["gang"]:
            leads.append(f"{r['name']} is affiliated with {r['gang']}; check that gang's "
                         f"recent activity in adjoining districts.")
        if r["community"] is not None:
            leads.append(f"{r['name']} belongs to network community {r['community']} — "
                         f"review other members for a linked series.")
        if r["pagerank"] and r["pagerank"] > 1.0:
            leads.append(f"{r['name']} ranks high for network influence "
                         f"(PageRank {r['pagerank']:.2f}) — likely an organiser, not a runner.")
    return leads[:6]


def _draft_summary(fir: dict, timeline: list[dict], similar: list[dict],
                   officer_role: str) -> str:
    # Mask BEFORE generation. Post-hoc redaction of generated prose is unreliable.
    safe = mask_person_fields(officer_role, dict(fir))
    convicted = sum(1 for s in similar if s["outcome"] == "Convicted")

    facts = (
        f"FIR {safe['fir_number']}, {safe['crime_type']} under IPC "
        f"{', '.join(safe.get('ipc_sections') or [])}, registered at {safe['ps_code']} "
        f"({safe['district']}) on {safe['date_filed']:%d %b %Y}. "
        f"Current status: {safe['case_status']}. "
        f"Modus operandi: {safe.get('modus_operandi') or 'not recorded'}. "
        f"{len(timeline)} recorded events in the case timeline. "
        f"{len(similar)} past cases share this MO; {convicted} ended in conviction."
    )

    if available():
        try:
            out = generate(
                f"Write one paste-ready case-diary paragraph for an Investigating "
                f"Officer, using only these facts:\n{facts}\n"
                f"Formal Indian police register style. No speculation about guilt.",
                system="You draft factual case-diary entries. Never invent details.",
            )
            if out:
                return out
        except Exception:
            pass
    return facts


def generate_copilot_brief(fir_id: str, officer_role: str) -> CopilotBrief:
    fir = _fir(fir_id)
    if not fir:
        raise KeyError(f"FIR {fir_id} not found")

    timeline = _timeline(fir_id, fir)
    similar = _similar_cases(fir)
    leads = _leads(fir_id, officer_role)
    return CopilotBrief(
        fir_id=fir_id,
        timeline=timeline,
        similar_cases=similar,
        leads=leads,
        draft_summary=_draft_summary(fir, timeline, similar, officer_role),
    )
