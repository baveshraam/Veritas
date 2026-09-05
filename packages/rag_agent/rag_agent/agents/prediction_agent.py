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


def _place(district_code: str) -> str:
    """The district's NAME for anything an officer reads.

    `district_code` is the join key ml_models works in ("KA05"); it is not a word
    any officer uses, and it was being printed verbatim into the two most-demoed
    evidence lines in the system ("a hotspot in KA05", "18 FIRs in KA05"). The
    code stays the identity everywhere internal — evidence_id, source_id — so
    nothing downstream that keys off it changes.
    """
    try:
        from data.districts import canonical_name
        return canonical_name(district_code) or district_code
    except Exception:                                    # noqa: BLE001
        return district_code


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
            content=(f"The model identifies a hotspot in {_place(district_code)} containing "
                     f"{p.crime_count} incidents (relative density {p.intensity:.2f})."),
            # Relative KDE density of THIS cluster — a real per-cluster measurement,
            # not a placeholder weight, so it keeps the default "support" kind.
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
                 f"{_place(district_code)} over the next {horizon_days} days "
                 f"({'MinT-reconciled' if fc.reconciled else 'unreconciled'}). "
                 f"This is a projection, not a record."),
        confidence=0.7 if fc.reconciled else 0.5,
        confidence_kind="model_estimate",
    )]
    return fc, ev


_RISK_BANDS = ["Low", "Moderate", "High", "Severe"]


def _risk_band(score: float) -> str:
    """Headline word first, raw score second — same convention as the
    console's own metrics.ts (influenceReading/densityReading): a bare
    "risk score of 1.00 (NOT calibrated)" tells an officer nothing about
    whether that is alarming; a band does."""
    i = 3 if score >= 0.75 else 2 if score >= 0.5 else 1 if score >= 0.25 else 0
    return _RISK_BANDS[i]


def risk(person_id: str):
    ml = _ml()
    r = ml.score_risk(person_id)
    band = _risk_band(r.score)
    factors = ", ".join(n for n, _ in r.top_factors)
    ev = [EvidenceItem(
        evidence_id=f"risk:{person_id}",
        source_type="ML_PREDICTION",
        source_id=person_id,
        source_query="XGBoost + SHAP",
        content=(f"{band} relative risk — this person ranks in that band among "
                 f"offenders on record (score {r.score:.2f} on a 0-1 ranking scale, "
                 f"{'calibrated' if r.calibrated else 'NOT calibrated — a ranking, not a probability'}). "
                 f"Driven most by: {factors}. This is decision-support, "
                 f"not a finding of fact."),
        confidence=0.6,
        confidence_kind="model_estimate",
    )]
    return r, ev


ADVISORY_HOTSPOT_WINDOW_DAYS = 90


def advisory_for(district_code: str, series_candidates: list[dict] | None = None,
                 fairness_flagged: bool = False) -> dict | None:
    """Fuses hotspot detection, trend forecasting, and cross-station series linkage
    into one proactive read for a district (STRATEGIC_RESET Part 9, Item 2) — today
    an officer combines these three separately-computed outputs mentally. Returns
    None when they don't actually agree on anything: a hotspot with a flat or
    falling forecast isn't news, and neither is a forecast alone without a real
    spatial cluster behind it.

    Advisory only — this never triggers a dispatch or any automated action.
    """
    from data.districts import canonical_name

    ml = _ml()
    end = date.today()
    polys = ml.detect_hotspots(district_code, (end - timedelta(days=ADVISORY_HOTSPOT_WINDOW_DAYS), end))
    if not polys:
        return None
    top = max(polys, key=lambda p: p.intensity)

    fc = ml.forecast_crime(district_code, HORIZON_DAYS)
    if not fc.series:
        return None
    rising = fc.series[-1][1] > fc.series[0][1]
    if not rising:
        return None

    place = canonical_name(district_code) or district_code
    linked = [s for s in (series_candidates or []) if place in (s.get("districts") or [])]

    headline = (f"Elevated likelihood of continued incidents near the known hotspot "
               f"in {place} over the next {HORIZON_DAYS} days, based on "
               f"{top.crime_count} recorded points.")

    # Shown alongside the number, never folded into it — an advisory that hides its
    # own caveats inside a confidence figure is the failure this project's whole
    # provenance design exists to avoid.
    disclosures = [
        # ponytail: a static, already-documented disclosure (CLAUDE.md §9) rather
        # than a fresh DoWhy causal run per district per refresh cycle — the
        # confounder itself doesn't change day to day. Upgrade to a live causal
        # estimate here if a district-level policing-intensity figure ever exists.
        "Not adjusted for police strength — not published per district in India; "
        "residual confounding in this reading cannot be ruled out.",
    ]
    if linked:
        disclosures.append(
            f"{len(linked)} open cross-station series already touch this district — "
            "see Series Discovery for the linked cases.")
    if fairness_flagged:
        disclosures.append(
            "The risk model's own Aequitas audit currently flags a disparate-impact "
            "concern — read any risk-based reasoning about this district with that in mind.")

    return {
        "district_code": district_code,
        "district": place,
        "headline": headline,
        "expected_total_incidents": round(sum(p for _, p, _, _ in fc.series)),
        "hotspot_intensity": round(top.intensity, 2),
        "disclosures": disclosures,
    }


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
        confidence_kind="model_estimate",
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
        # A fixed weight by significance tier (established/failed-refutation/not-
        # established), not a per-estimate score — the real numbers (effect size, CI)
        # are in `claim`. Same reasoning as risk/forecast below.
        confidence=confidence,
        confidence_kind="model_estimate",
        # ALL THREE verdicts are authoritative, including — especially — the two
        # negative ones. This number measures the STRENGTH OF THE CAUSAL CLAIM; the
        # CRAG evaluator's RELEVANCE_FLOOR measures whether an item is about the
        # question at all. Without this flag the two were conflated, so "not
        # established" (0.3) and "failed refutation" (0.1) both fell under the floor,
        # the batch scored as context-only, and the entire causal layer answered
        # "I could not find this in the available records" to every question it was
        # built for (found live 2026-09-06 — every phrasing of the §9 socio-economic
        # question refused). A rigorously-established absence of effect IS the
        # finding; reporting it as a retrieval failure states something weaker AND
        # less honest than the analysis actually supports. Exactly the distinction
        # the "cannot estimate" branch above already makes for the same reason.
        authoritative=True,
    )]
    return est, ev
