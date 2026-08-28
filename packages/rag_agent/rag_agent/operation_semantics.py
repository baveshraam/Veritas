"""The deterministic interpreter's semantic fallback tier: resolve an officer's
phrasing to an operation by meaning, when no keyword or regex shape matched.

## Why this exists

`intents.classify()` is lexical. It is precise and auditable, and it is what should
decide a query it recognises — but it has no opinion at all about *"who does she run
with"*, *"any idea who else got roped into this one"* or *"how likely is this fellow
to do it again"*. Those used to become `UNKNOWN`, which meant one of two things:

  - QuickML reachable  -> a 20-35s round trip (measured, ENGINEERING_BRIEF §12.12) to
    answer a question the officer expected instantly; or
  - QuickML unreachable/cooling down -> a flat refusal to a perfectly ordinary
    question, which is the worst outcome the system can produce short of a wrong
    answer.

This module closes that gap with the embedding model the container **already runs and
already has warm** (`data.vectors`, `BAAI/bge-small-en-v1.5` — it is what the vector
index is built from). One extra forward pass, measured at ~3.5ms.

## This is not a second semantic system

It is the bottom tier of the existing one. It produces nothing but an `operation`
string, it is validated against the same `intents.ALL_OPERATIONS` allowlist the model
path is, and everything downstream — subject resolution, RBAC, retrieval, CRAG,
citations — runs exactly as it does for a keyword match. It never sees the database,
never chooses a subject, and cannot cause an answer to be produced that the evidence
chain does not support. Where QuickML is available and this tier is not confident, the
model still gets consulted and can still override (see
`semantic_interpreter.interpret`).

## Why it needs a reject class, and how that was established

Raw cosine similarity does **not** separate in-domain from out-of-domain queries for
this model. Measured directly: real questions score 0.59-0.85 against these
prototypes and nonsense ("what is the weather today", "tell me a joke", "how do I
reset my password") scores 0.51-0.72 — completely overlapping. The margin between
first and second place separates no better: real questions landed at 0.02-1.57 in
units of the query's own spread, nonsense at 0.02-2.56. **There is no threshold on
either quantity that admits the real questions and rejects the nonsense**, and taking
the argmax unconditionally would answer "what is the weather today" with a confident,
cited hotspot map — the precise failure this project exists to prevent.

The fix is not a better threshold, it is modelling the reject case explicitly.
`_NO_OPERATION` below is a prototype class describing utterances that name a subject
without asking anything *about* it — "tell me about this one", "I mean that person
specifically", a bare name. When that class wins, this tier has no opinion and the
caller's existing behaviour stands unchanged. Measured on the same battery, this
single change:

  - correctly declines all four nonsense queries, including the "what is the weather
    today" -> HOTSPOT case that no threshold caught;
  - correctly declines bare reference utterances ("Tell me about Soom Nadkarni",
    "I meant Usha Naika specifically", "Soom Nadkarni"), which must keep the
    deliberate richest-profile default in `semantic_interpreter` rather than being
    pushed onto whichever facet the embedding noise favours — before the reject class,
    "I meant Usha Naika specifically" resolved to ALIAS_CHECK with a large margin;
  - resolves 13 of 13 real facet questions correctly.

The one measured miss ("any idea who else got roped into this one?" -> declined,
CASE_PEOPLE second) fails *safe*: the turn falls through to the model path or to the
existing refusal, rather than being answered wrongly.

The second gate is structural rather than statistical. **Scope**: only operations the
session can actually support are candidates — person-scoped when a person is resolved,
case-scoped when a case is open, and the four that need neither (`HOTSPOT`,
`FORECAST`, `CRIME_SEARCH`, `CAUSAL`) always. This mirrors `intents.NEEDS_SUBJECT` /
`intents.NEEDS_CASE`, so this tier can never propose an operation that the very next
step is guaranteed to refuse for want of a subject.

## Where a resolved operation sits relative to QuickML

`CONFIDENCE` sits just BELOW `semantic_interpreter._LLM_ROUTING_THRESHOLD`, so this
tier is a floor rather than a replacement: where the model is reachable it is still
consulted and still wins, and where it is not, the turn is answered from this tier
instead of refused. See the comment on `CONFIDENCE` for why the first version had this
the other way round and what that silently cost. Nothing about grounding depends on
this tier being right either way: a mis-resolved operation still retrieves through the
same deterministic tools, is still scored by the same CRAG evaluator, and still either
cites real records or refuses.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

log = logging.getLogger(__name__)

# What each operation IS, in an officer's terms. Deliberately descriptions of the
# operation, not paraphrases of test queries: a prototype written by copying the
# evaluation's own phrasing measures nothing but itself.
PROTOTYPES: dict[str, tuple[str, ...]] = {
    "PERSON_HISTORY": (
        "the past criminal record of a named person",
        "which cases a person has been accused in before",
        "a person's rap sheet and prior offences",
    ),
    "PERSON_NETWORK": (
        "the other offenders a person commits crimes together with",
        "a person's known associates, accomplices and criminal circle",
        "who a person is connected to in the co-offending network",
    ),
    "ALIAS_CHECK": (
        "whether a person is recorded under another name or spelling",
        "aliases and duplicate identities for the same person",
    ),
    "FINANCIAL": (
        "money moving between bank accounts, transfers and laundering",
        "the financial trail and suspicious transactions of a person",
    ),
    "RISK": (
        "how likely a person is to offend again",
        "the danger or recidivism score for a person",
    ),
    "HOTSPOT": (
        "where crimes are geographically clustered on a map",
        "the areas and hotspots with the most incidents",
    ),
    "FORECAST": (
        # "predicted"/"future"/"still to come" carry the whole distinction from
        # CRIME_SEARCH, which asks the same question about the past. Measured on the
        # held-out battery: without the explicit future framing, "how many break-ins
        # were booked in Kolar" — a question purely about what is already on record —
        # resolved to FORECAST.
        "how many crimes are predicted to happen in future weeks or months",
        "the projected trend of case volume in time still to come",
    ),
    "CAUSAL": (
        "why crime is higher in some districts, socioeconomic causes",
        "the effect of unemployment or literacy on crime rates",
    ),
    "CRIME_SEARCH": (
        "a list or count of cases already on record matching a crime type and district",
        "how many offences of a kind were registered or booked in a place in the past",
    ),
    "SIMILAR_CASES": (
        "other cases with the same modus operandi as this one",
        "past cases comparable to the case in view",
    ),
    "CASE_CONTEXT": (
        "a summary of what happened in the case currently open",
        "the brief facts of this case",
    ),
    "CASE_PEOPLE": (
        "the people accused of or involved in the case currently open",
        "who else was named on this case",
    ),
    "NEXT_STEPS": (
        "what the investigator should do or pursue next on this case",
        "recommended investigative leads for the open case",
    ),
    "BRIEFING": (
        "a written case diary paragraph or briefing report to hand over",
    ),
    "TIMELINE": (
        "the chronology and sequence of dated events for a case or person",
    ),
}

# The reject class. Not an operation — the label this module returns "no opinion" for.
# These describe an utterance that SELECTS or REFERS to a subject without asking
# anything about it, which is the shape both a bare reference ("tell me about her")
# and most out-of-domain input land closest to. See the module docstring for why an
# explicit class here works where no similarity or margin threshold did.
NO_OPERATION = "__none__"
_NO_OPERATION_PROTOTYPES = (
    # (a) selects or refers to a subject without asking anything about it
    "tell me about this one",
    "open that record, the one I just named",
    "I mean that person specifically, the one I said",
    "this person here",
    "show me that",
    # (b) out of domain — not a question about crime records at all. Added after the
    # held-out battery in tests/test_operation_semantics.py caught "what time does the
    # canteen close" resolving to CASE_CONTEXT with a case open: the (a) prototypes
    # cover "names a subject, asks nothing", which is a different idea from "asks
    # something this system is not about", and only the first was modelled. Written as
    # descriptions of the reject class, not as paraphrases of the query that exposed
    # it — the fix has to generalise or it is just that query's keyword in disguise.
    "a question about something other than police records or crime",
    "small talk, greetings and everyday chit-chat",
    "an administrative or IT question about using the computer system",
    # A general-knowledge question about a PLACE is the one out-of-domain shape the
    # (b) prototypes above still missed, and it is the dangerous one: HOTSPOT is this
    # vocabulary's geography operation, so "what is the capital of France" resolved to
    # HOTSPOT with a full margin and would have been answered with a real, cited
    # hotspot map of a defaulted district. Named as its own class rather than pushed
    # onto a threshold — the module docstring's argument for why that cannot work
    # applies here unchanged.
    "a geography or general knowledge fact about a country or city, not about crime",
)

# Which operations are even askable given what the session has resolved. Mirrors
# intents.NEEDS_SUBJECT / intents.NEEDS_CASE — those are the same facts, stated for
# the layer that enforces them; this is the same facts, stated for the layer that
# proposes. TIMELINE takes either.
_PERSON_SCOPED = {"PERSON_HISTORY", "PERSON_NETWORK", "ALIAS_CHECK", "FINANCIAL",
                  "RISK", "TIMELINE"}
_CASE_SCOPED = {"CASE_CONTEXT", "CASE_PEOPLE", "NEXT_STEPS", "BRIEFING",
                "SIMILAR_CASES", "TIMELINE"}
_UNSCOPED = {"HOTSPOT", "FORECAST", "CRIME_SEARCH", "CAUSAL"}

# Confidence handed back to semantic_interpreter, which compares it against
# _LLM_ROUTING_THRESHOLD (0.75). Deliberately BELOW it, which is a correction to this
# module's first version: at 0.80 a resolved operation short-circuited the model
# entirely, and that silently discarded everything the model contributes BESIDES the
# operation — above all `constraints`. Measured: "Did anything else happen around the
# same time?" resolves here to TIMELINE (right), but the relative date_range the model
# extracts from it is something no deterministic extractor in this file can parse, and
# it was being thrown away. An embedding argmax over ~35 prototypes is a good floor,
# not a better interpreter than the model.
#
# Below the threshold, this tier does exactly the job it was built for and no more:
#
#   QuickML reachable   -> the model is still consulted and still wins on ties
#                          (`llm_result.confidence >= det.confidence`), so nothing the
#                          model understood is lost.
#   QuickML unreachable -> interpret() returns the deterministic result, which now
#                          carries a real operation instead of UNKNOWN/0.3. That is
#                          this module's actual purpose per the docstring above: the
#                          worst outcome short of a wrong answer is refusing an
#                          ordinary question because the provider is down.
#
# The latency cost is bounded to queries that matched no keyword and no regex shape —
# the tail — which is precisely the set where the model is worth waiting for.
CONFIDENCE = 0.70


@lru_cache(maxsize=1)
def _prototype_matrix():
    """Embed every prototype once per process. ~35 short strings, ~0.6s, lazy — a
    process that never reaches this tier never pays for it."""
    import numpy as np

    from data.vectors import embed

    labels: list[str] = []
    texts: list[str] = []
    for op, descriptions in PROTOTYPES.items():
        for d in descriptions:
            labels.append(op)
            texts.append(d)
    for d in _NO_OPERATION_PROTOTYPES:
        labels.append(NO_OPERATION)
        texts.append(d)
    return labels, np.asarray(embed(texts))


def candidate_operations(has_person: bool, has_case: bool) -> set[str]:
    """The operations worth considering for a session in this state."""
    allowed = set(_UNSCOPED)
    if has_person:
        allowed |= _PERSON_SCOPED
    if has_case:
        allowed |= _CASE_SCOPED
    return allowed


def resolve(query: str, *, has_person: bool, has_case: bool
            ) -> Optional[tuple[str, float]]:
    """(operation, confidence) if the query's meaning is clear enough to act on.

    None means "no opinion" — the caller's existing behaviour (refuse, or ask the
    model) is left exactly as it was. Any failure to embed also returns None: this
    tier is an improvement on a fallback, never a dependency.
    """
    text = (query or "").strip()
    if len(text) < 3:
        return None

    try:
        from data.vectors import embed_one
        labels, protos = _prototype_matrix()
        sims = protos @ embed_one(text)
    except Exception as e:                       # no weights, no numpy, no index — fine
        log.debug("semantic operation resolver unavailable: %s", e)
        return None

    allowed = candidate_operations(has_person, has_case) | {NO_OPERATION}
    best: dict[str, float] = {}
    for label, score in zip(labels, sims):
        if label in allowed:
            best[label] = max(best.get(label, -1.0), float(score))

    winner = max(best, key=lambda op: best[op])
    if winner == NO_OPERATION:
        return None
    return winner, CONFIDENCE
