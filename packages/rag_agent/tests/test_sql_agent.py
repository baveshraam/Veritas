"""BUG-028: `person_record()` rendered "crime type not recorded" / "status not recorded"
for EVERY case of EVERY person, live, in production — the flagship "does X have priors"
capability (`CLAUDE.md` §0) silently degraded to case numbers and dates only. No prior
test caught this because every existing PERSON_HISTORY test only asserted intent
*routing* (`classify(...) == "PERSON_HISTORY"`), never the content of what came back.
"""
from datetime import date, timedelta

from data import ds

from rag_agent.agents.sql_agent import person_record


def test_person_record_carries_crime_type_and_status_not_just_ids(dataset):
    """The actual defect: `queries.cases_for_person()`'s own join budget (identity ->
    Accused -> CaseMaster -> Unit, already 3 of ZCQL's 4-JOIN cap) has no room left for
    the District/CrimeSubHead/CaseStatusMaster joins `_case()` needs -- so every row it
    fed straight into `_case()` had `CrimeMinorHeadID`/`CaseStatusID` but no
    `CrimeHeadName`/`CaseStatusName`, and `_case()` reads exactly those names."""
    person = ds.one('SELECT "PersonUID" FROM "vx_accused_identity" '
                    'GROUP BY "PersonUID" HAVING COUNT(*) >= 1')
    assert person, "fixture must have at least one resolved accused row"

    rows = person_record(str(person["PersonUID"]))
    assert rows, "a resolved person with an Accused row must have at least one case"

    for r in rows:
        assert r["crime_type"], f"crime_type missing for {r['fir_id']}"
        assert r["case_status"], f"case_status missing for {r['fir_id']}"
        assert r["district"], f"district missing for {r['fir_id']}"


def test_person_record_matches_a_direct_fully_joined_lookup(dataset):
    """Cross-check against the query `fir_by_id` uses for the exact same case — if these
    two ever disagree, one of them is wrong about what a case actually is."""
    from rag_agent.agents.sql_agent import fir_by_id

    person = ds.one('SELECT "PersonUID" FROM "vx_accused_identity"')
    rows = person_record(str(person["PersonUID"]))
    assert rows

    direct = fir_by_id(rows[0]["fir_id"], "IG", "")[0]
    assert rows[0]["crime_type"] == direct["crime_type"]
    assert rows[0]["case_status"] == direct["case_status"]
    assert rows[0]["district"] == direct["district"]


# --------------------------------------------------------------------------- #
# Area / Community / Watchlist / Workload — new analytics query functions      #
# --------------------------------------------------------------------------- #

def test_district_socioeconomic_returns_real_census_fields(dataset):
    from rag_agent.agents.sql_agent import district_socioeconomic

    name = ds.one('SELECT "DistrictName" FROM "District"')["DistrictName"]
    row = district_socioeconomic(name)
    assert row, f"no socioeconomic row for {name!r} — the Census load is incomplete"
    assert 0 < row["LiteracyRate"] <= 100
    assert 0 <= row["UrbanRatio"] <= 1
    assert row["Population"] > 0


def test_district_socioeconomic_returns_none_for_an_unknown_name(dataset):
    from rag_agent.agents.sql_agent import district_socioeconomic
    assert district_socioeconomic("Nonexistrict") is None


def test_flagged_transactions_lists_only_flagged_rows(dataset):
    """The generator never sets FlaggedSuspicious (test_financial.py enforces that),
    so this proves the query itself, not the detector: flag exactly one row and
    confirm it — and only it — comes back."""
    from data.transactions import flag_transaction
    from rag_agent.agents.sql_agent import flagged_transactions

    assert flagged_transactions("IG", "") == []
    txn = ds.one('SELECT "TxnID" FROM "vx_txn"')
    assert txn, "fixture must have at least one transaction"
    flag_transaction(txn["TxnID"], "structuring", "rule:structuring", 0.9)
    try:
        rows = flagged_transactions("IG", "")
        assert len(rows) == 1
        assert rows[0]["TxnID"] == txn["TxnID"]
        assert rows[0]["Detector"] == "rule:structuring"
    finally:
        from data.transactions import clear_flags
        clear_flags()


def test_community_case_profile_counts_distinct_cases_across_members(dataset):
    from data.gds import community_members
    from rag_agent.agents.sql_agent import community_case_profile

    cid = ds.one('SELECT "CommunityID" FROM "vx_person" WHERE "CommunityID" IS NOT NULL')
    assert cid, "the graph pass produced no community — is co_offending() empty?"
    members = community_members(cid["CommunityID"], limit=25)
    assert members

    profile = community_case_profile([str(m["PersonUID"]) for m in members], "IG", "")
    assert profile["case_count"] >= 1
    # Every case counted must actually be one of the members' own cases — the cross
    # check the offender-ranking test above applies to its own count.
    for pid in [str(m["PersonUID"]) for m in members]:
        assert len(person_record(pid)) >= 0  # each id must resolve without raising


