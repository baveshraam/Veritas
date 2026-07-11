"""Karnataka-flavoured name sampling with realistic collision structure.

Weighted draws from a small KA name pool (seed/derived/ka_names.csv) deliberately
produce Ramesh-Gowda-style collisions — the raw material the Fellegi-Sunter
entity-resolution demo needs. Replaced/expanded by the U3 name corpus later;
name_kn transliteration is filled by data.nlp.transliterate when that lands.
"""
import csv
import random
from functools import lru_cache
from pathlib import Path

_CSV = Path(__file__).resolve().parent.parent / "seed" / "derived" / "ka_names.csv"


@lru_cache(maxsize=1)
def _pool() -> dict[str, tuple[list[str], list[float]]]:
    buckets: dict[str, tuple[list[str], list[float]]] = {
        "first_m": ([], []), "first_f": ([], []), "surname": ([], [])
    }
    with _CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            names, weights = buckets[r["kind"]]
            names.append(r["name"])
            weights.append(float(r["weight"]))
    return buckets


def sample_name(rng: random.Random, gender: str) -> str:
    """Return an English full name. ~8% mononyms (common in South India)."""
    kind = "first_f" if gender == "F" else "first_m"
    names, weights = _pool()[kind]
    first = rng.choices(names, weights=weights, k=1)[0]
    if rng.random() < 0.08:
        return first
    snames, sweights = _pool()["surname"]
    return f"{first} {rng.choices(snames, weights=sweights, k=1)[0]}"


if __name__ == "__main__":
    rng = random.Random(0)
    names = [sample_name(rng, rng.choice("MF")) for _ in range(2000)]
    assert len(set(names)) < len(names), "expected collisions for the ER demo"
    print("names ok — sample:", names[:4])
