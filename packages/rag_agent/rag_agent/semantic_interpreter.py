"""Semantic investigation request interpreter.

Decomposes a natural officer query into a structured request independent of the
30-keyword-intent classifier. The LLM path (QuickML generate_json) produces rich
understanding when available; the deterministic path (reusing intents.classify)
runs always and produces identical SemanticRequest shape.

The 30 current intents become the values `operation` is allowed to take —
an implementation compatibility layer, not something removed.
"""
import re
from datetime import date
from typing import Any, Literal, Optional

from data import SessionFocus
from data.models import ConversationTurn
from data.nlp import ner_extract

from . import intents
from . import llm
from .agents import sql_agent
from .llm import LLMUnavailable, generate_json

# Below this deterministic confidence, the keyword/regex classifier found nothing (or
# next to nothing) worth trusting — genuine unseen-phrasing/ambiguity territory, which
# is exactly where a semantic model adds value over a confident structural match or a
# confident structural refusal. See interpret()'s docstring for the live-measured
# latency reason this routing exists.
_LLM_ROUTING_THRESHOLD = 0.75


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
        reference_kind: Literal["explicit", "pronoun", "positional", "implicit_from_focus",
                                "exhaustiveness_check", "exploration", "constraint_change"] = "implicit_from_focus",
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

    Deterministic first, always — it costs microseconds and is what
    result-set/positional/pronoun/repeat-cue resolution and every FIR-number exact
    match already run on. QuickML is only invoked when that result is NOT confident
    (below _LLM_ROUTING_THRESHOLD): unseen phrasing, genuinely ambiguous requests, or
    anything the keyword/regex classifier scored as UNKNOWN. This is the hybrid
    routing the architecture always specified but the code never actually did — every
    query, including an exact `FIR 100222201202600022` lookup, was paying a full
    14-30s QuickML round trip before ever reaching the instant deterministic answer
    (measured live 2026-08-28, the day QuickML first went live in production). A
    confident deterministic result — including a confident REFUSAL like an ambiguous-
    name tie, which the model cannot resolve any better since it's a real database
    fact — is used as-is; the LLM is tried only when there is genuine uncertainty for
    it to add value to, falling back to the deterministic result on any LLM failure
    or invalid output either way.
    """
    det = _interpret_deterministic(query, language, focus, prior_turn)
    if det.confidence >= _LLM_ROUTING_THRESHOLD:
        return det
    if not llm.available():
        return det
    try:
        llm_result = _interpret_llm(query, language, focus, prior_turn)
    except (LLMUnavailable, ValueError, KeyError):
        return det
    return llm_result if llm_result.confidence >= det.confidence else det

    return _interpret_deterministic(query, language, focus, prior_turn)


# Model-facing constraints, kept intentionally narrower than SemanticRequest's own
# type hints: reference_kind values like "exhaustiveness_check"/"exploration"/
# "constraint_change" are structural (only ever produced by the shape-matching
# patterns above, against the PRIOR turn's own recorded state) — nothing about a
# fresh utterance licenses the model to invent one. exploration_direction is a
# genuinely model-detectable signal ("go deeper"/"show more"), so it stays.
_LLM_SUBJECT_TYPES = {"person", "case", "location", "account", "none"}
_LLM_REFERENCE_KINDS = {"explicit", "pronoun", "positional", "implicit_from_focus"}
_LLM_EXPLORATION_DIRECTIONS = {"deeper", "wider", "more_samples", None}


def _validate_llm_result(result_json: dict) -> dict:
    """Schema + allowlist + argument validation on the model's raw JSON, before any of
    it is trusted to build a SemanticRequest. Raises ValueError on anything invalid —
    interpret()'s own try/except already treats that as "fall back to deterministic",
    so an invalid model output degrades exactly like an unreachable model, never a
    silently-misrouted turn.

    What this deliberately does NOT do: read a subject_id from the model. The model
    only ever supplies subject_text (how the officer named something); resolving that
    to a real id is this module's own job (sql_agent.person_by_name, below), grounded
    in the actual record layer. A model output has no field this validator would ever
    accept as an identifier, which is the structural version of "the model cannot
    invent entities" rather than a rule enforced by convention.
    """
    if not isinstance(result_json, dict):
        raise ValueError(f"LLM result is not an object: {type(result_json).__name__}")

    operation = result_json.get("operation")
    if not isinstance(operation, str) or not operation.strip():
        raise ValueError("LLM result missing a string 'operation'")
    operation = operation.strip().upper()
    if operation not in intents.ALL_OPERATIONS:
        raise ValueError(f"LLM returned an operation outside the allowlist: {operation!r}")

    subject_type = result_json.get("subject_type", "none")
    if subject_type not in _LLM_SUBJECT_TYPES:
        raise ValueError(f"LLM returned an invalid subject_type: {subject_type!r}")

    reference_kind = result_json.get("reference_kind", "implicit_from_focus")
    if reference_kind not in _LLM_REFERENCE_KINDS:
        raise ValueError(f"LLM returned an invalid reference_kind: {reference_kind!r}")

    subject_text = result_json.get("subject_text")
    if subject_text is not None and not isinstance(subject_text, str):
        raise ValueError("LLM result's subject_text must be a string or null")

    constraints = result_json.get("constraints", {})
    if not isinstance(constraints, dict):
        raise ValueError("LLM result's constraints must be an object")

    comparison_entities = result_json.get("comparison_entities", [])
    if not isinstance(comparison_entities, list) or not all(
            isinstance(x, str) for x in comparison_entities):
        raise ValueError("LLM result's comparison_entities must be a list of strings")

    exploration_direction = result_json.get("exploration_direction")
    if exploration_direction not in _LLM_EXPLORATION_DIRECTIONS:
        raise ValueError(
            f"LLM returned an invalid exploration_direction: {exploration_direction!r}")

    clarification_response = result_json.get("clarification_response")
    if clarification_response is not None and not isinstance(clarification_response, str):
        raise ValueError("LLM result's clarification_response must be a string or null")

    confidence = result_json.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("LLM result's confidence must be a number")
    confidence = max(0.0, min(1.0, float(confidence)))  # miscalibration, not unsafe — clamp

    return {
        "operation": operation, "subject_type": subject_type, "subject_text": subject_text,
        "reference_kind": reference_kind, "constraints": constraints,
        "comparison_entities": comparison_entities,
        "exploration_direction": exploration_direction,
        "clarification_response": clarification_response, "confidence": confidence,
    }


def _interpret_llm(
    query: str,
    language: str,
    focus: SessionFocus,
    prior_turn: Optional[ConversationTurn] = None,
) -> SemanticRequest:
    """LLM-based semantic interpretation. Every field the model returns is validated
    against the real operation allowlist and argument types (_validate_llm_result)
    before anything downstream sees it — see that function's docstring for why
    subject_id specifically is never read from the model at all."""
    schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": sorted(intents.ALL_OPERATIONS),
                "description": "the single investigation operation this query asks for",
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
- operation: exactly one value from the enum given for "operation" — the closest match
  to what the officer is asking for. Never invent a value outside that list.
- subject_type: person/case/location/account/none
- subject_text: how they named the subject, verbatim from the query — never a resolved
  id or a name you infer from outside the query
- reference_kind: explicit name, pronoun, positional ("the second one"), or implicit (from focus)
- constraints: extracted filters (date, crime type, district) — only ones actually named
- exploration_direction: if asking to "go deeper" or "show more"
- confidence: 0.5-1.0 (higher = confident interpretation)
- comparison_entities: for "both of them", "compare"

Never invent information not present in the query or the stated focus. If the query is
unclear or matches no operation well, set operation="UNKNOWN"."""

    result_json = generate_json(prompt, schema)
    if not result_json:
        raise LLMUnavailable("LLM returned empty response")

    validated = _validate_llm_result(result_json)
    operation = validated["operation"]
    subject_type = validated["subject_type"]
    subject_text = validated["subject_text"]

    # Resolve subject_id from subject_text ourselves — the model never supplies one
    # (see _validate_llm_result's docstring). This is the one DB-grounded step in the
    # whole LLM path, and it is identical to what the deterministic path already does.
    subject_id = None
    if subject_text and subject_type == "person":
        hits = sql_agent.person_by_name(subject_text)
        if hits:
            if len(hits) > 1 and hits[0].get("record_count", 0) == hits[1].get("record_count", 0):
                # Ambiguous
                return SemanticRequest(
                    operation=operation,
                    subject_type="person",
                    subject_text=subject_text,
                    reference_kind=validated["reference_kind"],
                    ambiguous_candidates=[h["name_en"] for h in hits[:4]],
                    confidence=validated["confidence"],
                )
            subject_id = str(hits[0]["person_id"])

    return SemanticRequest(
        operation=operation,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_text=subject_text,
        reference_kind=validated["reference_kind"],
        constraints=validated["constraints"],
        comparison_entities=validated["comparison_entities"],
        exploration_direction=validated["exploration_direction"],
        clarification_response=validated["clarification_response"],
        confidence=validated["confidence"],
    )


