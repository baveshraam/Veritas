"""Canonical result types. Every field here is consumed by name across folder
boundaries (rag_agent's EvidenceItem.content, apps/web's chart inputs) — treat as
an append-only contract. Defined in packages/ml_models/README.md.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class HotspotPolygon(BaseModel):
    polygon: list[tuple[float, float]]   # GeoJSON-style [lng, lat] ring, for Deck.gl
    intensity: float                      # KDE density at centroid, 0-1 normalized
    crime_count: int


class ForecastResult(BaseModel):
    level: Literal["ps", "taluk", "district", "state"]
    series: list[tuple[date, float, float, float]]   # (date, point, lower, upper)
    reconciled: bool   # true once MinT has run; false for raw per-level Prophet


class RiskResult(BaseModel):
    person_id: str
    score: float                          # 0-1
    top_factors: list[tuple[str, float]]  # SHAP feature -> contribution


class RecidivismResult(BaseModel):
    person_id: str
    probability_180d: float
    calibrated: bool


class AnomalyAlert(BaseModel):
    alert_id: str
    district_code: str
    metric: str
    observed: float
    expected: float
    severity: Literal["low", "medium", "high"]
    detected_at: datetime


class TransactionFlag(BaseModel):
    txn_id: str
    detector: Literal["rule_based_structuring", "gnn_subgraph"]
    confidence: float
    explanation: str                      # rule description or attention highlight
    related_account_ids: list[str]        # feeds the Sankey node/link set


class CausalEstimate(BaseModel):
    factor: str
    outcome: str
    district_code: str
    effect_size: float
    confidence_interval: tuple[float, float]
    confounders_adjusted: list[str]


class MatchResult(BaseModel):
    person_id_a: str
    person_id_b: str
    decision: Literal["link", "possible_link", "non_link"]
    confidence: float


class AequitasReport(BaseModel):
    model_name: str
    metrics_by_subgroup: dict[str, dict[str, float]]   # {"district=KA05": {"fpr": ..}}
    disparate_impact_flagged: bool
    generated_at: datetime
