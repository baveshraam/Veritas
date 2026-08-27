"""data.board — raw row CRUD for the persistent per-case investigation board.

No policy here (that is rag_agent.board's job) — these tests only check the table
round-trips correctly: create/list/get/update/delete, and that a lead's lifecycle
fields (status/reason) and an audit-relevant CreatedBy/UpdatedBy survive.
"""
import pytest

from data import board


def _case_id(dataset) -> int:
    from data import ds
    return ds.scalar('SELECT "CaseMasterID" AS c FROM "CaseMaster"')


def test_create_and_list_round_trip(dataset):
    cid = _case_id(dataset)
    item = board.create_item(cid, "note", "verify the alibi", created_by=7)
    assert item["item_type"] == "note"
    assert item["content"] == "verify the alibi"
    assert item["created_by"] == "7"
    assert item["case_id"] == str(cid)

    items = board.list_items(cid)
    assert any(i["item_id"] == item["item_id"] for i in items)


def test_unknown_item_type_is_rejected(dataset):
    with pytest.raises(ValueError):
        board.create_item(_case_id(dataset), "gang_chart", "x", created_by=1)


def test_get_item_returns_none_for_a_missing_id(dataset):
    assert board.get_item(999_999_999) is None


def test_update_item_only_touches_the_fields_given(dataset):
    cid = _case_id(dataset)
    item = board.create_item(cid, "lead", "follow up on X", created_by=1, status="open")

    updated = board.update_item(int(item["item_id"]), updated_by=2, status="pursued")
    assert updated["status"] == "pursued"
    assert updated["content"] == "follow up on X"       # untouched
    assert updated["updated_by"] == "2"

    again = board.update_item(int(item["item_id"]), updated_by=3, reason="confirmed alibi")
    assert again["status"] == "pursued"                 # still pursued, not clobbered
    assert again["reason"] == "confirmed alibi"


def test_update_a_missing_item_raises(dataset):
    with pytest.raises(KeyError):
        board.update_item(999_999_999, updated_by=1, status="dismissed")


def test_delete_item_removes_it(dataset):
    cid = _case_id(dataset)
    item = board.create_item(cid, "evidence", "some pinned fact", created_by=1)
    board.delete_item(int(item["item_id"]))
    assert board.get_item(int(item["item_id"])) is None


def test_items_are_scoped_per_case(dataset):
    from data import ds
    ids = [r["c"] for r in ds.query('SELECT DISTINCT "CaseMasterID" AS c FROM "CaseMaster" LIMIT 2')]
    if len(ids) < 2:
        pytest.skip("dataset has only one case")
    a, b = ids
    board.create_item(a, "note", "note on A", created_by=1)
    assert not any(i["case_id"] == str(a) for i in board.list_items(b))
