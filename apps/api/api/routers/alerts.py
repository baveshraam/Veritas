"""WebSocket /alerts — Isolation Forest anomaly alerts.

The one place apps/api calls packages/ml_models directly (check_anomalies);
everything else goes through rag_agent. Alerts are decision-support: an alert says
this month is unlike the district's own history, never "deploy here".
"""
import asyncio

from data.db import get_session
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ml_models.serving import check_anomalies
from sqlalchemy import text

router = APIRouter()

POLL_SECONDS = 30


def _districts() -> list[str]:
    with get_session() as s:
        return [r.district_code for r in s.execute(text(
            "SELECT DISTINCT district_code FROM fir WHERE district_code IS NOT NULL")).all()]


@router.websocket("/alerts")
async def alerts(ws: WebSocket):
    await ws.accept()
    seen: set[str] = set()
    loop = asyncio.get_running_loop()
    try:
        while True:
            for dc in await loop.run_in_executor(None, _districts):
                for alert in await loop.run_in_executor(None, check_anomalies, dc):
                    key = f"{alert.district_code}:{alert.detected_at:%Y-%m}"
                    if key in seen:
                        continue      # don't re-push the same spike every poll
                    seen.add(key)
                    await ws.send_json(alert.model_dump(mode="json"))
            await asyncio.sleep(POLL_SECONDS)
    except WebSocketDisconnect:
        return
