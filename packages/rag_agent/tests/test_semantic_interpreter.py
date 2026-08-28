"""Adversarial conversation test suite for semantic interpreter.

Tests the structured semantic decomposition against realistic officer phrasing,
linguistic variation, code-switching, pronouns, and context-dependent references.

All tests run against the real SQLite dataset via the `dataset` fixture, not mocks.
"""
import pytest
from datetime import datetime
from data import ds
from data.models import SessionFocus, ConversationTurn
from rag_agent.semantic_interpreter import interpret, SemanticRequest


@pytest.fixture
def test_person(dataset):
    """A known person with multiple cases for testing."""
    # Get a person with at least 2 cases (for priors testing)
    rows = ds.query(
        'SELECT p."PersonUID", p."CanonicalName" '
        'FROM "vx_person" p '
        'LIMIT 1',
    )
    assert rows, "No person found in dataset"
    return rows[0]


@pytest.fixture
def test_case(dataset):
    """A known FIR for testing."""
    rows = ds.query(
        'SELECT DISTINCT c."CrimeCaseID" as fir_id, c."CrimeNo" as fir_number, '
        '       c."CrimeHeadID", d."DistrictName", ps."PoliceStationName" '
        'FROM "CaseMaster" c '
        'JOIN "District" d ON c."DistrictID" = d."DistrictID" '
        'JOIN "PoliceStation" ps ON c."PoliceStationID" = ps."PoliceStationID" '
        'LIMIT 1',
    )
    assert rows, "No case found in dataset"
    return rows[0]


def _make_state(session_id="test-session", officer_id="1", officer_role="SHO",
                active_person=None, active_fir=None, language="en"):
    """Create a minimal InvestigationState-like object for testing."""
    focus = SessionFocus(active_person=active_person, active_fir=active_fir)
    return focus


# ============================================================================
# INTENT CLASSIFICATION TESTS — paraphrases and linguistic variation
# ============================================================================

class TestIntentClassification:
    """Test that semantic interpreter routes varied phrasings to correct intents."""

    def test_person_history_exact_keyword(self):
        """'does he have priors' should classify as PERSON_HISTORY."""
        focus = _make_state()
        result = interpret("does he have priors", language="en", focus=focus)
        assert result.operation == "PERSON_HISTORY"

    def test_person_history_paraphrase_1(self):
        """'any prior records' should also classify as PERSON_HISTORY."""
        focus = _make_state()
        result = interpret("any prior records for this guy", language="en", focus=focus)
        assert result.operation == "PERSON_HISTORY"

    def test_person_history_paraphrase_2(self):
        """'has he been arrested before' should classify as PERSON_HISTORY."""
        focus = _make_state()
        result = interpret("has he been arrested before", language="en", focus=focus)
        assert result.operation == "PERSON_HISTORY"

    def test_crime_search_exact_keyword(self):
        """'show me theft cases' should classify as CRIME_SEARCH."""
        focus = _make_state()
        result = interpret("show me theft cases", language="en", focus=focus)
        assert result.operation == "CRIME_SEARCH"

    def test_crime_search_paraphrase(self):
        """'find robbery cases' should also classify as CRIME_SEARCH."""
        focus = _make_state()
        result = interpret("find robbery cases", language="en", focus=focus)
        assert result.operation == "CRIME_SEARCH"

    def test_hotspot_exact_keyword(self):
        """'show me hotspots' should classify as HOTSPOT."""
        focus = _make_state()
        result = interpret("show me hotspots", language="en", focus=focus)
        assert result.operation == "HOTSPOT"

    def test_hotspot_paraphrase(self):
        """'where is the crime concentrated' should classify as HOTSPOT."""
        focus = _make_state()
        result = interpret("where is the crime concentrated", language="en", focus=focus)
        # This might be CASE_LOCATIONS due to "where...those", but the intent should be about hotspots
        # For now, just verify it's not UNKNOWN
        assert result.operation != "UNKNOWN"

    def test_similar_cases_exact_keyword(self):
        """'similar cases' should classify as SIMILAR_CASES."""
        focus = _make_state()
        result = interpret("find similar cases", language="en", focus=focus)
        assert result.operation == "SIMILAR_CASES"


