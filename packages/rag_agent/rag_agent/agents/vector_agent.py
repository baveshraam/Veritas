"""Vector Search Agent — hybrid dense + lexical retrieval over the pgvector store.

Fusion happens in data.vectors.hybrid_search (one SQL pass, so the dense and lexical
halves are ranked against the same candidate set rather than stitched together after
two round trips).
"""
from data.vectors import hybrid_search

from ..state import EvidenceItem

_SOURCE_TYPE = {
    "fir_narrative": "FIR_RECORD",
    "mo": "FIR_RECORD",
    "criminal_profile": "CRIMINAL_RECORD",
    "community_summary": "COMMUNITY_SUMMARY",
}


def _drop_dangling(rows: list[dict]) -> list[dict]:
    """Discard hits whose source record no longer exists.

    The index is rebuilt with the record layer, so this should never fire — but a
    citation pointing at a deleted FIR is the one failure this system must not have,
    and "should never happen" is not a guarantee. Cheap check, absolute payoff.
    """
    from data.db import get_session
    from sqlalchemy import text

    fir_ids = [r["source_id"] for r in rows
               if r["collection"] in ("fir_narrative", "mo")]
    person_ids = [r["source_id"] for r in rows if r["collection"] == "criminal_profile"]
    if not fir_ids and not person_ids:
        return rows

    with get_session() as s:
        live = set()
        if fir_ids:
            live |= {str(x) for (x,) in s.execute(text(
                "SELECT fir_id FROM fir WHERE fir_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": fir_ids}).all()}
        if person_ids:
            live |= {str(x) for (x,) in s.execute(text(
                "SELECT person_id FROM person WHERE person_id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": person_ids}).all()}
    return [r for r in rows if r["source_id"] in live
            or r["collection"] not in ("fir_narrative", "mo", "criminal_profile")]


def search(query: str, collection: str | None = None, k: int = 5
           ) -> tuple[list[dict], list[EvidenceItem]]:
    rows = _drop_dangling(hybrid_search(query, collection=collection, k=k))
    evidence = [
        EvidenceItem(
            evidence_id=f"vec:{r['collection']}:{r['source_id']}",
            source_type=_SOURCE_TYPE.get(r["collection"], "FIR_RECORD"),
            source_id=r["source_id"],
            source_query=f"hybrid dense+BM25 over '{r['collection']}'",
            content=r["content"],
            confidence=float(min(1.0, max(0.0, r["score"]))),
        )
        for r in rows
    ]
    return rows, evidence
