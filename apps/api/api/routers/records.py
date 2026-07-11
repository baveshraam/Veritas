"""GET /fir/{id} and /person/{id} — structured records, policy-masked.

These are the responses where post-hoc enforcement is legitimate: the shape is
known, so a field can be nulled on the way out. That is NOT true of /chat, where
the answer is prose — which is why rag_agent applies the same rules at
query-construction time instead. Same rule set, two enforcement points.
"""
from data.db import get_session
from fastapi import APIRouter, Depends, HTTPException, status
from policy import can_view_fir, mask_person_fields
from sqlalchemy import text

from ..audit import record
from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


@router.get("/fir/{fir_id}")
async def get_fir(fir_id: str, officer: Officer = Depends(current_officer)):
    with get_session() as s:
        row = s.execute(text(
            "SELECT fir_id, fir_number, ps_code, district_code, district, taluk, "
            "       crime_type, ipc_sections, date_filed, occurrence_from, "
            "       occurrence_to, case_status, modus_operandi, narrative, "
            "       complainant_id, io_id "
            "FROM fir WHERE fir_id = CAST(:f AS uuid)"), {"f": fir_id}).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "FIR not found")

    fir = dict(row)
    if not can_view_fir(officer.role, officer.ps_code, fir["ps_code"]):
        # 403, not a filtered-empty 200: pretending the record doesn't exist would
        # be a lie, and an IO is entitled to know the case is simply not theirs.
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This FIR was filed at another police station")

    record(officer.officer_id, None, f"/fir/{fir_id}", {"fir_id": fir_id}, fir)
    return fir


@router.get("/person/{person_id}")
async def get_person(person_id: str, officer: Officer = Depends(current_officer)):
    with get_session() as s:
        row = s.execute(text(
            "SELECT person_id, scrb_id, name_en, name_kn, dob, gender, "
            "       aadhaar_hash, criminal_history, risk_score, gang_affiliation, "
            "       canonical_entity_id, ST_AsText(address_geom) AS address_geom "
            "FROM person WHERE person_id = CAST(:p AS uuid)"),
            {"p": person_id}).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")

    masked = mask_person_fields(officer.role, dict(row))
    record(officer.officer_id, None, f"/person/{person_id}", {"person_id": person_id}, masked)
    return masked
