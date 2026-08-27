"""Cross-entity investigation timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 3).

One chronological event list spanning everything the record layer already knows how
to date: case registration/disposition, per-accused arrest/surrender, an accused
person's OTHER cases, and money moving through any account an accused person owns.
No new table, no invented timestamp, no fabricated relationship — every event's date
comes straight off a real ER/vx_ column (`CaseMaster.CrimeRegisteredDate`,
`ArrestSurrender.ArrestSurrenderDate`, `ChargesheetDetails.csdate`, the TRANSFERRED_TO
edge's own `date` prop — see data/generator/graph_sync.py) or off `vx_txn`/graph
structure the system already builds.

Every event carries a `kind`: "authoritative" for a directly stated ER/vx_ fact, or
"derived" for a relationship this code itself inferred — currently just one case: a
person's OTHER cases are linked only by Fellegi-Sunter's probabilistic identity match
(§0 of CLAUDE.md), not a directly stated fact, so those events are labelled as such
and carry the match confidence that produced them. `connection_between` applies the
same discipline to "why are these connected": a direct graph/ER fact (shared case,
CO_ACCUSED_WITH, a transaction between owned accounts) is reported as a real
connection; two events merely falling near each other in time is explicitly NOT
reported as one.
"""
from __future__ import annotations

from typing import Optional

from data import ds, queries
from data.graph import load_graph
from policy import can_view_fir, mask_person_name

from .agents.graph_agent import owned_accounts
from .agents.sql_agent import accused_on_case, cases_by_ids, fir_by_id
from .copilot.brief import NotPermitted

__all__ = ["NotPermitted", "case_timeline", "person_timeline", "connection_between"]

_RELATED_CASE_LIMIT = 5


def _event(dt, entity_type: str, entity_id, entity_name: Optional[str], event_type: str,
          description: str, kind: str = "authoritative",
          ref_type: Optional[str] = None, ref_id=None,
          source_query: Optional[str] = None) -> dict:
    return {
        "date": dt.isoformat(), "entity_type": entity_type,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "entity_name": entity_name, "event_type": event_type,
        "description": description, "kind": kind,
        "ref_type": ref_type, "ref_id": str(ref_id) if ref_id is not None else None,
        "source_query": source_query,
    }


def _case_core_events(case: dict) -> list[dict]:
    """Registration + disposition — the two case-level dates every case has, whoever
    is accused. Not tied to a specific person: the case itself is the entity."""
    events = []
    filed = ds.to_dt(case.get("date_filed"))
    if filed:
        events.append(_event(
            filed, "case", case["fir_id"], f'FIR {case["fir_number"]}', "case_registered",
            f'FIR {case["fir_number"]} registered — {case.get("crime_type") or "case"} '
            f'({case.get("district") or "district not recorded"})',
            ref_type="fir", ref_id=case["fir_id"],
            source_query='SELECT "CrimeRegisteredDate" FROM "CaseMaster" WHERE "CaseMasterID" = :cid'))

    for cs in ds.query('SELECT "csdate", "cstype" FROM "ChargesheetDetails" '
                       'WHERE "CaseMasterID" = :cid', {"cid": int(case["fir_id"])}):
        d = ds.to_dt(cs["csdate"])
        if not d:
            continue
        label = {"A": "Chargesheet filed", "B": "Closed as false",
                 "C": "Closed as undetected"}.get(cs["cstype"], "Final report filed")
        events.append(_event(
            d, "case", case["fir_id"], f'FIR {case["fir_number"]}', "case_disposition",
            f'{label} — FIR {case["fir_number"]}', ref_type="fir", ref_id=case["fir_id"],
            source_query='SELECT "csdate", "cstype" FROM "ChargesheetDetails" WHERE "CaseMasterID" = :cid'))
    return events


def _arrest_events(fir_id: str, fir_number: str, officer_role: str) -> list[dict]:
    """Per-accused arrest/surrender events for ONE case, tagged with the RESOLVED
    person where identity resolution reached one, so a later filter ("events
    involving Person X") can find them — falls back to the as-filed name otherwise."""
    rows = ds.query(
        'SELECT "ArrestSurrender"."ArrestSurrenderDate", '
        '       "ArrestSurrender"."ArrestSurrenderTypeID", "Accused"."AccusedName", '
        '       "vx_accused_identity"."PersonUID" '
        'FROM "ArrestSurrender" '
        'JOIN "Accused" ON "ArrestSurrender"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        'LEFT JOIN "vx_accused_identity" '
        '  ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID" '
        'WHERE "ArrestSurrender"."CaseMasterID" = :cid', {"cid": int(fir_id)})
    events = []
    for a in rows:
        d = ds.to_dt(a["ArrestSurrenderDate"])
        if not d:
            continue
        verb = "surrendered" if a["ArrestSurrenderTypeID"] == 2 else "arrested"
        who = mask_person_name(officer_role, a["AccusedName"])
        pid = a.get("PersonUID")
        events.append(_event(
            d, "person" if pid else "case", pid or fir_id, who, f"person_{verb}",
            f"{who} {verb} — FIR {fir_number}", ref_type="fir", ref_id=fir_id,
            source_query='SELECT "ArrestSurrenderDate" FROM "ArrestSurrender" '
                         'WHERE "CaseMasterID" = :cid'))
    return events


