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

_CSV = Path(__file__).resolve().parent.parent / "seed" / "derived" / "district_centroids.csv"

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


# Names for the activity centres above. An attractor is already the only real spatial
# structure in this dataset — KDE and DBSCAN find hotspots because incidents cluster on
# them — but it had no NAME, so nothing about it ever reached the narrative text an
# officer searches. Two burglaries 300m apart in the same market were, as far as
# retrieval was concerned, unrelated. Naming the centres makes the spatial layer and
# the text layer describe the same fact, which is what makes "other break-ins around
# Basava Market" a real query instead of a coincidence of wording.
#
# Deterministic per district, from the same district-seeded scheme `_attractors` uses,
# so a locality stays put across runs exactly as its coordinates do.
_LOCALITY_PREFIXES = ("Basava", "Vidya", "Shanti", "Jaya", "Kempe", "Hosa", "Gandhi",
                      "Vijaya", "Malleshwara", "Chikka", "Doddabele", "Sampige")
_LOCALITY_TYPES = ("Market", "Bus Stand", "Layout", "Industrial Estate",
                   "Ring Road Junction", "Bazaar Street", "Nagar")
# ~2.2km. `_LOCAL_SPREAD` is 450m, so this admits a clustered incident (3 sigma is
# ~1.4km) and excludes the diffuse background draws, which must stay unnamed — a
# background incident genuinely did not happen at an activity centre, and giving it a
# locality would invent the one fact this whole layer exists to record.
_LOCALITY_RADIUS = 0.02


@lru_cache(maxsize=64)
def _locality_names(district_code: str) -> tuple[str, ...]:
    rng = random.Random(f"locality:{district_code}")
    return tuple(f"{rng.choice(_LOCALITY_PREFIXES)} {t}"
                 for t in rng.sample(_LOCALITY_TYPES, _N_ATTRACTORS))


def locality(lat: float, lng: float, district_code: str) -> str:
    """The named activity centre this incident belongs to, or "" for a background one.

    Derived from the coordinates the record already carries, not stored alongside them:
    there is exactly one source of truth for where a case happened, and this reads it.
    """
    names = _locality_names(district_code)
    d2, i = min(((lat - a[0]) ** 2 + (lng - a[1]) ** 2, i)
                for i, a in enumerate(_attractors(district_code)))
    return names[i] if d2 <= _LOCALITY_RADIUS ** 2 else ""


def sample_point(rng: random.Random, district_code: str) -> tuple[float, float]:
    """A (latitude, longitude) pair, both plain decimals.

    Was WKT for a PostGIS geometry column. The organizers' reference schema stores
    latitude/longitude as DECIMAL, and Catalyst Data Store has no geometry type, so
    coordinates are two ordinary numbers now. Nothing downstream loses anything:
    KDE/DBSCAN always worked on lat/lng arrays, never on PostGIS functions.
    """
    if rng.random() < _BACKGROUND_SHARE:
        lat, lng = _centroids()[district_code]
        spread = _BACKGROUND_SPREAD
    else:
        lat, lng = rng.choice(_attractors(district_code))
        spread = _LOCAL_SPREAD
    return (round(lat + rng.gauss(0, spread), 6), round(lng + rng.gauss(0, spread), 6))


if __name__ == "__main__":
    rng = random.Random(0)
    assert set(_centroids()) == {f"KA{i:02d}" for i in range(1, 32)}
    assert len(_attractors("KA05")) == _N_ATTRACTORS
    assert _attractors("KA05") == _attractors("KA05")     # stable across calls
    assert _locality_names("KA05") == _locality_names("KA05")
    assert len(set(_locality_names("KA05"))) == _N_ATTRACTORS      # no two centres share a name
    _pt = _attractors("KA05")[2]
    assert locality(_pt[0], _pt[1], "KA05") == _locality_names("KA05")[2]
    assert locality(0.0, 0.0, "KA05") == ""                        # background stays unnamed
    print("geo ok —", sample_point(rng, "KA05"), "|", _locality_names("KA05"))
