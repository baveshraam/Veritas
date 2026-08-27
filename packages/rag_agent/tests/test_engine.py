"""Investigation-engine checks that need no database or LLM."""
import json

import pytest

import networkx as nx

from rag_agent.agents import graph_agent
from rag_agent.agents.synthesis_agent import build_citations
from rag_agent.evidence.evaluator import (
    ACCEPT_THRESHOLD, NOT_FOUND_MESSAGE, evaluate, score_batch,
)
import rag_agent.intents as intents_mod
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


# --- the case board's own intents --------------------------------------------

def test_board_action_phrases_are_not_swallowed_by_the_view_intent():
    """Found live: 'Pin this to the case board' and 'Add that to the case board'
    (the spec's own literal example phrasing) both contain the substring 'case
    board', which was also a bare BOARD_VIEW keyword — classify() picks the
    earliest-registered intent on a score tie, so every successful pin answered
    with a board SUMMARY instead of a pin confirmation. BOARD_VIEW's keyword list
    no longer contains a bare 'case board'/'investigation board' fragment that a
    pin/add phrase can contain as a substring."""
    assert classify("Pin this to the case board.") == "BOARD_PIN_EVIDENCE"
    assert classify("Add that to the case board.") == "BOARD_PIN_EVIDENCE"
    assert classify("Pin this evidence.") == "BOARD_PIN_EVIDENCE"
    assert classify("Save this as a lead: check his alibi") == "BOARD_ADD_LEAD"
    assert classify("Add a note that this needs verification") == "BOARD_ADD_NOTE"
    assert classify("Dismiss that lead") == "BOARD_LEAD_STATUS"


def test_board_view_phrases_still_route_correctly():
    assert classify("Open the investigation board.") == "BOARD_VIEW"
    assert classify("What is on the board for this case?") == "BOARD_VIEW"
    assert classify("What have we established so far?") == "BOARD_VIEW"


def test_answer_is_refusal_distinguishes_genuine_refusals_from_citationless_success():
    """The console colors a refusal differently from a normal answer, keyed off
    this flag (not citation count — CAPABILITY and a successful board action both
    carry zero citations without being refusals). Found live: before this field
    existed, every successful board confirmation rendered in the same red styling
    as 'I could not find this in the records.'"""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    capability = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                    original_query="what can you do", intent="CAPABILITY")
    orch.node_synthesize(capability)
    assert capability.citations == [] and capability.answer_is_refusal is False

    pinned = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                original_query="pin this", intent="BOARD_PIN_EVIDENCE")
    pinned.board_result = {"ok": True, "kind": "pinned",
                           "item": {"item_type": "evidence", "content": "x"}}
    orch.node_synthesize(pinned)
    assert pinned.citations == [] and pinned.answer_is_refusal is False

    board_error = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                     original_query="pin this", intent="BOARD_PIN_EVIDENCE")
    board_error.board_result = {"ok": False, "kind": "error", "message": "nothing to pin"}
    orch.node_synthesize(board_error)
    assert board_error.answer_is_refusal is True

    refused = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                 original_query="show me the money trail",
                                 intent="FINANCIAL", requires_escalation=True,
                                 refusal_reason="no_subject")
    orch.node_synthesize(refused)
    assert refused.citations == [] and refused.answer_is_refusal is True


def test_no_intents_keyword_is_a_substring_of_another_intents_keyword_unless_expected():
    """A systematic guard against the exact class of bug the two tests above
    caught by hand: any keyword phrase that is a plain substring of a DIFFERENT
    intent's keyword phrase will always win or tie that intent's own score on any
    query containing it. A handful of these are pre-existing and deliberate
    (CRIME_SEARCH is the scored-last fallback, see intents.classify's own
    docstring) — this only guards against a NEW one being introduced silently."""
    _KNOWN = {
        ("PERSON_HISTORY", "previous cases", "CRIME_SEARCH", "cases"),
        ("FINANCIAL", "account", "CRIME_SEARCH", "count"),
        ("SIMILAR_CASES", "matching cases", "CRIME_SEARCH", "cases"),
        ("CRIME_SEARCH", "firs", "FIR_LOOKUP", "fir"),
    }
    found = set()
    for name_a, (kws_a, _) in intents_mod.INTENTS.items():
        for name_b, (kws_b, _) in intents_mod.INTENTS.items():
            if name_a == name_b:
                continue
            for ka in kws_a:
                for kb in kws_b:
                    if ka != kb and ka in kb:
                        found.add((name_b, kb, name_a, ka))
    assert found == _KNOWN, f"new keyword collision(s): {found - _KNOWN}"


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


def test_this_that_as_a_determiner_is_not_an_unresolved_person_pronoun():
    """Found live 2026-08-26: 'How many gangs operate in THIS district?' contains no
    PERSON entity and 'this' matched the pronoun regex unconditionally, so it was
    treated as an unresolved person reference — with two people named in a recent
    turn's citations, the district question was hijacked into 'which person do you
    mean?'. 'this'/'that' immediately followed by an ordinary noun is a determiner
    ('this district', 'that case'), not a stand-in for a person; only a bare
    pronoun use ('tell me about this person', 'why is that') should still count."""
    assert has_unresolved_reference("How many gangs operate in this district?", []) is False
    assert has_unresolved_reference("Tell me about that case", []) is False
    assert has_unresolved_reference("Tell me more about this person", []) is True
    assert has_unresolved_reference("why is that", []) is True


def test_go_back_to_an_earlier_case_refuses_instead_of_guessing():
    """No case-history stack exists — SessionFocus keeps only the case currently in
    view — so 'go back to the first case' used to score a bare CRIME_SEARCH on the
    word 'case' and run a real semantic search over the literal phrase, returning
    confidently-cited but unrelated records. Found live 2026-08-26."""
    assert classify("Go back to the first case") == "CASE_REFERENCE_UNSUPPORTED"
    assert classify("Can we return to the previous case?") == "CASE_REFERENCE_UNSUPPORTED"


def test_a_case_reference_with_no_ordinal_still_refuses():
    """The original fix only matched an ORDINAL sitting directly before 'case' (the
    first/previous/original case). 'The case we started with' names the same thing —
    a case by its position in this session, not by FIR number — with the qualifier
    trailing 'case' instead of leading it. Found live 2026-08-27 (final judge pass):
    this exact phrasing skipped the refusal and fell to a real semantic search, which
    had enough confidence to pass CRAG and returned 5 confidently-cited but completely
    unrelated records (an Attempt to Murder case in Ballari/Kolar) — worse than a
    refusal, since nothing on screen signalled the mismatch."""
    assert classify("Go back to the case we started with.") == "CASE_REFERENCE_UNSUPPORTED"
    assert classify("Let's return to the case we began with") == "CASE_REFERENCE_UNSUPPORTED"
    assert classify("Go back to that case") == "CASE_REFERENCE_UNSUPPORTED"


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


