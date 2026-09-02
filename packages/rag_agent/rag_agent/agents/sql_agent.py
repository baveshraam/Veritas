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


def crime_heads_for_section(section: str) -> list[int]:
    """The MAJOR crime-head ids an IPC section is registered under.

    The organizers' ER attaches sections to a crime head, not to a case
    (`CrimeHeadActSection`), and that head is the MAJOR head — `CaseMaster`'s
    `CrimeMajorHeadID`, not the `CrimeMinorHeadID` that names the offence type. Joining
    the minor head instead looks plausible and is wrong: section 379 resolved to head 2,
    and CrimeSubHeadID 2 is "Hurt", so "show me cases under 379" returned assault cases.
    Caught by reading the crime types back out of the result rather than trusting the
    count beside them.

    The consequence is a real limit and callers must state it: a major head groups
    several offence types (379/380 and 454/457 share one), so this selects the offence
    GROUP that carries the section, not only the offence type that names it. That is
    what the schema records; narrowing further would mean parsing section numbers out of
    narrative prose, which is not a filter, it is a guess.
    """
    rows = ds.query(
        'SELECT "CrimeHeadID" FROM "CrimeHeadActSection" WHERE "SectionCode" = :s',
        {"s": str(section).strip()})
    return sorted({int(r["CrimeHeadID"]) for r in rows})


def section_scope_note(section: str) -> Optional[str]:
    """What a section filter actually selected, in the officer's terms — the honest
    caption for the limit `crime_heads_for_section` documents."""
    heads = crime_heads_for_section(section)
    if not heads:
        return (f"No offence in these records is registered under section {section}, "
                f"so nothing matched.")
    names = ds.query(
        'SELECT "CrimeHeadName" FROM "CrimeSubHead" WHERE "CrimeHeadID" IN :h',
        {"h": heads})
    kinds = sorted({r["CrimeHeadName"] for r in names if r.get("CrimeHeadName")})
    if not kinds:
        return None
    return (f"Section {section} is registered against the offence group covering "
            f"{', '.join(kinds)}; these are that group's cases.")


def _filters(crime_type: Optional[str], district: Optional[str],
             date_from: Optional[date], date_to: Optional[date],
             case_status: Optional[str], ps_code: Optional[str],
             section: Optional[str]) -> tuple[list[str], dict]:
    """One WHERE-clause builder for both the search and the count.

    They were two copies of the same four clauses, and every filter added to one and
    not the other is a count that does not describe the list printed under it — the
    most quietly wrong thing this layer can produce. Status, station and section were
    added here rather than to either caller.
    """
    clauses: list[str] = []
    params: dict = {}
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
    if case_status:
        clauses.append('AND "CaseStatusMaster"."CaseStatusName" LIKE :st')
        params["st"] = f"%{case_status}%"
    if ps_code:
        clauses.append('AND "CaseMaster"."PoliceStationID" = :psf')
        params["psf"] = int(ps_code)
    if section:
        heads = crime_heads_for_section(section)
        # No head carries this section: the honest filter is one that matches nothing,
        # not one that is silently dropped and answers about every case instead.
        clauses.append('AND "CaseMaster"."CrimeMajorHeadID" IN :heads')
        params["heads"] = heads or [-1]
    return clauses, params


# Every JOIN the filters above can reference. `count_firs` used to omit
# CaseStatusMaster, which is fine until a status filter exists — then the count and the
# list it captions come from different queries. Both use this now.
_FILTERED_FROM = (
    ' FROM "CaseMaster" '
    'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
    'JOIN "District" ON "Unit"."DistrictID" = "District"."DistrictID" '
    'LEFT JOIN "CrimeSubHead" '
    '  ON "CaseMaster"."CrimeMinorHeadID" = "CrimeSubHead"."CrimeSubHeadID" '
    'LEFT JOIN "CaseStatusMaster" '
    '  ON "CaseMaster"."CaseStatusID" = "CaseStatusMaster"."CaseStatusID" '
)
_COUNT_FROM = 'SELECT "CaseMaster"."CaseMasterID"' + _FILTERED_FROM
_STATUS_FROM = 'SELECT "CaseStatusMaster"."CaseStatusName"' + _FILTERED_FROM


