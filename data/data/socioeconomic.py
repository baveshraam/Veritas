"""D17 ETL — real district socioeconomic ground truth (Census of India 2011).

This is the ONE table in the schema that is not synthetic. Everything else in
`data/` is generated; `district_socioeconomic` is joined in verbatim from the
Census 2011 Primary Census Abstract, because the DoWhy causal layer estimates the
effect of socioeconomic conditions on crime — and a causal claim computed from
fabricated socioeconomic values would be worse than no claim at all.

Source: Census of India 2011, Primary Census Abstract (district level, all 640
districts). Read from the mirror in `PCA_URL`, which reproduces the official PCA
columns verbatim. Validated on load against the published Karnataka aggregates
(see `_STATE_CHECKS`): if the file ever drifts from the real Census totals, the
ETL fails rather than silently loading wrong ground truth.

Every column below is a ratio of two real Census counts. Nothing is modelled,
imputed or smoothed. Two fields the original schema asked for are deliberately
ABSENT, because no real district-level source exists for them and inventing one
is exactly the failure this module exists to prevent:

  - `unemployment`     — India publishes unemployment (PLFS/NSSO) at STATE level
                         only. The district-level labour measure the Census does
                         publish is the marginal-worker rate (below), which is
                         underemployment, not unemployment. It is named for what
                         it is.
  - `police_per_lakh`  — BPR&D and KSP publish police strength state-wide and
                         rank-wise, not per district. Not available at any price
                         we can pay, so it is not a confounder we can adjust for;
                         see `ml_models.causal.effects.CONFOUNDERS`.

Karnataka had 30 districts at the 2011 Census. Vijayanagara (KA31) was carved out
of Ballari in 2021 and therefore has NO Census 2011 record. It is omitted rather
than back-fabricated by splitting Ballari's counts — the panel is 30 real rows.
"""
import csv
import io
import urllib.request
from pathlib import Path

from sqlalchemy import text

from .db import get_session
from .districts import canonical_code

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
RAW_PATH = SEED_DIR / "ground_truth" / "census_2011" / "india-districts-census-2011.csv"
DERIVED_PATH = SEED_DIR / "derived" / "district_socioeconomic.csv"

PCA_URL = (
    "https://raw.githubusercontent.com/nishusharma1608/India-Census-2011-Analysis/"
    "master/india-districts-census-2011.csv"
)
CENSUS_YEAR = 2011

COLUMNS = [
    "district_code", "year", "population", "literacy_rate", "urban_ratio",
    "poverty_index", "marginal_worker_rate", "youth_ratio",
]

# Published Karnataka 2011 aggregates. The derived table must reproduce these from
# the raw counts, or the raw file is not the Census and we must not load it.
# (population: official state total; literacy: CRUDE rate, literates over TOTAL
# population — the 75.36% figure quoted for Karnataka is the *effective* rate,
# over population aged 7+, which the PCA does not break out by district.)
_STATE_CHECKS = {
    "population": (61_095_297, 0),        # exact
    "literacy_rate": (66.53, 0.1),        # published crude rate
    "youth_ratio": (55.1, 0.5),
}


def _fetch_raw() -> Path:
    """Download the PCA once into the gitignored raw-dataset staging area."""
    if RAW_PATH.exists():
        return RAW_PATH
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(PCA_URL, timeout=120) as r:
        RAW_PATH.write_bytes(r.read())
    return RAW_PATH


