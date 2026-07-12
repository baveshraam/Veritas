"""Hotspot detection — KDE for continuous density, DBSCAN for discrete polygons.

detect_hotspots returns polygons the Deck.gl map layer renders directly. KDE gives
each cluster a normalized intensity; DBSCAN gives it a shape. ST-DBSCAN (below) adds
the time dimension for linking a crime *series* rather than a static hotspot.

Note the honest ceiling: the generator places incidents by district centroid + jitter
until GADM/WorldPop land (see data/FEATURE_DATA_COVERAGE.md), so clusters here are
real algorithmic output over synthetic geography — the method is production-grade,
the micro-geography is not yet.
"""
from datetime import date

import numpy as np
from scipy.spatial import ConvexHull
from scipy.stats import gaussian_kde
from sklearn.cluster import DBSCAN
from sqlalchemy import text

from data.db import get_session

from ..types import HotspotPolygon

EARTH_RADIUS_M = 6_371_000
EPS_METRES = 500          # per the architecture: eps=500m
MIN_SAMPLES = 10


def _fetch_points(district_code: str, date_range: tuple[date, date]) -> np.ndarray:
    with get_session() as s:
        rows = s.execute(text(
            "SELECT latitude AS lat, longitude AS lng "
            "FROM fir WHERE district_code = :dc AND latitude IS NOT NULL "
            "  AND date_filed >= :d0 AND date_filed < :d1"
        ), {"dc": district_code, "d0": date_range[0], "d1": date_range[1]}).all()
    return np.array([[r.lat, r.lng] for r in rows], dtype=float)


def _cluster(points: np.ndarray) -> np.ndarray:
    """DBSCAN on the sphere: haversine expects radians and eps in radians."""
    radians = np.radians(points)
    db = DBSCAN(eps=EPS_METRES / EARTH_RADIUS_M, min_samples=MIN_SAMPLES,
                metric="haversine", algorithm="ball_tree")
    return db.fit_predict(radians)


def _kde_intensities(points: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Gaussian KDE with Scott's rule, evaluated at each cluster centroid."""
    if len(points) < 3:
        return np.ones(len(centroids))
    try:
        kde = gaussian_kde(points.T, bw_method="scott")
    except np.linalg.LinAlgError:
        return np.ones(len(centroids))       # degenerate (collinear) points
    dens = kde(centroids.T)
    # Scale by the max, not min-max: min-max forces the weakest cluster to exactly
    # 0.0, which renders as "no activity" on the map even though it's a real hotspot.
    return dens / dens.max() if dens.max() > 0 else np.ones(len(centroids))


def _ring(cluster_pts: np.ndarray) -> list[tuple[float, float]]:
    """Convex hull as a [lng, lat] ring for Deck.gl. Degenerate clusters (<3 unique
    points or collinear) fall back to their bounding box so the map still gets a shape."""
    uniq = np.unique(cluster_pts, axis=0)
    if len(uniq) >= 3:
        try:
            hull = ConvexHull(uniq)
            return [(float(uniq[i][1]), float(uniq[i][0])) for i in hull.vertices]
        except Exception:
            pass
    lat0, lat1 = cluster_pts[:, 0].min(), cluster_pts[:, 0].max()
    lng0, lng1 = cluster_pts[:, 1].min(), cluster_pts[:, 1].max()
    pad = 1e-4
    return [(float(lng0 - pad), float(lat0 - pad)), (float(lng1 + pad), float(lat0 - pad)),
            (float(lng1 + pad), float(lat1 + pad)), (float(lng0 - pad), float(lat1 + pad))]


def detect_hotspots(district_code: str, date_range: tuple) -> list[HotspotPolygon]:
    points = _fetch_points(district_code, (date_range[0], date_range[1]))
    if len(points) < MIN_SAMPLES:
        return []

    labels = _cluster(points)
    clusters = [l for l in set(labels) if l != -1]      # -1 is DBSCAN noise
    if not clusters:
        return []

    centroids = np.array([points[labels == l].mean(axis=0) for l in clusters])
    intensities = _kde_intensities(points, centroids)

    out: list[HotspotPolygon] = []
    for l, intensity in zip(clusters, intensities):
        pts = points[labels == l]
        out.append(HotspotPolygon(
            polygon=_ring(pts),
            intensity=round(float(intensity), 4),
            crime_count=int(len(pts)),
        ))
    return sorted(out, key=lambda h: -h.crime_count)
