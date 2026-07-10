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


def test_connection_modules_import_without_db():
    # get_engine is lazy, so importing must not require a running Postgres.
    import data.db  # noqa: F401
    import data.graph  # noqa: F401


if __name__ == "__main__":
    test_schema_splits_into_clean_statements()
    test_connection_modules_import_without_db()
    print("ok")
