"""GET /copilot/{fir_id} — the Investigation Copilot brief.

officer_role is taken from the JWT and passed into generate_copilot_brief, which
applies policy INSIDE its graph reads and masks victim fields before the draft
summary is written. Masking generated prose afterwards is not reliable, so it is
never generated unmasked.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from rag_agent import generate_copilot_brief
from rag_agent.copilot.brief import NotPermitted

from ..audit import record
from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


@router.get("/copilot/{fir_id}")
async def copilot(fir_id: str, officer: Officer = Depends(current_officer)):
    try:
        brief = generate_copilot_brief(fir_id, officer.role, officer.ps_code)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "FIR not found")
    except NotPermitted:
        # 403, matching GET /fir/{id} exactly: the case exists and the officer is
        # entitled to know it is simply not theirs.
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This FIR was filed at another police station")
    payload = brief.model_dump()
    record(officer.officer_id, None, f"/copilot/{fir_id}", {"fir_id": fir_id}, payload)
    return payload