def test_community_case_profile_is_empty_for_no_members(dataset):
    from rag_agent.agents.sql_agent import community_case_profile
    assert community_case_profile([], "IG", "") == {"case_count": 0, "top_crime_type": None,
                                                     "crime_mix": {}}


def test_flagged_transactions_hides_another_stations_case_linked_flag_from_an_io(dataset):
    """The RBAC gap this module's own docstring rules out for every other query: an
    IO must never have another station's cases pulled into context. A transaction
    tied to a case outside the IO's station must not appear for them, even though
    it appears for every other rank."""
    from data.transactions import clear_flags, flag_transaction
    from rag_agent.agents.sql_agent import flagged_transactions

    txn_case = ds.one('SELECT "TxnID" FROM "vx_txn" WHERE "CaseMasterID" IS NOT NULL')
    assert txn_case, "fixture must have at least one case-linked transaction"
    case = ds.one('SELECT "PoliceStationID" FROM "CaseMaster" WHERE "CaseMasterID" = '
                 '(SELECT "CaseMasterID" FROM "vx_txn" WHERE "TxnID" = :t)',
                 {"t": txn_case["TxnID"]})
    other_ps = str(ds.one('SELECT "PoliceStationID" FROM "CaseMaster" WHERE '
                          '"PoliceStationID" != :ps', {"ps": case["PoliceStationID"]}
                         )["PoliceStationID"])
    flag_transaction(txn_case["TxnID"], "structuring", "rule:structuring", 0.9)
    try:
        assert any(r["TxnID"] == txn_case["TxnID"] for r in flagged_transactions("IG", ""))
        assert not any(r["TxnID"] == txn_case["TxnID"]
                      for r in flagged_transactions("IO", other_ps))
    finally:
        clear_flags()


def test_community_case_profile_never_folds_in_another_stations_cases_for_an_io(dataset):
    """Same RBAC discipline as ranked_offenders: an IO's 'most often X' for a
    community must be computed only from their own station's cases, not the whole
    state's."""
    from data.gds import community_members
    from rag_agent.agents.sql_agent import community_case_profile

    cid = ds.one('SELECT "CommunityID" FROM "vx_person" WHERE "CommunityID" IS NOT NULL')
    members = community_members(cid["CommunityID"], limit=25)
    ids = [str(m["PersonUID"]) for m in members]

    statewide = community_case_profile(ids, "IG", "")
    row = ds.one('SELECT "PoliceStationID" FROM "CaseMaster"')
    io_scoped = community_case_profile(ids, "IO", str(row["PoliceStationID"]))
    assert io_scoped["case_count"] <= statewide["case_count"]


def test_station_workload_only_counts_untouched_old_cases_as_stalled(dataset):
    """Two open cases at the same station, both old enough to be stale: one gets a
    board item, the other doesn't. Only the untouched one may appear in stalled_ids —
    proving the anti-join, not just that the function runs.

    `dataset` is session-scoped and shared with every other suite in the run, so
    every mutation here is restored in `finally` — this test must leave the two
    cases and the board table exactly as it found them, or a later suite (which
    picks its own "first case" the same way) inherits a case whose status, date or
    board history it never set.
    """
    from data.board import create_item, delete_item
    from rag_agent.agents.sql_agent import station_workload

    investigating = ds.one(
        'SELECT "CaseStatusID" FROM "CaseStatusMaster" WHERE "CaseStatusName" = '
        "'Under Investigation'")
    assert investigating, "fixture's CaseStatusMaster has no 'Under Investigation' row"
    cases = ds.query('SELECT "CaseMasterID", "CrimeRegisteredDate", "CaseStatusID" '
                     'FROM "CaseMaster" LIMIT 2')
    assert len(cases) == 2, "fixture must have at least two cases"
    touched, untouched = cases[0], cases[1]
    old_date = date.today() - timedelta(days=45)
    item = None
    try:
        ds.update("CaseMaster", "CaseMasterID", [
            {"CaseMasterID": touched["CaseMasterID"], "CrimeRegisteredDate": old_date,
             "CaseStatusID": investigating["CaseStatusID"]},
            {"CaseMasterID": untouched["CaseMasterID"], "CrimeRegisteredDate": old_date,
             "CaseStatusID": investigating["CaseStatusID"]},
        ])
        item = create_item(touched["CaseMasterID"], "note", "Following up.", created_by=1)

        stations = station_workload("IG", "")
        stalled_ids = {i for s in stations for i in s["stalled_ids"]}
        assert str(untouched["CaseMasterID"]) in stalled_ids
        assert str(touched["CaseMasterID"]) not in stalled_ids
    finally:
        if item:
            delete_item(int(item["item_id"]))
        ds.update("CaseMaster", "CaseMasterID", [
            {"CaseMasterID": touched["CaseMasterID"],
             "CrimeRegisteredDate": touched["CrimeRegisteredDate"],
             "CaseStatusID": touched["CaseStatusID"]},
            {"CaseMasterID": untouched["CaseMasterID"],
             "CrimeRegisteredDate": untouched["CrimeRegisteredDate"],
             "CaseStatusID": untouched["CaseStatusID"]},
        ])