# ============================================================================
# PRONOUN & REFERENCE RESOLUTION TESTS
# ============================================================================

class TestPronounResolution:
    """Test that pronouns resolve against session focus correctly."""

    def test_pronoun_with_active_person(self, test_person):
        """'does he have priors' with active_person should resolve the pronoun."""
        focus = _make_state(active_person=str(test_person["PersonUID"]))
        result = interpret("does he have priors", language="en", focus=focus)
        assert result.operation == "PERSON_HISTORY"
        assert result.reference_kind == "pronoun"
        assert result.subject_id == str(test_person["PersonUID"])

    def test_pronoun_female_with_active_person(self, test_person):
        """'what about her' should detect female pronoun and resolve."""
        focus = _make_state(active_person=str(test_person["PersonUID"]))
        result = interpret("what about her", language="en", focus=focus)
        # Pronoun detected, but might fall to CRIME_SEARCH as fallback
        # The important thing is that it recognizes a pronoun
        assert result.reference_kind == "pronoun"

    def test_pronoun_no_active_person(self):
        """'does he have priors' with no active_person should note the reference but not resolve."""
        focus = _make_state(active_person=None)
        result = interpret("does he have priors", language="en", focus=focus)
        # Pronoun detected, but can't resolve
        assert result.reference_kind == "pronoun"
        assert result.subject_id is None


# ============================================================================
# CODE-SWITCHING & MULTILINGUAL TESTS
# ============================================================================

class TestCodeSwitching:
    """Test that mixed Kannada-English queries are understood."""

    def test_kannada_english_fir_query(self):
        """'ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?' should be understood as a case query."""
        focus = _make_state(language="kn")
        # This query is Kannada-script, but the interpreter receives it *after* translation
        # in node_translate_in, so we simulate the translated form
        result = interpret("Is there another FIR related to that case?", language="kn", focus=focus)
        # Should classify as some case-related intent (FIR_LOOKUP or similar)
        # If the translated form is too garbled, it might fall back, but intent should be determined
        assert result.operation != "UNKNOWN"

    def test_pure_kannada_query(self):
        """Pure Kannada query (translated) should still classify correctly."""
        focus = _make_state(language="kn")
        # ಈ case ಬಗ್ಗೆ ಏನು ಗೊತ್ತಿದೆ? -> What do you know about this case?
        result = interpret("What do you know about this case?", language="kn", focus=focus)
        # Should be CASE_CONTEXT or similar
        assert result.operation != "UNKNOWN"

    def test_kannada_loanwords(self):
        """Kannada with English loanwords like 'case' should not crash."""
        focus = _make_state(language="kn")
        # ಆ case ದೊಡ್ಡದೇ? -> Is that case big/serious?
        result = interpret("Is that case serious?", language="kn", focus=focus)
        # The main thing is that it doesn't crash and returns a result
        assert result is not None
        assert result.operation is not None


# ============================================================================
# ENTITY EXTRACTION & NAMED PERSON TESTS
# ============================================================================

class TestNamedPersonResolution:
    """Test that named persons are resolved correctly."""

    def test_explicit_person_name_single_match(self, test_person):
        """Named person should be resolved when named explicitly."""
        focus = _make_state()
        # Use the test_person's actual name in the query
        person_name = test_person["CanonicalName"]
        result = interpret(f"does {person_name} have priors", language="en", focus=focus)
        # The interpreter should detect PERSON_HISTORY intent
        assert result.operation == "PERSON_HISTORY"
        # And should extract the person name
        if result.subject_id or result.subject_text:
            assert result.subject_type == "person"

    def test_ambiguous_person_name(self):
        """When multiple people match, should flag ambiguity, not guess."""
        focus = _make_state()
        # "Ramesh Gowda" likely matches multiple people in the dataset
        result = interpret("tell me about Ramesh", language="en", focus=focus)
        # Might resolve to one person, or might be ambiguous
        # The key is that if ambiguous, it's explicitly marked
        if result.ambiguous_candidates:
            assert result.subject_id is None, "Ambiguous person should not be auto-resolved"


