"""The provenance chain: "why is this here?", answered about the CLAIM.

The property under test throughout is the one the feature exists for — an explanation
must name the actual records and the actual relationship that produced a result, and
must say so plainly when it cannot, rather than producing a plausible-sounding chain.
Every assertion below is about what an investigator reads, not about which component
ran.
"""
import re

import pytest
from rag_agent import provenance
from rag_agent.state import InvestigationState


# --- the flagship: why are these two people connected? ------------------------

def test_associate_explanation_names_the_shared_case_not_the_hop_count(dataset, habitual):
    """A co-offending edge is the most consequential DERIVED claim this platform
    makes — the organizers' ER has no cross-case person at all — so "why is this
    person connected" has to answer with the FIRs both people are named on."""
    from rag_agent.agents import graph_agent

    pid = str(habitual["PersonUID"])
    network = graph_agent.person_network(pid, "IG")
    direct = next((r for r in network if r["hops"] == 1), None)
    assert direct, "the generator produced no direct co-accused — the crew model is broken"

    d = provenance.explain({"evidence_id": f"assoc:{direct['person_id']}",
                            "source_type": "GRAPH_RELATIONSHIP"},
                           role="IG", ps="", operation="PERSON_NETWORK", subject_id=pid)

    assert d.basis == "derived"
    assert not d.incomplete
    # A real record, named the way the paper file names it.
    assert d.records, "no source record was named for a direct co-accusation"
    assert all(r.label.startswith("FIR ") for r in d.records)
    # The derivation says who is named on what, not "1 hop away".
    joined = " ".join(d.steps)
    assert "named as accused on" in joined
    assert habitual["CanonicalName"] in joined
    assert "direct co-accused" in d.qualifies
    # No "(s)" markers reach the panel. A chain is reached two ways — typed into the
    # copilot and clicked in the console — and only the first went through synthesis,
    # so the console read "1 step(s) of co-accusation away". Found by driving it.
    assert "(s)" not in d.qualifies and "1 step of" in d.qualifies
    # And it states what a co-accusation is NOT.
    assert d.caveat and "guilty" in d.caveat


def test_associate_explanation_says_so_rather_than_inventing_a_chain(dataset):
    """No subject in view means the connecting cases genuinely cannot be named. The
    honest answer is to say that — a fabricated chain is the exact failure this
    platform exists to prevent."""
    d = provenance.explain({"evidence_id": "assoc:999999"},
                           role="IG", ps="", subject_id=None)
    assert d.incomplete
    assert not d.records
    assert "cannot be named" in " ".join(d.steps)


def test_a_multi_hop_associate_is_not_described_as_a_direct_co_accused(dataset, habitual):
    from rag_agent.agents import graph_agent

    pid = str(habitual["PersonUID"])
    far = next((r for r in graph_agent.person_network(pid, "IG") if r["hops"] >= 2), None)
    if far is None:
        pytest.skip("this dataset's network has no 2+ hop associate for this subject")

    d = provenance.explain({"evidence_id": f"assoc:{far['person_id']}"},
                           role="IG", ps="", subject_id=pid)
    assert "direct co-accused" not in d.qualifies
    assert "not named alongside your subject" in d.qualifies
    # One derivation step per hop, plus the identity-resolution preamble.
    assert len(d.steps) >= far["hops"] + 1
    # Every record says WHICH PAIR it links. Printed flat, a multi-hop pool reads as
    # "these nine FIRs connect you to this person" — an over-claim, since the person
    # at the far end appears on only the last hop's cases.
    assert d.records
    assert all(r.detail.startswith("links ") for r in d.records)


# --- why THIS case, of ten thousand -------------------------------------------

def test_the_same_fir_is_explained_differently_by_how_it_was_retrieved(dataset):
    """The record does not change; the reason it is on screen does. A FIR looked up
    by number and a FIR ranked as similar to another case are two different claims
    about why the officer is looking at it."""
    from data import ds
    row = ds.one('SELECT "CaseMasterID" FROM "CaseMaster"')
    item = {"evidence_id": f"fir:{row['CaseMasterID']}", "source_type": "FIR_RECORD",
            "confidence": 0.97}

    looked_up = provenance.explain(item, role="IG", ps="", operation="FIR_LOOKUP")
    ranked = provenance.explain({**item, "confidence_kind": "similarity",
                                 "confidence": 0.66},
                                role="IG", ps="", operation="SIMILAR_CASES")

    assert "You gave this FIR number" in " ".join(looked_up.steps)
    assert "nothing to rank" in looked_up.qualifies
    assert "structured overlap" in " ".join(ranked.steps)
    assert "Text match 66%" in ranked.qualifies
    assert ranked.caveat and "not evidence that the cases are connected" in ranked.caveat


