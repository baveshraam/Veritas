"""Cross-case series discovery — the capability CROSS_STATION_LINKAGE and
SIMILAR_CASES don't cover: a pattern spanning cases nobody has connected because
there is no known common suspect yet. See series_detection.py's own module
docstring for why this deliberately builds on copilot_brief.similar_cases_for
rather than a second similarity engine.

Uses its own isolated dataset (module-scoped, a separate sqlite file) rather than
the shared session-scoped `dataset`/`indexed` fixtures from the root conftest —
every test here permanently overwrites specific case rows to build a controlled
scenario, which would otherwise leak into whatever other suite runs next in the
same test session.
"""
import random
from datetime import date, timedelta

import pytest
from data import ds
from data.generator import refdata as rd

from rag_agent import series_detection
from rag_agent.agents import sql_agent

# Every test crafts its cases against the SAME shared, module-scoped dataset (see
# series_ds below), so an earlier test's crafted cases are still sitting in the
# vector index when a later test runs. Each test therefore needs its OWN distinctive
# MO phrase — reusing one constant across tests let a stray case from an earlier
# test's crime type register a spurious "matching modus operandi" hit against a
# later test's anchor, purely because both happened to share literal text nothing
# in the product would ever actually produce twice by coincidence.


@pytest.fixture(scope="module")
def series_ds(tmp_path_factory):
    """A small, isolated, fully-indexed dataset this file owns exclusively."""
    import os

    tmp = tmp_path_factory.mktemp("series-detection")
    env = {
        "VERITAS_DS_BACKEND": "sqlite",
        "VERITAS_SQLITE": str(tmp / "ds.sqlite3"),
        "VERITAS_AML_LABELS": str(tmp / "aml_labels.json"),
        "VERITAS_VECTOR_INDEX": str(tmp / "vectors.npz"),
    }
    os.environ.update(env)
    ds.reset_for_tests(str(tmp / "ds.sqlite3"))

    from data.generator.build import generate
    from data.generator.load import load_dataset
    from data.socioeconomic import load as load_socioeconomic

    load_socioeconomic()
    built = generate(random.Random(11), 300)
    load_dataset(built)

    from ml_models.entity_resolution import resolve_entities
    resolve_entities()

    from data.embeddings.index_job import run_all
    run_all()
    return built


def _stations(n: int) -> list[int]:
    rows = ds.query('SELECT "UnitID" FROM "Unit" WHERE "TypeID" = 1 LIMIT :n', {"n": n})
    assert len(rows) >= n, "the generated dataset must seed at least this many stations"
    return [r["UnitID"] for r in rows]


def _some_case_ids(n: int, offset: int = 0) -> list[int]:
    rows = ds.query('SELECT "CaseMasterID" FROM "CaseMaster" ORDER BY "CaseMasterID" '
                    'LIMIT :n OFFSET :o', {"n": n, "o": offset})
    return [r["CaseMasterID"] for r in rows]


def _craft_case(case_id: int, *, station: int, sections: tuple[str, ...],
                crime_type: str, days_ago: int, mo: str) -> None:
    """Repurpose an EXISTING, already-FK-valid CaseMaster row for a controlled test
    scenario — safer than hand-assembling a new row, which would need valid foreign
    keys for half a dozen columns this test doesn't care about."""
    occurred = date.today() - timedelta(days=days_ago)
    ds.update("CaseMaster", "CaseMasterID", [{
        "CaseMasterID": case_id,
        "PoliceStationID": station,
        "CrimeMinorHeadID": rd.sub_head_id(crime_type),
        "CrimeRegisteredDate": occurred,
        "IncidentFromDate": occurred,
        "BriefFacts": (f"On {occurred:%d %b %Y}, a station registered a case of "
                      f"{crime_type.lower()} in a district. {mo}, in the afternoon, "
                      f"by a lone individual. Offences registered under sections "
                      f"{', '.join(sections)}."),
    }])
    ds.execute('DELETE FROM "ActSectionAssociation" WHERE "CaseMasterID" = :cid',
              {"cid": case_id})
    ds.insert("ActSectionAssociation", [
        {"CaseMasterID": case_id, "ActID": "IPC", "SectionID": s,
         "ActOrderID": 1, "SectionOrderID": i}
        for i, s in enumerate(sections, start=1)])


def _reindex() -> None:
    from data.embeddings.index_job import run_all
    run_all()


