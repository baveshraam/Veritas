"""Cross-entity timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 3).

Same discipline as test_board_policy.py: real ZCQL strings against the session
`dataset` fixture, not mocks, and the station-scope/case-isolation rules are
exercised directly rather than assumed to hold because a neighbouring module
already tests them.
"""
import pytest

from rag_agent import timeline
from rag_agent.orchestrator import _connection_targets, _timeline_subject
from rag_agent.state import InvestigationState


def _case_with_accused(dataset):
    """A CaseMasterID that has at least one resolved accused person."""
    from data import ds
    row = ds.one(
        'SELECT "Accused"."CaseMasterID" AS c FROM "Accused" '
        'JOIN "vx_accused_identity" '
        '  ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID"')
    assert row, "no case in the test dataset has a resolved accused"
    return str(row["c"])


def _two_cases_different_stations(dataset):
    from data import ds
    rows = ds.query('SELECT "CaseMasterID", "PoliceStationID" FROM "CaseMaster"')
    groups: dict[int, list[int]] = {}
    for r in rows:
        groups.setdefault(r["PoliceStationID"], []).append(r["CaseMasterID"])
    stations = list(groups)
    if len(stations) < 2:
        pytest.skip("dataset has only one station")
    return groups[stations[0]][0], stations[0], groups[stations[1]][0]


def _co_accused_pair(dataset):
    """Two resolved PersonUIDs who share at least one case."""
    from data import ds
    rows = ds.query(
        'SELECT "vx_accused_identity"."PersonUID", "Accused"."CaseMasterID" '
        'FROM "vx_accused_identity" '
        'JOIN "Accused" '
        '  ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID"')
    by_case: dict[int, set[int]] = {}
    for r in rows:
        by_case.setdefault(r["CaseMasterID"], set()).add(r["PersonUID"])
    for people in by_case.values():
        if len(people) >= 2:
            a, b = list(people)[:2]
            return a, b
    pytest.skip("no two-accused case in the test dataset")


# --- case_timeline -------------------------------------------------------------

def test_case_timeline_is_chronologically_ordered(dataset):
    fir_id = _case_with_accused(dataset)
    result = timeline.case_timeline(fir_id, "IG", "")
    dates = [e["date"] for e in result["events"]]
    assert dates == sorted(dates)


def test_case_timeline_events_are_traceable_to_a_source(dataset):
    """Every event must remain traceable — a ref pointing back to the authoritative
    record, never a bare, unattributed sentence."""
    fir_id = _case_with_accused(dataset)
    result = timeline.case_timeline(fir_id, "IG", "")
    assert result["events"], "expected at least the case's own registration event"
    for e in result["events"]:
        assert e["ref_type"] is not None
        assert e["ref_id"] is not None
        assert e["kind"] in ("authoritative", "derived")


def test_case_timeline_includes_the_accused_as_entities(dataset):
    fir_id = _case_with_accused(dataset)
    result = timeline.case_timeline(fir_id, "IG", "")
    kinds = {e["entity_type"] for e in result["entities"]}
    assert "case" in kinds
    assert "person" in kinds


def test_case_timeline_enforces_station_scope(dataset):
    own, own_ps, other = _two_cases_different_stations(dataset)
    timeline.case_timeline(str(own), "IO", str(own_ps))       # own station: fine
    with pytest.raises(timeline.NotPermitted):
        timeline.case_timeline(str(other), "IO", str(own_ps))


def test_case_timeline_on_a_missing_case_raises_key_error(dataset):
    with pytest.raises(KeyError):
        timeline.case_timeline("999999999", "IG", "")


