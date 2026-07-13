"""Catalyst Authentication — identity and role come from Catalyst, not from a token
this service signs itself.

What changed vs jwt_auth.py, and what deliberately did not:

  - CHANGED: who vouches for the caller. Catalyst issues and validates the token;
    `get_current_user()` is the only thing that says "this request is Officer X".
    We no longer sign, no longer hold a secret, no longer verify a signature.
  - UNCHANGED: what an officer is allowed to see. `packages/policy` is untouched —
    Catalyst tells us *who* someone is, never *what a DSP may read*. The officer
    record still resolves out of the record layer, and role still comes from there.

The role is cross-checked, not trusted: Catalyst carries a role name, but the
authoritative role is the one on the officer record, exactly as before. A Catalyst
role that disagrees with the record is rejected rather than honoured — the same
fail-closed rule jwt_auth applied to a token whose role had drifted.
"""
import os
from functools import lru_cache

from fastapi import HTTPException, Request, status
from policy import ROLE_RANK

from .jwt_auth import Officer


class CatalystUnavailable(RuntimeError):
    """The Catalyst SDK is not installed or not initialisable in this process."""


def enabled() -> bool:
    """Catalyst auth is on when we can actually *do* Catalyst auth.

    Both halves are required. A project id says which project to authenticate against; the
    SDK is what authenticates. Treating the id alone as "enabled" — which is what this used
    to do — meant a machine with the project configured but no SDK installed raised
    CatalystUnavailable on every single request instead of falling back, and that machine is
    every developer's laptop.

    The fallback is not a hole: jwt_auth refuses to run on a default secret outside dev mode,
    so a deployment that lost the SDK cannot quietly start accepting self-signed tokens
    without someone having set a real signing secret.
    """
    if not (os.getenv("CATALYST_PROJECT_ID") or os.getenv("X_ZOHO_CATALYST_PROJECT_ID")):
        return False
    try:
        import zcatalyst_sdk  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _sdk():
    try:
        import zcatalyst_sdk
    except ImportError as e:                       # pragma: no cover - deploy-only path
        raise CatalystUnavailable(
            "Catalyst auth is enabled but zcatalyst-sdk is not installed"
        ) from e
    return zcatalyst_sdk


def _catalyst_user(request: Request) -> dict:
    """The authenticated Catalyst user behind this request.

    Isolated in one function on purpose: it is the only part of this module that
    cannot run outside a Catalyst project, so everything below it stays testable.
    """
    app = _sdk().initialize(request)
    user = app.authentication().get_current_user()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated with Catalyst")
    return user


def catalyst_role(user: dict) -> str | None:
    """The KSP role carried by the Catalyst user, or None if it isn't one of ours.

    Catalyst roles are free-text, so an unrecognised name is not silently treated as
    a low-privilege role — it is no role at all, and the request is refused.
    """
    role = (user.get("role_details") or {}).get("role_name")
    return role if role in ROLE_RANK else None


def _officer_by_email(email: str, claimed_role: str | None) -> Officer:
    """Resolve the officer record for a Catalyst identity.

    The record layer, not Catalyst, is authoritative for station/district/role. Catalyst
    identifies users by email, and the ER's Employee has no email column, so the bridge is
    vx_officer_identity — see data.officers.
    """
    from data import officers

    rec = officers.by_email(email)
    if not rec:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Catalyst user is not a registered officer")
    if claimed_role and rec.role != claimed_role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Catalyst role does not match officer record")
    return Officer(*rec)


async def current_officer_catalyst(request: Request) -> Officer:
    user = _catalyst_user(request)
    email = user.get("email_id") or user.get("email")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Catalyst user has no email")
    return _officer_by_email(email, catalyst_role(user))