def _related_case_events(person: dict, exclude_fir_id: str, officer_role: str,
                         officer_ps_code: str, limit: int = _RELATED_CASE_LIMIT) -> list[dict]:
    """This person's OTHER cases — a cross-entity link that rests on Fellegi-Sunter's
    inferred identity match, not a directly stated ER fact, so every event here is
    labelled 'derived' and carries the match confidence that produced it."""
    other_ids = [str(c["CaseMasterID"]) for c in queries.cases_for_person(person["PersonUID"])
                if str(c["CaseMasterID"]) != str(exclude_fir_id)]
    if not other_ids:
        return []
    conf_row = ds.one('SELECT "MatchConfidence" FROM "vx_accused_identity" '
                      'WHERE "PersonUID" = :p ORDER BY "MatchConfidence" DESC',
                      {"p": person["PersonUID"]})
    conf = (float(conf_row["MatchConfidence"])
            if conf_row and conf_row.get("MatchConfidence") is not None else None)
    who = mask_person_name(officer_role, person["CanonicalName"])
    events = []
    for c in cases_by_ids(other_ids):
        if not can_view_fir(officer_role, officer_ps_code, c["ps_code"]):
            continue
        filed = ds.to_dt(c.get("date_filed"))
        if not filed:
            continue
        conf_note = f" (identity match confidence {conf:.2f})" if conf is not None else ""
        events.append(_event(
            filed, "person", person["PersonUID"], who, "related_case",
            f'{who} also accused in FIR {c["fir_number"]} '
            f'({c.get("crime_type") or "case"}, {c.get("district") or "district not recorded"}) '
            f'— linked by resolved identity{conf_note}',
            kind="derived", ref_type="fir", ref_id=c["fir_id"]))
    events.sort(key=lambda e: e["date"])
    return events[:limit]


def _financial_events(person: dict, officer_role: str) -> list[dict]:
    """Money in/out of every account this person owns — read straight off the
    TRANSFERRED_TO graph edges (data.graph), which already carry amount/date/txn_id
    (data/generator/graph_sync.py). No new query, no second copy of vx_txn."""
    accounts = owned_accounts(str(person["PersonUID"]))
    if not accounts:
        return []
    g = load_graph()
    who = mask_person_name(officer_role, person["CanonicalName"])
    events = []
    for acct in accounts:
        node = f"acct:{acct}"
        if node not in g:
            continue
        for _, dst, d in g.out_edges(node, data=True):
            if d.get("rel") != "TRANSFERRED_TO":
                continue
            dt = ds.to_dt(d.get("date"))
            if not dt:
                continue
            events.append(_event(
                dt, "transaction", d.get("txn_id"), f"transaction {d.get('txn_id')}", "money_out",
                f"{who}'s account {acct} sent ₹{float(d.get('amount') or 0):,.0f} to "
                f"account {dst.split(':', 1)[-1]}",
                ref_type="transaction", ref_id=d.get("txn_id"),
                source_query="TRANSFERRED_TO edge (vx_graph_edge, from vx_txn)"))
        for src, _, d in g.in_edges(node, data=True):
            if d.get("rel") != "TRANSFERRED_TO":
                continue
            dt = ds.to_dt(d.get("date"))
            if not dt:
                continue
            events.append(_event(
                dt, "transaction", d.get("txn_id"), f"transaction {d.get('txn_id')}", "money_in",
                f"{who}'s account {acct} received ₹{float(d.get('amount') or 0):,.0f} "
                f"from account {src.split(':', 1)[-1]}",
                ref_type="transaction", ref_id=d.get("txn_id"),
                source_query="TRANSFERRED_TO edge (vx_graph_edge, from vx_txn)"))
    return events