def test_endpoint_key_header_sent_only_when_configured(monkeypatch):
    """BUG-022: QuickML's sibling 'pipeline endpoints' REST surface documents a required
    per-endpoint X-QUICKML-ENDPOINT-KEY header. It cannot be obtained or verified from this
    environment (console-only), so it must stay optional — sent when someone sets it, absent
    otherwise, never fabricated."""
    from rag_agent import llm

    monkeypatch.setattr(llm, "ENDPOINT", "https://quickml.invalid/chat")
    monkeypatch.setenv("CATALYST_PROJECT_ID", "52852000000013048")
    monkeypatch.setattr(llm, "_degraded_until", 0.0)
    monkeypatch.setattr(llm, "_token", lambda: "a-token")

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.headers)
        return FakeResp()

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(json, "load", lambda f: {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm, "ENDPOINT_KEY", "")
    llm.generate("hello")
    assert "X-quickml-endpoint-key" not in captured["headers"]

    monkeypatch.setattr(llm, "ENDPOINT_KEY", "secret-from-console")
    llm.generate("hello")
    assert captured["headers"].get("X-quickml-endpoint-key") == "secret-from-console"


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


# --- BUG (QuickML unreachable): _token() called a method that never existed --------
#
# Verified live: /health reported "quickml (glm-4.7-flash)" while every answer was
# extractive. The actual cause was `catalyst_app()._app._credential.get_token()`:
# `zcatalyst_sdk.initialize()` returns the CatalystApp object DIRECTLY (there is no
# `._app` wrapper), and Credential subclasses expose `.token()`, never `.get_token()`
# — confirmed by extracting the published zcatalyst-sdk 1.4.0 wheel and reading
# credentials.py / catalyst_app.py directly, then round-tripping the fixed logic
# against the real installed package with simulated AppSail request headers
# (X-ZC-Admin-Cred-Token etc., per zcatalyst_sdk._constants.CredentialHeader). The old
# code raised AttributeError on the first attribute lookup, every single call, in
# every environment — this was never specific to being unreachable "in AppSail"; the
# LLM had never actually been called successfully.
#
# Skipped where the SDK isn't installed (by design — see llm.py's own "Absent
# everywhere else" and the test above). Run it anywhere the real dependency is present,
# including inside the deployed image, to catch a regression against the actual
# credential contract rather than a hand-rolled stand-in for it.

class _FakeAppSailRequest:
    def __init__(self, headers):
        self.headers = headers


def _fake_appsail_app(zcatalyst_sdk):
    """A CatalystApp initialized exactly the way AppSail's middleware does it —
    real SDK classes, simulated gateway headers."""
    headers = {
        "X-ZC-ProjectId": "52852000000013048",
        "X-ZC-Project-Domain": "veritas-60077763394.development.catalystserverless.in",
        "X-ZC-Project-Key": "k",
        "X-ZC-Environment": "Development",
        "X-ZC-PROJECT-SECRET-KEY": "s",
        "X-ZC-Admin-Cred-Type": "token",
        "X-ZC-Admin-Cred-Token": "REAL-ADMIN-TOKEN",
        "X-ZC-User-Cred-Type": "token",
        "X-ZC-User-Cred-Token": "REAL-USER-TOKEN",
    }
    return zcatalyst_sdk.initialize(name=f"test-{id(headers)}", req=_FakeAppSailRequest(headers))


def test_the_old_credential_path_never_existed_on_the_real_sdk():
    """Documents the actual defect against the real classes, not a guess about them.

    A function-scoped import: pytest.importorskip must never sit at module level in
    this file — doing so once already skipped collection of every test below it, all
    93 of them, silently. That mistake is worth naming so it is not repeated: a skip
    reason belongs to the one test that needs it, not to everything textually after it.
    """
    zcatalyst_sdk = pytest.importorskip("zcatalyst_sdk", reason="AppSail-only dependency")
    app = _fake_appsail_app(zcatalyst_sdk)
    assert not hasattr(app, "_app")
    with pytest.raises(AttributeError):
        app._app._credential.get_token()  # noqa: SLF001 — reproducing the old bug on purpose


def test_token_reads_the_admin_credential_the_way_the_sdks_own_http_client_does(monkeypatch):
    """The fixed _token(): same credential.token() call AuthorizedHttpClient makes
    before every Data Store / Cache / graph request, picking the admin scope Data
    Store operations already run under."""
    zcatalyst_sdk = pytest.importorskip("zcatalyst_sdk", reason="AppSail-only dependency")
    from rag_agent import llm

    app = _fake_appsail_app(zcatalyst_sdk)
    import data.ds as ds_module
    monkeypatch.setattr(ds_module, "catalyst_app", lambda: app)

    token = llm._token()
    assert token == "REAL-ADMIN-TOKEN"
    assert token != "REAL-USER-TOKEN"      # the app authenticates as itself, not as an officer


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


# --- BUG-006: an answer must cite only what supports it ---------------------
#
# Measured live before the fix: "What is the status of FIR 100050510202600037?"
# returned the right FIR at [1] (a Hurt case in Bengaluru Urban, confidence 0.97) and
# then five cyber-crime cases from Shivamogga at [2]-[6], each at ~0.49. Every one was
# a real record. None was evidence for the question. The evaluator had already drawn
# that line — RELEVANCE_FLOOR — to decide *whether* to answer, and synthesis then
# cited the whole batch anyway.

from rag_agent.evidence.evaluator import RELEVANCE_FLOOR, supporting


def test_only_supporting_evidence_is_citable():
    exact = _ev(0.97, "FIR_RECORD", "fir:9940")
    neighbours = [_ev(0.49, "FIR_RECORD", f"vec:fir_narrative:{i}") for i in range(5)]
    kept = supporting([exact] + neighbours)
    assert [e.evidence_id for e in kept] == ["fir:9940"]


def test_a_batch_that_supports_nothing_is_not_accepted_by_averaging():
    """Five neighbours just under the floor used to average their way past
    ACCEPT_THRESHOLD (0.45) and be cited as though they answered the question."""
    batch = [_ev(RELEVANCE_FLOOR - 0.01) for _ in range(5)]
    assert supporting(batch) == []
    assert evaluate(batch, attempts=1)[0] == "REJECT"
    assert evaluate(batch, attempts=0)[0] == "REFINE"


def test_one_exact_record_is_still_enough_on_its_own():
    """The fix must not swing the other way: a single decisive record answers."""
    assert evaluate([_ev(0.97)], attempts=0)[0] == "ACCEPT"


def test_an_exact_identifier_hit_suppresses_semantic_search():
    """'What is the status of FIR X' is a yes/no claim about one row. The nearest
    narratives to it are cases about something else, so they are not run at all."""
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="What is the status of FIR 100222201202600022?")
    state.intent = "FIR_LOOKUP"

    import rag_agent.orchestrator as orch

    hit = {"fir_id": 1, "fir_number": "100222201202600022", "ps_code": "2201",
           "district": "Mandya", "crime_type": "Hurt", "date_filed": "2026-06-30",
           "case_status": "Under Investigation", "narrative": "n"}
    called = []
    saved = (orch.sql_agent.fir_by_number, orch.vector_agent.search, orch._officer_ps)
    orch.sql_agent.fir_by_number = lambda *a, **k: [hit]
    orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        orch.sql_agent.fir_by_number, orch.vector_agent.search, orch._officer_ps = saved

    assert state.exact_lookup_hit is True
    assert called == [], "vector search ran despite an exact identifier hit"
    assert [e.evidence_id for e in out] == ["fir:1"]


# --- BUG-009 / BUG-010: a refusal has to state the reason it actually refused -------
#
# Measured live before the fix, every one of these produced the same sentence -- "please
# refine the query, or check whether the record exists in the system" -- after sweeping
# the vector index and citing nothing:
#
#   "who could be the suspect"      asks for an inference the records do not license
#   "what all could you answer"     is a question about the tool, not about the records
#   "show me the money trail"       names no subject to trace
#   "Tell me about <unknown name>"  names someone not on file
#
# Four different facts, one sentence, and the sentence was wrong for three of them.
# Every branch below still REFUSES. None of them answers, and none softens "not found
# in the records" into "does not exist".

from rag_agent.evidence.evaluator import REFUSAL_MESSAGES, refusal_message
from rag_agent.intents import NEEDS_SUBJECT, capability_answer


@pytest.mark.parametrize("query,expected", [
    ("who could be the suspect", "NOT_INFERABLE"),
    ("who might be the culprit", "NOT_INFERABLE"),
    ("who committed this crime", "NOT_INFERABLE"),
    ("what all could you answer", "CAPABILITY"),
    ("what can you do", "CAPABILITY"),
    ("what kind of questions do you support", "CAPABILITY"),
])
def test_questions_retrieval_cannot_answer_are_routed_before_retrieval(query, expected):
    assert classify(query) == expected


@pytest.mark.parametrize("query,expected", [
    ("Who are the associates of Usha Naika?", "PERSON_NETWORK"),
    ("Show me the money trail for Usha Naika", "FINANCIAL"),
    ("Does Usha Naika have priors?", "PERSON_HISTORY"),
    ("What is the status of FIR 100222201202600022?", "FIR_LOOKUP"),
    ("theft hotspots in Bengaluru Urban", "HOTSPOT"),
])
def test_the_new_branches_do_not_swallow_real_questions(query, expected):
    """The regexes run before keyword scoring, so they must not capture ordinary work."""
    assert classify(query) == expected


