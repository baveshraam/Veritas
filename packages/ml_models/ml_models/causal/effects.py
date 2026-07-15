"""Causal layer — DoWhy, confounder-adjusted effect estimates.

Answers "does deprivation *cause* higher recorded crime here", not "do they
correlate". A bare correlation between a socioeconomic factor and a crime rate is
exactly the kind of claim that gets laundered into policy, so it gets the full
identification pipeline: causal graph -> identify estimand -> estimate -> REFUTE.

The refutation step is not decoration. An effect that survives a placebo treatment
and a random-common-cause perturbation is a claim we can defend to a review panel;
one that doesn't is reported as `refutation_passed=False` and must not be quoted as
causal. Callers surface that flag.

Data: `district_socioeconomic`, the one real (non-synthetic) table in the schema —
Census of India 2011 Primary Census Abstract, 30 Karnataka districts, loaded by
`data.socioeconomic`. If it is empty the module raises SocioeconomicDataUnavailable
with the remedy rather than falling back to a correlation.

Note on what a 30-row panel can and cannot support: with 30 districts we estimate
ONE state-wide effect across the district cross-section. `district_code` names the
district the question was asked about; it does not make the estimate district-
specific, and the returned prose says so. Per-district causal effects would need a
district-year panel, which Census 2011 (a single year) cannot provide.

`police_per_lakh` is NOT among the confounders: India does not publish police
strength per district (BPR&D/KSP report it state-wide and rank-wise). Policing
intensity is therefore an unmeasured confounder and we say so out loud rather than
adjust for a fabricated column — see UNMEASURED_CONFOUNDERS.
"""
import pandas as pd

from data import ds, queries

from ..types import CausalEstimate

# Held fixed when estimating an effect: each plausibly drives BOTH the factor and
# the recorded crime rate. Omitting them is how spurious socioeconomic "causes" get
# published. All three are real Census 2011 district columns.
CONFOUNDERS = ["urban_ratio", "population", "youth_ratio"]

# Named, not silently ignored. A confounder we cannot measure is a limitation of the
# estimate, and the honest move is to report it alongside the number.
UNMEASURED_CONFOUNDERS = ["police_per_lakh"]

SUPPORTED_FACTORS = ["literacy_rate", "poverty_index", "marginal_worker_rate"]

# DoWhy's refuters permute and resample, so they are stochastic. Unseeded, the same
# question can pass refutation on one turn and fail it on the next — and a system
# whose claim is defensibility cannot give two different verdicts on one question.
REFUTER_SEED = 42


class SocioeconomicDataUnavailable(RuntimeError):
    """district_socioeconomic is empty — run `python -m data.socioeconomic` first."""


def _panel() -> pd.DataFrame:
    """District cross-section: real socioeconomic ground truth + observed crime rate.

    The join happens here rather than in the query: ZCQL has no subquery, so the crime
    count per district cannot be aggregated server-side. Thirty rows either way.
    """
    socio = ds.query(
        'SELECT "DistrictID", "Population", "LiteracyRate", "PovertyIndex", '
        '"MarginalWorkerRate", "UrbanRatio", "YouthRatio" FROM "vx_district_socioeconomic"')
    if not socio:
        raise SocioeconomicDataUnavailable(
            "vx_district_socioeconomic is empty. Causal estimates need the real Census 2011 "
            "ground truth (dataset D17) — load it with `python -m data.socioeconomic` "
            "rather than synthesising it.")

    counts = queries.case_counts_by_district()
    df = pd.DataFrame([{
        "district_code": r["DistrictID"],
        "population": r["Population"],
        "literacy_rate": r["LiteracyRate"],
        "poverty_index": r["PovertyIndex"],
        "marginal_worker_rate": r["MarginalWorkerRate"],
        "urban_ratio": r["UrbanRatio"],
        "youth_ratio": r["YouthRatio"],
        "crime_count": counts.get(r["DistrictID"], 0),
    } for r in socio])
    # Crime rate per 100k — comparing raw counts across districts would make the
    # effect of every factor collapse into "Bengaluru is large".
    df["crime_rate"] = df["crime_count"] / (df["population"] / 100_000)
    return df.dropna()


