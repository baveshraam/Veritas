"""Catalyst Data Store access. `query()` and `write()` are the only ways in.

Replaces the old SQLAlchemy/Postgres layer entirely. Two backends, one query language:

  catalyst  zcatalyst-sdk against the real Data Store. Used wherever the process runs
            inside Catalyst (AppSail), where the SDK authenticates itself as the app
            administrator — no keys, no secrets, nothing to leak.
  sqlite    the same ZCQL strings executed against a local SQLite file. Used for tests,
            for the generator, and for offline development.

The second backend is not a mock. ZCQL is a subset of SQL, so SQLite executes the same query
strings the deployed service sends to Data Store. A query that works in the test suite is a
query Data Store will accept, and one schema (data.schema) builds both.

Three Data Store facts every caller is protected from:
  * A SELECT returns at most 300 rows and 20 columns. `query()` pages transparently, so
    nothing above this module has to know. Ask for 24,000 FIRs and you get 24,000 FIRs.
  * Results come back keyed by table name ({"CaseMaster": {...}, "Employee": {...}} for a
    join). We flatten that to one flat row dict, which is what every caller wants.
  * **ZCQL rejects double-quoted identifiers.** SQLite needs them (the ER has tables called
    `Rank` and `Section`, which are SQL keywords); Data Store answers `No such Table with the
    given name exists` to every query that has them. So callers write the quoted, portable
    form and `unquote_identifiers()` strips them on the way out to Catalyst. This is the only
    genuine dialect difference between the two backends, and it is handled here so that it is
    handled once.
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


def unquote_identifiers(sql: str) -> str:
    """Strip `"double quotes"` from identifiers. Data Store rejects them; SQLite requires
    them for names like `Rank` and `Section` that collide with SQL keywords.

    This is the one place the two backends genuinely disagree, and it is not cosmetic — the
    live service answers `No such Table with the given name exists` to every quoted query, so
    a codebase that only ever ran against SQLite would pass its whole suite and then fail on
    literally every request in production.

    It cannot be a `.replace('"', '')`: a name in the data may legitimately contain a double
    quote (`Ramesh "Chikka" Gowda`), and stripping it from inside a string literal would
    silently corrupt the value being written or compared. So this walks the string and only
    removes quotes that are *outside* a single-quoted literal. ZCQL literals escape a quote by
    doubling it (`''`), which a single pass handles naturally: the closing quote of the first
    is immediately reopened by the second.
    """
    out: list[str] = []
    in_literal = False
    for ch in sql:
        if ch == "'":
            in_literal = not in_literal
            out.append(ch)
        elif ch == '"' and not in_literal:
            continue
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------- catalyst
# In AppSail the SDK's whole context — project id, key, domain, admin credential — arrives
# as X-ZC-* HEADERS on each gateway request, not as env vars, so `initialize()` with no
# request raises "Catalyst headers are empty". The API middleware calls
# bind_catalyst_request() on every request; the resulting app object is kept module-global
# so work that runs outside any request (the background model fetch, warm caches) can use
# the most recent context.
_sdk_app = None


def bind_catalyst_request(request) -> None:
    """Capture the current request's Catalyst headers into an SDK app instance."""
    global _sdk_app
    if backend() != "catalyst":
        return
    try:
        import zcatalyst_sdk
        _sdk_app = zcatalyst_sdk.initialize(req=request)
    except Exception:                              # never let context capture kill a request
        pass


def catalyst_app():
    """The SDK app for the current context. Public so model_fetch can share it."""
    global _sdk_app
    if _sdk_app is not None:
        return _sdk_app
    import zcatalyst_sdk
    _sdk_app = zcatalyst_sdk.initialize()          # functions-style runtime: thread-local set
    return _sdk_app