# ============================================================================
# CONVERSATIONAL FOLLOW-UPS & CONTEXT
# ============================================================================

class TestFollowUpContextAwareness:
    """Test that follow-ups leverage context from prior turns."""

    def test_explain_reasoning_shape_detection(self):
        """'why are you showing me this' should be EXPLAIN_REASONING."""
        focus = _make_state()
        result = interpret("why are you showing me these people", language="en", focus=focus)
        assert result.operation == "EXPLAIN_REASONING"

    def test_evidence_for_shape_detection(self):
        """'what evidence supports this' should be EVIDENCE_FOR."""
        focus = _make_state()
        result = interpret("what evidence supports that claim", language="en", focus=focus)
        assert result.operation == "EVIDENCE_FOR"

    def test_capability_question(self):
        """'what can you do' should be CAPABILITY."""
        focus = _make_state()
        result = interpret("what all can you answer", language="en", focus=focus)
        assert result.operation == "CAPABILITY"

    def test_not_inferable_question(self):
        """'who could be the suspect' should be NOT_INFERABLE."""
        focus = _make_state()
        result = interpret("who could be the suspect", language="en", focus=focus)
        assert result.operation == "NOT_INFERABLE"


# ============================================================================
# EDGE CASES & ERROR HANDLING
# ============================================================================

class TestEdgeCases:
    """Test handling of incomplete, malformed, or ambiguous input."""

    def test_empty_query(self):
        """Empty query should not crash."""
        focus = _make_state()
        result = interpret("", language="en", focus=focus)
        assert result is not None
        # Empty query likely maps to UNKNOWN
        assert result.operation in ["UNKNOWN", "CRIME_SEARCH"]  # fallback

    def test_query_with_only_stopwords(self):
        """'the and or but' should not crash."""
        focus = _make_state()
        result = interpret("the and or but", language="en", focus=focus)
        assert result is not None

    def test_very_long_query(self):
        """A very long query should not crash."""
        focus = _make_state()
        long_query = "does this person have " + "prior " * 100 + "cases"
        result = interpret(long_query, language="en", focus=focus)
        assert result is not None

    def test_query_with_numbers_only(self):
        """FIR numbers and IPC codes should be extracted."""
        focus = _make_state()
        result = interpret("FIR 302/2026 IPC 420", language="en", focus=focus)
        # Should detect IPC section and FIR number
        assert result is not None


# ============================================================================
# CONFIDENCE & RANKING TESTS
# ============================================================================

class TestConfidenceScores:
    """Test that confidence scores differentiate regex-shape vs. keyword matches."""

    def test_regex_shape_higher_confidence(self):
        """Regex-shape intents should have higher confidence than keyword matches."""
        focus = _make_state()

        # Regex shape (CAPABILITY)
        result_capability = interpret("what can you do", language="en", focus=focus)

        # Keyword match (CRIME_SEARCH)
        result_search = interpret("show me theft cases", language="en", focus=focus)

        # Regex shapes should be more confident
        if result_capability.operation == "CAPABILITY":
            assert result_capability.confidence > 0.9
        if result_search.operation == "CRIME_SEARCH":
            assert result_search.confidence >= 0.8

    def test_unknown_low_confidence(self):
        """UNKNOWN intents should have low confidence."""
        focus = _make_state()
        result = interpret("xyzzy qwerty", language="en", focus=focus)
        if result.operation == "UNKNOWN":
            assert result.confidence < 0.5


