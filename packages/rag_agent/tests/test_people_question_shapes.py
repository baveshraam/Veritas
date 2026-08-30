"""Asking "who" about a case, in the words officers actually use.

CASE_PEOPLE's keyword list spelled out a handful of phrasings. Measured against
the LIVE deployment (2026-08-29), the near-misses each landed somewhere
plausible and wrong:

    "show everyone involved"          -> CRIME_SEARCH   ("show" is its verb)
    "Who is connected?"               -> CASE_CONTEXT   (nothing matched)
    "Anyone connected to this case?"  -> CASE_CONTEXT
    "Who does she run with?"          -> NEXT_STEPS

All four ask one thing. They are matched now by SHAPE — a who-word plus an
involvement word — alongside the module's other shape patterns, rather than by
adding one keyword per phrasing forever. These tests lock in the shape and, just
as importantly, the two boundaries it must not cross: a question that names a
subject is about that person's network, and a two-entity timeline question is
still a timeline question.
"""
import pytest

from rag_agent.intents import classify


@pytest.mark.parametrize("query", [
    "who are all involved",
    "who all are involved?",
    "everyone involved?",
    "who is involved here?",
    "who else is involved?",
    "show everyone involved",
    "who are the people involved?",
    "People involved?",
    "Who is connected?",
    "Anyone connected to this case?",
    "who is linked to this case",
    "anybody else implicated?",
])
def test_asking_who_is_in_the_open_case_reaches_case_people(query):
    assert classify(query) == "CASE_PEOPLE"


@pytest.mark.parametrize("query", [
    "Who does she run with?",
    "who does he hang around with",
    "who did Ramesh work with",
    "who does he deal with",
])
def test_asking_who_somebody_runs_with_is_the_co_offending_question(query):
    assert classify(query) == "PERSON_NETWORK"


@pytest.mark.parametrize("query", [
    "Who is connected to Usha Naika?",
    "who is involved with Ramesh Gowda",
    "who are the associates of Usha Naika?",
])
def test_the_same_shape_with_a_named_subject_is_that_persons_network(query):
    """The distinction is whether a SUBJECT is named. Routing these to the open
    case would answer about the wrong population."""
    assert classify(query) == "PERSON_NETWORK"


@pytest.mark.parametrize("query,expected", [
    ("why are these events connected", "TIMELINE_CONNECTION"),
    ("What happened in this case?", "CASE_CONTEXT"),
    ("Show me theft cases in Mysuru", "CRIME_SEARCH"),
    ("Show me crime hotspots", "HOTSPOT"),
    ("Show me the timeline for this case", "TIMELINE"),
    ("What should I investigate next?", "NEXT_STEPS"),
    ("Does Usha Naika have priors?", "PERSON_HISTORY"),
])
def test_the_new_shape_does_not_swallow_a_neighbouring_operation(query, expected):
    assert classify(query) == expected
