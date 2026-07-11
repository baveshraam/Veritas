"""Causal layer — DoWhy, confounder-adjusted effect estimates.

Answers "does unemployment *cause* higher property crime here", not "do they
correlate". The whole point of this layer is that a bare correlation between a
socioeconomic factor and a crime rate is exactly the kind of claim that gets
laundered into policy, so it gets a proper identification step: build a causal
graph, identify the estimand, estimate, then refute.

MISSING EXTERNAL DATASET: this needs `district_socioeconomic` populated from D17
(Census 2011 Karnataka + NSSO) — see data/DATA_ACQUISITION_STRATEGY.md. That table
is real ground truth we deliberately do NOT synthesise: fabricating socioeconomic
values and then claiming a causal effect from them would be worse than useless.
Until the Census ETL is run, this raises SocioeconomicDataUnavailable with the
exact remedy, and the Prediction Agent reports that instead of inventing a number.
"""
from functools import lru_cache

import pandas as pd
from sqlalchemy import text

from data.db import get_session

from ..types import CausalEstimate

# Confounders held fixed when estimating an effect. Chosen because each plausibly
# drives BOTH the factor and the crime rate (urbanisation and policing intensity
# above all) — omitting them is how spurious socioeconomic "causes" get published.
CONFOUNDERS = ["urban_ratio", "police_per_lakh", "population"]

SUPPORTED_FACTORS = ["literacy_rate", "unemployment", "poverty_index"]


class SocioeconomicDataUnavailable(RuntimeError):
    """district_socioeconomic is empty — load D17 (Census/NSSO) first."""


def _panel() -> pd.DataFrame:
    """District-level panel: socioeconomic ground truth + observed crime rate."""
    with get_session() as s:
        rows = s.execute(text(
            "SELECT d.district_code, d.literacy_rate, d.unemployment, d.poverty_index, "
            "       d.population, d.urban_ratio, d.police_per_lakh, "
            "       COALESCE(f.crime_count, 0) AS crime_count "
            "FROM district_socioeconomic d "
            "LEFT JOIN (SELECT district_code, count(*) AS crime_count "
            "           FROM fir GROUP BY district_code) f "
            "  ON f.district_code = d.district_code"
        )).all()
    if not rows:
        raise SocioeconomicDataUnavailable(
            "district_socioeconomic is empty. Causal estimates need real Census/NSSO "
            "ground truth (dataset D17) — load it via the ETL rather than synthesising "
            "it. See data/DATA_ACQUISITION_STRATEGY.md."
        )
    df = pd.DataFrame(rows, columns=[
        "district_code", "literacy_rate", "unemployment", "poverty_index",
        "population", "urban_ratio", "police_per_lakh", "crime_count"])
    df["crime_rate"] = df["crime_count"] / (df["population"] / 100_000).replace(0, pd.NA)
    return df.dropna()


def estimate_causal_effect(factor: str, outcome: str, district_code: str) -> CausalEstimate:
    if factor not in SUPPORTED_FACTORS:
        raise ValueError(f"unsupported factor {factor!r}; expected one of {SUPPORTED_FACTORS}")

    # _panel() first: the binding constraint is the missing Census table, not the
    # library. Importing dowhy up front would mask that with a ModuleNotFoundError.
    df = _panel()

    from dowhy import CausalModel
    if len(df) < 10:
        raise SocioeconomicDataUnavailable(
            f"only {len(df)} districts with complete socioeconomic data — too few to "
            "identify an effect. Load the full D17 Census/NSSO table.")

    outcome_col = "crime_rate"
    model = CausalModel(
        data=df, treatment=factor, outcome=outcome_col,
        common_causes=[c for c in CONFOUNDERS if c != factor],
    )
    estimand = model.identify_effect(proceed_when_unidentifiable=False)
    estimate = model.estimate_effect(
        estimand, method_name="backdoor.linear_regression", test_significance=True)

    effect = float(estimate.value)
    ci = estimate.get_confidence_intervals()
    try:
        lo, hi = float(ci[0][0]), float(ci[0][1])
    except (TypeError, IndexError, KeyError):
        lo, hi = effect, effect

    return CausalEstimate(
        factor=factor, outcome=outcome, district_code=district_code,
        effect_size=round(effect, 4),
        confidence_interval=(round(lo, 4), round(hi, 4)),
        confounders_adjusted=[c for c in CONFOUNDERS if c != factor],
    )
