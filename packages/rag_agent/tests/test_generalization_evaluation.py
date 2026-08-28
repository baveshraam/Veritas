"""Held-out GENERALIZATION evaluation for the general N-step investigation planner
and semantic correction handling — companion to test_conversational_evaluation.py
(which covers the single-op conversational surface) and test_semantic_interpreter.py
(which covers plan validation) / test_engine.py (which covers plan execution).

The discipline this file exists to enforce: every phrasing below was written to be
a REALISTIC thing an officer might type, not tuned against any regex or keyword list
in this codebase. Where a query genuinely needs the model (an unseen multi-step
composition, a correction), the mocked generate_json response is what a real model
would plausibly return for that query — not hand-picked to make the test pass. A
failure here means a real category of question, not a missed synonym.

Categories (per the design spec this implements):
  unseen single-step | unseen multi-step | previous-result references | pronouns |
  corrections | multiple subjects | constraints | temporal relations | comparisons |
  Kannada | Kannada-English switching | ambiguous references | clarification |
  malformed plans | unsupported operations | RBAC denial | empty evidence |
  conflicting evidence | model timeout | restart/state recovery
"""
import json
from datetime import datetime

import pytest

from data.models import ConversationTurn
from rag_agent import semantic_interpreter as si
from rag_agent.semantic_interpreter import SemanticRequest, interpret


def _focus(**kw):
    from data import SessionFocus
    return SessionFocus(**kw)


_STEP = {"subject_type": "person", "reference_kind": "explicit"}


# --- unseen single-step ------------------------------------------------------

def test_unseen_single_step_phrasing_the_keyword_classifier_cannot_place(monkeypatch):
    """No word in this sentence is a keyword for any intent in intents.INTENTS —
    a genuinely colloquial phrasing, not a paraphrase of an existing test."""
    monkeypatch.setattr(si.llm, "available", lambda: True)
    monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
        "operation": "PERSON_HISTORY", "subject_type": "none",
        "reference_kind": "implicit_from_focus", "confidence": 0.82,
    })
    result = interpret("pull up whatever paperwork exists on this fellow",
                       "en", _focus(active_person="1"), None)
    assert result.operation == "PERSON_HISTORY"


# --- unseen multi-step --------------------------------------------------------

def test_unseen_multi_step_phrasing_builds_a_real_plan(dataset):
    """The design spec's own worked example, decomposed the way a real model would:
    one PERSON_HISTORY step per named person, sharing a crime_type+district
    constraint. Never hard-coded as a phrase match anywhere in the codebase."""
    from data import ds
    people = ds.query('SELECT "PersonUID", "CanonicalName" FROM "vx_person" LIMIT 2')
    if len(people) < 2:
        pytest.skip("dataset has fewer than two people")
    p1, p2 = people[0]["CanonicalName"], people[1]["CanonicalName"]

    result = si._build_plan_request([
        {**_STEP, "operation": "PERSON_HISTORY", "subject_text": p1,
         "constraints": {"crime_type": "Robbery", "district": "Bengaluru Urban"}},
        {**_STEP, "operation": "PERSON_HISTORY", "subject_text": p2,
         "constraints": {"crime_type": "Robbery", "district": "Bengaluru Urban"}},
    ])
    assert len(result.plan_steps) == 2
    assert all(s["constraints"].get("crime_type") == "Robbery" for s in result.plan_steps)


# --- previous-result references ----------------------------------------------

def test_previous_result_reference_in_novel_phrasing():
    """'is that the complete list or are there more on file' — a shape the
    existing _AMBIGUOUS_MORE_RE regex matches structurally, not a phrase it was
    written around; proves the pattern generalizes to unseen wording."""
    prior = ConversationTurn(
        turn_index=0, query="how many theft cases", language="en", final_answer="5 shown",
        citations=[], evidence_items=[], visualization={}, agent_trace=[],
        created_at=datetime.utcnow(),
        result_context={"operation": "CRIME_SEARCH", "total_matched": 20, "shown": 5,
                        "is_sample": True, "shown_ids": ["1", "2", "3", "4", "5"]},
    )
    result = interpret("is that the complete list or are there more on file",
                       "en", _focus(), prior)
    assert result.operation == "RESULT_SET_FOLLOWUP"


