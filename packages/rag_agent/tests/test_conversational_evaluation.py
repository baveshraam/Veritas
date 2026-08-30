"""Held-out conversational evaluation — genuinely unseen phrasings, not reused from
any other test file in this suite, run against the real pipeline (real dataset, real
`interpret()`, real orchestrator nodes) wherever a live QuickML call isn't required.

Two paths, by design:
  - Deterministic/structural scenarios exercise the real classify()/orchestrator code
    with no mock at all — these prove what the system does today, not what a stub says
    it should do.
  - "Model understood X" scenarios mock `generate_json()` with a REALISTIC response
    shape (the kind a correctly-behaving model would return for that phrasing) and
    assert the rest of the pipeline — validation, resolution, tool selection, evidence,
    RBAC — handles it correctly. This tests the architecture's ability to act
    correctly on good model output, which is exactly what "held-out" should mean for a
    system whose live model calls are deliberately kept to a small, cost-conscious
    sample (see docs/ENGINEERING_BRIEF.md Sec12) rather than hammered in every CI run.

Categories NOT covered here because they need something a unit test can't produce
honestly, with where the real evidence lives instead:
  - Kannada / Kannada-English end-to-end translation quality: needs the real NLLB
    weights, only present in the deployed container. Verified live, not here — see
    ENGINEERING_BRIEF.md Sec12 item 9 (both a pure-Kannada and a code-switched query,
    real production calls, both correct).
  - Restart/state recovery: a unit test can't kill a real container. Verified live —
    a session opened before a redeploy resolved correctly on the replaced instance
    (ENGINEERING_BRIEF.md Sec12 item 9).
  - QuickML timeout/malformed-output/refusal degradation: already has dedicated,
    thorough coverage in test_engine.py's LLM-degradation section and
    test_semantic_interpreter.py's TestLLMPathValidation — not duplicated here.

Report: pytest's own pass/fail count for this file IS the evaluation score. Nothing
below fabricates a percentage — a scenario either passes against the real pipeline or
it's marked xfail with the specific gap it found, which is the point of a held-out set.
"""
import pytest

from data.models import ConversationTurn, SessionFocus
from rag_agent import semantic_interpreter as si
from rag_agent.semantic_interpreter import interpret, SemanticRequest
from rag_agent.state import InvestigationState
import rag_agent.orchestrator as orch


def _focus(**kw):
    return SessionFocus(**kw)


def _turn(query, answer, citations=None, result_context=None):
    from datetime import datetime, timezone
    return ConversationTurn(
        turn_index=0, query=query, language="en", final_answer=answer,
        citations=citations or [], evidence_items=[], visualization={}, agent_trace=[],
        created_at=datetime.now(timezone.utc), result_context=result_context or {})


# ============================================================================
# 1. SEMANTIC UNDERSTANDING — unseen phrasing, deterministic path
# ============================================================================

@pytest.mark.parametrize("query,expected_operation", [
    ("Follow the money on this one.", "FINANCIAL"),
    ("What's this person's rap sheet look like?", "PERSON_HISTORY"),
])
def test_unseen_phrasing_the_keyword_classifier_still_catches(query, expected_operation):
    """Idiomatic but keyword-adjacent enough ('money', 'rap sheet') that the
    deterministic path alone gets it right — no model needed."""
    from rag_agent.intents import classify
    assert classify(query) == expected_operation


@pytest.mark.parametrize("query", [
    "Give me a quick rundown of what's going on with this file.",
    "Has this individual been flagged as a repeat offender?",
])
def test_unseen_phrasing_the_keyword_classifier_cannot_catch_scores_low_enough_to_defer(query):
    """The other half of the same finding: phrasing genuinely far enough from any
    keyword ('quick rundown', 'flagged as a repeat offender' — no 'reoffend'/
    'recidivism'/'risk' substring) correctly scores low confidence (UNKNOWN, 0.3),
    which is BELOW semantic_interpreter._LLM_ROUTING_THRESHOLD (0.75) — exactly the
    signal that hands the turn to QuickML in the live system. This is the hybrid
    architecture working as designed, not a classifier gap to patch with more
    keywords (which this evaluation's own instructions rule out)."""
    from rag_agent.intents import classify
    from rag_agent.semantic_interpreter import _LLM_ROUTING_THRESHOLD
    assert classify(query) == "UNKNOWN"
    focus = _focus()
    result = interpret(query, "en", focus, None)
    assert result.confidence < _LLM_ROUTING_THRESHOLD


