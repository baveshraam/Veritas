"""Compositional reference resolution + result-set awareness.

Structural extractors in semantic_interpreter.py, not phrase-specific patches — each
test below deliberately uses a PARAPHRASE of the reported/spec'd example, not the
exact wording, to prove the pattern generalizes rather than memorizing one sentence.

Live-reproduced baseline this pass fixes (docs/superpowers/specs/
2026-08-27-compositional-semantic-layer-design.md §1): a CRIME_SEARCH turn followed
by "Only these?" scored Intent: UNKNOWN and refused with no_evidence, even though the
previous turn's own count/sample was sitting right there.
"""
from datetime import datetime, timezone

from data import SessionFocus
from data.models import ConversationTurn
from rag_agent.semantic_interpreter import interpret


def _turn(citations=None, result_context=None, query="prior query", answer="prior answer"):
    return ConversationTurn(
        turn_index=0, query=query, language="en", final_answer=answer,
        citations=citations or [], evidence_items=[], visualization={}, agent_trace=[],
        created_at=datetime.now(timezone.utc), result_context=result_context or {},
    )


# --- Result-set awareness ----------------------------------------------------

def test_only_these_reads_the_real_prior_result_not_a_fresh_search():
    """The exact baseline defect: a sampled CRIME_SEARCH result followed by a
    bare exhaustiveness check must resolve to the result-set follow-up path,
    never UNKNOWN."""
    prior = _turn(result_context={
        "operation": "CRIME_SEARCH", "total_matched": 42, "shown": 5,
        "is_sample": True, "shown_ids": ["1", "2", "3", "4", "5"],
    })
    req = interpret("Only these?", "en", SessionFocus(), prior_turn=prior)
    assert req.operation == "RESULT_SET_FOLLOWUP"
    assert req.previous_result_context["total_matched"] == 42


def test_are_there_more_is_a_paraphrase_of_only_these():
    prior = _turn(result_context={
        "operation": "CRIME_SEARCH", "total_matched": 12, "shown": 5,
        "is_sample": True, "shown_ids": ["1"],
    })
    req = interpret("Are there more than what you just showed me?", "en",
                    SessionFocus(), prior_turn=prior)
    assert req.operation == "RESULT_SET_FOLLOWUP"


def test_exhausted_result_set_does_not_trigger_followup_without_a_prior_turn():
    """No antecedent -> falls through to the ordinary classify() path, honestly
    UNKNOWN, exactly as it does today -- this pattern must never fire on a cold
    first turn."""
    req = interpret("Only these?", "en", SessionFocus(), prior_turn=None)
    assert req.operation != "RESULT_SET_FOLLOWUP"


def test_ambiguous_more_falls_back_to_exploration_when_no_bounded_result_exists():
    """'What else?' after a non-bounded answer (e.g. PERSON_HISTORY, no
    result_context) with a person in focus reads as 'tell me more about him',
    not a result-set check -- context disambiguates the same surface phrase."""
    prior = _turn(result_context={})
    req = interpret("What else?", "en", SessionFocus(active_person="42"), prior_turn=prior)
    assert req.operation == "PERSON_HISTORY"
    assert req.reference_kind == "exploration"
    assert req.subject_id == "42"


def test_go_deeper_is_unambiguous_exploration_never_a_result_set_check():
    prior = _turn(result_context={
        "operation": "CRIME_SEARCH", "total_matched": 42, "shown": 5,
        "is_sample": True, "shown_ids": ["1"],
    })
    req = interpret("Can we dig deeper on this?", "en",
                    SessionFocus(active_fir="900"), prior_turn=prior)
    assert req.operation == "CASE_CONTEXT"
    assert req.reference_kind == "exploration"


# --- Positional / ordinal reference -------------------------------------------

def test_the_second_one_resolves_against_the_prior_ordered_citation_list():
    prior = _turn(citations=[
        {"index": 1, "evidence_id": "assoc:501", "label": "Person A"},
        {"index": 2, "evidence_id": "assoc:502", "label": "Person B"},
    ])
    req = interpret("Tell me about the second one.", "en", SessionFocus(), prior_turn=prior)
    assert req.subject_type == "person"
    assert req.subject_id == "502"
    assert req.reference_kind == "positional"


def test_item_number_is_a_paraphrase_of_the_ordinal_form():
    prior = _turn(citations=[
        {"index": 1, "evidence_id": "fir:9001", "label": "FIR one"},
        {"index": 2, "evidence_id": "fir:9002", "label": "FIR two"},
        {"index": 3, "evidence_id": "fir:9003", "label": "FIR three"},
    ])
    req = interpret("What about item 3?", "en", SessionFocus(), prior_turn=prior)
    assert req.subject_type == "case"
    assert req.subject_id == "9003"