def search_firs(officer_role: str, officer_ps_code: str,
                crime_type: Optional[str] = None, district: Optional[str] = None,
                date_from: Optional[date] = None, date_to: Optional[date] = None,
                case_status: Optional[str] = None, ps_code: Optional[str] = None,
                section: Optional[str] = None, limit: int = 25) -> list[dict]:
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = _filters(crime_type, district, date_from, date_to,
                               case_status, ps_code, section)
    params.update(limit=limit, **extra)
    rows = ds.query(
        f'{_CASE_SELECT} WHERE "CaseMaster"."CaseMasterID" > 0 {scope} {" ".join(clauses)} '
        f'ORDER BY "CaseMaster"."CrimeRegisteredDate" DESC LIMIT :limit', params)
    return [_case(r) for r in rows]


def count_firs(officer_role: str, officer_ps_code: str,
               crime_type: Optional[str] = None, district: Optional[str] = None,
               date_from: Optional[date] = None, date_to: Optional[date] = None,
               case_status: Optional[str] = None, ps_code: Optional[str] = None,
               section: Optional[str] = None) -> int:
    """The exact count for a "how many X cases in Y" question — ZCQL has no GROUP BY
    over a join this deep, so this counts rows in Python over the same scoped WHERE
    clause search_firs uses, rather than approximating from a sample page."""
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = _filters(crime_type, district, date_from, date_to,
                               case_status, ps_code, section)
    params.update(extra)
    rows = ds.query(
        f'{_COUNT_FROM} WHERE "CaseMaster"."CaseMasterID" > 0 {scope} {" ".join(clauses)}',
        params)
    return len(rows)


def status_breakdown(officer_role: str, officer_ps_code: str,
                     crime_type: Optional[str] = None,
                     district: Optional[str] = None) -> dict[str, int]:
    """How the matching cases are distributed across CaseStatusName.

    This is what "how many are pending", "what is the conviction rate" and "how many
    were solved" all actually need, and none of them had anywhere to go: each fell to
    CRIME_SEARCH, which dropped the word it turned on and answered with a count of
    every case in scope. Counted in Python for the same reason count_firs is — ZCQL has
    no GROUP BY over a join this deep.
    """
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = _filters(crime_type, district, None, None, None, None, None)
    params.update(extra)
    rows = ds.query(
        f'{_STATUS_FROM} WHERE "CaseMaster"."CaseMasterID" > 0 {scope} '
        f'{" ".join(clauses)}', params)
    out: dict[str, int] = {}
    for r in rows:
        name = r.get("CaseStatusName") or "not recorded"
        out[name] = out.get(name, 0) + 1
    return out


def ranked_offenders(officer_role: str, officer_ps_code: str,
                     district: Optional[str] = None, crime_type: Optional[str] = None,
                     habitual_only: bool = False, limit: int = 5,
                     q: Optional[str] = None) -> list[dict]:
    """The people with the most cases on record, within this officer's scope.

    "Who is the most active offender in Mandya?" and "top 5 habitual offenders" are the
    first questions an officer asks and had no home at all — both fell to CRIME_SEARCH
    and were answered with a count of every case in scope plus five arbitrary FIRs.
    They are answerable, and this is the payoff of the identity layer: the organizers'
    ER has no cross-case person (CLAUDE.md §0), so "how many cases has this man been
    accused in" is a question that only exists because Fellegi-Sunter reconstructed him.

    Ranked by CASE COUNT, not by PageRank or RiskScore. Case count is a fact the
    records state; the other two are derived and modelled, and neither means "most
    active" — putting a model's ranking under that question would be exactly the
    category error this platform works to avoid. Scope is applied by counting only the
    cases the officer may see, so an IO's "most active" is their station's, and the
    same query at IG rank returns the state's.

    `q`, if given, is a name search over the FULL scoped set, applied before `limit`
    slices it — a specific person can be well outside the top N by case count (most
    offenders are, by definition) and still needs to be findable. A ranked top-N view
    and a search are different operations sharing one function, not one operation with
    a bigger page size.
    """
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = _filters(crime_type, district, None, None, None, None, None)
    params.update(extra)
    rows = ds.query(
        'SELECT "vx_accused_identity"."PersonUID", "CaseMaster"."CaseMasterID"'
        + _FILTERED_FROM.replace(
            'FROM "CaseMaster" ',
            'FROM "CaseMaster" '
            'JOIN "Accused" ON "Accused"."CaseMasterID" = "CaseMaster"."CaseMasterID" '
            'JOIN "vx_accused_identity" '
            '  ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID" ',
            1)
        + f'WHERE "CaseMaster"."CaseMasterID" > 0 {scope} {" ".join(clauses)}', params)

    counts: dict[str, set] = {}
    for r in rows:
        counts.setdefault(str(r["PersonUID"]), set()).add(str(r["CaseMasterID"]))
    if not counts:
        return []

    people = ds.query(
        'SELECT "PersonUID", "CanonicalName", "IsHabitualOffender", "CommunityID" '
        'FROM "vx_person" WHERE "PersonUID" IN :ids',
        {"ids": [int(p) for p in counts]})
    out = [{"person_id": str(p["PersonUID"]), "name": p["CanonicalName"],
            "cases": len(counts[str(p["PersonUID"])]),
            "habitual": bool(p["IsHabitualOffender"]),
            "community": p["CommunityID"]}
           for p in people]
    if habitual_only:
        out = [p for p in out if p["habitual"]]
    if q:
        needle = q.strip().lower()
        out = [p for p in out if needle in (p["name"] or "").lower()]
    return sorted(out, key=lambda p: (-p["cases"], p["name"] or ""))[:limit]


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