def estimate_causal_effect(factor: str, outcome: str, district_code: str) -> CausalEstimate:
    if factor not in SUPPORTED_FACTORS:
        raise ValueError(f"unsupported factor {factor!r}; expected one of {SUPPORTED_FACTORS}")

    # _panel() first: the binding constraint is the Census table, not the library.
    # Importing dowhy up front would mask a missing table with an ImportError.
    df = _panel()
    if len(df) < 10:
        raise SocioeconomicDataUnavailable(
            f"only {len(df)} districts with complete socioeconomic data — too few to "
            "identify an effect. Load the full Census 2011 table.")

    try:
        from dowhy import CausalModel
    except ImportError as e:
        # The deployed image ships without dowhy (and its sympy/matplotlib/statsmodels
        # chain, ~230MB): AppSail's bundle sandbox caps the image, and this is the caught
        # channel the prediction agent already degrades through. Causal estimates run
        # anywhere the [causal] extra is installed — local dev and the demo laptop.
        raise SocioeconomicDataUnavailable(
            f"the causal-inference library is not installed on this host ({e}); "
            "install ml_models[causal] to run causal estimates.") from e

    adjusted = [c for c in CONFOUNDERS if c != factor]
    model = CausalModel(data=df, treatment=factor, outcome="crime_rate",
                        common_causes=adjusted)
    estimand = model.identify_effect(proceed_when_unidentifiable=False)
    estimate = model.estimate_effect(
        estimand, method_name="backdoor.linear_regression", test_significance=True)

    effect = float(estimate.value)
    try:
        ci = estimate.get_confidence_intervals()
        lo, hi = float(ci[0][0]), float(ci[0][1])
    except (TypeError, IndexError, KeyError):
        lo, hi = effect, effect

    passed, detail = _refute(model, estimand, estimate, effect)

    return CausalEstimate(
        factor=factor, outcome=outcome, district_code=district_code,
        effect_size=round(effect, 4),
        confidence_interval=(round(lo, 4), round(hi, 4)),
        confounders_adjusted=adjusted,
        unmeasured_confounders=UNMEASURED_CONFOUNDERS,
        n_districts=len(df),
        refutation_passed=passed,
        refutation_detail=detail,
    )


def _refute(model, estimand, estimate, effect: float) -> tuple[bool, str]:
    """Two standard DoWhy refuters. Both must pass for the estimate to be quotable.

    - placebo_treatment_refuter: replace the treatment with noise. A real effect
      must collapse toward zero; if the "effect" survives a placebo, the pipeline is
      fitting noise.
    - random_common_cause: add an irrelevant covariate. A real effect must be
      approximately unchanged; a large shift means the estimate is unstable.
    """
    notes, passed = [], True

    try:
        placebo = model.refute_estimate(
            estimand, estimate, method_name="placebo_treatment_refuter",
            placebo_type="permute", num_simulations=30, random_seed=REFUTER_SEED)
        new = float(placebo.new_effect)
        # A placebo must be small relative to the real effect. Guard the degenerate
        # case where the real effect is ~0 to begin with.
        ok = abs(new) < max(0.25 * abs(effect), 1e-9)
        passed &= ok
        notes.append(f"placebo treatment -> effect {new:+.4f} ({'pass' if ok else 'FAIL'})")
    except Exception as e:                      # refuters are best-effort, never fatal
        passed = False
        notes.append(f"placebo treatment -> could not run ({type(e).__name__})")

    try:
        rcc = model.refute_estimate(
            estimand, estimate, method_name="random_common_cause",
            num_simulations=30, random_seed=REFUTER_SEED)
        new = float(rcc.new_effect)
        ok = abs(new - effect) <= max(0.1 * abs(effect), 1e-9)
        passed &= ok
        notes.append(f"random common cause -> effect {new:+.4f} ({'pass' if ok else 'FAIL'})")
    except Exception as e:
        passed = False
        notes.append(f"random common cause -> could not run ({type(e).__name__})")

    return passed, "; ".join(notes)