def test_ordinal_plus_operation_composes_in_one_turn():
    """'does the second one have priors' -- the ordinal resolves WHO, the
    keyword-scored operation (already present today) resolves WHAT; the two are
    independent signals, not a new combined pattern."""
    prior = _turn(citations=[
        {"index": 1, "evidence_id": "assoc:501", "label": "Person A"},
        {"index": 2, "evidence_id": "assoc:502", "label": "Person B"},
    ])
    req = interpret("Does the second one have any priors?", "en",
                    SessionFocus(), prior_turn=prior)
    assert req.operation == "PERSON_HISTORY"
    assert req.subject_id == "502"


def test_bare_ordinal_defaults_to_the_richest_single_call_profile():
    """No operation verb at all -- 'the second one' alone -- defaults to a full
    profile rather than refusing with nothing to do."""
    prior = _turn(citations=[
        {"index": 1, "evidence_id": "assoc:501", "label": "Person A"},
        {"index": 2, "evidence_id": "assoc:502", "label": "Person B"},
    ])
    req = interpret("The second one.", "en", SessionFocus(), prior_turn=prior)
    assert req.operation == "PERSON_HISTORY"
    assert req.subject_id == "502"


def test_the_other_person_resolves_among_exactly_two_named_candidates(monkeypatch):
    import rag_agent.semantic_interpreter as si

    prior = _turn(citations=[
        {"index": 1, "evidence_id": "accused:1", "label": "Ramesh Gowda is accused on this case ..."},
        {"index": 2, "evidence_id": "accused:2", "label": "Suresh Naik is accused on this case ..."},
    ])
    monkeypatch.setattr(si.sql_agent, "person_by_name", lambda name: (
        [{"person_id": 501, "name_en": name}] if name == "Ramesh Gowda" else
        [{"person_id": 502, "name_en": name}] if name == "Suresh Naik" else []
    ))
    req = interpret("What about the other person?", "en",
                    SessionFocus(active_person="501"), prior_turn=prior)
    assert req.subject_type == "person"
    assert req.subject_id == "502"


# --- Constraint-change follow-up ("same thing for Bengaluru") ----------------

def test_same_thing_for_a_new_district_reuses_the_prior_operation():
    prior = _turn(result_context={
        "operation": "CRIME_SEARCH", "total_matched": 7, "shown": 5, "is_sample": True,
        "shown_ids": ["1"], "constraints": {"crime_type": "Theft", "district": "Mandya"},
    })
    req = interpret("What about Bengaluru?", "en", SessionFocus(), prior_turn=prior)
    assert req.operation == "CRIME_SEARCH"
    assert req.reference_kind == "constraint_change"
    # crime type carries forward from the prior turn; district is overridden by
    # THIS turn's own text via the same LOCATION gazetteer NER uses elsewhere.
    assert req.constraints["crime_type"] == "Theft"
    assert "Bengaluru" in req.constraints["district"]


def test_and_for_is_a_paraphrase_of_same_thing_for():
    prior = _turn(result_context={
        "operation": "HOTSPOT", "total_matched": None, "shown": 0, "is_sample": False,
        "shown_ids": [], "constraints": {"district": "Kolar"},
    })
    req = interpret("And for Mysuru district?", "en", SessionFocus(), prior_turn=prior)
    assert req.operation == "HOTSPOT"
    assert "Mysuru" in req.constraints["district"]


# --- Bare "why" / temporal follow-ups -----------------------------------------

def test_bare_why_reads_as_explain_reasoning_only_with_a_prior_turn():
    prior = _turn()
    assert interpret("Why those?", "en", SessionFocus(), prior_turn=prior).operation \
        == "EXPLAIN_REASONING"
    assert interpret("Why?", "en", SessionFocus(), prior_turn=prior).operation \
        == "EXPLAIN_REASONING"


def test_bare_why_does_not_steal_a_real_causal_question():
    req = interpret("Why do more crimes happen in poorer districts?", "en",
                    SessionFocus(), prior_turn=_turn())
    assert req.operation != "EXPLAIN_REASONING"


def test_bare_temporal_relation_widens_into_timeline():
    prior = _turn()
    req = interpret("Yeah but before this?", "en",
                    SessionFocus(active_person="42"), prior_turn=prior)
    assert req.operation == "TIMELINE"


