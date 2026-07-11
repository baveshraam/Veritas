"""Feature construction for the risk and recidivism models.

Responsible-AI constraint (non-negotiable, Layer 10): no caste, no religion, no
direct proxies. Gender is excluded from the *feature set* too — it is a protected
attribute and adds nothing the offending history doesn't already carry — but it is
retained as a *subgroup label* so the Aequitas audit can test for disparate impact.

Labels are built with a temporal cutoff: features come only from records BEFORE the
cutoff, the label from records AFTER it. Training on features that include the very
offence you're predicting is the classic leakage that makes a risk model look
excellent offline and useless in the field.
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from data.db import get_session

FEATURE_NAMES = [
    "age",
    "prior_offence_count",
    "distinct_crime_types",
    "conviction_count",
    "co_accused_degree",
    "days_since_last_offence",
    "gang_affiliated",
]

# Plain-language names for the SHAP explanation shown to officers.
FEATURE_LABELS = {
    "age": "age",
    "prior_offence_count": "number of prior recorded offences",
    "distinct_crime_types": "variety of offence types",
    "conviction_count": "prior convictions",
    "co_accused_degree": "number of known co-accused associates",
    "days_since_last_offence": "time since last recorded offence",
    "gang_affiliated": "known gang affiliation",
}

_FEATURE_SQL = """
WITH prior AS (
    SELECT cr.person_id,
           count(*)                                   AS prior_offence_count,
           count(DISTINCT f.crime_type)               AS distinct_crime_types,
           count(*) FILTER (WHERE cr.conviction)      AS conviction_count,
           max(f.date_filed)                          AS last_offence
    FROM criminal_record cr
    JOIN fir f ON f.fir_id = cr.fir_id
    WHERE f.date_filed < :cutoff
    GROUP BY cr.person_id
),
assoc AS (
    SELECT a.person_id, count(DISTINCT b.person_id) AS co_accused_degree
    FROM criminal_record a
    JOIN criminal_record b ON b.fir_id = a.fir_id AND b.person_id <> a.person_id
    JOIN fir f ON f.fir_id = a.fir_id
    WHERE f.date_filed < :cutoff
    GROUP BY a.person_id
)
SELECT p.person_id, p.dob, p.gender,
       COALESCE(pr.prior_offence_count, 0)  AS prior_offence_count,
       COALESCE(pr.distinct_crime_types, 0) AS distinct_crime_types,
       COALESCE(pr.conviction_count, 0)     AS conviction_count,
       COALESCE(a.co_accused_degree, 0)     AS co_accused_degree,
       pr.last_offence                      AS last_offence,
       (p.gang_affiliation IS NOT NULL)     AS gang_affiliated
FROM person p
LEFT JOIN prior pr ON pr.person_id = p.person_id
LEFT JOIN assoc a  ON a.person_id  = p.person_id
"""


@dataclass
class FeatureRow:
    person_id: str
    gender: str                 # subgroup label for the fairness audit, NOT a feature
    x: np.ndarray


def _row_to_x(r, cutoff: date) -> np.ndarray:
    age = (cutoff - r.dob).days / 365.25 if r.dob else 35.0
    if r.last_offence:
        last = r.last_offence.date() if hasattr(r.last_offence, "date") else r.last_offence
        days_since = max(0, (cutoff - last).days)
    else:
        days_since = 3650      # never offended: a long, capped gap
    return np.array([
        age,
        float(r.prior_offence_count),
        float(r.distinct_crime_types),
        float(r.conviction_count),
        float(r.co_accused_degree),
        float(days_since),
        1.0 if r.gang_affiliated else 0.0,
    ], dtype=float)


def build_features(cutoff: date) -> list[FeatureRow]:
    with get_session() as s:
        rows = s.execute(text(_FEATURE_SQL), {"cutoff": cutoff}).all()
    return [FeatureRow(str(r.person_id), r.gender or "U", _row_to_x(r, cutoff)) for r in rows]


def build_labels(cutoff: date, window_days: int | None) -> set[str]:
    """person_ids accused in a FIR filed after `cutoff` (optionally within a window).

    window_days=None -> "ever re-offends after the cutoff" (score_risk).
    window_days=180  -> the calibrated 180-day recidivism target.
    """
    sql = ("SELECT DISTINCT cr.person_id FROM criminal_record cr "
           "JOIN fir f ON f.fir_id = cr.fir_id WHERE f.date_filed >= :cutoff")
    params: dict = {"cutoff": cutoff}
    if window_days is not None:
        sql += " AND f.date_filed < :until"
        params["until"] = cutoff + timedelta(days=window_days)
    with get_session() as s:
        return {str(r.person_id) for r in s.execute(text(sql), params).all()}


def latest_fir_date() -> date | None:
    with get_session() as s:
        r = s.execute(text("SELECT max(date_filed) AS d FROM fir")).first()
    if not r or not r.d:
        return None
    return r.d.date() if hasattr(r.d, "date") else r.d
