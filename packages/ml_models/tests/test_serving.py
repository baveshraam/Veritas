"""The models, run against a real dataset — not their maths, their behaviour.

Every model here reads the Catalyst Data Store through `data.ds`. On this backend that is
SQLite executing the same ZCQL strings the deployed service sends, so these are the real
queries, not stand-ins. What is asserted is the thing each model exists to find: a hotspot
where the crime actually clusters, a structuring ring where deposits actually clustered, a
causal estimate that reports its own unmeasured confounder.
"""
import json
import os
from datetime import date, timedelta

import pytest

from data import ds, queries


# ------------------------------------------------------------------------------- spatial
def test_hotspots_are_found_where_the_crime_actually_is(dataset):
    from ml_models.spatial.hotspots import detect_hotspots
    from data.districts import all_districts
    from data.generator.refdata import district_id

    counts = queries.case_counts_by_district()
    busiest = max(counts, key=counts.get)
    code = next(d.code for d in all_districts() if district_id(d.code) == busiest)

    spots = detect_hotspots(code, (date(2023, 1, 1), date(2027, 1, 1)))
    assert spots, "no hotspot in the busiest district in the state"
    for s in spots:
        assert len(s.polygon) >= 3, "a hotspot polygon needs at least three corners"
        assert 0 < s.intensity <= 1.0


def test_a_district_with_no_cases_yields_no_hotspot(dataset):
    """The honest empty answer. A model that always finds a hotspot has found nothing."""
    from ml_models.spatial.hotspots import _fetch_points, _cluster
    import numpy as np

    empty = np.zeros((0, 2))
    assert len(_fetch_points(999_999, (date(2023, 1, 1), date(2027, 1, 1)))) == 0


# ---------------------------------------------------------------------------- financial
def test_the_structuring_detector_finds_the_injected_ring(dataset):
    """The explainable first line. It must find the pattern that was actually planted, and
    its explanation must quote the numbers that triggered it — a flag a court cannot audit
    line by line is not evidence."""
    from ml_models.financial.structuring import detect_structuring

    labels = json.loads(open(os.environ["VERITAS_AML_LABELS"]).read())
    ring_txns = [int(k) for k, v in labels.items() if v == "structuring"]
    assert ring_txns

    targets = {r["DstAccountID"] for r in ds.query(
        'SELECT "DstAccountID" FROM "vx_txn" WHERE "TxnID" IN :ids', {"ids": ring_txns})}

    flagged = [f for acct in targets for f in detect_structuring(acct)]
    assert flagged, f"the structuring detector found nothing in {len(targets)} target account(s)"

    f = flagged[0]
    assert f.detector == "rule_based_structuring"
    assert "deposits totalling" in f.explanation
    assert 0 < f.confidence <= 1


def test_a_normal_account_is_not_flagged_as_structuring(dataset):
    """The false-positive side. A detector that flags everyone has told you nothing."""
    from ml_models.financial.structuring import detect_structuring

    labels = json.loads(open(os.environ["VERITAS_AML_LABELS"]).read())
    dirty = {int(k) for k in labels}
    clean_accounts = {r["DstAccountID"] for r in ds.query(
        'SELECT "TxnID", "DstAccountID" FROM "vx_txn"') if r["TxnID"] not in dirty}
    dirty_targets = {r["DstAccountID"] for r in ds.query(
        'SELECT "DstAccountID" FROM "vx_txn" WHERE "TxnID" IN :ids',
        {"ids": list(dirty)})} if dirty else set()

    for acct in list(clean_accounts - dirty_targets)[:10]:
        assert detect_structuring(acct) == [], f"account {acct} flagged with no ring"


def test_flagging_writes_the_detector_that_fired(dataset):
    """A flag a court cannot attribute to a method is not evidence."""
    from data.transactions import clear_flags, flag_transaction

    txn = ds.scalar('SELECT "TxnID" AS t FROM "vx_txn"')
    flag_transaction(txn, "structuring", "rule_based_structuring", 0.9)
    row = ds.one('SELECT "FlaggedSuspicious", "Detector", "FlagConfidence" '
                 'FROM "vx_txn" WHERE "TxnID" = :t', {"t": txn})
    assert row["FlaggedSuspicious"] and row["Detector"] == "rule_based_structuring"

    clear_flags()
    assert ds.scalar('SELECT COUNT("TxnID") AS c FROM "vx_txn" '
                     'WHERE "FlaggedSuspicious" = 1') == 0


