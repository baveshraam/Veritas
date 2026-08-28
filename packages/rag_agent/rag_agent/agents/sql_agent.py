"""SQL Agent — relational + geospatial retrieval, policy-filtered at construction.

Templates are parameterised (never string-formatted with user input), and the IO
station-scope restriction is applied as a WHERE clause *inside* the query rather than by
dropping rows afterwards — an IO must never have another station's cases pulled into the
context that a free-text answer is generated from. You cannot un-read a record.

Everything here is a template. There is no LLM text-to-SQL fallback any more, and that is
not a gap left by the migration — ZCQL is a strict subset of SQL with no bind parameters,
so a model-authored query against an evidence store would be both less expressive and the
one place in the system where user text reaches the database uninterpolated. The long tail
that the old NL->Cypher generator served is now served by the graph agent's Think-on-Graph
beam search, which reasons over the graph instead of writing code against it.

The organizers' ER has no "FIR" table: a case's crime type lives in CrimeSubHead, its
station in Unit, its status in CaseStatusMaster. So the FIR *view* an officer expects is a
join, defined once here (`_CASE_SELECT`) and reused. ZCQL allows at most 4 joins; this uses
exactly 4.
"""
from datetime import date
from typing import Optional

from data import ds, queries
from policy import can_view_fir

# The case, as an investigator thinks of it. Reassembled from the ER's five tables.
_CASE_SELECT = (
    'SELECT "CaseMaster"."CaseMasterID", "CaseMaster"."CrimeNo", '
    '       "CaseMaster"."CrimeRegisteredDate", "CaseMaster"."PoliceStationID", '
    '       "CaseMaster"."BriefFacts", "CaseMaster"."latitude", "CaseMaster"."longitude", '
    '       "CrimeSubHead"."CrimeHeadName", "CaseStatusMaster"."CaseStatusName", '
    '       "Unit"."UnitName", "District"."DistrictName" '
    'FROM "CaseMaster" '
    'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
    'JOIN "District" ON "Unit"."DistrictID" = "District"."DistrictID" '
    'LEFT JOIN "CrimeSubHead" '
    '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID" '
    'LEFT JOIN "CaseStatusMaster" '
    '  ON "CaseMaster"."CaseStatusID" = "CaseStatusMaster"."CaseStatusID" '
)


def _case(r: dict) -> dict:
    """One ER row-bundle -> the flat case shape the rest of the system speaks."""
    return {
        "fir_id": str(r["CaseMasterID"]),
        "fir_number": r["CrimeNo"],
        "crime_type": r.get("CrimeHeadName"),
        "date_filed": r.get("CrimeRegisteredDate"),
        "district": r.get("DistrictName"),
        "ps_code": str(r["PoliceStationID"]),
        "ps_name": r.get("UnitName"),
        "case_status": r.get("CaseStatusName"),
        "narrative": r.get("BriefFacts"),
        "lat": r.get("latitude"),
        "lng": r.get("longitude"),
    }


def _ps_scope(officer_role: str, officer_ps_code: str) -> tuple[str, dict]:
    """An IO sees only their own station's cases — enforced in the query, not after it."""
    if officer_role == "IO" and officer_ps_code:
        return ' AND "CaseMaster"."PoliceStationID" = :ps ', {"ps": int(officer_ps_code)}
    return "", {}


def fir_by_id(fir_id: str, officer_role: str, officer_ps_code: str) -> list[dict]:
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    rows = ds.query(
        f'{_CASE_SELECT} WHERE "CaseMaster"."CaseMasterID" = :cid {scope}',
        {"cid": int(fir_id), **extra})
    return [_case(r) for r in rows]


def fir_by_number(fir_number: str, officer_role: str, officer_ps_code: str) -> list[dict]:
    """Lookup by the 18-digit CrimeNo — the number that appears on the paper FIR."""
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    rows = ds.query(f'{_CASE_SELECT} WHERE "CaseMaster"."CrimeNo" = :n {scope}',
                    {"n": fir_number, **extra})
    return [_case(r) for r in rows]


