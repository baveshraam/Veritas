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
                           "previous cases", "convicted", "arrested before", "rap sheet"),
                          "none"),
    "ALIAS_CHECK":       (("another name", "different name", "different spelling",
                           "alias", "same person", "duplicate"), "network"),
    "PERSON_NETWORK":    (("associate", "associates", "network", "gang", "accomplice",
                           "co-accused", "linked to", "connections", "who does he work"), "network"),
    "FINANCIAL":         (("money", "transaction", "transactions", "account", "transfer",
                           "laundering", "financial", "payment", "funds", "money trail"),
                          "sankey"),
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
    # The four conversational-follow-up intents below all read the *open case*
    # (SessionFocus.active_fir), not a named subject — see NEEDS_CASE. They exist
    # because a real investigation talks ABOUT a case once it's open ("what
    # happened", "who's involved", "what should I do next", "draft the briefing"),
    # not only about a named person or a raw record lookup.
    "CASE_CONTEXT":      (("what happened", "tell me about this case", "case summary",
                           "summarize this case", "summarise this case",
                           "brief facts"), "none"),
    "CASE_PEOPLE":        (("key people", "who is involved", "who's involved",
                           "people involved", "who are the accused",
                           "who are the people"), "network"),
    "NEXT_STEPS":        (("investigate next", "next steps", "what should i do",
                           "what should i focus", "what should i pursue"), "none"),
    "BRIEFING":          (("prepare the briefing", "prepare a briefing", "case diary",
                           "draft summary", "draft the summary", "prepare the report",
                           "prepare a report"), "none"),
}

# Word-boundary matching, not substring — BUG-019: plain `k in q` matched "fir" inside
# "firs" ("show me murder firs"), scoring FIR_LOOKUP on a query that named no FIR.
# Harmless while FIR_LOOKUP's branch is a no-op without a matching FIR_NUMBER_RE, but
# not a property to leave load-bearing by accident.
_KEYWORD_RE = {
    kw: re.compile(r"\b" + re.escape(kw) + r"\b")
    for keywords, _ in INTENTS.values() for kw in keywords
}

# Intents that are meaningless without a subject. Asked without one, the engine used to
# run the whole retrieval pipeline, come back with semantic neighbours, and refuse with
# "check whether the record exists in the system" — which is not why it failed. The
# orchestrator short-circuits these instead, and says which subject is missing.
NEEDS_SUBJECT = {"PERSON_HISTORY", "PERSON_NETWORK", "ALIAS_CHECK", "FINANCIAL", "RISK"}

# Intents that talk ABOUT the open case rather than a named person — meaningless
# without one. "What happened", "who's involved", "what should I investigate next"
# and "prepare the briefing" all assume a case is already in view (SessionFocus.
# active_fir); asked cold, they'd have nothing to read and nothing to say.
NEEDS_CASE = {"CASE_CONTEXT", "CASE_PEOPLE", "NEXT_STEPS", "BRIEFING"}

# Questions asking the system to nominate a suspect. The records hold who was accused,
# arrested and charged; they do not hold who "could be" guilty, and inferring it is the
# one thing an evidence-grounded police tool must not do. This is a refusal with a
# reason, not a retrieval that happens to fail.
_NOT_INFERABLE = re.compile(
    r"\b(who (could|might|may|would) (be|have)|likely (suspect|culprit|offender)|"
    r"who did it|who is guilty|who committed)\b", re.I)

# "What can you do" is a question about the tool, not about the records. Routed through
# retrieval it returned five unrelated criminal profiles and then a refusal telling the
# officer to check whether the record exists in the system.
_CAPABILITY = re.compile(
    # "what all could you answer" was the reported phrasing and the first version of
    # this pattern missed it, because "all" sits between the interrogative and the
    # auxiliary. Indian-English "what all" / "what all can" is common enough here that
    # it is the phrasing to match, not the edge case.
    r"\b(what (all )?(can|could|do|does|would) (you|it|this|veritas)"
    r"|what (kind|sort|type)s? of (question|quer)"
    r"|what are (you|your capabilit)|how do i use)", re.I)

# Three more "shape, not topic" questions — meta-questions ABOUT the conversation
# itself, asked about whatever the previous turn showed. All three read the *last
# turn's own record*, not the retrieval layer, so they must be pulled out before
# keyword scoring the same way CAPABILITY and NOT_INFERABLE already are:
#   - "why are you showing me these people" contains "why", which would otherwise
#     score CAUSAL (a question about crime *causation*, not about the answer itself).
#   - "where are those cases concentrated" contains "where", which would otherwise
#     score HOTSPOT (a fresh cluster-detection query, not "explain the last answer").
_EXPLAIN_REASONING = re.compile(
    r"\bwhy (are|were|did) you (show|showing|shown|tell|telling|told|say|said|include)"
    r"|\bwhy (is|are|was|were) (this|these|that|those) (relevant|shown|here|important)\b",
    re.I)
