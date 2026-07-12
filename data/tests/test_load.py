"""Loader row-mapping checks — no DB. Guards against build/insert column drift."""
import random

from data.generator.build import generate
from data.generator.load import (
    _FIR_COLS, _OFFICER_COLS, _PERSON_COLS, _RECORD_COLS,
    _insert_sql, fir_rows, officer_rows, person_rows, record_rows,
)

_DS = generate(random.Random(3), 50)


def test_every_row_dict_has_exactly_the_insert_columns():
    for rows, cols in [
        (officer_rows(_DS), _OFFICER_COLS),
        (person_rows(_DS), _PERSON_COLS),
        (fir_rows(_DS), _FIR_COLS),
        (record_rows(_DS), _RECORD_COLS),
    ]:
        assert rows, "generator produced no rows"
        for r in rows:
            # dataclass fields and the insert column set must match exactly,
            # otherwise executemany binds a missing/extra param at runtime.
            assert set(r.keys()) == set(cols)


def test_coordinates_are_plain_decimal_binds():
    """No PostGIS: coordinates bind as ordinary numbers, and nothing in the insert
    path may reintroduce a geometry wrapper (Catalyst Data Store has no such type)."""
    person_sql = _insert_sql("person", _PERSON_COLS)
    fir_sql = _insert_sql("fir", _FIR_COLS)
    assert ":address_lat" in person_sql and ":address_lng" in person_sql
    assert ":latitude" in fir_sql and ":longitude" in fir_sql
    assert "ST_" not in person_sql and "ST_" not in fir_sql


def test_generated_coordinates_are_numbers_inside_karnataka():
    for r in fir_rows(_DS):
        assert isinstance(r["latitude"], float) and isinstance(r["longitude"], float)
        assert 11.5 < r["latitude"] < 18.5 and 74.0 < r["longitude"] < 78.6


def test_every_officer_has_the_email_catalyst_authenticates_on():
    emails = [r["email"] for r in officer_rows(_DS)]
    assert all(e.endswith("@ksp.gov.in") for e in emails)
    assert len(set(emails)) == len(emails)          # Catalyst identity must be unique
