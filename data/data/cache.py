"""Catalyst Cache — a read-through cache for the session focus stack.

Why this one thing and not everything: the focus stack is read on *every* chat turn, before
anything else can happen. It is what resolves "does **he** have priors" against the person
the last turn was about, so the orchestrator cannot route a single query until it has been
fetched. It is also tiny, and it changes at most once per turn. That is the exact shape of
data a cache is for, and nothing else in this system is.

Correctness first: the Data Store stays the record of truth. A cache miss costs a query, a
stale entry is impossible (every write goes through `put` right after the row is written),
and a Catalyst-less environment silently uses a process-local dict, so the tests and the
offline stack behave identically without knowing this module exists.

# ponytail: the local fallback is an unbounded dict, which is fine for one process handling
# one officer's session at a time. If the API is ever scaled out, the local path stops being
# a cache and becomes a per-instance inconsistency — but by then Catalyst Cache is present
# and the local path is not the one running.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

SEGMENT = "Default"          # the segment Catalyst creates with every project
TTL_HOURS = 6                # a session an officer has left for six hours is over

_local: dict[str, str] = {}


def _segment():
    """The Catalyst Cache segment, or None when Catalyst isn't configured.

    Routed through `data.ds.catalyst_app()` — the SAME app instance Data Store
    uses — rather than an independent `zcatalyst_sdk.initialize()` call, and NOT
    memoized (`ds.catalyst_app()` itself isn't either): the SDK's context is
    thread-scoped, not process-global, so a bare `initialize()` succeeds only on
    a thread AppSail has bound live request headers into. `/jobs/refresh`'s
    background thread already captures and rebinds `ds._sdk_app` for exactly
    this reason (CLAUDE.md's "Catalyst SDK context is per-request headers, not
    environment variables" gotcha) — an independent cache client had no access
    to that rebinding, so a cache write from that thread silently no-opped
    (`put`'s own `except Exception` swallows a client that can't authenticate)
    every cycle. Found live: `/jobs/refresh`'s new fairness/advisory steps never
    populated their cache entries despite the job completing.
    """
    try:
        from data import ds
        return ds.catalyst_app().cache().segment(SEGMENT)
    except Exception:
        return None


def get(key: str) -> Any | None:
    seg = _segment()
    if seg is None:
        raw = _local.get(key)
    else:
        try:
            item = seg.get(key)
            raw = item.get("cache_value") if isinstance(item, dict) else item
        except Exception as e:
            log.debug("cache miss for %s (%s)", key, e)
            return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def put(key: str, value: Any, expiry_hours: int = TTL_HOURS) -> None:
    raw = json.dumps(value, default=str)
    seg = _segment()
    if seg is None:
        _local[key] = raw
        return
    try:
        seg.put(key, raw, expiry=expiry_hours)
    except Exception as e:                    # a cache that cannot write is not an outage
        log.debug("cache write failed for %s (%s)", key, e)


def evict(key: str) -> None:
    seg = _segment()
    if seg is None:
        _local.pop(key, None)
        return
    try:
        seg.delete(key)
    except Exception:
        pass