def _grouped_counts(officer_role: str, officer_ps_code: str, column: str,
                    crime_type: Optional[str] = None, district: Optional[str] = None,
                    case_status: Optional[str] = None) -> dict[str, int]:
    """Counts of matching cases grouped by one already-joined column.

    ZCQL has no GROUP BY over a join this deep, so the group is counted in Python over
    the same scoped WHERE clause `count_firs` uses — the same trade `count_firs` and
    `crime_counts_by_district` already make, and for the same reason. `column` is
    chosen from a fixed set by the caller, never from user text.
    """
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = _filters(crime_type, district, None, None, case_status, None, None)
    params.update(extra)
    rows = ds.query(
        f'SELECT {column}{_FILTERED_FROM} '
        f'WHERE "CaseMaster"."CaseMasterID" > 0 {scope} {" ".join(clauses)}', params)
    key = column.split(".")[-1].strip('"')
    out: dict[str, int] = {}
    for r in rows:
        name = r.get(key)
        name = "not recorded" if name is None else str(name)
        out[name] = out.get(name, 0) + 1
    return out


# The groupings a "which X has the most cases" question can ask for. A fixed table, so
# the column in the query is never assembled from anything the officer typed.
GROUPINGS = {
    "district": '"District"."DistrictName"',
    "station": '"Unit"."UnitName"',
    "crime_type": '"CrimeSubHead"."CrimeHeadName"',
    "status": '"CaseStatusMaster"."CaseStatusName"',
}


def counts_by(officer_role: str, officer_ps_code: str, grouping: str,
              crime_type: Optional[str] = None, district: Optional[str] = None,
              case_status: Optional[str] = None) -> list[tuple[str, int]]:
    """`[(name, cases)]`, commonest first — the answer to "which district/station/
    offence has the most", within this officer's own scope."""
    counts = _grouped_counts(officer_role, officer_ps_code, GROUPINGS[grouping],
                             crime_type, district, case_status)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def filter_viewable(rows: list[dict], officer_role: str, officer_ps_code: str) -> list[dict]:
    """Belt-and-braces for rows that didn't come from a scoped template."""
    return [r for r in rows
            if "ps_code" not in r or can_view_fir(officer_role, officer_ps_code, r["ps_code"])]


def person_community(person_id: str) -> Optional[int]:
    """The Louvain community a person was placed in, for 'this community' when the
    question names a person already in focus rather than a community number."""
    row = ds.one('SELECT "CommunityID" FROM "vx_person" WHERE "PersonUID" = :pid',
                {"pid": int(person_id)})
    return row["CommunityID"] if row and row.get("CommunityID") is not None else None


