"""Synthesis routing — QuickML only for operations where a narrative adds something
the extractive template doesn't already say.

Found live (2026-08-28): synthesize() called the LLM for EVERY answer, including a
plain FIR status lookup, at 20-30s per call regardless of how simple the underlying
fact was. Fixed by gating on intents.NEEDS_NARRATIVE_SYNTHESIS — these tests lock in
the gate itself, not the specific operation list (which belongs to intents.py).
"""
from rag_agent.agents import synthesis_agent
from rag_agent.state import EvidenceItem


def _ev(content="a fact", eid="e1"):
    return EvidenceItem(evidence_id=eid, source_type="FIR_RECORD", source_id="s",
                         content=content, confidence=0.9)


def test_a_simple_factual_operation_never_calls_the_model(monkeypatch):
    monkeypatch.setattr(synthesis_agent, "available", lambda: True)

    def fail_if_called(*a, **k):
        raise AssertionError("LLM must not be called for a simple factual operation")
    monkeypatch.setattr(synthesis_agent, "generate", fail_if_called)

    answer, citations = synthesis_agent.synthesize(
        "what is the status of this FIR", [_ev()], operation="FIR_LOOKUP")
    assert "a fact" in answer
    assert len(citations) == 1


def test_a_narrative_operation_calls_the_model_when_available(monkeypatch):
    monkeypatch.setattr(synthesis_agent, "available", lambda: True)
    monkeypatch.setattr(synthesis_agent, "generate", lambda *a, **k: "a fluent answer [1]")

    answer, citations = synthesis_agent.synthesize(
        "what stands out in the money trail", [_ev()], operation="FINANCIAL")
    assert answer == "a fluent answer [1]"


def test_a_narrative_operation_falls_back_when_the_model_is_unavailable(monkeypatch):
    monkeypatch.setattr(synthesis_agent, "available", lambda: False)

    def fail_if_called(*a, **k):
        raise AssertionError("must not call generate() when unavailable")
    monkeypatch.setattr(synthesis_agent, "generate", fail_if_called)

    answer, citations = synthesis_agent.synthesize(
        "what stands out", [_ev()], operation="FINANCIAL")
    assert "a fact" in answer  # extractive fallback, still grounded


def test_a_narrative_operation_falls_back_when_the_model_raises(monkeypatch):
    monkeypatch.setattr(synthesis_agent, "available", lambda: True)

    def explode(*a, **k):
        raise RuntimeError("degraded")
    monkeypatch.setattr(synthesis_agent, "generate", explode)

    answer, citations = synthesis_agent.synthesize(
        "why is this person high risk", [_ev()], operation="RISK")
    assert "a fact" in answer  # never fails the turn


def test_an_unspecified_operation_defaults_to_the_safe_extractive_path(monkeypatch):
    """No operation passed (e.g. a call site that hasn't been updated) must not
    silently start paying the LLM cost for something not opted into the narrative set."""
    monkeypatch.setattr(synthesis_agent, "available", lambda: True)

    def fail_if_called(*a, **k):
        raise AssertionError("an unrecognized/unspecified operation must not call the model")
    monkeypatch.setattr(synthesis_agent, "generate", fail_if_called)

    answer, citations = synthesis_agent.synthesize("some query", [_ev()])
    assert "a fact" in answer


def test_empty_evidence_never_calls_the_model_regardless_of_operation(monkeypatch):
    monkeypatch.setattr(synthesis_agent, "available", lambda: True)

    def fail_if_called(*a, **k):
        raise AssertionError("no evidence means nothing to synthesize")
    monkeypatch.setattr(synthesis_agent, "generate", fail_if_called)

    answer, citations = synthesis_agent.synthesize("what stands out", [], operation="FINANCIAL")
    assert citations == []
