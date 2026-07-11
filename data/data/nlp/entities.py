"""Entity extraction over queries and FIR text.

Hybrid gazetteer + pattern extractor: IPC sections and vehicle plates are strict
regex (they have hard formats), while LOCATION and GANG resolve against the real
reference tables, and PERSON resolves against the Karnataka name pool plus a
capitalised-sequence fallback for names outside it.

The Orchestrator uses this to seed HippoRAG; the generator's ER pass uses it on
narratives. If AI4Bharat IndicNER weights are provisioned (VERITAS_INDICNER_MODEL),
native Kannada-script extraction runs first and this acts as the backstop.

MISSING EXTERNAL MODEL: AI4Bharat IndicNER. Without it, Kannada-script PERSON
detection is limited to gazetteer hits; English extraction is fully covered.
"""
import csv
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..districts import all_districts
from ..priors import crime_types

_NAMES_CSV = Path(__file__).resolve().parent.parent.parent / "seed" / "derived" / "ka_names.csv"

# Karnataka plate format: KA 05 MJ 1234
_PLATE = re.compile(r"\b(KA[\s-]?\d{2}[\s-]?[A-Z]{1,2}[\s-]?\d{3,4})\b", re.I)
# "IPC 302", "Section 420", "u/s 379"
_IPC_CTX = re.compile(r"\b(?:IPC|I\.P\.C\.?|[Ss]ection|u/s)\s*[:\-]?\s*(\d{2,3}[A-Z]{0,2})\b")
_CAPS_TOKEN = re.compile(r"\b[A-Z][a-z]{2,}\b")


class Entity(BaseModel):
    text: str
    label: Literal["PERSON", "LOCATION", "GANG", "VEHICLE", "IPC_SECTION"]
    start: int
    end: int


@lru_cache(maxsize=1)
def _name_pool() -> set[str]:
    with _NAMES_CSV.open(encoding="utf-8") as f:
        return {r["name"].lower() for r in csv.DictReader(f)}


@lru_cache(maxsize=1)
def _locations() -> set[str]:
    out: set[str] = set()
    for d in all_districts():
        out.add(d.name.lower())
        out.update(a.lower() for a in d.aliases)
    return out


@lru_cache(maxsize=1)
def _known_ipc() -> set[str]:
    return {s for ct in crime_types() for s in ct.ipc_sections}


def _gangs() -> set[str]:
    from ..generator.build import GANGS
    return {g.lower() for g in GANGS}


def _add(found: list[Entity], seen: list[tuple[int, int]], text: str,
         start: int, end: int, label: str) -> None:
    if any(start < e and end > s for s, e in seen):     # no overlapping spans
        return
    seen.append((start, end))
    found.append(Entity(text=text[start:end], label=label, start=start, end=end))


def ner_extract(text: str, lang: Literal["en", "kn"] = "en") -> list[Entity]:
    """Entities in `text`, non-overlapping, ordered by position."""
    if not text:
        return []
    found: list[Entity] = []
    seen: list[tuple[int, int]] = []

    if lang == "kn" and os.getenv("VERITAS_INDICNER_MODEL"):
        for e in _indicner(text):
            _add(found, seen, text, e.start, e.end, e.label)

    for m in _PLATE.finditer(text):
        _add(found, seen, text, m.start(1), m.end(1), "VEHICLE")
    for m in _IPC_CTX.finditer(text):
        _add(found, seen, text, m.start(1), m.end(1), "IPC_SECTION")
    # bare section numbers that are real IPC sections we prosecute under
    for m in re.finditer(r"\b(\d{2,3}[A-Z]{0,2})\b", text):
        if m.group(1) in _known_ipc():
            _add(found, seen, text, m.start(1), m.end(1), "IPC_SECTION")

    lowered = text.lower()
    phrases = [(g, "GANG") for g in _gangs()] + [(l, "LOCATION") for l in _locations()]
    # longest first: "Bangalore Urban" must win over the "Bangalore" alias, since
    # _add drops anything overlapping an already-claimed span.
    for phrase, label in sorted(phrases, key=lambda p: -len(p[0])):
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", lowered):
            _add(found, seen, text, m.start(), m.end(), label)

    for start, end in _person_spans(text):
        _add(found, seen, text, start, end, "PERSON")

    return sorted(found, key=lambda e: e.start)


def _person_spans(text: str) -> list[tuple[int, int]]:
    """Spans anchored on name-pool tokens, merging adjacent capitalised tokens.

    Anchoring on the pool (rather than any capitalised run) is what keeps a
    sentence-initial "Was Ramesh ..." from being read as a person. The span is
    trimmed to the first..last pool token, so "Ramesh Gowda" survives intact.
    """
    tokens = [(m.group(), m.start(), m.end()) for m in _CAPS_TOKEN.finditer(text)]
    spans: list[tuple[int, int]] = []
    group: list[tuple[str, int, int]] = []

    def flush() -> None:
        pool_idx = [i for i, (t, _, _) in enumerate(group) if t.lower() in _name_pool()]
        if pool_idx:
            spans.append((group[pool_idx[0]][1], group[pool_idx[-1]][2]))
        group.clear()

    for tok in tokens:
        if group and text[group[-1][2]:tok[1]] == " ":   # directly adjacent
            group.append(tok)
        else:
            if group:
                flush()
            group.append(tok)
    if group:
        flush()
    return spans


def _indicner(text: str) -> list[Entity]:
    from ai4bharat.ner import IndicNER          # provisioned separately
    return _load_indicner().predict(text)


@lru_cache(maxsize=1)
def _load_indicner():
    from ai4bharat.ner import IndicNER
    return IndicNER(os.environ["VERITAS_INDICNER_MODEL"])


if __name__ == "__main__":
    q = "Was Ramesh Gowda accused under IPC 302 in Kolar, and is he linked to the KGF Syndicate vehicle KA 05 MJ 1234?"
    for e in ner_extract(q):
        print(f"  {e.label:12} {e.text!r}")