def district_socioeconomic(district_name: str) -> Optional[dict]:
    """The one real (non-synthetic) table in the schema, keyed to a district by name —
    Census 2011 ground truth for an Area Profile to sit next to the recorded crime mix.
    Two simple queries rather than one join: `District` and `vx_district_socioeconomic`
    are both tiny reference tables, and a join buys nothing a Python dict lookup doesn't
    already give for free."""
    d = ds.one('SELECT "DistrictID" FROM "District" WHERE "DistrictName" LIKE :d',
              {"d": f"%{district_name}%"})
    if not d:
        return None
    row = ds.one('SELECT "Population", "LiteracyRate", "UrbanRatio", "PovertyIndex", '
                '"MarginalWorkerRate", "YouthRatio" FROM "vx_district_socioeconomic" '
                'WHERE "DistrictID" = :did', {"did": d["DistrictID"]})
    return row


def flagged_transactions(officer_role: str, officer_ps_code: str, limit: int = 25) -> list[dict]:
    """Every transaction a detector has flagged, statewide, EXCEPT for an IO — the same
    "never pulled into context" rule every other query in this module enforces (see the
    module docstring). A transaction tied to a case is scoped by that case's station,
    the same way `ranked_offenders` scopes a person's case count; a transaction with no
    case link at all (pure account-to-account activity, not yet tied to an
    investigation) has no station to scope by and is visible to every rank — there is
    nothing station-specific to withhold.

    `vx_txn.FlaggedSuspicious` already carries everything a detector wrote (`Detector`,
    `FlagType`, `FlagConfidence` — CLAUDE.md §6's rule/GNN split), and it is never set
    by the generator (`data/tests/test_financial.py` enforces that), so a row here is
    always a real detector output, not a planted answer key.
    """
    scope = ""
    params: dict = {"limit": limit}
    if officer_role == "IO" and officer_ps_code:
        scope = (' AND ("vx_txn"."CaseMasterID" IS NULL OR "CaseMaster"."PoliceStationID" = :ps)')
        params["ps"] = int(officer_ps_code)
    rows = ds.query(
        'SELECT "vx_txn"."TxnID", "vx_txn"."SrcAccountID", "vx_txn"."DstAccountID", '
        '       "vx_txn"."Amount", "vx_txn"."TxnDate", "vx_txn"."CaseMasterID", '
        '       "vx_txn"."FlagType", "vx_txn"."Detector", "vx_txn"."FlagConfidence" '
        'FROM "vx_txn" '
        'LEFT JOIN "CaseMaster" ON "CaseMaster"."CaseMasterID" = "vx_txn"."CaseMasterID" '
        f'WHERE "vx_txn"."FlaggedSuspicious" = true {scope} '
        'ORDER BY "vx_txn"."FlagConfidence" DESC LIMIT :limit', params)
    return rows


def community_case_profile(person_ids: list[str], officer_role: str,
                           officer_ps_code: str) -> dict:
    """What a Louvain community's members actually have in common: their most frequent
    offence type and the total distinct cases behind the group. `gds.community_members`
    gives WHO is in the group; this is the one thing it doesn't — a community is a fact
    about the co-offending graph, not about the case records, so it never joins to
    `CaseMaster` on its own account.

    `_ps_scope` applies here exactly as it does everywhere else in this module: an IO
    asking about a community must not have another station's cases folded into the
    "most often X" figure — a community can span the whole state, and its members'
    OTHER stations' cases are exactly the "another station's cases in context" this
    module's docstring already rules out for every other query.

    Two joins (`vx_accused_identity`->`Accused`->`CaseMaster`), well under ZCQL's 4-join
    cap, then `CrimeSubHead` names are resolved as a second, join-free lookup — the same
    trade `fir_points`/`crime_counts_by_district` already make, rather than adding a
    third join for a ~20-row static table.
    """
    if not person_ids:
        return {"case_count": 0, "top_crime_type": None, "crime_mix": {}}
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    rows = ds.query(
        'SELECT DISTINCT "CaseMaster"."CaseMasterID", "CaseMaster"."CrimeMinorHeadID" '
        'FROM "vx_accused_identity" '
        'JOIN "Accused" ON "Accused"."AccusedMasterID" = "vx_accused_identity"."AccusedMasterID" '
        'JOIN "CaseMaster" ON "CaseMaster"."CaseMasterID" = "Accused"."CaseMasterID" '
        f'WHERE "vx_accused_identity"."PersonUID" IN :ids {scope}',
        {"ids": [int(p) for p in person_ids], **extra})
    crime_names = {r["CrimeSubHeadID"]: r["CrimeHeadName"]
                  for r in ds.query('SELECT "CrimeSubHeadID", "CrimeHeadName" FROM "CrimeSubHead"')}
    mix: dict[str, int] = {}
    for r in rows:
        name = crime_names.get(r.get("CrimeMinorHeadID")) or "not recorded"
        mix[name] = mix.get(name, 0) + 1
    top = max(mix.items(), key=lambda kv: kv[1])[0] if mix else None
    return {"case_count": len({r["CaseMasterID"] for r in rows}),
            "top_crime_type": top, "crime_mix": mix}


