"""Intent classification and the reference resolution that makes follow-ups work.

Deterministic keyword+entity classification is the primary path, with the LLM used
only to break ties when it's available. That ordering is deliberate: a police system
should not depend on a model being reachable to understand "does he have priors",
and the deterministic classifier is testable and auditable in a way a prompt is not.
"""
import re
from typing import Optional

from data import SessionFocus
from data.nlp import Entity, ner_extract

# Intent -> (keyword patterns, visualization kind)
INTENTS: dict[str, tuple[tuple[str, ...], str]] = {
    "PERSON_HISTORY":    (("prior", "priors", "history", "record", "previous case",
                           "convicted", "arrested before", "rap sheet"), "none"),
    "ALIAS_CHECK":       (("another name", "different name", "different spelling",
                           "alias", "same person", "duplicate"), "network"),
    "PERSON_NETWORK":    (("associate", "associates", "network", "gang", "accomplice",
                           "co-accused", "linked to", "connections", "who does he work"), "network"),
    "FINANCIAL":         (("money", "transaction", "account", "transfer", "laundering",
                           "financial", "payment", "funds", "money trail"), "sankey"),
    "HOTSPOT":           (("hotspot", "hotspots", "where", "map", "cluster", "area",
                           "location of crime", "crime map"), "map"),
    "FORECAST":          (("forecast", "predict", "next month", "next week", "expect",
                           "trend", "projection", "coming"), "trend"),
    "RISK":              (("risk", "dangerous", "reoffend", "re-offend", "recidivism",
                           "likely to offend"), "none"),
    "CAUSAL":            (("why", "cause", "caused", "because", "correlat",
                           "unemployment", "literacy", "poverty"), "none"),
    "SIMILAR_CASES":     (("similar", "same modus", "same mo", "like this case",
                           "comparable", "matching cases"), "none"),
    "CRIME_SEARCH":      (("show", "list", "find", "cases", "firs", "how many",
                           "count", "theft", "murder", "robbery"), "none"),
    "FIR_LOOKUP":        (("fir", "case number", "case details", "status of"), "none"),
}

# Third-person pronouns that must resolve against the session focus stack.
_PRONOUNS = re.compile(r"\b(he|him|his|she|her|hers|they|them|their|it|its|this|that)\b", re.I)


def classify(query: str) -> str:
    """Highest-scoring intent by keyword hits; UNKNOWN if nothing matches."""
    q = (query or "").lower()
    scores: dict[str, int] = {}
    for intent, (keywords, _) in INTENTS.items():
        hits = sum(1 for k in keywords if k in q)
        if hits:
            scores[intent] = hits
    if not scores:
        return "UNKNOWN"
    return max(scores, key=lambda i: (scores[i], -list(INTENTS).index(i)))


def visualization_for(intent: str) -> str:
    return INTENTS.get(intent, ((), "none"))[1]


def has_unresolved_reference(query: str, entities: list[Entity]) -> bool:
    """A pronoun with no person named in the query itself => needs the focus stack."""
    if not _PRONOUNS.search(query or ""):
        return False
    return not any(e.label == "PERSON" for e in entities)


def resolve_focus(query: str, focus: SessionFocus) -> tuple[SessionFocus, list[Entity]]:
    """Update the focus stack from this turn's entities, carrying forward anything
    the query didn't restate. This is what makes "does he have priors" work."""
    entities = ner_extract(query or "", "en")
    persons = [e.text for e in entities if e.label == "PERSON"]
    locations = [e.text for e in entities if e.label == "LOCATION"]

    updated = focus.model_copy(deep=True)
    if persons:
        updated.active_person = None      # resolved to an id by the orchestrator
    if locations:
        updated.active_location = locations[0]
    return updated, entities


def named_person(entities: list[Entity]) -> Optional[str]:
    for e in entities:
        if e.label == "PERSON":
            return e.text
    return None
