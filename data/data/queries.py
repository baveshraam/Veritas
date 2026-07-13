"""Shared reads over the organizers' ER.

The ER puts geography on the *station*, not the case: `CaseMaster.PoliceStationID` ->
`Unit.DistrictID` -> `District`. So "the cases in Kolar" is a join, and it is a join five
different callers (hotspots, forecasting, anomalies, the causal layer, the SQL agent) would
otherwise each have written slightly differently.

Everything here returns plain row dicts, aggregated in Python rather than in the query.
That is not laziness about SQL — ZCQL has no `date_trunc`, no CTEs and no correlated
subqueries, so a monthly count *cannot* be expressed server-side. The row volume is tens of
thousands, which pandas groups in milliseconds.
"""
from __future__ import annotations

from datetime import date

from . import ds


def district_id(code: str) -> int:
    """"KA07" -> the ER's DistrictID. Callers above this layer speak district codes
    (that is what an officer types); the ER speaks integer ids."""
    from .generator.refdata import district_id as _did
    return _did(code)


_CASE_COLS = ('"CaseMaster"."CaseMasterID", "CaseMaster"."CrimeNo", '
              '"CaseMaster"."CrimeRegisteredDate", "CaseMaster"."PoliceStationID", '
              '"CaseMaster"."CrimeMinorHeadID", "CaseMaster"."CaseStatusID", '
              '"CaseMaster"."latitude", "CaseMaster"."longitude"')


def cases_in_district(district_id: int,
                      date_range: tuple[date, date] | None = None) -> list[dict]:
    """Every case filed at a station in this district."""
    where = '"Unit"."DistrictID" = :did'
    params: dict = {"did": int(district_id)}
    if date_range:
        where += (' AND "CaseMaster"."CrimeRegisteredDate" >= :d_from'
                  ' AND "CaseMaster"."CrimeRegisteredDate" <= :d_to')
        params["d_from"], params["d_to"] = date_range
    return ds.query(
        f'SELECT {_CASE_COLS} FROM "CaseMaster" '
        f'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        f'WHERE {where}', params)


def case_counts_by_district() -> dict[int, int]:
    """DistrictID -> number of cases. The causal layer's outcome variable."""
    rows = ds.query('SELECT "Unit"."DistrictID" FROM "CaseMaster" '
                    'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID"')
    counts: dict[int, int] = {}
    for r in rows:
        counts[r["DistrictID"]] = counts.get(r["DistrictID"], 0) + 1
    return counts


def cases_for_person(person_uid: int) -> list[dict]:
    """Every case a resolved person is accused in — the query the ER cannot answer on its
    own, because it has no person. Goes through `vx_accused_identity`."""
    return ds.query(
        f'SELECT {_CASE_COLS} FROM "vx_accused_identity" '
        f'JOIN "Accused" '
        f'  ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        f'JOIN "CaseMaster" ON "Accused"."CaseMasterID" = "CaseMaster"."CaseMasterID" '
        f'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        f'WHERE "vx_accused_identity"."PersonUID" = :uid',
        {"uid": int(person_uid)})


def accused_with_cases() -> list[dict]:
    """(PersonUID, CaseMasterID, CrimeRegisteredDate, DistrictID) for every accused row,
    resolved to a person. The base table for the risk and recidivism features, and for the
    fairness audit's subgroup counts."""
    return ds.query(
        'SELECT "vx_accused_identity"."PersonUID", "Accused"."CaseMasterID", '
        '       "Accused"."AgeYear", "Accused"."GenderID", '
        '       "CaseMaster"."CrimeRegisteredDate", "Unit"."DistrictID" '
        'FROM "vx_accused_identity" '
        'JOIN "Accused" '
        '  ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        'JOIN "CaseMaster" ON "Accused"."CaseMasterID" = "CaseMaster"."CaseMasterID" '
        'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID"')


def latest_case_date() -> date | None:
    """The dataset's 'today'. Feature cutoffs are relative to it, not to wall-clock time,
    or a rebuilt dataset silently changes every model's training window."""
    row = ds.one('SELECT "CrimeRegisteredDate" FROM "CaseMaster" '
                 'ORDER BY "CrimeRegisteredDate" DESC')
    if not row or not row["CrimeRegisteredDate"]:
        return None
    dt = ds.to_dt(row["CrimeRegisteredDate"])
    return dt.date() if dt else None
