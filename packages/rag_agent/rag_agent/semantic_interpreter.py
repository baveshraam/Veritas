"""Semantic investigation request interpreter.

Decomposes a natural officer query into a structured request independent of the
30-keyword-intent classifier. The LLM path (QuickML generate_json) produces rich
understanding when available; the deterministic path (reusing intents.classify)
runs always and produces identical SemanticRequest shape.

The 30 current intents become the values `operation` is allowed to take —
an implementation compatibility layer, not something removed.
"""
from datetime import date
from typing import Any, Literal, Optional

from data import SessionFocus
from data.models import ConversationTurn
from data.nlp import ner_extract

from . import intents
from .agents import sql_agent
from .llm import LLMUnavailable, generate_json


class SemanticRequest:
    """Structured decomposition of what the officer is asking for.

    All fields are deterministic across both LLM and fallback paths; the paths
    differ only in confidence scores and the richness of context they extract.
    """
    def __init__(
        self,
        operation: str,
        subject_type: Literal["person", "case", "location", "account", "none"] = "none",
        subject_id: Optional[str] = None,
        subject_text: Optional[str] = None,
        reference_kind: Literal["explicit", "pronoun", "positional", "implicit_from_focus"] = "implicit_from_focus",
        constraints: Optional[dict[str, Any]] = None,
        previous_result_context: Optional[dict[str, Any]] = None,
        comparison_entities: Optional[list[str]] = None,
        exploration_direction: Optional[str] = None,
        clarification_response: Optional[str] = None,
        ambiguous_candidates: Optional[list[str]] = None,
        refusal_reason: Optional[str] = None,
        confidence: float = 0.0,
    ):
        self.operation = operation
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.subject_text = subject_text
        self.reference_kind = reference_kind
        self.constraints = constraints or {}
        self.previous_result_context = previous_result_context or {}
        self.comparison_entities = comparison_entities or []
        self.exploration_direction = exploration_direction
        self.clarification_response = clarification_response
        self.ambiguous_candidates = ambiguous_candidates or []
        self.refusal_reason = refusal_reason
        self.confidence = confidence


def interpret(
    query: str,
    language: str,
    focus: SessionFocus,
    prior_turn: Optional[ConversationTurn] = None,
) -> SemanticRequest:
    """Interpret a query as a structured semantic request.

    Tries LLM path first (QuickML generate_json); falls back to deterministic
    intents.classify() on any LLM failure. Both paths produce identical
    SemanticRequest shape.
    """
    # Try LLM path if available — currently always fails (QuickML unreachable)
    # so this always falls through to deterministic path. When QUICKML_ENDPOINT_KEY
    # is obtained, this path activates with no further code change.
    try:
        return _interpret_llm(query, language, focus, prior_turn)
    except (LLMUnavailable, ValueError, KeyError):
        # LLM unavailable or returned malformed output; use deterministic path
        pass

    return _interpret_deterministic(query, language, focus, prior_turn)