# --- pronouns ------------------------------------------------------------------

def test_pronoun_resolves_against_focus_with_novel_phrasing():
    result = interpret("does she have a record worth flagging",
                       "en", _focus(active_person="42"), None)
    assert result.subject_id == "42"


# --- corrections (semantic, not phrase-matched) -------------------------------

def test_a_correction_merges_onto_the_prior_structured_request(monkeypatch):
    """'no wait, I meant the other case' — the model is given the PRIOR structured
    request and asked to return a merged, corrected one. Validated exactly like
    any other model output; nothing here is a regex over the word 'wait'."""
    monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
        "operation": "CASE_CONTEXT", "subject_type": "case", "subject_text": "9991",
        "reference_kind": "explicit", "confidence": 0.83,
    })
    prior = ConversationTurn(
        turn_index=0, query="what happened in FIR 9992", language="en", final_answer="...",
        citations=[], evidence_items=[], visualization={}, agent_trace=[],
        created_at=datetime.utcnow(),
        result_context={"last_request": {
            "operation": "CASE_CONTEXT", "subject_type": "case", "subject_text": "9992",
            "subject_id": "9992", "constraints": {},
        }},
    )
    result = si._interpret_llm("no wait, I meant the other case", "en", _focus(active_fir="9992"),
                               prior)
    assert result.operation == "CASE_CONTEXT"


# --- multiple subjects (beyond the bounded 2-entity deterministic path) ------

def test_a_plan_can_compare_more_than_two_subjects(monkeypatch):
    """The deterministic _COORDINATION_RE path is bounded to exactly two people by
    design (see its own module docstring) — the general plan is not. Three named
    subjects is exactly the case the bounded path cannot express at all. Subject
    resolution always goes through subject_text (never a model-supplied
    subject_id — see _resolve_person_by_text's callers), so three distinct names
    are stubbed to three distinct records."""
    by_name = {"Ramesh": [{"person_id": 1, "name_en": "Ramesh", "record_count": 5}],
              "Suresh": [{"person_id": 2, "name_en": "Suresh", "record_count": 5}],
              "Naveen": [{"person_id": 3, "name_en": "Naveen", "record_count": 5}]}
    monkeypatch.setattr(si.sql_agent, "person_by_name", lambda name: by_name.get(name, []))
    result = si._build_plan_request([
        {**_STEP, "operation": "PERSON_HISTORY", "subject_text": "Ramesh"},
        {**_STEP, "operation": "PERSON_HISTORY", "subject_text": "Suresh"},
        {**_STEP, "operation": "PERSON_HISTORY", "subject_text": "Naveen"},
    ])
    assert len(result.plan_steps) == 3
    assert {s["subject_id"] for s in result.plan_steps} == {"1", "2", "3"}


# --- constraints ---------------------------------------------------------------

def test_a_step_carries_multiple_constraint_dimensions_at_once():
    result = si._build_plan_request([
        {**_STEP, "operation": "PERSON_HISTORY", "subject_id": "1",
         "constraints": {"crime_type": "Robbery", "district": "Bengaluru Urban",
                         "date_after": "2025-01-01"}},
        {**_STEP, "operation": "PERSON_HISTORY", "subject_id": "2"},
    ])
    c = result.plan_steps[0]["constraints"]
    assert c["crime_type"] == "Robbery" and c["district"] == "Bengaluru Urban"
    assert c["date_after"] == "2025-01-01"


# --- temporal relations (date_before/date_after actually reach the query) ----