def test_every_refusal_reason_has_its_own_message():
    reasons = {"no_evidence", "exact_lookup_missed", "no_subject",
               "person_not_on_file", "not_inferable"}
    assert reasons <= set(REFUSAL_MESSAGES)
    assert len(set(REFUSAL_MESSAGES.values())) == len(REFUSAL_MESSAGES)


def test_an_unknown_reason_falls_back_to_the_general_refusal():
    assert refusal_message("something_new") == NOT_FOUND_MESSAGE


def test_no_refusal_message_claims_the_record_does_not_exist():
    """Rule: "not found in the records" must never become "does not exist". The store
    holds what it holds; absence from it is not absence from the world."""
    for reason, msg in REFUSAL_MESSAGES.items():
        low = msg.lower()
        assert "does not exist" not in low or "within your access scope" in low, reason


def test_the_capability_answer_states_its_limits_not_only_its_features():
    text = capability_answer().lower()
    assert "cite" in text
    assert "do not name suspects" in text and "infer guilt" in text
    assert "rank and station" in text


def test_subject_less_relational_questions_stop_before_retrieval():
    """BUG-010. These used to run the full pipeline and refuse for the wrong reason."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    for intent in sorted(NEEDS_SUBJECT):
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                   original_query="show me the money trail")
        state.intent = intent
        called = []
        saved = orch.vector_agent.search
        orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
        try:
            orch.node_retrieve(state)
        finally:
            orch.vector_agent.search = saved

        assert state.refusal_reason == "no_subject", intent
        assert called == [], f"{intent} searched the index with no subject to search for"
        assert state.evidence_items == []


def test_a_capability_question_is_answered_without_touching_the_records():
    """BUG-009. It is the one of the three that gets an answer -- and it carries no
    citations, because there is no record behind a description of the tool."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="what all could you answer")
    state.intent = "CAPABILITY"

    called = []
    saved = orch.vector_agent.search
    orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
    try:
        orch.node_retrieve(state)
        orch.node_evaluate(state)
        orch.node_synthesize(state)
    finally:
        orch.vector_agent.search = saved

    assert called == []
    assert state.citations == []
    assert state.final_answer == capability_answer()
    assert NOT_FOUND_MESSAGE not in state.final_answer


def test_a_suspect_question_refuses_for_the_right_reason():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="who could be the suspect")
    state.intent = "NOT_INFERABLE"
    orch.node_retrieve(state)
    orch.node_evaluate(state)
    orch.node_synthesize(state)

    assert state.refusal_reason == "not_inferable"
    assert state.citations == []
    assert "do not nominate suspects" in state.final_answer
    assert state.final_answer != NOT_FOUND_MESSAGE


def test_a_refusal_already_decided_by_orchestrate_does_not_still_run_a_generic_search():
    """Found live (2026-08-26 golden-conversation pass): node_orchestrate had already
    set refusal_reason='ambiguous_person' (a tied name, or a pronoun with several
    named-last-turn candidates) and cleared active_person -- but node_retrieve had no
    guard for a refusal decided BEFORE it runs, only for the ones it decides itself
    (CAPABILITY/NOT_INFERABLE) or re-derives from NEEDS_CASE/NEEDS_SUBJECT (guarded
    with 'and not state.refusal_reason', which skips SETTING a duplicate reason but
    does not return early when one is already set). Every specialist branch requires
    a pid, so all of them were skipped -- except the generic vector-search fallback
    at the bottom of _run_specialists, which has no such guard and searched anyway,
    handing the officer 5 unrelated criminal-profile citations in the Evidence rail
    right next to a chat message saying 'I will not guess which one you mean.'"""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Does he have priors?")
    state.intent = "PERSON_HISTORY"
    state.refusal_reason = "ambiguous_person"
    state.ambiguous_candidates = ["Usha Naika", "Prashanth Krishnamurthy"]
    # active_person is deliberately left None, as node_orchestrate would have left it.

    called = []
    saved = orch.vector_agent.search
    orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
    try:
        orch.node_retrieve(state)
    finally:
        orch.vector_agent.search = saved

    assert called == [], "a decided refusal must not still search for something to cite"
    assert state.evidence_items == []


# --- BUG-012: /health reported a model it had never reached ------------------
#
# Live, every answer was extractive and the Copilot diary was the deterministic
# string, while /health reported "quickml (glm-4.7-flash)". Two causes: status()
# treated a configured endpoint URL as a working one, and the failure that was
# actually occurring -- no Catalyst credential -- was raised straight out of _chat
# without going through _degrade(), so the cooldown never tripped and the status
# never changed.

def test_a_missing_credential_degrades_the_reported_status(monkeypatch):
    from rag_agent import llm

    monkeypatch.setattr(llm, "ENDPOINT", "https://quickml.invalid/chat")
    monkeypatch.setenv("CATALYST_PROJECT_ID", "52852000000013048")
    monkeypatch.setattr(llm, "_degraded_until", 0.0)
    monkeypatch.setattr(llm, "_degraded_reason", "")
    monkeypatch.setattr(llm, "_ever_succeeded", False)
    monkeypatch.setattr(llm, "_token", lambda: None)

    with pytest.raises(llm.LLMUnavailable):
        llm.generate("hello")

    assert "degraded" in llm.status()
    assert not llm.available()


def test_a_configured_but_uncontacted_endpoint_is_not_reported_as_serving(monkeypatch):
    from rag_agent import llm

    monkeypatch.setattr(llm, "ENDPOINT", "https://quickml.invalid/chat")
    monkeypatch.setenv("CATALYST_PROJECT_ID", "52852000000013048")
    monkeypatch.setattr(llm, "_degraded_until", 0.0)
    monkeypatch.setattr(llm, "_ever_succeeded", False)

    assert "not yet contacted" in llm.status()


# --- BUG-013: a money-trail question answered from a theft record ------------

def test_an_empty_money_trail_states_the_absence_rather_than_leaving_it_unsaid():
    """Measured live: "Show me the money trail for Usha Naika" returned
    visualization=none, zero transfer evidence, and a confident answer whose top
    citation was a summary of her theft cases. A real record, cited, and not about
    money. The negative finding is the answer, so it has to be in the evidence -- the
    same reason ALIAS_CHECK states its own."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Show me the money trail for Usha Naika")
    state.intent = "FINANCIAL"
    state.active_entities.active_person = "803"

    saved = (orch.graph_agent.money_trail, orch.vector_agent.search, orch._officer_ps)
    orch.graph_agent.money_trail = lambda *a, **k: []
    orch.vector_agent.search = lambda *a, **k: ([], [])
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        orch.graph_agent.money_trail, orch.vector_agent.search, orch._officer_ps = saved

    assert len(out) == 1
    assert out[0].evidence_id == "flow:none:803"
    assert "No bank account is linked" in out[0].content
    # and it must not overclaim: absence in the records is not absence in the world
    assert "not a finding that no money moved" in out[0].content


# --- BUG-008: "how many" answered with narratives and never a number ---------

def test_crime_search_returns_an_exact_count_and_supporting_samples():
    """Measured live: 'how many theft cases in Mandya' returned five narrative
    excerpts and no number anywhere. Counting is a question the structured layer
    answers exactly; this asserts the count is now produced, is authoritative (so it
    settles the turn on its own), and vector search does not run to pad it."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(
        session_id="s", officer_id="1", officer_role="IG",
        original_query="How many theft cases are there in Mandya district?")
    state.intent = "CRIME_SEARCH"
    state.active_entities.active_location = "Mandya"

    sample = {"fir_id": "9", "fir_number": "1", "district": "Mandya",
              "ps_code": "1", "crime_type": "Theft", "date_filed": "2026-01-01",
              "case_status": "Under Investigation", "narrative": "n"}
    called = []
    saved = (orch.sql_agent.count_firs, orch.sql_agent.search_firs,
            orch.vector_agent.search, orch._officer_ps)
    orch.sql_agent.count_firs = lambda *a, **k: 7
    orch.sql_agent.search_firs = lambda *a, **k: [sample]
    orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        (orch.sql_agent.count_firs, orch.sql_agent.search_firs,
         orch.vector_agent.search, orch._officer_ps) = saved

    assert called == [], "vector search ran even though the count already settled the turn"
    counts = [e for e in out if e.evidence_id.startswith("crime_count:")]
    assert len(counts) == 1
    assert counts[0].authoritative is True
    assert "7 case(s)" in counts[0].content
    assert any(e.evidence_id == "fir:9" for e in out)


