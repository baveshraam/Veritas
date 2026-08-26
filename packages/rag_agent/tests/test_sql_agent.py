"""BUG-028: `person_record()` rendered "crime type not recorded" / "status not recorded"
for EVERY case of EVERY person, live, in production — the flagship "does X have priors"
capability (`CLAUDE.md` §0) silently degraded to case numbers and dates only. No prior
test caught this because every existing PERSON_HISTORY test only asserted intent
*routing* (`classify(...) == "PERSON_HISTORY"`), never the content of what came back.
"""
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
