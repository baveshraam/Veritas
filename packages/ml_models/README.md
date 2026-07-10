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
    # CALLED ONLY from data/generator/ as a batch dedup pass over freshly generated person
    # rows — NOT called live by packages/rag_agent. At query time "arrested under another
    # name" is answered by reading the already-written SAME_AS edges, a normal graph read.

def run_fairness_audit(model_name: str) -> AequitasReport: ...
    # Aequitas (Saleiro et al., 2018, Univ. of Chicago DSaPP) — disparate-impact and
    # FPR/FNR-parity across demographic/geographic subgroups. Run on score_risk and
    # predict_recidivism before every demo; report is a build artifact, not an afterthought.
    # CALLED ONLY from a standalone script (e.g. `fairness/run_audit.py`), by hand or CI,
    # before each demo — not part of any runtime request path, not called by rag_agent or apps/api.
```

## Result types (canonical — every field here is consumed by name across folder boundaries)

None of these existed as concrete shapes before this audit; every function above returned an undefined type. Defined against what the actual consumer needs (chart libraries in `apps/web`, `EvidenceItem.content` in `packages/rag_agent`):

```python
class HotspotPolygon(BaseModel):
    polygon: list[tuple[float, float]]   # GeoJSON-style [lng, lat] ring, for Deck.gl
    intensity: float                      # KDE density at centroid, 0-1 normalized
    crime_count: int

class ForecastResult(BaseModel):
    level: Literal["ps", "taluk", "district", "state"]
    series: list[tuple[date, float, float, float]]   # (date, point_estimate, lower, upper) — ECharts confidence-band input
    reconciled: bool   # true once MinT has run; false for a raw per-level Prophet output

class RiskResult(BaseModel):
    person_id: str; score: float                  # 0-1
    top_factors: list[tuple[str, float]]            # SHAP feature -> contribution, for the "model suggests" explanation text

class RecidivismResult(BaseModel):
    person_id: str; probability_180d: float; calibrated: bool

class AnomalyAlert(BaseModel):
    alert_id: str; district_code: str; metric: str; observed: float; expected: float
    severity: Literal["low", "medium", "high"]; detected_at: datetime

class TransactionFlag(BaseModel):
    txn_id: str; detector: Literal["rule_based_structuring", "gnn_subgraph"]
    confidence: float; explanation: str   # attention-weight highlight or rule description
    related_account_ids: list[str]         # feeds the Sankey view's node/link set

class CausalEstimate(BaseModel):
    factor: str; outcome: str; district_code: str
    effect_size: float; confidence_interval: tuple[float, float]; confounders_adjusted: list[str]

class MatchResult(BaseModel):
    person_id_a: str; person_id_b: str
    decision: Literal["link", "possible_link", "non_link"]; confidence: float

class AequitasReport(BaseModel):
    model_name: str; metrics_by_subgroup: dict[str, dict[str, float]]   # e.g. {"district=X": {"fpr": .., "fnr": ..}}
    disparate_impact_flagged: bool; generated_at: datetime
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
- **Provides to `packages/rag_agent`'s Prediction Agent**: `detect_hotspots`, `forecast_crime`, `score_risk`, `predict_recidivism`, `estimate_causal_effect`, `flag_transactions` — called live, per query.
- **Provides to `apps/api`**: `check_anomalies`, called directly (not via `rag_agent`) to feed the `/alerts` WebSocket.
- **Provides to `data/generator/`**: `resolve_entities`, called once per data-generation run (batch), not part of any live query path.
- **Provides to whoever runs the pre-demo checklist**: `run_fairness_audit`, invoked out-of-band via a standalone script, not by any other folder's runtime code.
- **Consumes from `data/`**: feature data via `data/`'s connection helpers only (never opens its own DB connection, never redefines a schema), plus `data.nlp.transliterate()` for name-variant generation inside `resolve_entities`.
- **Writes to `data/`**: via the named write helpers in `data/README.md` (`set_canonical_entity`, `write_same_as_edge`, `flag_transaction`) — never raw SQL/Cypher from this package.

## Non-goals
- No orchestration/routing logic, no NL understanding, no direct API/DB access outside `data/`'s helpers — this package is a pure model layer.