def test_related_case_events_are_labelled_derived_with_a_match_confidence(dataset):
    """A person's OTHER case is linked only by Fellegi-Sunter's inferred identity
    match, not a directly stated ER fact — must never be presented as though it were
    one (docs/INDUSTRY_GAP_ANALYSIS.md's own "clearly label it as derived" rule)."""
    from data import ds
    row = ds.one('SELECT "PersonUID" FROM "vx_person" WHERE "IsHabitualOffender" = 1')
    if not row:
        pytest.skip("no habitual offender in the test dataset")
    from data import queries
    from rag_agent.agents.sql_agent import accused_on_case
    cases = queries.cases_for_person(row["PersonUID"])
    if len(cases) < 2:
        pytest.skip("habitual offender has fewer than two cases")
    fir_id = str(cases[0]["CaseMasterID"])
    accused = accused_on_case(fir_id)
    person = next((a for a in accused if a["PersonUID"] == row["PersonUID"]), None)
    if not person:
        pytest.skip("habitual offender not accused on their own first case row")
    events = timeline._related_case_events(person, fir_id, "IG", "")
    assert events, "expected at least one related-case event"
    for e in events:
        assert e["kind"] == "derived"
        assert "identity" in e["description"].lower()


# --- person_timeline -------------------------------------------------------------

def test_person_timeline_spans_every_one_of_their_cases(dataset):
    from data import ds, queries
    row = ds.one('SELECT "PersonUID" FROM "vx_person" WHERE "IsHabitualOffender" = 1')
    if not row:
        pytest.skip("no habitual offender in the test dataset")
    n_cases = len(queries.cases_for_person(row["PersonUID"]))
    result = timeline.person_timeline(str(row["PersonUID"]), "IG", "")
    case_entities = [e for e in result["entities"] if e["entity_type"] == "case"]
    assert len(case_entities) == n_cases


def test_person_timeline_on_a_missing_person_raises_key_error(dataset):
    with pytest.raises(KeyError):
        timeline.person_timeline("999999999", "IG", "")


def test_person_timeline_is_chronologically_ordered(dataset):
    from data import ds
    row = ds.one('SELECT "PersonUID" FROM "vx_person" WHERE "IsHabitualOffender" = 1')
    if not row:
        pytest.skip("no habitual offender in the test dataset")
    result = timeline.person_timeline(str(row["PersonUID"]), "IG", "")
    dates = [e["date"] for e in result["events"]]
    assert dates == sorted(dates)


# --- connection_between -----------------------------------------------------

def test_connection_between_co_accused_people_is_direct_and_authoritative(dataset):
    a, b = _co_accused_pair(dataset)
    conn = timeline.connection_between(str(a), "Person A", str(b), "Person B")
    assert conn["has_direct_connection"]
    assert conn["direct"][0]["kind"] == "authoritative"


def test_connection_between_unrelated_people_reports_no_connection_not_a_guess(dataset):
    """The spec's own rule: two events near each other in time must never be
    reported as a connection. Two people with no graph/case/financial link at all
    must get an honest 'no direct connection', not a fabricated one."""
    from data import ds
    people = ds.query('SELECT "PersonUID" FROM "vx_person" ORDER BY "PersonUID" LIMIT 200')
    ids = [p["PersonUID"] for p in people]
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            conn = timeline.connection_between(str(a), "A", str(b), "B")
            if not conn["has_direct_connection"]:
                assert conn["direct"] == []
                return
    pytest.skip("every pair in the sample happened to be directly connected")


# --- orchestrator wiring -----------------------------------------------------

def _state(**over) -> InvestigationState:
    base = dict(session_id="s1", officer_id="1", officer_role="IG")
    base.update(over)
    return InvestigationState(**base)


def test_timeline_subject_prefers_a_resolved_person_over_an_open_case():
    from data import SessionFocus
    st = _state(active_entities=SessionFocus(active_person="42", active_fir="7"))
    assert _timeline_subject(st) == ("person", "42")


def test_timeline_subject_falls_back_to_the_open_case():
    from data import SessionFocus
    st = _state(active_entities=SessionFocus(active_fir="7"))
    assert _timeline_subject(st) == ("case", "7")


def test_timeline_subject_is_none_with_neither():
    st = _state()
    assert _timeline_subject(st) == (None, None)


