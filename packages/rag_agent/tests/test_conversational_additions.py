"""The six conversational additions — interrogation prep, the case-similarity
watch, case handoff, poking holes in a finding, the pre-filing check, and
cross-station linkage. Each is a real dialogue behaviour built entirely on data
already in the record layer (case history, arrests, chargesheets, resolved
identity, the co-offending graph) — no new table, no new model.

Two layers, matching this repo's own established split: `test_intents.py`-style
routing (does the phrasing reach the right operation, without colliding with an
existing one) lives in test_engine.py/test_officer_input_battery.py's own guard
tests; this file exercises the HANDLERS themselves against the real dataset, the
same way test_new_analytics_handlers.py does for the v21 additions — because a
classify()-only test cannot catch a bug inside the handler's own f-strings or SQL.
"""
from datetime import datetime, timezone

from data import ds
from rag_agent import intents, orchestrator, provenance
from rag_agent.agents import sql_agent
from rag_agent.state import InvestigationState


def _state(query: str) -> InvestigationState:
    return InvestigationState(session_id="t", officer_id="1", officer_role="IG",
                              original_query=query)


def _check_provenance(items):
    for e in items:
        d = provenance.explain(e, role="IG", ps="")
        assert not d.incomplete, f"{e.evidence_id}: provenance chain incomplete"


# --- routing -------------------------------------------------------------------

def test_new_intents_route_correctly_and_do_not_collide():
    cases = [
        ("What should I ask him before the interview?", "INTERROGATION_PREP"),
        ("Prepare me for questioning this suspect.", "INTERROGATION_PREP"),
        ("Match against my open cases.", "CASE_SIMILARITY_WATCH"),
        ("Check against cold cases.", "CASE_SIMILARITY_WATCH"),
        ("Catch me up on this case.", "CASE_HANDOFF"),
        ("Bring me up to speed.", "CASE_HANDOFF"),
        ("Would this case hold up?", "PREFILING_CHECK"),
        ("Is this case ready for chargesheet?", "PREFILING_CHECK"),
        ("Poke holes in this.", "CHALLENGE_FINDING"),
        ("What would the defence argue?", "CHALLENGE_FINDING"),
        ("Who else should know about this?", "CROSS_STATION_LINKAGE"),
        ("Is another station working on this?", "CROSS_STATION_LINKAGE"),
    ]
    for query, expected in cases:
        assert intents.classify(query) == expected, query


def test_challenge_finding_does_not_swallow_a_real_derivation_question():
    """A shape guard's whole risk is stealing a neighbour's phrasing. 'How did you
    decide this' must still explain the derivation, not go hunting for weaknesses."""
    assert intents.classify("How did you decide this?") == "EXPLAIN_REASONING"
    assert intents.classify("What is the basis for this?") == "EXPLAIN_REASONING"


# --- interrogation prep ----------------------------------------------------------

def test_interrogation_prep_produces_evidence_for_a_person_with_cases(dataset):
    row = sql_agent.ranked_offenders("IG", "", limit=1)
    assert row, "fixture must have at least one resolved offender"
    pid = row[0]["person_id"]
    state = _state("What should I ask him?")
    state.intent = "INTERROGATION_PREP"
    state.active_entities.active_person = pid

    out = orchestrator._run_specialists(state, widen=False)
    assert out, "no preparation points produced for a person with real case history"
    assert all(e.evidence_id.startswith(f"interview:{pid}:") for e in out)
    _check_provenance(out)


def test_interrogation_prep_states_the_absence_for_a_person_with_no_cases(dataset):
    row = ds.one('SELECT "PersonUID" FROM "vx_person" ORDER BY "PersonUID" DESC')
    pid = str(int(row["PersonUID"]) + 999999)     # guaranteed not to exist
    state = _state("What should I ask her?")
    state.intent = "INTERROGATION_PREP"
    state.active_entities.active_person = pid

    out = orchestrator._run_specialists(state, widen=False)
    assert out and "no prior record" in out[0].content.lower()


# --- case-similarity watch -------------------------------------------------------