def test_a_genuine_cross_station_series_is_found(series_ds):
    stations = _stations(3)
    a, b, c = _some_case_ids(3, offset=0)
    for cid, station in zip((a, b, c), stations):
        _craft_case(cid, station=station, sections=("379", "380"),
                   crime_type="Theft", days_ago=5,
                   mo="A distinctive theft signature only this test uses")
    _reindex()

    anchor = sql_agent.fir_by_id(str(a), "SHO", "")[0]
    result = series_detection.find_series(anchor)

    assert result is not None
    found_ids = {m.fir_id for m in result.members}
    assert str(b) in found_ids and str(c) in found_ids
    assert len(result.stations) >= 2


def test_same_station_candidates_are_not_a_series(series_ds):
    """The whole point is linkage BLINDNESS — cases the anchor's own station already
    sees are not the gap this capability exists to close."""
    station = _stations(1)[0]
    a, b, c = _some_case_ids(3, offset=10)
    for cid in (a, b, c):
        _craft_case(cid, station=station, sections=("406", "409"),
                   crime_type="Criminal Breach of Trust", days_ago=3,
                   mo="A distinctive breach-of-trust signature only this test uses")
    _reindex()

    anchor = sql_agent.fir_by_id(str(a), "SHO", "")[0]
    assert series_detection.find_series(anchor) is None


def test_a_single_matching_case_elsewhere_is_not_yet_a_series(series_ds):
    """One matching case is coincidence, not a pattern — MIN_CLUSTER_SIZE exists
    specifically so a single lucky hit doesn't get reported as a discovered series."""
    stations = _stations(2)
    a, b = _some_case_ids(2, offset=20)
    mo = "A distinctive burglary signature only this test uses"
    _craft_case(a, station=stations[0], sections=("454", "457"),
               crime_type="House Burglary", days_ago=2, mo=mo)
    _craft_case(b, station=stations[1], sections=("454", "457"),
               crime_type="House Burglary", days_ago=2, mo=mo)
    _reindex()

    anchor = sql_agent.fir_by_id(str(a), "SHO", "")[0]
    assert series_detection.find_series(anchor) is None


def test_a_shared_known_accused_is_excluded_as_already_linked(series_ds):
    """A candidate that already shares a resolved accused with the anchor is
    CROSS_STATION_LINKAGE's job, not a series discovery — including it here would
    double-report the same fact under two different names."""
    stations = _stations(3)
    a, b, c = _some_case_ids(3, offset=30)
    for cid, station in zip((a, b, c), stations):
        _craft_case(cid, station=station, sections=("392", "394"),
                   crime_type="Robbery", days_ago=4,
                   mo="A distinctive robbery signature only this test uses")
    _reindex()

    a_accused = ds.query('SELECT "AccusedMasterID" FROM "Accused" WHERE "CaseMasterID" = :cid',
                        {"cid": a})
    b_accused = ds.query('SELECT "AccusedMasterID" FROM "Accused" WHERE "CaseMasterID" = :cid',
                        {"cid": b})
    assert a_accused and b_accused, "the generator must have put at least one accused on each case"

    person = ds.one('SELECT "PersonUID" FROM "vx_accused_identity" WHERE "AccusedMasterID" = :aid',
                    {"aid": a_accused[0]["AccusedMasterID"]})
    ds.execute('UPDATE "vx_accused_identity" SET "PersonUID" = :p WHERE "AccusedMasterID" = :aid',
              {"p": person["PersonUID"], "aid": b_accused[0]["AccusedMasterID"]})

    anchor = sql_agent.fir_by_id(str(a), "SHO", "")[0]
    result = series_detection.find_series(anchor)
    found_ids = {m.fir_id for m in result.members} if result else set()
    assert str(b) not in found_ids


def test_scan_for_new_series_finds_a_recently_filed_pattern(series_ds):
    stations = _stations(3)
    a, b, c = _some_case_ids(3, offset=40)
    for cid, station in zip((a, b, c), stations):
        _craft_case(cid, station=station, sections=("20", "21"),
                   crime_type="Narcotics", days_ago=1,
                   mo="A distinctive narcotics signature only this test uses")
    _reindex()

    results = series_detection.scan_for_new_series(days=7)
    all_ids = {m.fir_id for r in results for m in r.members} | {r.anchor_fir_id for r in results}
    assert {str(a), str(b), str(c)} & all_ids