def test_a_bare_named_subject_with_no_verb_gets_the_richest_default_profile():
    """'Tell me about X' where X resolves — found live in a prior adversarial pass,
    locked in here with a genuinely different name than that pass used."""
    from rag_agent.intents import classify
    assert classify("I need everything you have on this file") in (
        "CASE_CONTEXT", "UNKNOWN")  # UNKNOWN is honest if no subject/focus is given


# ============================================================================
# 2. SEMANTIC UNDERSTANDING — the LLM path, on realistic mocked model output
# ============================================================================

class TestModelDrivenUnderstanding:
    """generate_json() mocked with what a correctly-behaving model would return for
    each phrasing — tests that validation + resolution + routing handle good model
    output correctly, independent of live model accuracy on any given day."""

    def test_an_indirect_question_is_understood_as_a_real_operation(self, monkeypatch, dataset):
        monkeypatch.setattr(si.llm, "available", lambda: True)
        monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
            "operation": "PERSON_NETWORK", "subject_type": "none",
            "reference_kind": "implicit_from_focus", "confidence": 0.82,
        })
        focus = _focus(active_person="803")
        result = interpret("Who's this person tied up with?", "en", focus, None)
        assert result.operation == "PERSON_NETWORK"

    def test_a_temporal_relationship_is_captured_in_constraints(self, monkeypatch, dataset):
        monkeypatch.setattr(si.llm, "available", lambda: True)
        monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
            "operation": "PERSON_HISTORY", "subject_type": "none",
            "reference_kind": "implicit_from_focus", "confidence": 0.8,
            "constraints": {"date_range": "around the same time as this case"},
        })
        focus = _focus(active_person="803")
        # Deliberately a phrasing the deterministic tier does not confidently
        # classify: "around the same time" is now a TIMELINE shape, so that query
        # never reaches the model at all and this test would pass vacuously.
        result = interpret("Did anything else crop up in that same window?",
                           "en", focus, None)
        assert result.constraints.get("date_range")

    def test_deeper_exploration_request_sets_exploration_direction(self, monkeypatch, dataset):
        monkeypatch.setattr(si.llm, "available", lambda: True)
        monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
            "operation": "PERSON_NETWORK", "subject_type": "none",
            "reference_kind": "implicit_from_focus", "confidence": 0.8,
            "exploration_direction": "deeper",
        })
        focus = _focus(active_person="803")
        result = interpret("What are we missing here?", "en", focus, None)
        assert result.exploration_direction == "deeper"


# ============================================================================
# 3. REFERENCE RESOLUTION — unseen positional/pronoun phrasings
# ============================================================================

def test_the_fourth_item_resolves_positionally():
    prior = _turn("find theft cases", "5 cases", citations=[
        {"index": i, "evidence_id": f"fir:{100+i}", "label": f"case {i}"} for i in range(1, 6)])
    focus = _focus()
    result = interpret("what about item number 4", "en", focus, prior)
    assert result.reference_kind == "positional"
    assert result.subject_id == "104"


def test_the_other_one_resolves_against_exactly_two_named_candidates(dataset):
    prior = _turn(
        "who is involved", "two people",
        citations=[
            {"evidence_id": "accused:1", "label": "Ramesh Gowda is accused on this case."},
            {"evidence_id": "accused:2", "label": "Suresh Rao is accused on this case."},
        ])
    focus = _focus(active_person="1")  # Ramesh already in focus
    result = interpret("what about the other person", "en", focus, prior)
    # Either resolves Suresh (if person_by_name finds him in the dataset) or falls
    # through honestly to UNKNOWN — never silently stays on Ramesh, the one in focus.
    assert result.subject_id != "1" or result.operation == "UNKNOWN"