def test_case_similarity_watch_runs_without_raising(indexed):
    fir_id = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 1')[0]["CaseMasterID"]
    state = _state("Does this match my backlog?")
    state.intent = "CASE_SIMILARITY_WATCH"
    state.active_entities.active_fir = str(fir_id)

    out = orchestrator._run_specialists(state, widen=False)
    assert out, "must produce either matches or an honest absence"
    assert all(e.evidence_id.startswith(f"watch:{fir_id}:") for e in out)
    _check_provenance(out)


# --- case handoff -----------------------------------------------------------------

def test_case_handoff_assembles_summary_and_board_state(dataset):
    fir_id = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 1')[0]["CaseMasterID"]
    state = _state("Catch me up on this case.")
    state.intent = "CASE_HANDOFF"
    state.active_entities.active_fir = str(fir_id)

    out = orchestrator._run_specialists(state, widen=False)
    assert any(e.evidence_id == f"handoff:{fir_id}:summary" for e in out)
    assert any(e.evidence_id == f"handoff:{fir_id}:board" for e in out)
    _check_provenance(out)


# --- pre-filing check --------------------------------------------------------------

def test_prefiling_check_reports_a_gap_or_an_honest_all_clear(dataset):
    fir_id = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 1')[0]["CaseMasterID"]
    state = _state("Would this case hold up?")
    state.intent = "PREFILING_CHECK"
    state.active_entities.active_fir = str(fir_id)

    out = orchestrator._run_specialists(state, widen=False)
    assert out
    assert any(e.evidence_id.startswith(f"filing:{fir_id}:") for e in out)
    _check_provenance(out)


# --- cross-station linkage ----------------------------------------------------------

def test_cross_station_linkage_runs_without_raising_and_reports_honestly(dataset):
    fir_id = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 1')[0]["CaseMasterID"]
    state = _state("Who else should know about this?")
    state.intent = "CROSS_STATION_LINKAGE"
    state.active_entities.active_fir = str(fir_id)

    out = orchestrator._run_specialists(state, widen=False)
    assert out, "must produce either real links or an honest absence"
    assert all(e.evidence_id.startswith(f"linkage:{fir_id}:") for e in out)
    _check_provenance(out)


def test_cross_station_linkage_never_names_a_case_outside_access_scope(dataset):
    """The v20 partial-visibility discipline (provenance._case_labels), applied to
    a brand-new producer: the link may be reported, the case named only where the
    officer's own scope allows it."""
    accused = ds.query(
        'SELECT "Accused"."CaseMasterID", "vx_accused_identity"."PersonUID" '
        'FROM "Accused" JOIN "vx_accused_identity" '
        'ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID"')
    by_person: dict = {}
    for a in accused:
        by_person.setdefault(a["PersonUID"], set()).add(a["CaseMasterID"])
    multi = next((pid for pid, cids in by_person.items() if len(cids) > 1), None)
    if multi is None:
        return   # no person with cases at two different stations in this dataset
    fir_id = sorted(by_person[multi])[0]
    other_ps = ds.one('SELECT "PoliceStationID" FROM "CaseMaster" WHERE "CaseMasterID" = :c',
                      {"c": sorted(by_person[multi])[-1]})
    this_ps = ds.one('SELECT "PoliceStationID" FROM "CaseMaster" WHERE "CaseMasterID" = :c',
                     {"c": fir_id})
    if other_ps["PoliceStationID"] == this_ps["PoliceStationID"]:
        return   # both cases at the same station — nothing cross-station to withhold

    state = _state("Who else should know about this?")
    state.intent = "CROSS_STATION_LINKAGE"
    state.officer_role = "IO"
    state.active_entities.active_fir = str(fir_id)
    saved = orchestrator._officer_ps
    orchestrator._officer_ps = lambda officer_id: str(this_ps["PoliceStationID"])
    try:
        out = orchestrator._run_specialists(state, widen=False)
    finally:
        orchestrator._officer_ps = saved
    assert any("outside your access scope" in e.content for e in out), (
        "an IO must not see a cross-station case named outright")


# --- poking holes in a finding ------------------------------------------------------