def test_crime_search_states_zero_plainly_rather_than_going_silent():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="How many dacoity cases in Kolar?")
    state.intent = "CRIME_SEARCH"
    state.active_entities.active_location = "Kolar"

    called = []
    saved = (orch.sql_agent.count_firs, orch.sql_agent.search_firs,
            orch.vector_agent.search, orch._officer_ps)
    orch.sql_agent.count_firs = lambda *a, **k: 0
    orch.sql_agent.search_firs = lambda *a, **k: (called.append(1), [])[1]
    orch.vector_agent.search = lambda *a, **k: ([], [])
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        (orch.sql_agent.count_firs, orch.sql_agent.search_firs,
         orch.vector_agent.search, orch._officer_ps) = saved

    assert called == [], "no need to fetch samples for a zero count"
    assert len(out) == 1
    assert "0 case(s)" in out[0].content
    assert out[0].authoritative is True


def test_crime_type_extraction_prefers_the_longer_specific_match():
    from rag_agent.orchestrator import _crime_type_from_query

    assert _crime_type_from_query("how many motor vehicle theft cases") == "Motor Vehicle Theft"
    assert _crime_type_from_query("how many theft cases") == "Theft"
    assert _crime_type_from_query("show me all cases") is None


# --- BUG-011: vector similarity displayed as evidential confidence -----------

def test_vector_hits_are_labeled_as_similarity_not_support():
    """A record's textual closeness to the query is a real number, but it is not the
    same claim as 'this record supports the answer'. The UI must be able to tell
    them apart, which means the field carrying the distinction must be set correctly
    at the one place a raw similarity score enters the evidence stream."""
    from rag_agent.agents import vector_agent

    saved = (vector_agent.hybrid_search, vector_agent._drop_dangling)
    vector_agent.hybrid_search = lambda *a, **k: [
        {"collection": "fir_narrative", "source_id": "1", "content": "c", "score": 0.8}]
    vector_agent._drop_dangling = lambda rows: rows       # no DB in this unit test
    try:
        rows, evidence = vector_agent.search("query")
    finally:
        vector_agent.hybrid_search, vector_agent._drop_dangling = saved

    assert evidence[0].confidence_kind == "similarity"


def test_exact_and_authoritative_evidence_defaults_to_support_kind():
    """Everything that is NOT a raw similarity score keeps the default — an exact FIR
    lookup, a graph relationship, an authoritative negative finding all genuinely mean
    'this backs the claim', so they must not be relabeled down to 'similarity'."""
    fir = _ev(0.97)
    assert fir.confidence_kind == "support"


def test_model_predictions_carry_a_distinct_kind_from_their_own_reported_score():
    """risk()/forecast()/causal() attach a fixed ranking weight as `confidence`, not
    the model's own reported number (which lives in `content`). Displaying a fixed
    0.6 as if it were the model's calibrated output would be exactly the category
    error BUG-011 already names for vector similarity, just via a constant instead
    of a computed score."""
    from unittest.mock import patch

    from rag_agent.agents import prediction_agent
    from ml_models.types import RiskResult

    with patch.object(prediction_agent, "_ml") as ml:
        ml.return_value.score_risk.return_value = RiskResult(
            person_id="1", score=0.62, top_factors=[("x", 0.1)], calibrated=True)
        _, ev = prediction_agent.risk("1")
    assert ev[0].confidence_kind == "model_estimate"
    assert "calibrated" in ev[0].content


# --- North Star Phase 5: AML detectors were unreachable via the conversational path -