def test_a_record_explanation_names_the_record_it_read(dataset):
    from data import ds
    row = ds.one('SELECT "CaseMasterID" FROM "CaseMaster"')
    d = provenance.explain({"evidence_id": f"fir:{row['CaseMasterID']}",
                            "source_type": "FIR_RECORD"},
                           role="IG", ps="", operation="FIR_LOOKUP")
    assert d.basis == "record"
    assert len(d.records) == 1
    assert d.records[0].label.startswith("FIR ")


# --- model output must never be able to look like a record --------------------

def test_a_forecast_is_a_prediction_and_a_hotspot_is_a_model():
    """Four kinds, and the two that are easiest to mistake for facts are separated:
    a hotspot describes the recorded past, a forecast describes nothing that has
    happened at all."""
    hot = provenance.explain({"evidence_id": "hotspot:KA05:0",
                              "source_type": "GEOSPATIAL_ANALYSIS"}, role="IG", ps="")
    fc = provenance.explain({"evidence_id": "forecast:KA05",
                             "source_type": "ML_PREDICTION"}, role="IG", ps="")

    assert hot.basis == "model"
    assert fc.basis == "prediction"
    assert "not a prediction" in hot.caveat
    assert "Nothing here has happened" in fc.caveat


def test_a_risk_score_states_that_no_protected_attribute_is_a_feature():
    d = provenance.explain({"evidence_id": "risk:1", "source_type": "ML_PREDICTION"},
                           role="IG", ps="")
    assert d.basis == "model"
    assert "No caste, religion or other protected attribute is a feature" in " ".join(d.steps)
    assert "never evidence" in d.caveat


# --- a timeline mixes two populations, and must say which is which ------------

def test_a_derived_timeline_event_is_explained_as_an_identity_inference():
    stated = provenance.explain(
        {"evidence_id": "timeline:fir_filed:9:2026-01-01", "authoritative": True,
         "source_type": "FIR_RECORD"}, role="IG", ps="")
    inferred = provenance.explain(
        {"evidence_id": "timeline:related_case:9:2026-01-01", "authoritative": False,
         "source_type": "CRIMINAL_RECORD"}, role="IG", ps="")

    assert stated.basis == "record"
    assert inferred.basis == "derived"
    assert "identity resolution matched" in " ".join(inferred.steps)
    assert inferred.caveat and "belongs to someone else" in inferred.caveat
    assert stated.caveat is None


def test_a_recorded_transfer_is_not_downgraded_to_derived_when_the_flag_is_missing():
    """A large turn is stored as evidence SKELETONS and an old one carried no items
    at all, so `authoritative` can genuinely be absent. Reading absent as False made a
    recorded transfer explain itself as a probabilistic identity inference — found
    live on a 12-event timeline. The event TYPE is in the evidence_id and cannot be
    lost, so it decides when the flag is gone."""
    transfer = provenance.explain({"evidence_id": "timeline:money_in:1755:2023-08-23"},
                                  role="IG", ps="")
    related = provenance.explain({"evidence_id": "timeline:related_case:803:2023-08-24"},
                                 role="IG", ps="")
    assert transfer.basis == "record"
    assert "incoming transfer" in transfer.claim
    assert related.basis == "derived"


# --- never fabricate, never raise ---------------------------------------------

def test_every_evidence_id_prefix_the_system_produces_has_an_explanation():
    """The fallback ("I cannot reconstruct why this is here") is honest, but it is a
    floor, not a design. An officer pointing at the most common thing on screen — a
    semantic search hit — and being told the derivation is unavailable would make the
    whole feature read as decorative.

    Read out of the source rather than listed by hand: a new producer cannot add a
    prefix without this failing."""
    import pathlib
    import re as _re

    import rag_agent
    root = pathlib.Path(rag_agent.__file__).parent
    produced = set()
    for path in root.rglob("*.py"):
        for m in _re.finditer(r'evidence_id=f?"([a-z_]+):', path.read_text(encoding="utf-8")):
            produced.add(m.group(1))

    assert produced, "no evidence_id conventions found — the scan is broken, not the code"
    missing = sorted(produced - set(provenance._PREFIX))
    assert not missing, f"no provenance handler for: {missing}"


