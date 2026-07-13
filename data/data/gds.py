"""Graph algorithms — NetworkX, replacing Neo4j GDS. On-demand, not a scheduled service.

Every algorithm the architecture named survives verbatim in method; only the engine
changed, because Catalyst has no graph-database service for GDS to run on:

    GDS                            ->  NetworkX
    gds.pageRank.write             ->  nx.pagerank
    gds.louvain.write              ->  nx.community.louvain_communities
    gds.betweenness.write          ->  nx.betweenness_centrality (pivot-sampled)
    gds.pageRank(sourceNodes=...)  ->  nx.pagerank(personalization=...)   <- HippoRAG

Results are written back onto `vx_person` — the same node properties GDS wrote, now on
the record they describe. packages/rag_agent reads them and calls `personalized_pagerank`;
it never runs an algorithm itself.

The community *is* the gang. The organizers' ER records no gang affiliation, so rather
than fabricate one we derive the grouping from co-offending (Louvain) and label it
honestly — "Community 47", not "the Chaddi Gang". That is also the stronger claim: the
grouping is evidence from the record layer, not an input to it.

Run after a graph sync: `python -m data.gds`.
"""
import networkx as nx

from . import ds
from .graph import load_graph, reset_graph, undirected

# Exact betweenness is O(V*E) — minutes on ~19k nodes. Pivot sampling (Brandes & Pich) is
# the standard approximation and is what keeps "who brokers between these groups" an
# interactive question instead of a batch job.
_BETWEENNESS_PIVOTS = 500


def _persons(g: nx.Graph) -> list[str]:
    return [n for n in g.nodes if n.startswith("person:")]


def _uid(node_id: str) -> int:
    return int(node_id.split(":", 1)[1])


def co_offending() -> nx.Graph:
    """The person-to-person projection: CO_ACCUSED_WITH only, weighted by shared cases.

    This projection is not an optimisation, it is the difference between an answer and
    nonsense. Run over the *whole* graph, Louvain puts 234 of 234 people in one community —
    correctly, because every case is joined to its district, so `loc:Bagalkot` is a hub that
    transitively connects every offender in the state to every other. What the question
    "which of these people work together" is actually about is the co-offending edges alone.

    GDS did exactly this, and called it a graph projection. Same thing, same reason.
    """
    g = load_graph()
    u = nx.Graph()
    for a, b, d in g.edges(data=True):
        if d["rel"] != "CO_ACCUSED_WITH":
            continue
        w = float(d.get("weight") or 1.0)
        if u.has_edge(a, b):
            u[a][b]["weight"] = max(u[a][b]["weight"], w)
        else:
            u.add_edge(a, b, weight=w)
    return u


def run_all() -> dict:
    """PageRank + Louvain + betweenness in one pass, one write.

    All three describe a person's position among *other people*, so all three run on the
    co-offending projection. Writing them separately would mean three ROWID lookups over
    vx_person; one pass, one update.
    """
    reset_graph()
    g = load_graph()
    u = co_offending()
    people = _persons(u)

    pagerank = nx.pagerank(u, weight="weight") if u.number_of_edges() else {}
    communities = (nx.community.louvain_communities(u, weight="weight", seed=0)
                   if u.number_of_edges() else [])
    community_of = {n: i for i, members in enumerate(communities) for n in members}
    k = min(_BETWEENNESS_PIVOTS, u.number_of_nodes())
    betweenness = (nx.betweenness_centrality(u, k=k, weight="weight", seed=0)
                   if u.number_of_nodes() > 2 else {})

    rows = []
    for n in people:
        cid = community_of.get(n)
        rows.append({
            "PersonUID": _uid(n),
            "PageRank": float(pagerank.get(n, 0.0)),
            "CommunityID": cid,
            "Betweenness": float(betweenness.get(n, 0.0)),
            "GangAffiliation": f"Community {cid}" if cid is not None else None,
        })
    ds.update("vx_person", "PersonUID", rows)

    return {"nodes": g.number_of_nodes(), "edges": g.number_of_edges(),
            "persons": len(people), "communities": len(communities)}


def personalized_pagerank(seed_node_ids: list[str], top_k: int = 20) -> list[dict]:
    """HippoRAG's retrieval primitive (Gutiérrez et al., NeurIPS 2024): seed Personalized
    PageRank from the query's entities and read off the highest-scoring nodes. Single-step
    multi-hop retrieval — no iterative LLM calls.

    nx.pagerank takes `personalization` directly, so this is the same computation GDS's
    `sourceNodes` performed — a port, not an approximation of it.
    """
    if not seed_node_ids:
        return []
    u = undirected()
    seeds = [s for s in seed_node_ids if s in u]
    if not seeds:
        return []

    scores = nx.pagerank(u, personalization={s: 1.0 for s in seeds}, weight="weight")
    ranked = sorted(((n, sc) for n, sc in scores.items() if sc > 0),
                    key=lambda t: -t[1])[:top_k]
    names = display_names([n for n, _ in ranked])
    return [{"label": u.nodes[n].get("label", "Node"), "id": n,
             "text": names.get(n, ""), "score": float(sc)} for n, sc in ranked]


def community_members(community_id: int, limit: int = 25) -> list[dict]:
    """Members of a Louvain community — the 'matches Community 47' copilot lead."""
    return ds.query(
        'SELECT "PersonUID", "CanonicalName", "GangAffiliation", "PageRank" '
        'FROM "vx_person" WHERE "CommunityID" = :cid '
        'ORDER BY "PageRank" DESC LIMIT :limit',
        {"cid": community_id, "limit": limit},
    )


def display_names(node_ids: list[str]) -> dict[str, str]:
    """Readable text for mixed node kinds. The graph holds ids; the records hold the
    names — one lookup per kind, not per node."""
    if not node_ids:
        return {}
    by_kind: dict[str, list[int]] = {}
    for n in node_ids:
        kind, _, rest = n.partition(":")
        if kind in ("person", "case", "acct"):
            by_kind.setdefault(kind, []).append(int(rest))

    out: dict[str, str] = {}
    lookups = [
        ("person", 'SELECT "PersonUID" AS k, "CanonicalName" AS t FROM "vx_person" '
                   'WHERE "PersonUID" IN :ids'),
        ("case", 'SELECT "CaseMasterID" AS k, "CrimeNo" AS t FROM "CaseMaster" '
                 'WHERE "CaseMasterID" IN :ids'),
        ("acct", 'SELECT "AccountID" AS k, "Bank" AS t FROM "vx_account" '
                 'WHERE "AccountID" IN :ids'),
    ]
    for kind, sql in lookups:
        ids = by_kind.get(kind)
        if not ids:
            continue
        for r in ds.query(sql, {"ids": ids}):
            out[f"{kind}:{r['k']}"] = r["t"] or ""
    for n in node_ids:      # loc:/txn: nodes are named by their own id
        out.setdefault(n, n.split(":", 1)[1])
    return out


if __name__ == "__main__":
    print("wrote pagerank/community/betweenness:", run_all())