def _prior_turn(**over):
    from data import ConversationTurn
    base = dict(
        turn_index=0, query="Does this person have priors?", language="en",
        final_answer="...", citations=[{"index": 1, "evidence_id": "fir:9", "label": "FIR 9"}],
        evidence_items=[{"evidence_id": "fir:9", "source_type": "FIR_RECORD", "source_id": "9",
                         "source_query": "q", "content": "FIR 9, Hurt.", "confidence": 0.6,
                         "authoritative": False, "confidence_kind": "support",
                         "timestamp": datetime.now(timezone.utc).isoformat()}],
        visualization={"kind": "none", "data": {}}, agent_trace=[],
        created_at=datetime.now(timezone.utc))
    base.update(over)
    return ConversationTurn(**base)


def test_challenge_finding_names_a_real_case_gap():
    state = _state("Poke holes in this.")
    state.intent = "CHALLENGE_FINDING"

    prior = _prior_turn()
    saved_last_turn = orchestrator._last_turn
    saved_fir_by_id = orchestrator.sql_agent.fir_by_id
    saved_query = orchestrator.ds.query
    orchestrator._last_turn = lambda sid: prior
    orchestrator.sql_agent.fir_by_id = lambda fir_id, role, ps: (
        [{"fir_id": "9", "fir_number": "FIR9", "date_filed": "2020-01-01",
          "crime_type": "Hurt", "district": "Mandya", "ps_code": "1",
          "case_status": "Under Investigation"}] if fir_id == "9" else [])
    orchestrator.ds.query = lambda sql, params=None: []   # no arrest, no chargesheet
    try:
        orchestrator.node_retrieve(state)
        orchestrator.node_evaluate(state)
        orchestrator.node_synthesize(state)
    finally:
        orchestrator._last_turn = saved_last_turn
        orchestrator.sql_agent.fir_by_id = saved_fir_by_id
        orchestrator.ds.query = saved_query

    assert "weaken" in state.final_answer.lower()
    assert "no arrest is recorded" in state.final_answer.lower()
    assert len(state.citations) == 1     # the prior turn's own citation is re-shown


def test_challenge_finding_finds_the_case_behind_a_handoff_turn():
    """Live-found: 'poke holes in this' right after 'catch me up on this case' read
    no case at all, because CASE_HANDOFF's own evidence is `handoff:{fir_id}:summary`
    — the FIR id sits in the SECOND segment, not written as a bare `fir:{fir_id}`
    citation the way a direct FIR lookup's evidence is."""
    state = _state("Poke holes in this.")
    state.intent = "CHALLENGE_FINDING"
    state.active_entities.active_fir = "9"

    prior = _prior_turn(
        query="Catch me up on this case.",
        citations=[{"index": 1, "evidence_id": "handoff:9:summary", "label": "x"}],
        evidence_items=[{"evidence_id": "handoff:9:summary", "source_type": "FIR_RECORD",
                         "source_id": "9", "source_query": "q", "content": "...",
                         "confidence": 0.95, "authoritative": True,
                         "confidence_kind": "support",
                         "timestamp": datetime.now(timezone.utc).isoformat()}])
    saved_last_turn = orchestrator._last_turn
    saved_fir_by_id = orchestrator.sql_agent.fir_by_id
    saved_query = orchestrator.ds.query
    orchestrator._last_turn = lambda sid: prior
    orchestrator.sql_agent.fir_by_id = lambda fir_id, role, ps: (
        [{"fir_id": "9", "fir_number": "FIR9", "date_filed": "2020-01-01",
          "crime_type": "Hurt", "district": "Mandya", "ps_code": "1",
          "case_status": "Under Investigation"}] if fir_id == "9" else [])
    orchestrator.ds.query = lambda sql, params=None: []
    try:
        orchestrator.node_retrieve(state)
        orchestrator.node_evaluate(state)
        orchestrator.node_synthesize(state)
    finally:
        orchestrator._last_turn = saved_last_turn
        orchestrator.sql_agent.fir_by_id = saved_fir_by_id
        orchestrator.ds.query = saved_query

    assert "no arrest is recorded" in state.final_answer.lower()


