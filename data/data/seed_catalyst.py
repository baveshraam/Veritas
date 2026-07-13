"""Seed the live Catalyst Data Store from the locally-built dataset.

    cd data && python -m data.generator.run --cases 10000     # build it in SQLite
    CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python -m data.seed_catalyst

Reads the SQLite dataset (which is the same schema, executed by the same ZCQL) and bulk-loads
it into Data Store over the same Admin API `data.provision` uses. Data Store's `ds:import` CSV
route exists, but it prompts at a TTY and cannot run unattended; this can.

Order is the FK topology — parents before children. Data Store enforces no foreign keys at
all, so nothing stops you loading a case that points at a station that does not exist; only
this ordering does.

Idempotent by truncation: every table is emptied before it is refilled. A partial reseed on
top of old rows would leave cases citing stations from a previous generation.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime

from .generator.load import DERIVED, LOAD_ORDER
from .schema import TABLES

_BASE = "https://api.catalyst.zoho.in/baas/v1/project"
_BATCH = 100                      # Data Store's per-call row cap
_ORDER = LOAD_ORDER + ["vx_district_socioeconomic"] + DERIVED


def _call(method: str, path: str, body: object | None = None, _tries: int = 4) -> dict:
    req = urllib.request.Request(
        f"{_BASE}/{os.environ.get('CATALYST_PROJECT_ID', '52852000000013048')}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Zoho-oauthtoken {os.environ['CATALYST_ACCESS_TOKEN']}",
            "Accept": "application/vnd.catalyst.v2+json",
            "CATALYST-ORG": os.environ.get("CATALYST_ORG", "60077763394"),
            "Content-Type": "application/json",
        },
    )
    for attempt in range(_tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
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


def _wire(v, col_type: str):
    """SQLite's value -> the JSON scalar Data Store expects.

    Typed by the column, not by the Python value, because SQLite has no boolean: it stored
    `Active` as 0/1, and Data Store rejects an integer there with "Please give a correct
    boolean value". The schema is the only thing that knows which is which.
    """
    if col_type == "boolean":
        return bool(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return v


def _insert_batch(table_id: str, rows: list[dict]) -> None:
    """Insert up to _BATCH rows, tolerating a batch that was *partially* applied.

    Data Store's row insert is not atomic across a batch: a transient 5xx can arrive after it
    has already committed some of the rows. The retry in `_call` then resends the whole batch
    and the rows that did land come back as DUPLICATE_VALUE, which killed the seed 188 rows
    into a 388-row table. So a duplicate is treated as what it actually is — evidence the row
    is already there — and the batch falls back to row-at-a-time, skipping the ones that
    exist. The result is that re-running the seeder is always safe.
    """
    try:
        _call("POST", f"/table/{table_id}/row", rows)
        return
    except RuntimeError as e:
        if "DUPLICATE_VALUE" not in str(e):
            raise
    for row in rows:
        try:
            _call("POST", f"/table/{table_id}/row", [row])
        except RuntimeError as e:
            if "DUPLICATE_VALUE" not in str(e):
                raise


def seed() -> None:
    os.environ.setdefault("VERITAS_DS_BACKEND", "sqlite")     # read side stays local
    from . import ds

    table_ids = {t["table_name"]: t["table_id"] for t in _call("GET", "/table")["data"]}
    missing = [t for t in _ORDER if t not in table_ids]
    if missing:
        sys.exit(f"not provisioned: {missing}. Run `python -m data.provision` first.")

    # Truncate children before parents, so a half-finished wipe never strands a child.
    # `/query` runs ZCQL directly — the same DELETE the app itself would issue.
    print("clearing…")
    for table in reversed(_ORDER):
        _call("POST", "/query", {"query": f"DELETE FROM {table}"})

    total = 0
    for table in _ORDER:
        types = {c.name: c.type for c in TABLES[table]}
        cols = ", ".join('"%s"' % c for c in types)
        rows = ds.query(f'SELECT {cols} FROM "{table}"')
        if not rows:
            continue
        payload = [{k: _wire(v, types[k]) for k, v in r.items() if v is not None}
                   for r in rows]
        for i in range(0, len(payload), _BATCH):
            _insert_batch(table_ids[table], payload[i:i + _BATCH])
        total += len(payload)
        print(f"  {table:28s} {len(payload):>7,}")

    print(f"\nseeded {total:,} rows into the live Data Store.")


if __name__ == "__main__":
    if "CATALYST_ACCESS_TOKEN" not in os.environ:
        sys.exit("CATALYST_ACCESS_TOKEN not set. Run: node scripts/catalyst-token.js")
    seed()
