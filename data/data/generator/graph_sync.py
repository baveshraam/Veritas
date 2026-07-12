"""Mirror a generated Dataset into the graph edge list (and the financial tables).

Edge param lists are built by pure functions (testable offline); `sync_graph` is the
thin executemany layer. The record tables stay the system of record; `graph_edge` is
the traversal projection of them. CO_ACCUSED_WITH is derived here — it is graph-only,
aggregating shared FIRs into an edge strength.

Was Neo4j. The node MERGEs are gone: nodes are the records themselves (person, fir,
account, txn) plus the two name-only kinds (Gang, Location), which need no storage
because their id *is* their name. Only edges get a table.

SAME_AS (entity-resolution batch, packages/ml_models) attaches later, through
data.transactions, without changing anything here.
"""
from collections import defaultdict
from dataclasses import asdict
from itertools import combinations
from typing import Optional

from sqlalchemy import text

from ..db import get_session
from ..graph import publish_graph, reset_graph
from .build import Dataset
from .financial import FinancialData

_EDGE_COLS = ["edge_type", "src_id", "src_label", "dst_id", "dst_label",
              "role", "edge_date", "amount", "strength", "confidence"]


def _edge(edge_type: str, src: str, src_label: str, dst: str, dst_label: str,
          *, role=None, edge_date=None, amount=None, strength=None,
          confidence=None) -> dict:
    """One graph_edge row. Every column is always present — executemany binds the
    full column set for every row, so a missing key is a runtime error, not a NULL."""
    return {"edge_type": edge_type, "src_id": str(src), "src_label": src_label,
            "dst_id": str(dst), "dst_label": dst_label, "role": role,
            "edge_date": edge_date, "amount": amount, "strength": strength,
            "confidence": confidence}


# --- edges derived from the record layer -------------------------------------

def accused_in_edges(ds: Dataset) -> list[dict]:
    return [_edge("ACCUSED_IN", r.person_id, "Person", r.fir_id, "CrimeEvent",
                  role=r.role, edge_date=r.arrest_date)
            for r in ds.criminal_records]


def victim_in_edges(ds: Dataset) -> list[dict]:
    return [_edge("VICTIM_IN", f.complainant_id, "Person", f.fir_id, "CrimeEvent")
            for f in ds.firs]


def member_of_edges(ds: Dataset) -> list[dict]:
    return [_edge("MEMBER_OF", p.person_id, "Person", p.gang_affiliation, "Gang")
            for p in ds.persons if p.gang_affiliation]


def occurred_at_edges(ds: Dataset) -> list[dict]:
    return [_edge("OCCURRED_AT", f.fir_id, "CrimeEvent", f.district, "Location")
            for f in ds.firs]


def co_accused_edges(ds: Dataset) -> list[dict]:
    """Undirected co-offending links: persons accused in the same FIR, strength =
    number of shared FIRs. Emitted once per unordered pair (a < b) — data.graph adds
    the reverse direction when it materialises the graph."""
    by_fir: dict[str, set[str]] = defaultdict(set)
    for r in ds.criminal_records:
        if r.role == "Accused":
            by_fir[r.fir_id].add(r.person_id)
    shared: dict[tuple[str, str], list[str]] = defaultdict(list)
    for fir_id, people in by_fir.items():
        for a, b in combinations(sorted(people), 2):
            shared[(a, b)].append(fir_id)
    return [_edge("CO_ACCUSED_WITH", a, "Person", b, "Person", strength=len(firs))
            for (a, b), firs in shared.items()]


# --- edges + rows from the financial layer -----------------------------------

def owns_account_edges(fin: FinancialData) -> list[dict]:
    return [_edge("OWNS_ACCOUNT", a.owner_person_id, "Person", a.account_id, "Account")
            for a in fin.accounts]


def transferred_to_edges(fin: FinancialData) -> list[dict]:
    """The one genuinely DIRECTED relation — money moves one way."""
    return [_edge("TRANSFERRED_TO", t.src_account_id, "Account",
                  t.dst_account_id, "Account", amount=t.amount, edge_date=t.date)
            for t in fin.transactions]


def involved_in_edges(fin: FinancialData) -> list[dict]:
    rows = []
    for t in fin.transactions:
        rows.append(_edge("INVOLVED_IN", t.src_account_id, "Account", t.txn_id, "Transaction"))
        rows.append(_edge("INVOLVED_IN", t.dst_account_id, "Account", t.txn_id, "Transaction"))
    return rows


def linked_to_edges(fin: FinancialData) -> list[dict]:
    return [_edge("LINKED_TO", t.txn_id, "Transaction", t.linked_fir_id, "CrimeEvent")
            for t in fin.transactions if t.linked_fir_id]


def account_rows(fin: FinancialData) -> list[dict]:
    return [{"account_id": a.account_id, "owner_person_id": a.owner_person_id,
             "bank": a.bank, "account_type": a.account_type,
             "opened_date": a.opened_date} for a in fin.accounts]


def txn_rows(fin: FinancialData) -> list[dict]:
    # flagged_suspicious/flag_* are detector OUTPUT — the generator never pre-flags,
    # or the AML models would be scoring their own answer key.
    return [{"txn_id": t.txn_id, "src_account_id": t.src_account_id,
             "dst_account_id": t.dst_account_id, "amount": t.amount,
             "txn_date": t.date, "channel": t.channel,
             "linked_fir_id": t.linked_fir_id, "injected_pattern": t.injected_pattern}
            for t in fin.transactions]


# --- write -------------------------------------------------------------------

_ACCOUNT_COLS = ["account_id", "owner_person_id", "bank", "account_type", "opened_date"]
_TXN_COLS = ["txn_id", "src_account_id", "dst_account_id", "amount", "txn_date",
             "channel", "linked_fir_id", "injected_pattern"]


def _insert(table: str, cols: list[str]) -> str:
    return (f"INSERT INTO {table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(':' + c for c in cols)})")


def sync_graph(ds: Dataset, fin: Optional[FinancialData] = None, wipe: bool = True) -> None:
    edges = (accused_in_edges(ds) + victim_in_edges(ds) + member_of_edges(ds)
             + occurred_at_edges(ds) + co_accused_edges(ds))
    if fin is not None:
        edges += (owns_account_edges(fin) + transferred_to_edges(fin)
                  + involved_in_edges(fin) + linked_to_edges(fin))

    with get_session() as s:
        if wipe:
            s.execute(text("TRUNCATE graph_edge, txn, account CASCADE"))
        if fin is not None:
            s.execute(text(_insert("account", _ACCOUNT_COLS)), account_rows(fin))
            s.execute(text(_insert("txn", _TXN_COLS)), txn_rows(fin))
        if edges:
            s.execute(text(_insert("graph_edge", _EDGE_COLS)), edges)
    reset_graph()   # the in-memory graph is now stale
    # Refresh the Stratus fast-path object so a cold AppSail container reads one blob
    # instead of paginating 136k edges through ZCQL's 300-row cap. No-op off Catalyst.
    publish_graph()