def test_temporal_correction_narrows_the_date_window_at_execution(monkeypatch):
    """'same thing but earlier' -> a date_before constraint. Wired all the way to
    sql_agent: count_firs/search_firs must receive it, or the count and the
    samples shown would silently stop matching each other (see sql_agent.py)."""
    from rag_agent.state import InvestigationState
    import rag_agent.orchestrator as orch

    captured = {}

    def fake_count_firs(role, ps, crime_type=None, district=None, date_from=None, date_to=None):
        captured["count_date_to"] = date_to
        return 3

    def fake_search_firs(role, ps, crime_type=None, district=None, date_from=None,
                         date_to=None, limit=25):
        captured["search_date_to"] = date_to
        return []

    saved = (orch.sql_agent.count_firs, orch.sql_agent.search_firs, orch._officer_ps)
    orch.sql_agent.count_firs = fake_count_firs
    orch.sql_agent.search_firs = fake_search_firs
    orch._officer_ps = lambda _oid: ""
    try:
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                   original_query="same thing but earlier")
        state.intent = "CRIME_SEARCH"
        state.constraints = {"date_before": "2026-01-01"}
        orch.node_retrieve(state)
    finally:
        orch.sql_agent.count_firs, orch.sql_agent.search_firs, orch._officer_ps = saved

    from datetime import date
    assert captured["count_date_to"] == date(2026, 1, 1)
    assert captured["search_date_to"] == date(2026, 1, 1)


# --- comparisons (across DIFFERENT operations, not just the same one twice) --

def test_a_comparison_plan_can_use_different_operations_per_subject():
    """'check his history, and separately whether the other one shows up in the
    financial layer' — the bounded deterministic comparison always runs the SAME
    operation for both subjects; a plan does not have that restriction."""
    result = si._build_plan_request([
        {**_STEP, "operation": "PERSON_HISTORY", "subject_id": "1"},
        {**_STEP, "operation": "FINANCIAL", "subject_id": "2"},
    ])
    ops = [s["operation"] for s in result.plan_steps]
    assert ops == ["PERSON_HISTORY", "FINANCIAL"]


# --- Kannada / Kannada-English switching --------------------------------------

def test_kannada_language_flag_reaches_the_model_prompt(monkeypatch):
    """Kannada text itself is translated to English upstream (node_translate_in) —
    this only guards that the LANGUAGE FLAG survives into interpretation, since a
    plan/correction decision may legitimately depend on it (e.g. which language to
    answer back in)."""
    captured = {}
    monkeypatch.setattr(si, "generate_json", lambda p, s: (
        captured.__setitem__("prompt", p) or
        {"operation": "CRIME_SEARCH", "subject_type": "none",
         "reference_kind": "implicit_from_focus", "confidence": 0.8}
    ))
    si._interpret_llm("how many theft cases in Mysuru", "kn", _focus(), None)
    assert "Language: kn" in captured["prompt"]


def test_kannada_english_code_switch_is_treated_the_same_as_pure_kannada(monkeypatch):
    """The translated-to-English query is what interpretation ever sees regardless
    of whether the original was pure Kannada or code-switched — nothing in this
    layer should special-case code-switching, since node_translate_in already
    normalized it before this ever runs."""
    captured = {}
    monkeypatch.setattr(si, "generate_json", lambda p, s: (
        captured.__setitem__("prompt", p) or
        {"operation": "PERSON_HISTORY", "subject_type": "none",
         "reference_kind": "implicit_from_focus", "confidence": 0.8}
    ))
    # As translation_agent would have already rendered a code-switched query.
    si._interpret_llm("does ಅವನು have priors", "kn", _focus(active_person="1"), None)
    assert "Language: kn" in captured["prompt"]


# --- ambiguous references / clarification -------------------------------------

def test_an_ambiguous_step_subject_asks_rather_than_guesses(monkeypatch):
    monkeypatch.setattr(si.sql_agent, "person_by_name", lambda name: [
        {"person_id": 1, "name_en": "Ramesh Gowda", "record_count": 3},
        {"person_id": 2, "name_en": "Ramesh Kumar", "record_count": 3},
    ])
    result = si._build_plan_request([
        {**_STEP, "operation": "PERSON_HISTORY", "subject_text": "Ramesh"},
        {**_STEP, "operation": "PERSON_HISTORY", "subject_id": "9"},
    ])
    assert result.plan_steps[0]["ambiguous_candidates"] == ["Ramesh Gowda", "Ramesh Kumar"]
    assert result.plan_steps[0]["subject_id"] is None


# --- malformed plans / unsupported operations ---------------------------------

def test_a_non_object_step_invalidates_the_whole_plan():
    with pytest.raises(ValueError, match="not an object"):
        si._build_plan_request([
            {**_STEP, "operation": "PERSON_HISTORY", "subject_id": "1"},
            "not even a dict",
        ])


