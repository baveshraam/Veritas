"""Canonical Karnataka district reconciliation — the pipeline's Step 0.

Every external dataset (NCRB, Census, GADM, KGIS) spells/segments Karnataka
districts differently. This maps any spelling to one canonical `district_code`
(KA01..KA31) so every downstream join holds. Uses stdlib csv — the reference
table is 31 controlled rows, no dependency needed.
"""
import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple, Optional

_CSV = Path(__file__).resolve().parent / "seed" / "karnataka_districts.csv"


class District(NamedTuple):
    code: str
    name: str
    aliases: tuple[str, ...]
    kannada_names: tuple[str, ...] = ()


def _norm(name: str) -> str:
    # Case/space/punctuation-insensitive key: "Bengaluru (Urban)" -> "bengaluruurban".
    return re.sub(r"[^a-z0-9]", "", name.lower())


@lru_cache(maxsize=1)
def all_districts() -> tuple[District, ...]:
    rows = []
    with _CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            aliases = tuple(a for a in (r["aliases"] or "").split("|") if a)
            kannada = tuple(k.strip() for k in (r.get("kannada_names") or "").split("|")
                            if k.strip())
            rows.append(District(r["district_code"], r["canonical_name"], aliases, kannada))
    return tuple(rows)


@lru_cache(maxsize=1)
def kannada_name_map() -> dict[str, str]:
    """Kannada-script district spelling -> canonical English name.

    A closed, 31-entry gazetteer, not a translation — used by data/nlp/translate.py
    to structurally close the "ಮಂಡ್ಯ (Mandya) -> Mandi" class of NLLB mistranslation
    (ENGINEERING_BRIEF.md §10): a Kannada district span is looked up here and
    replaced with the correct English name directly, never left to the model.
    Sourced from kn.wikipedia.org's district list, cross-checked 2026-08-27; treat
    as a starting gazetteer to extend/correct as real officer queries surface gaps,
    not a final, natively-reviewed reference.
    """
    idx: dict[str, str] = {}
    for d in all_districts():
        for kn in d.kannada_names:
            idx[kn] = d.name
    return idx


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    idx: dict[str, str] = {}
    for d in all_districts():
        idx[_norm(d.code)] = d.code
        idx[_norm(d.name)] = d.code
        for a in d.aliases:
            idx[_norm(a)] = d.code
    return idx


def canonical_code(name: str) -> Optional[str]:
    """Any district spelling/alias/code -> canonical KA code, or None if unknown."""
    if not name:
        return None
    return _lookup().get(_norm(name))


def canonical_name(code: str) -> Optional[str]:
    for d in all_districts():
        if d.code == code:
            return d.name
    return None


if __name__ == "__main__":
    # Smoke: alias spellings across datasets all resolve to the same code.
    assert canonical_code("Bangalore Urban") == canonical_code("Bengaluru Urban") == "KA05"
    assert canonical_code("Gulbarga") == canonical_code("Kalaburagi") == "KA16"
    assert canonical_code("Chikmagalur") == "KA10"
    assert canonical_code("nowhere") is None
    assert len(all_districts()) == 31
    print("districts ok:", len(all_districts()))