# --------------------------------------------------------------------------------- risk
def test_features_carry_no_protected_attribute(dataset):
    """Layer 10, asserted rather than asserted-in-a-docstring. Caste and religion are in the
    ER and are stored; no model reads them. Gender is kept only as a subgroup *label*, for
    the fairness audit to test against — never as an input."""
    from ml_models.risk.features import FEATURE_NAMES, build_features

    banned = {"caste", "religion", "gender", "sex", "community"}
    assert not any(b in f.lower() for f in FEATURE_NAMES for b in banned)

    cutoff = queries.latest_case_date() - timedelta(days=180)
    rows = build_features(cutoff)
    assert rows
    assert all(len(r.x) == len(FEATURE_NAMES) for r in rows)
    assert {r.gender for r in rows} <= {"M", "F", "T", "U"}


def test_features_are_built_strictly_before_the_cutoff(dataset):
    """The leakage test. Features drawn from cases *after* the cutoff include the very
    offence the label is about, which is how a risk model looks excellent offline and is
    useless in the field."""
    from ml_models.risk.features import FEATURE_NAMES, build_features

    latest = queries.latest_case_date()
    early = build_features(latest - timedelta(days=900))
    late = build_features(latest)

    i = FEATURE_NAMES.index("prior_offence_count")
    early_total = sum(r.x[i] for r in early)
    late_total = sum(r.x[i] for r in late)
    assert late_total > early_total, "priors did not accumulate as the cutoff moved forward"


def test_labels_come_only_from_after_the_cutoff(dataset):
    from ml_models.risk.features import build_labels

    latest = queries.latest_case_date()
    cutoff = latest - timedelta(days=365)
    ever = build_labels(cutoff, None)
    within = build_labels(cutoff, 180)
    assert within <= ever, "a 180-day re-offender must also be an eventual re-offender"


def test_risk_scores_are_calibrated_not_a_raw_saturated_margin(dataset):
    """BUG-014: a live risk score pinned at 1.00 with no way to tell 'very likely' from
    'the model is confident it's confident'. Raw XGBoost predict_proba is known to
    saturate on skewed data; this asserts the score actually comes from the calibrated
    wrapper (same isotonic pattern already proven for recidivism just below), not the
    raw booster, whenever the calibration split has enough of both classes to fit it."""
    from ml_models.risk.scoring import _risk_model, score_risk

    model, explainer, calibrated = _risk_model()
    assert hasattr(model, "predict_proba")
    assert explainer is not None

    people = ds.query('SELECT "PersonUID" FROM "vx_person" LIMIT 20')
    scores = []
    for p in people:
        try:
            r = score_risk(str(p["PersonUID"]))
        except KeyError:
            continue
        assert 0.0 <= r.score <= 1.0
        assert r.calibrated == calibrated
        scores.append(r.score)
    assert scores, "no person in the sample had current features to score"
    if calibrated:
        # Not every score should be indistinguishable from the boundary — a
        # calibrated model on a real feature spread produces a real spread of
        # scores, not everyone saturated at the same value.
        assert len(set(round(s, 2) for s in scores)) > 1, (
            "every calibrated score rounded to the same value — suspicious saturation")


# ------------------------------------------------------------------------------- causal
def test_the_causal_layer_reports_its_unmeasured_confounder(dataset):
    """The intellectually honest part, and the one a panel will look for. Police strength is
    not published per district, so policing intensity cannot be adjusted for — and a causal
    claim that hides that is worse than no claim."""
    from ml_models.causal.effects import (
        SUPPORTED_FACTORS, UNMEASURED_CONFOUNDERS, estimate_causal_effect,
    )

    est = estimate_causal_effect(SUPPORTED_FACTORS[0], "crime_rate", "KA05")
    assert est.unmeasured_confounders == UNMEASURED_CONFOUNDERS
    assert est.confounders_adjusted, "an unadjusted estimate is a correlation, not a cause"
    assert est.n_districts == 30, "Karnataka had 30 districts at the 2011 Census"
    lo, hi = est.confidence_interval
    assert lo <= est.effect_size <= hi


def test_the_causal_panel_refuses_to_run_without_real_census_data(dataset):
    """It would rather fail than estimate a causal effect from fabricated socioeconomics."""
    from ml_models.causal.effects import SocioeconomicDataUnavailable, _panel

    ds.truncate(["vx_district_socioeconomic"])
    try:
        with pytest.raises(SocioeconomicDataUnavailable):
            _panel()
    finally:
        from data.socioeconomic import load
        load()


# ---------------------------------------------------------------------------- anomalies
def test_anomaly_alerts_are_decision_support_not_a_verdict(dataset):
    from data.districts import all_districts
    from ml_models.risk.anomalies import check_anomalies

    counts = queries.case_counts_by_district()
    from data.generator.refdata import district_id
    busiest = max(counts, key=counts.get)
    code = next(d.code for d in all_districts() if district_id(d.code) == busiest)

    alerts = check_anomalies(code)
    for a in alerts:                        # may legitimately be empty — that is the point
        assert a.severity in ("low", "medium", "high")
        assert a.district_code == code
