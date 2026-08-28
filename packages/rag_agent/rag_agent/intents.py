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
    "ALIAS_CHECK":       (("another name", "other name", "different name", "different spelling",
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
                           "comparable", "matching cases", "related cases"), "none"),
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
    "NEXT_STEPS":        (("investigate next", "investigated next", "next steps",
                           "what should i do", "what should i focus", "what should i pursue",
                           "should be investigated"), "none"),
    "BRIEFING":          (("prepare the briefing", "prepare a briefing", "case diary",
                           "draft summary", "draft the summary", "prepare the report",
                           "prepare a report"), "none"),
    # The persistent investigation board (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 1) —
    # the conversational surface over data.board/rag_agent.board. All six are
    # case-scoped (NEEDS_CASE, below), the same way CASE_CONTEXT/CASE_PEOPLE/etc. are:
    # "pin this", "save this lead" and "what's on the board" only mean something once
    # a case is open. Deliberately distinctive phrasing (not bare "pin"/"note"/"lead")
    # so these do not silently absorb an unrelated question that happens to share one
    # short word — see intents.classify's own discipline on this.
    # "case board"/"investigation board" are deliberately NOT bare BOARD_VIEW
    # keywords: "pin this to the case board" and "add that to the case board" both
    # contain "case board" as a substring, so a bare keyword here would outscore or
    # tie BOARD_PIN_EVIDENCE on exactly the spec's own example phrasing and every
    # successful pin would render as a board summary instead — found live testing
    # "Pin this to the case board." The remaining phrases below are still specific
    # enough to cover real viewing requests without swallowing an action phrase.
    "BOARD_VIEW":        (("investigation board", "on the board",
                           "board for this case", "what have we established",
                           "what have i established", "have we pinned", "have i pinned",
                           "unresolved questions", "still unresolved", "saved leads",
                           "leads on the board", "leads for this case",
                           "open the investigation board", "open the board"), "none"),
    "BOARD_PIN_EVIDENCE": (("pin this", "pin that", "pin this evidence", "pin that evidence",
                            "save this evidence", "add this to the board",
                            "add that to the case board", "add to the board"), "none"),
    "BOARD_PIN_PERSON":  (("add this person to the investigation", "add him to the investigation",
                           "add her to the investigation", "add them to the investigation",
                           "add this person to the case"), "none"),
    "BOARD_ADD_LEAD":    (("save this as a lead", "save as a lead", "add him as a lead",
                           "add her as a lead", "add this as a lead", "mark this as a lead",
                           "flag this as a lead", "flag as a lead"), "none"),
    "BOARD_ADD_NOTE":    (("add a note", "add a note that", "make a note", "note that this",
                           "add note"), "none"),
    "BOARD_LEAD_STATUS": (("mark that lead", "mark this lead", "mark the lead",
                           "dismiss that lead", "dismiss the lead", "dismiss lead",
                           "remove that lead", "remove the lead", "remove lead",
                           "pursue that lead", "pursue the lead", "lead as pursued",
                           "lead pursued"), "none"),
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
# BOARD_PIN_PERSON also needs a resolved person, but is NOT in NEEDS_SUBJECT: it is
# also in NEEDS_CASE (a board belongs to a case), and the no_case gate runs first —
# adding it here as well would make "no case, no person" report the wrong missing
# thing. Its own missing-person message is produced locally in
# orchestrator._handle_board_intent, once a case is confirmed open.

# Intents that talk ABOUT the open case rather than a named person — meaningless
# without one. "What happened", "who's involved", "what should I investigate next"
# and "prepare the briefing" all assume a case is already in view (SessionFocus.
# active_fir); asked cold, they'd have nothing to read and nothing to say. Every
# BOARD_* intent joins this set for the same reason: a board belongs to a case.
NEEDS_CASE = {"CASE_CONTEXT", "CASE_PEOPLE", "NEXT_STEPS", "BRIEFING",
             "BOARD_VIEW", "BOARD_PIN_EVIDENCE", "BOARD_PIN_PERSON", "BOARD_ADD_LEAD",
             "BOARD_ADD_NOTE", "BOARD_LEAD_STATUS"}

