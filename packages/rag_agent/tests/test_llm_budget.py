"""The QuickML call-budget guard (llm.py) — a defense-in-depth spend cap independent
of Zoho's own console-level billing budget. See llm.py's MAX_CALLS docstring: this is
a call-count ceiling, not a rupee figure, because QuickML's real per-call cost isn't
published anywhere this code can read.

The root conftest's `_reset_llm_call_budget` fixture clears the counter before and
after every test, so each test here starts from zero without doing it by hand.
"""
from rag_agent import llm


def test_budget_starts_at_zero_and_is_not_exhausted():
    assert llm.calls_used() == 0
    assert llm.budget_exhausted() is False


def test_record_call_increments_the_persisted_counter():
    llm._record_call()
    llm._record_call()
    assert llm.calls_used() == 2


def test_budget_exhausted_once_the_cap_is_reached(monkeypatch):
    monkeypatch.setattr(llm, "MAX_CALLS", 3)
    for _ in range(3):
        llm._record_call()
    assert llm.budget_exhausted() is True


def test_available_degrades_to_false_when_budget_exhausted_even_if_configured(monkeypatch):
    monkeypatch.setattr(llm, "_configured", lambda: True)
    monkeypatch.setattr(llm, "MAX_CALLS", 1)
    llm._record_call()
    assert llm.available() is False


def test_status_reports_budget_exhaustion_honestly(monkeypatch):
    monkeypatch.setattr(llm, "_configured", lambda: True)
    monkeypatch.setattr(llm, "MAX_CALLS", 1)
    llm._record_call()
    assert "budget exhausted" in llm.status()
    assert "1/1" in llm.status()