def test_a_semantic_hit_is_never_described_as_evidence_of_a_connection():
    """The most over-readable result on screen. It is here because it READS like the
    question, which is a reason to look and not a reason to believe."""
    d = provenance.explain(
        {"evidence_id": "vec:fir_narrative:1043", "source_type": "FIR_RECORD",
         "content": "FIR 1043, theft.", "confidence": 0.66,
         "confidence_kind": "similarity"}, role="IG", ps="")
    assert not d.incomplete
    assert "Text match 66%" in d.qualifies
    assert d.caveat and "not evidence that the cases are connected" in d.caveat
    assert "only its SELECTION is a similarity judgement" in " ".join(d.steps)


def test_an_unrecognised_evidence_id_says_so_instead_of_guessing():
    d = provenance.explain({"evidence_id": "something_new:42", "source_type": "FIR_RECORD",
                            "content": "a claim", "source_query": "SELECT 1"},
                           role="IG", ps="")
    assert d.incomplete
    assert "could not be reconstructed" in " ".join(d.steps)
    assert d.claim == "a claim"


def test_explain_never_raises_on_a_malformed_item():
    """A 'why?' question failing outright is worse than an incomplete answer to it."""
    for bad in ({}, {"evidence_id": ""}, {"evidence_id": "fir:not-an-id"},
                {"evidence_id": "assoc:"}, {"evidence_id": "timeline:"}):
        d = provenance.explain(bad, role="IG", ps="")
        assert isinstance(d, provenance.Derivation)


def test_as_text_renders_the_five_sections_in_order():
    d = provenance.explain({"evidence_id": "hotspot:KA05:0",
                            "source_type": "GEOSPATIAL_ANALYSIS"}, role="IG", ps="")
    text = provenance.as_text(d)
    order = [text.index(s) for s in
             ("This is MODEL", "How it was arrived at", "Why it qualifies",
              "What it does not mean")]
    assert order == sorted(order)


# --- §4: never claim completeness for a bounded sample ------------------------

def test_a_sample_is_named_as_a_sample_with_the_real_total():
    line = provenance.describe_result_set(
        {"operation": "CRIME_SEARCH", "total_matched": 73, "shown": 5, "is_sample": True})
    assert "SAMPLE" in line and "5 of 73" in line and "only these?" in line


def test_an_exhaustive_network_is_not_described_as_a_sample():
    line = provenance.describe_result_set(
        {"operation": "PERSON_NETWORK", "total_matched": 12, "shown": 12, "is_sample": False})
    assert "EXHAUSTIVE" in line and "SAMPLE" not in line


def test_a_result_set_with_no_recorded_operation_makes_no_claim():
    assert provenance.describe_result_set({}) is None
    assert provenance.describe_result_set({"operation": "CAPABILITY"}) is None


# --- pointing at ONE item -----------------------------------------------------

def _turn(evidence, **over):
    from datetime import datetime, timezone

    from data import ConversationTurn
    base = dict(turn_index=0, query="Who are her associates?", language="en",
                final_answer="...",
                citations=[{"index": i + 1, "evidence_id": e["evidence_id"],
                            "label": e.get("content", "")} for i, e in enumerate(evidence)],
                evidence_items=evidence, visualization={"kind": "none", "data": {}},
                agent_trace=[], result_context={"operation": "PERSON_NETWORK"},
                created_at=datetime.now(timezone.utc))
    base.update(over)
    return ConversationTurn(**base)


_POOL = [
    {"evidence_id": "assoc:11", "source_type": "GRAPH_RELATIONSHIP", "source_id": "11",
     "source_query": "q", "content": "A is an associate.", "confidence": 0.8,
     "authoritative": False, "confidence_kind": "support", "timestamp": None},
    {"evidence_id": "fir:22", "source_type": "FIR_RECORD", "source_id": "22",
     "source_query": "q", "content": "FIR 22.", "confidence": 0.9,
     "authoritative": False, "confidence_kind": "support", "timestamp": None},
    {"evidence_id": "timeline:arrest:33:2026-01-01", "source_type": "FIR_RECORD",
     "source_id": "33", "source_query": "q", "content": "Arrest.", "confidence": 0.9,
     "authoritative": True, "confidence_kind": "support", "timestamp": None},
]


def _state(query, **over):
    s = InvestigationState(session_id="s", officer_id="1", officer_role="IG",
                           original_query=query)
    for k, v in over.items():
        setattr(s, k, v)
    return s


def test_a_console_selection_beats_every_other_way_of_pointing():
    """Clicking a graph node and typing "why is this case here" must explain the NODE.
    A click is the most specific thing the officer can do; nothing overrides it."""
    import rag_agent.orchestrator as orch
    for e in _POOL:
        e.setdefault("timestamp", None)
    turn = _turn([dict(e) for e in _POOL])
    hit = orch._explain_target(turn, _state("why is this case here",
                                            active_evidence_id="assoc:11"))
    assert hit["evidence_id"] == "assoc:11"