# Questions asking the system to nominate a suspect. The records hold who was accused,
# arrested and charged; they do not hold who "could be" guilty, and inferring it is the
# one thing an evidence-grounded police tool must not do. This is a refusal with a
# reason, not a retrieval that happens to fail.
# Found live via the adversarial battery (docs/superpowers/specs/2026-08-27-
# compositional-semantic-layer-design.md): "Who do you think committed the murder
# in FIR ...?" was ANSWERED, not refused — the literal two-word "who committed"
# match requires the verb to sit immediately after "who", and "do you think" broke
# that adjacency. This is a safety boundary (never name a suspect), not a topic
# keyword, so it is widened to tolerate filler between "who" and the verb phrase —
# the same shape-not-phrase discipline every other regex in this file already
# follows — rather than enumerating "who do you think committed" as its own
# literal alternative.
_NOT_INFERABLE = re.compile(
    r"\b(who (could|might|may|would) (be|have)|likely (suspect|culprit|offender)|"
    r"who\b(?:\s+\S+){0,4}\s+(?:did\s+it|is\s+guilty|committed))\b", re.I)

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
    r"\bwhy (are|were|did) you (show|showing|shown|tell|telling|told|say|said|include|"
    r"select|selecting|selected|choose|choosing|chose|pick|picking|picked|"
    r"surface|surfacing|surfaced)"
    # Passive voice, no "you": "why were those associates surfaced" — a noun (the
    # thing being explained: "associates", "cases") sits between "those" and the
    # participle, unlike the "you"-branch above which has the verb right after "you".
    r"|\bwhy (is|are|was|were) (this|these|that|those)(?: \w+)? "
    r"(relevant|shown|here|important|selected|surfaced|chosen|picked|included|returned|listed)\b",
    re.I)
_EVIDENCE_FOR = re.compile(
    r"\bwhat evidence\b|\bhow do you know\b|\bwhat supports (this|that)\b"
    r"|\bsource for (this|that)\b|\bbasis for (this|that)\b|\bprove (this|that)\b", re.I)
_CASE_LOCATIONS = re.compile(
    r"\bwhere (are|were) (those|these|they)\b|\bwhich districts?\b.*\b(those|these|they)\b"
    r"|\bgeographically concentrated\b", re.I)

# "Go back to the first case" / "return to the previous case" names a case by its
# position in this session's own history, not by FIR number or a fresh search term.
# No case-history stack exists — SessionFocus keeps only the single case currently in
# view — so this used to fall to a bare CRIME_SEARCH-shaped keyword score ("case"),
# which ran a real semantic search over the literal words and confidently returned
# citations for whatever the vector index happened to think "first case" resembled —
# unrelated cases, cited and answered as if the request had been understood. Refusing
# honestly (you cannot un-search a case you never named) is the correct answer; the
# active case is left untouched, exactly as if this turn had not been asked.
_CASE_REFERENCE_UNSUPPORTED = re.compile(
    r"\b(go|switch|return|come|head)\s+back\s+to\s+(the\s+)?(first|previous|prior|"
    r"earlier|last|original|other)\s+case\b"
    r"|\b(return|switch)\s+to\s+(the\s+)?(first|previous|prior|earlier|last|original|"
    r"other)\s+case\b"
    r"|\bthe\s+(first|previous|prior|earlier|original)\s+case\s+(again|once more)\b"
    # The pattern above only fires when an ORDINAL sits directly before "case" — but
    # "go back to the CASE WE STARTED WITH" names the same thing (a case by its
    # position in this session, not an ID) with the qualifier trailing "case" instead
    # of leading it. Found live: this exact phrasing skipped the refusal entirely and
    # fell to a real semantic search, which had enough confidence to pass CRAG and
    # returned 5 confidently-cited but completely unrelated records — worse than a
    # refusal, because nothing on screen signalled the mismatch. Two more shapes of
    # the same underlying reference: "back to that case" (a bare demonstrative, no
    # ordinal at all) and "the case we started/began/opened with" (no "back to").
    r"|\b(go|switch|return|come|head)\s+back\s+to\s+(the\s+)?case\s+(we|i|you)\b"
    r"|\b(go|switch|return|come|head)\s+back\s+to\s+(that|this|the\s+other)\s+case\b"
    r"|\bthe\s+case\s+(we|i|you)\s+(started|began|opened)(\s+with)?\b",
    re.I)

# Cross-entity timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 3) — checked as a
# shape, not a keyword-scored topic, for the same reason CASE_LOCATIONS/EXPLAIN_
# REASONING are: "what happened before this incident" and "what happened around
# the time he was involved" both contain "what happened", which would otherwise
# tie CASE_CONTEXT's own "what happened" keyword and lose on dict-order tie-break.
_TIMELINE = re.compile(
    r"\btimelines?\b|\bchronology\b|\bsequence of events\b|\baround the time\b"
    r"|\bwhat happened before (this|that)\b|\bwhat happened after (this|that)\b"
    r"|\bbefore (this|that) (incident|event|transaction|case|arrest)\b"
    r"|\bafter (this|that) (incident|event|transaction|case|arrest)\b",
    re.I)