def test_conversation_turn_produces_a_grounded_timeline_answer(dataset):
    """End-to-end: node_retrieve -> node_evaluate -> node_synthesize for a real
    'show me the timeline for this case' turn against a real case."""
    from data import SessionFocus
    import rag_agent.orchestrator as orch

    fir_id = _case_with_accused(dataset)
    st = _state(original_query="Show me the timeline for this case.", intent="TIMELINE",
               active_entities=SessionFocus(active_fir=fir_id))
    orch.node_retrieve(st)
    assert not st.refusal_reason, "a real case must not refuse"
    orch.node_evaluate(st)
    assert not st.requires_escalation
    orch.node_synthesize(st)
    assert st.answer_is_refusal is False
    assert st.final_answer
    assert st.citations
    assert st.visualization.kind == "timeline"
    assert st.visualization.data["events"], "the visualization must carry the events, not just a summary"


def test_timeline_with_no_subject_refuses_honestly(dataset):
    import rag_agent.orchestrator as orch

    st = _state(original_query="Show me the timeline for this case.", intent="TIMELINE")
    orch.node_retrieve(st)
    orch.node_evaluate(st)
    orch.node_synthesize(st)
    assert st.answer_is_refusal is True
    assert "case or a person" in st.final_answer


def test_timeline_on_an_out_of_scope_case_refuses_not_leaks(dataset, monkeypatch):
    from data import SessionFocus
    import rag_agent.orchestrator as orch

    own, own_ps, other = _two_cases_different_stations(dataset)
    monkeypatch.setattr(orch, "_officer_ps", lambda officer_id: str(own_ps))
    st = _state(officer_role="IO", original_query="Show me the timeline for this case.",
               intent="TIMELINE", active_entities=SessionFocus(active_fir=str(other)))
    orch.node_retrieve(st)
    assert st.refusal_reason == "board_forbidden"


def test_timeline_connection_with_fewer_than_two_people_refuses(dataset):
    import rag_agent.orchestrator as orch

    st = _state(original_query="Why are these events connected?", intent="TIMELINE_CONNECTION")
    orch.node_retrieve(st)
    orch.node_evaluate(st)
    orch.node_synthesize(st)
    assert st.answer_is_refusal is True
    assert "two people" in st.final_answer


def test_timeline_event_can_be_pinned_to_the_board_like_any_evidence(dataset, monkeypatch):
    """'Add this event to the investigation board' must resolve exactly the way
    'pin this' already does for any other evidence card — the timeline's events are
    ordinary EvidenceItems, so no new pinning code path was needed. Confirms that
    claim by driving it end to end rather than merely asserting the source_type."""
    from data import SessionFocus
    import rag_agent.orchestrator as orch

    fir_id = _case_with_accused(dataset)
    prior_state = _state(original_query="Show me the timeline for this case.",
                         intent="TIMELINE", active_entities=SessionFocus(active_fir=fir_id))
    orch.node_retrieve(prior_state)
    orch.node_evaluate(prior_state)
    orch.node_synthesize(prior_state)
    assert prior_state.evidence_items, "need a real timeline event to pin"
    target = prior_state.evidence_items[0]

    class _Prior:
        evidence_items = [e.model_dump() for e in prior_state.evidence_items]
        citations = [c.model_dump() for c in prior_state.citations]

    monkeypatch.setattr(orch, "_last_turn", lambda session_id: _Prior())

    pin_state = _state(original_query="Add this event to the investigation board.",
                       intent="BOARD_PIN_EVIDENCE",
                       active_entities=SessionFocus(active_fir=fir_id),
                       active_evidence_id=target.evidence_id)
    orch.node_retrieve(pin_state)
    assert pin_state.board_result and pin_state.board_result["ok"], pin_state.board_result
    item = pin_state.board_result["item"]
    assert item["ref_id"] == target.source_id
    assert item["content"] == target.content


