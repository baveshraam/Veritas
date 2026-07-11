"""Neo4j GDS job scripts. On-demand — not a scheduled service.

Lives at `data.gds` (not `data/graph/`) because `data.graph` is already the driver
module; a `graph/` package would shadow it. The .cypher constraint files stay in
data/graph/ as resources.

packages/rag_agent reads the results (pagerank/community node properties) and calls
`personalized_pagerank` — the HippoRAG retrieval primitive. It never runs the
algorithms itself. Run the write-back jobs after a graph sync: `python -m data.gds`.
"""
from .graph import get_driver

GRAPH_NAME = "veritas"

# Project the whole crime graph (persons, events, accounts, gangs) so PageRank
# influence and Louvain communities span co-offending, shared events, and money.
_CREATE = """
CALL gds.graph.project(
  $name,
  ['Person', 'CrimeEvent', 'Account', 'Gang'],
  {
    CO_ACCUSED_WITH: {orientation: 'UNDIRECTED'},
    ACCUSED_IN:      {orientation: 'UNDIRECTED'},
    MEMBER_OF:       {orientation: 'UNDIRECTED'},
    OWNS_ACCOUNT:    {orientation: 'UNDIRECTED'},
    TRANSFERRED_TO:  {orientation: 'NATURAL'}
  }
) YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount
"""


def _ensure_projection(session, recreate: bool = False) -> None:
    exists = session.run("CALL gds.graph.exists($name) YIELD exists RETURN exists",
                         name=GRAPH_NAME).single()["exists"]
    if exists and recreate:
        session.run("CALL gds.graph.drop($name)", name=GRAPH_NAME)
        exists = False
    if not exists:
        session.run(_CREATE, name=GRAPH_NAME)


def project() -> dict:
    with get_driver().session() as s:
        _ensure_projection(s, recreate=True)
        rec = s.run("CALL gds.graph.list($name) "
                    "YIELD graphName, nodeCount, relationshipCount "
                    "RETURN graphName, nodeCount, relationshipCount",
                    name=GRAPH_NAME).single()
        return dict(rec) if rec else {}


def run_pagerank() -> None:
    """Influence — who matters in the network."""
    with get_driver().session() as s:
        _ensure_projection(s)
        s.run("CALL gds.pageRank.write($name, {writeProperty: 'pagerank'})", name=GRAPH_NAME)


def run_louvain() -> None:
    """Communities — the organized-crime / gang clusters."""
    with get_driver().session() as s:
        _ensure_projection(s)
        s.run("CALL gds.louvain.write($name, {writeProperty: 'community'})", name=GRAPH_NAME)


def run_betweenness() -> None:
    """Brokers — persons bridging otherwise separate groups."""
    with get_driver().session() as s:
        _ensure_projection(s)
        s.run("CALL gds.betweenness.write($name, {writeProperty: 'betweenness'})",
              name=GRAPH_NAME)


def personalized_pagerank(seed_person_ids: list[str], top_k: int = 20) -> list[dict]:
    """HippoRAG's retrieval primitive (Gutiérrez et al., NeurIPS 2024): seed
    Personalized PageRank from the query's entities and read off the highest-scoring
    nodes. Single-step multi-hop retrieval — no iterative LLM calls."""
    if not seed_person_ids:
        return []
    with get_driver().session() as s:
        _ensure_projection(s)
        return s.run(
            "MATCH (p:Person) WHERE p.person_id IN $seeds "
            "WITH collect(p) AS sourceNodes "
            "CALL gds.pageRank.stream($name, "
            "     {sourceNodes: sourceNodes, maxIterations: 20}) "
            "YIELD nodeId, score "
            "WITH gds.util.asNode(nodeId) AS n, score WHERE score > 0 "
            "RETURN labels(n)[0] AS label, "
            "  coalesce(n.person_id, n.fir_id, n.account_id, n.name) AS id, "
            "  coalesce(n.name_en, n.crime_type, n.name, '') AS text, "
            "  score ORDER BY score DESC LIMIT $k",
            seeds=seed_person_ids, name=GRAPH_NAME, k=top_k,
        ).data()


def community_members(community_id: int, limit: int = 25) -> list[dict]:
    """Members of a Louvain community — the 'matches Community 47' copilot lead."""
    with get_driver().session() as s:
        return s.run(
            "MATCH (p:Person) WHERE p.community = $cid "
            "RETURN p.person_id AS person_id, p.name_en AS name_en, "
            "  p.gang_affiliation AS gang, coalesce(p.pagerank, 0.0) AS pagerank "
            "ORDER BY pagerank DESC LIMIT $limit",
            cid=community_id, limit=limit,
        ).data()


def run_all() -> dict:
    stats = project()
    run_pagerank()
    run_louvain()
    run_betweenness()
    return stats


if __name__ == "__main__":
    print("projected + wrote pagerank/community/betweenness:", run_all())
