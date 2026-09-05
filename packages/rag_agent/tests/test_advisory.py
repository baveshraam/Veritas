"""advisory_for fuses hotspot/forecast/series-linkage into one proactive read
(STRATEGIC_RESET Part 9, Item 2). It must say nothing when the signals don't
actually agree — a hotspot with a flat/falling forecast is not news — and it
must show its caveats alongside the headline number, never folded into it.
"""
from datetime import date

from ml_models.types import ForecastResult, HotspotPolygon
from rag_agent.agents import prediction_agent


def _polys(intensity=0.8, crime_count=12):
    return [HotspotPolygon(polygon=[(0.0, 0.0)], intensity=intensity, crime_count=crime_count)]


def _forecast(rising: bool):
    lo_first, lo_last = (1.0, 3.0) if rising else (3.0, 1.0)
    series = [(date(2026, 1, 1), lo_first, 0.5, 1.5), (date(2026, 1, 30), lo_last, 2.0, 4.0)]
    return ForecastResult(level="district", series=series, reconciled=True)


def test_no_advisory_without_a_hotspot(monkeypatch):
    monkeypatch.setattr("ml_models.serving.detect_hotspots", lambda *a: [])
    assert prediction_agent.advisory_for("KA05") is None


def test_no_advisory_when_the_forecast_is_flat_or_falling(monkeypatch):
    monkeypatch.setattr("ml_models.serving.detect_hotspots", lambda *a: _polys())
    monkeypatch.setattr("ml_models.serving.forecast_crime", lambda *a: _forecast(rising=False))
    assert prediction_agent.advisory_for("KA05") is None


def test_advisory_fires_on_genuine_confluence_and_shows_caveats_separately(monkeypatch):
    monkeypatch.setattr("ml_models.serving.detect_hotspots", lambda *a: _polys(crime_count=12))
    monkeypatch.setattr("ml_models.serving.forecast_crime", lambda *a: _forecast(rising=True))
    monkeypatch.setattr("data.districts.canonical_name", lambda code: "Kolar")

    out = prediction_agent.advisory_for(
        "KA05",
        series_candidates=[{"districts": ["Kolar"]}],
        fairness_flagged=True,
    )

    assert out is not None
    assert "12 recorded points" in out["headline"]
    assert "Kolar" in out["headline"]
    # The number stays a number; the caveats are separate list entries, not text
    # appended onto the headline.
    assert not any("police strength" in out["headline"] for _ in [None])
    assert any("police strength" in d for d in out["disclosures"])
    assert any("cross-station series" in d for d in out["disclosures"])
    assert any("Aequitas" in d for d in out["disclosures"])


def test_unrelated_series_in_other_districts_are_not_counted(monkeypatch):
    monkeypatch.setattr("ml_models.serving.detect_hotspots", lambda *a: _polys())
    monkeypatch.setattr("ml_models.serving.forecast_crime", lambda *a: _forecast(rising=True))
    monkeypatch.setattr("data.districts.canonical_name", lambda code: "Kolar")

    out = prediction_agent.advisory_for("KA05", series_candidates=[{"districts": ["Mysuru"]}])
    assert not any("cross-station series" in d for d in out["disclosures"])
