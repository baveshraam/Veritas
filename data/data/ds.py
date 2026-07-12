"""Catalyst Data Store access. `query()` and `write()` are the only ways in.

Replaces the old SQLAlchemy/Postgres layer entirely. Two backends, one query language:

  catalyst  zcatalyst-sdk against the real Data Store. Used wherever the process runs
            inside Catalyst (AppSail), where the SDK authenticates itself as the app
            administrator — no keys, no secrets, nothing to leak.
  sqlite    the same ZCQL strings executed against a local SQLite file. Used for tests,
            for the generator, and for offline development.

The second backend is not a mock. ZCQL is a subset of SQL, so SQLite executes the exact
query strings the deployed service sends to Data Store. A query that works in the test
suite is a query Data Store will accept, and one schema (data.schema) builds both.

Two Data Store facts every caller is protected from:
  * A SELECT returns at most 300 rows and 20 columns. `query()` pages transparently, so
    nothing above this module has to know. Ask for 24,000 FIRs and you get 24,000 FIRs.
  * Results come back keyed by table name ({"CaseMaster": {...}, "Employee": {...}} for a
    join). We flatten that to one flat row dict, which is what every caller wants.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

PAGE = 300                       # Data Store's hard SELECT cap. Not tunable.
_INSERT_BATCH = 100              # rows per Data Store insert call
_SQLITE_PATH = Path(os.getenv("VERITAS_SQLITE", ".veritas/ds.sqlite3"))
_LIMIT_RE = re.compile(r"\blimit\b", re.IGNORECASE)


def backend() -> str:
    """catalyst inside Catalyst, sqlite everywhere else. Override with VERITAS_DS_BACKEND."""
    if forced := os.getenv("VERITAS_DS_BACKEND"):
        return forced
    return "catalyst" if os.getenv("CATALYST_PROJECT_ID") else "sqlite"


# ---------------------------------------------------------------------------- literals
def _lit(v: Any) -> str:
    """Render a Python value as a ZCQL literal.

    ZCQL has no bind parameters — the query is a string, so a value spliced in raw is an
    injection. Everything goes through here. Strings get their quotes doubled, and only
    types we can render exactly are allowed; anything else raises rather than guessing.
    """
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.strftime("%Y-%m-%d") + "'"
    if isinstance(v, (list, tuple, set)):
        return "(" + ", ".join(_lit(x) for x in v) + ")"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    raise TypeError(f"cannot render {type(v).__name__} as a ZCQL literal")


def render(zcql: str, params: dict[str, Any] | None = None) -> str:
    """Substitute :name placeholders with quoted literals."""
    if not params:
        return zcql
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in params:
            raise KeyError(f"no value for :{key}")
        return _lit(params[key])
    return re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", sub, zcql)


# ---------------------------------------------------------------------------- catalyst
@lru_cache(maxsize=1)
def _catalyst_app():
    import zcatalyst_sdk
    return zcatalyst_sdk.initialize()


def _flatten(rows: list[dict]) -> list[dict]:
    """{"CaseMaster": {...}, "Employee": {...}} -> one flat dict per row."""
    out = []
    for r in rows:
        flat: dict[str, Any] = {}
        for v in r.values():
            flat.update(v) if isinstance(v, dict) else None
        out.append(flat or r)
    return out


def _catalyst_select(sql: str) -> list[dict]:
    zcql = _catalyst_app().zcql()
    if _LIMIT_RE.search(sql):                     # caller set its own LIMIT: respect it
        return _flatten(zcql.execute_query(sql))
    rows, offset = [], 0
    while True:                                   # page around the 300-row cap
        page = _flatten(zcql.execute_query(f"{sql} LIMIT {offset}, {PAGE}"))
        rows += page
        if len(page) < PAGE:
            return rows
        offset += PAGE


# ------------------------------------------------------------------------------ sqlite
_local = threading.local()


def _sqlite_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        if str(_SQLITE_PATH) != ":memory:":
            _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
    return conn


def init_db() -> None:
    """Create the schema in the sqlite backend. On Catalyst the tables already exist —
    they were provisioned by `catalyst iac:import` from data.schema.emit_iac()."""
    if backend() != "sqlite":
        return
    from .schema import emit_sqlite
    conn = _sqlite_conn()
    for stmt in emit_sqlite():
        conn.execute(stmt)
    conn.commit()


# ------------------------------------------------------------------------------- public
def query(zcql: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Run a ZCQL SELECT. Pages past the 300-row cap; returns flat row dicts."""
    sql = render(zcql, params)
    if backend() == "catalyst":
        return _catalyst_select(sql)
    return [dict(r) for r in _sqlite_conn().execute(sql).fetchall()]