def test_challenge_finding_refuses_honestly_on_a_first_turn():
    state = _state("Poke holes in this.")
    state.intent = "CHALLENGE_FINDING"
    saved = orchestrator._last_turn
    orchestrator._last_turn = lambda sid: None
    try:
        orchestrator.node_retrieve(state)
        orchestrator.node_evaluate(state)
        orchestrator.node_synthesize(state)
    finally:
        orchestrator._last_turn = saved
    assert state.citations == []
    assert "nothing" in state.final_answer.lower() or "first" in state.final_answer.lower()


# --- the safe-draft tag ---------------------------------------------------------

def test_draft_summary_tags_the_derived_figure(dataset):
    from rag_agent.copilot.brief import generate_copilot_brief
    fir_id = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" LIMIT 1')[0]["CaseMasterID"]
    brief = generate_copilot_brief(str(fir_id), "IG", "")
    assert "DERIVED" in brief.draft_summary


# --- v25: two defects found by reading the answers out loud ----------------------

def test_interrogation_prep_asks_the_subject_not_the_investigating_officer(dataset):
    """Found live. The briefing was assembled from `_case_evidence_gaps`, which finds
    file-completeness gaps — no arrest entry, no chargesheet after N days. Those are
    the investigating officer's OWN record-keeping; put to a suspect across a table
    ("explain the 805-day delay in filing your chargesheet") they are questions
    nobody in the room can answer. PREFILING_CHECK still owns them."""
    pid = sql_agent.ranked_offenders("IG", "", limit=1)[0]["person_id"]
    state = _state("What should I ask him?")
    state.intent = "INTERROGATION_PREP"
    state.active_entities.active_person = pid

    body = "\n".join(e.content for e in orchestrator._run_specialists(state, widen=False))
    low = body.lower()
    assert "no chargesheet has been filed in" not in low
    assert "no arrest is recorded on this case" not in low
    # and it must actually produce questions to put to the person
    assert "ask" in low


def test_challenge_never_quotes_an_empty_weakest_point():
    """Found live: `- The least-supported single point this rests on: "" (confidence
    100%)`. Two bugs in one line — `sessions._pack` sheds evidence BODIES on a large
    turn, so `content` is empty on exactly the answers most worth challenging; and a
    point at 100% confidence is not the least-supported anything."""
    state = _state("Convince me this is wrong.")
    state.intent = "CHALLENGE_FINDING"
    prior = _prior_turn(
        query="Who are the associates of X?",
        citations=[{"index": 1, "evidence_id": "assoc:803", "label": "X is an associate"}],
        # a truncated turn: identity kept, body shed — and confidence 1.0
        evidence_items=[{"evidence_id": "assoc:803", "source_type": "GRAPH_RELATIONSHIP",
                         "source_id": "803", "authoritative": False,
                         "confidence": 1.0, "confidence_kind": "support"}])
    saved_last_turn = orchestrator._last_turn
    saved_query = orchestrator.ds.query
    saved_net = orchestrator.graph_agent.person_network
    orchestrator._last_turn = lambda sid: prior
    orchestrator.ds.query = lambda sql, params=None: []
    orchestrator.graph_agent.person_network = lambda pid, role: []
    try:
        orchestrator.node_retrieve(state)
        orchestrator.node_evaluate(state)
        orchestrator.node_synthesize(state)
    finally:
        orchestrator._last_turn = saved_last_turn
        orchestrator.ds.query = saved_query
        orchestrator.graph_agent.person_network = saved_net

    assert '""' not in state.final_answer
    assert "least-supported" not in state.final_answer.lower()


def test_challenge_of_a_derived_network_names_the_derivation_it_rests_on(dataset):
    """A PERSON_NETWORK answer's evidence ids are `assoc:`/`same_as:`, which the case-
    and person-id extraction did not recognise — so the most-challenged kind of answer
    got no structural check at all. Its real weaknesses are the multi-hop links and
    the record linkage underneath every name (CLAUDE.md §0)."""
    pid = sql_agent.ranked_offenders("IG", "", limit=1)[0]["person_id"]
    lines = orchestrator._network_challenges(pid, "IG")
    assert lines, "a resolved offender's network must have something checkable"
    assert any("record linkage" in ln for ln in lines)
