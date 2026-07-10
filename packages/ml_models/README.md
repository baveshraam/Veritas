# ML / Predictive Analytics (`packages/ml_models/`)

**What this is**: every model in the system — hotspot detection, forecasting, risk/recidivism scoring, financial-crime detection, entity resolution, fairness auditing. Exposes one typed function per capability; called only by `packages/rag_agent`'s Prediction Agent. No HTTP endpoints of its own, no direct calls from `apps/api` or the frontend.

Owns Layer 4, the ML half of Layer 2.4, Layer 6.2 (entity resolution), and Layer 10 (fairness) of root [`CLAUDE.md`](../../CLAUDE.md).

## Functions this package exposes

```python
def detect_hotspots(district_code: str, date_range: tuple) -> list[HotspotPolygon]: ...
    # KDE (Gaussian, Scott's rule) for continuous density + DBSCAN (eps=500m, min_samples=10)
    # for discrete polygons; ST-DBSCAN when linking a crime series over time.

def forecast_crime(district_code: str, horizon_days: int) -> ForecastResult: ...
    # Prophet, forecast independently at PS / taluk / district / state level, then
    # reconciled with MinT (Wickramasuriya, Athanasopoulos & Hyndman, 2019, JASA) so a
    # district's forecast always equals the coherent sum of its taluks.

def score_risk(person_id: str) -> RiskResult: ...
    # XGBoost + SHAP — returns a score plus a natural-language explanation of the
    # top contributing features. No protected/proxy attributes as inputs.

def predict_recidivism(person_id: str) -> RecidivismResult: ...
    # LightGBM, 180-day re-offense probability, calibrated.

def check_anomalies(district_code: str) -> list[AnomalyAlert]: ...
    # Isolation Forest over district-level crime-count time series.

def estimate_causal_effect(factor: str, outcome: str, district_code: str) -> CausalEstimate: ...
    # DoWhy — confounder-adjusted effect size, not bare correlation.

def flag_transactions(account_id: str) -> list[TransactionFlag]: ...
    # Two detectors run together, both returned:
    #  1. rule-based structuring detector (many sub-threshold transactions) — explainable,
    #     auditable line-by-line.
    #  2. heterogeneous/temporal GNN suspicious-subgraph classifier, trained on the synthetic
    #     transaction graph with injected structuring/layering patterns as ground truth —
    #     catches coordinated multi-account laundering the rule-based detector can't see.
    #     Explained via attention-weight/subgraph highlighting, not a bare score.

def resolve_entities(candidate_person_ids: list[str]) -> list[MatchResult]: ...
    # Fellegi-Sunter probabilistic record linkage (1969) — scores pairs on weighted field
    # agreement (name similarity post-IndicXlit, DOB, address proximity, phone) into
    # link / possible-link / non-link with explicit error-rate thresholds. Writes to the
    # `SAME_AS {confidence}` graph edge and `canonical_entity_id` column (schema in `data/`).

def run_fairness_audit(model_name: str) -> AequitasReport: ...
    # Aequitas (Saleiro et al., 2018, Univ. of Chicago DSaPP) — disparate-impact and
    # FPR/FNR-parity across demographic/geographic subgroups. Run on score_risk and
    # predict_recidivism before every demo; report is a build artifact, not an afterthought.
```

## Responsible AI (non-negotiable, applies to every model above)
- No caste, religion, or direct proxies for them as features, ever.
- Every output is decision-support (score + explanation) — never wired to an automated action.
- Confidence intervals / calibrated probabilities surfaced, not just point estimates.

## Suggested structure
```
packages/ml_models/
  spatial/             # KDE, DBSCAN, ST-DBSCAN → detect_hotspots
  forecasting/         # Prophet per-level + MinT reconciliation → forecast_crime
  risk/                # XGBoost+SHAP, LightGBM, Isolation Forest → score_risk, predict_recidivism, check_anomalies
  causal/              # DoWhy → estimate_causal_effect
  financial/           # rule-based detector + GNN classifier → flag_transactions
  entity_resolution/   # Fellegi-Sunter → resolve_entities
  fairness/            # Aequitas → run_fairness_audit
  serving.py           # re-exports the public functions above
```

## Provides / Consumes
- **Provides to `packages/rag_agent`**: the functions listed above, nothing else.
- **Consumes from `data/`**: feature data via `data/`'s connection helpers only — never opens its own DB connection, never redefines a schema.
- **Writes to `data/`**: entity-resolution matches and AML flags go through `data/`'s write helpers.

## Non-goals
- No orchestration/routing logic, no NL understanding, no direct API/DB access outside `data/`'s helpers — this package is a pure model layer.
