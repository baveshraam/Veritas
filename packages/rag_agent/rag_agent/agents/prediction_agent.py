"""Prediction Agent — the only bridge to packages/ml_models.

Never predicts inline; it calls the typed functions and turns their results into
EvidenceItems whose content distinguishes "the model suggests" from "the record
shows". That distinction is a Layer-10 requirement, not a stylistic one: an officer
must be able to tell a prediction from a fact at a glance.

check_anomalies is deliberately absent — apps/api calls it directly for /alerts.
resolve_entities is absent too — it's a batch job run from data/generator.
"""
from datetime import date, timedelta

from ..state import EvidenceItem

HORIZON_DAYS = 30


def _ml():
    from ml_models import serving
    return serving


def hotspots(district_code: str) -> tuple[object, list[EvidenceItem]]:
    ml = _ml()
    end = date.today()
    polys = ml.detect_hotspots(district_code, (end - timedelta(days=730), end))
    ev = [
        EvidenceItem(
            evidence_id=f"hotspot:{district_code}:{i}",
            source_type="GEOSPATIAL_ANALYSIS",
            source_id=f"{district_code}:{i}",
            source_query="KDE (Scott) + DBSCAN(eps=500m, min_samples=10)",
            content=(f"The model identifies a hotspot in {district_code} containing "
                     f"{p.crime_count} incidents (relative density {p.intensity:.2f})."),
            confidence=float(p.intensity),
        )
        for i, p in enumerate(polys, 1)
    ]
    return polys, ev


def forecast(district_code: str, horizon_days: int = HORIZON_DAYS):
    ml = _ml()
    fc = ml.forecast_crime(district_code, horizon_days)
    if not fc.series:
        return fc, []
    total = sum(p for _, p, _, _ in fc.series)
    ev = [EvidenceItem(
        evidence_id=f"forecast:{district_code}",
        source_type="ML_PREDICTION",
        source_id=district_code,
        source_query=f"Prophet + MinT reconciliation, horizon={horizon_days}d",
        content=(f"The model forecasts approximately {total:.0f} FIRs in "
                 f"{district_code} over the next {horizon_days} days "
                 f"({'MinT-reconciled' if fc.reconciled else 'unreconciled'}). "
                 f"This is a projection, not a record."),
        confidence=0.7 if fc.reconciled else 0.5,
    )]
    return fc, ev


def risk(person_id: str):
    ml = _ml()
    r = ml.score_risk(person_id)
    factors = ", ".join(f"{n} ({v:+.2f})" for n, v in r.top_factors)
    ev = [EvidenceItem(
        evidence_id=f"risk:{person_id}",
        source_type="ML_PREDICTION",
        source_id=person_id,
        source_query="XGBoost + SHAP",
        content=(f"The model suggests a risk score of {r.score:.2f} for this person. "
                 f"Top contributing factors: {factors}. This is decision-support, "
                 f"not a finding of fact."),
        confidence=0.6,
    )]
    return r, ev


def recidivism(person_id: str):
    ml = _ml()
    r = ml.predict_recidivism(person_id)
    ev = [EvidenceItem(
        evidence_id=f"recidivism:{person_id}",
        source_type="ML_PREDICTION",
        source_id=person_id,
        source_query="LightGBM (isotonic-calibrated)",
        content=(f"The model estimates a {r.probability_180d:.0%} probability of "
                 f"re-offence within 180 days (calibrated). Decision-support only."),
        confidence=0.6,
    )]
    return r, ev


def transactions(account_id: str):
    ml = _ml()
    flags = ml.flag_transactions(account_id)
    ev = [EvidenceItem(
        evidence_id=f"aml:{f.detector}:{f.txn_id}",
        source_type="ML_PREDICTION",
        source_id=f.txn_id,
        source_query=f"AML detector: {f.detector}",
        content=f.explanation,
        confidence=f.confidence,
    ) for f in flags[:10]]
    return flags, ev


def causal(factor: str, district_code: str):
    """Returns ([], [evidence explaining the gap]) when Census data is absent —
    the Prediction Agent reports the gap rather than inventing an effect size."""
    ml = _ml()
    from ml_models.causal.effects import SocioeconomicDataUnavailable
    try:
        est = ml.estimate_causal_effect(factor, "crime_rate", district_code)
    except SocioeconomicDataUnavailable as e:
        return None, [EvidenceItem(
            evidence_id=f"causal:unavailable:{factor}",
            source_type="ML_PREDICTION",
            source_id=district_code,
            source_query="DoWhy backdoor adjustment",
            content=(f"A causal estimate for {factor} cannot be produced: {e} "
                     f"No correlation is being reported in its place."),
            confidence=0.0,
        )]
    ci = est.confidence_interval
    ev = [EvidenceItem(
        evidence_id=f"causal:{factor}:{district_code}",
        source_type="ML_PREDICTION",
        source_id=district_code,
        source_query=f"DoWhy backdoor, adjusted for {est.confounders_adjusted}",
        content=(f"Adjusted for {', '.join(est.confounders_adjusted)}, a unit change "
                 f"in {factor} is associated with a causal effect of "
                 f"{est.effect_size:+.3f} on the crime rate "
                 f"(95% CI {ci[0]:+.3f} to {ci[1]:+.3f})."),
        confidence=0.6,
    )]
    return est, ev
