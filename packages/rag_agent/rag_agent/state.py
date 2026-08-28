"""Canonical data contracts for the investigation engine.

Other folders mirror these; don't redefine them. SessionFocus is imported from
`data` (it maps 1:1 to the session table's active_* columns and data's write
helpers take/return it — defining it here would make data import rag_agent, which
is a cycle). Re-exported so callers can still get it from one place.
"""
from datetime import datetime
from typing import Any, Literal, Optional

from data import SessionFocus  # noqa: F401  (canonical definition lives in data)
from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal["FIR_RECORD", "CRIMINAL_RECORD", "GRAPH_RELATIONSHIP",
                         "COMMUNITY_SUMMARY", "ML_PREDICTION", "GEOSPATIAL_ANALYSIS"]
    source_id: str
    source_query: Optional[str] = None      # the exact SQL/Cypher that produced this
    content: str
    confidence: float
    # confidence measures RELEVANCE — how strongly this item supports the claim it is
    # cited for. It is not the right axis for a different kind of item: a specialist
    # agent's own authoritative statement that it looked and found nothing (or that it
    # cannot produce an estimate at all). That statement isn't "weak evidence" scored
    # low because it's off-topic — it's the complete, correct answer, and its
    # confidence field is either unused (0.0, "not applicable") or reused to mean
    # something else ("certainty of the negative finding"). Conflating the two meant a
    # floor built to separate support from noise also deleted honest refusals: the
    # CAUSAL agent's "no estimate can be produced" (deliberately confidence=0.0) was
    # silently dropped by the RELEVANCE_FLOOR check, leaving unrelated vector hits as
    # the only citations for a causal question. `authoritative` is the second axis:
    # true for exactly the specialist-produced statements (positive or negative) that
    # settle the question on their own — see evidence.evaluator.supporting/evaluate.
    authoritative: bool = False
    # What `confidence` actually measures for this item — a category, not a
    # calibration claim. "support": an exact/structural match (a FIR record, a graph
    # relationship, a stated finding) — the number genuinely means "how strongly this
    # backs the claim". "similarity": raw hybrid dense+BM25 text similarity to the
    # query — a real number, but it measures textual proximity, not evidential
    # support, and must never be displayed or reasoned about as if it were the same
    # thing as "support". "model_estimate": an ML_PREDICTION item's ranking weight —
    # a heuristic the evaluator uses to corroborate/rank, distinct from the model's
    # own reported score/probability, which lives in `content`, not here.
    confidence_kind: Literal["support", "similarity", "model_estimate"] = "support"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Citation(BaseModel):
    index: int                               # 1-based — matches the [1] FIR/... render
    evidence_id: str
    label: str


class AgentTraceEntry(BaseModel):
    step: str
    detail: str
    duration_ms: Optional[int] = None
    confidence: Optional[float] = None


class VisualizationPayload(BaseModel):
    kind: Literal["map", "network", "sankey", "trend", "timeline", "none"] = "none"
    data: dict = Field(default_factory=dict)


