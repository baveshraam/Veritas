"""Execution tests for the five new analytics handlers (Area/Community/Watchlist/
Workload/Compare-identity-check) — not just that `classify()` routes to them
(test_engine.py), but that the handler itself runs against the real dataset without
raising. This is the exact gap that let a live `NameError: name '_STALE_DAYS' is not
defined` reach the console in `_handle_station_workload`: sql_agent-level tests
exercised `station_workload()` directly and never went through the orchestrator
handler's own f-strings, where the bug actually was.
"""
from rag_agent import orchestrator, provenance
from rag_agent.agents import sql_agent
from rag_agent.state import EvidenceItem, InvestigationState


def _state(query: str) -> InvestigationState:
    return InvestigationState(session_id="t", officer_id="1", officer_role="IG",
                              original_query=query)


def test_handle_area_profile_produces_record_and_census_evidence(dataset):
    district = sql_agent.crime_counts_by_district(limit=1)[0]["district"]
    state = _state(f"Give me an area profile of {district}")
    out: list[EvidenceItem] = []
    orchestrator._handle_area_profile(state, out, "IG", "", 0.0)
    assert out, "no evidence produced for a district that has cases"
    assert any(e.evidence_id.startswith("area:mix:") for e in out)
    # Every produced evidence id must have a working provenance handler.
    for e in out:
        d = provenance.explain(e, role="IG", ps="")
        assert not d.incomplete, f"{e.evidence_id}: provenance chain incomplete"


def test_handle_community_profile_produces_member_evidence(dataset):
    from data import ds
    cid_row = ds.one('SELECT "CommunityID" FROM "vx_person" WHERE "CommunityID" IS NOT NULL')
    assert cid_row, "graph pass produced no community"
    cid = cid_row["CommunityID"]
    state = _state(f"Who is in community {cid}?")
    out: list[EvidenceItem] = []
    orchestrator._handle_community_profile(state, out, "IG", "", 0.0)
    assert any(e.evidence_id.startswith(f"community:summary:{cid}") for e in out)
    assert any(e.evidence_id.startswith("community:") and ":summary:" not in e.evidence_id
              for e in out), "no per-member community: evidence produced"
    for e in out:
        d = provenance.explain(e, role="IG", ps="")
        assert not d.incomplete


def test_handle_watchlist_produces_the_honest_absence_when_nothing_flagged(dataset):
    state = _state("Show me the financial watchlist")
    out: list[EvidenceItem] = []
    orchestrator._handle_watchlist(state, out, "IG", "", 0.0)
    assert out and out[0].evidence_id == "watchlist:none"
    d = provenance.explain(out[0], role="IG", ps="")
    assert not d.incomplete


def test_handle_watchlist_labels_rule_and_gnn_detectors_apart(dataset):
    from data import ds
    from data.transactions import clear_flags, flag_transaction

    rows = ds.query('SELECT "TxnID" FROM "vx_txn" LIMIT 2')
    assert len(rows) == 2
    try:
        flag_transaction(rows[0]["TxnID"], "structuring", "rule:structuring", 0.9)
        flag_transaction(rows[1]["TxnID"], "layering", "gnn:subgraph", 0.5)
        state = _state("Show me the financial watchlist")
        out: list[EvidenceItem] = []
        orchestrator._handle_watchlist(state, out, "IG", "", 0.0)
        summary = next(e for e in out if e.evidence_id == "watchlist:summary")
        assert "1 from the rule-based" in summary.content
        assert "1 from the GNN" in summary.content
        rows_out = [e for e in out if e.evidence_id.startswith(f"watchlist:{rows[0]['TxnID']}")]
        assert rows_out and rows_out[0].authoritative is True
        gnn_out = [e for e in out if e.evidence_id.startswith(f"watchlist:{rows[1]['TxnID']}")]
        assert gnn_out and gnn_out[0].authoritative is False
        for e in out:
            d = provenance.explain(e, role="IG", ps="")
            assert not d.incomplete
    finally:
        clear_flags()


def test_handle_station_workload_does_not_raise_and_names_are_defined(dataset):
    """The regression test for the exact live bug: a NameError inside the handler's
    own f-strings, invisible to any test that only calls sql_agent.station_workload
    directly."""
    state = _state("Which stations are falling behind?")
    out: list[EvidenceItem] = []
    orchestrator._handle_station_workload(state, out, "IG", "", 0.0)
    assert out, "no evidence produced — fixture must have open cases"
    assert str(sql_agent.STALE_DAYS) in out[0].content
    for e in out:
        d = provenance.explain(e, role="IG", ps="")
        assert not d.incomplete


def test_comparison_identity_check_fires_only_for_similar_names():
    similar = orchestrator._comparison_identity_check(["1", "2"], ["Suma Nadkarni", "Soom Nadkarni"])
    assert len(similar) == 1
    assert similar[0].evidence_id == "idcheck:1:2"
    d = provenance.explain(similar[0], role="IG", ps="")
    assert not d.incomplete

    dissimilar = orchestrator._comparison_identity_check(
        ["1", "2"], ["Usha Naika", "Ravi Kumar"])
    assert dissimilar == []
