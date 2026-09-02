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


# Signing in is the FIRST thing anyone does, and on a cold container it is also the
# first thing to touch the data layer — which means it pays the one-off Data Store
# mirror hydration (~23s, see CLAUDE.md v13/BUG-001). If that read raises, FastAPI's
# default is a bare 500, and "500" on the sign-in screen is indistinguishable from a
# broken deployment. Observed live: one 500 from /auth/token seconds after a redeploy,
# with the identical request succeeding on retry once the container was warm.
#
# 503 is the truthful status for this — the service exists and is starting, the request
# is worth retrying — and the console's sign-in gate already treats a failed roster
# fetch as "still warming up" rather than as a dead API. The exception type is kept in
# the detail so a genuine data-layer fault is still diagnosable and not silently
# reported as a warm-up.
_STARTING = ("The records layer is not ready yet — this container is still loading the "
             "case data. Retry in a few seconds.")


def _data_layer(fn):
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as e:                                    # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"{_STARTING} ({type(e).__name__})") from e


@router.post("/auth/token")
async def token(req: TokenRequest):
    row = _data_layer(lambda: ds.one(
        'SELECT "EmployeeID" FROM "Employee" WHERE "KGID" = :b', {"b": req.badge_no}))
    rec = officers.by_id(row["EmployeeID"]) if row else None
    if not rec:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown badge number")
    # No personal name in the response — the console identifies an officer by rank
    # and station only, never by name (LoginGate/TopBar). `rec.name` still exists
    # in the Employee record and in vx_audit_log's real EmployeeID; it simply never
    # crosses this endpoint.
    return {
        "access_token": issue_token(rec.officer_id, rec.role),
        "token_type": "bearer",
        "officer": {"role": rec.role, "ps_code": rec.ps_code},
    }


@router.get("/auth/officers")
async def list_officers():
    """Demo helper: one badge number per role to sign in with. No personal name —
    see the note in `token()` above."""
    from data.generator.refdata import DESIGNATION_TO_ROLE

    seen: dict[str, dict] = {}
    rows = _data_layer(lambda: ds.query(
        'SELECT "EmployeeID", "DesignationID", "KGID", "UnitID" '
        'FROM "Employee" ORDER BY "EmployeeID"'))
    for r in rows:
        role = DESIGNATION_TO_ROLE.get(int(r["DesignationID"] or 0))
        if role and role not in seen:
            seen[role] = {"badge_no": r["KGID"], "role": role, "ps_code": str(r["UnitID"] or "")}
    return sorted(seen.values(), key=lambda o: o["role"])
