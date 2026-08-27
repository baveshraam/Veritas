"""GET /timeline/case/{fir_id}, GET /timeline/person/{person_id} — the cross-entity
investigation timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 3).

Mirrors copilot.py: the same station-scope check every other case-reading endpoint
applies, thrown as 403/404 by `rag_agent.timeline` itself and translated here — a
second REST surface over a case an officer could not otherwise open would be a rule
enforced by one caller and not its neighbour.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from rag_agent import timeline
from rag_agent.timeline import NotPermitted

from ..audit import record
from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


@router.get("/timeline/case/{fir_id}")
async def timeline_for_case(fir_id: str, officer: Officer = Depends(current_officer)):
    try:
        result = timeline.case_timeline(fir_id, officer.role, officer.ps_code)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "FIR not found")
    except NotPermitted:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This FIR was filed at another police station")
    record(officer.officer_id, None, f"/timeline/case/{fir_id}", {"fir_id": fir_id}, result)
    return result


@router.get("/timeline/person/{person_id}")
async def timeline_for_person(person_id: str, officer: Officer = Depends(current_officer)):
    try:
        result = timeline.person_timeline(person_id, officer.role, officer.ps_code)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    record(officer.officer_id, None, f"/timeline/person/{person_id}",
          {"person_id": person_id}, result)
    return result
