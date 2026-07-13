"""Crime forecasting — Prophet per level, reconciled with MinT.

Prophet is fitted independently at each level of the hierarchy (district and its
police stations). Independent forecasts are *incoherent*: the district's own
forecast won't equal the sum of its stations'. MinT (Wickramasuriya,
Athanasopoulos & Hyndman, 2019, JASA) projects the base forecasts onto the
coherent subspace, minimising the trace of the reconciled error covariance —
statistically optimal, not just "close enough".

    y~ = S (S' W^-1 S)^-1 S' W^-1  y^

with S the summing matrix and W the base-forecast error covariance. We use the
diagonal (WLS) estimator of W from in-sample residual variances — the standard
choice when the full covariance is not reliably estimable from short series.

The hierarchy is rooted at the requested district (district = sum of its stations),
which is exactly the coherence property the architecture promises, and keeps the
number of Prophet fits small enough to serve a live query.
"""
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
from data import ds, queries

from ..types import ForecastResult

logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

MIN_POINTS = 20          # Prophet needs a real series, not three dots


def _daily_counts(district_id: int) -> pd.DataFrame:
    """Long frame: one row per (station, day) with the case count, zero-filled.

    The daily aggregation is done here, not in the query: ZCQL has no date_trunc. The rows
    are one district's cases — thousands, not millions.
    """
    rows = queries.cases_in_district(district_id)
    rows = [r for r in rows if r["CrimeRegisteredDate"]]
    if not rows:
        return pd.DataFrame(columns=["ps_code", "ds", "y"])

    df = pd.DataFrame([{"ps_code": r["PoliceStationID"],
                        "ds": ds.to_dt(r["CrimeRegisteredDate"])} for r in rows])
    df["ds"] = pd.to_datetime(df["ds"]).dt.normalize()
    df = df.groupby(["ps_code", "ds"]).size().reset_index(name="y")
    # zero-fill: a day with no FIR is a real zero, not a gap
    full = pd.MultiIndex.from_product(
        [df["ps_code"].unique(),
         pd.date_range(df["ds"].min(), df["ds"].max(), freq="D")],
        names=["ps_code", "ds"])
    return (df.set_index(["ps_code", "ds"]).reindex(full, fill_value=0)
              .reset_index().astype({"y": float}))


def _fit_prophet(series: pd.DataFrame, horizon: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Returns (point forecast, [lower, upper], residual variance)."""
    from prophet import Prophet

    m = Prophet(weekly_seasonality=True, yearly_seasonality=True,
                daily_seasonality=False, interval_width=0.8)
    m.fit(series[["ds", "y"]])
    future = m.make_future_dataframe(periods=horizon)
    fc = m.predict(future)

    in_sample = fc.iloc[:len(series)]
    resid_var = float(np.var(series["y"].values - in_sample["yhat"].values)) or 1.0

    tail = fc.iloc[-horizon:]
    point = tail["yhat"].to_numpy()
    bounds = np.vstack([tail["yhat_lower"].to_numpy(), tail["yhat_upper"].to_numpy()])
    return point, bounds, resid_var


def _mint_reconcile(base: np.ndarray, resid_var: np.ndarray, n_bottom: int) -> np.ndarray:
    """base: (1+n, h) — row 0 is the district total, rows 1.. are its stations,
    columns are horizon steps. Returns (h, 1+n) reconciled forecasts.

    S stacks the aggregation (a row of ones) on top of the identity over the bottom
    level, so the reconciled district forecast is exactly the sum of its stations.
    """
    S = np.vstack([np.ones((1, n_bottom)), np.eye(n_bottom)])       # (1+n, n)
    W_inv = np.diag(1.0 / np.maximum(resid_var, 1e-6))              # (1+n, 1+n)
    # G = (S' W^-1 S)^-1 S' W^-1  — the MinT projection onto the coherent subspace
    G = np.linalg.pinv(S.T @ W_inv @ S) @ S.T @ W_inv               # (n, 1+n)
    return (S @ G @ base).T                                          # (h, 1+n)


def forecast_crime(district_code: str, horizon_days: int) -> ForecastResult:
    df = _daily_counts(queries.district_id(district_code))
    if df.empty:
        return ForecastResult(level="district", series=[], reconciled=False)

    stations = sorted(df["ps_code"].unique())
    district = (df.groupby("ds", as_index=False)["y"].sum())

    if len(district) < MIN_POINTS:
        return ForecastResult(level="district", series=[], reconciled=False)

    # base forecasts: the district in its own right, plus each station
    points, bounds, variances = [], [], []
    d_point, d_bounds, d_var = _fit_prophet(district, horizon_days)
    points.append(d_point); bounds.append(d_bounds); variances.append(d_var)

    usable_stations = []
    for ps in stations:
        s = df[df["ps_code"] == ps][["ds", "y"]]
        if len(s) < MIN_POINTS or s["y"].sum() == 0:
            continue
        p, b, v = _fit_prophet(s, horizon_days)
        points.append(p); bounds.append(b); variances.append(v)
        usable_stations.append(ps)

    dates = [district["ds"].max().date() + timedelta(days=i + 1) for i in range(horizon_days)]

    if not usable_stations:
        # nothing to reconcile against — return the district's own Prophet output,
        # honestly flagged as unreconciled rather than pretending MinT ran.
        series = [(dates[i], float(d_point[i]), float(d_bounds[0][i]), float(d_bounds[1][i]))
                  for i in range(horizon_days)]
        return ForecastResult(level="district", series=_clip(series), reconciled=False)

    base = np.vstack(points)                       # (1+n, h)
    reconciled = _mint_reconcile(base, np.array(variances), len(usable_stations))  # (h, 1+n)

    # keep the base forecast's interval *width*, recentred on the reconciled point
    lower_w = d_point - d_bounds[0]
    upper_w = d_bounds[1] - d_point
    series = []
    for i in range(horizon_days):
        pt = float(reconciled[i][0])
        series.append((dates[i], pt, pt - float(lower_w[i]), pt + float(upper_w[i])))
    return ForecastResult(level="district", series=_clip(series), reconciled=True)


def _clip(series: list[tuple[date, float, float, float]]):
    """Crime counts can't be negative — Prophet's Gaussian tails can be."""
    return [(d, max(0.0, round(p, 2)), max(0.0, round(lo, 2)), max(0.0, round(hi, 2)))
            for d, p, lo, hi in series]
