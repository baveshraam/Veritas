"""SQL Agent — relational + geospatial retrieval, policy-filtered at construction.

Templates are parameterised (never string-formatted with user input), and the IO
PS-scope restriction is applied as a WHERE clause *inside* the query rather than by
dropping rows afterwards — an IO must never have another station's FIRs pulled into
the context that a free-text answer is generated from.
"""
from datetime import date
from typing import Optional

from data.db import get_session
from policy import can_view_fir
from sqlalchemy import text

_FIR_COLUMNS = (
    "f.fir_id, f.fir_number, f.crime_type, f.ipc_sections, f.date_filed, "
    "f.district, f.taluk, f.ps_code, f.case_status, f.modus_operandi, f.narrative"
)


def _ps_scope(officer_role: str, officer_ps_code: str) -> tuple[str, dict]:
    """IO sees only their own station's FIRs — enforced in the query, not after it."""
    if officer_role == "IO" and officer_ps_code:
        return " AND f.ps_code = :ps ", {"ps": officer_ps_code}
    return "", {}


def fir_by_id(fir_id: str, officer_role: str, officer_ps_code: str) -> list[dict]:
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    with get_session() as s:
        rows = s.execute(text(
            f"SELECT {_FIR_COLUMNS} FROM fir f WHERE f.fir_id = CAST(:fid AS uuid) {scope}"
        ), {"fid": fir_id, **extra}).mappings().all()
    return [dict(r) for r in rows]


def fir_by_number(fir_number: str, officer_role: str, officer_ps_code: str) -> list[dict]:
    """Lookup by the human-facing number ("0112/2026") — what officers actually type."""
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    with get_session() as s:
        rows = s.execute(text(
            f"SELECT {_FIR_COLUMNS} FROM fir f WHERE f.fir_number = :n {scope}"
        ), {"n": fir_number, **extra}).mappings().all()
    return [dict(r) for r in rows]


def search_firs(officer_role: str, officer_ps_code: str,
                crime_type: Optional[str] = None, district: Optional[str] = None,
                date_from: Optional[date] = None, date_to: Optional[date] = None,
                limit: int = 25) -> list[dict]:
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = [], {"limit": limit, **extra}
    if crime_type:
        clauses.append("AND lower(f.crime_type) LIKE lower(:ct)")
        params["ct"] = f"%{crime_type}%"
    if district:
        clauses.append("AND lower(f.district) LIKE lower(:d)")
        params["d"] = f"%{district}%"
    if date_from:
        clauses.append("AND f.date_filed >= :d0")
        params["d0"] = date_from
    if date_to:
        clauses.append("AND f.date_filed < :d1")
        params["d1"] = date_to

    with get_session() as s:
        rows = s.execute(text(
            f"SELECT {_FIR_COLUMNS} FROM fir f WHERE TRUE {scope} {' '.join(clauses)} "
            f"ORDER BY f.date_filed DESC LIMIT :limit"
        ), params).mappings().all()
    return [dict(r) for r in rows]


def person_record(person_id: str) -> list[dict]:
    """Criminal record rows for a person, joined to their FIRs."""
    with get_session() as s:
        rows = s.execute(text(
            "SELECT f.fir_id, f.fir_number, f.crime_type, f.date_filed, f.district, "
            "       f.case_status, cr.role, cr.arrest_date, cr.bail_status, cr.conviction "
            "FROM criminal_record cr JOIN fir f ON f.fir_id = cr.fir_id "
            "WHERE cr.person_id = CAST(:pid AS uuid) ORDER BY f.date_filed DESC LIMIT 50"
        ), {"pid": person_id}).mappings().all()
    return [dict(r) for r in rows]


def person_by_name(name: str) -> list[dict]:
    """Name matches ranked by how much record there is behind them.

    Indian name collisions are common and this database has them by design (four
    distinct people named "Umesh Reddy"). Returning them in arbitrary order and
    letting the caller take the first is how a query about a prolific offender ends
    up resolved to a namesake with no record at all — which then looks like the
    system has no data on him. Rank by record count so the subject of an
    investigative question is the one who actually has a history.
    """
    with get_session() as s:
        rows = s.execute(text(
            "SELECT p.person_id, p.scrb_id, p.name_en, p.dob, p.gender, "
            "       p.gang_affiliation, p.criminal_history, p.canonical_entity_id, "
            "       count(cr.record_id) AS record_count "
            "FROM person p LEFT JOIN criminal_record cr ON cr.person_id = p.person_id "
            "WHERE lower(p.name_en) LIKE lower(:n) "
            "GROUP BY p.person_id "
            "ORDER BY record_count DESC, p.name_en LIMIT 5"
        ), {"n": f"%{name}%"}).mappings().all()
    return [dict(r) for r in rows]


def crime_counts_by_district(limit: int = 10) -> list[dict]:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT district, district_code, count(*) AS fir_count FROM fir "
            "GROUP BY 1, 2 ORDER BY fir_count DESC LIMIT :limit"
        ), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def filter_viewable(rows: list[dict], officer_role: str, officer_ps_code: str) -> list[dict]:
    """Belt-and-braces for rows that didn't come from a scoped template."""
    return [r for r in rows
            if "ps_code" not in r or can_view_fir(officer_role, officer_ps_code, r["ps_code"])]


def fir_points(district_code: str, limit: int = 600) -> list[dict]:
    """FIR coordinates for the map layer. The hotspot polygons alone show WHERE the
    clusters are but not how dense the surrounding activity is — the point scatter
    is what makes a cluster legible as a cluster rather than an arbitrary shape."""
    with get_session() as s:
        rows = s.execute(text(
            "SELECT fir_id, latitude AS lat, longitude AS lng "
            "FROM fir WHERE district_code = :dc AND latitude IS NOT NULL "
            "ORDER BY date_filed DESC LIMIT :limit"
        ), {"dc": district_code, "limit": limit}).mappings().all()
    return [{"fir_id": str(r["fir_id"]), "lat": r["lat"], "lng": r["lng"]} for r in rows]