_EVIDENCE_FOR = re.compile(
    r"\bwhat evidence\b|\bhow do you know\b|\bwhat supports (this|that)\b"
    r"|\bsource for (this|that)\b|\bbasis for (this|that)\b|\bprove (this|that)\b", re.I)
_CASE_LOCATIONS = re.compile(
    r"\bwhere (are|were) (those|these|they)\b|\bwhich districts?\b.*\b(those|these|they)\b"
    r"|\bgeographically concentrated\b", re.I)

# Third-person pronouns that must resolve against the session focus stack.
_PRONOUNS = re.compile(r"\b(he|him|his|she|her|hers|they|them|their|it|its|this|that)\b", re.I)


def classify(query: str) -> str:
    """Highest-scoring intent by keyword hits; UNKNOWN if nothing matches.

    The regex branches run first because they are about the *shape* of the question,
    not its topic. "who could be the suspect" contains no keyword that routes it
    anywhere useful, and "what all could you answer" scores CRIME_SEARCH on the bare
    word "answer" sitting near "cases" — both then ran the full retrieval pipeline and
    refused with a message about records that were never the problem. The three
    conversational-meta patterns (why/evidence/where-those) are the same shape of
    problem one layer up: each contains a common word ("why", "where") that would
    otherwise be captured by an unrelated topic intent (CAUSAL, HOTSPOT).
    """
    q = (query or "").lower()
    if _CAPABILITY.search(query or ""):
        return "CAPABILITY"
    if _NOT_INFERABLE.search(query or ""):
        return "NOT_INFERABLE"
    if _EXPLAIN_REASONING.search(query or ""):
        return "EXPLAIN_REASONING"
    if _EVIDENCE_FOR.search(query or ""):
        return "EVIDENCE_FOR"
    if _CASE_LOCATIONS.search(query or ""):
        return "CASE_LOCATIONS"
    scores: dict[str, int] = {}
    for intent, (keywords, _) in INTENTS.items():
        hits = sum(1 for k in keywords if _KEYWORD_RE[k].search(q))
        if hits:
            scores[intent] = hits

    # CRIME_SEARCH is scored last, because its keywords are not topic words — "show",
    # "list", "find", "cases" are the verbs almost every question in this domain uses.
    # Counting them alongside specific ones let a generic pair outvote a precise single:
    # "Find cases similar to FIR 100222201202600022" scored CRIME_SEARCH 2 ("find",
    # "cases") against SIMILAR_CASES 1 ("similar") and was answered with five unrelated
    # criminal profiles. It is the fallback intent, so it behaves like one.
    specific = {i: n for i, n in scores.items() if i != "CRIME_SEARCH"}
    if specific:
        return max(specific, key=lambda i: (specific[i], -list(INTENTS).index(i)))
    if not scores:
        return "UNKNOWN"
    return "CRIME_SEARCH"


# Not in INTENTS: these three are matched by regex before keyword scoring runs
# (see classify()), so they carry no keyword tuple to read a visualization kind from.
_EXTRA_VISUALIZATION = {"CASE_LOCATIONS": "map"}


def visualization_for(intent: str) -> str:
    if intent in _EXTRA_VISUALIZATION:
        return _EXTRA_VISUALIZATION[intent]
    return INTENTS.get(intent, ((), "none"))[1]


def capability_answer() -> str:
    """What this engine can actually answer.

    Deliberately not a chat feature: one paragraph, no retrieval, no citations —
    because there is nothing to cite. It is scoped to what the INTENTS table above
    actually implements, and it states the limits in the same breath as the
    capabilities, since a capability list that omits them is a sales pitch.
    """
    return (
        "I answer questions against the FIR records held in this system, and I cite "
        "the record behind every claim. I can look up a case by its FIR number; give "
        "a named person's prior cases, known associates and recorded aliases; trace "
        "money between accounts; map crime hotspots and forecast case volume for a "
        "district; score risk and recidivism; and find cases similar to one you name. "
        "I answer in English or Kannada.\n\n"
        "I do not name suspects, infer guilt, or answer from anything other than the "
        "records — where they do not support an answer, I say so instead of guessing. "
        "What I can show you is also limited by your rank and station."
    )


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
