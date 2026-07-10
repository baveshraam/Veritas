"""Foundation checks that need no live DB — splitter correctness + import safety."""
from pathlib import Path

from data.db import _split_statements

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def test_schema_splits_into_clean_statements():
    sql = (_SQL_DIR / "001_schema.sql").read_text(encoding="utf-8")
    stmts = _split_statements(sql)
    assert any(s.startswith("CREATE TABLE") and "officer" in s for s in stmts)
    assert all(";" not in s for s in stmts)          # each is one statement
    assert all(not s.startswith("--") for s in stmts)  # comments stripped
    # every table the README promises is present
    joined = " ".join(stmts)
    for table in ("officer", "person", "fir", "criminal_record",
                  "district_socioeconomic", "session", "conversation_turn", "audit_log"):
        assert f"TABLE IF NOT EXISTS {table}" in joined


def test_district_aliases_reconcile():
    from data.districts import all_districts, canonical_code
    assert len(all_districts()) == 31
    # different dataset spellings collapse to one code
    assert canonical_code("Bangalore Urban") == canonical_code("Bengaluru Urban") == "KA05"
    assert canonical_code("Gulbarga") == canonical_code("Kalaburagi") == "KA16"
    assert canonical_code("unknownville") is None


def test_manifest_invariants():
    from data.manifest import DATASETS, by_role, get
    ids = [d.id for d in DATASETS]
    assert len(ids) == len(set(ids)) == 17            # unique, complete
    paths = [d.local_path for d in DATASETS]
    assert len(paths) == len(set(paths))              # no colliding staging dirs
    assert get("D17").role == "GROUND_TRUTH"          # census fills a real table
    assert sum(len(by_role(r)) for r in ("PRIOR", "GROUND_TRUTH", "ML_CORPUS")) == 17


def test_priors_cover_all_districts_and_sample_correctly():
    import random
    from data.districts import canonical_code
    from data.priors import crime_types, district_weights, sample_crime_type, sample_district
    assert len(crime_types()) == 20
    assert len(district_weights()) == 31
    for code in district_weights():                    # every prior code is real
        assert canonical_code(code) == code
    rng = random.Random(1)
    assert all(0.0 <= c.conviction_rate <= c.chargesheet_rate <= 1.0 for c in crime_types())
    assert sample_crime_type(rng).crime_type          # non-empty draw
    assert canonical_code(sample_district(rng))        # draws a real district


def test_connection_modules_import_without_db():
    # get_engine is lazy, so importing must not require a running Postgres.
    import data.db  # noqa: F401
    import data.graph  # noqa: F401


if __name__ == "__main__":
    test_schema_splits_into_clean_statements()
    test_connection_modules_import_without_db()
    print("ok")