def test_bare_temporal_relation_does_not_steal_a_dated_question():
    req = interpret("How many murders happened before 2020?", "en",
                    SessionFocus(), prior_turn=_turn())
    assert req.operation != "TIMELINE"


# --- Bounded deterministic multi-step composition -----------------------------

def test_two_named_people_with_a_coordination_cue_resolve_as_a_comparison(monkeypatch):
    import rag_agent.semantic_interpreter as si

    monkeypatch.setattr(si.sql_agent, "person_by_name", lambda name: (
        [{"person_id": "501", "name_en": "Ramesh Gowda"}] if "Ramesh" in name else
        [{"person_id": "502", "name_en": "Suresh Naik"}] if "Suresh" in name else []
    ))
    req = interpret(
        "Check whether either Ramesh Gowda or Suresh Naik had a prior case.",
        "en", SessionFocus(), prior_turn=None)
    assert sorted(req.comparison_entities) == ["501", "502"]
    assert req.operation == "PERSON_HISTORY"


def test_back_reference_pair_resolves_against_the_prior_turns_own_candidates(monkeypatch):
    import rag_agent.semantic_interpreter as si

    prior = _turn(citations=[
        {"index": 1, "evidence_id": "accused:1", "label": "Ramesh Gowda is accused on this case ..."},
        {"index": 2, "evidence_id": "accused:2", "label": "Suresh Naik is accused on this case ..."},
    ])
    monkeypatch.setattr(si.sql_agent, "person_by_name", lambda name: (
        [{"person_id": "501", "name_en": name}] if name == "Ramesh Gowda" else
        [{"person_id": "502", "name_en": name}] if name == "Suresh Naik" else []
    ))
    req = interpret("Did both of them have a case in Bengaluru as well?", "en",
                    SessionFocus(), prior_turn=prior)
    assert sorted(req.comparison_entities) == ["501", "502"]


def test_three_or_more_names_is_not_a_bounded_comparison(monkeypatch):
    """Explicit non-goal (design spec §3): three+ names is the open-ended planning
    case this deliberately does not attempt -- must fall through, not guess a pair."""
    import rag_agent.semantic_interpreter as si

    monkeypatch.setattr(si.sql_agent, "person_by_name",
                        lambda name: [{"person_id": "1", "name_en": name}])
    req = interpret("Check whether Ramesh, Suresh or Ganesh had a prior case.", "en",
                    SessionFocus(), prior_turn=None)
    assert req.comparison_entities == []


def test_handle_comparison_runs_the_same_retrieval_path_once_per_subject(monkeypatch):
    """orchestrator._handle_comparison sequences the EXISTING single-subject
    PERSON_HISTORY retrieval once per compared id, tags each result by name, and
    restores active_person afterward -- proving this reuses retrieval/RBAC rather
    than inventing a parallel code path."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import InvestigationState

    state = InvestigationState(
        session_id="s", officer_id="1", officer_role="IG",
        original_query="Check whether either of them had a case in Mandya.")
    state.intent = "PERSON_HISTORY"
    state.comparison_subject_ids = ["501", "502"]
    state.active_entities.active_person = None

    sample = {"fir_id": "9", "fir_number": "1", "district": "Mandya",
              "ps_code": "1", "crime_type": "Theft", "date_filed": "2026-01-01",
              "case_status": "Under Investigation", "narrative": "n"}
    names = {"501": "Ramesh Gowda", "502": "Suresh Naik"}
    saved = (orch.sql_agent.person_name, orch.sql_agent.person_record,
            orch.hipporag.retrieve, orch.vector_agent.search, orch._officer_ps)
    orch.sql_agent.person_name = lambda pid: names[pid]
    orch.sql_agent.person_record = lambda pid: [dict(sample, fir_id=pid)]
    orch.hipporag.retrieve = lambda *a, **k: ([], [])
    orch.vector_agent.search = lambda *a, **k: ([], [])
    orch._officer_ps = lambda _oid: ""
    try:
        orch._handle_comparison(state, widen=False, t0=0.0)
    finally:
        (orch.sql_agent.person_name, orch.sql_agent.person_record,
         orch.hipporag.retrieve, orch.vector_agent.search, orch._officer_ps) = saved

    assert state.active_entities.active_person is None, "active_person restored after the loop"
    tags = {e.evidence_id.rsplit("#cmp:", 1)[1] for e in state.evidence_items}
    assert tags == {"501", "502"}
    contents = " ".join(e.content for e in state.evidence_items)
    assert "Ramesh Gowda" in contents and "Suresh Naik" in contents
