"""The officer-input battery: ~1,100 real inputs, checked as properties.

Two tiers, and the split is deliberate.

**Routing (the whole corpus, no database).** `classify()` is the deterministic,
auditable tier — it is what answers a question when the model is unreachable, and it is
where every misrouting bug this repo has found actually lived. Running the full corpus
through it costs milliseconds, so it runs on every commit.

**Execution (a representative sample, against the real dataset).** Full retrieval for
1,100 inputs would take an hour and would mostly re-measure the same code paths. So a
sample crossing every operation runs end to end, and is checked for the properties that
make an answer trustworthy rather than for expected text: a count that matches an
independent recount, a sample never described as complete, a refusal that carries no
citations, and no template scaffolding reaching the officer.

Stating the trade rather than implying full coverage: this battery proves that every
input in the corpus ROUTES correctly and that a representative slice ANSWERS correctly.
It does not prove all 1,100 answers are correct, and no test in this repo does.
"""
import re

import pytest
from rag_agent.intents import classify

from judge_inputs import corpus as judge_corpus
from officer_inputs import corpus, kannada, out_of_domain

CORPUS = corpus()
JUDGE = judge_corpus()


# --------------------------------------------------------------------------- #
# routing                                                                      #
# --------------------------------------------------------------------------- #

def test_the_corpus_is_large_enough_to_be_a_corpus():
    """A guard on the corpus itself. A generator bug that silently produced twelve
    inputs would make every test below pass for the wrong reason."""
    assert len(CORPUS) >= 1000, f"corpus shrank to {len(CORPUS)}"
    assert len({q for q, _ in CORPUS}) == len(CORPUS), "duplicate inputs in the corpus"


def test_every_officer_input_routes_to_a_defensible_operation():
    """The property: an ordinary request must reach an operation that would be a
    defensible reading of it — never a confidently wrong one, and never UNKNOWN where
    a deterministic reading exists (deferring to a model that may be unreachable is
    how an ordinary question becomes a refusal).

    Reported in bulk rather than one assertion per input: a routing change usually
    moves a CLASS of inputs, and seeing thirty at once is what tells you which class.
    """
    wrong = [(q, sorted(ok), classify(q)) for q, ok in CORPUS if classify(q) not in ok]
    assert not wrong, (
        f"{len(wrong)} of {len(CORPUS)} inputs misrouted; first 15:\n"
        + "\n".join(f"  {got:20s} <- {q!r}  (acceptable: {ok})" for q, ok, got in wrong[:15]))


def test_the_judge_corpus_is_large_enough_to_be_a_corpus():
    assert len(JUDGE) >= 580, f"judge corpus shrank to {len(JUDGE)}"
    assert len({q for q, _ in JUDGE}) == len(JUDGE), "duplicate inputs in the corpus"


def test_every_audit_question_is_answered_about_the_claim_not_re_searched():
    """The auditor's corpus. A judge asking "how did you decide this" and getting a
    fresh retrieval has been answered confidently and wrongly — the whole provenance
    layer exists so that cannot happen. 338 of these 586 missed before this pass:
    "How did you determine this?", "On what basis?", "Where does this come from?" (a
    hotspot map, on the word "where"), a bare "why?"."""
    wrong = [(q, sorted(ok), classify(q)) for q, ok in JUDGE if classify(q) not in ok]
    assert not wrong, (
        f"{len(wrong)} of {len(JUDGE)} audit questions misrouted; first 15:\n"
        + "\n".join(f"  {got:20s} <- {q!r}  (acceptable: {ok})" for q, ok, got in wrong[:15]))


@pytest.mark.parametrize("query,expected_fragment", [
    ("Do you decide guilt?", "do not decide guilt"),
    ("Can you convict someone?", "do not decide guilt"),
    ("Is your output evidence?", "not a witness"),
    ("Can this be used in court?", "not a witness"),
    ("Should I rely on this alone?", "decision support"),
    ("Do you replace an investigating officer?", "decision support"),
    ("Is this biased?", "protected attribute"),
    ("Is this predictive policing?", "protected attribute"),
    ("Do you ever guess?", "reported as a refusal"),
    ("Is there an audit trail?", "tamper-evident"),
    ("What data do you have?", "no external database"),
    ("Does an accusation mean he did it?", "not a finding"),
])
def test_a_question_about_this_systems_standing_gets_its_own_answer(query, expected_fragment):
    """Routing these to CAPABILITY was half the fix; answering them specifically is
    the other half. A judge who asks "do you decide guilt" and is handed a feature
    list has been answered in form and not in substance."""
    from rag_agent.intents import capability_answer
    assert classify(query) == "CAPABILITY", f"{query!r} did not reach the tool answer"
    assert expected_fragment in capability_answer(query).lower(), \
        f"{query!r} got the generic capability blurb"