def insert(table: str, rows: Sequence[dict]) -> int:
    """Insert rows. Batches to Data Store's per-call limit. Returns the row count."""
    rows = [r for r in rows if r]
    if not rows:
        return 0
    if backend() == "catalyst":
        t = _catalyst_app().datastore().table(table)
        for i in range(0, len(rows), _INSERT_BATCH):
            t.insert_rows(list(rows[i : i + _INSERT_BATCH]))
        return len(rows)
    conn = _sqlite_conn()
    for r in rows:                                # heterogeneous keys are allowed
        cols = ", ".join(f'"{c}"' for c in r)
        vals = ", ".join(_lit(v) for v in r.values())
        conn.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({vals})')
    conn.commit()
    return len(rows)


def execute(zcql: str, params: dict[str, Any] | None = None) -> None:
    """Run a ZCQL UPDATE/DELETE."""
    sql = render(zcql, params)
    if backend() == "catalyst":
        _catalyst_app().zcql().execute_query(sql)
        return
    conn = _sqlite_conn()
    conn.execute(sql)
    conn.commit()


def one(zcql: str, params: dict[str, Any] | None = None) -> dict | None:
    rows = query(f"{zcql} LIMIT 1", params)
    return rows[0] if rows else None


def scalar(zcql: str, params: dict[str, Any] | None = None) -> Any:
    row = one(zcql, params)
    return next(iter(row.values())) if row else None


def next_id(table: str, column: str) -> int:
    """Next value for one of the ER's own INT keys.

    The ER's keys (CaseMasterID, AccusedMasterID, ...) are business keys we must
    generate ourselves — Data Store's auto ROWID is a separate, additional column and
    cannot serve as CaseMasterID without violating the schema we were given.

    ponytail: MAX()+1, which is correct for the batch generator and for a single API
    process, and races under concurrent writers. Move to a Data Store sequence table
    with a compare-and-set if the API ever writes FIRs from more than one instance.
    """
    return int(scalar(f'SELECT MAX("{column}") AS m FROM "{table}"') or 0) + 1


def truncate(tables: Iterable[str] | None = None) -> None:
    """Wipe tables. Used by the generator's rebuild and by test teardown."""
    from .schema import TABLES
    for t in tables or TABLES:
        execute(f'DELETE FROM "{t}"')


def reset_for_tests(path: str = ":memory:") -> None:
    global _SQLITE_PATH
    _SQLITE_PATH = Path(path)
    os.environ["VERITAS_DS_BACKEND"] = "sqlite"
    if hasattr(_local, "conn"):
        _local.conn.close()
        del _local.conn
    init_db()


if __name__ == "__main__":   # self-check: same ZCQL, both backends, no injection
    reset_for_tests()
    insert("Rank", [{"RankID": 1, "RankName": "DSP", "Hierarchy": 3, "Active": True}])
    assert scalar('SELECT "RankName" AS n FROM "Rank" WHERE "RankID" = :r', {"r": 1}) == "DSP"

    # 1000 rows > the 300-row page cap: the pager must return all of them.
    insert("District", [{"DistrictID": i, "DistrictName": f"D{i}", "StateID": 29,
                         "Active": True} for i in range(1, 1001)])
    assert len(query('SELECT "DistrictID" FROM "District"')) == 1000

    # A quote in a value must not end the string literal.
    insert("Court", [{"CourtID": 1, "CourtName": "O'Brien's Court", "DistrictID": 1,
                      "StateID": 29, "Active": True}])
    assert scalar('SELECT "CourtName" AS n FROM "Court" WHERE "CourtID" = 1') == "O'Brien's Court"
    hostile = "x'; DELETE FROM \"District\"; --"
    insert("Court", [{"CourtID": 2, "CourtName": hostile, "DistrictID": 1, "StateID": 29}])
    assert scalar('SELECT "CourtName" AS n FROM "Court" WHERE "CourtID" = 2') == hostile
    assert len(query('SELECT "DistrictID" FROM "District"')) == 1000, "injection deleted rows"

    assert next_id("District", "DistrictID") == 1001
    print(f"ds.py OK (backend={backend()})")
