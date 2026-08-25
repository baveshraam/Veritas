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
    kind: Literal["map", "network", "sankey", "trend", "none"] = "none"
    data: dict = Field(default_factory=dict)


class InvestigationState(BaseModel):
    session_id: str
    officer_id: str
    officer_role: str
    original_query: Optional[str] = None
    language: Literal["en", "kn"] = "en"

    input_audio: Optional[bytes] = None
    respond_with_voice: bool = False
    output_audio: Optional[bytes] = None

    active_entities: SessionFocus = Field(default_factory=SessionFocus)
    decomposed_subqueries: list[str] = Field(default_factory=list)

    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    graph_query_results: list[dict] = Field(default_factory=list)
    sql_query_results: list[dict] = Field(default_factory=list)
    vector_search_results: list[dict] = Field(default_factory=list)
    prediction_results: dict[str, Any] = Field(default_factory=dict)

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
