"""WebSocket /alerts — Isolation Forest anomaly alerts.

The one place apps/api calls packages/ml_models directly (check_anomalies);
everything else goes through rag_agent. Alerts are decision-support: an alert says
this month is unlike the district's own history, never "deploy here".
"""
import asyncio
from datetime import datetime, timedelta, timezone

from data.db import get_session
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ml_models.serving import check_anomalies
from sqlalchemy import text

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
    with get_session() as s:
        return [r.district_code for r in s.execute(text(
            "SELECT DISTINCT district_code FROM fir WHERE district_code IS NOT NULL")).all()]


def _recent(alert) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    at = alert.detected_at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at >= cutoff


@router.websocket("/alerts")
async def alerts(ws: WebSocket):
    await ws.accept()
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
