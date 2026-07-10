"""Geo placement inside a district.

Until GADM polygons (D18) are downloaded, points are placed at the district
centroid + bounded jitter — enough for map demos and district-level joins.
`sample_point` is the seam the GADM polygon-sampling ETL replaces; its callers
(build.py) don't change. Note the intra-district-realism limitation is exactly
what FEATURE_DATA_COVERAGE's WorldPop/OSM gap addresses.
"""
import csv
import random
from functools import lru_cache
from pathlib import Path

_CSV = Path(__file__).resolve().parent.parent.parent / "seed" / "derived" / "district_centroids.csv"
_JITTER_DEG = 0.18  # ~20 km — keeps points inside the district, not crossing state lines


@lru_cache(maxsize=1)
def _centroids() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    with _CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["district_code"]] = (float(r["lat"]), float(r["lng"]))
    return out


def sample_point(rng: random.Random, district_code: str) -> str:
    """WKT 'POINT(lng lat)' near the district centroid. SRID 4326 is applied on load."""
    lat, lng = _centroids()[district_code]
    lat += rng.uniform(-_JITTER_DEG, _JITTER_DEG)
    lng += rng.uniform(-_JITTER_DEG, _JITTER_DEG)
    return f"POINT({lng:.6f} {lat:.6f})"


if __name__ == "__main__":
    rng = random.Random(0)
    assert set(_centroids()) == {f"KA{i:02d}" for i in range(1, 32)}
    p = sample_point(rng, "KA05")
    assert p.startswith("POINT(") and p.endswith(")")
    print("geo ok —", p)
