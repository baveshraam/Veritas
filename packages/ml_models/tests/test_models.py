"""ML-layer checks that need no database — the load-bearing maths and invariants."""
import numpy as np
import pytest

from ml_models.fairness.audit import (
    DISPARITY_CEILING, DISPARITY_FLOOR, _flag_disparate_impact, _group_metrics,
)
from ml_models.forecasting.forecast import _mint_reconcile
from ml_models.risk.features import FEATURE_LABELS, FEATURE_NAMES
from ml_models.spatial.hotspots import _kde_intensities, _ring


# --- MinT --------------------------------------------------------------------

def test_mint_makes_incoherent_forecasts_coherent():
    """The whole point of MinT: the district forecast must equal the sum of its
    stations. Independent Prophet fits do not satisfy that."""
    rng = np.random.default_rng(0)
    stations = rng.uniform(1, 5, size=(3, 5))
    district = stations.sum(axis=0) + rng.uniform(-2, 2, size=5)   # incoherent by design
    base = np.vstack([district, stations])

    before = np.abs(base[0] - base[1:].sum(axis=0))
    assert (before > 1e-6).any(), "test setup must start incoherent"

    rec = _mint_reconcile(base, np.array([2.0, 1.0, 1.0, 1.0]), n_bottom=3)
    after = np.abs(rec[:, 0] - rec[:, 1:].sum(axis=1))
    assert np.allclose(after, 0, atol=1e-9)


def test_mint_returns_horizon_by_hierarchy():
    base = np.ones((4, 7))          # 1 district + 3 stations, 7 horizon steps
    rec = _mint_reconcile(base, np.ones(4), n_bottom=3)
    assert rec.shape == (7, 4)


# --- spatial -----------------------------------------------------------------

def test_ring_falls_back_to_bbox_for_degenerate_clusters():
    collinear = np.array([[12.0, 77.0], [12.1, 77.0], [12.2, 77.0]])
    ring = _ring(collinear)
    assert len(ring) >= 3                       # still a renderable polygon
    assert all(len(pt) == 2 for pt in ring)


def test_kde_intensity_is_max_scaled_never_zeroing_a_real_hotspot():
    pts = np.vstack([np.random.default_rng(1).normal([12.9, 77.5], 0.01, size=(60, 2)),
                     np.random.default_rng(2).normal([13.4, 77.9], 0.01, size=(40, 2))])
    centroids = np.array([[12.9, 77.5], [13.4, 77.9]])
    inten = _kde_intensities(pts, centroids)
    assert inten.max() == pytest.approx(1.0)
    assert (inten > 0).all(), "a real cluster must never render as zero intensity"


# --- responsible AI ----------------------------------------------------------

def test_no_protected_attributes_in_the_feature_set():
    banned = {"caste", "religion", "gender", "community", "sect"}
    for f in FEATURE_NAMES:
        assert not any(b in f.lower() for b in banned), f"protected attribute {f!r} used"
    assert set(FEATURE_NAMES) == set(FEATURE_LABELS), "every feature needs a plain-language label"


# --- fairness ----------------------------------------------------------------

def test_group_metrics():
    y_true = np.array([1, 1, 0, 0])
    y_pred = np.array([1, 0, 1, 0])
    m = _group_metrics(y_true, y_pred)
    assert m["fpr"] == 0.5 and m["fnr"] == 0.5
    assert m["selection_rate"] == 0.5 and m["base_rate"] == 0.5


def test_disparate_impact_uses_the_80_percent_rule():
    balanced = {
        "gender=M": {"group_size": 100, "selection_rate": 0.50, "fpr": 0, "fnr": 0, "base_rate": 0},
        "gender=F": {"group_size": 80, "selection_rate": 0.45, "fpr": 0, "fnr": 0, "base_rate": 0},
    }
    assert _flag_disparate_impact(balanced) is False

    skewed = {
        "gender=M": {"group_size": 100, "selection_rate": 0.50, "fpr": 0, "fnr": 0, "base_rate": 0},
        "gender=F": {"group_size": 80, "selection_rate": 0.20, "fpr": 0, "fnr": 0, "base_rate": 0},
    }
    assert 0.20 / 0.50 < DISPARITY_FLOOR
    assert _flag_disparate_impact(skewed) is True


def test_disparate_impact_flags_over_selection_too():
    over = {
        "district=A": {"group_size": 100, "selection_rate": 0.40, "fpr": 0, "fnr": 0, "base_rate": 0},
        "district=B": {"group_size": 50, "selection_rate": 0.90, "fpr": 0, "fnr": 0, "base_rate": 0},
    }
    assert 0.90 / 0.40 > DISPARITY_CEILING
    assert _flag_disparate_impact(over) is True
