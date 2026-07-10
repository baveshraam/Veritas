"""Mirror a generated Dataset into Neo4j.

Node/edge param lists are built by pure functions (testable offline); `sync_graph`
is the thin UNWIND executor. Postgres stays the system of record; the graph is the
traversal/GDS projection of it. CO_ACCUSED_WITH is derived here (it's graph-only —
no Postgres table), aggregating shared FIRs into an edge strength.

Not built here: Account/Transaction (financial-crime generation) and SAME_AS
(entity-resolution batch, packages/ml_models) — they attach later without changing
this module's node/edge shapes.
"""
from collections import defaultdict
from itertools import combinations
from typing import Optional

from ..graph import get_driver
from .build import Dataset
from .financial import FinancialData


def person_nodes(ds: Dataset) -> list[dict]:
    return [{
        "person_id": p.person_id, "scrb_id": p.scrb_id,
        "name_en": p.name_en, "name_kn": p.name_kn, "gender": p.gender,
        "risk_score": p.risk_score, "gang_affiliation": p.gang_affiliation,
        "is_habitual_offender": p.criminal_history,
        "canonical_entity_id": p.canonical_entity_id,
    } for p in ds.persons]


def crimeevent_nodes(ds: Dataset) -> list[dict]:
    return [{
        "fir_id": f.fir_id, "crime_type": f.crime_type, "ipc_sections": f.ipc_sections,
        "date_occurred": f.occurrence_from, "location": f.district, "district": f.district,
        "modus_operandi": f.modus_operandi, "case_status": f.case_status,
    } for f in ds.firs]


def location_nodes(ds: Dataset) -> list[dict]:
    return [{"name": name} for name in sorted({f.district for f in ds.firs})]


def gang_nodes(ds: Dataset) -> list[dict]:
    gangs = {p.gang_affiliation for p in ds.persons if p.gang_affiliation}
    return [{"name": g} for g in sorted(gangs)]


def accused_in_edges(ds: Dataset) -> list[dict]:
    return [{
        "person_id": r.person_id, "fir_id": r.fir_id,
        "role": r.role, "arrest_date": r.arrest_date,
    } for r in ds.criminal_records]


def victim_in_edges(ds: Dataset) -> list[dict]:
    return [{"person_id": f.complainant_id, "fir_id": f.fir_id} for f in ds.firs]


def member_of_edges(ds: Dataset) -> list[dict]:
    return [{"person_id": p.person_id, "gang": p.gang_affiliation}
            for p in ds.persons if p.gang_affiliation]


def occurred_at_edges(ds: Dataset) -> list[dict]:
    return [{"fir_id": f.fir_id, "location": f.district} for f in ds.firs]


def co_accused_edges(ds: Dataset) -> list[dict]:
    """Undirected co-offending links: persons accused in the same FIR, strength =
    number of shared FIRs. Emitted once per unordered pair (a < b)."""
    by_fir: dict[str, set[str]] = defaultdict(set)
    for r in ds.criminal_records:
        if r.role == "Accused":
            by_fir[r.fir_id].add(r.person_id)
    shared: dict[tuple[str, str], list[str]] = defaultdict(list)
    for fir_id, people in by_fir.items():
        for a, b in combinations(sorted(people), 2):
            shared[(a, b)].append(fir_id)
    return [{"a": a, "b": b, "fir_ids": firs, "strength": len(firs)}
            for (a, b), firs in shared.items()]


def account_nodes(fin: FinancialData) -> list[dict]:
    return [{"account_id": a.account_id, "bank": a.bank,
             "account_type": a.account_type, "opened_date": a.opened_date}
            for a in fin.accounts]


def transaction_nodes(fin: FinancialData) -> list[dict]:
    return [{"txn_id": t.txn_id, "amount": t.amount, "date": t.date,
             "channel": t.channel, "flagged_suspicious": False,
             "injected_pattern": t.injected_pattern}
            for t in fin.transactions]


def owns_account_edges(fin: FinancialData) -> list[dict]:
    return [{"person_id": a.owner_person_id, "account_id": a.account_id} for a in fin.accounts]


def transferred_to_edges(fin: FinancialData) -> list[dict]:
    return [{"src": t.src_account_id, "dst": t.dst_account_id,
             "amount": t.amount, "date": t.date} for t in fin.transactions]


def involved_in_edges(fin: FinancialData) -> list[dict]:
    rows = []
    for t in fin.transactions:
        rows.append({"account_id": t.src_account_id, "txn_id": t.txn_id})
        rows.append({"account_id": t.dst_account_id, "txn_id": t.txn_id})
    return rows


