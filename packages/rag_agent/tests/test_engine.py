"""Investigation-engine checks that need no database or LLM."""
import pytest

import networkx as nx

from rag_agent.agents import graph_agent
from rag_agent.agents.synthesis_agent import build_citations
from rag_agent.evidence.evaluator import (
    ACCEPT_THRESHOLD, NOT_FOUND_MESSAGE, evaluate, score_batch,
)
from rag_agent.intents import classify, has_unresolved_reference, visualization_for
from rag_agent.state import EvidenceItem


def _ev(conf: float, source_type: str = "FIR_RECORD", eid: str = "") -> EvidenceItem:
    return EvidenceItem(evidence_id=eid or f"e{conf}", source_type=source_type,
                        source_id="s", content="c", confidence=conf)


# --- CRAG evaluator: the trust guarantee ------------------------------------

def test_no_evidence_is_refused_not_answered():
    verdict, conf, _ = evaluate([], attempts=1)
    assert verdict == "REJECT" and conf == 0.0
    assert "could not find" in NOT_FOUND_MESSAGE


def test_empty_first_attempt_widens_before_giving_up():
    verdict, _, _ = evaluate([], attempts=0)
    assert verdict == "REFINE"


def test_strong_evidence_is_not_vetoed_by_weak_context():
    """A broad HippoRAG neighbourhood must not outvote an exact record.

    Averaging over everything retrieved made the evaluator refuse questions it had
    the FIR for; score_batch scores the top-k instead.
    """
    batch = [_ev(0.95)] + [_ev(0.05) for _ in range(30)]
    assert score_batch(batch) >= ACCEPT_THRESHOLD
    assert evaluate(batch, attempts=0)[0] == "ACCEPT"


def test_uniformly_weak_evidence_still_refuses_after_widening():
    batch = [_ev(0.05) for _ in range(30)]
    assert evaluate(batch, attempts=1)[0] == "REJECT"


def test_corroboration_across_source_types_raises_confidence():
    same = [_ev(0.6, "FIR_RECORD", "a"), _ev(0.6, "FIR_RECORD", "b")]
    mixed = [_ev(0.6, "FIR_RECORD", "a"), _ev(0.6, "GRAPH_RELATIONSHIP", "b")]
    assert score_batch(mixed) > score_batch(same)


# --- policy at traversal time ------------------------------------------------
#
# The depth cap used to be rewritten into the Cypher `*1..n` pattern before the query
# ran. With NetworkX it bounds the walk itself — same rule, same place in the pipeline
# (before any data is reached), so an IO still cannot out-traverse their role.

def _money_chain() -> nx.MultiDiGraph:
    """P owns A0; money flows A0 -> A1 -> A2 -> A3 -> A4, one hop at a time."""
    g = nx.MultiDiGraph()
    g.add_node("P", label="Person")
    for i in range(5):
        g.add_node(f"A{i}", label="Account")
    g.add_edge("P", "A0", rel="OWNS_ACCOUNT", amount=None)
    for i in range(4):
        g.add_edge(f"A{i}", f"A{i+1}", rel="TRANSFERRED_TO", amount=1000.0)
    return g


@pytest.mark.parametrize("role,expected_depth", [("IO", 2), ("SHO", 2), ("DSP", 4), ("IG", 4)])
def test_money_trail_depth_is_capped_by_role(monkeypatch, role, expected_depth):
    monkeypatch.setattr(graph_agent, "load_graph", _money_chain)
    hops = [r["hops"] for r in graph_agent.money_trail("P", role)]
    assert hops, "the trail must find something at every role"
    assert max(hops) == expected_depth


def test_money_trail_never_walks_a_payment_backwards(monkeypatch):
    """TRANSFERRED_TO is the one directed relation: following it in reverse would
    report money that never moved that way."""
    monkeypatch.setattr(graph_agent, "load_graph", _money_chain)
    reached = {r["to_account"] for r in graph_agent.money_trail("P", "IG")}
    assert reached == {"A1", "A2", "A3", "A4"}      # never back to A0, never to P


# --- intents ----------------------------------------------------------------

def test_intent_classification():
    assert classify("Does he have any priors?") == "PERSON_HISTORY"
    assert classify("Who are his known associates?") == "PERSON_NETWORK"
    assert classify("Has he been arrested under a different name?") == "ALIAS_CHECK"
    assert classify("Trace the money trail") == "FINANCIAL"
    assert classify("Forecast crime next month") == "FORECAST"
    assert classify("colourless green ideas") == "UNKNOWN"


def test_visualization_is_bound_to_intent():
    assert visualization_for("PERSON_NETWORK") == "network"
    assert visualization_for("FINANCIAL") == "sankey"
    assert visualization_for("HOTSPOT") == "map"
    assert visualization_for("FORECAST") == "trend"
    assert visualization_for("PERSON_HISTORY") == "none"


def test_pronoun_without_a_named_person_needs_the_focus_stack():
    assert has_unresolved_reference("does he have priors", []) is True
    named = [type("E", (), {"label": "PERSON", "text": "Ramesh"})()]
    assert has_unresolved_reference("does Ramesh have priors", named) is False


# --- citations ---------------------------------------------------------------

def test_citations_are_1_based_and_aligned_to_evidence():
    ev = [_ev(0.9, eid="a"), _ev(0.8, eid="b"), _ev(0.7, eid="c")]
    cites = build_citations(ev)
    assert [c.index for c in cites] == [1, 2, 3]
    assert [c.evidence_id for c in cites] == ["a", "b", "c"]


# --- LLM degradation ----------------------------------------------------------
# A present-but-rate-limited key is the common failure, not a missing one: Gemini's
# free tier 429s exactly when a demo hammers it. Every provider error must collapse
# into LLMUnavailable / {} so the deterministic paths take over, because the one
# thing this engine may never do is fail a turn just because the LLM blinked.

def test_provider_failure_degrades_instead_of_propagating(monkeypatch):
    from rag_agent import llm

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_degraded_until", 0.0)
    monkeypatch.setattr(llm, "_degraded_reason", "")

    class Boom(Exception):
        pass

    def explode(*_a, **_k):
        raise Boom("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(llm, "_client", explode)
    assert llm.available() is True             # key is present, nothing known bad yet

    with pytest.raises(llm.LLMUnavailable):    # NOT the raw provider error
        llm.generate("hello")

    assert llm.available() is False            # cooldown tripped
    assert "degraded" in llm.status()
    assert llm.generate_json("hello", {}) == {}   # returns {}, never raises


def test_no_key_is_reported_honestly(monkeypatch):
    from rag_agent import llm

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.available() is False
    assert "no GEMINI_API_KEY" in llm.status()
    assert llm.generate_json("hello", {}) == {}