class InvestigationState(BaseModel):
    session_id: str
    officer_id: str
    officer_role: str
    original_query: Optional[str] = None
    language: Literal["en", "kn"] = "en"
    # The pre-translation Kannada string, set by node_translate_in and never
    # overwritten. Lets entity extraction reach closed-format entities (district,
    # FIR number, IPC, plate) directly, instead of depending on translation quality
    # for anything that has a checkable, script-independent shape.
    original_query_kn: Optional[str] = None

    input_audio: Optional[bytes] = None
    respond_with_voice: bool = False
    output_audio: Optional[bytes] = None

    active_entities: SessionFocus = Field(default_factory=SessionFocus)
    decomposed_subqueries: list[str] = Field(default_factory=list)
    # Which evidence card the officer had selected in the console when they said
    # "pin this" — an ephemeral per-turn UI hint (apps/web tracks it as `activeEvidence`
    # already), not identity focus, so it does not belong in SessionFocus/vx_session.
    active_evidence_id: Optional[str] = None
    # Set only by a BOARD_* intent (see orchestrator._handle_board_intent) — the
    # outcome of a board mutation/read, which node_synthesize turns into the answer
    # instead of running the normal evidence-citation path (a board action is not a
    # retrieval, and has nothing for CRAG to score).
    board_result: Optional[dict[str, Any]] = None
    # Whether the FINAL rendered answer is a genuine refusal — set explicitly, by
    # node_synthesize, at the exact point a refusal-shaped answer is produced.
    # Deliberately NOT derived from requires_escalation or "citations is empty":
    # requires_escalation is set generically whenever a refusal_reason existed
    # BEFORE synthesis even when synthesis goes on to answer successfully (a found
    # EXPLAIN_REASONING/EVIDENCE_FOR prior turn), and CAPABILITY/BOARD_* answers
    # carry no citations while still being real, successful answers. The console
    # colors a refusal differently from a normal answer (apps/web ChatPane.tsx), and
    # inferring that from citation count alone painted every successful
    # citation-free answer — including a board confirmation like "Pinned this
    # evidence..." — in the same red as "I could not find this in the records."
    answer_is_refusal: bool = False

    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    graph_query_results: list[dict] = Field(default_factory=list)
    sql_query_results: list[dict] = Field(default_factory=list)
    vector_search_results: list[dict] = Field(default_factory=list)
    prediction_results: dict[str, Any] = Field(default_factory=dict)
    # Set by _run_specialists at the same point a bounded/sampled result is produced
    # (CRIME_SEARCH's count+samples, PERSON_NETWORK/ALIAS_CHECK/SIMILAR_CASES' caps).
    # Persisted onto ConversationTurn.result_context so a follow-up turn ("only
    # these?", "the second one", "same thing for Bengaluru") can read a real fact
    # about what was actually shown instead of the interpreter re-guessing.
    result_context: dict[str, Any] = Field(default_factory=dict)
    # Constraints named in THIS turn (crime_type, district) or carried forward from
    # a "same thing for Bengaluru"-shaped constraint-change follow-up (see
    # semantic_interpreter._REPEAT_CUE_RE). Read by _run_specialists before falling
    # back to its own per-query extraction, so a carried-forward crime type from the
    # prior turn survives a follow-up that only names a new district.
    constraints: dict[str, Any] = Field(default_factory=dict)
    # Two resolved person_ids for a bounded deterministic comparison ("check
    # whether either of those people had a prior case in Bengaluru") — see
    # semantic_interpreter._COORDINATION_RE / orchestrator._handle_comparison.
    # Empty for every ordinary single-subject turn.
    comparison_subject_ids: list[str] = Field(default_factory=list)
    # A general N-step investigation plan, set only by semantic_interpreter's LLM
    # path (see SemanticRequest.plan_steps) — each dict already carries a validated
    # operation from intents.ALL_OPERATIONS plus a subject reference. Empty for
    # every ordinary single-op turn and for the bounded deterministic two-entity
    # comparison above, which is unrelated and unchanged. See
    # orchestrator._run_plan.
    plan_steps: list[dict[str, Any]] = Field(default_factory=list)
    # This turn's own structured request (operation/subject/constraints), snapshotted
    # once in node_orchestrate and never touched by any specialist branch — unlike
    # result_context, which several branches overwrite wholesale to record a bounded/
    # sampled result. apps/api's chat router merges this into the persisted turn's
    # result_context under "last_request", so the NEXT turn's interpreter can read
    # what was actually asked (not just the prose answer) when deciding whether this
    # turn is a correction to it. See semantic_interpreter._interpret_llm.
    last_request: dict[str, Any] = Field(default_factory=dict)

    final_answer: Optional[str] = None
    citations: list[Citation] = Field(default_factory=list)
    visualization: VisualizationPayload = Field(default_factory=VisualizationPayload)

    confidence_score: float = 0.0
    requires_escalation: bool = False
    # Set when the query named a specific record (a FIR number) that the store does
    # not hold. Semantic neighbours of a nonexistent FIR are not evidence about it.
    exact_lookup_missed: bool = False
    # Set when the query named a record identifier and the store HELD it. The exact
    # record is then the whole answer, so semantic neighbours are not run — see
    # orchestrator._run_specialists.
    exact_lookup_hit: bool = False
    # Which of the refusal situations applies, when one does. See
    # evidence.evaluator.REFUSAL_MESSAGES — "no evidence retrieved" and "you named no
    # subject to search for" are different facts and must not share a sentence.
    refusal_reason: str = ""
    # Set only when a named person matches more than one record with no clear leader
    # (tied record_count) — see node_orchestrate. Carries the candidate names so the
    # clarification question can name them, without guessing which one was meant.
    ambiguous_candidates: list[str] = Field(default_factory=list)
    agent_trace: list[AgentTraceEntry] = Field(default_factory=list)

    # Internal routing (not part of the API surface).
    intent: str = "UNKNOWN"
    retrieval_attempts: int = 0

    model_config = {"arbitrary_types_allowed": True}


class CopilotBrief(BaseModel):
    fir_id: str
    timeline: list[dict]
    similar_cases: list[dict]
    leads: list[str]
    draft_summary: str