def _catalyst_app():
    return catalyst_app()


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
    sql = unquote_identifiers(sql)
    if _LIMIT_RE.search(sql):                     # caller set its own LIMIT: respect it
        return _flatten(zcql.execute_query(sql))
    # Pagination MUST have a stable order or pages overlap and skip: Data Store gives
    # `LIMIT offset, n` no ordering guarantee. And measured live, even ordered paging
    # duplicates one row at a page boundary — so when ROWID is in the result, rows are
    # deduped on it. (This artifact is also why the store itself briefly held 13
    # "duplicates": the original seeding read through the same paging.)
    if "ORDER BY" not in sql.upper():
        sql = f"{sql} ORDER BY ROWID"
    rows, offset, seen = [], 0, set()
    while True:                                   # page around the 300-row cap
        page = _flatten(zcql.execute_query(f"{sql} LIMIT {offset}, {PAGE}"))
        for r in page:
            rid = r.get("ROWID")
            if rid is not None:
                if rid in seen:
                    continue
                seen.add(rid)
            rows.append(r)
        if len(page) < PAGE:
            return rows
        offset += PAGE


# ------------------------------------------------------------------------------ sqlite
_local = threading.local()


def _sqlite_path() -> Path:
    """The local database file. On Catalyst this is the READ MIRROR (see below), which
    lives on the instance's scratch disk, not in the repo tree."""
    if backend() == "catalyst":
        return Path(os.getenv("VERITAS_MIRROR_DB", "/tmp/veritas_mirror.db"))
    return _SQLITE_PATH


def _sqlite_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "epoch", -1) != _CONN_EPOCH:
        path = _sqlite_path()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
        _local.epoch = _CONN_EPOCH
    return conn


# ---------------------------------------------------------------- catalyst read mirror
# Discovered on the live Data Store, not in any doc: ZCQL refuses to JOIN tables that
# have no *declared* relationship — and the ER's relationships are by business value
# (CaseMasterID, ActCode), which Data Store's ForeignKey column type cannot express
# (it only references ROWIDs; see data.schema). Every JOIN in the codebase is therefore
# unexecutable server-side, while the same string runs perfectly on SQLite.
#
# So on Catalyst, reads run against a LOCAL SQLITE MIRROR hydrated from the Data Store
# once per container: every ZCQL string keeps working verbatim, and the Data Store
# remains the record of truth — every write goes there first and is applied to the
# mirror second. Bonus, not incidental: hydration coerces values through the schema's
# declared column types, which kills the whole "live returns '4', sqlite returns 4"
# class of bug, and runtime Data Store reads drop to near zero (cost directive).
#
# Ceiling: one app instance. A second instance would have its own mirror and would not
# see this one's writes until rehydration. At that point move reads back server-side
# or add invalidation — for a single-instance deployment this is exact, not approximate.
_MIRROR_LOCK = threading.Lock()
_MIRROR_READY = False
_CONN_EPOCH = 0        # bumped when the mirror file is atomically replaced — stale
                       # per-thread connections point at the old inode and must reopen


def _norm(col, v):
    """Coerce a Data Store value (usually a string) to the schema's declared type."""
    if v is None or v == "":
        return None
    if col.type in ("int", "bigint"):
        return int(v)
    if col.type == "double":
        return float(v)
    if col.type == "boolean":
        return v if isinstance(v, bool) else str(v).lower() in ("true", "1")
    if col.type in ("date", "datetime"):
        dt = to_dt(v)
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d" if col.type == "date" else "%Y-%m-%d %H:%M:%S")
    return str(v)


def _ensure_mirror() -> None:
    global _MIRROR_READY, _CONN_EPOCH
    if _MIRROR_READY or backend() != "catalyst":
        return
    with _MIRROR_LOCK:
        if _MIRROR_READY:
            return
        import logging
        log = logging.getLogger(__name__)
        path = _sqlite_path()
        if path.exists():
            probe = sqlite3.connect(str(path))
            done = probe.execute(
                "SELECT name FROM sqlite_master WHERE name='vx_mirror_done'").fetchone()
            probe.close()
            if done:
                _MIRROR_READY = True
                return

        # All-or-nothing: hydrate into a scratch file and atomically replace. A failed
        # attempt leaves nothing behind, so the next request retries from zero instead
        # of colliding with a half-filled mirror (the UNIQUE-violation loop seen live).
        tmp = path.with_suffix(".hydrating")
        tmp.unlink(missing_ok=True)
        log.info("hydrating read mirror from Data Store")
        conn = sqlite3.connect(str(tmp))
        try:
            from .schema import TABLES, emit_sqlite
            for stmt in emit_sqlite():
                conn.execute(stmt)
            for table, cols in TABLES.items():
                rows = _catalyst_select(f'SELECT * FROM "{table}"')
                if not rows:
                    continue
                names = [c.name for c in cols]
                # OR IGNORE: belt against the page-boundary duplicate above — the second
                # copy of an identical row is dropped, never a distinct row (unique keys
                # would collide loudly in the tests otherwise).
                sql = (f'INSERT OR IGNORE INTO "{table}" '
                       f'({", ".join(chr(34)+n+chr(34) for n in names)}) '
                       f'VALUES ({", ".join("?" for _ in names)})')
                conn.executemany(sql, [[_norm(c, r.get(c.name)) for c in cols]
                                       for r in rows])
                log.info("mirrored %s: %d rows", table, len(rows))
            conn.execute("CREATE TABLE vx_mirror_done (ok INT)")
            conn.commit()
        except Exception:
            conn.close()
            tmp.unlink(missing_ok=True)
            raise
        conn.close()
        os.replace(tmp, path)
        _CONN_EPOCH += 1                # stale per-thread conns reopen the new file
        _MIRROR_READY = True
        log.info("read mirror ready")


