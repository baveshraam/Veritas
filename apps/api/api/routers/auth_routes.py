"""POST /auth/token — issue a JWT for an officer.

Sign-in by KGID (the Karnataka Government ID the ER's `Employee` row carries). This is the
local/offline path: on Catalyst, identity comes from Catalyst Authentication instead and
`api.auth.catalyst_auth` is what runs. Either way the important property holds — once
issued the token is the ONLY source of officer_id/role downstream, and the `Employee`
record is the only source of role and station.
"""
from data import ds, officers
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth.jwt_auth import issue_token

router = APIRouter()


class TokenRequest(BaseModel):
    badge_no: str          # KGID


@router.post("/auth/token")
async def token(req: TokenRequest):
    row = ds.one('SELECT "EmployeeID" FROM "Employee" WHERE "KGID" = :b', {"b": req.badge_no})
    rec = officers.by_id(row["EmployeeID"]) if row else None
    if not rec:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown badge number")
    return {
        "access_token": issue_token(rec.officer_id, rec.role),
        "token_type": "bearer",
        "officer": {"name": rec.name, "role": rec.role, "ps_code": rec.ps_code},
    }


@router.get("/auth/officers")
async def list_officers():
    """Demo helper: one badge number per role to sign in with."""
    from data.generator.refdata import DESIGNATION_TO_ROLE

    seen: dict[str, dict] = {}
    for r in ds.query('SELECT "EmployeeID", "DesignationID", "KGID", "FirstName", "UnitID" '
                      'FROM "Employee" ORDER BY "EmployeeID"'):
        role = DESIGNATION_TO_ROLE.get(r["DesignationID"])
        if role and role not in seen:
            seen[role] = {"badge_no": r["KGID"], "name": r["FirstName"], "role": role,
                          "ps_code": str(r["UnitID"] or "")}
    return sorted(seen.values(), key=lambda o: o["role"])
