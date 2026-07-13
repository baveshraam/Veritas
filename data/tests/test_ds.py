"""The Data Store client: the two Catalyst limits, and the one injection boundary.

ZCQL has **no bind parameters** — a query is a string, so every value is spliced in. That
makes `render()`/`_lit()` the single place where hostile input could reach the database, and
the reason it is worth its own test file.
"""
from datetime import date, datetime

import pytest

from data import ds


@pytest.fixture(autouse=True)
def fresh():
    ds.reset_for_tests()          # in-memory sqlite, schema from data.schema


def test_paging_returns_every_row_past_the_300_cap():
    """Data Store caps a SELECT at 300 rows. `query()` pages, so no caller has to know."""
    ds.insert("District", [{"DistrictID": i, "DistrictName": f"D{i}", "StateID": 29,
                            "Active": True} for i in range(1, 1001)])
    assert len(ds.query('SELECT "DistrictID" FROM "District"')) == 1000
    assert ds.PAGE == 300


def test_a_quote_in_a_value_cannot_end_the_literal():
    ds.insert("Court", [{"CourtID": 1, "CourtName": "O'Brien's Court", "DistrictID": 1,
                         "StateID": 29, "Active": True}])
    assert ds.scalar('SELECT "CourtName" AS n FROM "Court" WHERE "CourtID" = 1') \
        == "O'Brien's Court"


def test_injection_through_a_value_does_not_execute():
    ds.insert("District", [{"DistrictID": i, "DistrictName": f"D{i}", "StateID": 29}
                           for i in range(1, 51)])
    hostile = "x'; DELETE FROM \"District\"; --"
    ds.insert("Court", [{"CourtID": 2, "CourtName": hostile, "DistrictID": 1, "StateID": 29}])

    assert ds.scalar('SELECT "CourtName" AS n FROM "Court" WHERE "CourtID" = 2') == hostile
    assert len(ds.query('SELECT "DistrictID" FROM "District"')) == 50, "injection ran"


def test_injection_through_a_parameter_does_not_execute():
    ds.insert("District", [{"DistrictID": i, "DistrictName": f"D{i}", "StateID": 29}
                           for i in range(1, 51)])
    rows = ds.query('SELECT "DistrictID" FROM "District" WHERE "DistrictName" = :n',
                    {"n": "D1'; DELETE FROM \"District\"; --"})
    assert rows == []
    assert len(ds.query('SELECT "DistrictID" FROM "District"')) == 50


def test_unrenderable_types_raise_rather_than_guess():
    with pytest.raises(TypeError):
        ds.render("SELECT :x", {"x": object()})


def test_missing_parameter_raises():
    with pytest.raises(KeyError):
        ds.render('SELECT * FROM "x" WHERE "a" = :nope', {"other": 1})


def test_update_writes_by_business_key():
    ds.insert("Rank", [{"RankID": i, "RankName": f"R{i}", "Hierarchy": i} for i in (1, 2)])
    ds.update("Rank", "RankID", [{"RankID": 2, "RankName": "DSP"}])
    assert ds.scalar('SELECT "RankName" AS n FROM "Rank" WHERE "RankID" = 2') == "DSP"
    assert ds.scalar('SELECT "RankName" AS n FROM "Rank" WHERE "RankID" = 1') == "R1"


def test_next_id_generates_the_ers_own_business_keys():
    """Data Store's ROWID is its key, not the ER's. CaseMasterID is ours to generate."""
    assert ds.next_id("District", "DistrictID") == 1
    ds.insert("District", [{"DistrictID": 7, "DistrictName": "x", "StateID": 29}])
    assert ds.next_id("District", "DistrictID") == 8


@pytest.mark.parametrize("value,expected", [
    ("2026-03-12 09:30:00", datetime(2026, 3, 12, 9, 30)),
    ("2026-03-12", datetime(2026, 3, 12)),
    ("Mar 12, 2026 09:30 AM", datetime(2026, 3, 12, 9, 30)),   # Data Store's own format
    (datetime(2026, 3, 12, 9, 30), datetime(2026, 3, 12, 9, 30)),
    (date(2026, 3, 12), datetime(2026, 3, 12)),
    (None, None),
])
def test_to_dt_accepts_both_backends_date_shapes(value, expected):
    """SQLite hands back the ISO string it stored; Data Store hands back a real datetime.
    Any caller doing date arithmetic goes through to_dt, or it works on one and throws on
    the other."""
    assert ds.to_dt(value) == expected


# --------------------------------------------------------------- the one dialect difference
def test_identifier_quotes_are_stripped_for_data_store():
    """ZCQL rejects double-quoted identifiers outright — `No such Table with the given name
    exists` — while SQLite needs them, because the ER contains tables called `Rank` and
    `Section` which are SQL keywords. Callers write the portable quoted form; this strips it
    on the way out to Catalyst.
    """
    sql = 'SELECT "CaseMaster"."CrimeNo" FROM "CaseMaster" WHERE "Rank"."RankID" = 1'
    assert ds.unquote_identifiers(sql) == (
        "SELECT CaseMaster.CrimeNo FROM CaseMaster WHERE Rank.RankID = 1")


def test_a_double_quote_inside_a_value_survives_unquoting():
    """It cannot be a blind `.replace('"', '')`. A recorded name may legitimately contain a
    double quote — Indian aliases are often written `Ramesh "Chikka" Gowda` — and stripping it
    from inside the literal would silently corrupt the value being written or compared."""
    sql = ds.render('SELECT * FROM "vx_person" WHERE "CanonicalName" = :n',
                    {"n": 'Ramesh "Chikka" Gowda'})
    out = ds.unquote_identifiers(sql)
    assert out == "SELECT * FROM vx_person WHERE CanonicalName = 'Ramesh \"Chikka\" Gowda'"


def test_an_escaped_single_quote_does_not_unbalance_the_scanner():
    """ZCQL escapes a quote by doubling it. The scanner must not mistake the second for the
    start of a new literal, or every identifier after an apostrophe would stop being stripped.
    """
    sql = ds.render('SELECT * FROM "Court" WHERE "CourtName" = :n AND "Rank"."RankID" = 1',
                    {"n": "O'Brien's"})
    out = ds.unquote_identifiers(sql)
    assert out.endswith("AND Rank.RankID = 1")
    assert "'O''Brien''s'" in out
