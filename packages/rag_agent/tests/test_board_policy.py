"""rag_agent.board — the policy-checked entry point every caller (the REST router,
the conversational orchestrator) shares. Mirrors test_copilot.py's discipline: the
station rule (BUG-003's fix pattern) must hold here exactly as it does for /fir and
/copilot, since a board is reachable only from a case the officer may already open.
"""
import pytest

from rag_agent import board


def _two_cases_different_stations(dataset):
    """A (own, other) pair of CaseMasterIDs on different stations, if one exists."""
    from data import ds
    rows = ds.query('SELECT "CaseMasterID", "PoliceStationID" FROM "CaseMaster"')
    ps_groups: dict[int, list[int]] = {}
    for r in rows:
        ps_groups.setdefault(r["PoliceStationID"], []).append(r["CaseMasterID"])
    stations = list(ps_groups)
    if len(stations) < 2:
        pytest.skip("dataset has only one station")
    return ps_groups[stations[0]][0], stations[0], ps_groups[stations[1]][0]


def test_an_io_cannot_read_another_stations_board(dataset):
    own, own_ps, other = _two_cases_different_stations(dataset)
    b = board.get_board(str(own), "IO", str(own_ps))
    assert b["fir_id"] == str(own)
    with pytest.raises(board.NotPermitted):
        board.get_board(str(other), "IO", str(own_ps))


def test_an_io_cannot_write_to_another_stations_board(dataset):
    own, own_ps, other = _two_cases_different_stations(dataset)
    with pytest.raises(board.NotPermitted):
        board.create_item(str(other), "IO", str(own_ps), "1", "note", "sneaking in a note")


def test_a_missing_case_raises_key_error(dataset):
    with pytest.raises(KeyError):
        board.get_board("999999999", "IG", "")


def test_create_get_update_remove_round_trip(dataset):
    from data import ds
    cid = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')

    item = board.create_item(str(cid), "IG", "", "5", "note", "a real observation")
    assert item["item_type"] == "note"

    b = board.get_board(str(cid), "IG", "")
    assert any(i["item_id"] == item["item_id"] for i in b["items"])
    assert b["by_type"]["note"], "the item must be grouped under its own type"

    updated = board.update_item(str(cid), "IG", "", "5", item["item_id"], content="edited")
    assert updated["content"] == "edited"

    deleted = board.remove_item(str(cid), "IG", "", item["item_id"])
    assert deleted["item_id"] == item["item_id"]
    b2 = board.get_board(str(cid), "IG", "")
    assert not any(i["item_id"] == item["item_id"] for i in b2["items"])


def test_a_lead_cannot_be_hard_deleted(dataset):
    """'A dismissed lead must remain auditable' — the API for retiring a lead is a
    status change, not a delete, so the row (and its disposition history) survives."""
    from data import ds
    cid = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')
    lead = board.create_item(str(cid), "IG", "", "5", "lead", "a lead", status="open")
    with pytest.raises(ValueError):
        board.remove_item(str(cid), "IG", "", lead["item_id"])
    # still there, untouched
    assert board.get_board(str(cid), "IG", "")["by_type"]["lead"]


def test_lead_status_is_validated(dataset):
    from data import ds
    cid = ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')
    lead = board.create_item(str(cid), "IG", "", "5", "lead", "a lead", status="open")
    with pytest.raises(ValueError):
        board.update_item(str(cid), "IG", "", "5", lead["item_id"], status="not-a-real-status")
    ok = board.update_item(str(cid), "IG", "", "5", lead["item_id"], status="dismissed",
                           reason="dead end — confirmed alibi")
    assert ok["status"] == "dismissed"
    assert ok["reason"] == "dead end — confirmed alibi"


def test_an_item_cannot_be_mutated_through_a_different_cases_url(dataset):
    """Even when the officer is authorized for BOTH cases, an item_id from case A must
    not be reachable by naming case B in the URL — cross-case tampering, not just
    cross-station, must be blocked."""
    from data import ds
    ids = [r["c"] for r in ds.query('SELECT DISTINCT "CaseMasterID" AS c FROM "CaseMaster" LIMIT 2')]
    if len(ids) < 2:
        pytest.skip("dataset has only one case")
    a, b_case = ids
    item = board.create_item(str(a), "IG", "", "5", "note", "belongs to A")
    with pytest.raises(KeyError):
        board.update_item(str(b_case), "IG", "", "5", item["item_id"], content="hijacked")
