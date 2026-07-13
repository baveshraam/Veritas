"""GET /cases, /fir/{id}, /person/{id} — structured records, policy-masked.

These are the responses where post-hoc enforcement is legitimate: the shape is known, so a
field can be nulled on the way out. That is NOT true of /chat, where the answer is prose —
which is why rag_agent applies the same rules at query-construction time instead. Same rule
set, two enforcement points.

`/person` returns a *resolved* person (`vx_person`), not an `Accused` row. The organizers'
ER has no person entity — an Accused row belongs to one case, and its `PersonID` is a
per-case label — so a person endpoint over the raw ER could only ever show one case at a
time. The identity layer is what makes this endpoint answerable at all.
"""
from data import ds, queries
from fastapi import APIRouter, Depends, HTTPException, status
from policy import can_view_fir, mask_person_fields
from rag_agent.agents.sql_agent import fir_by_id

from ..audit import record
from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()

_CASE_LIST = (
    'SELECT "CaseMaster"."CaseMasterID", "CaseMaster"."CrimeNo", '
    '       "CaseMaster"."CrimeRegisteredDate", "CaseMaster"."PoliceStationID", '
    '       "CaseMaster"."BriefFacts", "CrimeSubHead"."CrimeHeadName", '
    '       "CaseStatusMaster"."CaseStatusName", "District"."DistrictName" '
    'FROM "CaseMaster" '
    'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
    'JOIN "District" ON "Unit"."DistrictID" = "District"."DistrictID" '
    'LEFT JOIN "CrimeSubHead" '
    '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID" '
    'LEFT JOIN "CaseStatusMaster" '
    '  ON "CaseMaster"."CaseStatusID" = "CaseStatusMaster"."CaseStatusID" '
)


def _flat(r: dict) -> dict:
    return {
        "fir_id": str(r["CaseMasterID"]),
        "fir_number": r["CrimeNo"],
        "ps_code": str(r["PoliceStationID"]),
        "district": r.get("DistrictName"),
        "crime_type": r.get("CrimeHeadName"),
        "date_filed": r.get("CrimeRegisteredDate"),
        "case_status": r.get("CaseStatusName"),
        "narrative": r.get("BriefFacts"),
    }


@router.get("/cases")
async def list_cases(
    q: str | None = None,
    crime_type: str | None = None,
    case_status: str | None = None,
    limit: int = 60,
    officer: Officer = Depends(current_officer),
):
    """The case index the console opens on.

    A conversational console that shows an empty box is unusable: an officer cannot ask
    about records they have never seen. This is the browsable inventory the chat is *about*
    — same policy scope, so what you can list is exactly what you can ask.
    """
    rows = [_flat(r) for r in
            ds.query(_CASE_LIST + 'ORDER BY "CaseMaster"."CrimeRegisteredDate" DESC')]

    # ponytail: policy filtering in Python, not a WHERE clause — can_view_fir stays the
    # single definition of who sees what. Scale ceiling ~10^4 cases; push into ZCQL beyond.
    mine = [r for r in rows if can_view_fir(officer.role, officer.ps_code, r["ps_code"])]

    matched = mine
    if crime_type:
        matched = [r for r in matched if r["crime_type"] == crime_type]
    if case_status:
        matched = [r for r in matched if r["case_status"] == case_status]
    if q:
        needle = q.lower()
        matched = [r for r in matched
                   if any(needle in str(r.get(f) or "").lower()
                          for f in ("fir_number", "crime_type", "district", "narrative"))]

    def facet(field: str) -> list[dict]:
        counts: dict[str, int] = {}
        for r in mine:
            if r.get(field):
                counts[r[field]] = counts.get(r[field], 0) + 1
        return [{"name": k, "count": v}
                for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]

    return {
        "cases": matched[:limit],
        "matched": len(matched),
        "total": len(mine),
        "crime_types": facet("crime_type"),
        "statuses": facet("case_status"),
    }


@router.get("/fir/{fir_id}")
async def get_fir(fir_id: str, officer: Officer = Depends(current_officer)):
    rows = fir_by_id(fir_id, "SHO", "")          # unscoped read; the check is immediately below
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "FIR not found")
    fir = rows[0]

    if not can_view_fir(officer.role, officer.ps_code, fir["ps_code"]):
        # 403, not a filtered-empty 200: pretending the record doesn't exist would be a lie,
        # and an IO is entitled to know the case is simply not theirs.
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This FIR was filed at another police station")

    fir["accused"] = ds.query(
        'SELECT "Accused"."AccusedName", "Accused"."AgeYear", '
        '       "vx_accused_identity"."PersonUID" '
        'FROM "Accused" LEFT JOIN "vx_accused_identity" '
        '  ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID" '
        'WHERE "Accused"."CaseMasterID" = :cid', {"cid": int(fir_id)})
    fir["victims"] = ds.query(
        'SELECT "VictimName", "AgeYear" FROM "Victim" WHERE "CaseMasterID" = :cid',
        {"cid": int(fir_id)})
    fir["sections"] = ds.query(
        'SELECT "ActID", "SectionID" FROM "ActSectionAssociation" '
        'WHERE "CaseMasterID" = :cid ORDER BY "SectionOrderID"', {"cid": int(fir_id)})

    record(officer.officer_id, None, f"/fir/{fir_id}", {"fir_id": fir_id}, fir)
    return fir


@router.get("/person/{person_id}")
async def get_person(person_id: str, officer: Officer = Depends(current_officer)):
    row = ds.one(
        'SELECT "PersonUID", "CanonicalName", "NameKn", "DOB", "GenderID", "RiskScore", '
        '"IsHabitualOffender", "GangAffiliation", "PageRank", "CommunityID" '
        'FROM "vx_person" WHERE "PersonUID" = :p', {"p": int(person_id)})
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")

    person = {
        "person_id": str(row["PersonUID"]),
        "name_en": row["CanonicalName"],
        "name_kn": row["NameKn"],
        "dob": row["DOB"],
        "gender": row["GenderID"],
        "risk_score": row["RiskScore"],
        "criminal_history": bool(row["IsHabitualOffender"]),
        "gang_affiliation": row["GangAffiliation"],
        "pagerank": row["PageRank"],
        "community": row["CommunityID"],
        "cases": [{"fir_id": str(c["CaseMasterID"]), "fir_number": c["CrimeNo"],
                   "date_filed": c["CrimeRegisteredDate"],
                   "ps_code": str(c["PoliceStationID"])}
                  for c in queries.cases_for_person(int(person_id))],
    }
    masked = mask_person_fields(officer.role, person)
    record(officer.officer_id, None, f"/person/{person_id}", {"person_id": person_id}, masked)
    return masked