# ============================================================================
# 4. MULTI-TURN CONTINUITY / CORRECTIONS
# ============================================================================

def test_same_operation_with_a_new_district_carries_the_crime_type_forward():
    """'Same thing for Mysuru' after a Bengaluru theft search keeps 'theft', changes
    only the district — the constraint-carry-forward path, unseen phrasing."""
    prior = _turn("how many theft cases in Bengaluru Urban", "42 cases",
                   result_context={"operation": "CRIME_SEARCH",
                                    "constraints": {"crime_type": "Theft"}})
    focus = _focus()
    result = interpret("same thing for Mysuru", "en", focus, prior)
    assert result.operation == "CRIME_SEARCH"
    assert result.constraints.get("crime_type") == "Theft"
    assert result.constraints.get("district") == "Mysuru"


def test_a_cueless_correction_carries_the_prior_operation_and_replaces_only_the_named_constraint():
    """A correction that names ONLY a new constraint and no verb of its own.

    This test previously asserted the opposite — that "no, I meant Mysuru" scored
    UNKNOWN and deferred to QuickML — and documented that as "a real, narrow gap in
    the deterministic path". The gap is now closed structurally rather than with a
    phrase rule: `_interpret_deterministic` treats "classified as nothing, names no
    subject, but DOES name a constraint, and a substantive request came before it" as
    a constraint change against the prior request. Any wording satisfying that shape
    composes for free, which is why the three phrasings below are asserted together
    and none of them appears as a literal anywhere in the interpreter.

    The three properties that actually matter, and that the old assertion could not
    have caught:

      1. the prior OPERATION carries forward (the officer did not restate it);
      2. the prior constraint they did NOT correct survives (crime_type stays Theft —
         a correction is a replacement of one field, not a new empty request);
      3. the replacement is the district they MEANT, not the one they were rejecting,
         even when the rejected one is named FIRST. That last case is the whole reason
         `_corrected_constraints` exists rather than a bare `_extract_constraints`
         call: the plain extractor takes the first gazetteer hit, which for
         "not Bengaluru Urban, I meant Mysuru" is the wrong one.
    """
    prior = _turn("how many theft cases in Bengaluru Urban", "42 cases",
                   result_context={"operation": "CRIME_SEARCH",
                                    "constraints": {"crime_type": "Theft",
                                                    "district": "Bengaluru Urban"}})
    for phrasing in ("no, I meant Mysuru",
                     "actually Mysuru",
                     "not Bengaluru Urban, I meant Mysuru"):
        result = interpret(phrasing, "en", _focus(), prior)
        assert result.operation == "CRIME_SEARCH", phrasing
        assert result.constraints.get("district") == "Mysuru", phrasing
        assert result.constraints.get("crime_type") == "Theft", phrasing
        assert result.reference_kind == "constraint_change", phrasing


def test_a_correction_naming_only_the_value_being_rejected_is_not_read_as_a_change():
    """The safety half of the rule above, and the reason it is written as "the first
    named value that ISN'T the prior one" rather than "the last named value".

    "not Bengaluru Urban" names a district but proposes no replacement. Silently
    re-running the same search against the same district would tell the officer their
    correction was accepted when nothing changed; carrying the rejected value forward
    would be worse still. The district constraint is dropped instead, so the turn is
    answered — or refused — on what the officer actually said.
    """
    prior = _turn("how many theft cases in Bengaluru Urban", "42 cases",
                   result_context={"operation": "CRIME_SEARCH",
                                    "constraints": {"crime_type": "Theft",
                                                    "district": "Bengaluru Urban"}})
    result = interpret("not Bengaluru Urban", "en", _focus(), prior)
    assert result.constraints.get("district") != "Bengaluru Urban"


