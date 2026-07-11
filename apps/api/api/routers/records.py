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


@router.get("/cases")
async def list_cases(
    q: str | None = None,
    crime_type: str | None = None,
    case_status: str | None = None,
    limit: int = 60,
    officer: Officer = Depends(current_officer),
):
    """The case index the console opens on.

    A conversational console that shows an empty box is unusable: an officer cannot
    ask about records they have never seen. This is the browsable inventory the chat
    is *about* — same policy scope, so what you can list is exactly what you can ask.
    """
    where, params = ["1=1"], {}
    if crime_type:
        where.append("crime_type = :ct")
        params["ct"] = crime_type
    if case_status:
        where.append("case_status = :cs")
        params["cs"] = case_status
    if q:
        where.append("(fir_number ILIKE :q OR crime_type ILIKE :q OR district ILIKE :q "
                     "OR modus_operandi ILIKE :q)")
        params["q"] = f"%{q}%"

    with get_session() as s:
        rows = s.execute(text(
            "SELECT fir_id, fir_number, ps_code, district, taluk, crime_type, "
            "       ipc_sections, date_filed, case_status, modus_operandi "
            f"FROM fir WHERE {' AND '.join(where)} "
            "ORDER BY date_filed DESC"), params).mappings().all()
        facet_rows = s.execute(text(
            "SELECT ps_code, crime_type, case_status FROM fir")).mappings().all()

    # ponytail: policy filtering in Python, not a WHERE clause — can_view_fir stays the
    # single definition of who sees what. Scale ceiling ~10^4 FIRs; push into SQL beyond.
    def visible(r) -> bool:
        return can_view_fir(officer.role, officer.ps_code, r["ps_code"])

    cases = [dict(r) for r in rows if visible(r)]
    mine = [r for r in facet_rows if visible(r)]

    def facet(field: str) -> list[dict]:
        counts: dict[str, int] = {}
        for r in mine:
            if r[field]:
                counts[r[field]] = counts.get(r[field], 0) + 1
        return [{"name": k, "count": v}
                for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]

    return {
        "cases": cases[:limit],
        "matched": len(cases),
        "total": len(mine),
        "crime_types": facet("crime_type"),
        "statuses": facet("case_status"),
    }


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