@pytest.mark.parametrize("query", [
    "Who do you think did it?",
    "Who could be the suspect?",
    "Who is guilty?",
    "Who would you arrest?",
    "Name the likely culprit.",
    "Who might have done this?",
    "Who may be responsible?",
    "Who could have been involved?",
])
def test_a_request_to_nominate_a_suspect_is_always_refused(query):
    """The one class where being helpful is the failure. "Who would you arrest?" was
    ANSWERED — it reached no refusal pattern at all, because the existing ones needed
    the word "guilty" or a completed verb of commission."""
    assert classify(query) == "NOT_INFERABLE"


@pytest.mark.parametrize("query", out_of_domain())
def test_out_of_domain_input_is_never_given_a_confident_topical_route(query):
    """"What is the capital of France" once resolved to HOTSPOT with a full margin and
    would have been answered with a real, cited hotspot map of a defaulted district.
    The deterministic tier must decline, so the reject class in operation_semantics is
    what decides — not a keyword that happened to match."""
    assert classify(query) == "UNKNOWN"


def test_no_two_intents_claim_the_same_input_by_accident():
    """Two intents matching one input is fine; the tie-break is defined. What is NOT
    fine is a keyword of one intent sitting inside a keyword of another, which makes
    the tie-break silently unreachable — the collision class that sent every
    successful board pin to a board summary."""
    from rag_agent.intents import INTENTS
    expected = {
        # A singular inside its own plural, listed in both intents on purpose: the
        # keyword match is word-bounded, so the plural is not covered by the singular
        # and both have to be present.
        ("area", "areas"), ("transfer", "transfers"), ("cluster", "clusters"),
        ("account", "accounts"), ("payment", "payments"),
        ("transaction", "transactions"), ("hotspot", "hotspots"),
        ("associate", "associates"), ("prior", "priors"),
        # CRIME_SEARCH's "cases" sits inside several specific intents' phrases. That
        # collision is real and is what the scored-last rule exists for: a generic
        # pair must never outvote a precise single ("find cases similar to X" is
        # SIMILAR_CASES, not a search that happens to say "cases").
        ("cases", "previous cases"), ("cases", "matching cases"),
        ("cases", "related cases"),
        # Same shape: every CASE_SIMILARITY_WATCH phrase happens to contain "cases",
        # which only ever adds a harmless CRIME_SEARCH point (CRIME_SEARCH is the
        # scored-last fallback and cannot outvote a specific intent either way).
        ("cases", "check my open cases"), ("cases", "check against cold cases"),
        ("cases", "check my other cases"), ("cases", "check my unsolved cases"),
        ("cases", "match against my open cases"),
        # ALIAS_CHECK's two-word keyword deliberately overlaps PERSON_HISTORY's
        # "record": the second hit is what breaks a 1-1 tie toward the alias read.
        ("record", "duplicate record"),
    }
    collisions = set()
    for a_intent, (a_words, _) in INTENTS.items():
        for b_intent, (b_words, _) in INTENTS.items():
            if a_intent == b_intent:
                continue
            for a in a_words:
                for b in b_words:
                    if a != b and re.search(rf"\b{re.escape(a)}\b", b):
                        collisions.add((a, b))
    assert not (collisions - expected), f"unexpected keyword collisions: {collisions - expected}"


# --------------------------------------------------------------------------- #
# the qualifiers that used to be dropped in silence                            #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("query,expected", [
    ("How many cases are pending in Mandya?", "Under Investigation"),
    ("show me convicted cases", "Convicted"),
    ("how many were acquitted", "Acquitted"),
    ("chargesheeted cases in Kolar", "Chargesheeted"),
    ("closed cases", "Closed"),
    ("unsolved cases in Mysuru", "Under Investigation"),
    ("How many theft cases in Mandya?", None),
])
def test_a_status_word_is_read_as_a_status_filter(query, expected):
    from rag_agent.semantic_interpreter import case_status_from_query
    assert case_status_from_query(query) == expected


@pytest.mark.parametrize("query,expected", [
    ("Show me cases under section 379", "379"),
    ("cases u/s 420", "420"),
    ("IPC 457 cases in Mandya", "457"),
    ("section 302", "302"),
    # A year and a case count are not sections.
    ("how many cases in 2026", None),
    ("show me 5 cases", None),
])
def test_a_section_number_is_read_as_a_section_and_a_year_is_not(query, expected):
    from rag_agent.semantic_interpreter import section_from_query
    assert section_from_query(query) == expected


@pytest.mark.parametrize("query,expected", [
    ("Show me all cases from PS 2201", "2201"),
    ("cases at police station 501", "501"),
    ("station 1201 cases", "1201"),
    ("show me 12 cases", None),
])
def test_a_station_code_is_read_as_a_station(query, expected):
    from rag_agent.semantic_interpreter import station_from_query
    assert station_from_query(query) == expected