def test_aml_detectors_run_against_every_account_the_person_owns():
    """`for acct in {r["from_account"] for r in rows}: ... break` checked at most one
    account, and for a multi-hop transfer `from_account` can be an intermediate
    account nobody in this case owns — for structuring specifically (deposits INTO an
    account), that was never even the right side of the transfer to check. A person
    who owns two accounts must have both checked, not one."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Show me the money trail for Usha Naika")
    state.intent = "FINANCIAL"
    state.active_entities.active_person = "803"

    checked = []
    saved = (orch.graph_agent.money_trail, orch.graph_agent.owned_accounts,
            orch.prediction_agent.transactions, orch.vector_agent.search, orch._officer_ps)
    orch.graph_agent.money_trail = lambda *a, **k: [
        {"from_account": "acctA", "to_account": "intermediate", "amount": 1000, "hops": 1}]
    orch.graph_agent.owned_accounts = lambda pid: ["acctA", "acctB"]
    orch.prediction_agent.transactions = lambda acct: (checked.append(acct), (None, []))[1]
    orch.vector_agent.search = lambda *a, **k: ([], [])
    orch._officer_ps = lambda _oid: ""
    try:
        orch._run_specialists(state, widen=False)
    finally:
        (orch.graph_agent.money_trail, orch.graph_agent.owned_accounts,
         orch.prediction_agent.transactions, orch.vector_agent.search,
         orch._officer_ps) = saved

    assert set(checked) == {"acctA", "acctB"}, (
        f"expected both owned accounts checked, got {checked}")


# --- BUG-007: a generic verb pair outvoting a specific topic word -----------

@pytest.mark.parametrize("query,expected", [
    # The reported failure: scored CRIME_SEARCH 2 ("find", "cases") against
    # SIMILAR_CASES 1 ("similar") and returned five unrelated criminal profiles.
    ("Find cases similar to FIR 100222201202600022", "SIMILAR_CASES"),
    ("show me comparable cases", "SIMILAR_CASES"),
    ("list cases with the same modus", "SIMILAR_CASES"),
    # CRIME_SEARCH must still win when nothing more specific is present.
    ("How many theft cases are there in Mandya district?", "CRIME_SEARCH"),
    ("list the robbery cases", "CRIME_SEARCH"),
    ("count the theft cases", "CRIME_SEARCH"),
    # BUG-019, fixed: keyword matching used to be by substring, and "fir" is inside
    # "firs" — "show me murder firs" scored FIR_LOOKUP on a query that named no FIR.
    # Word-boundary matching now correctly leaves FIR_LOOKUP unmatched here.
    ("show me murder firs", "CRIME_SEARCH"),
    # and the specific intents keep their questions
    ("Show me crime hotspots", "HOTSPOT"),
    ("show me the money trail", "FINANCIAL"),
    ("find his known associates", "PERSON_NETWORK"),
])
def test_crime_search_is_the_fallback_not_a_competitor(query, expected):
    assert classify(query) == expected


# --- Regression: authoritative findings vs. relevance-scored evidence --------------
#
# BUG-006's fix (supporting/RELEVANCE_FLOOR) introduced a real regression: it could not
# tell a genuinely weak/irrelevant hit apart from a specialist's own authoritative
# statement whose confidence field isn't a relevance score at all. Measured live before
# this fix: "Why does crime correlate with literacy?" lost its honest
# "a causal estimate cannot be produced" decline (confidence=0.0 by convention) and
# answered instead from five unrelated criminal profiles that happened to clear 0.5.
#
# The fix adds a second axis — EvidenceItem.authoritative — rather than touching
# RELEVANCE_FLOOR itself or special-casing CAUSAL by name.

from rag_agent.evidence.evaluator import AUTHORITATIVE_CONFIDENCE, supporting


def _authoritative_ev(conf: float = 0.0, eid: str = "auth") -> EvidenceItem:
    return EvidenceItem(evidence_id=eid, source_type="ML_PREDICTION", source_id="s",
                        content="an authoritative statement", confidence=conf,
                        authoritative=True)


def test_an_authoritative_item_survives_the_relevance_floor_regardless_of_confidence():
    """The exact defect: a confidence=0.0 authoritative item must not be dropped."""
    batch = [_authoritative_ev(0.0)] + [_ev(0.3) for _ in range(5)]   # all noise below floor
    kept = supporting(batch)
    assert "auth" in [e.evidence_id for e in kept]


def test_a_batch_of_pure_noise_still_rejects_when_nothing_is_authoritative():
    """Guards against over-correcting: ordinary weak evidence must still be filtered."""
    batch = [_ev(0.3) for _ in range(5)]
    assert supporting(batch) == []
    assert evaluate(batch, attempts=1)[0] == "REJECT"


def test_an_authoritative_item_alone_is_accepted_immediately_not_widened():
    """Retrying cannot improve on an authoritative statement — evaluate() must not
    REFINE a batch that already contains one, even on the very first attempt."""
    verdict, confidence, detail = evaluate([_authoritative_ev(0.0)], attempts=0)
    assert verdict == "ACCEPT"
    assert confidence == AUTHORITATIVE_CONFIDENCE
    assert "authoritative" in detail.lower()


def test_an_authoritative_item_is_not_outvoted_by_surrounding_noise():
    """The regression's exact shape: an authoritative decline plus several unrelated
    vector hits that clear the floor on their own. The decline must still be present
    and citable — not silently dropped in favour of the noise around it."""
    batch = [_authoritative_ev(0.0, "causal:unavailable")] +             [_ev(0.55, eid=f"noise{i}") for i in range(5)]
    verdict, _, _ = evaluate(batch, attempts=0)
    assert verdict == "ACCEPT"
    kept_ids = {e.evidence_id for e in supporting(batch)}
    assert "causal:unavailable" in kept_ids


def test_the_causal_decline_is_marked_authoritative(monkeypatch):
    """prediction_agent.causal() must set authoritative=True on its own decline —
    this is the actual production code path the regression was found in, not just the
    evaluator in isolation."""
    from rag_agent.agents import prediction_agent
    from ml_models.causal.effects import SocioeconomicDataUnavailable

    def _raise(*a, **k):
        raise SocioeconomicDataUnavailable("no Census row for this district")

    monkeypatch.setattr(prediction_agent, "_ml", lambda: type(
        "M", (), {"estimate_causal_effect": staticmethod(_raise)})())

    _, ev = prediction_agent.causal("literacy_rate", "KA99")
    assert len(ev) == 1
    assert ev[0].authoritative is True
    assert ev[0].confidence == 0.0
    assert "cannot be produced" in ev[0].content


# --- BUG-013 residual: FINANCIAL must not pad an authoritative answer with noise ----

def test_vector_search_is_skipped_once_a_relational_specialist_settles_the_question():
    """Generalises the exact_lookup_hit suppression: FINANCIAL, ALIAS_CHECK,
    PERSON_NETWORK and CAUSAL each produce their own complete answer once a subject is
    resolved, and semantic neighbours of the subject are not evidence for it."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    for intent in ("FINANCIAL", "ALIAS_CHECK", "CAUSAL"):
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                   original_query="irrelevant for this stub")
        state.intent = intent
        state.active_entities.active_person = "803"

        called = []
        saved = (orch.graph_agent.money_trail, orch.graph_agent.aliases,
                 orch.prediction_agent.causal, orch.prediction_agent.transactions,
                 orch.vector_agent.search, orch._officer_ps, orch._district_code)
        orch.graph_agent.money_trail = lambda *a, **k: []          # empty -> authoritative negative
        orch.graph_agent.aliases = lambda *a, **k: []               # empty -> authoritative negative
        orch.prediction_agent.causal = lambda *a, **k: (None, [_authoritative_ev(0.0, "c")])
        orch.prediction_agent.transactions = lambda *a, **k: (None, [])
        orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
        orch._officer_ps = lambda _oid: ""
        orch._district_code = lambda _state: "KA05"
        try:
            out = orch._run_specialists(state, widen=False)
        finally:
            (orch.graph_agent.money_trail, orch.graph_agent.aliases,
             orch.prediction_agent.causal, orch.prediction_agent.transactions,
             orch.vector_agent.search, orch._officer_ps, orch._district_code) = saved

        assert called == [], f"{intent}: vector search ran despite a settled specialist answer"
        assert out, f"{intent}: specialist produced no evidence at all"


# --- Conversational architecture pass: case-scoped follow-ups, meta-questions,
# ambiguous names, and the focus-persistence gap that made them all forgettable ----
#
# The engine already carried a session focus (active_person/active_fir/active_location,
# see data.models.SessionFocus) across turns, but two things undercut it: (1) nothing
# ever answered a follow-up ABOUT the open case itself ("what happened", "who's
# involved", "what next", "prepare the briefing") or ABOUT the previous answer ("why
# these", "what evidence"), so those turns fell through to a literal-text vector search
# that could not possibly be about either; and (2) whatever FIR_LOOKUP resolved into
# active_fir during node_retrieve was never persisted — only the focus resolved BEFORE
# retrieval (in node_orchestrate) was saved. "Open FIR X" then "What happened?" forgot
# X the moment the second turn asked for the session's saved focus.

def test_previous_cases_plural_is_recognised_as_person_history():
    """Found live: 'What previous cases involve her?' matched no PERSON_HISTORY
    keyword ('previous case' is singular-only) and fell to CRIME_SEARCH's bare
    'cases' instead — a follow-up asking about ONE person's prior record got a
    global case count with no connection to who was asked about."""
    assert classify("What previous cases involve her?") == "PERSON_HISTORY"


def test_transactions_plural_is_recognised_as_financial():
    """FINANCIAL had 'transaction' but not 'transactions' — the word-boundary regex
    does not treat a plural as a substring match, so 'what transactions look unusual'
    matched no FINANCIAL keyword at all."""
    assert classify("What transactions look unusual?") == "FINANCIAL"


@pytest.mark.parametrize("query,expected", [
    ("What happened here?", "CASE_CONTEXT"),
    ("Tell me about this case", "CASE_CONTEXT"),
    ("Who are the key people in this case?", "CASE_PEOPLE"),
    ("Who is involved?", "CASE_PEOPLE"),
    ("What should I investigate next?", "NEXT_STEPS"),
    ("Prepare the briefing", "BRIEFING"),
    ("Draft the case diary", "BRIEFING"),
    # These three each contain a word ("why"/"where") that an unrelated topic intent
    # already keys on (CAUSAL, HOTSPOT) — the regressions this session most wanted to
    # avoid re-introducing while adding meta-questions.
    ("Why are you showing me these people?", "EXPLAIN_REASONING"),
    ("What evidence supports that?", "EVIDENCE_FOR"),
    ("Where are those cases concentrated?", "CASE_LOCATIONS"),
    # Found live (2026-08-26 golden-conversation pass): the "you <verb>" and
    # "those <adjective>" shapes above didn't cover an investigator naming a
    # DIFFERENT verb ("select" instead of "show") or the passive voice with a noun
    # in between ("those associates surfaced" instead of "those [X] shown") — both
    # fell through to CAUSAL ("why") or a bare repeat of the prior topic intent.
    ("Why did you select those cases?", "EXPLAIN_REASONING"),
    ("Why were those associates surfaced?", "EXPLAIN_REASONING"),
    # Passive phrasing of the same question the NEXT_STEPS keyword list already had
    # active-voice ("investigate next"): "investigated next" is a different word,
    # not a substring, and the word-boundary matcher does not stem it.
    ("What should be investigated next?", "NEXT_STEPS"),
    # Ordinary questions using the same words must still route where they always did.
    ("Why does crime correlate with literacy?", "CAUSAL"),
    ("Show me crime hotspots", "HOTSPOT"),
    ("theft hotspots in Bengaluru Urban", "HOTSPOT"),
])
def test_conversational_followup_intents_do_not_collide_with_existing_ones(query, expected):
    assert classify(query) == expected


