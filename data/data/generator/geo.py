"""Geo placement inside a district.

Incidents are NOT spread uniformly across a district. Real crime concentrates around
attractors — markets, bus stands, highways, bars, informal settlements — and uniform
placement is the single thing that makes synthetic crime geography useless: KDE and
DBSCAN over a uniform scatter find nothing at all (a 500m/10-sample cluster cannot
exist when 60 incidents are smeared over 40km), so the hotspot layer comes back empty.
FEATURE_DATA_COVERAGE.md flags this as the biggest spatial-realism gap.

So each district gets a small set of deterministic *activity centres*, and incidents
are drawn around them with a tight spread, plus a diffuse background. This is a
stand-in for the real attractor layer (WorldPop population grid + OSM POI/land-use,
datasets U1/U2 in the manifest); `_attractors` is the seam that layer replaces, and
`sample_point`'s callers do not change.
"""
import csv
import random
from functools import lru_cache
from pathlib import Path

_CSV = Path(__file__).resolve().parent.parent.parent / "seed" / "derived" / "district_centroids.csv"

_N_ATTRACTORS = 4          # activity centres per district
_ATTRACTOR_SPREAD = 0.14   # ~15 km — how far centres sit from the district centroid
_LOCAL_SPREAD = 0.004      # ~450 m — tight cluster around a centre (DBSCAN eps=500m)
_BACKGROUND_SHARE = 0.25   # incidents that don't belong to any hotspot
_BACKGROUND_SPREAD = 0.16


@lru_cache(maxsize=1)
def _centroids() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    with _CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["district_code"]] = (float(r["lat"]), float(r["lng"]))
    return out


@lru_cache(maxsize=64)
def _attractors(district_code: str) -> tuple[tuple[float, float], ...]:
    """Fixed activity centres for a district. Derived from a district-seeded RNG so
    they're stable across runs — a hotspot must stay in the same place between a
    forecast and the map that renders it."""
    lat, lng = _centroids()[district_code]
    rng = random.Random(f"attractors:{district_code}")
    return tuple(
        (lat + rng.uniform(-_ATTRACTOR_SPREAD, _ATTRACTOR_SPREAD),
         lng + rng.uniform(-_ATTRACTOR_SPREAD, _ATTRACTOR_SPREAD))
        for _ in range(_N_ATTRACTORS)
    )


def sample_point(rng: random.Random, district_code: str) -> str:
    """WKT 'POINT(lng lat)'. SRID 4326 is applied on load."""
    if rng.random() < _BACKGROUND_SHARE:
        lat, lng = _centroids()[district_code]
        spread = _BACKGROUND_SPREAD
    else:
        lat, lng = rng.choice(_attractors(district_code))
        spread = _LOCAL_SPREAD
    return (f"POINT({lng + rng.gauss(0, spread):.6f} "
            f"{lat + rng.gauss(0, spread):.6f})")


if __name__ == "__main__":
    rng = random.Random(0)
    assert set(_centroids()) == {f"KA{i:02d}" for i in range(1, 32)}
    assert len(_attractors("KA05")) == _N_ATTRACTORS
    assert _attractors("KA05") == _attractors("KA05")     # stable across calls
    print("geo ok —", sample_point(rng, "KA05"))