# --- Structural reference / result-set / exploration patterns -------------------
#
# Each of these matches the SHAPE of a follow-up relative to the previous turn, not
# a specific sentence. They compose with any prior operation/subject/result-set —
# "the fourth transaction" needs no new pattern once "the second one" works, the
# same way intents.py's own EXPLAIN_REASONING/CASE_LOCATIONS shape-checks already
# generalize across topics. None of these fires without a prior_turn (or, for
# pronoun/positional resolution, an active focus) to resolve against — a fresh
# query that happens to contain one of these words with no antecedent falls through
# to the ordinary classify() path unchanged, exactly as it does today.

_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
_ORDINAL_RE = re.compile(
    r"\bthe\s+(" + "|".join(_ORDINAL_WORDS) + r"|\d+(?:st|nd|rd|th))\s+"
    r"(?:one|case|person|fir|associate|record|account|transaction|item)\b"
    r"|\b(?:item|number|record)\s*#?\s*(\d+)\b",
    re.I,
)
_OTHER_RE = re.compile(r"\bthe\s+other\s+(?:one|person)\b", re.I)

# "only these?" / "is that all?" / "what else?" — genuinely ambiguous in English
# between "is this the whole result set" and "tell me more about the subject".
# Disambiguated by context in _interpret_deterministic: a bounded result set from
# the prior turn wins that reading; a subject in focus with no bounded set wins the
# "elaborate" reading. Neither present -> falls through, honestly unresolved.
_AMBIGUOUS_MORE_RE = re.compile(
    r"\bonly\s+these\??\b|\bis\s+that\s+all\??\b|\bare\s+there\s+more\??\b"
    r"|\bany(?:thing)?\s+else\b|\bwhat\s+else\b|\bthat'?s\s+it\??\b"
    r"|\bjust\s+these\??\b|\bmore\s+than\s+(?:this|these|that|those)\??\b",
    re.I,
)
# Unambiguous elaboration cues — never mean "more items of the same list".
_EXPLORATION_ONLY_RE = re.compile(
    r"\bgo\s+deeper\b|\bdig\s+deeper\b|\btell\s+me\s+more\b"
    r"|\bexpand\s+on\s+(?:this|that)\b|\bshow\s+more\b",
    re.I,
)
# A bare "why" / "why this?" / "why those?" with nothing else in the sentence is a
# meta-question about the PREVIOUS answer (EXPLAIN_REASONING already handles this
# fully — orchestrator.py:959ff reads the stored trace, not a fresh search). Whole-
# query anchored so it never steals a real CAUSAL question ("why do more crimes
# happen in poorer districts") that just happens to start with "why".
_BARE_WHY_RE = re.compile(
    r"^\s*(?:but\s+)?why\s*(?:this|that|these|those)?\s*\??\s*$", re.I)