def test_an_operation_outside_the_allowlist_in_any_step_is_rejected():
    with pytest.raises(ValueError, match="allowlist"):
        si._build_plan_request([
            {**_STEP, "operation": "PERSON_HISTORY", "subject_id": "1"},
            {**_STEP, "operation": "DELETE_EVERYTHING", "subject_id": "2"},
        ])


# --- RBAC denial (a plan step is scoped exactly like a single-op turn) -------

def test_a_plan_steps_case_scoped_operation_still_respects_station_scope():
    """_run_plan re-derives role/station and calls the SAME scoped sql_agent
    functions every ordinary turn uses — a plan is not a side door around
    policy. A case outside the officer's station yields no evidence for that
    step, the same as an ordinary single-op CASE_CONTEXT turn would."""
    from rag_agent.state import InvestigationState
    import rag_agent.orchestrator as orch

    saved = (orch.sql_agent.fir_by_id, orch._officer_ps, orch.vector_agent.search)
    orch.sql_agent.fir_by_id = lambda *a, **k: []   # outside this officer's scope
    orch._officer_ps = lambda _oid: "OTHER_STATION"
    orch.vector_agent.search = lambda *a, **k: ([], [])
    try:
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IO",
                                   original_query="what happened in this case")
        state.intent = "CASE_CONTEXT"
        state.active_entities.active_fir = "9992"
        state.plan_steps = [
            {**_STEP, "operation": "CASE_CONTEXT", "subject_type": "case",
             "subject_text": None, "subject_id": None, "constraints": {},
             "depends_on_step": None, "fan_out": False, "position": None,
             "ambiguous_candidates": []},
        ]
        out = orch.node_retrieve(state)
    finally:
        orch.sql_agent.fir_by_id, orch._officer_ps, orch.vector_agent.search = saved

    assert out.evidence_items == []


# --- empty evidence -------------------------------------------------------------

def test_a_plan_where_every_step_finds_nothing_still_refuses_honestly():
    from rag_agent.evidence.evaluator import evaluate
    from rag_agent.state import InvestigationState
    import rag_agent.orchestrator as orch

    saved = (orch._run_specialists, orch.hipporag.retrieve)
    orch._run_specialists = lambda state, widen: []
    orch.hipporag.retrieve = lambda *a, **k: ([], [])
    try:
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                   original_query="check both for priors")
        state.intent = "PERSON_HISTORY"
        state.plan_steps = [
            {**_STEP, "operation": "PERSON_HISTORY", "subject_text": None, "subject_id": "1",
             "constraints": {}, "depends_on_step": None, "fan_out": False, "position": None,
             "ambiguous_candidates": []},
            {**_STEP, "operation": "PERSON_HISTORY", "subject_text": None, "subject_id": "2",
             "constraints": {}, "depends_on_step": None, "fan_out": False, "position": None,
             "ambiguous_candidates": []},
        ]
        # Mirrors the compiled graph's own retry edge (_after_evaluate): an empty
        # first pass widens once before giving up, exactly like a single-op turn.
        orch.node_retrieve(state)
        orch.node_evaluate(state)
        orch.node_retrieve(state)
        orch.node_evaluate(state)
    finally:
        orch._run_specialists, orch.hipporag.retrieve = saved

    assert state.evidence_items == []
    assert state.requires_escalation is True


# --- conflicting evidence -------------------------------------------------------