STALE_DAYS = 30  # ponytail: a fixed threshold, tune if a demo needs a different cut


def station_workload(officer_role: str, officer_ps_code: str) -> list[dict]:
    """Per-station: open caseload, average days a case has been open, and — the one
    that actually matters to a supervisor — how many of those open cases have gone
    STALE: older than `STALE_DAYS` with zero investigation-board activity. A raw open
    count says a station is busy; a stale count says a specific case is being neglected.

    `vx_case_board_item` has no per-case "last touched" summary, so staleness is a set
    difference computed in Python: which open CaseMasterIDs never appear in a board-item
    row at all. Two plain single-table-ish queries (CaseMaster+Unit+CaseStatusMaster is
    2 joins; vx_case_board_item is 0) rather than a LEFT JOIN ... IS NULL, matching this
    module's own established avoidance of ZCQL's documented live-JOIN restrictions
    between value-related tables (CLAUDE.md v8).

    RBAC via the same `_ps_scope` every other query here uses: an IO sees only their own
    station's queue (a self-check — "am I falling behind"), every other rank sees every
    station in scope, ranked by who needs backup most.
    """
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    open_cases = ds.query(
        'SELECT "CaseMaster"."CaseMasterID", "CaseMaster"."CrimeRegisteredDate", '
        '       "CaseMaster"."PoliceStationID", "Unit"."UnitName" '
        'FROM "CaseMaster" '
        'JOIN "Unit" ON "CaseMaster"."PoliceStationID" = "Unit"."UnitID" '
        'JOIN "CaseStatusMaster" ON "CaseMaster"."CaseStatusID" = "CaseStatusMaster"."CaseStatusID" '
        f'WHERE "CaseStatusMaster"."CaseStatusName" = \'Under Investigation\' {scope}',
        extra)
    if not open_cases:
        return []
    touched = {str(r["CaseMasterID"]) for r in ds.query(
        'SELECT DISTINCT "CaseMasterID" FROM "vx_case_board_item" WHERE "CaseMasterID" IN :ids',
        {"ids": [int(c["CaseMasterID"]) for c in open_cases]})}

    today = date.today()
    by_station: dict[str, dict] = {}
    for c in open_cases:
        filed = ds.to_dt(c.get("CrimeRegisteredDate"))
        age = (today - filed.date()).days if filed else 0
        key = str(c["PoliceStationID"])
        st = by_station.setdefault(key, {
            "ps_code": key, "station": c.get("UnitName") or key,
            "open_cases": 0, "age_total": 0, "stalled_ids": []})
        st["open_cases"] += 1
        st["age_total"] += age
        if age > STALE_DAYS and str(c["CaseMasterID"]) not in touched:
            st["stalled_ids"].append(str(c["CaseMasterID"]))

    out = []
    for st in by_station.values():
        out.append({
            "ps_code": st["ps_code"], "station": st["station"],
            "open_cases": st["open_cases"],
            "avg_age_days": round(st["age_total"] / st["open_cases"], 1),
            "stalled_count": len(st["stalled_ids"]),
            "stalled_ids": st["stalled_ids"][:10],
        })
    return sorted(out, key=lambda s: (-s["stalled_count"], -s["avg_age_days"]))


