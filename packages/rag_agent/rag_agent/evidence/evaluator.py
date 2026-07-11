"""Corrective-RAG evidence evaluator (Yan et al., 2024).

Scores the retrieved batch and returns one of three verdicts:
    ACCEPT  -> synthesise an answer from this evidence
    REFINE  -> widen the query and retry once
    REJECT  -> say "not found in the available records", and say nothing else

REJECT existing at all is the single most important property in this system. An
investigative assistant that fabricates a plausible associate or a plausible prior
is worse than one that returns nothing, because the fabrication is actionable. So
the "no evidence -> no answer" path is a hard structural rule here, not a prompt
instruction that a model may or may not follow.
"""
from typing import Literal

from ..state import EvidenceItem

Verdict = Literal["ACCEPT", "REFINE", "REJECT"]

ACCEPT_THRESHOLD = 0.45     # mean confidence of the batch
MIN_ITEMS = 1


TOP_K = 5
RELEVANCE_FLOOR = 0.5      # below this an item is context, not support


def score_batch(evidence: list[EvidenceItem]) -> float:
    """Score the RELEVANT evidence, not everything retrieved.

    CRAG's evaluator judges each retrieved document as supporting or not, and that
    distinction is what this reproduces. Retrieval deliberately casts wide —
    HippoRAG pulls in a whole PageRank neighbourhood, most of which is context. Two
    naive statistics both fail here:
      - the mean over all items lets a dozen weak graph-proximity hits outvote an
        exact FIR record, so the engine refuses a question it holds the record for;
      - a blind top-k mean has the same defect whenever the decisive record is
        alone (one 0.95 FIR among four 0.05 neighbours averages to 0.23).
    A single exact record IS sufficient support. So: keep the items above the
    relevance floor and score those; if none clear it, the batch is context-only and
    the honest answer is that nothing was found.
    """
    if not evidence:
        return 0.0
    relevant = [e for e in evidence if e.confidence >= RELEVANCE_FLOOR]
    if not relevant:
        return max(e.confidence for e in evidence)      # too weak — will be rejected

    top = sorted((e.confidence for e in relevant), reverse=True)[:TOP_K]
    best = sum(top) / len(top)
    # corroboration: independent source types agreeing beats one loud source
    distinct_sources = len({e.source_type for e in relevant})
    corroboration = min(0.15, 0.05 * (distinct_sources - 1))
    return min(1.0, best + corroboration)


def evaluate(evidence: list[EvidenceItem], attempts: int) -> tuple[Verdict, float, str]:
    """Returns (verdict, confidence, plain-language detail for the trace)."""
    confidence = score_batch(evidence)

    if len(evidence) < MIN_ITEMS:
        if attempts < 1:
            return "REFINE", confidence, "No evidence retrieved — widening the query"
        return "REJECT", 0.0, "No supporting records found after widening"

    if confidence < ACCEPT_THRESHOLD:
        if attempts < 1:
            return ("REFINE", confidence,
                    f"{len(evidence)} weak matches (confidence {confidence:.2f}) — widening")
        return ("REJECT", confidence,
                f"Evidence too weak to support an answer (confidence {confidence:.2f})")

    return ("ACCEPT", confidence,
            f"{len(evidence)} corroborating records (confidence {confidence:.2f})")


NOT_FOUND_MESSAGE = (
    "I could not find this in the available records. Rather than infer an answer, "
    "I am reporting that no supporting evidence was retrieved — please refine the "
    "query, or check whether the record exists in the system."
)
