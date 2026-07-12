"""Graph algorithms — NetworkX, replacing Neo4j GDS. On-demand, not a scheduled service.

Every algorithm the architecture named survives verbatim in method; only the engine
changed, because Catalyst has no graph-database service for GDS to run on:

    GDS                            ->  NetworkX
    gds.pageRank.write             ->  nx.pagerank
    gds.louvain.write              ->  nx.community.louvain_communities
    gds.betweenness.write          ->  nx.betweenness_centrality (pivot-sampled)
    gds.pageRank(sourceNodes=...)  ->  nx.pagerank(personalization=...)   <- HippoRAG

Results are written back onto the `person` table (pagerank/community/betweenness) —
the same node properties GDS wrote, now on the record they describe. packages/rag_agent
reads them and calls `personalized_pagerank`; it never runs an algorithm itself.

Run after a graph sync: `python -m data.gds`.
"""
import networkx as nx
from sqlalchemy import text

from .db import get_session
from .graph import load_graph, reset_graph, undirected

# Exact betweenness is O(V*E) — minutes on ~19k nodes. Pivot sampling (Brandes & Pich)
# is the standard approximation and is what keeps "who brokers between these gangs"
# an interactive question instead of a batch job.
_BETWEENNESS_PIVOTS = 500


def _persons(g: nx.Graph) -> list[str]:
    return [n for n, d in g.nodes(data=True) if d.get("label") == "Person"]


def _write_metric(column: str, values: dict[str, float]) -> None:
    """Write one metric back onto the person rows it describes."""
    if not values:
        return
    rows = [{"pid": pid, "v": v} for pid, v in values.items()]
    with get_session() as s:
        s.execute(text(
            f"UPDATE person SET {column} = :v WHERE person_id = CAST(:pid AS uuid)"
        ), rows)


def run_pagerank() -> None:
    """Influence — who matters in the network."""
    u = undirected()
    scores = nx.pagerank(u, weight="weight")
    _write_metric("pagerank", {n: scores[n] for n in _persons(u)})


def run_louvain() -> None:
    """Communities — the organized-crime / gang clusters."""
    u = undirected()
    communities = nx.community.louvain_communities(u, weight="weight", seed=0)
    labels = {n: i for i, members in enumerate(communities) for n in members}
    _write_metric("community", {n: labels[n] for n in _persons(u) if n in labels})


def run_betweenness() -> None:
    """Brokers — persons bridging otherwise separate groups."""
    u = undirected()
    k = min(_BETWEENNESS_PIVOTS, u.number_of_nodes())
    scores = nx.betweenness_centrality(u, k=k, weight="weight", seed=0)
    _write_metric("betweenness", {n: scores[n] for n in _persons(u)})


def personalized_pagerank(seed_person_ids: list[str], top_k: int = 20) -> list[dict]:
    """HippoRAG's retrieval primitive (Gutiérrez et al., NeurIPS 2024): seed
    Personalized PageRank from the query's entities and read off the highest-scoring
    nodes. Single-step multi-hop retrieval — no iterative LLM calls.

    nx.pagerank takes `personalization` directly, so this is the same computation
    GDS's `sourceNodes` performed — a port, not an approximation of it.
    """
    if not seed_person_ids:
        return []
    u = undirected()
    seeds = [s for s in seed_person_ids if s in u]
    if not seeds:
        return []

    scores = nx.pagerank(u, personalization={s: 1.0 for s in seeds}, weight="weight")
    ranked = sorted(((n, sc) for n, sc in scores.items() if sc > 0),
                    key=lambda t: -t[1])[:top_k]
    names = _display_names([n for n, _ in ranked])
    return [{"label": u.nodes[n].get("label", "Node"), "id": n,
             "text": names.get(n, ""), "score": float(sc)} for n, sc in ranked]


def community_members(community_id: int, limit: int = 25) -> list[dict]:
    """Members of a Louvain community — the 'matches Community 47' copilot lead."""
    with get_session() as s:
        return [dict(r) for r in s.execute(text(
            "SELECT CAST(person_id AS text) AS person_id, name_en, "
            "  gang_affiliation AS gang, COALESCE(pagerank, 0.0) AS pagerank "
            "FROM person WHERE community = :cid "
            "ORDER BY pagerank DESC NULLS LAST LIMIT :limit"
        ), {"cid": community_id, "limit": limit}).mappings().all()]


def _display_names(node_ids: list[str]) -> dict[str, str]:
    """Readable text for mixed node kinds. The graph holds ids; the records hold the
    names — one lookup per kind, not per node."""
    if not node_ids:
        return {}
    out: dict[str, str] = {}
    with get_session() as s:
        for sql in (
            "SELECT CAST(person_id AS text) AS id, name_en AS t FROM person "
            "WHERE CAST(person_id AS text) = ANY(:ids)",
            "SELECT CAST(fir_id AS text) AS id, crime_type AS t FROM fir "
            "WHERE CAST(fir_id AS text) = ANY(:ids)",
            "SELECT account_id AS id, bank AS t FROM account WHERE account_id = ANY(:ids)",
        ):
            for r in s.execute(text(sql), {"ids": node_ids}).mappings().all():
                out[r["id"]] = r["t"] or ""
    for n in node_ids:      # Gang/Location nodes are named by their id
        out.setdefault(n, n)
    return out


def run_all() -> dict:
    reset_graph()
    g = load_graph()
    run_pagerank()
    run_louvain()
    run_betweenness()
    return {"nodeCount": g.number_of_nodes(), "relationshipCount": g.number_of_edges()}


if __name__ == "__main__":
    print("wrote pagerank/community/betweenness:", run_all())
