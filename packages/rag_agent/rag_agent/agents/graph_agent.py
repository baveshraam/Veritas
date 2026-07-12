"""Graph Agent — graph retrieval, policy-capped at query-construction time.

Was the Cypher Agent. Neo4j has no Catalyst equivalent, so the graph is an edge list
and the traversals run in NetworkX (data.graph) with node attributes read from the
record tables. The six investigative queries are unchanged in meaning; only the engine
underneath them moved.

What is gone: the LLM NL->Cypher fallback. It existed to cover questions no template
matched, by writing Cypher against the graph store — with no Cypher to write, there
is nothing for it to fall back to. That long tail now belongs to the SQL Agent, which
already has an EXPLAIN-validated, write-blocked LLM path against the same records.

Policy is applied HERE, not on the result: you cannot un-traverse a graph. The depth
cap from packages/policy bounds the traversal before it runs, exactly as it bounded
the `*1..n` pattern in the Cypher it replaces.
"""
import networkx as nx
from data.graph import load_graph
from policy import max_traversal_depth
from sqlalchemy import text

from data.db import get_session


def _persons(sql: str, params: dict) -> list[dict]:
    with get_session() as s:
        return [dict(r) for r in s.execute(text(sql), params).mappings().all()]


def person_by_name(name: str) -> list[dict]:
    return _persons(
        "SELECT CAST(person_id AS text) AS person_id, name_en, "
        "  gang_affiliation AS gang, COALESCE(pagerank, 0.0) AS pagerank, "
        "  community, criminal_history AS habitual "
        "FROM person WHERE lower(name_en) LIKE lower(:pat) "
        "ORDER BY pagerank DESC NULLS LAST LIMIT 5", {"pat": f"%{name}%"})


def person_history(person_id: str) -> list[dict]:
    return _persons(
        "SELECT CAST(f.fir_id AS text) AS fir_id, f.crime_type, f.ipc_sections, "
        "  f.occurrence_from AS date_occurred, f.district, f.case_status, cr.arrest_date "
        "FROM criminal_record cr JOIN fir f ON f.fir_id = cr.fir_id "
        "WHERE cr.person_id = CAST(:pid AS uuid) "
        "ORDER BY f.occurrence_from DESC LIMIT 25", {"pid": person_id})


def person_network(person_id: str, officer_role: str) -> list[dict]:
    """Co-offending network out to the role's traversal depth.

    The Cypher was `(:Person)-[:CO_ACCUSED_WITH*1..4]-(:Person)` returning each person
    once at their *shortest* hop distance. `single_source_shortest_path_length` on the
    CO_ACCUSED_WITH subgraph is exactly that, and the cutoff is the same policy cap.
    """
    depth = max_traversal_depth(officer_role)
    g = load_graph()
    if person_id not in g:
        return []

    co = nx.Graph()
    for a, b, d in g.edges(data=True):
        if d["rel"] == "CO_ACCUSED_WITH":
            co.add_edge(a, b)
    if person_id not in co:
        return []

    hops = nx.single_source_shortest_path_length(co, person_id, cutoff=depth)
    hops.pop(person_id, None)
    if not hops:
        return []

    rows = _persons(
        "SELECT CAST(person_id AS text) AS person_id, name_en, "
        "  gang_affiliation AS gang, COALESCE(pagerank, 0.0) AS pagerank "
        "FROM person WHERE CAST(person_id AS text) = ANY(:ids)",
        {"ids": list(hops)})
    for r in rows:
        r["hops"] = hops[r["person_id"]]
    return sorted(rows, key=lambda r: (r["hops"], -r["pagerank"]))[:40]


def money_trail(person_id: str, officer_role: str) -> list[dict]:
    """Money out of the person's accounts, to a depth the role is allowed to follow.

    Was `(a)-[:TRANSFERRED_TO*1..4]->(b)`. Same bounded, DIRECTED walk: the flow is
    followed forward only, so the trail cannot silently run backwards up a payment.
    """
    depth = max_traversal_depth(officer_role)
    g = load_graph()

    owned = [dst for rel, dst, _ in _out_edges(g, person_id) if rel == "OWNS_ACCOUNT"]
    trail: dict[tuple[str, str], dict] = {}
    for account in owned:
        frontier = {account: 0}
        seen = {account}
        while frontier:
            nxt: dict[str, int] = {}
            for node, hop in frontier.items():
                if hop >= depth:
                    continue
                for rel, dst, data in _out_edges(g, node):
                    if rel != "TRANSFERRED_TO":
                        continue
                    key = (account, dst)
                    agg = trail.setdefault(key, {"from_account": account,
                                                 "to_account": dst,
                                                 "amount": 0.0, "hops": hop + 1})
                    agg["amount"] += float(data.get("amount") or 0.0)
                    agg["hops"] = min(agg["hops"], hop + 1)
                    if dst not in seen:
                        seen.add(dst)
                        nxt[dst] = hop + 1
            frontier = nxt
    return sorted(trail.values(), key=lambda r: -r["amount"])[:60]


def _out_edges(g, node_id: str):
    if node_id not in g:
        return []
    return [(d["rel"], dst, d) for _, dst, d in g.out_edges(node_id, data=True)]


def aliases(person_id: str) -> list[dict]:
    """SAME_AS edges written by the Fellegi-Sunter batch — a normal graph read, not a
    live linkage computation."""
    g = load_graph()
    linked = {dst: d.get("confidence")
              for rel, dst, d in _out_edges(g, person_id) if rel == "SAME_AS"}
    if not linked:
        return []
    rows = _persons(
        "SELECT CAST(person_id AS text) AS person_id, name_en FROM person "
        "WHERE CAST(person_id AS text) = ANY(:ids)", {"ids": list(linked)})
    for r in rows:
        r["confidence"] = linked[r["person_id"]]
    return rows


def community_of(person_id: str) -> list[dict]:
    return _persons(
        "SELECT p.community AS community, "
        "  (SELECT count(*) FROM person o WHERE o.community = p.community) AS members "
        "FROM person p WHERE p.person_id = CAST(:pid AS uuid) "
        "  AND p.community IS NOT NULL", {"pid": person_id})
