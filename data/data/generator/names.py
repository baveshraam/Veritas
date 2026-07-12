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


def sample_patronym(rng: random.Random) -> str:
    """A father's given name, for the S/o/D/o form every Indian FIR actually uses."""
    names, weights = _pool()["first_m"]
    return rng.choices(names, weights=weights, k=1)[0]


def full_record_name(name: str, patronym: str, gender: str) -> str:
    """The name as a police record actually writes it: "Ramesh Gowda S/o Krishnappa".

    This is not decoration. A bare given name + surname is drawn from a pool small enough
    that unrelated people collide constantly — measured on this generator, 1.4% of random
    pairs "agreed" on name, which makes name agreement nearly worthless as evidence and
    leaves entity resolution with nothing to work from. That is an artefact of the pool,
    not of reality, and the patronymic is exactly how Indian police disambiguate common
    names in practice. Adding it is both more faithful to a real FIR and what restores
    name to being the discriminating field it is in the real world.
    """
    rel = "D/o" if gender == "F" else "S/o"
    return f"{name} {rel} {patronym}"


if __name__ == "__main__":
    rng = random.Random(0)
    names = [sample_name(rng, rng.choice("MF")) for _ in range(2000)]
    assert len(set(names)) < len(names), "expected collisions for the ER demo"

    # With the patronymic, full record names must be far more discriminating.
    full = [full_record_name(sample_name(rng, "M"), sample_patronym(rng), "M")
            for _ in range(2000)]
    bare_rate = 1 - len(set(names)) / len(names)
    full_rate = 1 - len(set(full)) / len(full)
    assert full_rate < bare_rate / 3, (bare_rate, full_rate)
    print(f"names ok — bare collision {bare_rate:.1%} -> with patronym {full_rate:.1%}; "
          f"sample: {full[0]!r}")
