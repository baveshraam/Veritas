"""The three RBAC rules, plus the role hierarchy. Pure functions over strings.

Enforced in two places (apps/api middleware on structured responses; rag_agent
Cypher/SQL agents at query-construction time) — see packages/policy/README.md.
"""
from typing import Any

# Rank drives the "below DSP" masking and depth rules. SCRB_Analyst is a
# state-bureau analyst and needs full visibility for cross-jurisdiction analysis,
# so it ranks alongside SP.
ROLE_RANK: dict[str, int] = {
    "IO": 1,
    "SHO": 2,
    "DSP": 3,
    "SP": 4,
    "SCRB_Analyst": 4,
    "IG": 5,
}

_DSP_RANK = ROLE_RANK["DSP"]

# Victim-identifying fields nulled below DSP rank. Operational fields
# (person_id, scrb_id, risk_score, criminal_history) stay visible.
_VICTIM_IDENTITY_FIELDS = ("name_en", "name_kn", "dob", "address_geom", "aadhaar_hash")


def _rank(officer_role: str) -> int:
    # Unknown role -> lowest privilege, never highest (fail closed).
    return ROLE_RANK.get(officer_role, 0)


def can_view_fir(officer_role: str, officer_ps_code: str, fir_ps_code: str) -> bool:
    """IO sees only FIRs filed at their own PS; every other role is cross-PS."""
    if officer_role == "IO":
        return officer_ps_code == fir_ps_code
    return officer_role in ROLE_RANK


def mask_person_fields(officer_role: str, person: dict) -> dict:
    """Copy with victim-identifying fields nulled below DSP rank."""
    if _rank(officer_role) >= _DSP_RANK:
        return dict(person)
    masked: dict[str, Any] = dict(person)
    for field in _VICTIM_IDENTITY_FIELDS:
        if field in masked:
            masked[field] = None
    return masked


def max_traversal_depth(officer_role: str) -> int:
    """IO/SHO capped at 2 hops; DSP and above get 4 (matches TRANSFERRED_TO*1..4)."""
    return 4 if _rank(officer_role) >= _DSP_RANK else 2
