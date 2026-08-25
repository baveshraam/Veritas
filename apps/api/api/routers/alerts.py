"""WebSocket /alerts — Isolation Forest anomaly alerts.

The one place apps/api calls packages/ml_models directly (check_anomalies);
everything else goes through rag_agent. Alerts are decision-support: an alert says
this month is unlike the district's own history, never "deploy here".
"""
import asyncio
from datetime import datetime, timedelta, timezone

from data import ds
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ml_models.serving import check_anomalies

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


# A browser WebSocket cannot set an Authorization header, and putting a bearer token in
# the URL writes officer identity into every access log and proxy trace — which the rest
# of this API deliberately avoids. So the token is the first frame the client sends, and
# nothing is streamed until it verifies. Previously this route called ws.accept() and
# began pushing district anomaly data to anyone who connected.
AUTH_TIMEOUT_SECONDS = 10


@router.websocket("/alerts")
async def alerts(ws: WebSocket):
    from fastapi import HTTPException

    from ..auth.jwt_auth import officer_from_token

    await ws.accept()
    try:
        token = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SECONDS)
        officer_from_token(token.strip())
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await ws.close(code=1008, reason="No credential presented")
        return
    except HTTPException as exc:
        await ws.close(code=1008, reason=str(exc.detail))
        return

    seen: set[str] = set()
    loop = asyncio.get_running_loop()
    try:
        while True:
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
                await ws.send_json(alert.model_dump(mode="json"))
            await asyncio.sleep(POLL_SECONDS)
    except WebSocketDisconnect:
        return