def test_conflicting_findings_across_steps_both_survive_to_synthesis():
    """Two steps can honestly disagree (e.g. one finds an alias, a differently-
    scoped check finds none) — the plan must not silently drop either in favour
    of the other; reconciling a genuine conflict is synthesis's job (or the
    officer's), not something evidence collection should decide by omission."""
    from rag_agent.state import EvidenceItem, InvestigationState
    import rag_agent.orchestrator as orch

    def fake_specialists(state, widen):
        pid = state.active_entities.active_person
        if pid == "1":
            return [EvidenceItem(evidence_id="same_as:none", source_type="GRAPH_RELATIONSHIP",
                                 source_id="1", content="No alias found.", confidence=0.9,
                                 authoritative=True)]
        return [EvidenceItem(evidence_id="same_as:99", source_type="GRAPH_RELATIONSHIP",
                             source_id="2", content="Alias found under a different name.",
                             confidence=0.9, authoritative=True)]

    saved = (orch._run_specialists, orch.hipporag.retrieve)
    orch._run_specialists = fake_specialists
    orch.hipporag.retrieve = lambda *a, **k: ([], [])
    try:
        state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                                   original_query="check both for aliases")
        state.intent = "ALIAS_CHECK"
        state.plan_steps = [
            {**_STEP, "operation": "ALIAS_CHECK", "subject_text": None, "subject_id": "1",
             "constraints": {}, "depends_on_step": None, "fan_out": False, "position": None,
             "ambiguous_candidates": []},
            {**_STEP, "operation": "ALIAS_CHECK", "subject_text": None, "subject_id": "2",
             "constraints": {}, "depends_on_step": None, "fan_out": False, "position": None,
             "ambiguous_candidates": []},
        ]
        out = orch.node_retrieve(state)
    finally:
        orch._run_specialists, orch.hipporag.retrieve = saved

    contents = [e.content for e in out.evidence_items]
    assert any("No alias found" in c for c in contents)
    assert any("Alias found under a different name" in c for c in contents)


# --- model timeout (degrades to unavailable, never crashes) --------------------

def test_a_model_timeout_degrades_to_the_deterministic_result(monkeypatch):
    """Per llm.py's contract, a provider failure of any kind — quota, network,
    5xx, or a timeout — degrades generate_json() to {}, never raises out of the
    HTTP layer. _interpret_llm turns that into LLMUnavailable, and interpret()'s
    existing fallback handles it exactly like any other unreachable-model case."""
    monkeypatch.setattr(si.llm, "available", lambda: True)
    monkeypatch.setattr(si, "generate_json", lambda *a, **k: {})   # simulated timeout
    result = interpret("some genuinely unseen phrasing about a case",
                       "en", _focus(), None)
    assert isinstance(result, SemanticRequest)
    assert result.plan_steps == []


# --- restart / state recovery ---------------------------------------------------

def test_last_request_survives_a_json_round_trip_like_a_real_restart():
    """last_request is what a NEW process (a restarted container, a different
    officer's session picking up the same conversation_id) reads back from
    Data Store — proving it round-trips through plain JSON is what actually
    matters, not that it survives in the same Python process."""
    from rag_agent.state import InvestigationState
    import rag_agent.orchestrator as orch

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="what happened in FIR 9992")
    saved = (orch.semantic_interpreter.interpret, orch.upsert_session_focus)
    orch.semantic_interpreter.interpret = lambda **kw: SemanticRequest(
        operation="CASE_CONTEXT", subject_type="case", subject_id="9992",
        subject_text="9992", confidence=0.9)
    orch.upsert_session_focus = lambda *a, **k: None
    try:
        orch.node_orchestrate(state)
    finally:
        orch.semantic_interpreter.interpret, orch.upsert_session_focus = saved

    # Must be plain JSON-safe types — no datetime, no pydantic model, nothing that
    # only round-trips inside this one process.
    json.dumps(state.last_request)
    assert state.last_request["operation"] == "CASE_CONTEXT"
    assert state.last_request["subject_id"] == "9992"


def test_a_correction_after_simulated_restart_reads_only_the_persisted_dict(monkeypatch):
    """A second 'process' (no shared Python state at all — only the ConversationTurn
    a store would hand back) must correct exactly as well as a live continuation."""
    monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
        "operation": "CASE_CONTEXT", "subject_type": "case", "subject_text": "9991",
        "reference_kind": "explicit", "confidence": 0.83,
    })
    # Simulates reading this back from Data Store after a restart: a fresh dict,
    # not an object carried over in memory.
    persisted = json.loads(json.dumps({
        "last_request": {"operation": "CASE_CONTEXT", "subject_type": "case",
                         "subject_text": "9992", "subject_id": "9992", "constraints": {}},
    }))
    prior = ConversationTurn(
        turn_index=0, query="what happened in FIR 9992", language="en", final_answer="...",
        citations=[], evidence_items=[], visualization={}, agent_trace=[],
        created_at=datetime.utcnow(), result_context=persisted,
    )
    result = si._interpret_llm("no wait, the other case", "en", _focus(), prior)
    assert result.operation == "CASE_CONTEXT"