def _interpret_llm(
    query: str,
    language: str,
    focus: SessionFocus,
    prior_turn: Optional[ConversationTurn] = None,
) -> SemanticRequest:
    """LLM-based semantic interpretation (currently always fails, kept for future)."""
    schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "description": "one of the 30 investigation operations",
            },
            "subject_type": {
                "type": "string",
                "enum": ["person", "case", "location", "account", "none"],
            },
            "subject_text": {
                "type": ["string", "null"],
                "description": "how the officer named the subject, if present",
            },
            "reference_kind": {
                "type": "string",
                "enum": ["explicit", "pronoun", "positional", "implicit_from_focus"],
            },
            "constraints": {
                "type": "object",
                "description": "date_range, crime_type, district, etc.",
            },
            "comparison_entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "for 'both of them', 'compare these'",
            },
            "exploration_direction": {
                "type": ["string", "null"],
                "enum": ["deeper", "wider", "more_samples", None],
            },
            "clarification_response": {
                "type": ["string", "null"],
                "description": "if answering 'which one did you mean'",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        "required": ["operation", "subject_type", "reference_kind", "confidence"],
    }

    # Build context prompt from prior turn if present
    prior_context = ""
    if prior_turn:
        prior_context = f"\nPrevious turn: {prior_turn.query[:200]}\nAnswer: {prior_turn.final_answer[:200]}\n"

    prompt = f"""You are a police investigation assistant. Decompose this officer query into structured semantic concepts.

Query: {query}
Language: {language}
Current focus: person={focus.active_person}, case={focus.active_fir}, location={focus.active_location}
{prior_context}

Interpret the query as:
- operation: what they want done (lookup_person, count_crimes, find_network, explain_reasoning, etc.)
- subject_type: person/case/location/account/none
- subject_text: how they named it
- reference_kind: explicit name, pronoun, positional ("the second one"), or implicit (from focus)
- constraints: extracted filters (date, crime type, district)
- exploration_direction: if asking to "go deeper" or "show more"
- confidence: 0.5-1.0 (higher = confident interpretation)
- comparison_entities: for "both of them", "compare"

Never invent information. If the query is unclear, set operation="unknown"."""

    result_json = generate_json(prompt, schema)
    if not result_json:
        raise LLMUnavailable("LLM returned empty response")

    # Resolve subject_id from subject_text if present
    subject_id = None
    subject_type = result_json.get("subject_type", "none")
    subject_text = result_json.get("subject_text")

    if subject_text and subject_type == "person":
        hits = sql_agent.person_by_name(subject_text)
        if hits:
            if len(hits) > 1 and hits[0].get("record_count", 0) == hits[1].get("record_count", 0):
                # Ambiguous
                return SemanticRequest(
                    operation=result_json.get("operation", "unknown"),
                    subject_type="person",
                    subject_text=subject_text,
                    reference_kind=result_json.get("reference_kind", "explicit"),
                    ambiguous_candidates=[h["name_en"] for h in hits[:4]],
                    confidence=result_json.get("confidence", 0.7),
                )
            subject_id = str(hits[0]["person_id"])

    return SemanticRequest(
        operation=result_json.get("operation", "unknown"),
        subject_type=subject_type,
        subject_id=subject_id,
        subject_text=subject_text,
        reference_kind=result_json.get("reference_kind", "explicit"),
        constraints=result_json.get("constraints", {}),
        comparison_entities=result_json.get("comparison_entities", []),
        exploration_direction=result_json.get("exploration_direction"),
        confidence=result_json.get("confidence", 0.7),
    )


def _interpret_deterministic(
    query: str,
    language: str,
    focus: SessionFocus,
    prior_turn: Optional[ConversationTurn] = None,
) -> SemanticRequest:
    """Deterministic path: reuses intents.classify() + resolve_focus() + constraint extraction.

    This is the always-available fallback, and must produce output shape identical to
    the LLM path so no downstream changes are needed.
    """
    q = query or ""

    # Classify intent (existing keywords + regex shapes)
    operation = intents.classify(q)

    # Extract entities and update focus
    updated_focus, entities = intents.resolve_focus(q, focus)

    # Determine reference kind
    reference_kind = "implicit_from_focus"
    named_person = intents.named_person(entities)
    if named_person:
        reference_kind = "explicit"
    elif intents.has_unresolved_reference(q, entities):
        reference_kind = "pronoun"

    # Resolve subject if present
    subject_type = "none"
    subject_id = None
    subject_text = None
    ambiguous_candidates = []

    if named_person:
        subject_type = "person"
        subject_text = named_person
        hits = sql_agent.person_by_name(named_person)
        if hits:
            if len(hits) > 1 and hits[0].get("record_count", 0) == hits[1].get("record_count", 0):
                # Ambiguous — don't guess
                ambiguous_candidates = [h["name_en"] for h in hits[:4]]
            else:
                subject_id = str(hits[0]["person_id"])
        # If no hits, subject_text is set but subject_id remains None — will fail later
    elif intents.has_unresolved_reference(q, entities):
        # Pronoun, resolve against focus or prior turn
        if focus.active_person:
            subject_type = "person"
            subject_id = focus.active_person
            reference_kind = "pronoun"
        else:
            # No active person in focus — check prior turn for recent candidates
            # (e.g., CASE_PEOPLE that lists several accused without auto-resolving one)
            candidates = _recent_person_candidates_from_prior(prior_turn)
            if len(candidates) >= 2:
                # Genuinely ambiguous — ask which one, same as a tied name search
                ambiguous_candidates = candidates[:4]
            elif len(candidates) == 1:
                # Only one candidate from prior turn — resolve to it
                subject_type = "person"
                subject_text = candidates[0]
                hits = sql_agent.person_by_name(candidates[0])
                if hits:
                    subject_id = str(hits[0]["person_id"])
            reference_kind = "pronoun"

    # Extract constraints
    constraints = _extract_constraints(q)

    # Read previous-result context if prior turn exists and operation matches expected types
    previous_result_context = {}
    if prior_turn:
        previous_result_context = _extract_previous_result_context(prior_turn, operation)

    # Assign confidence: regex shapes are more confident than keyword matches
    confidence = 0.9 if operation != "UNKNOWN" else 0.3
    if operation in ["CAPABILITY", "NOT_INFERABLE", "EXPLAIN_REASONING", "EVIDENCE_FOR",
                     "CASE_LOCATIONS", "CASE_REFERENCE_UNSUPPORTED", "TIMELINE", "TIMELINE_CONNECTION",
                     "BOARD_PIN_EVENT"]:
        confidence = 0.95  # Regex-shape matches are high-confidence

    refusal_reason = None
    if ambiguous_candidates:
        refusal_reason = "ambiguous_person"
    elif operation == "UNKNOWN":
        refusal_reason = "cannot_understand"

    return SemanticRequest(
        operation=operation,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_text=subject_text,
        reference_kind=reference_kind,
        constraints=constraints,
        previous_result_context=previous_result_context,
        ambiguous_candidates=ambiguous_candidates,
        refusal_reason=refusal_reason,
        confidence=confidence,
    )


