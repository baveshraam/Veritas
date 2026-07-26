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
    """person:1 owns acct:0; money flows acct:0 -> 1 -> 2 -> 3 -> 4, one hop at a time.

    Node ids carry their own kind, exactly as data.graph builds them.
    """
    g = nx.MultiDiGraph()
    g.add_node("person:1", label="Person")
    for i in range(5):
        g.add_node(f"acct:{i}", label="Account")
    g.add_edge("person:1", "acct:0", rel="OWNS_ACCOUNT", amount=None)
    for i in range(4):
        g.add_edge(f"acct:{i}", f"acct:{i+1}", rel="TRANSFERRED_TO", amount=1000.0)
    return g


@pytest.mark.parametrize("role,expected_depth", [("IO", 2), ("SHO", 2), ("DSP", 4), ("IG", 4)])
def test_money_trail_depth_is_capped_by_role(monkeypatch, role, expected_depth):
    """The cap is applied while traversing, not to the result. You cannot un-traverse a
    graph, so a depth an officer may not reach is a depth we never walk."""
    monkeypatch.setattr(graph_agent, "load_graph", _money_chain)
    hops = [r["hops"] for r in graph_agent.money_trail("1", role)]
    assert hops, "the trail must find something at every role"
    assert max(hops) == expected_depth


