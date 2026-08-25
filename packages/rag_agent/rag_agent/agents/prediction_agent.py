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


# Plain-language names, and the one caveat an officer must hear. India publishes
# unemployment only at STATE level, so a question about unemployment is answered with
# the district-level measure the Census *does* publish — underemployment — and the
# answer says so rather than quietly substituting one for the other.
FACTOR_LABELS = {
    "literacy_rate": "the literacy rate",
    "poverty_index": "the household poverty rate",
    "marginal_worker_rate": (
        "underemployment (the Census marginal-worker rate — India does not publish "
        "unemployment below state level, so this is the closest real district measure)"
    ),
}


def factor_for(query: str) -> str:
    """Which socioeconomic factor a causal question is about.

    Only the three the Census gives us per district are estimable; anything else
    would need a number we do not have. Poverty is the default because it is the
    factor these questions most often mean.
    """
    q = (query or "").lower()
    if any(w in q for w in ("literacy", "literate", "education", "school")):
        return "literacy_rate"
    if any(w in q for w in ("unemploy", "employ", "job", "work", "labour", "labor", "wage")):
        return "marginal_worker_rate"
    return "poverty_index"


def causal(factor: str, district_code: str):
    """Returns (None, [evidence explaining the gap]) when Census data is absent —
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
            # This IS the answer, not a low-relevance hit — the confidence floor that
            # separates support from noise elsewhere does not apply to a statement
            # declining to estimate. See EvidenceItem.authoritative.
            authoritative=True,
        )]
    lo, hi = est.confidence_interval
    # A CI spanning zero means the data cannot distinguish the effect from none. Say
    # that, rather than quoting a point estimate an officer would read as a finding.
    significant = not (lo <= 0 <= hi)
    label = FACTOR_LABELS.get(factor, factor)

    # Significance is checked BEFORE refutation, and the order matters. Refuting an
    # effect that is already indistinguishable from zero is meaningless — the placebo
    # is being compared against noise — and reporting that as "failed refutation" would
    # state something stronger and more alarming than the data supports. "Not
    # established" is the honest verdict; "refuted" is a different claim entirely.
    if not significant:
        claim = (f"No significant causal effect of {label} on the crime rate is "
                 f"detectable across {est.n_districts} districts: the estimate is "
                 f"{est.effect_size:+.3f} but its 95% CI ({lo:+.3f} to {hi:+.3f}) "
                 f"includes zero. The correct conclusion is 'not established' — not a "
                 f"weak effect, and not a refuted one.")
        confidence = 0.3
    elif not est.refutation_passed:
        claim = (f"An effect of {label} on the crime rate was estimated but FAILED "
                 f"DoWhy's refutation checks ({est.refutation_detail}), so it must not "
                 f"be treated as causal.")
        confidence = 0.1
    else:
        claim = (f"Adjusted for {', '.join(est.confounders_adjusted)} across "
                 f"{est.n_districts} districts, a unit increase in {label} causes a "
                 f"{est.effect_size:+.3f} change in the crime rate per 100k "
                 f"(95% CI {lo:+.3f} to {hi:+.3f}); the estimate survives placebo and "
                 f"random-common-cause refutation.")
        confidence = 0.6
    if est.unmeasured_confounders:
        claim += (f" Not adjusted for {', '.join(est.unmeasured_confounders)} — no "
                  f"district-level data source exists for it, so residual confounding "
                  f"cannot be ruled out.")

    ev = [EvidenceItem(
        evidence_id=f"causal:{factor}:{district_code}",
        source_type="ML_PREDICTION",
        source_id=district_code,
        source_query=f"DoWhy backdoor, adjusted for {est.confounders_adjusted}",
        content=claim,
        confidence=confidence,
    )]
    return est, ev