def test_pin_with_a_target_absent_from_the_prior_turn_reconstructs_it_not_grabs_top(
        dataset, monkeypatch):
    """Found live: a genuine `active_evidence_id` set to a Timeline-tab event (never
    part of any chat turn, since that tab fetches over REST) fell straight through
    to 'grab the previous turn's top evidence item' instead of the reconstruction
    fallback — silently pinning an unrelated FIR record with no sign a substitution
    had happened. A target that fails to match anywhere must never fall back to a
    different item than the one asked for."""
    from data import SessionFocus
    import rag_agent.orchestrator as orch

    fir_id = _case_with_accused(dataset)
    tl = timeline.case_timeline(fir_id, "IG", "")
    assert tl["events"], "need at least one real timeline event"
    target_event = tl["events"][0]
    target_id = (f"timeline:{target_event['event_type']}:"
                f"{target_event['entity_id']}:{target_event['date']}")

    class _Prior:
        # A real prior turn exists, but its evidence pool is a DIFFERENT FIR-record
        # item — not the timeline event being pinned.
        evidence_items = [{"evidence_id": "fir:999", "source_type": "FIR_RECORD",
                           "source_id": "999", "content": "an unrelated FIR",
                           "confidence": 0.9, "authoritative": False}]
        citations = [{"evidence_id": "fir:999", "index": 1, "label": "an unrelated FIR"}]

    monkeypatch.setattr(orch, "_last_turn", lambda session_id: _Prior())

    st = _state(original_query="Add this event to the investigation board.",
               intent="BOARD_PIN_EVIDENCE", active_entities=SessionFocus(active_fir=fir_id),
               active_evidence_id=target_id)
    orch.node_retrieve(st)
    assert st.board_result and st.board_result["ok"], st.board_result
    item = st.board_result["item"]
    assert item["content"] != "an unrelated FIR"
    assert target_event["description"] in item["content"]


def test_timeline_connection_after_case_people_resolves_both_without_asking(
        dataset, monkeypatch):
    """Found live: 'Show me events involving both of them' right after a 2-accused
    CASE_PEOPLE turn fell to the generic pronoun-ambiguity refusal (RAG-34's own
    mechanism) before _handle_timeline_connection ever ran — even though 2 recent
    candidates is exactly what TIMELINE_CONNECTION's own pronoun is asking for, not
    the singular ambiguity that refusal exists to catch."""
    import rag_agent.orchestrator as orch

    monkeypatch.setattr(orch, "_recent_person_candidates",
                        lambda session_id: ["Person A", "Person B"])
    monkeypatch.setattr(
        "rag_agent.agents.sql_agent.person_by_name",
        lambda name: [{"name_en": name, "person_id": "1" if name == "Person A" else "2"}])
    monkeypatch.setattr(orch.timeline_agent, "connection_between",
                        lambda *a, **k: {"person_a": {}, "person_b": {}, "direct": [],
                                         "has_direct_connection": False})
    monkeypatch.setattr(orch.timeline_agent, "person_timeline",
                        lambda *a, **k: {"events": []})

    st = _state(original_query="Show me events involving both of them.",
               intent="TIMELINE_CONNECTION")
    orch.node_orchestrate(st)
    assert st.refusal_reason == "", "must not pre-refuse — TIMELINE_CONNECTION resolves this itself"
    orch.node_retrieve(st)
    assert st.refusal_reason != "ambiguous_person"
    assert st.evidence_items, "expected the no-direct-connection statement as evidence"


def test_connection_targets_reads_named_people_from_the_query(dataset, monkeypatch):
    from data import ds
    row = ds.one('SELECT "PersonUID", "CanonicalName" FROM "vx_person" '
                 'WHERE "IsHabitualOffender" = 1')
    if not row:
        pytest.skip("no habitual offender in the test dataset")

    class _E:
        def __init__(self, text, label):
            self.text, self.label = text, label

    monkeypatch.setattr("data.nlp.ner_extract",
                        lambda q, lang: [_E(row["CanonicalName"], "PERSON")])
    st = _state(original_query=f"Is {row['CanonicalName']} connected to anyone?")
    targets = _connection_targets(st)
    assert targets, "expected the named person to resolve"
    assert targets[0][1] == str(row["PersonUID"])