def derive() -> list[dict]:
    """Raw PCA -> the 30 real Karnataka rows. Pure; no DB, no network beyond the fetch."""
    raw = _fetch_raw().read_text(encoding="utf-8-sig")
    rows = [r for r in csv.DictReader(io.StringIO(raw))
            if r["State name"].strip().upper().startswith("KARNATAKA")]
    if len(rows) != 30:
        raise ValueError(f"expected 30 Karnataka districts in the 2011 PCA, found {len(rows)}")

    out = []
    for r in rows:
        n = lambda k: float(r[k])  # noqa: E731
        pop = n("Population")
        name = r["District name"].strip()
        code = canonical_code(name)
        if code is None:
            # The Census uses 2011 district names; karnataka_districts.csv carries the
            # modern name plus its historical aliases. An unmapped name means the alias
            # map has a hole — load nothing rather than drop a district silently.
            raise ValueError(
                f"Census district {name!r} does not map to any KA code. Add it as an "
                f"alias in seed/karnataka_districts.csv.")
        out.append({
            "district_code": code,
            "year": CENSUS_YEAR,
            "population": int(pop),
            # Crude literacy rate: literates as a share of the TOTAL population.
            "literacy_rate": round(100 * n("Literate") / pop, 3),
            # Urbanisation, measured on households (the PCA's district-level unit).
            "urban_ratio": round(n("Urban_Households") / n("Households"), 5),
            # Poverty: households in the Census's lowest annual income bracket
            # (< Rs 45,000 purchasing-power-parity) as a share of all households.
            "poverty_index": round(n("Power_Parity_Less_than_Rs_45000")
                                   / n("Total_Power_Parity"), 5),
            # Underemployment: workers employed under 6 months of the year.
            "marginal_worker_rate": round(n("Marginal_Workers") / n("Workers"), 5),
            # Young-population share — a first-order crime confounder (offending is
            # concentrated in the late teens/twenties) that also tracks development.
            "youth_ratio": round(n("Age_Group_0_29") / pop, 5),
        })

    _validate(out)
    return sorted(out, key=lambda d: d["district_code"])


def _validate(rows: list[dict]) -> None:
    """Fail loudly if the derived table doesn't reproduce the published state totals."""
    pop = sum(r["population"] for r in rows)
    got = {
        "population": pop,
        # Re-weight the per-district rates back to a state figure by population.
        "literacy_rate": sum(r["literacy_rate"] * r["population"] for r in rows) / pop,
        "youth_ratio": 100 * sum(r["youth_ratio"] * r["population"] for r in rows) / pop,
    }
    for field, (expected, tol) in _STATE_CHECKS.items():
        if abs(got[field] - expected) > tol:
            raise ValueError(
                f"Census PCA check failed: {field} = {got[field]:,.3f}, expected "
                f"{expected:,} (+/-{tol}). The source file is not the 2011 PCA; refusing "
                f"to load it as socioeconomic ground truth.")
    if len({r["district_code"] for r in rows}) != 30:
        raise ValueError("district codes are not unique — the alias map missed a district")


def write_derived(rows: list[dict] | None = None) -> Path:
    """Persist the 30-row derived table so it is reviewable in the diff, not opaque."""
    rows = rows or derive()
    DERIVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DERIVED_PATH.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return DERIVED_PATH


def load() -> int:
    """Upsert the real socioeconomic layer into Postgres. Idempotent.

    Reads the committed derived CSV when present (so a clean checkout needs no
    network), and falls back to deriving it from the raw PCA.
    """
    if DERIVED_PATH.exists():
        with DERIVED_PATH.open(encoding="utf-8") as fh:
            rows = [
                {k: (int(v) if k in ("year", "population") else
                     v if k == "district_code" else float(v))
                 for k, v in r.items()}
                for r in csv.DictReader(fh)
            ]
    else:
        rows = derive()

    cols = ", ".join(COLUMNS)
    vals = ", ".join(f":{c}" for c in COLUMNS)
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "district_code")
    with get_session() as s:
        s.execute(text(
            f"INSERT INTO district_socioeconomic ({cols}) VALUES ({vals}) "
            f"ON CONFLICT (district_code) DO UPDATE SET {upd}"), rows)
    return len(rows)


if __name__ == "__main__":
    path = write_derived()
    print(f"derived -> {path}")
    print(f"loaded {load()} districts of Census 2011 socioeconomic ground truth")
