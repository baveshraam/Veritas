"""GET /sessions, GET /sessions/{id} — chat history, pooled by rank+station.

History is never listed per named officer: a session belongs to whichever desk
asked it — every DSP at a given station shares one history bucket — so the
roster picker's own move away from personal names (LoginGate/TopBar) holds here
too. `vx_audit_log` is untouched by any of this; it keeps recording the real
signed-in EmployeeID for every action regardless of what the console pools or
displays.
"""
from data import get_conversation_history, list_sessions, officers, ds
from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


@router.get("/sessions")
async def sessions(officer: Officer = Depends(current_officer)):
    return list_sessions(officer.role, officer.ps_code)


@router.get("/sessions/{session_id}")
async def session_detail(session_id: str, officer: Officer = Depends(current_officer)):
    row = ds.one('SELECT "EmployeeID" FROM "vx_session" WHERE "SessionID" = :sid',
                 {"sid": session_id})
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")

    owner = officers.by_id(str(row["EmployeeID"]))
    if not owner or owner.role != officer.role or owner.ps_code != officer.ps_code:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This session belongs to a different rank/station")

    return [t.model_dump(mode="json") for t in get_conversation_history(session_id)]
