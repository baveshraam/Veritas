"""HippoRAG retrieval (Gutiérrez et al., NeurIPS 2024).

Extract the query's entities, seed Personalized PageRank over the knowledge graph
from those entities, and read off the highest-scoring nodes. One graph pass gives
multi-hop retrieval — no iterative LLM-in-the-loop, which is where the 10-20x cost
saving over agentic retrieval comes from.

The PPR primitive itself lives in data.gds (this package reads GDS results, it does
not run graph algorithms).
"""
from data.gds import personalized_pagerank

from ..agents import graph_agent
from ..state import EvidenceItem

TOP_K = 15


def seed_person_ids(person_names: list[str]) -> list[str]:
    """Resolve the query's entity names to graph node ids (`person:<PersonUID>`).

    The names resolve against `vx_person`, i.e. against *reconstructed* people. Seeding from
    raw `Accused` rows would seed one case's worth of a man and PPR would spread from a
    stub, not from his actual network.
    """
    return [f"person:{hit['person_id']}"
            for name in person_names
            for hit in graph_agent.person_by_name(name)]


def retrieve(person_names: list[str], top_k: int = TOP_K) -> tuple[list[dict], list[EvidenceItem]]:
    """Returns (raw PPR rows, evidence items) — empty when nothing seeds."""
    seeds = seed_person_ids(person_names)
    if not seeds:
        return [], []

    rows = personalized_pagerank(seeds, top_k=top_k)
    evidence = [
        EvidenceItem(
            evidence_id=f"ppr:{r['label']}:{r['id']}",
            source_type="GRAPH_RELATIONSHIP",
            source_id=str(r["id"]),
            source_query=f"personalized PageRank, seeded from {seeds}",
            content=(f"{r['label']} '{r['text']}' is connected to the query entities "
                     f"with personalized-PageRank score {r['score']:.4f}"),
            confidence=min(1.0, float(r["score"]) * 4),   # PPR mass -> rough confidence
        )
        for r in rows
    ]
    return rows, evidence
