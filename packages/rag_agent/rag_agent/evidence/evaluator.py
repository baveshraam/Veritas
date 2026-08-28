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

# The reported confidence when an authoritative finding — not a relevance score —
# is what settled the turn. Matches the number the specialists already use for their
# own high-confidence negative findings (ALIAS_CHECK's "no alias", FINANCIAL's "no
# account linked"), so a batch driven by one of these reads the same in the trace
# whether or not a numeric relevance score happens to exist alongside it.
AUTHORITATIVE_CONFIDENCE = 0.9


def _authoritative(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    return [e for e in evidence if e.authoritative]


def _relevant(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    """Items whose confidence sits on the relevance scale and clears the floor.

    Kept separate from supporting(): an authoritative item's confidence is not
    necessarily a relevance score at all (the CAUSAL decline sets it to 0.0 by
    convention — "not applicable", not "irrelevant"), so it must not be averaged in
    here as though it were one.
    """
    return [e for e in evidence if e.confidence >= RELEVANCE_FLOOR]


def supporting(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    """The items that belong in the citation set: relevance-scored support, plus any
    authoritative statement regardless of what its own confidence number says.

    This is the distinction CRAG's evaluator exists to draw, and it was being computed
    and then discarded: score_batch() used it to decide *whether* to answer, and
    synthesis then cited the whole batch anyway. That is how "what is the status of FIR
    100050510202600037?" came back with the right FIR at [1] and five cyber-crime cases
    from another district at [2]-[6] — every one of them a real record, none of them
    evidence for the question asked. One floor, one meaning, used in both places.

    RELEVANCE_FLOOR alone then went on to silently drop a *different* class of item:
    prediction_agent's CAUSAL branch sets confidence=0.0 by convention when no
    estimate can be produced — a deliberate "not applicable" marker on an authoritative
    refusal, not a relevance score that happens to be low. The floor doesn't know the
    difference, so "why does crime correlate with literacy" lost its honest decline and
    kept only the unrelated criminal profiles that happened to clear 0.5. `authoritative`
    is the second axis this needs: true for exactly the specialist-produced statements,
    positive or negative, that settle the question on their own.
    """
    return _relevant(evidence) + [e for e in evidence if e.authoritative and e.confidence < RELEVANCE_FLOOR]


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
    the honest answer is that nothing was found — unless an authoritative statement
    is present, which evaluate() checks before this score is used to decide anything.
    """
    if not evidence:
        return 0.0
    relevant = _relevant(evidence)
    if not relevant:
        if _authoritative(evidence):
            return AUTHORITATIVE_CONFIDENCE
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
    if exact_lookup_missed:
        return ("REJECT", 0.0,
                "The FIR number in the query matches no record within policy scope")

    authoritative = _authoritative(evidence)
    if authoritative:
        # A specialist has already given its final, complete word on this question —
        # a positive relationship, a stated negative finding, or a declined estimate.
        # None of that is "weak evidence to be scored for relevance and possibly
        # outvoted"; relevance isn't the axis it lives on. And widening cannot improve
        # on an authoritative answer, so this accepts on the first pass rather than
        # retrying — a second identical specialist call would just waste the round trip.
        return ("ACCEPT", max(score_batch(evidence), AUTHORITATIVE_CONFIDENCE),
                "An authoritative finding from the record layer settles this")

    confidence = score_batch(evidence)

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
    "no_case": (
        "This question is about an open case, and none is open in this session: give "
        "me an FIR number, or open one first — then I can answer about it."
    ),
    "case_reference_unsupported": (
        "I do not keep an ordered history of every case opened this session — only "
        "the one currently in view. Name the FIR number of the case you mean to "
        "reopen it; the case you had open before this question is still open."
    ),
    "nothing_prior": (
        "There is nothing earlier in this session to explain — this is the first "
        "answer, so there is no prior evidence or reasoning to point to yet."
    ),
    # Distinct from "nothing_prior" above: CASE_LOCATIONS can fail on turn 7 just as
    # easily as turn 1 (the immediately preceding turn simply didn't cite any FIRs —
    # a refusal, a meta-answer, a capability question). Reusing "this is the first
    # answer" there was a false statement about the session on every turn but the
    # actual first one.
    "nothing_prior_locations": (
        "The previous answer named no cases to map — ask a question that returns "
        "case records first (an FIR lookup, a crime search, similar cases), then ask "
        "where they're concentrated."
    ),
    "board_forbidden": (
        "This case's investigation board is outside your access scope — it was filed "
        "at another police station, the same rule that governs the case record itself."
    ),
    "board_not_found": (
        "No case matches the FIR this board action targets — it may have been "
        "re-scoped since it was opened this session."
    ),
    "ambiguous_person": (
        "More than one person in the records matches that name equally well, and I "
        "will not guess which one you mean — please say more (a case, a district, or "
        "which one) to tell them apart."
    ),
    "no_timeline_subject": (
        "A timeline needs a case or a person to build it around: open a case, name "
        "someone, or ask this right after I've shown you one."
    ),
    "plan_step_unresolved": (
        "One step of this multi-step investigation could not safely resolve who or "
        "what it should look at next — I will not guess. Try naming that step's "
        "subject directly, or ask it as separate questions."
    ),
    "timeline_connection_no_subjects": (
        "I need two people to check for a connection between them — name them both, "
        "or ask this right after I've listed several people on a case so 'both of "
        "them' has someone to mean."
    ),
}


def refusal_message(reason: str) -> str:
    return REFUSAL_MESSAGES.get(reason, NOT_FOUND_MESSAGE)