# "yeah but before this?" / "and after that?" — a temporal relation with no noun to
# anchor it beyond "this"/"that". TIMELINE already resolves "before"/"after" from
# the raw query text (orchestrator._TIMELINE_BEFORE_RE/_AFTER_RE); this only widens
# which utterances REACH that handling — same anchoring discipline as _BARE_WHY_RE,
# so "murders before 2020" (a real, fully-specified query) is untouched.
_TEMPORAL_BARE_RE = re.compile(
    r"^\s*(?:yeah,?\s*)?(?:but\s+)?(?:before|after)\s+(?:this|that)\s*\??\s*$", re.I)
# "same thing for Bengaluru" / "what about Mysuru" / "and for Kolar" — repeats the
# PREVIOUS operation with a new constraint, most commonly a district (which
# resolve_focus() already extracts for free via the LOCATION gazetteer). Anchored
# near the start of the query so it doesn't fire mid-sentence on unrelated "what
# about" phrasing.
_REPEAT_CUE_RE = re.compile(
    r"^\s*(?:same\s+(?:thing|query|question)?\s*(?:for|in)\b"
    r"|what\s+about\b|and\s+for\b|and\s+in\b)", re.I)
# The bare two-word form ("And Mysuru?") — found live via the adversarial battery:
# a real officer follow-up to a hotspot answer, with no "for"/"in"/"about" to
# anchor on. Whole-query anchored to a SHORT "and <phrase>?" shape (the same
# discipline _BARE_WHY_RE/_TEMPORAL_BARE_RE already use) rather than a bare
# "and\s+" prefix, so it can't misfire on an unrelated sentence that happens to
# start with "and" ("and then what happened next to the case").
_REPEAT_CUE_BARE_RE = re.compile(r"^\s*and\s+[\w][\w\s]{0,24}\??\s*$", re.I)

