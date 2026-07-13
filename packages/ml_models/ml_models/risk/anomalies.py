"""District-level spike detection — Isolation Forest over monthly crime counts.

Called directly by apps/api for the /alerts WebSocket (not via rag_agent).
Decision-support only: an alert says "this month is unlike this district's own
history", never "deploy here".
"""
import uuid
from datetime import datetime

import numpy as np
from sklearn.ensemble import IsolationForest

from data import ds, queries

from ..types import AnomalyAlert

MIN_MONTHS = 12          # below a year of history an "anomaly" is just noise


def _monthly_counts(district_id: int) -> list[tuple[datetime, int]]:
    """Monthly case counts for one district. Bucketed here because ZCQL has no
    date_trunc — and one district's cases are a few thousand rows."""
    counts: dict[datetime, int] = {}
    for r in queries.cases_in_district(district_id):
        d = ds.to_dt(r["CrimeRegisteredDate"])
        if d is None:
            continue
        month = datetime(d.year, d.month, 1)
        counts[month] = counts.get(month, 0) + 1
    return sorted(counts.items())


def _severity(observed: float, expected: float, sigma: float) -> str:
    if sigma <= 0:
        return "low"
    z = abs(observed - expected) / sigma
    if z >= 3:
        return "high"
    if z >= 2:
        return "medium"
    return "low"


def check_anomalies(district_code: str) -> list[AnomalyAlert]:
    series = _monthly_counts(queries.district_id(district_code))
    if len(series) < MIN_MONTHS:
        return []

    counts = np.array([c for _, c in series], dtype=float)
    # Contamination left at 'auto' — hardcoding an expected anomaly rate would
    # manufacture alerts in districts that simply had a quiet year.
    forest = IsolationForest(random_state=0, contamination="auto")
    flags = forest.fit_predict(counts.reshape(-1, 1))

    expected = float(np.median(counts))
    sigma = float(np.std(counts))

    alerts: list[AnomalyAlert] = []
    for (month, count), flag in zip(series, flags):
        if flag != -1 or count <= expected:
            continue          # only surface upward spikes; a quiet month isn't an alert
        alerts.append(AnomalyAlert(
            alert_id=str(uuid.uuid4()),
            district_code=district_code,
            metric="monthly_fir_count",
            observed=float(count),
            expected=round(expected, 2),
            severity=_severity(count, expected, sigma),
            detected_at=month if isinstance(month, datetime) else datetime.now(),
        ))
    return sorted(alerts, key=lambda a: -a.observed)
