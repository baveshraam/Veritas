"""GET/POST/PATCH/DELETE /board/{fir_id} — the persistent per-case investigation board.

Four endpoints, one dispatch-by-`item_type` create — not one route per item kind —
because every kind shares the same case-scoped RBAC check and the same audit
obligation; splitting them would mean splitting that enforcement five ways too.
`rag_agent.board` is the single policy-checked entry point this router and the
conversational orchestrator (`packages/rag_agent/rag_agent/orchestrator.py`,
`_handle_board_intent`) both go through — see that module's docstring for why.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from rag_agent import board as board_agent

from ..audit import record
from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


class CreateItemRequest(BaseModel):
    item_type: str
    content: str
    ref_type: str | None = None
    ref_id: str | None = None
    confidence: float | None = None
    source_query: str | None = None
    status: str | None = None


class UpdateItemRequest(BaseModel):
    status: str | None = None
    reason: str | None = None
    content: str | None = None


def _not_found(fir_id: str):
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Case {fir_id} not found")


def _forbidden():
    return HTTPException(status.HTTP_403_FORBIDDEN,
                         "This FIR was filed at another police station")


@router.get("/board/{fir_id}")
async def get_board(fir_id: str, officer: Officer = Depends(current_officer)):
    try:
        board = board_agent.get_board(fir_id, officer.role, officer.ps_code)
    except KeyError:
        raise _not_found(fir_id)
    except board_agent.NotPermitted:
        raise _forbidden()
    record(officer.officer_id, None, f"/board/{fir_id}", {"fir_id": fir_id}, board)
    return board


@router.post("/board/{fir_id}/items")
async def create_board_item(fir_id: str, body: CreateItemRequest,
                            officer: Officer = Depends(current_officer)):
    if body.item_type not in ("evidence", "person", "lead", "note", "question", "finding"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown item_type {body.item_type!r}")
    try:
        item = board_agent.create_item(
            fir_id, officer.role, officer.ps_code, officer.officer_id,
            body.item_type, body.content, ref_type=body.ref_type, ref_id=body.ref_id,
            confidence=body.confidence, source_query=body.source_query, status=body.status)
    except KeyError:
        raise _not_found(fir_id)
    except board_agent.NotPermitted:
        raise _forbidden()
    record(officer.officer_id, None, f"/board/{fir_id}/items", body.model_dump(), item)
    return item


@router.patch("/board/{fir_id}/items/{item_id}")
async def update_board_item(fir_id: str, item_id: str, body: UpdateItemRequest,
                            officer: Officer = Depends(current_officer)):
    try:
        item = board_agent.update_item(
            fir_id, officer.role, officer.ps_code, officer.officer_id, item_id,
            status=body.status, reason=body.reason, content=body.content)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board item not found")
    except board_agent.NotPermitted:
        raise _forbidden()
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    record(officer.officer_id, None, f"/board/{fir_id}/items/{item_id}",
           {"fir_id": fir_id, "item_id": item_id, **body.model_dump()}, item)
    return item


@router.delete("/board/{fir_id}/items/{item_id}")
async def delete_board_item(fir_id: str, item_id: str,
                            officer: Officer = Depends(current_officer)):
    try:
        deleted = board_agent.remove_item(fir_id, officer.role, officer.ps_code, item_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board item not found")
    except board_agent.NotPermitted:
        raise _forbidden()
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    record(officer.officer_id, None, f"/board/{fir_id}/items/{item_id}",
           {"fir_id": fir_id, "item_id": item_id, "action": "delete"}, deleted)
    return {"deleted": True, "item": deleted}