def test_money_trail_never_walks_a_payment_backwards(monkeypatch):
    """TRANSFERRED_TO is the one directed relation: following it in reverse would report
    money that never moved that way — a transfer the system invented."""
    monkeypatch.setattr(graph_agent, "load_graph", _money_chain)
    reached = {r["to_account"] for r in graph_agent.money_trail("1", "IG")}
    assert reached == {"1", "2", "3", "4"}      # never back to acct:0, never to the person


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

    monkeypatch.setattr(llm, "ENDPOINT", "https://quickml.invalid/chat")
    monkeypatch.setenv("CATALYST_PROJECT_ID", "52852000000013048")
    monkeypatch.setattr(llm, "_degraded_until", 0.0)
    monkeypatch.setattr(llm, "_degraded_reason", "")
    monkeypatch.setattr(llm, "_token", lambda: "a-token")

    class Boom(Exception):
        pass

    def explode(*_a, **_k):
        raise Boom("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(llm.urllib.request, "urlopen", explode)
    assert llm.available() is True             # configured, nothing known bad yet

    with pytest.raises(llm.LLMUnavailable):    # NOT the raw provider error
        llm.generate("hello")

    assert llm.available() is False            # cooldown tripped
    assert "degraded" in llm.status()
    assert llm.generate_json("hello", {}) == {}   # returns {}, never raises


def test_an_unconfigured_llm_is_reported_honestly(monkeypatch):
    """The deployed service authenticates as itself inside AppSail, so "no LLM" locally is
    the normal case, not an error. It must say so rather than name a model it cannot reach."""
    from rag_agent import llm

    monkeypatch.setattr(llm, "ENDPOINT", "")
    assert llm.available() is False
    assert "not configured" in llm.status()
    assert llm.generate_json("hello", {}) == {}


def test_no_catalyst_credential_means_no_llm(monkeypatch):
    """QuickML is only reachable with the app's own Catalyst token. Without one — which is
    every environment that is not AppSail — the engine runs deterministically."""
    from rag_agent import llm

    monkeypatch.setattr(llm, "ENDPOINT", "https://quickml.invalid/chat")
    monkeypatch.setenv("CATALYST_PROJECT_ID", "52852000000013048")
    monkeypatch.setattr(llm, "_degraded_until", 0.0)
    monkeypatch.setattr(llm, "_token", lambda: None)

    with pytest.raises(llm.LLMUnavailable):
        llm.generate("hello")


# --- Exact FIR lookup: the number on the paper FIR --------------------------
#
# fir_by_number() has always taken the 18-digit CrimeNo — its docstring says so, and
# that is the number the generator writes and the case index renders. But the branch
# that calls it only recognised the "0112/2026" short form, so every query carrying a
# real FIR number fell through to semantic search. Asking for a Hurt case in Mandya
# returned cyber-crime cases in Shivamogga, cited and confident. The console's own
# "Ask about this case" button sends exactly this format.

from rag_agent.orchestrator import FIR_NUMBER_RE


@pytest.mark.parametrize("query,expected", [
    ("What is the status of FIR 100222201202600022?", "100222201202600022"),
    ("what is the status of fir 0112/2026", "0112/2026"),
    ("Tell me about FIR 100121201202600041.", "100121201202600041"),
    ("status of FIR 123/2024?", "123/2024"),
])
def test_both_fir_number_forms_are_recognised(query, expected):
    m = FIR_NUMBER_RE.search(query)
    assert m is not None, f"no FIR number found in {query!r}"
    assert m.group(1) == expected


def test_a_bare_year_is_not_mistaken_for_a_fir_number():
    """Guards the long-form branch: it must not fire on ordinary numbers."""
    assert FIR_NUMBER_RE.search("How many thefts in 2026?") is None
    assert FIR_NUMBER_RE.search("Show me the last 30 days") is None


def test_naming_a_fir_that_does_not_exist_is_refused():
    """A named identifier is a claim about a specific record, and it is either in the
    store or it is not. Semantic neighbours of a nonexistent FIR are not evidence
    about it — answering from them is the fabrication the evaluator exists to stop."""
    verdict, conf, detail = evaluate([_ev(0.6), _ev(0.55)], attempts=1,
                                     exact_lookup_missed=True)
    assert verdict == "REJECT"
    assert conf == 0.0


def test_a_fir_that_does_exist_still_answers():
    verdict, _, _ = evaluate([_ev(0.9)], attempts=1, exact_lookup_missed=False)
    assert verdict == "ACCEPT"


# --- FIR evidence formatting ------------------------------------------------
#
# The FIR_LOOKUP branch built its evidence string from three keys sql_agent._case()
# has never returned — 'ipc_sections', 'modus_operandi' — and formatted date_filed
# with a date spec. None of it had ever run: the branch was unreachable until the
# 18-digit number was recognised, so fixing the regex turned a dead branch into a
# KeyError on every FIR lookup. Live Data Store also returns dates as strings, which
# is why ds.to_dt() exists and why '%d %b %Y' applied straight to the value is wrong.

from rag_agent.orchestrator import _fir_content


def _row(**over):
    r = {"fir_id": "1", "fir_number": "100222201202600022", "district": "Mandya",
         "ps_code": "2201", "crime_type": "Hurt", "date_filed": "2026-06-30",
         "case_status": "Under Investigation", "narrative": "A brief fact."}
    r.update(over)
    return r


def test_fir_content_uses_only_keys_the_row_actually_has():
    text = _fir_content(_row())
    assert "100222201202600022" in text
    assert "Mandya" in text and "Hurt" in text and "Under Investigation" in text


def test_fir_content_accepts_a_string_date_from_live_datastore():
    """Live Data Store returns every value as a string — see CONTEXT.md."""
    assert "30 Jun 2026" in _fir_content(_row(date_filed="2026-06-30"))


def test_fir_content_accepts_a_real_date_too():
    from datetime import date
    assert "30 Jun 2026" in _fir_content(_row(date_filed=date(2026, 6, 30)))


def test_fir_content_survives_a_missing_date():
    text = _fir_content(_row(date_filed=None))
    assert "100222201202600022" in text      # no crash, still identifies the record


# --- district code contract --------------------------------------------------

def test_district_fallback_emits_a_code_the_models_can_parse(monkeypatch):
    """`_district_code()` falls back to the busiest district when the question names
    none ("show me crime hotspots"). Everything downstream parses the code with
    `int(code[2:])`, so a raw DistrictID -- "5" -- made int('') raise and the whole
    turn failed. The fallback must speak the same KAnn dialect as canonical_code().
    """
    from data import queries
    from rag_agent.agents import sql_agent

    monkeypatch.setattr(sql_agent.ds, "query",
                        lambda *a, **k: [{"DistrictID": "5", "DistrictName": "Bengaluru Urban"}])
    monkeypatch.setattr(sql_agent.queries, "case_counts_by_district", lambda: {"5": 900})

    code = sql_agent.crime_counts_by_district(limit=1)[0]["district_code"]
    assert code == "KA05"
    assert queries.district_id(code) == 5
