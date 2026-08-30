"""Unified search over the record layer — FIR number, crime, district, station,
status, modus operandi, and people.

## What was wrong

`/cases?q=` matched by testing whether the WHOLE query string appeared inside ONE
field:

    any(needle in str(row[f]) for f in ("fir_number", "crime_type", "district", "narrative"))

So a single word worked and everything else did not. "theft mandya" is not a substring
of the crime type, nor of the district, nor of any narrative — it matched zero cases,
and the console reported that the register held no theft in Mandya while holding
sixty-one of them. Two words is not an edge case; it is how anybody searches.

Nor could it find a PERSON at all, though people are the entity this platform exists
to reconstruct, and nor could it use a section or a station even though both are
printed on every row it returns.

## What this does instead

Tokenise, then require EVERY token to match SOMETHING — across fields, not within one.
"theft mandya" matches a case whose crime type is Theft and whose district is Mandya;
"mandya theft" matches the same case, because a search box is not a sentence and word
order carries no meaning in one.

Ranked by WHERE a token matched, not merely whether it did. An 18-digit FIR number is
an exact claim about one record and outranks everything; a crime type or a district is
a structured field the officer chose deliberately; a narrative hit is the modus
operandi search, which is genuinely useful and genuinely the weakest signal, so it
ranks last and says so.

Every hit carries `why` — the fields that actually matched — because a result list
whose ordering cannot be explained is one an officer learns to distrust.

## Policy

Scoped exactly as the register is: cases are filtered through `can_view_fir` before
matching, so an IO's search cannot surface another station's case even as a title. A
person is returned only when at least one of their cases is visible to this officer —
a name is a record too, and the identity layer must not become a way around the
station filter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from data import ds
from policy import can_view_fir, mask_person_name

from .agents import sql_agent
from .intents import FIR_NUMBER_RE

# Words that carry no selectivity in a police case search. Dropped so "show me theft
# cases in mandya" searches for the two words that matter rather than failing on
# "show", which appears in no record.
_STOPWORDS = frozenset("""
a an the of in at on for from to with and or is are was were be been show me my give
us list find search look pull up get all any some please pls cases case fir firs
record records file files about into regarding related
""".split())

_SECTION_RE = re.compile(r"^(\d{2,3}[a-z]?)$", re.I)
_STATION_RE = re.compile(r"^(\d{3,5})$")


@dataclass
class Hit:
    kind: str                       # "case" | "person"
    id: str
    title: str                      # what it IS — crime type, or a person's name
    subtitle: str                   # where or what kind
    ident: str                      # the identifier, shown last and set in mono
    why: list[str] = field(default_factory=list)
    score: float = 0.0

    def as_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id, "title": self.title,
                "subtitle": self.subtitle, "ident": self.ident,
                "why": self.why, "score": round(self.score, 3)}


def tokenize(query: str) -> list[str]:
    """Query -> the words worth matching on. Never empty-handed: a query made only of
    stopwords keeps them, because searching for "the" and finding nothing is a better
    answer than searching for nothing and returning everything."""
    words = [w for w in re.split(r"[^\w/]+", (query or "").lower()) if w]
    meaningful = [w for w in words if w not in _STOPWORDS]
    return meaningful or words


# How much a match is worth, by where it landed. A structured field is something the
# officer chose from a fixed vocabulary; a narrative is prose that happens to contain
# the word. Both are real matches and they are not equally strong.
_WEIGHTS = {
    "fir_number": 6.0, "crime_type": 3.0, "district": 3.0, "ps_name": 2.5,
    "case_status": 2.0, "narrative": 1.0,
}
_WHY_LABEL = {
    "fir_number": "FIR number", "crime_type": "crime", "district": "district",
    "ps_name": "station", "case_status": "status", "narrative": "modus operandi",
}


def _score_case(row: dict, tokens: list[str]) -> tuple[float, list[str]]:
    """(score, matched fields). Zero score means at least one token matched nothing,
    which is what makes this an AND across tokens rather than an OR."""
    total = 0.0
    matched: set[str] = set()
    for token in tokens:
        best = 0.0
        best_field = None
        for fname, weight in _WEIGHTS.items():
            value = str(row.get(fname) or "").lower()
            if not value or token not in value:
                continue
            # A token that IS the whole field ("theft" == "theft") is a stronger
            # signal than one buried inside it ("the" inside "theft").
            hit = weight * (1.6 if value == token else 1.0)
            if hit > best:
                best, best_field = hit, fname
        if not best_field:
            return 0.0, []
        total += best
        matched.add(best_field)
    return total, [_WHY_LABEL[f] for f in _WEIGHTS if f in matched]


def _viewable_cases(role: str, ps: str) -> list[dict]:
    # ponytail: one scan of the case table per search, filtered in Python — the same
    # ceiling GET /cases already documents, and the same reason: can_view_fir stays
    # the single definition of who sees what. Push into ZCQL past ~10^4 cases.
    rows = sql_agent.search_firs(role, ps, limit=100_000)
    return [r for r in rows if can_view_fir(role, ps, r["ps_code"])]


def _case_hit(row: dict, score: float, why: list[str]) -> Hit:
    return Hit(kind="case", id=row["fir_id"],
               title=row.get("crime_type") or "Case",
               subtitle=" · ".join(x for x in (
                   row.get("district"), row.get("ps_name"), row.get("case_status")) if x),
               ident=row.get("fir_number") or row["fir_id"],
               why=why, score=score)


def _people(tokens: list[str], role: str, ps: str, limit: int) -> list[Hit]:
    """People whose canonical name contains every token.

    Filtered by whether this officer can see any of their cases: the identity layer
    reconstructs a person from records, and a person the officer may not read any case
    about must not become searchable through the back door.
    """
    if not tokens:
        return []
    rows = ds.query(
        'SELECT "PersonUID", "CanonicalName", "IsHabitualOffender" FROM "vx_person" '
        'WHERE "CanonicalName" LIKE :pat ORDER BY "PageRank" DESC LIMIT 60',
        {"pat": f"%{tokens[0]}%"})
    out: list[Hit] = []
    for r in rows:
        name = (r["CanonicalName"] or "")
        low = name.lower()
        if not all(t in low for t in tokens):
            continue
        cases = sql_agent.person_record(str(r["PersonUID"]))
        visible = [c for c in cases if can_view_fir(role, ps, c["ps_code"])]
        if not visible:
            continue
        out.append(Hit(
            kind="person", id=str(r["PersonUID"]),
            title=mask_person_name(role, name),
            subtitle=(f"{len(visible)} case(s) you can see"
                      + (" · recorded as habitual" if r["IsHabitualOffender"] else "")),
            ident=f"person {r['PersonUID']}",
            why=["name"],
            # Below an exact FIR number, above a narrative-only case match: a named
            # person is a strong, deliberate search, but an officer typing a record
            # number wants that record.
            score=5.0 + min(len(visible), 20) * 0.05))
        if len(out) >= limit:
            break
    return out


def search(query: str, role: str, ps: str, limit: int = 20) -> list[Hit]:
    """Ranked hits across cases and people, scoped to this officer."""
    tokens = tokenize(query)
    if not tokens:
        return []

    hits: list[Hit] = []

    # 1. A record identifier is a yes/no claim about ONE row, and it outranks
    #    everything — including a narrative that happens to contain the digits.
    m = FIR_NUMBER_RE.search(query or "")
    if m:
        for row in sql_agent.fir_by_number(m.group(1), role, ps):
            hits.append(_case_hit(row, 1000.0, ["exact FIR number"]))

    cases = _viewable_cases(role, ps)
    seen = {h.id for h in hits}

    # 2. A bare number that is not a FIR number is a section or a station — both are
    #    printed on every row the register shows, and neither was searchable.
    #
    #    "379" is BOTH shapes: three digits is a valid IPC section and a valid station
    #    code. Deciding between them by pattern picked the wrong one and silently
    #    dropped the other — "379" was routed to the station branch, matched no
    #    station, and fell through to whichever narratives happened to contain the
    #    digits. So both are tried, and the ranking decides: the reading that actually
    #    matches records wins, and if both do, both are shown with `why` saying which.
    for token in tokens:
        if not _SECTION_RE.match(token) and not _STATION_RE.match(token):
            continue
        if _SECTION_RE.match(token) and sql_agent.crime_heads_for_section(token):
            for row in sql_agent.search_firs(role, ps, section=token, limit=limit):
                if row["fir_id"] not in seen:
                    seen.add(row["fir_id"])
                    hits.append(_case_hit(row, 8.0, [f"section {token}"]))
        if _STATION_RE.match(token):
            for row in cases:
                if row["ps_code"] == token and row["fir_id"] not in seen:
                    seen.add(row["fir_id"])
                    hits.append(_case_hit(row, 7.0, [f"police station {token}"]))

    # 3. Every remaining token must match SOMETHING on the row — across fields, which
    #    is the whole difference from the substring check this replaces.
    for row in cases:
        if row["fir_id"] in seen:
            continue
        score, why = _score_case(row, tokens)
        if score > 0:
            hits.append(_case_hit(row, score, why))

    hits += _people(tokens, role, ps, limit=5)
    # Ties broken by recency of the identifier, so two equally-matched cases come back
    # in a stable, meaningful order rather than table order.
    hits.sort(key=lambda h: (-h.score, h.kind != "case", -_numeric(h.id)))
    return hits[:limit]


def _numeric(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