def fir_points(district_code: str, limit: int = 600) -> list[dict]:
    """Case coordinates for the map layer. The hotspot polygons alone show WHERE the
    clusters are but not how dense the surrounding activity is — the point scatter is what
    makes a cluster legible as a cluster rather than an arbitrary shape.

    `crime_no`/`filed`/`crime_type` ride along so the map's hover tooltip can show real
    case metadata instead of forcing an officer to click through for it. `crime_type` is a
    second, cheap, JOIN-free query — `CrimeSubHead` is a ~20-row static reference table,
    the same source `/cases` already trusts for this label (`apps/api/routers/records.py`)
    — rather than adding a JOIN to `cases_in_district`, which is shared with
    forecast/anomaly-detection callers that have no use for this column and no reason to
    pay for it. `district` is resolved once from the input code, not per row — every point
    in one call is in the same district by construction. `fir_id` stays the internal
    CaseMasterID; every citation/selection in the app already addresses a case as
    `fir:{CaseMasterID}`, and changing that here would desync map selection from the rest
    of the evidence chain.
    """
    from data.districts import canonical_name

    rows = queries.cases_in_district(queries.district_id(district_code))
    crime_names = {r["CrimeSubHeadID"]: r["CrimeHeadName"]
                  for r in ds.query('SELECT "CrimeSubHeadID", "CrimeHeadName" FROM "CrimeSubHead"')}
    district = canonical_name(district_code)
    pts = [{"fir_id": str(r["CaseMasterID"]), "lat": r["latitude"], "lng": r["longitude"],
            "crime_no": r.get("CrimeNo"), "filed": r.get("CrimeRegisteredDate"),
            "crime_type": crime_names.get(r.get("CrimeMinorHeadID")), "district": district}
           for r in rows if r["latitude"] is not None and r["longitude"] is not None]
    return pts[:limit]


def dashboard(officer_role: str, officer_ps_code: str,
              district: Optional[str] = None, crime_type: Optional[str] = None) -> dict:
    """Every count the Statistics dashboard needs, from ONE scan of the scoped case set.

    `counts_by` is the right shape for a single grouped question and the wrong shape for
    a dashboard: five groupings would be five full scans of the same rows, over a
    backend whose SELECT already pages 300 at a time. The WHERE clause and the RBAC
    scope are `_filters`/`_ps_scope` exactly as everywhere else in this module — this
    counts the same rows differently, it does not widen them.

    Every figure here is a COUNT OF RECORDS. Nothing is modelled, nothing is a rate the
    caller can mistake for a prediction; the conviction rate is computed from the same
    status breakdown printed beside it, so its denominator is always on screen.
    """
    scope, extra = _ps_scope(officer_role, officer_ps_code)
    clauses, params = _filters(crime_type, district, None, None, None, None, None)
    params.update(extra)
    rows = ds.query(
        'SELECT "CaseStatusMaster"."CaseStatusName", "CrimeSubHead"."CrimeHeadName", '
        '       "District"."DistrictName", "Unit"."UnitName", '
        '       "CaseMaster"."CrimeRegisteredDate"'
        + _FILTERED_FROM
        + f'WHERE "CaseMaster"."CaseMasterID" > 0 {scope} {" ".join(clauses)}', params)

    status: dict[str, int] = {}
    crime: dict[str, int] = {}
    dist: dict[str, int] = {}
    station: dict[str, int] = {}
    month: dict[str, int] = {}
    for r in rows:
        for bucket, key in ((status, "CaseStatusName"), (crime, "CrimeHeadName"),
                            (dist, "DistrictName"), (station, "UnitName")):
            name = r.get(key) or "not recorded"
            bucket[name] = bucket.get(name, 0) + 1
        d = ds.to_dt(r.get("CrimeRegisteredDate"))
        if d:
            m = f"{d.year:04d}-{d.month:02d}"
            month[m] = month.get(m, 0) + 1

    def ranked(b: dict[str, int]) -> list[dict]:
        return [{"name": k, "cases": v}
                for k, v in sorted(b.items(), key=lambda kv: (-kv[1], kv[0]))]

    convicted = status.get("Convicted", 0)
    decided = convicted + status.get("Acquitted", 0)
    return {
        "total": len(rows),
        "scope": {"district": district, "crime_type": crime_type},
        "status": ranked(status),
        "crime_type": ranked(crime),
        "district": ranked(dist),
        "station": ranked(station),
        # Chronological, not ranked — this one is a series, and sorting it by
        # volume would draw a trend line through a shuffled x-axis.
        "monthly": [{"name": k, "cases": month[k]} for k in sorted(month)],
        "conviction": {"convicted": convicted, "decided": decided,
                       "rate": (convicted / decided) if decided else None},
    }
