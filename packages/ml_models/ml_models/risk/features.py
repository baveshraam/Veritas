"""Feature construction for the risk and recidivism models.

Responsible-AI constraint (non-negotiable, Layer 10): no caste, no religion, no direct
proxies. The ER *records* CasteID and ReligionID — the organizers' schema declares them —
and they are stored, but no model reads them. Storing is not scoring. Gender is excluded
from the feature set too, since it is protected and adds nothing the offending history does
not already carry, but it is retained as a *subgroup label* so the Aequitas audit can test
for disparate impact across it.

Labels are built with a temporal cutoff: features come only from cases BEFORE the cutoff,
the label from cases AFTER it. Training on features that include the very offence you are
predicting is the classic leakage that makes a risk model look excellent offline and
useless in the field.

Everything here keys on `PersonUID`, not `AccusedMasterID`. On the raw ER a man charged
four times is four unrelated rows, so "prior offence count" would be 0 for everyone and the
model would correctly learn that priors predict nothing. Identity resolution is what makes
this feature set mean anything.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from data import ds, queries

CONVICTED_STATUS_ID = 3          # CaseStatusMaster: 1 Under Investigation .. 3 Convicted
NEVER_OFFENDED_GAP = 3650        # a long, capped gap — not an infinity the model must fit

FEATURE_NAMES = [
    "age",
    "prior_offence_count",
    "distinct_crime_types",
    "conviction_count",
    "co_accused_degree",
    "days_since_last_offence",
]

# Plain-language names for the SHAP explanation shown to officers.
FEATURE_LABELS = {
    "age": "age",
    "prior_offence_count": "number of prior recorded offences",
    "distinct_crime_types": "variety of offence types",
    "conviction_count": "prior convictions",
    "co_accused_degree": "number of known co-accused associates",
    "days_since_last_offence": "time since last recorded offence",
}


@dataclass
class FeatureRow:
    person_id: str              # PersonUID
    gender: str                 # subgroup label for the fairness audit, NOT a feature
    x: np.ndarray


def _accused_rows() -> list[dict]:
    """Every accused row, resolved to a person, with its case's date, status and type."""
    rows = ds.query(
        'SELECT "vx_accused_identity"."PersonUID", "Accused"."AgeYear", '
        '       "Accused"."GenderID", "Accused"."CaseMasterID", '
        '       "CaseMaster"."CrimeRegisteredDate", "CaseMaster"."CrimeMinorHeadID", '
        '       "CaseMaster"."CaseStatusID" '
        'FROM "vx_accused_identity" '
        'JOIN "Accused" '
        '  ON "vx_accused_identity"."AccusedMasterID" = "Accused"."AccusedMasterID" '
        'JOIN "CaseMaster" ON "Accused"."CaseMasterID" = "CaseMaster"."CaseMasterID"')
    for r in rows:
        dt = ds.to_dt(r["CrimeRegisteredDate"])
        r["filed"] = dt.date() if dt else None
    return rows


def _co_accused_degree(rows: list[dict], cutoff: date) -> dict[int, int]:
    """Distinct people each person was accused alongside, before the cutoff."""
    by_case: dict[int, set[int]] = {}
    for r in rows:
        if r["filed"] and r["filed"] < cutoff:
            by_case.setdefault(r["CaseMasterID"], set()).add(r["PersonUID"])
    degree: dict[int, set[int]] = {}
    for people in by_case.values():
        for p in people:
            degree.setdefault(p, set()).update(people - {p})
    return {p: len(assoc) for p, assoc in degree.items()}


def build_features(cutoff: date) -> list[FeatureRow]:
    """One row per person, from their record *strictly before* `cutoff`."""
    rows = _accused_rows()
    degree = _co_accused_degree(rows, cutoff)

    agg: dict[int, dict] = {}
    for r in rows:
        p = agg.setdefault(r["PersonUID"], {
            "gender": r["GenderID"], "age": r["AgeYear"], "priors": 0, "types": set(),
            "convictions": 0, "last": None})
        # The most recent recorded age is the best estimate we have — the ER stores age at
        # the time of the case, not a date of birth.
        if r["AgeYear"]:
            agg[r["PersonUID"]]["age"] = r["AgeYear"]
        if not (r["filed"] and r["filed"] < cutoff):
            continue
        p["priors"] += 1
        p["types"].add(r["CrimeMinorHeadID"])
        if r["CaseStatusID"] == CONVICTED_STATUS_ID:
            p["convictions"] += 1
        if p["last"] is None or r["filed"] > p["last"]:
            p["last"] = r["filed"]

    out = []
    for uid, a in agg.items():
        days_since = (max(0, (cutoff - a["last"]).days) if a["last"] else NEVER_OFFENDED_GAP)
        x = np.array([
            float(a["age"] or 35),
            float(a["priors"]),
            float(len(a["types"])),
            float(a["convictions"]),
            float(degree.get(uid, 0)),
            float(days_since),
        ], dtype=float)
        out.append(FeatureRow(str(uid), _gender_label(a["gender"]), x))
    return out


def _gender_label(gender_id) -> str:
    return {1: "M", 2: "F", 3: "T"}.get(gender_id, "U")


def build_labels(cutoff: date, window_days: int | None) -> set[str]:
    """PersonUIDs accused in a case filed after `cutoff` (optionally within a window).

    window_days=None -> "ever re-offends after the cutoff" (score_risk).
    window_days=180  -> the calibrated 180-day recidivism target.
    """
    until = cutoff + timedelta(days=window_days) if window_days is not None else None
    out = set()
    for r in _accused_rows():
        f = r["filed"]
        if f and f >= cutoff and (until is None or f < until):
            out.add(str(r["PersonUID"]))
    return out


def latest_fir_date() -> date | None:
    return queries.latest_case_date()