# Bounded deterministic multi-step composition (design spec §3): "check whether
# EITHER of those people had a prior case in Bengaluru" / "does she have a record
# AS WELL" / "show me BOTH of their networks". Two-entity comparisons only — three
# or more names is exactly the open-ended planning this deliberately does not
# attempt (needs the LLM path, see ENGINEERING_BRIEF.md §12).
_COORDINATION_RE = re.compile(
    r"\beither of\b|\beither\b.*\bor\b|\bboth of\b|\bboth\b|\band also\b|\bas well\b", re.I)
_BACK_REFERENCE_PAIR_RE = re.compile(
    r"\b(?:those|them|these)\s+(?:people|persons|two)\b|\bboth\s+of\s+them\b", re.I)

# evidence_id prefix -> subject_type, for resolving a positional/'other' reference
# against the previous turn's own numbered citation list (orchestrator.py:1274,
# :359, :465 — assoc:<person_id>, same_as:<person_id>, fir:<fir_id>).
_EVIDENCE_PREFIX_SUBJECT = {"fir": "case", "assoc": "person", "same_as": "person"}


def _ordinal_index(query: str) -> Optional[int]:
    """1-based position named by an ordinal reference ('the second one', 'item 3')."""
    m = _ORDINAL_RE.search(query or "")
    if not m:
        return None
    word = (m.group(1) or "").lower()
    if word in _ORDINAL_WORDS:
        return _ORDINAL_WORDS[word]
    if word[:-2].isdigit():                 # "3rd", "21st"
        return int(word[:-2])
    if m.group(2):
        return int(m.group(2))
    return None


def _citation_subject(citation: dict) -> Optional[tuple[str, str]]:
    """(subject_type, subject_id_or_name) from one of the prior turn's own citations."""
    eid = citation.get("evidence_id") or ""
    prefix, sep, rest = eid.partition(":")
    if not sep or not rest:
        return None
    subject_type = _EVIDENCE_PREFIX_SUBJECT.get(prefix)
    if subject_type:
        return subject_type, rest
    if prefix == "accused":
        # CASE_PEOPLE's citations carry a per-case AccusedID here, not a resolved
        # PersonUID — same reason _recent_person_candidates_from_prior parses the
        # label instead. Returns a NAME, resolved like any other named subject.
        label = citation.get("label") or ""
        if " is accused on this case" in label:
            name = label.split(" is accused on this case")[0].strip()
            if name:
                return "person_name", name
    return None


def _resolve_other_candidate(focus: SessionFocus,
                             prior_turn: Optional[ConversationTurn]) -> Optional[str]:
    """'the other one'/'the other person': among exactly two named candidates from
    the prior turn, the one that is NOT the person currently in focus. Three or
    more candidates makes "the other one" genuinely ambiguous, so this only fires
    on exactly two — the same discipline the tied-name ambiguity check already
    applies elsewhere rather than guessing."""
    candidates = _recent_person_candidates_from_prior(prior_turn)
    if len(candidates) != 2:
        return None
    resolved = [(name, str(hits[0]["person_id"]))
                for name in candidates if (hits := sql_agent.person_by_name(name))]
    others = [name for name, pid in resolved if pid != focus.active_person]
    return others[0] if len(others) == 1 else None


def _default_operation_for_subject(subject_type: str) -> str:
    """What a bare selection ('the second one', with no verb of its own) should
    do once a subject is resolved — the richest single-call profile for that
    subject type, the way an investigator would pull up a file on request."""
    return "CASE_CONTEXT" if subject_type == "case" else "PERSON_HISTORY"


def crime_type_from_query(query: str) -> Optional[str]:
    """Which of the 20 canonical crime types (if any) a question names — the longest
    match wins so "Motor Vehicle Theft" is not shadowed by the bare "Theft" it
    contains. Moved here (from orchestrator.py) so _extract_constraints can reuse
    it without a circular import — orchestrator already imports this module."""
    from data.generator.refdata import crime_type_names
    q = (query or "").lower()
    matches = [ct for ct in crime_type_names() if ct.lower() in q]
    return max(matches, key=len) if matches else None


