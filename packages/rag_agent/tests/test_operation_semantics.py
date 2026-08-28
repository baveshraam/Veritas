"""Held-out evaluation of the semantic fallback tier (rag_agent/operation_semantics.py).

The point of this file is the *held-out* part. Every query below was written as a thing
an officer would plausibly type, without consulting the prototype strings in the module
under test — an evaluation whose inputs were written by paraphrasing the prototypes
would measure nothing but the paraphrase.

Two properties are being measured, and they matter in opposite directions:

  - **Resolution** — an unseen phrasing of a real question reaches the right operation,
    which is the whole reason this tier exists (the alternative is a 20-35s QuickML
    round trip, or a refusal when QuickML is down).
  - **Refusal** — an utterance that names a subject without asking anything about it,
    or that is simply out of domain, is *declined*. This is the load-bearing one: a
    confident wrong operation on "what is the weather today" produces a cited,
    authoritative-looking answer to a question nobody asked, and that is worse than
    every refusal in the system put together.

An accuracy figure is asserted rather than a per-query result, deliberately: a
per-query assertion invites fixing the prototype for the query, which is the
overfitting this file exists to detect. The refusal set IS asserted per-query, because
there is no acceptable rate of confidently answering nonsense.
"""
import pytest

from rag_agent import operation_semantics

# (query, expected_operation, has_person, has_case)
RESOLUTION_SET = [
    # person in focus, asking about a facet of that person
    ("has this fellow been booked before", "PERSON_HISTORY", True, False),
    ("what's on her sheet", "PERSON_HISTORY", True, False),
    ("who does he pull jobs with", "PERSON_NETWORK", True, False),
    ("which other offenders turn up alongside him", "PERSON_NETWORK", True, False),
    ("is she filed under a different spelling anywhere", "ALIAS_CHECK", True, False),
    ("do we have him under two identities", "ALIAS_CHECK", True, False),
    ("follow the cash through his bank accounts", "FINANCIAL", True, False),
    ("what transfers has she been making", "FINANCIAL", True, False),
    ("odds he offends again in six months", "RISK", True, False),
    ("how dangerous is this man to release", "RISK", True, False),
    # a case open, asking about a facet of that case
    ("summarise what actually happened here", "CASE_CONTEXT", False, True),
    ("give me the gist of this file", "CASE_CONTEXT", False, True),
    ("who else was booked on this one", "CASE_PEOPLE", False, True),
    ("name everyone charged here", "CASE_PEOPLE", False, True),
    ("what should I chase down next on this", "NEXT_STEPS", False, True),
    ("where do I go from here with this file", "NEXT_STEPS", False, True),
    ("draft a paragraph for the case diary", "BRIEFING", False, True),
    ("have we worked anything with the same method", "SIMILAR_CASES", False, True),
    # neither, but a district-scoped question that needs no subject
    ("which localities are seeing the most incidents", "HOTSPOT", False, False),
    ("plot where these crimes are clustering", "HOTSPOT", False, False),
    ("how many cases should we plan for next month", "FORECAST", False, False),
    ("is the caseload going up or down", "FORECAST", False, False),
    ("does joblessness explain the difference between districts", "CAUSAL", False, False),
]

# (a) Names a subject, asks nothing about it. This one is unconditional. These must
# keep semantic_interpreter's own deliberate richest-profile default ("tell me about
# X" -> the fullest profile of X), and before the reject class existed they did not:
# "I meant Usha Naika specifically" resolved to ALIAS_CHECK with a large margin, which
# is a wrong answer to a question the officer did not ask.
BARE_REFERENCE_SET = [
    ("tell me about Ramesh Gowda", True, False),
    ("I meant the Gowda one specifically", True, False),
    ("Ramesh Gowda", True, False),
    ("that one", True, False),
    ("open this record", False, True),
]

