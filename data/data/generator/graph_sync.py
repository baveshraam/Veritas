"""Project the record layer into `vx_graph_edge`.

The ER tables stay the system of record; the edge list is a *derived* traversal view of
them. It is rebuilt, never patched.

Runs after entity resolution, and that ordering is the whole point. The ER has no person
— an `Accused` row belongs to one case, and its `PersonID` is a per-case sort label
("A1", "A2"). So co-offending is invisible in the records as given: two rows naming the
same man in two cases are two strangers. `vx_accused_identity` (Fellegi-Sunter,
packages/ml_models) is what turns them back into one node, and only then does
CO_ACCUSED_WITH mean anything.

Gangs are deliberately absent. The ER records no gang, so a Gang node would be a fact we
invented. Organised-crime grouping is instead *derived*, by Louvain over CO_ACCUSED_WITH
(data.gds), and labelled as the community it is — see §2.2.

Edge builders are pure functions over rows (testable offline); `sync_graph` is the thin
read-transform-write layer.
"""
import json
from collections import defaultdict
from itertools import combinations, count

from .. import ds
from ..graph import publish_graph, reset_graph


def _edge(src: str, dst: str, edge_type: str, weight: float = 1.0, **props) -> dict:
    return {"SrcId": src, "DstId": dst, "EdgeType": edge_type, "Weight": weight,
            "Props": json.dumps(props, default=str) if props else None}


# --- edges from the record layer ---------------------------------------------

def accused_in_edges(accused: list[dict], uid_of: dict[int, int]) -> list[dict]:
    """person -> case, one per Accused row that resolution mapped to a person."""
    return [_edge(f"person:{uid_of[a['AccusedMasterID']]}", f"case:{a['CaseMasterID']}",
                  "ACCUSED_IN", role="Accused")
            for a in accused if a["AccusedMasterID"] in uid_of]


def co_accused_edges(accused: list[dict], uid_of: dict[int, int]) -> list[dict]:
    """Undirected co-offending links between *resolved* people, weight = shared cases.

    Emitted once per unordered pair — data.graph adds the reverse direction when it
    materialises the graph.
    """
    by_case: dict[int, set[int]] = defaultdict(set)
    for a in accused:
        uid = uid_of.get(a["AccusedMasterID"])
        if uid is not None:
            by_case[a["CaseMasterID"]].add(uid)

    shared: dict[tuple[int, int], int] = defaultdict(int)
    for people in by_case.values():
        for p, q in combinations(sorted(people), 2):
            shared[(p, q)] += 1

    return [_edge(f"person:{p}", f"person:{q}", "CO_ACCUSED_WITH", weight=float(n),
                  shared_cases=n)
            for (p, q), n in shared.items()]


def occurred_at_edges(cases: list[dict], district_of: dict[int, str]) -> list[dict]:
    return [_edge(f"case:{c['CaseMasterID']}", f"loc:{district_of[c['PoliceStationID']]}",
                  "OCCURRED_AT")
            for c in cases if c["PoliceStationID"] in district_of]


# --- edges from the financial layer ------------------------------------------

def owns_account_edges(accounts: list[dict]) -> list[dict]:
    return [_edge(f"person:{a['PersonUID']}", f"acct:{a['AccountID']}", "OWNS_ACCOUNT")
            for a in accounts if a.get("PersonUID")]


def transferred_to_edges(txns: list[dict]) -> list[dict]:
    """The one genuinely DIRECTED relation — money moves one way."""
    return [_edge(f"acct:{t['SrcAccountID']}", f"acct:{t['DstAccountID']}",
                  "TRANSFERRED_TO", weight=float(t["Amount"]),
                  amount=t["Amount"], date=t["TxnDate"], txn_id=t["TxnID"])
            for t in txns]


def involved_in_edges(txns: list[dict]) -> list[dict]:
    out = []
    for t in txns:
        out.append(_edge(f"acct:{t['SrcAccountID']}", f"txn:{t['TxnID']}", "INVOLVED_IN"))
        out.append(_edge(f"acct:{t['DstAccountID']}", f"txn:{t['TxnID']}", "INVOLVED_IN"))
    return out


def linked_to_edges(txns: list[dict]) -> list[dict]:
    return [_edge(f"txn:{t['TxnID']}", f"case:{t['CaseMasterID']}", "LINKED_TO")
            for t in txns if t.get("CaseMasterID")]


# --- write -------------------------------------------------------------------

def sync_graph() -> int:
    """Rebuild vx_graph_edge from what is currently in the database. Returns edge count."""
    accused = ds.query('SELECT "AccusedMasterID", "CaseMasterID" FROM "Accused"')
    uid_of = {r["AccusedMasterID"]: r["PersonUID"]
              for r in ds.query('SELECT "AccusedMasterID", "PersonUID" '
                                'FROM "vx_accused_identity"')}
    cases = ds.query('SELECT "CaseMasterID", "PoliceStationID" FROM "CaseMaster"')
    district_of = {r["UnitID"]: r["DistrictName"]
                   for r in ds.query('SELECT "Unit"."UnitID", "District"."DistrictName" '
                                     'FROM "Unit" LEFT JOIN "District" '
                                     'ON "Unit"."DistrictID" = "District"."DistrictID"')}
    accounts = ds.query('SELECT "AccountID", "PersonUID" FROM "vx_account"')
    txns = ds.query('SELECT "TxnID", "SrcAccountID", "DstAccountID", "Amount", '
                    '"TxnDate", "CaseMasterID" FROM "vx_txn"')

    edges = (accused_in_edges(accused, uid_of)
             + co_accused_edges(accused, uid_of)
             + occurred_at_edges(cases, district_of)
             + owns_account_edges(accounts)
             + transferred_to_edges(txns)
             + involved_in_edges(txns)
             + linked_to_edges(txns))

    ids = count(1)
    for e in edges:
        e["EdgeID"] = next(ids)

    ds.truncate(["vx_graph_edge"])
    ds.insert("vx_graph_edge", edges)

    reset_graph()          # the in-memory graph is now stale
    publish_graph()        # refresh the Stratus blob; no-op off Catalyst
    return len(edges)
