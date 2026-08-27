"""Persistent per-case investigation board — raw row CRUD, no policy.

One table, one row per item (`vx_case_board_item`), discriminated by `ItemType`:
"evidence" | "person" | "lead" | "note" | "question" | "finding". Policy (can this
officer see/touch this case's board at all) is enforced one layer up, in
`rag_agent.board` — this module is the same kind of thin ZCQL layer `data.sessions`
already is for `vx_session`, and stays ignorant of who is asking on purpose: two
callers (the REST router and the conversational orchestrator) must share exactly one
enforcement point, not each grow their own.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from . import ds

ITEM_TYPES = ("evidence", "person", "lead", "note", "question", "finding")
LEAD_STATUSES = ("open", "pursued", "dismissed")
QUESTION_STATUSES = ("open", "resolved")

_COLUMNS = (
    "BoardItemID", "CaseMasterID", "ItemType", "RefType", "RefID", "Content",
    "Confidence", "SourceQuery", "Status", "Reason", "CreatedBy", "CreatedAt",
    "UpdatedBy", "UpdatedAt",
)


def _row_to_item(r: dict) -> dict:
    return {
        "item_id": str(r["BoardItemID"]),
        "case_id": str(r["CaseMasterID"]),
        "item_type": r["ItemType"],
        "ref_type": r.get("RefType"),
        "ref_id": r.get("RefID"),
        "content": r.get("Content") or "",
        "confidence": r.get("Confidence"),
        "source_query": r.get("SourceQuery"),
        "status": r.get("Status"),
        "reason": r.get("Reason"),
        "created_by": str(r["CreatedBy"]) if r.get("CreatedBy") is not None else None,
        "created_at": r.get("CreatedAt"),
        "updated_by": str(r["UpdatedBy"]) if r.get("UpdatedBy") is not None else None,
        "updated_at": r.get("UpdatedAt"),
    }


def create_item(case_id: int, item_type: str, content: str, created_by: int,
                ref_type: Optional[str] = None, ref_id: Optional[str] = None,
                confidence: Optional[float] = None, source_query: Optional[str] = None,
                status: Optional[str] = None) -> dict:
    if item_type not in ITEM_TYPES:
        raise ValueError(f"unknown board item type {item_type!r}")
    now = datetime.now(timezone.utc)
    row = {
        "BoardItemID": ds.next_id("vx_case_board_item", "BoardItemID"),
        "CaseMasterID": case_id,
        "ItemType": item_type,
        "RefType": ref_type,
        "RefID": str(ref_id) if ref_id is not None else None,
        "Content": content,
        "Confidence": confidence,
        "SourceQuery": source_query,
        "Status": status,
        "CreatedBy": created_by,
        "CreatedAt": now,
    }
    ds.insert("vx_case_board_item", [row])
    return _row_to_item({**row, "Reason": None, "UpdatedBy": None, "UpdatedAt": None})


def list_items(case_id: int) -> list[dict]:
    rows = ds.query(
        f'SELECT {", ".join(chr(34) + c + chr(34) for c in _COLUMNS)} '
        'FROM "vx_case_board_item" WHERE "CaseMasterID" = :cid ORDER BY "CreatedAt"',
        {"cid": case_id})
    return [_row_to_item(r) for r in rows]


def get_item(item_id: int) -> Optional[dict]:
    row = ds.one(
        f'SELECT {", ".join(chr(34) + c + chr(34) for c in _COLUMNS)} '
        'FROM "vx_case_board_item" WHERE "BoardItemID" = :iid', {"iid": item_id})
    return _row_to_item(row) if row else None


def update_item(item_id: int, updated_by: int, **fields: Any) -> dict:
    """Patch content/status/reason. Only the columns actually passed are touched —
    Data Store has no partial-UPDATE-by-diff, so the caller must read-then-write, and
    this is that single point rather than every caller doing it separately."""
    current = ds.one('SELECT * FROM "vx_case_board_item" WHERE "BoardItemID" = :iid',
                     {"iid": item_id})
    if not current:
        raise KeyError(f"board item {item_id} not found")
    # Callers pass all three kwargs through unconditionally (see rag_agent.board.
    # update_item), so "not given" and "given as None" are indistinguishable here —
    # treated the same, as "leave it alone". None of these three columns has a
    # legitimate reason to be explicitly nulled back out through this API.
    row = {"BoardItemID": item_id}
    for k in ("Status", "Reason", "Content"):
        arg = k[0].lower() + k[1:]
        row[k] = fields.get(arg) if fields.get(arg) is not None else current.get(k)
    row["UpdatedBy"] = updated_by
    row["UpdatedAt"] = datetime.now(timezone.utc)
    ds.update("vx_case_board_item", "BoardItemID", [row])
    merged = {**current, **row}
    return _row_to_item(merged)


def delete_item(item_id: int) -> None:
    ds.execute('DELETE FROM "vx_case_board_item" WHERE "BoardItemID" = :iid', {"iid": item_id})
