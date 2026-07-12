"""Think-on-Graph (Sun et al., ICLR 2024) — beam search over graph paths.

Used when HippoRAG's confidence is low or the question is explicitly multi-hop and
relational ("how are these three gangs financially connected"). Instead of trusting
one generated Cypher query to be right, the agent walks the graph a relation at a
time, keeping the best `beam_width` paths, and returns the *paths* — so the answer
carries a traceable chain rather than an assertion.

Scoring the frontier is where an LLM helps (it can judge which relation is relevant
to the question); without a key we fall back to a structural score (PageRank of the
node reached, preferring edges that carry weight). The search still runs, still
produces real paths, and still terminates — it is just less selective.
"""
from dataclasses import dataclass, field
from functools import lru_cache

from data.db import get_session
from data.graph import load_graph, neighbours
from policy import max_traversal_depth
from sqlalchemy import text

from ..llm import available, generate_json
from ..state import EvidenceItem

BEAM_WIDTH = 4
PATH_CONFIDENCE_CAP = 0.7   # a reasoning path is a hypothesis, not a record

# Relations worth walking for an investigative question, with a structural prior.
_RELATION_PRIOR = {
    "CO_ACCUSED_WITH": 1.0,
    "MEMBER_OF": 0.9,
    "ACCUSED_IN": 0.8,
    "TRANSFERRED_TO": 0.9,
    "OWNS_ACCOUNT": 0.7,
    "SAME_AS": 0.6,
    "OCCURRED_AT": 0.4,
    "VICTIM_IN": 0.4,
}


@dataclass
class Path:
    nodes: list[str] = field(default_factory=list)      # display labels
    ids: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    score: float = 0.0

    def describe(self) -> str:
        parts = [self.nodes[0]] if self.nodes else []
        for rel, node in zip(self.relations, self.nodes[1:]):
            parts.append(f"-[{rel}]->{node}")
        return " ".join(parts)


_FRONTIER_CAP = 60      # the Cypher had `LIMIT 60`; the beam cannot fan out unbounded


def _neighbours(node_id: str) -> list[dict]:
    """One hop out of `node_id`. The Cypher matched any node kind by id and returned
    (rel, id, display label, pagerank); the graph and the record tables between them
    hold exactly the same four things."""
    hops = [{"rel": rel, "id": dst} for rel, dst, _ in neighbours(node_id)][:_FRONTIER_CAP]
    if not hops:
        return []
    meta = _node_meta(tuple(h["id"] for h in hops))
    for h in hops:
        label, pagerank = meta.get(h["id"], (h["id"], 0.0))
        h["label"], h["pagerank"] = label, pagerank
    return hops


@lru_cache(maxsize=512)
def _node_meta(node_ids: tuple[str, ...]) -> dict[str, tuple[str, float]]:
    """Display label + PageRank per node. Cached: a beam search revisits the same
    frontier nodes repeatedly, and this was one DB round-trip each time."""
    out: dict[str, tuple[str, float]] = {}
    ids = list(node_ids)
    with get_session() as s:
        for row in s.execute(text(
            "SELECT CAST(person_id AS text) AS id, name_en AS label, "
            "  COALESCE(pagerank, 0.0) AS pagerank FROM person "
            "WHERE CAST(person_id AS text) = ANY(:ids)"), {"ids": ids}).mappings():
            out[row["id"]] = (row["label"] or "?", float(row["pagerank"]))
        for row in s.execute(text(
            "SELECT CAST(fir_id AS text) AS id, crime_type AS label FROM fir "
            "WHERE CAST(fir_id AS text) = ANY(:ids)"), {"ids": ids}).mappings():
            out[row["id"]] = (row["label"] or "?", 0.0)
    g = load_graph()
    for nid in ids:                      # Account/Gang/Location are named by their id
        out.setdefault(nid, (nid, 0.0))
        if nid not in g:
            out[nid] = (nid, 0.0)
    return out


def _rank(question: str, candidates: list[dict]) -> list[float]:
    """Relevance of each candidate expansion to the question."""
    structural = [
        _RELATION_PRIOR.get(c["rel"], 0.2) * (1.0 + float(c["pagerank"]))
        for c in candidates
    ]
    if not available() or not candidates:
        return structural

    schema = {
        "type": "OBJECT",
        "properties": {"scores": {"type": "ARRAY", "items": {"type": "NUMBER"}}},
        "required": ["scores"],
    }
    listing = "\n".join(
        f"{i}. via {c['rel']} to {c['label']}" for i, c in enumerate(candidates))
    out = generate_json(
        f"Question: {question}\n\nCandidate next steps in a crime knowledge graph:\n"
        f"{listing}\n\nScore each 0-1 for how likely it is to lead to the answer. "
        f"Return exactly {len(candidates)} scores in order.",
        schema=schema,
        system="You guide a beam search over a police knowledge graph.",
    )
    scores = out.get("scores") or []
    if len(scores) != len(candidates):
        return structural
    # blend: the model's judgement, anchored by structure so it can't wander off
    return [0.7 * float(s) + 0.3 * st for s, st in zip(scores, structural)]


def search(question: str, seed_ids: list[str], seed_labels: list[str],
           officer_role: str, beam_width: int = BEAM_WIDTH) -> tuple[list[Path], list[EvidenceItem]]:
    """Beam-search outward from the seeds. Depth is capped by the caller's role —
    the same policy cap the Cypher Agent applies, for the same reason."""
    depth = max_traversal_depth(officer_role)
    if not seed_ids:
        return [], []

    beams = [Path(nodes=[lbl], ids=[i], score=1.0)
             for i, lbl in zip(seed_ids, seed_labels)][:beam_width]

    for _ in range(depth):
        expansions: list[Path] = []
        for path in beams:
            nbrs = [n for n in _neighbours(path.ids[-1]) if n["id"] not in path.ids]
            if not nbrs:
                continue
            for cand, score in zip(nbrs, _rank(question, nbrs)):
                expansions.append(Path(
                    nodes=path.nodes + [str(cand["label"])],
                    ids=path.ids + [str(cand["id"])],
                    relations=path.relations + [cand["rel"]],
                    score=path.score * max(score, 1e-3),
                ))
        if not expansions:
            break
        beams = sorted(expansions, key=lambda p: -p.score)[:beam_width]

    # A ToG path is a *hypothesis* — "these nodes are connected this way" — not a
    # record. Capping its confidence below that of a retrieved FIR keeps a
    # speculative chain from outranking the document that actually answers the
    # question when synthesis picks its top citations.
    evidence = [
        EvidenceItem(
            evidence_id=f"tog:{'>'.join(p.ids)}",
            source_type="GRAPH_RELATIONSHIP",
            source_id=p.ids[-1],
            source_query=f"ToG beam search (width={beam_width}, depth<={depth})",
            content=f"Reasoning path: {p.describe()}",
            confidence=min(PATH_CONFIDENCE_CAP, p.score),
        )
        for p in beams if len(p.nodes) > 1
    ]
    return beams, evidence
