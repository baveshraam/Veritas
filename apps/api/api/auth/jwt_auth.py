"""JWT verification. The officer's identity and role come from the token, only.

`officer_id` and `officer_role` are NEVER read from a request body or query string —
if they were, any caller could name themselves IG and read the whole state's records.
The body is data; the token is authority.

The signing secret is read from the environment. There is no default in production:
a fallback secret is a backdoor, so the app refuses to start without one unless it
is explicitly in dev mode.
"""
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from policy import ROLE_RANK

ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=12)

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    secret = os.getenv("VERITAS_JWT_SECRET", "").strip()
    if secret:
        return secret
    if os.getenv("VERITAS_DEV_MODE", "").lower() in ("1", "true", "yes"):
        return "veritas-dev-only-not-for-production"
    raise RuntimeError(
        "VERITAS_JWT_SECRET is not set. Refusing to sign or verify tokens with a "
        "default secret — set the variable, or set VERITAS_DEV_MODE=1 locally."
    )


@dataclass(frozen=True)
class Officer:
    officer_id: str
    role: str
    ps_code: str
    district_code: str
    badge_no: str
    name: str


def issue_token(officer_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": officer_id, "role": role, "iat": now, "exp": now + TOKEN_TTL},
        _secret(), algorithm=ALGORITHM,
    )


def _load_officer(officer_id: str, claimed_role: str) -> Officer:
    """Resolve ps_code/role from the officer table — the token says who you are, the
    database says what you are. A token whose role no longer matches the record is
    rejected rather than trusted."""
    from data.db import get_session
    from sqlalchemy import text

    with get_session() as s:
        row = s.execute(text(
            "SELECT officer_id, role, ps_code, district_code, badge_no, name "
            "FROM officer WHERE officer_id = CAST(:o AS uuid)"), {"o": officer_id}).first()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown officer")
    if row.role != claimed_role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token role does not match record")
    return Officer(str(row.officer_id), row.role, row.ps_code or "",
                   row.district_code or "", row.badge_no or "", row.name or "")


async def current_officer(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Officer:
    # Catalyst Authentication is the identity provider wherever a Catalyst project is
    # configured (i.e. every deployed environment). The self-signed JWT below is the
    # local/offline path only — it is what the test-suite and `docker compose up`
    # run against, and it is why the secret still refuses to default in production.
    from .catalyst_auth import current_officer_catalyst, enabled
    if enabled():
        return await current_officer_catalyst(request)

    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = jwt.decode(creds.credentials, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    officer_id, role = claims.get("sub"), claims.get("role")
    if not officer_id or role not in ROLE_RANK:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing sub/role")
    return _load_officer(officer_id, role)