def _interpret_deterministic(
    query: str,
    language: str,
    focus: SessionFocus,
    prior_turn: Optional[ConversationTurn] = None,
) -> SemanticRequest:
    """Deterministic path: reuses intents.classify() + resolve_focus() + constraint
    extraction, widened by the structural follow-up patterns above.

    This is the always-available fallback, and must produce output shape identical to
    the LLM path so no downstream changes are needed.
    """
    q = query or ""
    prior_result = (prior_turn.result_context if prior_turn else None) or {}

    # --- Structural follow-ups, checked before topic classification -------------
    # Same precedence discipline as intents.classify()'s own regex "shape" checks:
    # these are about what KIND of follow-up this is relative to the last turn, not
    # what topic it names, so they must not lose to an accidental keyword hit.

    if prior_turn and _BARE_WHY_RE.search(q):
        return SemanticRequest(
            operation="EXPLAIN_REASONING", reference_kind="explicit",
            confidence=0.9)

    if prior_turn and _TEMPORAL_BARE_RE.search(q):
        return SemanticRequest(
            operation="TIMELINE", reference_kind="implicit_from_focus",
            confidence=0.85)

    if prior_turn and _AMBIGUOUS_MORE_RE.search(q):
        if prior_result.get("shown_ids") or prior_result.get("total_matched") is not None:
            return SemanticRequest(
                operation="RESULT_SET_FOLLOWUP", reference_kind="exhaustiveness_check",
                previous_result_context=prior_result, confidence=0.9)
        if focus.active_person or focus.active_fir:
            return SemanticRequest(
                operation=_default_operation_for_subject(
                    "case" if focus.active_fir and not focus.active_person else "person"),
                subject_type="person" if focus.active_person else "case",
                subject_id=focus.active_person or focus.active_fir,
                reference_kind="exploration", exploration_direction="wider",
                confidence=0.75)
        # No bounded result and no subject to elaborate on — genuinely nothing to
        # widen. Falls through rather than guessing.

    if prior_turn and _EXPLORATION_ONLY_RE.search(q) and (focus.active_person or focus.active_fir):
        return SemanticRequest(
            operation=_default_operation_for_subject(
                "case" if focus.active_fir and not focus.active_person else "person"),
            subject_type="person" if focus.active_person else "case",
            subject_id=focus.active_person or focus.active_fir,
            reference_kind="exploration", exploration_direction="deeper",
            confidence=0.75)

    if prior_turn:
        idx = _ordinal_index(q)
        resolved_positional = None
        if idx is not None:
            for c in prior_turn.citations:
                if c.get("index") == idx:
                    resolved_positional = _citation_subject(c)
                    break
        elif _OTHER_RE.search(q):
            other_name = _resolve_other_candidate(focus, prior_turn)
            if other_name:
                resolved_positional = ("person_name", other_name)
        if resolved_positional:
            kind, ident = resolved_positional
            base_op = intents.classify(q)          # "does the second one have priors" etc.
            if kind == "person_name":
                hits = sql_agent.person_by_name(ident)
                if hits:
                    op = base_op if base_op != "UNKNOWN" else "PERSON_HISTORY"
                    return SemanticRequest(
                        operation=op, subject_type="person", subject_id=str(hits[0]["person_id"]),
                        subject_text=ident, reference_kind="positional", confidence=0.85)
            elif kind == "person":
                op = base_op if base_op != "UNKNOWN" else "PERSON_HISTORY"
                return SemanticRequest(
                    operation=op, subject_type="person", subject_id=ident,
                    reference_kind="positional", confidence=0.9)
            elif kind == "case":
                op = base_op if base_op != "UNKNOWN" else "CASE_CONTEXT"
                return SemanticRequest(
                    operation=op, subject_type="case", subject_id=ident,
                    reference_kind="positional", confidence=0.9)

    if prior_turn and prior_result.get("operation") and _REPEAT_CUE_RE.search(q):
        # "same thing for Bengaluru": reuse the prior turn's own operation, and
        # overlay the new constraint(s) named in THIS turn's text on top of the
        # prior turn's own constraints — _extract_constraints already finds
        # "Bengaluru" via the same LOCATION gazetteer NER uses elsewhere. Anything
        # not restated (e.g. a crime type from the prior turn) carries forward.
        merged_constraints = {**prior_result.get("constraints", {}), **_extract_constraints(q)}
        return SemanticRequest(
            operation=prior_result["operation"], reference_kind="constraint_change",
            constraints=merged_constraints, previous_result_context=prior_result,
            confidence=0.8)

    if prior_turn and prior_result.get("operation") and _REPEAT_CUE_BARE_RE.search(q):
        # "And Mysuru?" -- the bare two-word form has no "for"/"in"/"about" to
        # anchor on, so it only fires when THIS turn's text actually names a real
        # constraint (a district or crime type) -- otherwise "And then?" or "And
        # why?" would wrongly be read as a repeat-with-new-constraint instead of
        # falling through to their own handling (temporal/why, above).
        new_constraints = _extract_constraints(q)
        if new_constraints:
            merged_constraints = {**prior_result.get("constraints", {}), **new_constraints}
            return SemanticRequest(
                operation=prior_result["operation"], reference_kind="constraint_change",
                constraints=merged_constraints, previous_result_context=prior_result,
                confidence=0.7)

    # Bounded deterministic multi-step composition (design spec §3): "check
    # whether either of those people had a prior case in Bengaluru" — two-entity
    # only, explicitly not open-ended planning (see the module docstring above
    # _COORDINATION_RE). orchestrator._handle_comparison sequences the SAME
    # single-subject retrieval path once per resolved id, unchanged RBAC/CRAG.
    if _COORDINATION_RE.search(q):
        pair = _resolve_comparison_pair(q, prior_turn)
        if len(pair) == 2:
            base_op = intents.classify(q)
            return SemanticRequest(
                operation=base_op if base_op != "UNKNOWN" else "PERSON_HISTORY",
                subject_type="person", comparison_entities=[pid for _, pid in pair],
                constraints=_extract_constraints(q), reference_kind="explicit",
                confidence=0.75)

    # --- Ordinary path (unchanged from the §5.1 migration) -----------------------

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

    # A resolved subject with no operation verb at all -- "Tell me about Usha
    # Naika", "I meant Usha Naika specifically" -- found live via the adversarial
    # battery: neither has a keyword any INTENT recognizes, so this used to reach
    # UNKNOWN and refuse even though a specific, resolved person was RIGHT THERE.
    # Same defaulting principle already used for a bare ordinal/"other" reference
    # (_default_operation_for_subject) -- a named subject with nothing else asked
    # gets the richest single-call profile, not a refusal.
    if operation == "UNKNOWN" and subject_id and subject_type == "person":
        operation = _default_operation_for_subject("person")

    # Extract constraints
    constraints = _extract_constraints(q)

    # Read previous-result context if prior turn exists
    previous_result_context = prior_result

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
    """Explicit constraints named IN this query: crime type (keyword match against
    the 20 canonical types) and district (via the same LOCATION gazetteer NER
    already uses elsewhere). Consolidates what used to be scattered per-intent
    extraction in orchestrator.py into one place the interpreter can read before
    retrieval runs — used directly by constraint-change follow-ups ("same thing for
    Bengaluru"), and available to every operation via SemanticRequest.constraints."""
    constraints: dict[str, Any] = {}
    ct = crime_type_from_query(query)
    if ct:
        constraints["crime_type"] = ct
    for e in ner_extract(query or "", "en"):
        if e.label == "LOCATION":
            constraints["district"] = e.text
            break
    return constraints


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


def _resolve_comparison_pair(query: str, prior_turn: Optional[ConversationTurn]
                             ) -> list[tuple[str, str]]:
    """Two resolved (name, person_id) pairs for a bounded comparison, or [] if the
    query doesn't name/reference exactly two people. Either named explicitly in
    THIS query ("check Ramesh and Suresh for...") or referred back to the prior
    turn's own candidate list ("either of those people") — reuses the exact
    mechanism pronoun resolution already relies on for the latter."""
    names = [e.text for e in ner_extract(query or "", "en") if e.label == "PERSON"]
    if len(names) < 2 and _BACK_REFERENCE_PAIR_RE.search(query or ""):
        names = _recent_person_candidates_from_prior(prior_turn)
    if len(dict.fromkeys(names)) != 2:
        return []
    resolved = []
    for name in dict.fromkeys(names):
        hits = sql_agent.person_by_name(name)
        if hits:
            resolved.append((hits[0]["name_en"], hits[0]["person_id"]))
    return resolved if len(resolved) == 2 else []