def test_needs_case_intents_refuse_without_an_open_case():
    """Symmetric to NEEDS_SUBJECT: asked cold, these four have nothing to read."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    for intent in sorted(intents_mod.NEEDS_CASE):
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                   original_query="irrelevant text")
        state.intent = intent
        called = []
        saved = orch.vector_agent.search
        orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
        try:
            orch.node_retrieve(state)
        finally:
            orch.vector_agent.search = saved

        assert state.refusal_reason == "no_case", intent
        assert called == [], f"{intent} searched the index with no case open"


def test_case_context_answers_from_the_open_case():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="What happened?")
    state.intent = "CASE_CONTEXT"
    state.active_entities.active_fir = "9"

    row = _row(fir_id="9")
    saved = (orch.sql_agent.fir_by_id, orch._officer_ps)
    orch.sql_agent.fir_by_id = lambda *a, **k: [row]
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        orch.sql_agent.fir_by_id, orch._officer_ps = saved

    assert [e.evidence_id for e in out] == ["fir:9"]
    assert "Hurt" in out[0].content


def test_case_people_lists_the_accused_and_resolves_a_single_one_as_active_person():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Who are the key people in this case?")
    state.intent = "CASE_PEOPLE"
    state.active_entities.active_fir = "9"

    accused = [{"PersonUID": 803, "CanonicalName": "Usha Naika", "AccusedName": "Usha Naika",
               "CommunityID": 4, "GangAffiliation": None, "PageRank": 0.01}]
    saved = (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case, orch._officer_ps)
    orch.sql_agent.fir_by_id = lambda *a, **k: [_row(fir_id="9")]
    orch.sql_agent.accused_on_case = lambda fid: accused
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case,
         orch._officer_ps) = saved

    assert [e.evidence_id for e in out] == ["accused:803"]
    assert "Usha Naika" in out[0].content
    assert state.active_entities.active_person == "803"


def test_case_people_leaves_active_person_unset_when_several_are_accused():
    """Naming ONE of several accused as 'the' subject would be the same unlicensed
    guess the ambiguous-name check refuses to make for a searched name."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Who are the key people in this case?")
    state.intent = "CASE_PEOPLE"
    state.active_entities.active_fir = "9"

    accused = [
        {"PersonUID": 1, "CanonicalName": "A", "AccusedName": "A", "CommunityID": None,
         "GangAffiliation": None, "PageRank": 0.0},
        {"PersonUID": 2, "CanonicalName": "B", "AccusedName": "B", "CommunityID": None,
         "GangAffiliation": None, "PageRank": 0.0},
    ]
    saved = (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case, orch._officer_ps)
    orch.sql_agent.fir_by_id = lambda *a, **k: [_row(fir_id="9")]
    orch.sql_agent.accused_on_case = lambda fid: accused
    orch._officer_ps = lambda _oid: ""
    try:
        orch._run_specialists(state, widen=False)
    finally:
        (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case,
         orch._officer_ps) = saved

    assert state.active_entities.active_person is None


def test_case_people_clears_a_stale_active_person_when_several_are_accused():
    """Found live (2026-08-26 golden-conversation pass): a person named several turns
    ago (e.g. from PERSON_HISTORY) stayed in active_person forever, because the
    previous fix only checked 'if len(accused) == 1: set it' and did nothing
    otherwise — leaving whatever was already there untouched. Re-opening a DIFFERENT
    multi-accused case therefore kept answering a pronoun follow-up ('does he have
    priors?') about the stale person instead of asking which of THIS case's several
    accused was meant, silently guessing instead of using the ambiguous_person
    clarification path this exact scenario exists to trigger."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Who is involved?")
    state.intent = "CASE_PEOPLE"
    state.active_entities.active_fir = "9"
    state.active_entities.active_person = "999"   # stale, from an earlier turn/case

    accused = [
        {"PersonUID": 1, "CanonicalName": "A", "AccusedName": "A", "CommunityID": None,
         "GangAffiliation": None, "PageRank": 0.0},
        {"PersonUID": 2, "CanonicalName": "B", "AccusedName": "B", "CommunityID": None,
         "GangAffiliation": None, "PageRank": 0.0},
    ]
    saved = (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case, orch._officer_ps)
    orch.sql_agent.fir_by_id = lambda *a, **k: [_row(fir_id="9")]
    orch.sql_agent.accused_on_case = lambda fid: accused
    orch._officer_ps = lambda _oid: ""
    try:
        orch._run_specialists(state, widen=False)
    finally:
        (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case,
         orch._officer_ps) = saved

    assert state.active_entities.active_person is None


def test_case_scoped_intents_refuse_rather_than_leak_a_case_outside_officer_scope():
    """The authorization requirement: active_fir being SET does not itself grant
    access — every case-scoped branch re-checks scope through the same station-
    filtered query FIR_LOOKUP uses, on every turn, not only when the FIR was first
    opened. Simulated here as the scoped fetch coming back empty (station mismatch),
    the same signal a real IO-vs-other-station mismatch produces."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    for intent in ("CASE_CONTEXT", "CASE_PEOPLE", "NEXT_STEPS"):
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IO",
                                   original_query="irrelevant text")
        state.intent = intent
        state.active_entities.active_fir = "9"

        called = []
        saved = (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case,
                 orch.copilot_brief.leads_for_case, orch.vector_agent.search, orch._officer_ps)
        orch.sql_agent.fir_by_id = lambda *a, **k: []          # outside this IO's station
        orch.sql_agent.accused_on_case = lambda fid: (called.append(1), [])[1]
        orch.copilot_brief.leads_for_case = lambda *a, **k: (called.append(1), [])[1]
        orch.vector_agent.search = lambda *a, **k: ([], [])
        orch._officer_ps = lambda _oid: "1201"
        try:
            out = orch._run_specialists(state, widen=False)
        finally:
            (orch.sql_agent.fir_by_id, orch.sql_agent.accused_on_case,
             orch.copilot_brief.leads_for_case, orch.vector_agent.search,
             orch._officer_ps) = saved

        assert called == [], f"{intent} read case data despite the scoped fetch finding nothing"
        assert out == [], intent


def test_similar_cases_uses_the_open_case_and_settles_without_generic_search():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Are there similar cases?")
    state.intent = "SIMILAR_CASES"
    state.active_entities.active_fir = "9"

    candidate = {**_row(fir_id="10"), "similarity": 0.71,
                "explanation": "same crime type (Hurt); same district (Mandya)"}
    called = []
    saved = (orch.sql_agent.fir_by_id, orch.copilot_brief.similar_cases_for,
            orch.vector_agent.search, orch._officer_ps)
    orch.sql_agent.fir_by_id = lambda *a, **k: [_row(fir_id="9")]
    orch.copilot_brief.similar_cases_for = lambda case, limit=5: [candidate]
    orch.vector_agent.search = lambda *a, **k: (called.append(1), ([], []))[1]
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        (orch.sql_agent.fir_by_id, orch.copilot_brief.similar_cases_for,
         orch.vector_agent.search, orch._officer_ps) = saved

    assert called == [], "generic vector search ran despite a case-scoped similar-cases answer"
    assert len(out) == 1
    assert out[0].confidence_kind == "similarity"
    assert "same crime type" in out[0].content


def test_next_steps_states_leads_as_authoritative():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="What should I investigate next?")
    state.intent = "NEXT_STEPS"
    state.active_entities.active_fir = "9"

    saved = (orch.sql_agent.fir_by_id, orch.copilot_brief.leads_for_case, orch._officer_ps)
    orch.sql_agent.fir_by_id = lambda *a, **k: [_row(fir_id="9")]
    orch.copilot_brief.leads_for_case = lambda *a, **k: ["Pull the prior files on X."]
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        orch.sql_agent.fir_by_id, orch.copilot_brief.leads_for_case, orch._officer_ps = saved

    assert len(out) == 1
    assert out[0].authoritative is True
    assert "Pull the prior files" in out[0].content


def test_briefing_uses_the_copilot_draft_and_leads():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Prepare the briefing")
    state.intent = "BRIEFING"
    state.active_entities.active_fir = "9"

    from rag_agent.state import CopilotBrief
    brief = CopilotBrief(fir_id="9", timeline=[{"date": "2026-01-01", "event": "x"}],
                         similar_cases=[], leads=["Interview the co-accused."],
                         draft_summary="FIR 9, Hurt, registered ... Under Investigation.")
    saved = orch.copilot_brief.generate_copilot_brief
    orch.copilot_brief.generate_copilot_brief = lambda *a, **k: brief
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        orch.copilot_brief.generate_copilot_brief = saved

    assert any(e.content == brief.draft_summary for e in out)
    assert any("Interview the co-accused" in e.content for e in out)
    assert all(e.authoritative for e in out)