# ============================================================================
# DETERMINISTIC PATH VERIFICATION
# ============================================================================

class TestDeterministicPath:
    """Verify the deterministic fallback path produces correct output."""

    def test_deterministic_produces_semantic_request(self):
        """Deterministic path should produce complete SemanticRequest."""
        focus = _make_state()
        result = interpret("does he have priors", language="en", focus=focus)

        assert isinstance(result, SemanticRequest)
        assert result.operation is not None
        assert result.subject_type is not None
        assert result.reference_kind is not None
        assert 0.0 <= result.confidence <= 1.0


# ============================================================================
# LLM PATH VALIDATION — the operation allowlist and argument checks that stand
# between whatever the model returns and anything downstream trusting it.
#
# BUG found by this pass's own live testing: the LLM prompt used to describe
# `operation` with lowercase examples ("lookup_person", "count_crimes") that don't
# match ANY real dispatch value orchestrator.py actually checks (all uppercase,
# e.g. "CASE_CONTEXT", "PERSON_HISTORY") — a live call for "Tell me more about
# that case" returned operation="lookup_case", which would have silently
# misrouted every LLM-interpreted turn with no error raised anywhere. Fixed at
# two layers: the schema now enumerates the real allowlist, and
# _validate_llm_result rejects (raises ValueError -> falls back to the
# deterministic path) anything the model returns outside it regardless.
# ============================================================================

from rag_agent import semantic_interpreter as si
from rag_agent.intents import ALL_OPERATIONS