# (b) Out of domain. Asserted as a RATE with a named known miss, not unconditionally,
# because that is what was actually measured and the alternative would be dishonest.
# "what time does the canteen close" resolves to CASE_CONTEXT (0.592) when a case is
# open. Two fixes were tried and both rejected on evidence rather than taste:
#   - Adding out-of-domain descriptions to the reject class (they are in the module,
#     and they do correctly catch "when is my shift tomorrow" and "book me a meeting
#     room") does not catch this one: bge-small genuinely reads it as nearer to "the
#     brief facts of this case" than to "a question about something other than police
#     records".
#   - An absolute similarity floor would work here (0.592 vs the 0.693 lowest genuine
#     case-scoped win) but would also reject a real question measured at 0.589
#     ("anything else on our books that looks like this job?"). That trades a false
#     accept for a false reject and is tuned on the very queries being evaluated.
# The residual consequence is bounded and visible: with a case open, an out-of-domain
# question gets that case's summary — cited, obviously about the case, and impossible
# to mistake for an answer about the canteen. It is not a fabricated claim.
OUT_OF_DOMAIN_SET = [
    ("what is the weather today", False, False),
    ("tell me a joke", True, False),
    ("hello there", True, False),
    ("how do I reset my password", False, True),
    ("when is my shift tomorrow", False, True),
    ("book me a meeting room", False, True),
    ("what time does the canteen close", False, True),      # the known miss
]

MIN_RESOLUTION_ACCURACY = 0.80
MIN_OUT_OF_DOMAIN_REFUSAL = 0.85


@pytest.fixture(scope="module")
def _warm():
    """Embedding weights must be present; skip rather than fail where they are not
    (the same discipline every other model-dependent suite here uses)."""
    try:
        operation_semantics._prototype_matrix()
    except Exception as e:                                    # pragma: no cover
        pytest.skip(f"embedding model unavailable: {e}")


def test_unseen_phrasings_resolve_to_the_right_operation(_warm):
    """Accuracy over held-out phrasings, asserted as a rate, not per query."""
    wrong = []
    for query, expected, has_person, has_case in RESOLUTION_SET:
        got = operation_semantics.resolve(query, has_person=has_person, has_case=has_case)
        if got is None or got[0] != expected:
            wrong.append((query, expected, got[0] if got else None))

    accuracy = 1 - len(wrong) / len(RESOLUTION_SET)
    assert accuracy >= MIN_RESOLUTION_ACCURACY, (
        f"resolution accuracy {accuracy:.0%} < {MIN_RESOLUTION_ACCURACY:.0%}\n"
        + "\n".join(f"  {q!r}: want {w}, got {g}" for q, w, g in wrong))


@pytest.mark.parametrize("query,has_person,has_case", BARE_REFERENCE_SET)
def test_an_utterance_that_asks_nothing_is_declined(query, has_person, has_case, _warm):
    """Unconditional. An utterance that only NAMES a subject must leave
    semantic_interpreter's richest-profile default in place — pushing it onto a facet
    answers a question the officer did not ask, using the subject they did name, which
    reads as authoritative and is wrong."""
    assert operation_semantics.resolve(
        query, has_person=has_person, has_case=has_case) is None


def test_out_of_domain_input_is_mostly_declined(_warm):
    """A rate, with the one known miss named in OUT_OF_DOMAIN_SET's comment.

    Asserting 100% here would mean either deleting the query that fails or tuning the
    prototypes until it passes — both of which would make this file measure its own
    inputs instead of the module.
    """
    answered = [(q, operation_semantics.resolve(q, has_person=hp, has_case=hc))
                for q, hp, hc in OUT_OF_DOMAIN_SET]
    answered = [(q, r) for q, r in answered if r is not None]

    rate = 1 - len(answered) / len(OUT_OF_DOMAIN_SET)
    assert rate >= MIN_OUT_OF_DOMAIN_REFUSAL, (
        f"out-of-domain refusal rate {rate:.0%} < {MIN_OUT_OF_DOMAIN_REFUSAL:.0%}; "
        f"answered: {answered}")


def test_scope_gate_never_proposes_an_operation_the_turn_cannot_serve(_warm):
    """A case-scoped operation with no case open would be refused by node_retrieve the
    moment it was proposed (intents.NEEDS_CASE); proposing it anyway would turn a
    clean 'I did not understand' into a misleading 'no case is open'."""
    for query, _, _, _ in RESOLUTION_SET:
        got = operation_semantics.resolve(query, has_person=False, has_case=False)
        if got is not None:
            assert got[0] in operation_semantics._UNSCOPED, (
                f"{query!r} proposed {got[0]} with no subject and no case in session")


def test_declining_is_the_answer_when_the_model_cannot_be_loaded(monkeypatch):
    """This tier is an improvement on a fallback, never a dependency: if the embedding
    weights are missing the turn must proceed exactly as it did before this module
    existed, not fail."""
    monkeypatch.setattr(operation_semantics, "_prototype_matrix",
                        lambda: (_ for _ in ()).throw(RuntimeError("no weights")))
    assert operation_semantics.resolve(
        "who does he pull jobs with", has_person=True, has_case=False) is None
