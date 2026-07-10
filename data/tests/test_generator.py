"""Offline integrity checks for the synthetic builder — no DB required."""
import random

from data.districts import canonical_code
from data.generator.build import generate


def _ds():
    return generate(random.Random(42), 400)


def test_referential_integrity():
    ds = _ds()
    person_ids = {p.person_id for p in ds.persons}
    officer_ids = {o.officer_id for o in ds.officers}
    fir_ids = {f.fir_id for f in ds.firs}
    ps_by_officer = {o.officer_id: o.ps_code for o in ds.officers}

    for f in ds.firs:
        assert f.complainant_id in person_ids
        assert f.io_id in officer_ids
        assert ps_by_officer[f.io_id] == f.ps_code       # IO belongs to the FIR's station
        assert canonical_code(f.district_code) == f.district_code
        assert f.ipc_sections                             # never empty
        assert f.occurrence_from <= f.occurrence_to <= f.date_filed

    for r in ds.criminal_records:
        assert r.person_id in person_ids
        assert r.fir_id in fir_ids


def test_accused_have_criminal_history_flag():
    ds = _ds()
    accused_ids = {r.person_id for r in ds.criminal_records}
    flagged = {p.person_id for p in ds.persons if p.criminal_history}
    assert accused_ids == flagged                         # flag <=> appears as accused


def test_scrb_and_badge_ids_unique():
    ds = _ds()
    assert len({p.scrb_id for p in ds.persons}) == len(ds.persons)
    assert len({o.badge_no for o in ds.officers}) == len(ds.officers)
    assert len({f.fir_id for f in ds.firs}) == len(ds.firs)


def test_deterministic_for_same_seed():
    a, b = generate(random.Random(1), 100), generate(random.Random(1), 100)
    assert [f.fir_number for f in a.firs] == [f.fir_number for f in b.firs]
    assert len(a.persons) == len(b.persons)