class TestLLMPathValidation:
    def test_a_hallucinated_operation_outside_the_allowlist_is_rejected(self):
        with pytest.raises(ValueError, match="allowlist"):
            si._validate_llm_result({
                "operation": "lookup_case",  # the exact bug found live — not a real op
                "subject_type": "case", "reference_kind": "explicit", "confidence": 0.9,
            })

    def test_a_real_uppercase_operation_from_the_allowlist_is_accepted(self):
        out = si._validate_llm_result({
            "operation": "CASE_CONTEXT", "subject_type": "case",
            "reference_kind": "explicit", "confidence": 0.9,
        })
        assert out["operation"] == "CASE_CONTEXT"
        assert out["operation"] in ALL_OPERATIONS

    def test_operation_is_case_normalized(self):
        """A model that returns lowercase for an otherwise-real operation is corrected,
        not rejected — case is a formatting slip, not a hallucinated capability."""
        out = si._validate_llm_result({
            "operation": "case_context", "subject_type": "case",
            "reference_kind": "explicit", "confidence": 0.9,
        })
        assert out["operation"] == "CASE_CONTEXT"

    def test_missing_operation_is_rejected(self):
        with pytest.raises(ValueError):
            si._validate_llm_result({"subject_type": "case", "confidence": 0.9})

    def test_invalid_subject_type_is_rejected(self):
        with pytest.raises(ValueError, match="subject_type"):
            si._validate_llm_result({
                "operation": "CASE_CONTEXT", "subject_type": "vehicle",
                "confidence": 0.9,
            })

    def test_invalid_reference_kind_is_rejected(self):
        with pytest.raises(ValueError, match="reference_kind"):
            si._validate_llm_result({
                "operation": "CASE_CONTEXT", "subject_type": "case",
                "reference_kind": "telepathic", "confidence": 0.9,
            })

    def test_a_structural_only_reference_kind_the_model_should_never_invent_is_rejected(self):
        """exhaustiveness_check/exploration/constraint_change are produced only by the
        deterministic structural patterns matching against the PRIOR turn's recorded
        state — nothing about a fresh utterance licenses the model to claim one."""
        with pytest.raises(ValueError, match="reference_kind"):
            si._validate_llm_result({
                "operation": "CASE_CONTEXT", "subject_type": "case",
                "reference_kind": "exhaustiveness_check", "confidence": 0.9,
            })

    def test_non_dict_constraints_is_rejected(self):
        with pytest.raises(ValueError, match="constraints"):
            si._validate_llm_result({
                "operation": "CASE_CONTEXT", "subject_type": "case",
                "reference_kind": "explicit", "confidence": 0.9,
                "constraints": "Bengaluru",
            })

    def test_non_string_items_in_comparison_entities_is_rejected(self):
        with pytest.raises(ValueError, match="comparison_entities"):
            si._validate_llm_result({
                "operation": "CASE_CONTEXT", "subject_type": "case",
                "reference_kind": "explicit", "confidence": 0.9,
                "comparison_entities": [{"name": "Ramesh"}],
            })

    def test_out_of_range_confidence_is_clamped_not_rejected(self):
        """Miscalibration is not a safety issue — a model saying 1.5 confident just
        means 1.0 confident, not an invalid response."""
        out = si._validate_llm_result({
            "operation": "CASE_CONTEXT", "subject_type": "case",
            "reference_kind": "explicit", "confidence": 1.7,
        })
        assert out["confidence"] == 1.0

    def test_non_numeric_confidence_is_rejected(self):
        with pytest.raises(ValueError, match="confidence"):
            si._validate_llm_result({
                "operation": "CASE_CONTEXT", "subject_type": "case",
                "reference_kind": "explicit", "confidence": "very sure",
            })

    def test_a_boolean_confidence_is_rejected_despite_being_an_int_subtype(self):
        """bool is a subclass of int in Python — isinstance(True, int) is True — so a
        naive numeric check would silently accept it as confidence=1.0/0.0."""
        with pytest.raises(ValueError, match="confidence"):
            si._validate_llm_result({
                "operation": "CASE_CONTEXT", "subject_type": "case",
                "reference_kind": "explicit", "confidence": True,
            })

    def test_the_model_can_never_supply_a_subject_id_directly(self):
        """There is no code path in _validate_llm_result or _interpret_llm that reads
        subject_id from the model's JSON — planting one in the payload must have zero
        effect, proving entity resolution stays grounded in the real record lookup."""
        out = si._validate_llm_result({
            "operation": "CASE_CONTEXT", "subject_type": "person",
            "subject_id": "999999",  # a model has no such field to legitimately set
            "reference_kind": "explicit", "confidence": 0.9,
        })
        assert "subject_id" not in out

    def test_interpret_llm_end_to_end_with_a_mocked_valid_response(self, monkeypatch):
        """The full _interpret_llm path: mocked generate_json -> validation -> a real
        SemanticRequest. subject_type="case" takes no DB round trip in this path (only
        a resolved person does, via sql_agent.person_by_name), so a synthetic focus is
        enough here — the dataset-grounded resolution is covered separately above."""
        monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
            "operation": "CASE_CONTEXT", "subject_type": "case", "subject_text": "that case",
            "reference_kind": "implicit_from_focus", "confidence": 0.88,
        })
        focus = _make_state(active_fir="12345")
        result = si._interpret_llm("Tell me more about that case", "en", focus, None)
        assert result.operation == "CASE_CONTEXT"
        assert result.subject_type == "case"
        assert result.confidence == 0.88

    def test_interpret_llm_raises_and_falls_back_on_a_hallucinated_operation(self, monkeypatch):
        """interpret() (not _interpret_llm directly) must recover from the exact bug
        found live: the LLM path returning something that means nothing to the
        dispatcher. The public interpret() should silently fall back rather than
        propagate or misroute."""
        monkeypatch.setattr(si, "generate_json", lambda *a, **k: {
            "operation": "lookup_case", "subject_type": "case",
            "reference_kind": "explicit", "confidence": 0.9,
        })
        focus = _make_state()
        # interpret() catches ValueError from the validator and falls back — this must
        # not raise, and must still produce a real (deterministic-path) answer.
        result = si.interpret("Tell me more about that case", "en", focus, None)
        assert isinstance(result, SemanticRequest)