def _sdk_row(r: dict) -> dict:
    """A row the SDK can send: it JSON-serializes, so datetimes must already be the
    display strings Data Store expects — sqlite's _lit() did this implicitly, and any
    caller passing a datetime (the audit trail's CreatedAt) worked locally and 500'd
    live until this normalization.

    A `double` column is a hard DECIMAL(15,4) — confirmed live by asking Data Store's
    own column-update endpoint for decimal_digits=12 on an existing column and getting
    the request accepted (status: success) with the returned spec still reading
    decimal_digits=4: the platform silently clamps it, no provisioning choice of ours
    changes it. A magnitude too small to show at 4 decimal places doesn't round to
    0 the way a fixed-point column normally would — it comes back inflated by
    10^4-10^5. Measured live: `vx_person.PageRank` of 0.000851196807533056 (an
    ordinary co-offender's real centrality in a 17k-node graph) came back as 8.5119.

    The first fix here rounded to a Python float (`round(v, 4)`) on the theory that
    avoiding scientific notation *in Python's own repr* would be enough. It wasn't:
    round-tripped live through the exact row-write endpoint the SDK calls, a Python
    float re-serializes as a JSON number, and Data Store's own JSON-number ingest for
    a `double` field turned out to have its own failure mode independent of ours —
    `0.0009` sent as a bare JSON number came back `400 INVALID_INPUT ("Please give a
    correct double value")`, rejected outright, not merely mis-scaled, so a batch
    write with any such value inside it likely fails the whole call, which the
    background refresh job then only logs and swallows. What DOES round-trip exactly
    is a plain fixed-point STRING: `"0.000851196807533056"` came back `8.0E-4`
    (correct, just Data Store's own — reasonably rounded — precision limit), and
    `"123.4567"` came back `123.4567` exactly. The one shape that is NEVER safe, string
    or number, is scientific notation: `"7.817113529341168e-05"` as a STRING still
    came back `7.8171` — this is genuinely a text-level `E`-notation bug on Data
    Store's side, not a JSON type-coercion issue, and no amount of picking `float` vs
    `str` fixes it unless the string itself is guaranteed exponent-free.

    So every float is now formatted with `:.4f` — always plain decimal, at Data
    Store's own real precision, never `e`/`E` regardless of magnitude — and sent as a
    string, which is what the live round-trip test above actually proved safe. A real
    signal below 0.00005 already can't survive this column's precision; better it
    prints `0.0000` than `8.5119`."""
    out = {}
    for k, v in r.items():
        if isinstance(v, datetime):
            v = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, date):
            v = v.strftime("%Y-%m-%d")
        elif isinstance(v, float):
            v = f"{v:.4f}"
        out[k] = v
    return out


def _mirror_apply(fn) -> None:
    """Apply a write to the mirror; a mirror failure must never fail the Data Store
    write that already happened — worst case a read is stale until the next container."""
    try:
        _ensure_mirror()
        conn = _sqlite_conn()
        fn(conn)
        conn.commit()
    except Exception:
        import logging
        logging.getLogger(__name__).exception("mirror write failed (Data Store write OK)")