# "Show me events involving both of them" / "are there events connecting these two
# people" / "why are these events connected" — a request to compare TWO entities'
# timelines, not to read one. Checked before CAUSAL's bare "why" keyword can steal
# "why are these events connected" (see classify()'s existing EXPLAIN_REASONING
# precedent for the same class of collision).
_TIMELINE_CONNECTION = re.compile(
    r"\bevents?\s+(connecting|involving both|linking)\b"
    r"|\bconnect(ing)?\s+these\s+(two|people)\b"
    r"|\bwhat\s+connects\s+(these|those|them)\b"
    r"|\bhow\s+(are|is)\s+(these|those|they)\s+(connected|linked)\b"
    r"|\bwhy\s+(are|is)\s+(these|those|this|that)\s+(events?|connections?|links?)\s+connected\b"
    r"|\bare there (any )?events? connecting\b",
    re.I)

# "Add this event to the investigation board" contains "investigation board" —
# a bare BOARD_VIEW keyword — so without this pre-check it misroutes to a board
# summary instead of pinning, the same collision class BOARD_VIEW's own keyword
# list already documents for "case board" (found live testing this exact spec
# example: v16's fix only covered "case board", not "investigation board").
_BOARD_PIN_EVENT = re.compile(r"\b(add|pin|save)\s+(this|that)\s+event\b", re.I)

# Third-person pronouns that must resolve against the session focus stack. Bare
# "this"/"that" are ambiguous between a personal pronoun ("does *this* have priors" —
# rare, but "tell me about this person" is common) and a determiner in front of an
# ordinary noun ("this district", "that case"). Found live: "how many gangs operate in
# THIS district" matched the pronoun and, with no active person but recent person
# candidates in session, was answered as if it were an ambiguous PERSON question — a
# district-scoped question hijacked into "which person do you mean". The determiner use
# is what has a noun sitting immediately after it, so only exclude those.
_DETERMINER_NOUN = (
    r"district|case|fir|firs|record|records|question|evidence|report|reports|area|"
    r"region|station|city|taluk|crime|hotspot|community|network|trail|gang|gangs|"
    r"pattern|dataset|table|list|data|information|thing|answer"
)
_PRONOUNS = re.compile(
    r"\b(he|him|his|she|her|hers|they|them|their|it|its)\b"
    r"|\b(?:this|that)\b(?!\s+(?:" + _DETERMINER_NOUN + r")s?\b)",
    re.I)


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
    if _CASE_REFERENCE_UNSUPPORTED.search(query or ""):
        return "CASE_REFERENCE_UNSUPPORTED"
    if _BOARD_PIN_EVENT.search(query or ""):
        return "BOARD_PIN_EVIDENCE"
    if _TIMELINE_CONNECTION.search(query or ""):
        return "TIMELINE_CONNECTION"
    if _TIMELINE.search(query or ""):
        return "TIMELINE"
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


# Not in INTENTS: these are matched by regex before keyword scoring runs (see
# classify()), so they carry no keyword tuple to read a visualization kind from.
_EXTRA_VISUALIZATION = {"CASE_LOCATIONS": "map", "TIMELINE": "timeline",
                        "TIMELINE_CONNECTION": "timeline"}

# The complete set of operations classify() can ever return, plus the ones matched
# by regex shape (never in INTENTS, since they carry no keyword tuple) and the two
# structural values semantic_interpreter.py's own follow-up patterns produce
# (RESULT_SET_FOLLOWUP) or fall back to (UNKNOWN). This is the ONE allowlist the
# semantic-planner's model output is validated against — computed from this module's
# own dispatch table rather than hand-duplicated, so it cannot silently drift out of
# sync with what orchestrator.py actually knows how to route.
ALL_OPERATIONS: frozenset[str] = frozenset(INTENTS) | {
    "CAPABILITY", "NOT_INFERABLE", "EXPLAIN_REASONING", "EVIDENCE_FOR",
    "CASE_LOCATIONS", "CASE_REFERENCE_UNSUPPORTED", "TIMELINE", "TIMELINE_CONNECTION",
    "RESULT_SET_FOLLOWUP", "UNKNOWN",
}


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
