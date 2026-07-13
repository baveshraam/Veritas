"""Create the Data Store tables from `schema.TABLES`, over the Catalyst Admin API.

The documented ways in are the console (manual) and an IaC template import (which forks
a *new* project — it would orphan the AppSail and QuickML deployments already living in
this one). Neither is usable. But the Admin API that the console itself calls is:

    POST /baas/v1/project/{id}/table            {"table_name": "X"}      -> table_id
    POST /baas/v1/project/{id}/table/{tid}/column   [ {column spec}, ... ]

Both are reachable with the OAuth token the `catalyst` CLI already stores from
`catalyst login`, so provisioning needs no extra credential.

    node scripts/catalyst-token.js               # mints an access token from that login
    CATALYST_ACCESS_TOKEN=<token> python -m data.provision

Idempotent: existing tables and columns are left alone, missing ones are added.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from .schema import _MAX_LEN, TABLES

_BASE = "https://api.catalyst.zoho.in/baas/v1/project"

# Data Store has no DATE type — only DATETIME. Everything else maps straight through.
_DS_TYPE = {"date": "datetime"}


def _call(method: str, path: str, body: object | None = None, _tries: int = 4) -> dict:
    token = os.environ["CATALYST_ACCESS_TOKEN"]
    project = os.environ.get("CATALYST_PROJECT_ID", "52852000000013048")
    org = os.environ.get("CATALYST_ORG", "60077763394")
    req = urllib.request.Request(
        f"{_BASE}/{project}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Zoho-oauthtoken {token}",
            "Accept": "application/vnd.catalyst.v2+json",
            "CATALYST-ORG": org,
            "Content-Type": "application/json",
        },
    )
    for attempt in range(_tries):
        try:
            with urllib.request.urlopen(req) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            if e.code == 429 and attempt < _tries - 1:
                wait = 10 + 5 * (attempt + 1)
                print(f"    429 rate-limited, waiting {wait}s…", flush=True)
                time.sleep(wait)
                continue
            # The column endpoint throws a transient 500 under back-to-back batches.
            if e.code >= 500 and attempt < _tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"{method} {path} -> {e.code} {detail}") from None
    raise AssertionError("unreachable")


def _column_spec(col) -> dict:
    dtype = _DS_TYPE.get(col.type, col.type)
    spec: dict = {
        "column_name": col.name,
        "data_type": dtype,
        "is_mandatory": col.mandatory,
        "is_unique": col.unique,
    }
    if dtype in _MAX_LEN:
        spec["max_length"] = _MAX_LEN[dtype]
    return spec


def provision() -> None:
    existing = {t["table_name"]: t["table_id"] for t in _call("GET", "/table")["data"]}

    for table, cols in TABLES.items():
        if table in existing:
            tid = existing[table]
        else:
            tid = _call("POST", "/table", {"table_name": table})["data"]["table_id"]
            print(f"+ table {table}")

        have = {c["column_name"] for c in _call("GET", f"/table/{tid}/column")["data"]}
        missing = [_column_spec(c) for c in cols if c.name not in have]
        if missing:
            # One call per table: the endpoint takes a batch, and 36 round-trips beat 250.
            _call("POST", f"/table/{tid}/column", missing)
            print(f"  + {len(missing)} columns on {table}")

    print(f"\n{len(TABLES)} tables provisioned.")


if __name__ == "__main__":
    if "CATALYST_ACCESS_TOKEN" not in os.environ:
        sys.exit("CATALYST_ACCESS_TOKEN not set. Run: node scripts/catalyst-token.js")
    provision()