def search_firs(officer_role: str, officer_ps_code: str,
                crime_type: Optional[str] = None, district: Optional[str] = None,
                date_from: Optional[date] = None, date_to: Optional[date] = None,
                limit: int = 25) -> list[dict]:
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = [], {"limit": limit, **extra}
    if crime_type:
        clauses.append('AND "CrimeSubHead"."CrimeHeadName" LIKE :ct')
        params["ct"] = f"%{crime_type}%"
    if district:
        clauses.append('AND "District"."DistrictName" LIKE :d')
        params["d"] = f"%{district}%"
    if date_from:
        clauses.append('AND "CaseMaster"."CrimeRegisteredDate" >= :d0')
        params["d0"] = date_from
    if date_to:
        clauses.append('AND "CaseMaster"."CrimeRegisteredDate" < :d1')
        params["d1"] = date_to

    rows = ds.query(
        f'{_CASE_SELECT} WHERE "CaseMaster"."CaseMasterID" > 0 {scope} {" ".join(clauses)} '
        f'ORDER BY "CaseMaster"."CrimeRegisteredDate" DESC LIMIT :limit', params)
    return [_case(r) for r in rows]


def count_firs(officer_role: str, officer_ps_code: str,
               crime_type: Optional[str] = None, district: Optional[str] = None,
               date_from: Optional[date] = None, date_to: Optional[date] = None) -> int:
    """The exact count for a "how many X cases in Y" question — ZCQL has no GROUP BY
    over a join this deep, so this counts rows in Python over the same scoped WHERE
    clause search_firs uses, rather than approximating from a sample page."""
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = [], dict(extra)
    if crime_type:
        clauses.append('AND "CrimeSubHead"."CrimeHeadName" LIKE :ct')
        params["ct"] = f"%{crime_type}%"
    if district:
        clauses.append('AND "District"."DistrictName" LIKE :d')
        params["d"] = f"%{district}%"
    if date_from:
        clauses.append('AND "CaseMaster"."CrimeRegisteredDate" >= :d0')
        params["d0"] = date_from
    if date_to:
        clauses.append('AND "CaseMaster"."CrimeRegisteredDate" < :d1')
        params["d1"] = date_to
    rows = ds.query(
        'SELECT "CaseMaster"."CaseMasterID" FROM "CaseMaster" '
        'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        'JOIN "District" ON "Unit"."DistrictID" = "District"."DistrictID" '
        'LEFT JOIN "CrimeSubHead" '
        '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID" '
        f'WHERE "CaseMaster"."CaseMasterID" > 0 {scope} {" ".join(clauses)}', params)
    return len(rows)


def cases_by_ids(fir_ids: list[str]) -> list[dict]:
    """Fully-joined case cards (crime type, status, district — the shape `_case()` needs)
    for a caller that already resolved a list of CaseMasterIDs some other way.

    Exists because ZCQL caps joins at 4, and `_CASE_SELECT` already spends all 4 getting
    from `CaseMaster` to `District`/`CrimeSubHead`/`CaseStatusMaster`. A caller whose own
    lookup already used up its join budget getting to a case id (e.g. `person_record`,
    via `vx_accused_identity` -> `Accused` -> `CaseMaster` -> `Unit`) can't add three more
    joins to the same query — it fetches ids there, then the descriptive fields here, as
    two queries each within the cap rather than one query over it.
    """
    if not fir_ids:
        return []
    rows = ds.query(f'{_CASE_SELECT} WHERE "CaseMaster"."CaseMasterID" IN :ids',
                    {"ids": [int(i) for i in fir_ids]})
    return [_case(r) for r in rows]


def accused_on_case(fir_id: str) -> list[dict]:
    """The people accused on this case, resolved to their cross-case identity.

    Unscoped by station — the caller must confirm access to `fir_id` itself first
    (e.g. via a scoped `fir_by_id`/`fir_by_number` call), the same discipline
    `copilot.brief.generate_copilot_brief` already applies before reading this.
    """
    return ds.query(
        'SELECT "vx_person"."PersonUID", "vx_person"."CanonicalName", '
        '       "vx_person"."CommunityID", "vx_person"."GangAffiliation", '
        '       "vx_person"."PageRank", "Accused"."AccusedName" '
        'FROM "Accused" '
        'JOIN "vx_accused_identity" '
        '  ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID" '
        'JOIN "vx_person" '
        '  ON "vx_accused_identity"."PersonUID" = "vx_person"."PersonUID" '
        'WHERE "Accused"."CaseMasterID" = :cid', {"cid": int(fir_id)})


