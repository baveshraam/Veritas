"""Writes made by packages/ml_models: entity-resolution results and AML flags.

Entity resolution (set_canonical_entity, write_same_as_edge) is the batch pass run
from data/generator/; AML detectors call flag_transaction.

There is one store now — the graph moved into `graph_edge` when Neo4j came out — so
the SAME_AS edge and the transaction flag are ordinary rows, and the double-write
that used to keep Postgres and Neo4j agreeing is gone with it.
"""
from sqlalchemy import text

from .db import get_session
from .graph import reset_graph


def set_canonical_entity(person_id: str, canonical_id: str, confidence: float) -> None:
    # The pairwise confidence rides the SAME_AS edge (write_same_as_edge), not a
    # person column: it is a property of the link, not of either record.
    with get_session() as s:
        s.execute(text(
            "UPDATE person SET canonical_entity_id = CAST(:cid AS uuid) "
            "WHERE person_id = CAST(:pid AS uuid)"
        ), {"cid": canonical_id, "pid": person_id})


def write_same_as_edge(person_id_a: str, person_id_b: str, confidence: float) -> None:
    """Idempotent, like the MERGE it replaces: re-running the linkage batch must not
    accumulate duplicate SAME_AS edges between the same two people."""
    with get_session() as s:
        s.execute(text(
            "DELETE FROM graph_edge WHERE edge_type = 'SAME_AS' "
            "  AND src_id = :a AND dst_id = :b"
        ), {"a": person_id_a, "b": person_id_b})
        s.execute(text(
            "INSERT INTO graph_edge (edge_type, src_id, src_label, dst_id, dst_label, "
            "  confidence) VALUES ('SAME_AS', :a, 'Person', :b, 'Person', :conf)"
        ), {"a": person_id_a, "b": person_id_b, "conf": confidence})
    reset_graph()


def flag_transaction(txn_id: str, flag_type: str, detector: str, confidence: float) -> None:
    with get_session() as s:
        s.execute(text(
            "UPDATE txn SET flagged_suspicious = TRUE, flag_type = :ft, "
            "  detector = :det, flag_confidence = :conf WHERE txn_id = :tid"
        ), {"tid": txn_id, "ft": flag_type, "det": detector, "conf": confidence})
