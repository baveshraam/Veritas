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


def test_geometry_columns_wrapped():
    person_sql = _insert_sql("person", _PERSON_COLS, "address_geom")
    fir_sql = _insert_sql("fir", _FIR_COLS, "location_geom")
    assert "ST_GeomFromText(:address_geom, 4326)" in person_sql
    assert "ST_GeomFromText(:location_geom, 4326)" in fir_sql
    # non-geom columns stay plain binds
    assert ":scrb_id" in person_sql and "ST_GeomFromText(:scrb_id" not in person_sql
