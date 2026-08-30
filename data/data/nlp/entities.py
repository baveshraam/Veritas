"""Entity extraction over queries and FIR text.

Hybrid gazetteer + pattern extractor: IPC sections and vehicle plates are strict
regex (they have hard formats), while LOCATION resolves against the real
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

_NAMES_CSV = Path(__file__).resolve().parent.parent / "seed" / "derived" / "ka_names.csv"

# Karnataka plate format: KA 05 MJ 1234
_PLATE = re.compile(r"\b(KA[\s-]?\d{2}[\s-]?[A-Z]{1,2}[\s-]?\d{3,4})\b", re.I)
# "IPC 302", "Section 420", "u/s 379"
_IPC_CTX = re.compile(r"\b(?:IPC|I\.P\.C\.?|[Ss]ection|u/s)\s*[:\-]?\s*(\d{2,3}[A-Z]{0,2})\b")
_CAPS_TOKEN = re.compile(r"\b[A-Z][a-z]{2,}\b")


class Entity(BaseModel):
    text: str
    # No GANG label. The organizers' ER records no gang, so a GANG entity would have
    # nothing to resolve against — organised-crime grouping is the Louvain community over
    # co-offending (data.gds), which is reached through a *person*, not by typing a gang's
    # name. A gazetteer of invented gang names would only ever match invented gangs.
    label: Literal["PERSON", "LOCATION", "VEHICLE", "IPC_SECTION"]
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
    phrases = [(l, "LOCATION") for l in _locations()]
    # longest first: "Bangalore Urban" must win over the "Bangalore" alias, since
    # _add drops anything overlapping an already-claimed span.
    for phrase, label in sorted(phrases, key=lambda p: -len(p[0])):
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", lowered):
            _add(found, seen, text, m.start(), m.end(), label)

    for start, end in _person_spans(text):
        _add(found, seen, text, start, end, "PERSON")

    return sorted(found, key=lambda e: e.start)


# Query words that start a sentence and are capitalised for that reason alone.
# Without this list an unknown-name fallback reads "Does"/"Show"/"Trace" as people.
_QUERY_STOPWORDS = frozenset("""
does do did is are was were has have had can could would should show list find
trace tell give what which who whom whose where when why how the a an and or but
if any all his her their this that these those him she they them please
forecast predict check search get open review crime crimes case cases report
hotspot hotspots map money risk network associate associates priors
compare compared versus vs
""".split())


def _person_spans(text: str) -> list[tuple[int, int]]:
    """Spans of capitalised tokens that name a person.

    Two tiers, and the second one matters more than it looks:
      1. Anchored on the Karnataka name pool — precise, and keeps a sentence-initial
         "Was Ramesh ..." from being read as a person.
      2. A fallback for capitalised runs that hit NO gazetteer at all. Without it, a
         name the system has never seen is simply invisible to NER, the orchestrator
         sees no subject in the query, and the *previous* turn's person stays in
         focus — so an officer asking about an unknown suspect gets a different
         person's record back with no indication anything was substituted. A name it
         cannot resolve must still be *seen*, so it can be reported as not found.
    """
    tokens = [(m.group(), m.start(), m.end()) for m in _CAPS_TOKEN.finditer(text)]
    spans: list[tuple[int, int]] = []
    group: list[tuple[str, int, int]] = []
    known = _locations()

    def flush() -> None:
        if not group:
            return
        pool_idx = [i for i, (t, _, _) in enumerate(group) if t.lower() in _name_pool()]
        if pool_idx:
            # Extend from the pool-matched core outward through adjacent capitalised
            # tokens that aren't query stopwords or place names. ka_names.csv is a
            # first-name/common-surname SAMPLE, not exhaustive — a less common surname
            # sitting right next to a known first name ("Usha Naika": "Usha" is in the
            # pool, "Naika" is not) used to be clipped to just the pool token, which
            # then resolved to a DIFFERENT, unrelated "Usha" in the database (whichever
            # had the most records) with nothing to show a substitution had happened —
            # a wrong-person answer delivered at full confidence, not an honest "not
            # found". Stopwords are still excluded on the leading side, which is what
            # keeps "Was Ramesh Gowda" as "Ramesh Gowda" and not "Was Ramesh Gowda".
            lo, hi = pool_idx[0], pool_idx[-1]
            while lo > 0 and group[lo - 1][0].lower() not in _QUERY_STOPWORDS \
                    and group[lo - 1][0].lower() not in known:
                lo -= 1
            while hi < len(group) - 1 and group[hi + 1][0].lower() not in _QUERY_STOPWORDS \
                    and group[hi + 1][0].lower() not in known:
                hi += 1
            spans.append((group[lo][1], group[hi][2]))
        else:
            # tier 2: drop stopwords and gazetteer terms; whatever survives is a
            # candidate person name, even though we've never seen it before.
            rest = [t for t in group
                    if t[0].lower() not in _QUERY_STOPWORDS and t[0].lower() not in known]
            # A lone capitalised word at the very start of the query is capitalised
            # because it starts a sentence — it's the verb ("Forecast crime next
            # month"), not a name. A name is either multi-token, or appears somewhere
            # other than position 0.
            if rest and (len(rest) > 1 or rest[0][1] > 0):
                spans.append((rest[0][1], rest[-1][2]))
        group.clear()

    for tok in tokens:
        if group and text[group[-1][2]:tok[1]] == " ":   # directly adjacent
            group.append(tok)
        else:
            flush()
            group.append(tok)
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