def test_an_ordinal_selects_by_position_in_the_previous_answer():
    import rag_agent.orchestrator as orch
    turn = _turn([dict(e) for e in _POOL])
    hit = orch._explain_target(turn, _state("What supports the third event?"))
    assert hit["evidence_id"].startswith("timeline:")


def test_the_noun_says_which_kind_of_item_is_being_asked_about():
    """'Why is this PERSON connected' and 'why is this CASE here' are questions about
    different rows of the same answer, and the noun is the only thing that says which."""
    import rag_agent.orchestrator as orch
    turn = _turn([dict(e) for e in _POOL])
    assert orch._explain_target(turn, _state("why is this person connected")
                                )["evidence_id"] == "assoc:11"
    assert orch._explain_target(turn, _state("why is this case here")
                                )["evidence_id"] == "fir:22"
    assert orch._explain_target(turn, _state("why is this hotspot here")) is None


def test_pointing_at_nothing_explains_the_whole_answer():
    import rag_agent.orchestrator as orch
    turn = _turn([dict(e) for e in _POOL])
    assert orch._explain_target(turn, _state("How are you deriving all these?")) is None


def test_a_truncated_turn_can_still_be_explained_from_its_citations():
    """A turn too large for the Data Store's text column sheds evidence_items and keeps
    citations. The evidence_id is on both, and it is all the dispatch needs."""
    import rag_agent.orchestrator as orch
    turn = _turn([dict(e) for e in _POOL], evidence_items=[])
    hit = orch._explain_target(turn, _state("why is this person connected"))
    assert hit and hit["evidence_id"] == "assoc:11"


# --- §5: the structured field beats the generated sentence --------------------

def test_prose_contradicting_the_recorded_status_is_corrected(dataset):
    import rag_agent.orchestrator as orch
    state = _state("what is the status", sql_query_results=[
        {"fir_id": "9", "case_status": "Convicted", "district": "Mandya"}])
    out = orch._reconcile_with_records(
        "The investigation is being carried out by the station.", [], state)
    assert "Correction from the record" in out
    assert '"Convicted"' in out


def test_a_paraphrase_of_the_recorded_status_is_left_alone(dataset):
    import rag_agent.orchestrator as orch
    state = _state("status", sql_query_results=[
        {"fir_id": "9", "case_status": "Under Investigation", "district": "Mandya"}])
    out = orch._reconcile_with_records(
        "The investigation is ongoing at the station.", [], state)
    assert "Correction from the record" not in out


def test_a_mixed_status_result_set_raises_no_status_contradiction(dataset):
    """A person's history legitimately spans several statuses, so any status phrase in
    the prose is then about one of them. Flagging it would train the officer to ignore
    the warning."""
    import rag_agent.orchestrator as orch
    state = _state("her priors", sql_query_results=[
        {"fir_id": "9", "case_status": "Convicted", "district": "Mandya"},
        {"fir_id": "10", "case_status": "Under Investigation", "district": "Mandya"}])
    out = orch._reconcile_with_records("The investigation is ongoing.", [], state)
    assert "Correction from the record" not in out


def test_a_citation_grouped_under_the_wrong_status_is_corrected(dataset):
    """Found live: a priors answer read 'Other cases include Theft [3, 7, 9, 11] ...
    which are Chargesheeted or Under Investigation' while citation [7] was recorded
    Acquitted — the whole-answer status check (above) never runs here at all, because
    the history spans several statuses. This is the narrower, citation-scoped check
    that catches the synthesized narrative's own grouping error instead."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import EvidenceItem

    def ev(i: int, status: str) -> EvidenceItem:
        return EvidenceItem(evidence_id=f"fir:{i}", source_type="FIR_RECORD",
                            source_id=str(i), content=f"FIR {i} — Theft, status {status}.",
                            confidence=0.9)

    evidence = [ev(1, "Chargesheeted"), ev(2, "Acquitted"), ev(3, "Under Investigation")]
    state = _state("her priors", sql_query_results=[
        {"fir_id": "1", "case_status": "Chargesheeted"},
        {"fir_id": "2", "case_status": "Acquitted"},
        {"fir_id": "3", "case_status": "Under Investigation"}])
    out = orch._reconcile_with_records(
        "Other cases include Theft [1, 2, 3] which are Chargesheeted or "
        "Under Investigation.", evidence, state)
    assert "Correction from the record" in out
    assert "citation [2]" in out
    assert "citation [1]" not in out and "citation [3]" not in out


def test_a_capped_exhaustive_network_stops_claiming_the_full_count():
    """Found live: "Who are the associates of Usha Naika?" answered with a 40-person
    network, but node_synthesize's own [:12] citation cap trims the evidence down to
    12 before the answer is built — and PERSON_NETWORK sets is_sample=False /
    shown=40 at production time, before it can know a cap is coming. Left
    uncorrected, the answer says 'Result set: EXHAUSTIVE — 40 record(s)' over 12
    citations, and the next turn's "only these?" says 'all 40 already shown' when
    only 12 were. _reconcile_shown_with_cap is the one place downstream of the cap
    that can still tell the two numbers apart."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import EvidenceItem

    all_ids = [str(i) for i in range(40)]
    state = _state("who are her associates", result_context={
        "operation": "PERSON_NETWORK", "total_matched": 40, "shown": 40,
        "is_sample": False, "shown_ids": all_ids})
    capped_evidence = [
        EvidenceItem(evidence_id=f"assoc:{i}", source_type="GRAPH_RELATIONSHIP",
                    source_id=i, content="associate", confidence=0.5)
        for i in all_ids[:12]]

    orch._reconcile_shown_with_cap(state, capped_evidence)

    assert state.result_context["is_sample"] is True
    assert state.result_context["shown"] == 12
    assert set(state.result_context["shown_ids"]) == set(all_ids[:12])


