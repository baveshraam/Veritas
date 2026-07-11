"""The committed Census 2011 ground truth must stay real.

`district_socioeconomic` is the only non-synthetic table in the schema, and the
DoWhy causal layer reads it directly. If the derived CSV silently drifts — a bad
merge, a re-derive against the wrong source file — every causal claim the platform
makes becomes a claim about fabricated data, which is the exact failure the whole
module exists to prevent. So the shipped artifact is checked against the published
Karnataka aggregates, not just against itself.
"""
import csv

import pytest

from data.districts import canonical_code
from data.socioeconomic import COLUMNS, DERIVED_PATH


@pytest.fixture(scope="module")
def rows():
    if not DERIVED_PATH.exists():
        pytest.skip("derived table absent; run `python -m data.socioeconomic`")
    with DERIVED_PATH.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_thirty_real_districts(rows):
    # Karnataka had 30 districts at the 2011 Census. Vijayanagara (KA31) was created
    # in 2021 and has no Census 2011 record — it must be absent, not back-filled.
    assert len(rows) == 30
    codes = {r["district_code"] for r in rows}
    assert len(codes) == 30
    assert "KA31" not in codes
    assert all(canonical_code(c) == c for c in codes)
    assert list(rows[0]) == COLUMNS


def test_reproduces_published_karnataka_aggregates(rows):
    """Population-weighted totals must match the real published Census 2011 figures."""
    pop = sum(int(r["population"]) for r in rows)
    assert pop == 61_095_297                       # official Karnataka 2011 total

    literacy = sum(float(r["literacy_rate"]) * int(r["population"]) for r in rows) / pop
    assert literacy == pytest.approx(66.53, abs=0.1)   # published crude literacy rate


def test_every_value_is_a_real_proportion(rows):
    for r in rows:
        assert int(r["year"]) == 2011
        assert 0 < float(r["literacy_rate"]) < 100
        for field in ("urban_ratio", "poverty_index", "marginal_worker_rate", "youth_ratio"):
            assert 0 < float(r[field]) < 1, f"{r['district_code']}.{field} out of range"


def test_districts_are_not_uniform(rows):
    """A flat socioeconomic layer would make every causal estimate identically zero.

    Guards against a re-derive that accidentally divides by the wrong denominator and
    collapses the cross-district variation the causal model depends on.
    """
    lit = sorted(float(r["literacy_rate"]) for r in rows)
    assert lit[-1] - lit[0] > 20      # Yadgir ~43% .. Dakshina Kannada ~80%
    urban = sorted(float(r["urban_ratio"]) for r in rows)
    assert urban[-1] - urban[0] > 0.5  # Kodagu ~0.15 .. Bengaluru Urban ~0.91