def case_timeline(fir_id: str, officer_role: str, officer_ps_code: str) -> dict:
    """Cross-entity timeline anchored on one case: the case's own dates, every
    accused person's arrest/surrender on it, their OTHER cases (derived), and money
    through any account they own."""
    rows = fir_by_id(fir_id, "SHO", "")           # unscoped read; checked immediately below
    if not rows:
        raise KeyError(f"Case {fir_id} not found")
    case = rows[0]
    if not can_view_fir(officer_role, officer_ps_code, case["ps_code"]):
        raise NotPermitted(f"Case {fir_id} was filed at another police station")

    accused = accused_on_case(fir_id)
    events = _case_core_events(case) + _arrest_events(fir_id, case["fir_number"], officer_role)
    entities = [{"entity_type": "case", "entity_id": fir_id,
                "entity_name": f'FIR {case["fir_number"]}'}]
    for a in accused:
        who = mask_person_name(officer_role, a["CanonicalName"])
        entities.append({"entity_type": "person", "entity_id": str(a["PersonUID"]),
                         "entity_name": who})
        events += _related_case_events(a, fir_id, officer_role, officer_ps_code)
        events += _financial_events(a, officer_role)

    events.sort(key=lambda e: e["date"])
    return {"fir_id": fir_id, "fir_number": case["fir_number"], "anchor": "case",
           "entities": entities, "events": events, "total": len(events)}


def person_timeline(person_id: str, officer_role: str, officer_ps_code: str) -> dict:
    """Cross-entity timeline anchored on one person: every one of their cases' own
    dates and co-accused arrests, plus money through any account they own. Not
    station-scoped for the person's OWN identity the way /person/{id} isn't (a
    resolved person is not a station-owned record) — each of their CASES is still
    checked individually, so a case outside this officer's scope contributes no
    events, exactly as /person/{id} already relies on can_view_fir per-row."""
    row = ds.one('SELECT "PersonUID", "CanonicalName" FROM "vx_person" WHERE "PersonUID" = :p',
                {"p": int(person_id)})
    if not row:
        raise KeyError(f"Person {person_id} not found")
    person = {"PersonUID": row["PersonUID"], "CanonicalName": row["CanonicalName"]}
    who = mask_person_name(officer_role, person["CanonicalName"])

    ids = [str(c["CaseMasterID"]) for c in queries.cases_for_person(person["PersonUID"])]
    entities = [{"entity_type": "person", "entity_id": str(person["PersonUID"]), "entity_name": who}]
    events: list[dict] = []
    for c in cases_by_ids(ids):
        if not can_view_fir(officer_role, officer_ps_code, c["ps_code"]):
            continue
        events += _case_core_events(c)
        events += _arrest_events(c["fir_id"], c["fir_number"], officer_role)
        entities.append({"entity_type": "case", "entity_id": c["fir_id"],
                         "entity_name": f'FIR {c["fir_number"]}'})
    events += _financial_events(person, officer_role)

    events.sort(key=lambda e: e["date"])
    return {"person_id": str(person["PersonUID"]), "name": who, "anchor": "person",
           "entities": entities, "events": events, "total": len(events)}


def connection_between(person_a_id: str, name_a: str, person_b_id: str, name_b: str) -> dict:
    """Direct, real connections between two resolved people — never inferred from
    events merely falling near each other in time. `direct` lists actual graph/ER
    facts (co-accused, a shared case, a transaction between accounts either owns).
    Empty `direct` is itself the honest answer: 'no recorded connection', not
    silence, and never backfilled with a temporal coincidence dressed up as one."""
    g = load_graph()
    a_node, b_node = f"person:{person_a_id}", f"person:{person_b_id}"
    direct: list[dict] = []

    if a_node in g and b_node in g and g.has_edge(a_node, b_node):
        weight = sum(d.get("weight", 1.0) for d in g.get_edge_data(a_node, b_node).values()
                    if d.get("rel") == "CO_ACCUSED_WITH")
        if weight:
            direct.append({
                "type": "co_accused", "kind": "authoritative",
                "description": f"{name_a} and {name_b} are recorded as co-accused "
                               f"together in {int(round(weight))} case(s)."})

    if not direct:
        a_cases = {str(c["CaseMasterID"]) for c in queries.cases_for_person(int(person_a_id))}
        b_cases = {str(c["CaseMasterID"]) for c in queries.cases_for_person(int(person_b_id))}
        shared = a_cases & b_cases
        if shared:
            direct.append({
                "type": "shared_case", "kind": "authoritative",
                "description": f"{name_a} and {name_b} are both named as accused on "
                               f"{len(shared)} of the same FIR(s)."})

    a_accts = set(owned_accounts(person_a_id))
    b_accts = set(owned_accounts(person_b_id))
    for acct in a_accts:
        node = f"acct:{acct}"
        if node not in g:
            continue
        for _, dst, d in g.out_edges(node, data=True):
            if d.get("rel") == "TRANSFERRED_TO" and dst.split(":", 1)[-1] in b_accts:
                direct.append({
                    "type": "financial_transfer", "kind": "authoritative",
                    "description": f"A transaction moved money from an account "
                                   f"{name_a} owns to an account {name_b} owns."})
                break

    return {"person_a": {"id": person_a_id, "name": name_a},
           "person_b": {"id": person_b_id, "name": name_b},
           "direct": direct, "has_direct_connection": bool(direct)}
