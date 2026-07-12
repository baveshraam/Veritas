"""Knowledge-graph access — NetworkX over the `graph_edge` table.

Replaces the Neo4j driver. No Catalyst service corresponds to a graph database, so
the graph is stored as ordinary edge rows and materialised in memory on demand:

    from data.graph import load_graph, neighbours
    for rel, node_id, edge in neighbours(person_id): ...

Every graph *algorithm* survived the move (see data.gds). What did not survive is
Cypher itself, and with it the LLM NL->Cypher fallback — there is nothing left for it
to translate into. The template queries it backstopped are all still here.

Honest ceiling: this loads the whole graph into memory (~24k nodes / 136k edges at the
current dataset size — well under a second, tens of MB). That is the right trade,
because Neo4j's real advantage is traversal at a scale this dataset does not have.
# ponytail: whole-graph in-memory load. If the edge count outgrows RAM, swap
# load_graph() for a bounded frontier query (WHERE src_id IN (:frontier)) — every
# caller goes through this module, so nothing outside it changes.

Stratus fast path: on Catalyst the row store is the Data Store, whose ZCQL caps a SELECT
at 300 rows — 136k edges would be ~455 sequential queries on every cold start. So the
generator pickles the built graph into Stratus (object storage) and `load_graph()` reads
that single object instead. `graph_edge` stays the record of truth; Stratus is a derived
cache, and a miss silently falls back to rebuilding from rows, so it can never be the
reason an answer is wrong — only the reason one is slow.
"""
import logging
import pickle
from functools import lru_cache
from typing import Iterator

import networkx as nx
from sqlalchemy import text

from .db import get_session

log = logging.getLogger(__name__)

_STRATUS_BUCKET = "veritas-cache"
_GRAPH_KEY = "graph/knowledge_graph.pkl"

# Symmetric relations. A MultiDiGraph stores the row's direction only, so without the
# reverse edge a traversal starting from the other endpoint would find nothing —
# "who is Ramesh co-accused with" must work from either end of the pair.
# TRANSFERRED_TO is deliberately absent: money flow is the one genuinely directed
# relation, and reversing it would invent a payment that never happened.
_SYMMETRIC = frozenset({
    "CO_ACCUSED_WITH", "ACCUSED_IN", "VICTIM_IN", "MEMBER_OF", "OWNS_ACCOUNT",
    "SAME_AS", "OCCURRED_AT", "INVOLVED_IN", "LINKED_TO",
})


def _bucket():
    """The Stratus bucket, or None when Catalyst isn't configured (local dev, tests)."""
    try:
        import zcatalyst_sdk
        return zcatalyst_sdk.initialize().stratus().bucket(_STRATUS_BUCKET)
    except Exception:
        return None


def _build_from_rows() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    with get_session() as s:
        rows = s.execute(text(
            "SELECT edge_type, src_id, src_label, dst_id, dst_label, "
            "       role, edge_date, amount, strength, confidence FROM graph_edge"
        )).mappings().all()

    for r in rows:
        g.add_node(r["src_id"], label=r["src_label"])
        g.add_node(r["dst_id"], label=r["dst_label"])
        amount = float(r["amount"]) if r["amount"] is not None else None
        g.add_edge(r["src_id"], r["dst_id"], rel=r["edge_type"], role=r["role"],
                   date=r["edge_date"], amount=amount,
                   strength=r["strength"], confidence=r["confidence"])
        if r["edge_type"] in _SYMMETRIC:
            g.add_edge(r["dst_id"], r["src_id"], rel=r["edge_type"], role=r["role"],
                       date=r["edge_date"], amount=amount,
                       strength=r["strength"], confidence=r["confidence"])
    return g


@lru_cache(maxsize=1)
def load_graph() -> nx.MultiDiGraph:
    """The whole crime graph. Cached per process — call `reset_graph()` after a write.

    Reads the Stratus pickle when there is one; otherwise rebuilds from `graph_edge`.
    A cache miss is never fatal — it costs latency, not correctness.
    """
    b = _bucket()
    if b is not None:
        try:
            return pickle.loads(b.get_object(_GRAPH_KEY).read())
        except Exception as e:
            log.warning("Stratus graph cache miss (%s) — rebuilding from graph_edge", e)
    return _build_from_rows()


def publish_graph() -> bool:
    """Pickle the graph built from `graph_edge` into Stratus. Called by the generator
    after the edge list is rewritten. Returns False when Catalyst isn't configured."""
    b = _bucket()
    if b is None:
        return False
    g = _build_from_rows()
    b.put_object(_GRAPH_KEY, pickle.dumps(g, protocol=pickle.HIGHEST_PROTOCOL))
    log.info("published graph to Stratus: %d nodes, %d edges",
             g.number_of_nodes(), g.number_of_edges())
    reset_graph()
    return True


def reset_graph() -> None:
    load_graph.cache_clear()


def undirected() -> nx.Graph:
    """Simple undirected view for the centrality/community algorithms that need one.
    Parallel edges collapse; `strength` (shared-FIR count) becomes the edge weight."""
    g = load_graph()
    u = nx.Graph()
    u.add_nodes_from(g.nodes(data=True))
    for a, b, d in g.edges(data=True):
        w = float(d.get("strength") or 1)
        if u.has_edge(a, b):
            u[a][b]["weight"] += w
        else:
            u.add_edge(a, b, weight=w)
    return u


def neighbours(node_id: str) -> Iterator[tuple[str, str, dict]]:
    """(relation, neighbour_id, edge_data) for every edge out of `node_id`."""
    g = load_graph()
    if node_id not in g:
        return
    for _, dst, data in g.out_edges(node_id, data=True):
        yield data["rel"], dst, data


def node_label(node_id: str) -> str | None:
    return load_graph().nodes.get(node_id, {}).get("label")


if __name__ == "__main__":  # `python -m data.graph`
    g = load_graph()
    print(f"graph loaded: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