def test_briefing_refuses_gracefully_when_not_permitted():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IO",
                               original_query="Prepare the briefing")
    state.intent = "BRIEFING"
    state.active_entities.active_fir = "9"

    def deny(*a, **k):
        raise orch.copilot_brief.NotPermitted("wrong station")

    saved = (orch.copilot_brief.generate_copilot_brief, orch.vector_agent.search)
    orch.copilot_brief.generate_copilot_brief = deny
    orch.vector_agent.search = lambda *a, **k: ([], [])
    try:
        out = orch._run_specialists(state, widen=False)
    finally:
        orch.copilot_brief.generate_copilot_brief, orch.vector_agent.search = saved

    assert out == []      # no leak, no crash — the trace records why, the answer stays empty


# --- Meta-questions about the previous turn -----------------------------------

def _prior_turn(**over):
    from data import ConversationTurn
    from datetime import datetime, timezone
    base = dict(
        turn_index=0, query="Does Usha Naika have priors?", language="en",
        final_answer="...", citations=[{"index": 1, "evidence_id": "fir:9", "label": "FIR 9 ..."}],
        evidence_items=[{"evidence_id": "fir:9", "source_type": "FIR_RECORD", "source_id": "9",
                         "source_query": "q", "content": "FIR 9, Hurt.", "confidence": 0.95,
                         "authoritative": False, "confidence_kind": "support",
                         "timestamp": datetime.now(timezone.utc).isoformat()}],
        visualization={"kind": "none", "data": {}},
        agent_trace=[{"step": "SQL Agent", "detail": "1 criminal-record row(s)",
                     "duration_ms": 5, "confidence": None}],
        created_at=datetime.now(timezone.utc))
    base.update(over)
    return ConversationTurn(**base)


def test_explain_reasoning_restates_the_previous_trace():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Why are you showing me these people?")
    state.intent = "EXPLAIN_REASONING"

    saved = orch._last_turn
    orch._last_turn = lambda sid: _prior_turn()
    try:
        orch.node_retrieve(state)
        orch.node_evaluate(state)
        orch.node_synthesize(state)
    finally:
        orch._last_turn = saved

    assert "criminal-record row" in state.final_answer
    assert len(state.citations) == 1


def test_evidence_for_restates_the_previous_citations():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="What evidence supports that?")
    state.intent = "EVIDENCE_FOR"

    saved = orch._last_turn
    orch._last_turn = lambda sid: _prior_turn()
    try:
        orch.node_retrieve(state)
        orch.node_evaluate(state)
        orch.node_synthesize(state)
    finally:
        orch._last_turn = saved

    assert "[1]" in state.final_answer
    assert state.citations[0].evidence_id == "fir:9"
    assert state.evidence_items[0].evidence_id == "fir:9"


@pytest.mark.parametrize("intent", ["EXPLAIN_REASONING", "EVIDENCE_FOR"])
def test_meta_questions_refuse_honestly_on_a_first_turn(intent):
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="why is that")
    state.intent = intent

    saved = orch._last_turn
    orch._last_turn = lambda sid: None
    try:
        orch.node_retrieve(state)
        orch.node_evaluate(state)
        orch.node_synthesize(state)
    finally:
        orch._last_turn = saved

    assert state.citations == []
    assert "nothing" in state.final_answer.lower() or "first" in state.final_answer.lower()


def test_case_locations_tallies_districts_from_the_previous_turns_fir_citations():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Where are those cases concentrated?")
    state.intent = "CASE_LOCATIONS"

    prior = _prior_turn(citations=[{"index": 1, "evidence_id": "fir:9", "label": "x"},
                                   {"index": 2, "evidence_id": "fir:10", "label": "y"}])
    rows = [_row(fir_id="9", district="Mandya"), _row(fir_id="10", district="Mandya")]
    saved = (orch._last_turn, orch.sql_agent.cases_by_ids, orch.sql_agent.filter_viewable)
    orch._last_turn = lambda sid: prior
    orch.sql_agent.cases_by_ids = lambda ids: rows
    orch.sql_agent.filter_viewable = lambda rows, role, ps: rows
    try:
        orch.node_retrieve(state)
    finally:
        (orch._last_turn, orch.sql_agent.cases_by_ids,
         orch.sql_agent.filter_viewable) = saved

    assert state.refusal_reason == ""
    assert len(state.evidence_items) == 1
    assert "Mandya (2)" in state.evidence_items[0].content
    assert state.evidence_items[0].authoritative is True


def test_case_locations_refuses_when_nothing_prior_named_a_case():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Where are those cases concentrated?")
    state.intent = "CASE_LOCATIONS"

    saved = orch._last_turn
    orch._last_turn = lambda sid: None
    try:
        orch.node_retrieve(state)
    finally:
        orch._last_turn = saved

    assert state.refusal_reason == "nothing_prior_locations"


# --- Ambiguous names: ask, don't guess ----------------------------------------

def test_an_ambiguous_name_asks_instead_of_guessing():
    """Two people share a name with no clear leader by record count — the engine
    must not silently pick one, the same discipline it already applies to a name
    matching nobody at all."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Does Ramesh have priors?")

    tied = [{"person_id": "1", "name_en": "Ramesh Gowda", "record_count": 2},
           {"person_id": "2", "name_en": "Ramesh Kumar", "record_count": 2}]
    saved = orch.sql_agent.person_by_name
    orch.sql_agent.person_by_name = lambda *a, **k: tied
    try:
        orch.node_orchestrate(state)
    finally:
        orch.sql_agent.person_by_name = saved

    assert state.active_entities.active_person is None
    assert state.refusal_reason == "ambiguous_person"
    assert set(state.ambiguous_candidates) == {"Ramesh Gowda", "Ramesh Kumar"}


def test_a_clear_leader_is_still_resolved_automatically():
    """The fix must not swing the other way: a real, non-tied leader still resolves
    without asking — this is what makes 'Does Usha Naika have priors' work at all."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Does Usha Naika have priors?")

    ranked = [{"person_id": "803", "name_en": "Usha Naika", "record_count": 12},
             {"person_id": "999", "name_en": "Usha N.", "record_count": 1}]
    saved = orch.sql_agent.person_by_name
    orch.sql_agent.person_by_name = lambda *a, **k: ranked
    try:
        orch.node_orchestrate(state)
    finally:
        orch.sql_agent.person_by_name = saved

    assert state.active_entities.active_person == "803"
    assert state.refusal_reason == ""


def test_the_ambiguous_person_answer_names_the_candidates():
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Does Ramesh have priors?")
    state.refusal_reason = "ambiguous_person"
    state.requires_escalation = True
    state.ambiguous_candidates = ["Ramesh Gowda", "Ramesh Kumar"]

    orch.node_synthesize(state)

    assert "Ramesh Gowda" in state.final_answer and "Ramesh Kumar" in state.final_answer
    assert state.citations == []


