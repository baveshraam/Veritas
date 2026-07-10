"""Prior distributions the synthetic generator draws from.

Committed seed values under seed/derived/ are hand-derived and provenance-marked:
their *shape* follows the NCRB Crime-in-India IPC-head distribution and KSP
per-district crime volumes (Bengaluru Urban dominant), with exact figures
approximate pending the D01/D02/D03 ETL. When those raw datasets are downloaded,
the ETL regenerates these same CSVs — the generator's consuming interface below
does not change.

stdlib only (csv + random); the generator passes its own seeded Random for
reproducibility.
"""
import csv
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .districts import canonical_code

_DERIVED = Path(__file__).resolve().parent.parent / "seed" / "derived"


@dataclass(frozen=True)
class CrimeTypePrior:
    crime_type: str
    weight: float
    ipc_sections: tuple[str, ...]
    chargesheet_rate: float
    conviction_rate: float


@lru_cache(maxsize=1)
def crime_types() -> tuple[CrimeTypePrior, ...]:
    out = []
    with (_DERIVED / "crime_types.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append(CrimeTypePrior(
                crime_type=r["crime_type"],
                weight=float(r["weight"]),
                ipc_sections=tuple(r["ipc_sections"].split("|")),
                chargesheet_rate=float(r["chargesheet_rate"]),
                conviction_rate=float(r["conviction_rate"]),
            ))
    return tuple(out)


@lru_cache(maxsize=1)
def district_weights() -> dict[str, float]:
    out: dict[str, float] = {}
    with (_DERIVED / "district_weights.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["district_code"]] = float(r["crime_weight"])
    return out


def sample_crime_type(rng: random.Random) -> CrimeTypePrior:
    cts = crime_types()
    return rng.choices(cts, weights=[c.weight for c in cts], k=1)[0]


def sample_district(rng: random.Random) -> str:
    codes = list(district_weights())
    return rng.choices(codes, weights=[district_weights()[c] for c in codes], k=1)[0]


if __name__ == "__main__":
    # Every district-weight row must resolve to a real canonical code, and the
    # weighted samplers must respect their weights (dominant categories dominate).
    for code in district_weights():
        assert canonical_code(code) == code, f"unknown district code {code}"
    assert len(district_weights()) == 31

    rng = random.Random(0)
    ct_counts: dict[str, int] = {}
    for _ in range(20000):
        ct = sample_crime_type(rng).crime_type
        ct_counts[ct] = ct_counts.get(ct, 0) + 1
    top = max(ct_counts, key=ct_counts.get)
    assert top == "Theft", f"expected Theft to dominate, got {top}"

    d_counts: dict[str, int] = {}
    for _ in range(20000):
        c = sample_district(rng)
        d_counts[c] = d_counts.get(c, 0) + 1
    assert max(d_counts, key=d_counts.get) == "KA05", "expected Bengaluru Urban dominant"
    print("priors ok:", len(crime_types()), "crime types,", len(district_weights()), "districts")
