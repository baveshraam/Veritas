"""Risk scoring (XGBoost + SHAP) and 180-day recidivism (calibrated LightGBM).

Both are trained on a temporal split — features strictly before a cutoff, label
strictly after — so the model is predicting the future rather than memorising it.
The cutoff is placed one label-window back from the latest FIR, leaving a real
holdout period.

Every output is decision-support: a score plus the SHAP factors that produced it,
in plain language. Nothing here is wired to an automated action.
"""
from datetime import timedelta
from functools import lru_cache

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split

from ..types import RecidivismResult, RiskResult
from .features import (
    FEATURE_LABELS, FEATURE_NAMES, build_features, build_labels, latest_fir_date,
)

RECIDIVISM_WINDOW_DAYS = 180
_RISK_HOLDOUT_DAYS = 365


class ModelUnavailable(RuntimeError):
    """Not enough history (or not enough positives) to fit an honest model."""


def _training_set(window_days: int | None, holdout_days: int):
    latest = latest_fir_date()
    if latest is None:
        raise ModelUnavailable("no FIR data loaded")
    cutoff = latest - timedelta(days=holdout_days)

    rows = build_features(cutoff)
    positives = build_labels(cutoff, window_days)
    if not rows:
        raise ModelUnavailable("no person rows")

    X = np.vstack([r.x for r in rows])
    y = np.array([1 if r.person_id in positives else 0 for r in rows])
    if y.sum() < 10 or (len(y) - y.sum()) < 10:
        raise ModelUnavailable(
            f"insufficient label balance to train ({int(y.sum())} positives of {len(y)})")
    return X, y, rows, cutoff


class _XGBShap:
    """TreeSHAP through xgboost's own `pred_contribs` — the exact per-feature
    attributions shap.TreeExplainer computes for an XGBoost ensemble, minus the
    shap→numba→llvmlite import chain (~240MB) the deployed image cannot afford
    under AppSail's bundle-sandbox size cap."""

    def __init__(self, model) -> None:
        self._booster = model.get_booster()

    def shap_values(self, x: np.ndarray) -> np.ndarray:
        import xgboost as xgb

        contribs = self._booster.predict(xgb.DMatrix(x), pred_contribs=True)
        return contribs[:, :-1]                     # last column is the bias term


def _fit_base(Xtr, ytr):
    from xgboost import XGBClassifier

    model = XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.08,
        subsample=0.9, colsample_bytree=0.9, eval_metric="logloss",
        random_state=0,
    )
    model.fit(Xtr, ytr)
    return model


@lru_cache(maxsize=1)
def _risk_model():
    """Calibrated on a held-out split, same reasoning as `_recidivism_model` below.

    Raw XGBoost `predict_proba` is a margin-derived score, not a probability — it
    routinely saturates near 0/1 on skewed data (observed live: a reported 1.00 with
    no way to tell "very likely" from "the model is just confident it's confident").
    `cv="prefit"` calibrates a *second* fit on a held-out split while leaving `base`
    itself untouched, so TreeSHAP still explains the real fitted booster rather than
    an ensemble of calibration folds. If the calibration split lacks enough of both
    classes to fit isotonic regression, the raw (uncalibrated) model is used instead
    and reported as such — a failed calibration must not be reported as a successful
    one.
    """
    X, y, _, _ = _training_set(window_days=None, holdout_days=_RISK_HOLDOUT_DAYS)
    Xtr, Xcal, ytr, ycal = train_test_split(X, y, test_size=0.3, random_state=0, stratify=y)
    base = _fit_base(Xtr, ytr)
    explainer = _XGBShap(base)

    if ycal.sum() < 5 or (len(ycal) - ycal.sum()) < 5:
        return base, explainer, False

    try:
        calibrated = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
        calibrated.fit(Xcal, ycal)
    except ValueError:
        return base, explainer, False
    return calibrated, explainer, True


@lru_cache(maxsize=1)
def _recidivism_model():
    from lightgbm import LGBMClassifier

    X, y, _, _ = _training_set(window_days=RECIDIVISM_WINDOW_DAYS,
                               holdout_days=RECIDIVISM_WINDOW_DAYS + 180)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=0, stratify=y)
    base = LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05,
                          random_state=0, verbose=-1)
    # Calibrated probabilities, not raw scores: an officer reading "0.7" must be able
    # to take it as ~70% of such people re-offending, or the number is theatre.
    model = CalibratedClassifierCV(base, method="isotonic", cv=3)
    model.fit(Xtr, ytr)
    return model


def _current_features(person_id: str):
    latest = latest_fir_date()
    if latest is None:
        raise ModelUnavailable("no FIR data loaded")
    for r in build_features(latest + timedelta(days=1)):   # everything known to date
        if r.person_id == person_id:
            return r
    raise KeyError(f"unknown person_id {person_id}")


def score_risk(person_id: str) -> RiskResult:
    model, explainer, calibrated = _risk_model()
    row = _current_features(person_id)
    x = row.x.reshape(1, -1)

    score = float(model.predict_proba(x)[0][1])
    shap_values = explainer.shap_values(x)[0]

    factors = sorted(
        ((FEATURE_LABELS[FEATURE_NAMES[i]], float(shap_values[i]))
         for i in range(len(FEATURE_NAMES))),
        key=lambda t: -abs(t[1]),
    )[:4]
    return RiskResult(person_id=person_id, score=round(score, 4), top_factors=factors,
                      calibrated=calibrated)


def predict_recidivism(person_id: str) -> RecidivismResult:
    model = _recidivism_model()
    row = _current_features(person_id)
    prob = float(model.predict_proba(row.x.reshape(1, -1))[0][1])
    return RecidivismResult(person_id=person_id,
                            probability_180d=round(prob, 4),
                            calibrated=True)