def test_a_no_evidence_refusal_does_not_keep_the_evidence_it_rejected():
    """Found live 2026-08-27 (final judge pass): 'Tell me about the flying saucer
    incident on the moon' correctly refused in the chat text ('I could not find this
    in the available records') but the Evidence rail still rendered 8 unrelated
    robbery FIRs at ~40% text similarity — the exact widened search CRAG had just
    REJECTed. Root cause: this refusal branch (requires_escalation, reason
    'no_evidence') cleared state.citations but not state.evidence_items, unlike every
    other refusal branch in node_synthesize (CAPABILITY, 'nothing_prior',
    'ambiguous_person' all clear both). A refusal that already knows it has nothing
    to cite must not still ship the evidence it rejected to the client."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Tell me about the flying saucer incident on the moon.")
    state.refusal_reason = "no_evidence"
    state.requires_escalation = True
    state.evidence_items = [_ev(0.40, eid="vec:fir_narrative:1")]

    orch.node_synthesize(state)

    assert state.citations == []
    assert state.evidence_items == []


def test_network_evidence_never_says_gang():
    """CLAUDE.md §4: the ER records no gang, so the Louvain grouping is labelled
    honestly as what it is — 'network community 6' — everywhere else it's shown
    (copilot/brief.py's leads). This rendering was the one place still printing the
    literal word 'gang' in front of an officer, contradicting that documented rule."""
    import rag_agent.orchestrator as orch

    ev = orch._network_evidence({"person_id": "41", "name_en": "Usha Naika",
                                 "hops": 1, "gang": "Community 6"})
    assert "gang" not in ev.content.lower()
    assert "network community 6" in ev.content


def test_network_evidence_disambiguates_a_real_namesake_collision():
    """Found live 2026-08-27 (final judge pass): 'Who are her associates?' for Usha
    Naika listed 'Suma Nadkarni is a known associate...' TWICE, verbatim, in the same
    answer — confirmed via the raw evidence source_ids that these are two DIFFERENT
    real PersonUIDs (7334 and 8395) who happen to share a CanonicalName, not a
    duplicate-row bug. With nothing distinguishing them, it read as broken rendering
    rather than two real associates. Only a genuine collision within the same result
    set gets a disambiguator; an ordinary list of distinct names is untouched."""
    import rag_agent.orchestrator as orch

    rows = [
        {"person_id": "7334", "name_en": "Suma Nadkarni", "hops": 1, "gang": "Community 6"},
        {"person_id": "8395", "name_en": "Suma Nadkarni", "hops": 1, "gang": "Community 6"},
        {"person_id": "151", "name_en": "Nithin Madar", "hops": 1, "gang": "Community 6"},
    ]
    evidence = [orch._network_evidence(r, rows) for r in rows]

    assert "7334" in evidence[0].content and "8395" in evidence[1].content
    assert evidence[0].content != evidence[1].content
    assert "person" not in evidence[2].content.lower()  # untouched: no collision here


def test_a_bare_pronoun_after_case_people_asks_which_of_the_named_candidates():
    """CASE_PEOPLE lists every accused on a case but deliberately leaves active_person
    unset when there's more than one (naming one would be a guess). A pronoun follow-up
    ("does he have priors?") used to fall to a bare "no_subject" refusal that discarded
    the names the previous turn had just listed. Found live 2026-08-26: asking Usha
    Naika/Soom Nadkarni's case "Does he have priors?" refused with no names at all, even
    though both were on screen one turn earlier. It must now ask which of THOSE people,
    using the same ask-don't-guess path a tied name search already uses."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Does he have priors?")

    prior = _prior_turn(citations=[
        {"index": 1, "evidence_id": "accused:41",
         "label": "Usha Naika is accused on this case (network community 6)."},
        {"index": 2, "evidence_id": "accused:877",
         "label": "Soom Nadkarni is accused on this case (network community 6)."},
    ])
    saved = orch._last_turn
    orch._last_turn = lambda sid: prior
    try:
        orch.node_orchestrate(state)
    finally:
        orch._last_turn = saved

    assert state.active_entities.active_person is None
    assert state.refusal_reason == "ambiguous_person"
    assert set(state.ambiguous_candidates) == {"Usha Naika", "Soom Nadkarni"}


def test_a_bare_pronoun_with_no_recent_case_people_still_refuses_plainly():
    """The fix must not manufacture candidates that were never named — a prior turn
    with no `accused:` citations (e.g. a FIR lookup) falls back to the original,
    honest "no active person" note exactly as before."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Does he have priors?")

    prior = _prior_turn(citations=[{"index": 1, "evidence_id": "fir:9", "label": "FIR 9 ..."}])
    saved = orch._last_turn
    orch._last_turn = lambda sid: prior
    try:
        orch.node_orchestrate(state)
    finally:
        orch._last_turn = saved

    assert state.active_entities.active_person is None
    assert state.refusal_reason == ""
    assert state.ambiguous_candidates == []


def test_a_district_question_with_recent_person_candidates_is_not_hijacked():
    """Found live 2026-08-26: with two people named in the previous turn's citations
    (exactly the state test_a_bare_pronoun_after_case_people_asks... sets up), a
    question that merely happens to contain the word 'this' but names no person at
    all — 'How many gangs operate in this district?' — was answered as an ambiguous
    PERSON clarification instead of being classified and routed on its own terms."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="How many gangs operate in this district?")

    prior = _prior_turn(citations=[
        {"index": 1, "evidence_id": "accused:41", "label": "Usha Naika is accused..."},
        {"index": 2, "evidence_id": "accused:877", "label": "Soom Nadkarni is accused..."},
    ])
    saved = orch._last_turn
    orch._last_turn = lambda sid: prior
    try:
        orch.node_orchestrate(state)
    finally:
        orch._last_turn = saved

    assert state.refusal_reason == ""
    assert state.ambiguous_candidates == []
    assert state.intent != "PERSON_HISTORY"


def test_case_reference_by_position_refuses_without_touching_the_active_case():
    """'Go back to the first case' must refuse honestly rather than silently running
    a generic search — and must leave whatever case was already open untouched, since
    this turn named no new one."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Go back to the first case")
    state.intent = "CASE_REFERENCE_UNSUPPORTED"
    state.active_entities.active_fir = "9"          # a case is already open

    orch.node_retrieve(state)

    assert state.refusal_reason == "case_reference_unsupported"
    assert state.active_entities.active_fir == "9"  # untouched
    assert state.evidence_items == []


# --- Focus persists what retrieval resolves, not only what orchestrate resolved ----

def test_fir_lookup_persists_the_case_it_opens_for_the_next_turn():
    """BUG-level regression: node_orchestrate persists focus BEFORE retrieval runs,
    but FIR_LOOKUP resolves active_fir DURING retrieval. Without a second write,
    'Open FIR X' followed one turn later by 'What happened?' would find no case ever
    opened — the resolution lived only in this turn's in-memory response."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="What is the status of FIR 100222201202600022?")
    state.intent = "FIR_LOOKUP"

    hit = {"fir_id": "9", "fir_number": "100222201202600022", "ps_code": "1",
           "district": "Mandya", "crime_type": "Hurt", "date_filed": "2026-06-30",
           "case_status": "Under Investigation", "narrative": "n"}
    persisted = []
    saved = (orch.sql_agent.fir_by_number, orch.vector_agent.search, orch._officer_ps,
             orch.upsert_session_focus)
    orch.sql_agent.fir_by_number = lambda *a, **k: [hit]
    orch.vector_agent.search = lambda *a, **k: ([], [])
    orch._officer_ps = lambda _oid: ""
    orch.upsert_session_focus = lambda sid, oid, focus: persisted.append(focus.model_copy())
    try:
        orch.node_retrieve(state)
    finally:
        (orch.sql_agent.fir_by_number, orch.vector_agent.search, orch._officer_ps,
         orch.upsert_session_focus) = saved

    assert persisted, "session focus was never (re-)persisted after retrieval"
    assert persisted[-1].active_fir == "9", (
        "the FIR resolved during retrieval must be in the LAST persisted focus")


def test_person_history_and_hotspot_still_get_vector_corroboration():
    """The suppression must stay scoped — PERSON_HISTORY/HOTSPOT/FORECAST are not in
    _SPECIALIST_SETTLES and must keep running vector search. CRIME_SEARCH is the one
    exception: once it has produced its own exact count (BUG-008's fix), semantic
    neighbours cannot corroborate a count — they can only pad it — so it settles like
    the relational intents do."""
    from rag_agent.orchestrator import _RELATIONAL_INTENTS, _SPECIALIST_SETTLES
    assert "PERSON_HISTORY" not in _SPECIALIST_SETTLES
    assert "HOTSPOT" not in _SPECIALIST_SETTLES
    assert "FORECAST" not in _SPECIALIST_SETTLES
    assert "CRIME_SEARCH" in _SPECIALIST_SETTLES
    assert _RELATIONAL_INTENTS <= _SPECIALIST_SETTLES
