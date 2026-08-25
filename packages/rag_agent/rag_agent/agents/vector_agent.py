"""Vector Search Agent — hybrid dense + lexical retrieval over the Stratus index.

Fusion happens in data.vectors.hybrid_search (one numpy pass over the whole index, so the
dense and lexical halves are ranked against the same candidate set rather than stitched
together after two round trips).
"""
from data.vectors import hybrid_search

from ..state import EvidenceItem

_SOURCE_TYPE = {
    "fir_narrative": "FIR_RECORD",
    "criminal_profile": "CRIMINAL_RECORD",
    "community_summary": "COMMUNITY_SUMMARY",
}


def _drop_dangling(rows: list[dict]) -> list[dict]:
    """Discard hits whose source record no longer exists.

    The index is rebuilt with the record layer, so this should never fire — but a citation
    pointing at a deleted case is the one failure this system must not have, and "should
    never happen" is not a guarantee. Cheap check, absolute payoff.
    """
    from data import ds

    case_ids = [r["source_id"] for r in rows if r["collection"] == "fir_narrative"]
    person_ids = [r["source_id"] for r in rows if r["collection"] == "criminal_profile"]
    if not case_ids and not person_ids:
        return rows

    live: set[str] = set()
    if case_ids:
        live |= {str(r["CaseMasterID"]) for r in ds.query(
            'SELECT "CaseMasterID" FROM "CaseMaster" WHERE "CaseMasterID" IN :ids',
            {"ids": [int(i) for i in case_ids]})}
    if person_ids:
        live |= {str(r["PersonUID"]) for r in ds.query(
            'SELECT "PersonUID" FROM "vx_person" WHERE "PersonUID" IN :ids',
            {"ids": [int(i) for i in person_ids]})}
    return [r for r in rows if r["source_id"] in live
            or r["collection"] not in ("fir_narrative", "criminal_profile")]


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
            # This is cosine/BM25 similarity to the query text, not evidential
            # support — a semantically close record can be about a different crime
            # entirely (see BUG-011). It still drives the evaluator's relevance
            # floor and gets cited when it clears it, but the UI must render it as
            # what it is, not as "confidence this claim is true".
            confidence_kind="similarity",
        )
        for r in rows
    ]
    return rows, evidence
