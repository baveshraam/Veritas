"""POST /auth/token — issue a JWT for an officer.

Demo-grade sign-in by badge number: there is no HR identity provider to federate
with here (Keycloak is the production path, Appendix A). The important property is
that the token, once issued, is the ONLY source of officer_id/role downstream.
"""
from data.db import get_session
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from ..auth.jwt_auth import issue_token

router = APIRouter()


class TokenRequest(BaseModel):
    badge_no: str


@router.post("/auth/token")
async def token(req: TokenRequest):
    with get_session() as s:
        row = s.execute(text(
            "SELECT officer_id, role, name, ps_code FROM officer WHERE badge_no = :b"),
            {"b": req.badge_no}).first()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown badge number")
    return {
        "access_token": issue_token(str(row.officer_id), row.role),
        "token_type": "bearer",
        "officer": {"name": row.name, "role": row.role, "ps_code": row.ps_code},
    }


@router.get("/auth/officers")
async def officers():
    """Demo helper: the badge numbers available to sign in with, one per role."""
    with get_session() as s:
        rows = s.execute(text(
            "SELECT DISTINCT ON (role) badge_no, name, role, ps_code "
            "FROM officer ORDER BY role, badge_no")).mappings().all()
    return [dict(r) for r in rows]
