"""The public surface of packages/ml_models — one typed function per capability.

Callers (per the contract in packages/ml_models/README.md):
  - rag_agent's Prediction Agent: detect_hotspots, forecast_crime, score_risk,
    predict_recidivism, estimate_causal_effect, flag_transactions
  - apps/api directly: check_anomalies (for the /alerts WebSocket)
  - data/generator: resolve_entities (batch, offline)
  - fairness/run_audit.py: run_fairness_audit (out-of-band, pre-demo)

Heavy model libraries are imported lazily inside each implementation module, so
importing this surface does not drag torch/prophet/xgboost into every process.
"""
from datetime import date

from .entity_resolution import resolve_entities
from .types import (
    AequitasReport, AnomalyAlert, CausalEstimate, ForecastResult, HotspotPolygon,
    MatchResult, RecidivismResult, RiskResult, TransactionFlag,
)


def detect_hotspots(district_code: str, date_range: tuple) -> list[HotspotPolygon]:
    from .spatial.hotspots import detect_hotspots as _impl
    return _impl(district_code, date_range)


def forecast_crime(district_code: str, horizon_days: int) -> ForecastResult:
    from .forecasting.forecast import forecast_crime as _impl
    return _impl(district_code, horizon_days)


def score_risk(person_id: str) -> RiskResult:
    from .risk.scoring import score_risk as _impl
    return _impl(person_id)


def predict_recidivism(person_id: str) -> RecidivismResult:
    from .risk.scoring import predict_recidivism as _impl
    return _impl(person_id)


def check_anomalies(district_code: str) -> list[AnomalyAlert]:
    from .risk.anomalies import check_anomalies as _impl
    return _impl(district_code)


def estimate_causal_effect(factor: str, outcome: str, district_code: str) -> CausalEstimate:
    from .causal.effects import estimate_causal_effect as _impl
    return _impl(factor, outcome, district_code)


def flag_transactions(account_id: str) -> list[TransactionFlag]:
    """Both detectors, both returned — that is the contract.

    The rule-based structuring detector is the explainable baseline a court can
    audit; the GNN catches coordinated cross-account patterns the rule cannot see.
    Neither replaces the other, so a caller never has to pick. Flags are persisted
    via data.flag_transaction so the graph carries the detector's verdict.
    """
    from data.transactions import flag_transaction

    from .financial.gnn import GNNUnavailable, detect_subgraph
    from .financial.structuring import detect_structuring

    flags: list[TransactionFlag] = list(detect_structuring(account_id))
    try:
        flags += detect_subgraph(account_id)
    except GNNUnavailable:
        # too few laundering examples to fit an honest classifier — the rule-based
        # detector still stands on its own rather than the whole call failing.
        pass

    for f in flags:
        if f.txn_id:
            flag_transaction(f.txn_id, "laundering", f.detector, f.confidence)
    return flags


def run_fairness_audit(model_name: str) -> AequitasReport:
    from .fairness.audit import run_fairness_audit as _impl
    return _impl(model_name)


__all__ = [
    "detect_hotspots", "forecast_crime", "score_risk", "predict_recidivism",
    "check_anomalies", "estimate_causal_effect", "flag_transactions",
    "resolve_entities", "run_fairness_audit",
    "HotspotPolygon", "ForecastResult", "RiskResult", "RecidivismResult",
    "AnomalyAlert", "TransactionFlag", "CausalEstimate", "MatchResult", "AequitasReport",
]
