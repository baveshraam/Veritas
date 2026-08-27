"""The persistent per-case investigation board — policy-checked, case-scoped.

Wraps `data.board`'s raw row CRUD the same way `copilot.brief` wraps a case read:
the station rule is enforced HERE, once, so the REST router (`apps/api`) and the
conversational orchestrator (`rag_agent.orchestrator`) share one enforcement point
instead of each growing their own — the exact discipline `copilot.brief`'s own
docstring names as the fix for BUG-003 (a rule enforced by one caller and not its
neighbour is not a rule).

Does not duplicate FIR/person/financial/graph facts: every item stores a reference
(`ref_type`, `ref_id`) to the authoritative record plus a content *snapshot* taken at
pin time, never a second copy the record layer could drift out of sync with.
"""
from datetime import date, datetime
from typing import Any, Optional

from data import board as _db
from policy import can_view_fir

from .agents.sql_agent import fir_by_id
from .copilot.brief import NotPermitted

__all__ = ["NotPermitted", "get_board", "create_item", "update_item", "remove_item"]


def _json_safe(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _item_out(item: dict) -> dict:
    return {k: _json_safe(v) for k, v in item.items()}


def _scoped_case(fir_id: str, officer_role: str, officer_ps_code: str) -> dict:
    """The case this board belongs to, with the same station check every other
    case-reading endpoint applies (/fir, /copilot) — a board is reachable only from
    a case the officer may already open, never a separate authorization surface."""
    rows = fir_by_id(fir_id, "SHO", "")           # unscoped read; checked immediately below
    if not rows:
        raise KeyError(f"Case {fir_id} not found")
    case = rows[0]
    if not can_view_fir(officer_role, officer_ps_code, case["ps_code"]):
        raise NotPermitted(f"Case {fir_id} was filed at another police station")
    return case


def _own_item(case_id: int, item_id: str) -> dict:
    """The item, only if it actually belongs to this case — an officer authorized for
    case A must never mutate an item_id that belongs to case B by passing A's fir_id
    in the URL and B's item_id in the body. A 404 here reads exactly like "no such
    item", which is the correct, non-leaking answer to a guessed cross-case id."""
    item = _db.get_item(int(item_id))
    if not item or int(item["case_id"]) != case_id:
        raise KeyError(f"board item {item_id} not found on this case")
    return item


def get_board(fir_id: str, officer_role: str, officer_ps_code: str) -> dict:
    case = _scoped_case(fir_id, officer_role, officer_ps_code)
    items = [_item_out(i) for i in _db.list_items(int(fir_id))]
    grouped: dict[str, list[dict]] = {t: [] for t in _db.ITEM_TYPES}
    for i in items:
        grouped[i["item_type"]].append(i)
    return {
        "fir_id": fir_id, "fir_number": case["fir_number"],
        "crime_type": case["crime_type"], "district": case["district"],
        "case_status": case["case_status"],
        "items": items, "by_type": grouped, "total": len(items),
    }


def create_item(fir_id: str, officer_role: str, officer_ps_code: str, officer_id: str,
                item_type: str, content: str, ref_type: Optional[str] = None,
                ref_id: Optional[str] = None, confidence: Optional[float] = None,
                source_query: Optional[str] = None, status: Optional[str] = None) -> dict:
    _scoped_case(fir_id, officer_role, officer_ps_code)
    if item_type == "lead" and status is None:
        status = "open"
    if item_type == "question" and status is None:
        status = "open"
    item = _db.create_item(int(fir_id), item_type, content, int(officer_id),
                           ref_type=ref_type, ref_id=ref_id, confidence=confidence,
                           source_query=source_query, status=status)
    return _item_out(item)


def update_item(fir_id: str, officer_role: str, officer_ps_code: str, officer_id: str,
                item_id: str, status: Optional[str] = None, reason: Optional[str] = None,
                content: Optional[str] = None) -> dict:
    """Status transitions on a lead/question are the one mutation type this project's
    own rules require stay human-decided (never inferred/auto-applied by the model) —
    that discipline lives in the CALLER (a conversational command must come from an
    explicit officer instruction, never a side effect of answering a question), not
    here; this layer only enforces that the item is theirs to change."""
    case = _scoped_case(fir_id, officer_role, officer_ps_code)
    item = _own_item(int(case["fir_id"]), item_id)
    if status is not None:
        if item["item_type"] == "lead" and status not in _db.LEAD_STATUSES:
            raise ValueError(f"invalid lead status {status!r}")
        if item["item_type"] == "question" and status not in _db.QUESTION_STATUSES:
            raise ValueError(f"invalid question status {status!r}")
    updated = _db.update_item(int(item_id), int(officer_id), status=status,
                              reason=reason, content=content)
    return _item_out(updated)


def remove_item(fir_id: str, officer_role: str, officer_ps_code: str, item_id: str) -> dict:
    """Hard delete — for a pinned evidence/person/note, or a finding. NOT for a lead:
    'a dismissed lead must remain auditable', so a lead is retired via update_item's
    status='dismissed', never removed from the table. Returns the deleted item (for
    the audit before/after record) rather than nothing."""
    case = _scoped_case(fir_id, officer_role, officer_ps_code)
    item = _own_item(int(case["fir_id"]), item_id)
    if item["item_type"] == "lead":
        raise ValueError("a lead cannot be deleted — dismiss it instead (status=dismissed)")
    _db.delete_item(int(item_id))
    return _item_out(item)