def person_record(person_id: str) -> list[dict]:
    """Every case a person is accused in — the question the ER cannot answer by itself.

    `Accused` rows are per-case; nothing in the organizers' schema says two of them are the
    same man. This goes through `vx_accused_identity`, which is what Fellegi-Sunter
    reconstructed, so "does he have priors" has an answer at all.

    BUG-028: this used to run `_case()` straight over `queries.cases_for_person()`'s own
    rows, which carry only `CrimeMinorHeadID`/`CaseStatusID` (raw foreign keys) — that
    query's own join budget is already spent reaching `vx_accused_identity` ->
    `Accused` -> `CaseMaster` -> `Unit`, with no room left for the three more joins
    `_case()` actually needs. Every "does X have priors" answer rendered "crime type not
    recorded" / "status not recorded" for every case, live, in production. Fixed by
    fetching ids first, then the fully-joined cards via `cases_by_ids` above.
    """
    ids = [str(r["CaseMasterID"]) for r in queries.cases_for_person(int(person_id))]
    return cases_by_ids(ids)


def person_name(person_id: str) -> Optional[str]:
    """The reverse of person_by_name — a display label for an already-resolved id,
    e.g. tagging each half of a bounded multi-step comparison's evidence."""
    row = ds.one('SELECT "CanonicalName" FROM "vx_person" WHERE "PersonUID" = :pid',
                 {"pid": int(person_id)})
    return row["CanonicalName"] if row else None


def person_by_name(name: str) -> list[dict]:
    """Name matches, ranked by how much record there is behind them.

    Indian name collisions are common and this data has them by design. Returning matches in
    arbitrary order and letting the caller take the first is how a question about a prolific
    offender gets resolved to a namesake with no record — which then looks like the system
    has no data on him. Rank by record count, so the subject of an investigative question is
    the one who actually has a history.
    """
    people = ds.query(
        'SELECT "PersonUID", "CanonicalName", "DOB", "GenderID", "GangAffiliation", '
        '"IsHabitualOffender", "RiskScore" FROM "vx_person" '
        'WHERE "CanonicalName" LIKE :n LIMIT 25', {"n": f"%{name}%"})
    if not people:
        return []

    counts = {r["PersonUID"]: 0 for r in people}
    for r in ds.query('SELECT "PersonUID" FROM "vx_accused_identity" '
                      'WHERE "PersonUID" IN :ids', {"ids": list(counts)}):
        counts[r["PersonUID"]] = counts.get(r["PersonUID"], 0) + 1

    for p in people:
        p["record_count"] = counts.get(p["PersonUID"], 0)
        p["person_id"] = str(p["PersonUID"])
        p["name_en"] = p["CanonicalName"]
    people.sort(key=lambda p: (-p["record_count"], p["name_en"] or ""))
    return people[:5]


def crime_counts_by_district(limit: int = 10) -> list[dict]:
    """Counted here, not in the query — ZCQL has no GROUP BY over a join this deep."""
    names = {r["DistrictID"]: r["DistrictName"]
             for r in ds.query('SELECT "DistrictID", "DistrictName" FROM "District"')}
    counts = queries.case_counts_by_district()
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    # The ER stores an integer DistrictID; every caller above this layer — and every
    # model behind it — speaks the canonical KAnn code, which they parse with
    # int(code[2:]). Emitting the raw id here made that int('') and failed the turn.
    return [{"district": names.get(did, str(did)), "district_code": f"KA{int(did):02d}",
             "fir_count": n} for did, n in ranked]


def filter_viewable(rows: list[dict], officer_role: str, officer_ps_code: str) -> list[dict]:
    """Belt-and-braces for rows that didn't come from a scoped template."""
    return [r for r in rows
            if "ps_code" not in r or can_view_fir(officer_role, officer_ps_code, r["ps_code"])]


def fir_points(district_code: str, limit: int = 600) -> list[dict]:
    """Case coordinates for the map layer. The hotspot polygons alone show WHERE the
    clusters are but not how dense the surrounding activity is — the point scatter is what
    makes a cluster legible as a cluster rather than an arbitrary shape."""
    rows = queries.cases_in_district(queries.district_id(district_code))
    pts = [{"fir_id": str(r["CaseMasterID"]), "lat": r["latitude"], "lng": r["longitude"]}
           for r in rows if r["latitude"] is not None and r["longitude"] is not None]
    return pts[:limit]
