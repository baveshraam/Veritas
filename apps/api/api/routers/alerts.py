"""GET /alerts — SSE stream of Isolation Forest anomaly alerts.

The one place apps/api calls packages/ml_models directly (check_anomalies);
everything else goes through rag_agent. Alerts are decision-support: an alert says
this month is unlike the district's own history, never "deploy here".

BUG-005 history: this was a WebSocket route (`@router.websocket("/alerts")`),
authenticated by sending the bearer token as the first frame — a browser
WebSocket cannot set an Authorization header, so the normal `Depends
(current_officer)` pattern didn't apply. That transport was verified correct
in-process (`TestClient.websocket_connect` exercises the real auth logic), but
every live check — a mature Python `websocket-client`, and raw curl with
explicit `Connection: Upgrade`/`Sec-WebSocket-*` headers — got Starlette's own
404, while an ordinary REST route on the identical domain (`/cases`) correctly
returned 401 and CORS visibly processed the request. That is consistent with
AppSail's gateway not proxying WebSocket upgrades to a custom-runtime app at
all; `/alerts` had likely never worked live on any version of this code,
independent of the auth fix.

`/chat` already proves the alternative works live on this exact deployment:
`sse_starlette.EventSourceResponse` over a plain POST, authenticated with the
console's own bearer token via `fetch` (not `EventSource`, which — like
WebSocket — cannot set an Authorization header either, so `lib/api.ts` never
used it). Converting `/alerts` to the same transport removes the dependency on
whatever AppSail does or does not proxy for WebSocket upgrades, reuses a
proven-live pattern instead of a second bespoke one, and lets this route take
the same `Depends(current_officer)` every other data-bearing route already
uses — no more hand-rolled first-frame auth.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from data import cache, ds
from fastapi import APIRouter, Depends, Request
from ml_models.serving import check_anomalies
from policy import can_view_fir
from sse_starlette.sse import EventSourceResponse

from ..auth.jwt_auth import Officer, current_officer
from .jobs import ADVISORY_CACHE_KEY, SERIES_CACHE_KEY

log = logging.getLogger(__name__)
router = APIRouter()

POLL_SECONDS = 30

# check_anomalies() returns every anomalous month in a district's whole history.
# Pushed as-is across ~31 districts that is several hundred toasts the moment an
# officer signs in — the feed drowns the console and says nothing actionable.
# This is an *early-warning* feed: only spikes inside the recent window are news,
# and only the sharpest few of those are worth interrupting someone for.
RECENT_DAYS = 180
MAX_PER_POLL = 4


def _districts() -> list[str]:
    """The district codes to watch. Read from the District master, not from the cases —
    a district with no case this month is exactly the one a spike would be news in."""
    from data.districts import all_districts
    known = {r["DistrictID"] for r in ds.query('SELECT "DistrictID" FROM "District"')}
    from data.generator.refdata import district_id
    return [d.code for d in all_districts() if district_id(d.code) in known]


def _recent(alert) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    at = alert.detected_at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at >= cutoff


def _cached_series() -> list[dict]:
    """Read-only: the actual scan runs in /jobs/refresh's own step, on that job's 6h
    cadence, never here. A poll that finds nothing cached (no refresh has run yet)
    gets an empty list, not an error — the same "a missing derived layer degrades
    silently" property the rest of this feed already has."""
    return cache.get(SERIES_CACHE_KEY) or []


def _cached_advisories() -> list[dict]:
    """Same read-only contract as `_cached_series` — the fused hotspot/forecast/
    series-linkage advisory (STRATEGIC_RESET Part 9, Item 2) is computed once per
    refresh cycle, never per poll."""
    return cache.get(ADVISORY_CACHE_KEY) or []


def _scoped_series(series: dict, role: str, ps: str) -> dict | None:
    """The same partial-visibility discipline SERIES_DISCOVERY's conversational
    handler applies, here for the push feed: an officer never sees this at all if
    they can't see the anchor case itself, and a member at a station outside their
    scope is reported as existing without being named — the pattern is real, the
    case is not shown."""
    if not can_view_fir(role, ps, series.get("anchor_ps_code") or ""):
        return None
    members = []
    for m in series.get("members", []):
        if can_view_fir(role, ps, m.get("ps_code") or ""):
            members.append(m)
        else:
            members.append({**m, "fir_number": None, "ps_name": None,
                            "matched_features": ["outside your access scope"]})
    return {**series, "members": members}


@router.get("/alerts")
async def alerts(request: Request, officer: Officer = Depends(current_officer)):
    async def stream():
        seen: set[str] = set()
        seen_series: set[str] = set()
        seen_advisory: set[str] = set()
        loop = asyncio.get_running_loop()
        try:
            while True:
                if await request.is_disconnected():
                    return
                fresh = []
                for dc in await loop.run_in_executor(None, _districts):
                    for alert in await loop.run_in_executor(None, check_anomalies, dc):
                        key = f"{alert.district_code}:{alert.detected_at:%Y-%m}"
                        if key in seen or not _recent(alert):
                            continue      # already pushed, or old news
                        seen.add(key)
                        fresh.append(alert)

                fresh.sort(key=lambda a: -abs(a.observed - a.expected))
                for alert in fresh[:MAX_PER_POLL]:
                    yield {"event": "alert", "data": alert.model_dump_json()}

                for series in await loop.run_in_executor(None, _cached_series):
                    anchor = series.get("anchor_fir_id")
                    if not anchor or anchor in seen_series:
                        continue
                    scoped = _scoped_series(series, officer.role, officer.ps_code)
                    if scoped is None:
                        continue          # can't see the anchor case at all
                    seen_series.add(anchor)
                    yield {"event": "series", "data": json.dumps(scoped)}

                for advisory in await loop.run_in_executor(None, _cached_advisories):
                    dc = advisory.get("district_code")
                    if not dc or dc in seen_advisory:
                        continue
                    seen_advisory.add(dc)
                    yield {"event": "advisory", "data": json.dumps(advisory)}

                await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            return

    return EventSourceResponse(stream())
