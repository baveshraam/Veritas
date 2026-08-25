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


def supporting(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    """The items that actually support an answer, as opposed to surrounding context.

    This is the distinction CRAG's evaluator exists to draw, and it was being computed
    and then discarded: score_batch() used it to decide *whether* to answer, and
    synthesis then cited the whole batch anyway. That is how "what is the status of FIR
    100050510202600037?" came back with the right FIR at [1] and five cyber-crime cases
    from another district at [2]-[6] — every one of them a real record, none of them
    evidence for the question asked. One floor, one meaning, used in both places.
    """
    return [e for e in evidence if e.confidence >= RELEVANCE_FLOOR]


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
    relevant = supporting(evidence)
    if not relevant:
        return max(e.confidence for e in evidence)      # too weak — will be rejected

    top = sorted((e.confidence for e in relevant), reverse=True)[:TOP_K]
    best = sum(top) / len(top)
    # corroboration: independent source types agreeing beats one loud source
    distinct_sources = len({e.source_type for e in relevant})
    corroboration = min(0.15, 0.05 * (distinct_sources - 1))
    return min(1.0, best + corroboration)


def evaluate(evidence: list[EvidenceItem], attempts: int,
             exact_lookup_missed: bool = False) -> tuple[Verdict, float, str]:
    """Returns (verdict, confidence, plain-language detail for the trace).

    `exact_lookup_missed` is set when the query named a specific record — a FIR
    number — that the store does not hold. That is a different situation from weak
    evidence, and confidence cannot rescue it: retrieval will happily return the
    nearest narratives it can find, and those are records about something else. A
    named identifier is a yes/no claim about one row, so a miss is a refusal
    regardless of how confident the neighbourhood looks.
    """
    confidence = score_batch(evidence)

    if exact_lookup_missed:
        return ("REJECT", 0.0,
                "The FIR number in the query matches no record within policy scope")

    if len(supporting(evidence)) < MIN_ITEMS:
        # Note "supporting", not "evidence". A batch can be full and still support
        # nothing — a dozen semantic neighbours a shade under the floor used to average
        # their way past ACCEPT_THRESHOLD and be cited as though they answered the
        # question. score_batch()'s own docstring already said a batch that clears
        # nothing is context-only; the code did not act on it.
        if attempts < 1:
            return "REFINE", confidence, "Nothing retrieved supports an answer — widening"
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

# Five different situations were all reported with NOT_FOUND_MESSAGE, which tells the
# officer to "check whether the record exists" when the actual problem is that the
# question named no record to look for. Refusing is right; refusing for a reason that
# is not the reason is a false statement about the records.
#
# Every message here still refuses. None of them answers, and none of them softens
# "not found in the records" into "does not exist".
REFUSAL_MESSAGES: dict[str, str] = {
    "no_evidence": NOT_FOUND_MESSAGE,
    "exact_lookup_missed": (
        "No record with that number exists within your access scope. A record "
        "identifier is a claim about one specific case, so I will not answer it from "
        "similar cases — please check the number, or ask an officer with wider scope."
    ),
    "no_subject": (
        "This question needs a subject before I can search for it: name the person, "
        "the case, or the district. Choosing one myself would mean answering a "
        "question you did not ask."
    ),
    "person_not_on_file": (
        "No person of that name appears in the records available to you. I have not "
        "substituted a similarly-spelled name — if you expected a match, the record "
        "may be filed under a different spelling, or outside your access scope."
    ),
    "not_inferable": (
        "The records do not answer this. They record who was accused, arrested and "
        "charged; they do not nominate suspects, and I will not infer one. Ask about "
        "a named person, a case, or the people already recorded as accused on a case."
    ),
}


def refusal_message(reason: str) -> str:
    return REFUSAL_MESSAGES.get(reason, NOT_FOUND_MESSAGE)
