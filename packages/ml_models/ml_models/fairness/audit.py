"""Aequitas bias audit (Saleiro et al., 2018, UChicago DSaPP).

Predictive policing has a documented history of laundering historical policing bias
into an apparently-objective score. This audit is the check on our own models, and
it is a build artifact, not a slide: run it before every demo.

Computes per-subgroup FPR/FNR/selection-rate and the disparate-impact ratio against
the largest reference group, across the subgroups we can honestly test:
  - gender  — retained as a *label*, never used as a model feature
  - district — the geographic axis where over-policing feedback loops actually show up

Called only from `fairness/run_audit.py`, by hand or CI. Never on a request path.

The 80% rule (selection-rate ratio < 0.8 or > 1.25) is the flag threshold, following
the EEOC convention Aequitas adopts.
"""
from datetime import datetime, timezone

import numpy as np

from data import queries

from ..types import AequitasReport

DISPARITY_FLOOR = 0.8
DISPARITY_CEILING = 1.25
MIN_GROUP_SIZE = 20


def _district_by_person() -> dict[str, str]:
    """Person -> the district they most often appear in, for geographic subgroups.

    Geographic subgroups are the whole point of auditing a *policing* model: over-policing
    a district produces more recorded crime there, which a naive model then "predicts".
    This is the axis that catches it.
    """
    tally: dict[str, dict[int, int]] = {}
    for r in queries.accused_with_cases():
        pid = str(r["PersonUID"])
        tally.setdefault(pid, {})
        tally[pid][r["DistrictID"]] = tally[pid].get(r["DistrictID"], 0) + 1
    return {pid: str(max(d, key=d.get)) for pid, d in tally.items() if d}


def _group_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    return {
        "group_size": float(len(y_true)),
        "selection_rate": float((y_pred == 1).mean()) if len(y_pred) else 0.0,
        "fpr": fp / (fp + tn) if (fp + tn) else 0.0,
        "fnr": fn / (fn + tp) if (fn + tp) else 0.0,
        "base_rate": float((y_true == 1).mean()) if len(y_true) else 0.0,
    }


def run_fairness_audit(model_name: str) -> AequitasReport:
    """Audit over the model's own temporal holdout.

    The cutoff MUST be the one the model was trained against, and the features must
    be the ones as-of that cutoff. Auditing with features as-of *today* against
    labels "after today" gives an empty label set — every base rate collapses to 0,
    FNR is undefined, and FPR degenerates into the selection rate, so the report
    looks clean for the worst possible reason.
    """
    from ..risk.scoring import (
        _RISK_HOLDOUT_DAYS, RECIDIVISM_WINDOW_DAYS,
        _recidivism_model, _risk_model, _training_set,
    )

    if model_name not in ("score_risk", "predict_recidivism"):
        raise ValueError(f"unknown model {model_name!r}")

    if model_name == "score_risk":
        model, _, _ = _risk_model()
        X, y_true, rows, _cutoff = _training_set(None, _RISK_HOLDOUT_DAYS)
    else:
        model = _recidivism_model()
        X, y_true, rows, _cutoff = _training_set(
            RECIDIVISM_WINDOW_DAYS, RECIDIVISM_WINDOW_DAYS + 180)

    y_pred = (model.predict_proba(X)[:, 1] >= 0.5).astype(int)
    districts = _district_by_person()
    groups = [(f"gender={r.gender}",
               f"district={districts.get(r.person_id, 'unknown')}") for r in rows]

    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)

    metrics: dict[str, dict[str, float]] = {}
    for axis in (0, 1):
        labels = np.array([g[axis] for g in groups])
        for g in sorted(set(labels)):
            mask = labels == g
            if mask.sum() < MIN_GROUP_SIZE:
                continue          # a 'disparity' over 4 people is noise, not bias
            metrics[g] = _group_metrics(y_true[mask], y_pred[mask])

    flagged = _flag_disparate_impact(metrics)
    return AequitasReport(
        model_name=model_name,
        metrics_by_subgroup={k: {m: round(v, 4) for m, v in vals.items()}
                             for k, vals in metrics.items()},
        disparate_impact_flagged=flagged,
        generated_at=datetime.now(timezone.utc),
    )


def _flag_disparate_impact(metrics: dict[str, dict[str, float]]) -> bool:
    """Compare each subgroup's selection rate to its axis's largest group (the
    reference), per the 80% rule."""
    for axis in ("gender=", "district="):
        axis_groups = {k: v for k, v in metrics.items() if k.startswith(axis)}
        if len(axis_groups) < 2:
            continue
        ref = max(axis_groups.values(), key=lambda v: v["group_size"])
        ref_rate = ref["selection_rate"]
        if ref_rate == 0:
            continue
        for vals in axis_groups.values():
            ratio = vals["selection_rate"] / ref_rate
            if ratio < DISPARITY_FLOOR or ratio > DISPARITY_CEILING:
                return True
    return False
