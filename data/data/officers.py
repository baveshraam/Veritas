"""Officer lookup — the record layer's answer to "who is this, and what may they see".

Catalyst Authentication says *who signed in*. It does not know that this person is an
Investigating Officer at station 412, and it must not: role and station are police facts,
they live in the ER's `Employee` row, and `packages/policy` reads them from there. An
identity that Catalyst authenticates but `Employee` does not know is not an officer.

`Employee` has no email (the ER declares none, and we do not add columns to it), so the
bridge from a Catalyst identity to an employee record is `vx_officer_identity`.
"""
from __future__ import annotations

from typing import NamedTuple

from . import ds
from .generator.refdata import DESIGNATION_TO_ROLE


class OfficerRecord(NamedTuple):
    officer_id: str          # EmployeeID
    role: str                # IG | SP | DSP | SHO | IO | SCRB_Analyst
    ps_code: str             # UnitID — the station, which is what an IO is scoped to
    district_code: str       # DistrictID
    badge_no: str            # KGID
    name: str


_SELECT = ('SELECT "EmployeeID", "DesignationID", "UnitID", "DistrictID", "KGID", '
           '"FirstName" FROM "Employee" ')


def _record(row: dict) -> OfficerRecord:
    return OfficerRecord(
        officer_id=str(row["EmployeeID"]),
        # int(): the live Data Store returns every column as a string ("4"), sqlite as an
        # int — an uncoerced .get() silently made every deployed officer an IO.
        role=DESIGNATION_TO_ROLE.get(int(row["DesignationID"] or 0), "IO"),
        ps_code=str(row["UnitID"] or ""),
        district_code=str(row["DistrictID"] or ""),
        badge_no=row["KGID"] or "",
        name=row["FirstName"] or "",
    )


def by_id(employee_id: str) -> OfficerRecord | None:
    row = ds.one(f'{_SELECT} WHERE "EmployeeID" = :e', {"e": int(employee_id)})
    return _record(row) if row else None


def by_email(email: str) -> OfficerRecord | None:
    link = ds.one('SELECT "EmployeeID" FROM "vx_officer_identity" WHERE "Email" = :e',
                  {"e": email.lower()})
    return by_id(link["EmployeeID"]) if link else None