def test_an_uncapped_result_is_left_alone_by_the_cap_reconciler():
    """Nothing was actually trimmed here (12 shown, 12 survived) — the reconciler
    must not flip a genuinely exhaustive result to a false 'sample'."""
    import rag_agent.orchestrator as orch
    from rag_agent.state import EvidenceItem

    ids = [str(i) for i in range(12)]
    state = _state("who are his associates", result_context={
        "operation": "PERSON_NETWORK", "total_matched": 12, "shown": 12,
        "is_sample": False, "shown_ids": ids})
    evidence = [EvidenceItem(evidence_id=f"assoc:{i}", source_type="GRAPH_RELATIONSHIP",
                             source_id=i, content="associate", confidence=0.5)
               for i in ids]

    orch._reconcile_shown_with_cap(state, evidence)

    assert state.result_context["is_sample"] is False
    assert state.result_context["shown"] == 12


def test_a_district_no_cited_record_mentions_is_flagged(dataset):
    import rag_agent.orchestrator as orch
    state = _state("theft in Mandya", sql_query_results=[
        {"fir_id": "9", "case_status": "Convicted", "district": "Mandya"}])
    out = orch._reconcile_with_records(
        "Two of the cases were filed in Kolar.", [], state)
    assert "Not supported by the cited records" in out
    assert "Kolar" in out


def test_a_district_the_officer_asked_about_is_not_flagged(dataset):
    """The question named it, so it is not the model inventing a place."""
    import rag_agent.orchestrator as orch
    state = _state("how many theft cases in Kolar", sql_query_results=[])
    out = orch._reconcile_with_records("No theft cases are recorded in Kolar.", [], state)
    assert "Not supported" not in out


# --- routing: the questions of §1, asked the way they are asked ---------------

@pytest.mark.parametrize("query", [
    "Why is this person connected?",
    "Why is this case in the timeline?",
    "Why is that a hotspot?",
    "How are you deriving all these?",
    "How did you get this?",
    "How was this derived?",
    "Show me the chain.",
    "Why these?",
    "Why are you showing me these people?",
])
def test_claim_level_why_questions_explain_instead_of_researching(query):
    """Each of these used to score somewhere plausible and wrong — 'connected' on
    PERSON_NETWORK, 'hotspot' on HOTSPOT — running a FRESH search for the thing
    already on screen instead of explaining why it is on screen."""
    from rag_agent.intents import classify
    assert classify(query) == "EXPLAIN_REASONING"


def test_the_two_entity_timeline_question_still_wins_the_phrasings_it_owns():
    """'How are these connected' asks about the ENTITIES, not about the method. The
    widened explanation vocabulary overlaps it, and the narrower pattern keeps it."""
    from rag_agent.intents import classify
    assert classify("How are these connected?") == "TIMELINE_CONNECTION"
    assert classify("Why are these events connected?") == "TIMELINE_CONNECTION"


def test_where_are_the_related_cases_locates_the_previous_answer():
    """It used to score HOTSPOT on the bare word 'where' and run cluster detection
    over a defaulted district — a fresh search in reply to a backreference."""
    from rag_agent.intents import classify
    assert classify("Where are the related cases?") == "CASE_LOCATIONS"
    # ...and a genuine geographic search must stay one.
    assert classify("Where are the theft cases?") != "CASE_LOCATIONS"