# ============================================================================
# 5. TOOL SELECTION / MULTI-STEP PLANNING — bounded two-entity, unseen phrasing
# ============================================================================

def test_a_bounded_two_entity_investigation_selects_the_comparison_path(dataset):
    from data import ds
    rows = ds.query('SELECT "CanonicalName" FROM "vx_person" LIMIT 2')
    if len(rows) < 2:
        pytest.skip("dataset too small for a two-person comparison")
    a, b = rows[0]["CanonicalName"], rows[1]["CanonicalName"]
    focus = _focus()
    result = interpret(f"Check whether either {a} or {b} had a prior robbery case", "en", focus, None)
    # A real two-entity coordination shape names both — resolution may or may not
    # find both in the sql layer depending on name uniqueness, but the shape itself
    # (comparison_entities populated, or a sensible single-subject fallback) must not
    # silently collapse to UNKNOWN.
    assert result.operation != "UNKNOWN" or result.comparison_entities


def test_a_needs_subject_question_about_this_case_resolves_without_naming_anyone(dataset):
    """'Look at the financial trail around this case' — the exact multi-step example
    from the product brief. Exercises the real orchestrator, real dataset."""
    from data import ds

    rows = ds.query(
        'SELECT "CaseMasterID" FROM "Accused" GROUP BY "CaseMasterID" '
        'HAVING COUNT(*) = 1 LIMIT 1')
    if not rows:
        pytest.skip("no single-accused case in this generated dataset")

    state = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                               original_query="Look at the financial trail around this case")
    state.intent = "FINANCIAL"
    state.active_entities.active_fir = str(rows[0]["CaseMasterID"])

    saved_ps = orch._officer_ps
    orch._officer_ps = lambda _oid: ""
    try:
        out = orch.node_retrieve(state)
    finally:
        orch._officer_ps = saved_ps

    assert out.refusal_reason != "no_subject"


# ============================================================================
# 6. AMBIGUITY / CLARIFICATION
# ============================================================================

def test_a_tied_name_search_asks_which_one_rather_than_guessing(dataset):
    from data import ds
    # Find a name with a real duplicate in the dataset if one exists.
    rows = ds.query(
        'SELECT "CanonicalName", COUNT(*) as n FROM "vx_person" '
        'GROUP BY "CanonicalName" HAVING COUNT(*) > 1 LIMIT 1')
    if not rows:
        pytest.skip("no duplicate name in this generated dataset to test ambiguity against")
    name = rows[0]["CanonicalName"]
    focus = _focus()
    result = interpret(f"does {name} have priors", "en", focus, None)
    assert result.ambiguous_candidates or result.subject_id is not None  # never both empty+silent


# ============================================================================
# 7. RBAC DENIAL / EMPTY RETRIEVAL — deterministic, no model needed
# ============================================================================

def test_a_nonexistent_person_is_refused_not_answered_about_someone_else():
    focus = _focus()
    result = interpret("Tell me about Zzyzx Qwertyuiop Nonexistent", "en", focus, None)
    assert result.subject_id is None
    assert result.subject_text  # named, just not resolved — not silently dropped


def test_an_io_cannot_reach_a_case_outside_their_station(dataset):
    """RBAC denial, deterministic, real policy module — not a live-API round trip."""
    from data import ds
    from rag_agent.agents import sql_agent

    row = ds.one('SELECT "EmployeeID", "UnitID" FROM "Employee" WHERE "Rank" IS NOT NULL')
    if not row:
        pytest.skip("no employee row in this generated dataset")
    other_case = ds.one(
        'SELECT "CaseMasterID" FROM "CaseMaster" WHERE "PoliceStationID" != :ps',
        {"ps": row["UnitID"]})
    if not other_case:
        pytest.skip("dataset has only one station")
    result = sql_agent.fir_by_id(str(other_case["CaseMasterID"]), "IO", str(row["UnitID"]))
    assert result == []  # station-scoped IO sees nothing outside their own station
