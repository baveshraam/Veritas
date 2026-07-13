"""Copy the built dataset into the live Catalyst Data Store.

The generator builds into SQLite (fast, local, and the same ZCQL either way). This pushes
that result up. It is the one operation the SDK cannot help with locally — the SDK
authenticates as the *app*, which only exists inside AppSail — so it goes over the same
Admin API `data.provision` uses, with the same token minted from the `catalyst login` the
CLI already holds.

    CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python -m data.seed_datastore

Order is the FK topology, not alphabetical: masters, then Unit/Employee, then CaseMaster,
then everything hanging off a case, then the derived layers. Anything else leaves rows
pointing at parents that do not exist yet.

Idempotent by wipe-and-reload: each table is emptied before it is filled. A partial seed is
worse than no seed — half a case's accused rows is a record that lies.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .generator.load import DERIVED, LOAD_ORDER
from .schema import TABLES

_BASE = "https://api.catalyst.zoho.in/baas/v1/project"
BATCH = 100                      # Data Store's per-call row cap
SEED_ORDER = LOAD_ORDER + ["vx_district_socioeconomic"] + DERIVED


def _call(method: str, path: str, body: object | None = None, _tries: int = 5) -> dict:
    token = os.environ["CATALYST_ACCESS_TOKEN"]
    project = os.environ.get("CATALYST_PROJECT_ID", "52852000000013048")
    org = os.environ.get("CATALYST_ORG", "60077763394")
    req = urllib.request.Request(
        f"{_BASE}/{project}{path}",
        method=method,
        data=json.dumps(body, default=str).encode() if body is not None else None,
        headers={
            "Authorization": f"Zoho-oauthtoken {token}",
            "Accept": "application/vnd.catalyst.v2+json",
            "CATALYST-ORG": org,
            "Content-Type": "application/json",
        },
    )
    for attempt in range(_tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            if e.code == 429 and attempt < _tries - 1:
                wait = 10 + 5 * (attempt + 1)   # rate-limited: back off longer
                print(f"    429 rate-limited, waiting {wait}s…", flush=True)
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt < _tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"{method} {path} -> {e.code} {detail}") from None
        except urllib.error.URLError:
            if attempt < _tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise AssertionError("unreachable")


def _table_ids() -> dict[str, str]:
    return {t["table_name"]: t["table_id"] for t in _call("GET", "/table")["data"]}


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    cols = [c.name for c in TABLES[table]]
    quoted = ", ".join(f'"{c}"' for c in cols)
    cur = conn.execute(f'SELECT {quoted} FROM "{table}"')
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _clean(row: dict, table: str) -> dict:
    """Drop NULLs (Data Store rejects an explicit null for an unset column) and coerce the
    booleans SQLite stored as 0/1 back into real booleans."""
    bools = {c.name for c in TABLES[table] if c.type == "boolean"}
    out = {}
    for k, v in row.items():
        if v is None:
            continue
        out[k] = bool(v) if k in bools else v
    return out


def seed(sqlite_path: str | None = None) -> dict[str, int]:
    path = sqlite_path or os.getenv("VERITAS_SQLITE", ".veritas/ds.sqlite3")
    if not Path(path).exists():
        sys.exit(f"{path} not found — run `python -m data.generator.run` first")

    conn = sqlite3.connect(path)
    ids = _table_ids()
    counts: dict[str, int] = {}

    for table in SEED_ORDER:
        if table not in ids:
            continue
        rows = _rows(conn, table)
        _call("DELETE", f"/table/{ids[table]}/row")           # wipe: a partial seed lies
        if not rows:
            continue

        payload = [_clean(r, table) for r in rows]
        for i in range(0, len(payload), BATCH):
            _call("POST", f"/table/{ids[table]}/row", payload[i : i + BATCH])
        counts[table] = len(payload)
        print(f"  {table:<28} {len(payload):>7,}", flush=True)

    print(f"\nseeded {sum(counts.values()):,} rows across {len(counts)} tables")
    return counts


if __name__ == "__main__":
    if "CATALYST_ACCESS_TOKEN" not in os.environ:
        sys.exit("CATALYST_ACCESS_TOKEN not set. Run: node scripts/catalyst-token.js")
    seed(sys.argv[1] if len(sys.argv) > 1 else None)
