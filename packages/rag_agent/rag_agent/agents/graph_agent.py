"""Graph Agent — graph retrieval, policy-capped at query-construction time.

Was the Cypher Agent. Neo4j has no Catalyst equivalent, so the graph is an edge list
(`vx_graph_edge`) and the traversals run in NetworkX (data.graph), with node attributes read
from the record tables. The investigative queries are unchanged in meaning; only the engine
underneath them moved.

What is gone: the LLM NL->Cypher fallback. It existed to cover questions no template
matched, by writing Cypher against the graph store — with no Cypher to write, there is
nothing for it to fall back to. That long tail now belongs to Think-on-Graph (retrieval/tog),
which beam-searches the graph rather than generating code against it.

Policy is applied HERE, not on the result: you cannot un-traverse a graph. The depth cap
from packages/policy bounds the traversal before it runs, exactly as it bounded the `*1..n`
pattern in the Cypher it replaces.

Node ids are `person:<PersonUID>` — resolved people, not per-case `Accused` rows. That is
what makes a co-offending network exist at all: on the raw ER, two cases naming the same man
are two strangers.
"""
import networkx as nx
from data import ds
from data.graph import load_graph
from policy import max_traversal_depth


def _node(person_id: str) -> str:
    return f"person:{person_id}"


def _uid(node_id: str) -> str:
    return node_id.split(":", 1)[1]


def _people(person_ids: list[str]) -> list[dict]:
    """The record behind a set of graph nodes. One query, not one per node."""
    if not person_ids:
        return []
    rows = ds.query(
        'SELECT "PersonUID", "CanonicalName", "GangAffiliation", "PageRank", '
        '"CommunityID", "IsHabitualOffender" FROM "vx_person" WHERE "PersonUID" IN :ids',
        {"ids": [int(p) for p in person_ids]})
    return [{"person_id": str(r["PersonUID"]), "name_en": r["CanonicalName"],
             "gang": r["GangAffiliation"], "pagerank": float(r["PageRank"] or 0.0),
             "community": r["CommunityID"], "habitual": bool(r["IsHabitualOffender"])}
            for r in rows]


def person_by_name(name: str) -> list[dict]:
    rows = ds.query(
        'SELECT "PersonUID", "CanonicalName", "GangAffiliation", "PageRank", '
        '"CommunityID", "IsHabitualOffender" FROM "vx_person" '
        'WHERE "CanonicalName" LIKE :pat ORDER BY "PageRank" DESC LIMIT 5',
        {"pat": f"%{name}%"})
    return [{"person_id": str(r["PersonUID"]), "name_en": r["CanonicalName"],
             "gang": r["GangAffiliation"], "pagerank": float(r["PageRank"] or 0.0),
             "community": r["CommunityID"], "habitual": bool(r["IsHabitualOffender"])}
            for r in rows]


def person_history(person_id: str) -> list[dict]:
    """Every case this person is accused in, newest first."""
    from .sql_agent import person_record
    return person_record(person_id)[:25]


def person_network(person_id: str, officer_role: str) -> list[dict]:
    """Co-offending network out to the role's traversal depth.

    The Cypher was `(:Person)-[:CO_ACCUSED_WITH*1..4]-(:Person)`, returning each person once
    at their *shortest* hop distance. `single_source_shortest_path_length` over the
    CO_ACCUSED_WITH subgraph is exactly that, and the cutoff is the same policy cap.
    """
    depth = max_traversal_depth(officer_role)
    g = load_graph()
    src = _node(person_id)
    if src not in g:
        return []

    co = nx.Graph()
    for a, b, d in g.edges(data=True):
        if d["rel"] == "CO_ACCUSED_WITH":
            co.add_edge(a, b)
    if src not in co:
        return []

    hops = nx.single_source_shortest_path_length(co, src, cutoff=depth)
    hops.pop(src, None)
    if not hops:
        return []

    rows = _people([_uid(n) for n in hops])
    for r in rows:
        r["hops"] = hops[_node(r["person_id"])]
    return sorted(rows, key=lambda r: (r["hops"], -r["pagerank"]))[:40]


def owned_accounts(person_id: str) -> list[str]:
    """Every account this person owns — not the trail's `from_account`, which for a
    multi-hop transfer can be an intermediate account nobody in this case owns.
    AML detection is per-account and, for structuring specifically, about deposits
    INTO an account, so the account to check is the person's own, not whichever
    account happened to appear first in an outbound trail."""
    g = load_graph()
    return [_uid(dst) for rel, dst, _ in _out_edges(g, _node(person_id)) if rel == "OWNS_ACCOUNT"]


def money_trail(person_id: str, officer_role: str) -> list[dict]:
    """Money out of the person's accounts, to a depth the role is allowed to follow.

    Was `(a)-[:TRANSFERRED_TO*1..4]->(b)`. The same bounded, DIRECTED walk: the flow is
    followed forward only, so a trail can never silently run backwards up a payment and
    invent a transfer that did not happen.
    """
    depth = max_traversal_depth(officer_role)
    g = load_graph()

    owned = [dst for rel, dst, _ in _out_edges(g, _node(person_id)) if rel == "OWNS_ACCOUNT"]
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
                    agg = trail.setdefault(key, {"from_account": _uid(account),
                                                 "to_account": _uid(dst),
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
    """The name spellings this person has actually been recorded under.

    This is the payoff of the whole identity layer, and on the organizers' ER it is a real
    question with a real answer: `Accused` rows carry a name string, nothing links them, and
    Fellegi-Sunter is what decided these particular rows are one man. So "has he been booked
    before under a different spelling" returns the spellings, each with the match confidence
    that merged it.
    """
    rows = ds.query(
        'SELECT "Accused"."AccusedName", "vx_accused_identity"."MatchConfidence" '
        'FROM "vx_accused_identity" '
        'JOIN "Accused" '
        '  ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        'WHERE "vx_accused_identity"."PersonUID" = :uid', {"uid": int(person_id)})

    best: dict[str, float] = {}
    for r in rows:
        name = r["AccusedName"]
        conf = float(r["MatchConfidence"] or 0.0)
        if name and conf > best.get(name, -1.0):
            best[name] = conf
    if len(best) < 2:            # only one spelling: there is no alias to report
        return []
    return sorted(({"person_id": str(person_id), "name_en": n, "confidence": round(c, 4)}
                   for n, c in best.items()), key=lambda r: -r["confidence"])


def community_of(person_id: str) -> list[dict]:
    """The Louvain community this person sits in, and how big it is.

    "Community 47" is the organized-crime grouping — derived from co-offending, not read off
    a gang column, because the ER records no gang and we do not invent one.
    """
    row = ds.one('SELECT "CommunityID" FROM "vx_person" WHERE "PersonUID" = :uid',
                 {"uid": int(person_id)})
    if not row or row["CommunityID"] is None:
        return []
    cid = row["CommunityID"]
    members = ds.query('SELECT "PersonUID" FROM "vx_person" WHERE "CommunityID" = :cid',
                       {"cid": cid})
    return [{"community": cid, "members": len(members)}]
