"""Veritas investigation engine — LangGraph multi-agent RAG over the crime graph.

The only two entrypoints apps/api calls:
    run_investigation(state) -> InvestigationState
    generate_copilot_brief(fir_id, officer_role) -> CopilotBrief
"""
from .copilot.brief import generate_copilot_brief
from .orchestrator import run_investigation
from .state import (
    AgentTraceEntry, Citation, CopilotBrief, EvidenceItem, InvestigationState,
    SessionFocus, VisualizationPayload,
)

__all__ = [
    "run_investigation", "generate_copilot_brief",
    "InvestigationState", "SessionFocus", "EvidenceItem", "Citation",
    "AgentTraceEntry", "VisualizationPayload", "CopilotBrief",
]