def linked_to_edges(fin: FinancialData) -> list[dict]:
    return [{"txn_id": t.txn_id, "fir_id": t.linked_fir_id}
            for t in fin.transactions if t.linked_fir_id]


_CYPHER = {
    "person": "UNWIND $rows AS r MERGE (p:Person {person_id: r.person_id}) SET p += r",
    "crimeevent": "UNWIND $rows AS r MERGE (c:CrimeEvent {fir_id: r.fir_id}) SET c += r",
    "location": "UNWIND $rows AS r MERGE (l:Location {name: r.name})",
    "gang": "UNWIND $rows AS r MERGE (g:Gang {name: r.name})",
    "accused_in": (
        "UNWIND $rows AS r MATCH (p:Person {person_id: r.person_id}), "
        "(c:CrimeEvent {fir_id: r.fir_id}) "
        "MERGE (p)-[e:ACCUSED_IN]->(c) SET e.role = r.role, e.arrest_date = r.arrest_date"),
    "victim_in": (
        "UNWIND $rows AS r MATCH (p:Person {person_id: r.person_id}), "
        "(c:CrimeEvent {fir_id: r.fir_id}) MERGE (p)-[:VICTIM_IN]->(c)"),
    "member_of": (
        "UNWIND $rows AS r MATCH (p:Person {person_id: r.person_id}), "
        "(g:Gang {name: r.gang}) MERGE (p)-[:MEMBER_OF]->(g)"),
    "occurred_at": (
        "UNWIND $rows AS r MATCH (c:CrimeEvent {fir_id: r.fir_id}), "
        "(l:Location {name: r.location}) MERGE (c)-[:OCCURRED_AT]->(l)"),
    "co_accused": (
        "UNWIND $rows AS r MATCH (a:Person {person_id: r.a}), (b:Person {person_id: r.b}) "
        "MERGE (a)-[e:CO_ACCUSED_WITH]->(b) SET e.strength = r.strength, e.fir_ids = r.fir_ids"),
    "account": "UNWIND $rows AS r MERGE (a:Account {account_id: r.account_id}) SET a += r",
    "transaction": "UNWIND $rows AS r MERGE (t:Transaction {txn_id: r.txn_id}) SET t += r",
    "owns_account": (
        "UNWIND $rows AS r MATCH (p:Person {person_id: r.person_id}), "
        "(a:Account {account_id: r.account_id}) MERGE (p)-[:OWNS_ACCOUNT]->(a)"),
    "transferred_to": (
        "UNWIND $rows AS r MATCH (s:Account {account_id: r.src}), (d:Account {account_id: r.dst}) "
        "CREATE (s)-[:TRANSFERRED_TO {amount: r.amount, date: r.date}]->(d)"),
    "involved_in": (
        "UNWIND $rows AS r MATCH (a:Account {account_id: r.account_id}), "
        "(t:Transaction {txn_id: r.txn_id}) MERGE (a)-[:INVOLVED_IN]->(t)"),
    "linked_to": (
        "UNWIND $rows AS r MATCH (t:Transaction {txn_id: r.txn_id}), "
        "(c:CrimeEvent {fir_id: r.fir_id}) MERGE (t)-[:LINKED_TO]->(c)"),
}


def sync_graph(ds: Dataset, fin: Optional[FinancialData] = None, wipe: bool = True) -> None:
    builders = [
        ("person", lambda: person_nodes(ds)), ("crimeevent", lambda: crimeevent_nodes(ds)),
        ("location", lambda: location_nodes(ds)), ("gang", lambda: gang_nodes(ds)),
        ("accused_in", lambda: accused_in_edges(ds)), ("victim_in", lambda: victim_in_edges(ds)),
        ("member_of", lambda: member_of_edges(ds)), ("occurred_at", lambda: occurred_at_edges(ds)),
        ("co_accused", lambda: co_accused_edges(ds)),
    ]
    if fin is not None:
        builders += [
            ("account", lambda: account_nodes(fin)), ("transaction", lambda: transaction_nodes(fin)),
            ("owns_account", lambda: owns_account_edges(fin)),
            ("transferred_to", lambda: transferred_to_edges(fin)),
            ("involved_in", lambda: involved_in_edges(fin)), ("linked_to", lambda: linked_to_edges(fin)),
        ]
    with get_driver().session() as s:
        if wipe:
            s.run("MATCH (n) DETACH DELETE n")
        for key, builder in builders:
            rows = builder()
            if rows:
                s.run(_CYPHER[key], rows=rows)
