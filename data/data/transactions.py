"""Writes made by packages/ml_models: entity-resolution results and AML flags.

Entity resolution (set_canonical_entity, write_same_as_edge) is the batch pass
run from data/generator/; AML detectors call flag_transaction. Postgres holds
canonical_entity_id; Neo4j holds the SAME_AS edge and the flagged Transaction.
"""
from sqlalchemy import text

from .db import get_session
from .graph import get_driver


def set_canonical_entity(person_id: str, canonical_id: str, confidence: float) -> None:
    # canonical_entity_id in both stores; the pairwise confidence rides the
    # SAME_AS edge (write_same_as_edge), not a person column.
    with get_session() as s:
        s.execute(text(
            "UPDATE person SET canonical_entity_id = CAST(:cid AS uuid) WHERE person_id = :pid"
        ), {"cid": canonical_id, "pid": person_id})
    with get_driver().session() as g:
        g.run("MATCH (p:Person {person_id: $pid}) SET p.canonical_entity_id = $cid",
              pid=person_id, cid=canonical_id)


def write_same_as_edge(person_id_a: str, person_id_b: str, confidence: float) -> None:
    with get_driver().session() as g:
        g.run(
            "MATCH (a:Person {person_id: $a}), (b:Person {person_id: $b}) "
            "MERGE (a)-[e:SAME_AS]->(b) SET e.confidence = $conf",
            a=person_id_a, b=person_id_b, conf=confidence,
        )


def flag_transaction(txn_id: str, flag_type: str, detector: str, confidence: float) -> None:
    with get_driver().session() as g:
        g.run(
            "MATCH (t:Transaction {txn_id: $tid}) "
            "SET t.flagged_suspicious = true, t.flag_type = $ft, "
            "    t.detector = $det, t.flag_confidence = $conf",
            tid=txn_id, ft=flag_type, det=detector, conf=confidence,
        )