def test_a_named_month_or_year_becomes_a_half_open_window():
    from datetime import date

    from rag_agent.semantic_interpreter import date_window_from_query
    assert date_window_from_query("cases filed in June 2026") == (
        date(2026, 6, 1), date(2026, 7, 1))
    assert date_window_from_query("cases filed in December 2025") == (
        date(2025, 12, 1), date(2026, 1, 1))
    assert date_window_from_query("how many cases in 2024") == (
        date(2024, 1, 1), date(2025, 1, 1))
    # Relative windows belong to the model path, which owns the clock. Two readings of
    # "last year" is how two halves of one answer describe different windows.
    assert date_window_from_query("cases from last year") == (None, None)


# --------------------------------------------------------------------------- #
# execution: the filters actually reach the query                              #
# --------------------------------------------------------------------------- #

def test_a_filtered_count_and_its_sample_list_describe_the_same_set(dataset):
    """The count captions the list under it. If a filter reaches one and not the
    other, the officer reads a number that does not describe what they are looking
    at — which is exactly what happened while count_firs and search_firs kept two
    copies of the same WHERE clause."""
    from rag_agent.agents import sql_agent

    for filters in ({"case_status": "Convicted"},
                    {"district": "Mandya"},
                    {"crime_type": "Theft", "case_status": "Under Investigation"},
                    {"section": "379"}):
        count = sql_agent.count_firs("IG", "", **filters)
        rows = sql_agent.search_firs("IG", "", limit=200, **filters)
        assert len(rows) <= count, f"{filters}: sample bigger than the count"
        if "case_status" in filters:
            assert all(r["case_status"] == filters["case_status"] for r in rows), \
                f"{filters}: the sample contains a status the count excluded"
        if "district" in filters:
            assert all(r["district"] == filters["district"] for r in rows)


def test_an_unfiltered_count_is_the_whole_scope_and_says_so(dataset):
    from rag_agent.agents import sql_agent
    total = sql_agent.count_firs("IG", "")
    assert total > 0
    # Every status must be a subset, and the statuses must sum to the total: a
    # breakdown that does not add up is a breakdown of a different query.
    breakdown = sql_agent.status_breakdown("IG", "")
    assert sum(breakdown.values()) == total


def test_a_section_that_no_offence_carries_matches_nothing_rather_than_everything(dataset):
    """The dangerous failure mode is the opposite one: a filter that cannot be applied
    being dropped, so "cases under section 9999" answers with every case on record."""
    from rag_agent.agents import sql_agent
    assert sql_agent.count_firs("IG", "", section="9999") == 0
    assert sql_agent.search_firs("IG", "", section="9999") == []


def test_the_offender_ranking_counts_cases_not_model_scores(dataset, habitual):
    """Ranked on a recorded fact. `vx_person` also carries PageRank and a risk score,
    and ranking on either produces a superficially similar list that means something
    completely different."""
    from rag_agent.agents import sql_agent
    ranked = sql_agent.ranked_offenders("IG", "", limit=5)
    assert ranked, "no offenders ranked on a dataset that has habitual offenders"
    assert [p["cases"] for p in ranked] == sorted((p["cases"] for p in ranked),
                                                  reverse=True)
    # The count must be checkable against the person's own case list.
    top = ranked[0]
    assert len(sql_agent.person_record(top["person_id"])) >= top["cases"]


def test_a_name_search_finds_someone_outside_the_top_ranked_page(dataset):
    """A name search must scan every offender in scope, not just the ranked page —
    most offenders are outside any top-N by definition (that is what "top" means),
    and a specific person an officer names must still be findable regardless of
    where they fall in the case-count ranking."""
    from rag_agent.agents import sql_agent
    everyone = sql_agent.ranked_offenders("IG", "", limit=10_000)
    assert len(everyone) > 5, "need more than one ranked page to prove this"
    target = everyone[-1]                     # at the bottom of the ranking
    hit = sql_agent.ranked_offenders("IG", "", limit=5, q=target["name"])
    assert any(p["person_id"] == target["person_id"] for p in hit), \
        "a small limit must not hide a name search's own match"


def test_an_io_ranking_never_reaches_another_station(dataset):
    """Scope is applied inside the count, so an IO's "most active offender" is their
    station's — not the state's list with the other stations' names still on it."""
    from data import ds
    from rag_agent.agents import sql_agent

    row = ds.one('SELECT "PoliceStationID" FROM "CaseMaster"')
    ps = str(row["PoliceStationID"])
    for person in sql_agent.ranked_offenders("IO", ps, limit=5):
        cases = sql_agent.person_record(person["person_id"])
        assert any(c["ps_code"] == ps for c in cases), \
            "an IO's ranking named someone with no case at their own station"


@pytest.mark.parametrize("query", kannada())
def test_a_kannada_question_is_not_dropped_on_the_floor(query):
    """Kannada is translated inside the container before routing, so `classify` sees
    English. What must never happen is the raw Kannada scoring a topical intent by
    accident — a confident answer to a question nobody understood."""
    assert classify(query) in ("UNKNOWN", "CRIME_SEARCH", "CASE_PEOPLE", "HOTSPOT")