def init_db() -> None:
    """Create the schema in the sqlite backend. On Catalyst the tables already exist —
    `python -m data.provision` created them from data.schema.TABLES."""
    if backend() != "sqlite":
        return
    from .schema import emit_sqlite
    conn = _sqlite_conn()
    for stmt in emit_sqlite():
        conn.execute(stmt)
    conn.commit()


# ------------------------------------------------------------------------------- public
def query(zcql: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Run a ZCQL SELECT. On Catalyst, reads come from the hydrated mirror — live ZCQL
    cannot JOIN value-related tables (see the mirror block above). Locally, sqlite."""
    sql = render(zcql, params)
    if backend() == "catalyst":
        _ensure_mirror()
    return [dict(r) for r in _sqlite_conn().execute(sql).fetchall()]


def insert(table: str, rows: Sequence[dict]) -> int:
    """Insert rows. Batches to Data Store's per-call limit. Returns the row count."""
    rows = [r for r in rows if r]
    if not rows:
        return 0
    def _sqlite_insert(conn: sqlite3.Connection) -> None:
        for r in rows:                            # heterogeneous keys are allowed
            cols = ", ".join(f'"{c}"' for c in r)
            vals = ", ".join(_lit(v) for v in r.values())
            conn.execute(f'INSERT INTO "{table}" ({cols}) VALUES ({vals})')

    if backend() == "catalyst":
        t = _catalyst_app().datastore().table(table)
        payload = [_sdk_row(r) for r in rows]
        for i in range(0, len(payload), _INSERT_BATCH):
            t.insert_rows(payload[i : i + _INSERT_BATCH])
        _mirror_apply(_sqlite_insert)             # truth written; keep reads current
        return len(rows)
    conn = _sqlite_conn()
    _sqlite_insert(conn)
    conn.commit()
    return len(rows)


def update(table: str, key: str, rows: Sequence[dict]) -> int:
    """Bulk-update rows, matched on the business key `key` (e.g. PersonUID).

    Data Store updates by ROWID, which is its own key, not ours — so on Catalyst this
    resolves key -> ROWID once and then bulk-writes. Issuing one ZCQL UPDATE per row
    instead would be ~10k round-trips for a single PageRank pass.
    """
    rows = [r for r in rows if r]
    if not rows:
        return 0
    def _sqlite_update(conn: sqlite3.Connection) -> None:
        for r in rows:
            sets = ", ".join(f'"{c}" = {_lit(v)}' for c, v in r.items() if c != key)
            conn.execute(f'UPDATE "{table}" SET {sets} WHERE "{key}" = {_lit(r[key])}')

    if backend() == "catalyst":
        # ROWID resolution must hit the real Data Store: the mirror's sqlite rowids
        # are its own and share nothing with Data Store's. str() both sides — the live
        # store returns every value as a string, our callers pass ints.
        rowid_of = {str(r[key]): r["ROWID"] for r in
                    _catalyst_select(f'SELECT ROWID, "{key}" FROM "{table}"')}
        payload = [_sdk_row(dict(r, ROWID=rowid_of[str(r[key])]))
                   for r in rows if str(r[key]) in rowid_of]
        t = _catalyst_app().datastore().table(table)
        for i in range(0, len(payload), _INSERT_BATCH):
            t.update_rows(payload[i : i + _INSERT_BATCH])
        _mirror_apply(_sqlite_update)
        return len(payload)
    conn = _sqlite_conn()
    _sqlite_update(conn)
    conn.commit()
    return len(rows)


def execute(zcql: str, params: dict[str, Any] | None = None) -> None:
    """Run a ZCQL UPDATE/DELETE. On Catalyst: Data Store first (truth), mirror second."""
    sql = render(zcql, params)
    if backend() == "catalyst":
        _catalyst_app().zcql().execute_query(unquote_identifiers(sql))
        _mirror_apply(lambda conn: conn.execute(sql))
        return
    conn = _sqlite_conn()
    conn.execute(sql)
    conn.commit()


def to_dt(v: Any) -> datetime | None:
    """Coerce a datetime column to a datetime.

    Data Store hands back real datetimes; SQLite hands back the ISO strings it stored. Any
    caller doing date arithmetic goes through here, or it works on one backend and throws
    on the other.
    """
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d",
                "%b %d, %Y %I:%M %p"):          # the last is Data Store's display format
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    raise ValueError(f"cannot parse {v!r} as a datetime")


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