def _extract_constraints(query: str) -> dict[str, Any]:
    """Extract explicit constraints from query: date range, crime type, district, etc.

    Existing orchestrator has _crime_type_from_query, _district_code, _date_range_from_query
    scattered through _run_specialists. Consolidate them here.
    """
    constraints = {}

    # TODO: integrate existing constraint extractors if they're worth reusing.
    # For now, leave empty — orchestrator's existing per-intent constraint extraction
    # can continue inline. This field is here for future enrichment.

    return constraints


def _extract_previous_result_context(turn: ConversationTurn, current_operation: str) -> dict[str, Any]:
    """Extract context about what the previous turn returned.

    Used to handle follow-ups like "only these?", "the second one", "go deeper".
    Reads the stored citations and evidence from the prior turn.
    """
    context = {}

    if not turn or not turn.citations:
        return context

    # Store the previous operation and citation count
    # (operation is not stored on ConversationTurn today, but citations are)
    context["previous_citation_count"] = len(turn.citations)
    context["previous_citations"] = turn.citations  # Full list for positional lookup

    # If this is a follow-up to a result-set operation, store more context
    if current_operation in ["CRIME_SEARCH", "PERSON_NETWORK", "ALIAS_CHECK"]:
        # The orchestrator knows whether the result was a sample or exhaustive.
        # That information is not persisted on ConversationTurn yet (future work),
        # so we can't reconstruct it here. Note it as a gap.
        pass

    return context


def _recent_person_candidates_from_prior(prior_turn: Optional[ConversationTurn]) -> list[str]:
    """Extract person names from the prior turn's citations.

    Used when a bare pronoun appears after CASE_PEOPLE (which lists accused but doesn't
    auto-resolve one). Lets a follow-up like "does he have priors?" ask which of those
    people, instead of refusing with no names to offer.

    Coupled to CASE_PEOPLE's citation template: "X is accused on this case..." with
    evidence_id prefix "accused:".
    """
    if not prior_turn or not prior_turn.citations:
        return []

    names = []
    seen = set()
    for c in prior_turn.citations:
        eid = c.get("evidence_id") or ""
        if not eid.startswith("accused:"):
            continue
        # Extract name from label like "Usha Naika is accused on this case..."
        label = c.get("label") or ""
        if " is accused on this case" in label:
            name = label.split(" is accused on this case")[0].strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names
