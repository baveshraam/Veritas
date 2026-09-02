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
    # "convicted" was a PERSON_HISTORY keyword, and it is a CASE STATUS: "show me
    # convicted theft cases in Bagalkot" scored PERSON_HISTORY and was answered with
    # somebody's criminal record. Found by the officer-input corpus (31 of 1,115
    # inputs hit it). The person-scoped reading — "has he been convicted" — is kept
    # as a shape below (_PERSON_CONVICTION), where the subject is explicit.
    "PERSON_HISTORY":    (("prior", "priors", "history", "record", "previous case",
                           "previous cases", "arrested before", "rap sheet"),
                          "none"),
    "ALIAS_CHECK":       (("another name", "other name", "other spellings", "different name",
                           "different spelling", "different spellings", "spellings",
                           "alias", "aliases", "same person", "same man", "same individual",
                           "duplicate", "duplicate record"), "network"),
    "PERSON_NETWORK":    (("associate", "associates", "network", "gang", "accomplice",
                           "co-accused", "linked to", "connections", "who does he work"), "network"),
    # The plurals are listed explicitly for the same reason "areas" is below: the
    # keyword match is word-bounded, so "transfer" never matched "transfers" and
    # "show me the bank transfers" scored CRIME_SEARCH on the bare verb "show".
    "FINANCIAL":         (("money", "transaction", "transactions", "account", "accounts",
                           "transfer", "transfers", "bank", "laundering", "financial",
                           "payment", "payments", "funds", "money trail"),
                          "sankey"),
    "HOTSPOT":           (("hotspot", "hotspots", "where", "map", "cluster", "area",
                           # "areas" is how the question is actually written ("which
                           # AREAS have the most theft") and the singular keyword's
                           # word boundary never matched it.
                           "areas", "locality", "localities", "clusters",
                           "location of crime", "crime map"), "map"),
    "FORECAST":          (("forecast", "forecasts", "predict", "predicted",
                           "prediction", "predictions", "next month", "next week",
                           "expect", "expected",
                           # The plurals again: "what are the crime TRENDS" is
                           # the phrasing, and \btrend\b never matched it.
                           "trend", "trends", "projection", "projections",
                           "coming"), "trend"),
    "RISK":              (("risk", "dangerous", "reoffend", "re-offend", "recidivism",
                           "likely to offend"), "none"),
    "CAUSAL":            (("why", "cause", "caused", "because", "correlat",
                           "unemployment", "literacy", "poverty",
                           # A judge or officer asking about the platform's own
                           # §9-required sociological-insight capability rarely
                           # says "correlate" or "poverty" — live-tested phrasing
                           # like "socio-economic conditions" or "social factors"
                           # missed CAUSAL entirely and fell through to a plain
                           # CRIME_SEARCH count, silently dropping the causal
                           # question being asked.
                           "socio-economic", "socioeconomic", "social factor",
                           "social background", "demographic", "urbanization",
                           "urbanisation", "migration", "economic condition",
                           "economic stress", "education level"), "none"),
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
                           "should be investigated", "what leads", "any leads",
                           "leads are there"), "none"),
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
                            "add that to the board", "add this to the case board",
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

# Operations that read or describe the PREVIOUS turn (or the system itself), rather
# than making a fresh investigative ask of their own — a meta-turn, not a new
# request. Used by orchestrator.node_orchestrate to decide whether THIS turn's own
# operation replaces state.last_request, or whether the PRIOR turn's last_request
# should simply carry forward unchanged. Found live (2026-08-28): a correction
# ("actually Mysuru, not Bengaluru Urban") typed right after a "Only these?" turn
# was handed that RESULT_SET_FOLLOWUP turn's own last_request as "the previous
# request" to correct — a meta-operation with no district field of its own to
# override — and the model produced a plausible-shaped but wrong answer (more of
# the OLD district's results) instead of a fresh search for the new one. A
# correction has to correct the last SUBSTANTIVE request, not whatever meta-turn
# happened to sit between it and the officer's new question.
META_OPERATIONS = {
    "CAPABILITY", "NOT_INFERABLE", "EXPLAIN_REASONING", "EVIDENCE_FOR",
    "CASE_LOCATIONS", "CASE_REFERENCE_UNSUPPORTED", "RESULT_SET_FOLLOWUP",
    "BOARD_VIEW", "BOARD_PIN_EVIDENCE", "BOARD_PIN_PERSON", "BOARD_ADD_LEAD",
    "BOARD_ADD_NOTE", "BOARD_LEAD_STATUS",
}

# Operations where a woven narrative genuinely adds something the evidence list alone
# doesn't already say — a financial trail's "what stands out", a network's "who's
# connected and how", a risk score's "why", a comparison's "here's how these two
# differ". Everything NOT in this set is a direct factual retrieval (a status, a
# count, a list of names/locations/dates) where the extractive template ("[1] ...
# [2] ...") already says exactly what the records say — an LLM call there buys
# nothing but 20-30s of latency for a rephrasing of a list. Used by
# synthesis_agent.synthesize() to decide whether QuickML is worth calling at all;
# unlike NEEDS_SUBJECT/NEEDS_CASE this is about the SHAPE OF THE ANSWER, not what a
# question requires to be askable, but it belongs here for the same reason those do —
# one place that knows what each operation actually is, read by whichever layer needs
# that fact next.
NEEDS_NARRATIVE_SYNTHESIS = {
    "PERSON_HISTORY", "PERSON_NETWORK", "ALIAS_CHECK", "FINANCIAL", "RISK", "CAUSAL",
    "SIMILAR_CASES", "NEXT_STEPS", "BRIEFING", "TIMELINE_CONNECTION",
    # Set by orchestrator._run_plan once a general multi-step plan (see
    # semantic_interpreter's SemanticRequest.plan_steps) finishes executing —
    # never produced by classify() or the model directly. A plan's whole point is
    # tying several steps' evidence together ("here's what connects them"), which
    # is exactly the narrative case, not a single direct-retrieval fact.
    "INVESTIGATION_PLAN",
}

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
    r"who\b(?:\s+\S+){0,4}\s+(?:did\s+it|is\s+guilty|committed))\b"
    # "Who would you arrest?" / "who would you charge" / "name the offender" —
    # the same request in the imperative, and the form a supervising officer
    # actually uses. Unanswered by the branch above, which needs the word
    # "guilty" or a completed verb of commission.
    r"|\bwho\s+would\s+you\s+(?:arrest|charge|book|pick\s+up|suspect|name)\b"
    r"|\b(?:name|identify|give\s+me)\s+the\s+(?:likely\s+)?(?:culprit|offender|suspect|accused\s+person|guilty\s+party)\b"
    r"|\bwho\s+(?:may|might)\s+be\s+responsible\b"
    r"|\bwho\s+could\s+have\s+been\s+involved\b", re.I)

# "What can you do" is a question about the tool, not about the records. Routed through
# retrieval it returned five unrelated criminal profiles and then a refusal telling the
# officer to check whether the record exists in the system.
# "What can you do" is a question about the tool, not about the records. Routed through
# retrieval it returned five unrelated criminal profiles and then a refusal telling the
# officer to check whether the record exists in the system.
#
# Widened well past capability listing, because the questions a magistrate puts FIRST
# are about the machine's standing, not its features: "do you decide guilt", "are you a
# witness", "can this be used in court", "should I rely on this alone", "do you ever
# guess". Every one of those fell to UNKNOWN, and a system that cannot answer "do you
# decide guilt" is one no court should let near a case file. See capability_answer().
_CAPABILITY = re.compile(
    # "what all could you answer" was the reported phrasing and the first version of
    # this pattern missed it, because "all" sits between the interrogative and the
    # auxiliary. Indian-English "what all" / "what all can" is common enough here that
    # it is the phrasing to match, not the edge case.
    #
    # The negative lookahead is load-bearing: "what does this MEAN" and "what does this
    # NOT establish" are questions about a RESULT, not about the tool, and they were
    # being answered with a capability paragraph.
    # The object is what makes it a capability question. Without it, "what would
    # you need to be sure?" and "what does this percentage mean?" matched here and
    # were answered with a paragraph about the tool.
    r"\b(what (all )?(can|could|do|does|would) "
    r"(?:you|it|this|veritas|this system|the system|this tool|the tool)\s+"
    # An adverb can sit between the pronoun and the verb — "what all can you ACTUALLY
    # answer for me" is the phrasing the live officer-session gate uses, and pinning
    # the verb to the next word turned it into UNKNOWN.
    r"(?:\w+\s+){0,2}?"
    r"(?:do|answer|handle|help|tell\s+me|show\s+me|give\s+me|provide|support)\b"
    r"|what (kind|sort|type)s? of (question|quer)"
    # "what are you ASSUMING" / "what are you inferring" are questions about the
    # ANSWER, and were being met with a paragraph about the tool.
    r"|what are you(?!\s+(?:assuming|inferring|saying|doing|going|not|based))\b"
    r"|what are your capabilit|how do i use)"
    # --- what this system IS -------------------------------------------------
    r"|\bwhat\s+is\s+(?:this|the)\s+(?:system|tool|thing|platform|veritas)\b"
    r"|^\s*what\s+are\s+you\s*\??\s*$"
    r"|\bwho\s+(?:built|made|created|wrote)\s+(?:you|this)\b"
    r"|\bare\s+you\s+(?:an?\s+)?(?:ai|model|bot|machine|witness|expert|officer|"
    r"investigator|lawyer|judge)\b"
    # --- what it holds -------------------------------------------------------
    r"|\bwhat\s+(?:data|records?|information|sources?)\s+do\s+you\s+(?:have|hold|use)\b"
    r"|\bwhat\s+(?:data|records?)\s+do\s+you\s+have\s+access\s+to\b"
    r"|\bwhere\s+does\s+your\s+data\s+come\s+from\b"
    r"|\bhow\s+(?:much|many)\s+(?:data|records?|cases?)\s+do\s+you\s+(?:have|hold)\b"
    r"|\bhow\s+(?:current|recent|up.to.date|fresh)\s+is\s+your\s+data\b"
    # --- its standing: the questions that decide whether it is admissible ----
    r"|\bdo\s+you\s+(?:decide|determine|establish|find|judge)\s+guilt\b"
    r"|\bdo\s+you\s+(?:decide|determine)\s+(?:who\s+is\s+guilty|innocence)\b"
    r"|\bcan\s+you\s+convict\b|\bdo\s+you\s+convict\b"
    r"|\bdo\s+you\s+(?:make|carry\s+out)\s+(?:arrests|an\s+arrest)\b"
    r"|\bis\s+your\s+output\s+evidence\b"
    r"|\bcan\s+(?:this|your\s+output|it)\s+be\s+used\s+in\s+court\b"
    r"|\bis\s+(?:this|it)\s+admissible\b"
    r"|\bdo\s+you\s+replace\s+(?:an?\s+)?(?:investigating\s+officer|investigator|"
    r"officer|human)\b"
    r"|\bshould\s+I\s+rely\s+on\s+(?:this|it)\s+alone\b"
    r"|\bcan\s+I\s+act\s+on\s+(?:this|it)\s+by\s+itself\b"
    r"|\bdo\s+you\s+ever\s+guess\b|\bdo\s+you\s+(?:make\s+things\s+up|hallucinate)\b"
    r"|\bwhat\s+do\s+you\s+do\s+when\s+you\s+(?:do\s+not|don.t)\s+know\b"
    r"|\bwhat\s+happens\s+when\s+the\s+records\s+do\s+not\s+support\b"
    r"|\bwhat\s+(?:are|is)\s+(?:your|the)\s+limits?\b"
    r"|\bwhat\s+can\s+you\s+not\s+do\b"
    # --- oversight, bias and accountability ----------------------------------
    r"|\b(?:is|are)\s+(?:this|these|you|the\s+(?:answer|output|result|system))\s+biased\b"
    r"|\bcould\s+(?:this|the\s+(?:answer|result|system))\s+be\s+biased\b"
    r"|\bhow\s+do\s+you\s+(?:guard|protect)\s+against\s+bias\b"
    r"|\bdo\s+you\s+audit\s+for\s+bias\b"
    r"|\bare\s+you\s+profiling\b|\bis\s+this\s+predictive\s+policing\b"
    r"|\bdoes\s+this\s+(?:target|single\s+out)\s+a\s+community\b"
    r"|\bcould\s+this\s+over.?police\b"
    r"|\bis\s+(?:a\s+)?human\s+reviewing\b|\bis\s+any\s+of\s+this\s+automated\b"
    r"|\bdoes\s+anything\s+happen\s+automatically\b"
    r"|\bwho\s+is\s+accountable\b|\bwho\s+is\s+responsible\s+for\s+this\s+output\b"
    r"|\bis\s+(?:this|my)\s+(?:decision|query|question)\s+(?:logged|recorded)\b"
    r"|\bis\s+there\s+an\s+audit\s+trail\b"
    r"|\bcan\s+(?:this|the\s+answer)\s+be\s+(?:reproduced|reviewed\s+later)\b"
    r"|\bwould\s+you\s+give\s+the\s+same\s+answer\b"
    r"|\bwho\s+can\s+see\s+that\s+I\s+asked\b"
    # --- rights framing ------------------------------------------------------
    r"|\bis\s+this\s+fair\s+to\s+the\s+accused\b"
    r"|\bdoes\s+(?:this|being\s+on\s+this\s+list)\s+(?:presume|imply)\s+guilt\b"
    r"|\bdoes\s+an\s+accusation\s+mean\b"
    r"|\bdo\s+you\s+distinguish\s+accused\s+from\s+convicted\b"
    r"|\bis\s+(?:an\s+)?acquittal\s+counted\s+the\s+same\b"
    r"|\bis\s+this\s+person\s+presumed\s+innocent\b"
    # --- access scope, asked of the tool -------------------------------------
    r"|\bwhat\s+am\s+I\s+allowed\s+to\s+see\b"
    r"|\bwhat\s+is\s+my\s+access\s+scope\b"
    r"|\bwould\s+a\s+(?:senior|higher).{0,12}officer\s+see\s+more\b",
    re.I)

# Three more "shape, not topic" questions — meta-questions ABOUT the conversation
# itself, asked about whatever the previous turn showed. All three read the *last
# turn's own record*, not the retrieval layer, so they must be pulled out before
# keyword scoring the same way CAPABILITY and NOT_INFERABLE already are:
#   - "why are you showing me these people" contains "why", which would otherwise
#     score CAUSAL (a question about crime *causation*, not about the answer itself).
#   - "where are those cases concentrated" contains "where", which would otherwise
#     score HOTSPOT (a fresh cluster-detection query, not "explain the last answer").
# --- "how did you decide that?" — the auditor's question, in every phrasing -------
#
# This used to be a list of phrasings, and a list of phrasings is what an auditor walks
# straight past. Measured against a 600-line corpus of what a magistrate, defence
# counsel or supervising officer actually asks (tests/judge_inputs.py), 338 of them
# missed — "How did you determine this?", "On what basis?", "What is your reasoning
# here?", "Where does this come from?", a bare "why?". Each was then answered by a
# FRESH retrieval: "Where did this come from?" scored HOTSPOT on the word "where" and
# returned a cluster map in reply to a question about provenance.
#
# So it is built out of shapes now. The pieces are named because the whole is long,
# and a 40-line regex nobody can read is a 40-line regex nobody will correct.

# The verbs a derivation question turns on. "How did you X this" is an explanation
# request for every X in here, and no amount of phrase-listing covers them one by one.
_DERIVE_VERB = (
    r"(?:deriv\w*|decid\w*|determin\w*|conclud\w*|infer\w*|reason\w*|"
    r"arriv\w*|reach\w*|get|got|getting|obtain\w*|produc\w*|generat\w*|"
    r"comput\w*|calculat\w*|work\w*\s+(?:this|that|it)\s+out|figur\w*\s+out|"
    r"build|built|construct\w*|put\s+(?:this|that|these|those|it)\s+together|"
    r"come\s+up\s+with|came\s+up\s+with|justif\w*|"
    r"rank\w*|order\w*|sort\w*|scor\w*|weigh\w*|filter\w*|narrow\w*|"
    r"pick\w*|choos\w*|chose|chosen|select\w*|match\w*|identif\w*|"
    r"link\w*|connect\w*|resolv\w*|associat\w*|group\w*|cluster\w*|"
    r"flag\w*|surfac\w*|includ\w*|shortlist\w*|estimat\w*|predict\w*)"
)

# What the officer points AT — a demonstrative or a pronoun standing in for the answer
# on screen. This is what separates "why is THIS first" (explain the result) from "why
# is crime higher in Kolar" (a genuine causal question about the world).
_THAT = r"(?:this|that|these|those|it|them|they|he|she|him|her|the\s+\w+)"

# The nouns that make a "why is this X" question one about the WORLD rather than about
# the answer. Guarded separately below, in _WORLD_QUESTION.
_WORLD_NOUN = r"(?:crime|crimes|district|districts|area|areas|region|state|city|town)"

_EXPLAIN_REASONING = re.compile(
    # 1. "why are you showing / selecting / deriving these"
    r"\bwhy\s+(?:are|were|did|do|does)\s+you\b[^?.]{0,40}?"
    r"\b(?:show\w*|tell\w*|told|say\w*|said|" + _DERIVE_VERB[4:-1] + r")"
    # 2. "why is this relevant / shown / connected / in the timeline / first"
    r"|\bwhy\s+(?:is|are|was|were)\s+" + _THAT + r"(?:\s+\w+){0,2}?\s+"
    r"(?:relevant|shown|here|important|selected|surfaced|chosen|picked|included|"
    r"returned|listed|connected|linked|related|flagged|derived|first|top|"
    r"ranked|above|strongest|at\s+the\s+top|"
    r"on\s+the\s+(?:timeline|map|board|list)|in\s+the\s+(?:timeline|list|results?|network))\b"
    # 3. "why is that A hotspot" — a predicate NOUN, which branch 2 cannot reach.
    r"|\bwhy\s+(?:is|are|was|were)\s+(?:this|these|that|those|it)\s+(?:a\s+|an\s+)?"
    r"(?:hotspot|cluster|associate|lead|match|suspect|risk|community|connection|"
    r"finding|result|priority)\b"
    # 4. "how did YOU decide / derive / rank / choose ..." — method, any of the verbs.
    r"|\bhow\s+(?:are|were|did|do|does|have|has)\s+(?:you|we)\b[^?.]{0,50}?\b"
    + _DERIVE_VERB +
    # 5. Passive: "how was this derived / calculated / worked out / arrived at"
    r"|\bhow\s+(?:was|were|is|are)\s+" + _THAT + r"[^?.]{0,30}?\b" + _DERIVE_VERB +
    # 6. "show me the chain / your working / the reasoning", "walk me through ..."
    r"|\b(?:show|explain|describe|give)\s+(?:me\s+)?(?:the\s+|your\s+)?"
    r"(?:chain|derivation|reasoning|rationale|working|provenance|logic|method|"
    r"methodology|process|steps|workings)\b"
    r"|\bshow\s+(?:me\s+)?(?:your\s+)?work\b"
    r"|\b(?:walk|take)\s+me\s+through\b"
    # 7. "on what basis", "what is the basis / reasoning / logic / process"
    r"|\bon\s+what\s+(?:basis|grounds|footing)\b"
    r"|\bwhat\s+(?:is|was|were)\s+(?:the|your)\s+"
    r"(?:basis|reasoning|logic|rationale|process|method|methodology|steps?|grounds)\b"
    r"|\bwhat\s+steps?\b[^?.]{0,20}\b(?:take|took|taken|involved)\b"
    r"|\bwhich\s+step\b"
    # 8. "what is this based on", "what did you use", "what made / led you to say that"
    r"|\bwhat\s+(?:is|are|was|were)\s+" + _THAT + r"\s+(?:based\s+on|built\s+from|"
    r"derived\s+from|drawn\s+from)\b"
    r"|\bwhat\s+did\s+you\s+use\b"
    r"|\bwhat\s+(?:made|led)\s+(?:you|this|that)\b"
    r"|\bwhat\s+makes\s+you\s+(?:say|think|believe)\b"
    r"|\bwhat\s+makes\s+" + _THAT + r"\s+(?:true|reliable|a\s+match|similar|"
    r"suspicious|the\s+strongest)\b"
    r"|\bwhat\s+put\s+" + _THAT + r"\s+at\s+the\s+top\b"
    # 9. "where does this come from" — must beat HOTSPOT's bare "where".
    r"|\bwhere\s+(?:does|did|do)\s+" + _THAT + r"\s+come\s+from\b"
    r"|\bwhere\s+did\s+you\s+get\b"
    # 10. Doubt and limits: the auditor testing the claim rather than reading it.
    r"|\bcould\s+" + _THAT + r"\s+be\s+(?:wrong|a\s+mistake|someone\s+else|"
    r"a\s+different|two\s+different)\b"
    r"|\bcould\s+(?:you|these|those|they)\s+be\s+(?:wrong|a\s+different|two\s+different)\b"
    r"|\bare\s+you\s+(?:sure|certain)\b|\bis\s+that\s+definitely\b"
    r"|\bhow\s+(?:confident|certain|sure|reliable|strong|common)\b"
    r"|\bwhat\s+(?:is|are)\s+the\s+(?:confidence|uncertainty|margin|limitations?|"
    r"caveats?|assumptions?|weakest)\b"
    r"|\bwhat\s+(?:would|could)\s+(?:change|make)\b"
    r"|\bwhat\s+(?:would\s+)?you\s+need\s+to\s+be\s+sure\b"
    r"|\bwhat\s+are\s+you\s+assuming\b|\bwhat\s+assumptions\b"
    r"|\bwhere\s+is\s+(?:this|that)\s+answer\s+weakest\b"
    r"|\bhow\s+could\s+(?:this|that)\s+be\s+challenged\b"
    r"|\bwhat\s+does\s+" + _THAT + r"\s+not\s+(?:mean|establish|prove|show)\b"
    r"|\bwhat\s+can\s+I\s+not\s+conclude\b"
    r"|\bis\s+" + _THAT + r"\s+(?:a\s+|an\s+)?(?:fact|guess|inference|assumption|"
    r"certain|definite|proven|recorded|derived|inferred)\b"
    r"|\bis\s+(?:this|that)\s+your\s+inference\b|\bare\s+you\s+inferring\b"
    r"|\bdid\s+you\s+infer\b|\bwhat\s+did\s+you\s+infer\b"
    r"|\bwhat\s+is\s+inferred\b"
    r"|\bwhat\s+(?:part|parts)\s+of\s+" + _THAT + r"\s+(?:is|are)\b"
    r"|\bwhich\s+parts?\s+(?:is|are|came|were)\b"
    r"|\bwhat\s+(?:does|do)\s+(?:that|this|the)\s+(?:confidence|score|percentage|"
    r"number|probability|figure|density)\b[^?.]{0,24}\bmean\b"
    r"|\bwhat\s+does\s+the\s+score\s+actually\s+measure\b"
    r"|\bwhat\s+(?:did|do)\s+you\s+(?:leave\s+out|exclude)\b"
    r"|\bwhat\s+(?:was|is)\s+excluded\b|\bwhat\s+is\s+missing\b"
    r"|\bis\s+anything\s+missing\b|\banything\s+you\s+are\s+not\s+telling\b"
    # 11. What the model is made of — a question about the method, not the person.
    r"|\bwhat\s+(?:goes|feeds)\s+into\b"
    r"|\bwhat\s+features\b|\bwhat\s+(?:is|are)\s+in\s+the\s+denominator\b"
    r"|\bdoes\s+the\s+(?:model|score|system)\s+use\b"
    r"|\bdo\s+you\s+use\s+any\s+protected\b"
    r"|\bis\s+the\s+(?:risk\s+)?score\s+calibrated\b"
    r"|\bwhy\s+are\s+pending\s+cases\s+excluded\b"
    # 12. Cross-examination openers: "you said X — on what?"
    r"|\byou\s+said\b[^?.]{0,60}?\b(?:on\s+what|which|how|from\s+where|similar\s+how)\b"
    r"|\b(?:double-?check|check\s+that\s+again)\b"
    # 13. The short forms. Anchored to the whole utterance so they cannot fire inside
    #     a real question ("why is crime rising in Kolar" keeps its own meaning).
    r"|^\s*(?:and\s+|but\s+|so\s+)?why\b[\s\w]{0,12}?[?.!]?\s*$"
    r"|^\s*how\s*(?:so|come|exactly)?\s*\??\s*$"
    r"|^\s*(?:based\s+on\s+what|from\s+what|derived\s+how|inferred\s+from\s+what|"
    r"on\s+what\s+grounds|with\s+what\s+support|supported\s+by\s+what)\s*\??\s*$"
    r"|^\s*(?:justify|explain|unpack|elaborate\s+on)\b"
    r"|^\s*break\s+(?:that|this|it)\s+down\b"
    r"|^\s*go\s+on\s*\??\s*$"
    r"|\bwhy\s+(?:should|would)\s+I\s+(?:believe|trust|accept)\b"
    r"|\bwhy\s+do\s+you\s+(?:say|think)\b"
    r"|\bhow\s+can\s+you\s+tell\b"
    r"|\bhow\s+(?:would|do|can)\s+I\s+(?:check|verify|confirm)\b"
    r"|\bcan\s+I\s+verify\b|\bwhere\s+would\s+I\s+look\b"
    r"|\btell\s+me\s+more\s+about\s+how\b"
    r"|\bshow\s+(?:me\s+)?how\s+you\s+(?:got|derived|arrived|decided|worked)\b"
    r"|\bwhat\s+did\s+you\s+do\s+to\s+get\b"
    r"|\bis\s+(?:this|that)\s+from\s+the\s+(?:file|record|records)\s+or\b"
    r"|\bwhat\s+would\s+you\s+need\s+to\s+be\s+sure\b"
    r"|\bwhat\s+are\s+you\s+assuming\b"
    r"|\bwhat\s+does\s+(?:this|that)\s+\w+\s+mean\b"
    r"|\bdoes\s+the\s+(?:risk\s+)?(?:model|score|system|ranking)\s+use\b",
    re.I)

# The audit question aimed at ONE KIND of result. These name the thing being audited
# — a ranking, a count, a similarity, an identity match — and every one of them was
# answered by re-running the very operation being questioned: "Which transactions make
# up that total?" scored FINANCIAL and traced the money again instead of itemising the
# figure already on screen.
_RESULT_AUDIT = re.compile(
    # identity and namesakes — the sharpest cross-examination this system faces,
    # because the identity layer is what makes a "prior" exist at all.
    r"\bwhat\s+if\s+the\s+(?:identity\s+)?match\s+is\s+wrong\b"
    r"|\bwhat\s+if\s+the\s+name\s+is\s+a\s+coincidence\b"
    r"|\bcould\s+two\s+different\s+people\b"
    r"|\bis\s+there\s+a\s+namesake\b"
    r"|\bhave\s+you\s+confused\b"
    r"|\bshow\s+me\s+both\s+names\b"
    r"|\bwhat\s+name\s+(?:is\s+on\s+the\s+file|does\s+the\s+fir\s+use)\b"
    r"|\bis\s+the\s+name\s+you\s+used\b"
    r"|\bwhy\s+do\s+you\s+call\s+(?:him|her|them)\b"
    r"|\bwhere\s+did\s+the\s+canonical\s+name\s+come\s+from\b"
    r"|\bwhat\s+is\s+the\s+difference\s+between\s+the\s+two\s+names\b"
    r"|\bwhich\s+is\s+the\s+recorded\s+spelling\b"
    # contradiction and consistency
    r"|\bis\s+(?:that|this)\s+contradicted\b"
    r"|\bdoes\s+any\s+record\s+contradict\b"
    r"|\bis\s+there\s+anything\s+inconsistent\b"
    r"|\bdo\s+the\s+records\s+disagree\b"
    r"|\bdoes\s+the\s+status\s+match\b"
    r"|\bis\s+the\s+district\s+you\s+named\b"
    r"|\bdid\s+any\s+cited\s+record\s+mention\b"
    r"|\bthat\s+does\s+not\s+sound\s+right\b|\bthat\s+doesn.t\s+sound\s+right\b"
    # rankings and counts
    r"|\bwhat\s+is\s+(?:that|this|the)\s+ranking\s+based\s+on\b"
    r"|\bis\s+the\s+ranking\s+based\s+on\b"
    r"|\bdoes\s+being\s+(?:top|at\s+the\s+top)\s+of\s+(?:that|this|the)\s+list\b"
    r"|\bhow\s+did\s+you\s+count\b"
    r"|\bdoes\s+(?:that|this|the)\s+count\s+include\b"
    r"|\bwould\s+(?:that|this|the)\s+number\s+be\s+different\b"
    r"|\bdoes\s+more\s+recorded\s+crime\s+mean\b"
    # similarity, community, money, flags — "is X the same as Y" is the shape of a
    # question about what a derived label MEANS, not a request to re-derive it.
    r"|\bis\s+(?:a|the)\s+community\s+the\s+same\s+as\b"
    r"|\bwhat\s+makes\s+these\s+cases\s+similar\b"
    r"|\bwhich\s+sections?\s+do\s+they\s+share\b"
    r"|\bwhich\s+cases\s+do\s+they\s+share\b"
    r"|\bon\s+how\s+many\s+cases\b"
    r"|\bhow\s+many\s+steps?\s+apart\b"
    r"|\bis\s+similar\s+wording\s+the\s+same\b"
    r"|\bis\s+one\s+hop\s+the\s+same\b"
    r"|\bdoes\s+co.?accused\s+mean\b"
    r"|\bwhich\s+transactions?\s+make\s+up\b"
    r"|\bwhich\s+direction\s+did\s+the\s+money\s+go\b"
    r"|\bwhat\s+rule\s+flagged\b"
    r"|\bis\s+a\s+flag\s+a\s+finding\b"
    r"|\bhow\s+many\s+incidents?\s+(?:are\s+)?in\s+(?:that|this|the)\s+cluster\b"
    r"|\bis\s+the\s+hotspot\s+a\s+prediction\b"
    r"|\bdoes\s+a\s+hotspot\s+mean\b"
    r"|\bcould\s+the\s+hotspot\s+just\s+be\b"
    r"|\bis\s+the\s+forecast\s+a\s+record\b"
    r"|\bhow\s+far\s+ahead\b"
    r"|\bis\s+the\s+risk\s+score\s+evidence\b"
    r"|\bwhat\s+does\s+(?:a\s+)?(?:risk\s+)?(?:score|probability)\s+of\s+that\s+size\s+mean\b"
    r"|\bwhat\s+makes\s+this\s+area\s+a\s+hotspot\b"
    r"|\byou\s+said\b[^?.]{0,60}?\bfrom\s+what\s+data\b"
    r"|\byou\s+said\b[^?.\u2014-]{0,60}?[\u2014-]?\s*\bis\s+that\s+the\s+recorded\b"
    r"|\bwhat\s+is\s+a\s+network\s+community\b",
    re.I)

# The fields a judge reads off a charge sheet, asked of the case already open. Each is
# a READ of the case in view, so CASE_CONTEXT — which re-fetches that case through the
# same policy-scoped query — is the operation that answers them. They matched nothing
# before and fell to UNKNOWN, which for an offline model means a refusal.
_CASE_FIELD = re.compile(
    r"\bwhat\s+(?:are\s+the\s+facts|is\s+this\s+case\s+about|is\s+alleged)\b"
    # "What do you know about this case?" used to match _CAPABILITY's "what do you"
    # branch and was answered with a description of the tool.
    r"|\bwhat\s+do\s+you\s+know\s+about\s+(?:this|the|it)\b"
    r"|\b(?:describe|read\s+me)\s+the\s+(?:incident|complaint|case|facts)\b"
    r"|\bwhich\s+(?:police\s+station|station)\s+(?:registered|filed|has)\s+this\b"
    r"|\bwhich\s+district\s+is\s+this\s+case\s+in\b"
    r"|\bwhat\s+sections?\s+(?:are|is|was|were)\s+(?:applied|invoked|registered|charged)\b"
    r"|\bunder\s+which\s+sections?\b"
    r"|\bwhat\s+offence\s+is\s+this\b|\bwhat\s+is\s+the\s+(?:crime\s+type|offence)\b"
    r"|\bwhen\s+was\s+(?:the\s+fir|this\s+case|it)\s+(?:filed|registered|lodged)\b"
    r"|\bwhat\s+is\s+the\s+current\s+status\b"
    r"|\bhas\s+a\s+charge\s?sheet\s+been\s+filed\b"
    r"|\bwas\s+anyone\s+(?:convicted|acquitted)\s+in\s+this\s+case\b"
    r"|\bwas\s+there\s+an\s+arrest\b|\bwhen\s+was\s+the\s+arrest\b"
    ,
    re.I)

# The PEOPLE question, in the forms CASE_PEOPLE's keyword list misses. Kept OUT of
# _CASE_FIELD: "name the accused" wants the accused list, not the case summary.
_CASE_PEOPLE_SHAPE = re.compile(
    r"\bname\s+the\s+accused\b|\bwho\s+else\s+was\s+named\b"
    r"|\bhow\s+many\s+accused\b|\blist\s+the\s+accused\b",
    re.I)

# The one thing branch 2 must not swallow: a genuine causal question about the world.
# "Why is this district high in crime" is CAUSAL analysis over socioeconomics; "why is
# this district here" is provenance. The noun after the demonstrative tells them apart.
_WORLD_QUESTION = re.compile(
    r"\bwhy\s+(?:is|are|was|were|does|do)\s+(?:this|that|these|those|the\s+)?\s*"
    + _WORLD_NOUN + r"\b[^?.]{0,40}?\b(?:high|higher|highest|low|lower|rising|"
    r"falling|worse|increas\w+|decreas\w+|more|less|concentrat\w+|caused|"
    r"correlat\w+)\b", re.I)

# --- "what supports that?" — the evidentiary question ----------------------------
#
# The sibling of _EXPLAIN_REASONING and the same rewrite for the same reason: it was
# six phrasings, and a judge asks in fifty. "Show me the evidence" scored CRIME_SEARCH
# on the bare verb "show" and ran a semantic search for the literal words.
#
# The boundary between the two is real and worth keeping: EXPLAIN answers HOW the
# result was reached, EVIDENCE_FOR answers WHICH RECORDS it rests on. Where a phrasing
# genuinely admits both, either is a defensible route and the corpus accepts both.
_EVIDENCE_FOR = re.compile(
    # "what supports this / that / the third event"
    r"\bwhat\s+support\w*\s+(?:this|that|these|those|it|the\s+\w+)\b"
    r"|\bwhat\s+(?:is|are)\s+(?:the\s+)?(?:supporting\s+)?evidence\b"
    r"|\bwhat\s+evidence\b"
    r"|\bevidence\s+for\s+(?:this|that|it)\b"
    r"|\bwhat\s+backs\s+(?:this|that|it)\s+up\b"
    # "show me the evidence / the source / the records behind this" — must beat
    # CRIME_SEARCH's bare "show".
    r"|\bshow\s+(?:me\s+)?(?:the\s+)?(?:evidence|sources?|citations?|"
    r"supporting\s+records?|source\s+records?|underlying\s+records?|"
    r"records?\s+behind\s+(?:this|that|it))\b"
    # "which record / file / case / FIR says this"
    r"|\bwhich\s+(?:record|records|file|files|case|cases|firs?|document|documents)\b"
    r"[^?.]{0,30}\b(?:say|says|said|state|states|show|shows|support|supports|"
    r"come|comes|is|are|did|do|used|read|look)\b"
    r"|\bwhich\s+records?\s+did\s+you\b"
    r"|\bwhat\s+records?\s+did\s+you\b"
    r"|\bhow\s+many\s+(?:records?|cases?)\s+(?:is\s+this\s+based\s+on|support|back)\b"
    # "what is the source for this" / bare "source?" / "citation?"
    r"|\bwhat\s+(?:is|was)\s+the\s+source\b"
    r"|\bsource\s+for\s+(?:this|that|it)\b"
    r"|\bbasis\s+for\s+(?:this|that|it)\b"
    r"|^\s*(?:source|evidence|citation|reference|proof)\s*\??\s*$"
    r"|^\s*(?:says\s+who|according\s+to\s+what|on\s+what\s+evidence|which\s+record|"
    r"which\s+file|which\s+case|what\s+source)\s*\??\s*$"
    # "how do you know" — the oldest form of the question.
    r"|\bhow\s+do\s+you\s+know\b"
    # "prove it", "substantiate that", "back it up", "cite your source"
    r"|\bprove\s+(?:this|that|it)\b|\bcan\s+you\s+prove\b"
    r"|\bsubstantiate\b|\bback\s+(?:it|that|this)\s+up\b"
    r"|\bcite\s+(?:your|the)\b|\bgive\s+me\s+the\s+citation\b"
    r"|\bwhat\s+did\s+you\s+cite\b|\bwhat\s+are\s+the\s+citations\b"
    # "where is that written / recorded", "is that in the file"
    r"|\bwhere\s+is\s+(?:that|this|it)\s+(?:written|recorded|stated)\b"
    r"|\bis\s+(?:that|this)\s+(?:written|recorded|stated)\s+anywhere\b"
    r"|\bis\s+(?:that|this)\s+in\s+the\s+(?:file|record|fir)\b"
    r"|\bis\s+(?:that|this)\s+stated\s+in\s+the\b"
    r"|\bdoes\s+(?:any|the)\s+record\s+(?:actually\s+)?say\b"
    # "point to the record", "which sentence is supported"
    r"|\bpoint\s+to\s+the\s+record\b"
    r"|\bwhich\s+sentence\s+is\s+supported\b"
    r"|\bsay\s+that\s+again\s+with\s+the\s+sources\b"
    r"|\bwhich\s+part\s+of\s+that\s+is\s+from\s+the\s+file\b",
    re.I)

_CASE_LOCATIONS = re.compile(
    r"\bwhere (are|were) (those|these|they)\b|\bwhich districts?\b.*\b(those|these|they)\b"
    r"|\bgeographically concentrated\b"
    # "Where are the related cases?" — a backreference to the set just shown, not a
    # fresh geographic search, and it used to score HOTSPOT on the bare word "where"
    # and run cluster detection over a defaulted district instead. The adjective is
    # what makes it a backreference: "where are the THEFT cases" is a real search and
    # must stay one, so only the referring adjectives are matched here.
    r"|\bwhere (are|were) (the |all the )?(related|similar|matching|other|remaining|"
    r"rest of the)\s+(cases?|firs?|records?|ones)\b",
    re.I)

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
    # The verb is optional here: "back to that case" is how it is actually typed, and
    # requiring "go"/"return" in front left the shortest form matching nothing at all.
    r"|\b(?:(?:go|switch|return|come|head)\s+)?back\s+to\s+(that|this|the\s+other)\s+case\b"
    r"|\bthe\s+case\s+(we|i|you)\s+(started|began|opened)(\s+with)?\b",
    re.I)

# Cross-entity timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 3) — checked as a
# shape, not a keyword-scored topic, for the same reason CASE_LOCATIONS/EXPLAIN_
# REASONING are: "what happened before this incident" and "what happened around
# the time he was involved" both contain "what happened", which would otherwise
# tie CASE_CONTEXT's own "what happened" keyword and lose on dict-order tie-break.
_TIMELINE = re.compile(
    # "around the SAME time" is the phrasing people use, and only "around the time"
    # matched — so CASE_CONTEXT's "what happened" keyword took the whole question.
    r"\btimelines?\b|\bchronology\b|\bsequence of events\b|\baround the (?:same )?time\b"
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

# --- the two question classes that had no home at all --------------------------
#
# Both were measured live falling into CRIME_SEARCH, which answered them with a count
# of every case in scope plus five arbitrary FIRs, cited and confident:
#
#   "Who is the most active offender in Mandya?"   -> 5 unrelated burglary narratives
#   "Give me the top 5 habitual offenders"         -> "10000 cases within your scope"
#   "Which police station has the most pending?"   -> the same 10000
#   "What is the conviction rate in Mandya?"       -> 263 (every Mandya case)
#
# These are the first questions an officer asks, and each is answerable from the
# records. Matched as SHAPES — a ranking word plus the thing being ranked — rather
# than by enumerating phrasings, the same discipline the people-question and
# explanation patterns above already follow.

# "Has he been convicted?" — the person-scoped reading of a word that is otherwise a
# case STATUS. The subject is what makes it one: a pronoun, a demonstrative person, or
# a named individual. Without that, "convicted" describes cases, and the query is a
# filtered search (see the PERSON_HISTORY keyword list's own note).
_ALIAS_CONTEXT = re.compile(
    r"\b(?:different|another|other|second|alternate)\s+(?:name|spelling|identity)\b"
    r"|\balias(?:es)?\b|\bsame person\b|\bduplicate\b", re.I)
_PERSON_CONVICTION = re.compile(
    r"\b(?:has|have|had|was|were|is|are)\s+(?:he|she|they|him|her|them|this person|"
    r"that person|this individual|the accused|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+"
    r"(?:ever\s+)?(?:been\s+)?(?:convicted|acquitted|arrested|charge ?sheeted)\b"
    r"|\b(?:his|her|their)\s+(?:convictions?|acquittals?|arrests?)\b",
    re.I)

# A bare "<offence> in <district>" — the most compressed real query there is, and the
# one that matched nothing at all. CRIME_SEARCH's keyword list carries three offence
# names out of twenty ("theft", "murder", "robbery"), so "Hurt in Ballari", "Riot in
# Chikkamagaluru" and "House Burglary in Belagavi" scored zero and fell to UNKNOWN —
# 44 of the officer-input corpus's 1,115 entries. Naming an offence or a district IS
# a search; it does not need a verb in front of it.
#
# A CORRECTION also names a district ("no, I meant Mysuru", "actually Bengaluru") and
# is emphatically not a fresh search: it edits the previous request, and the semantic
# interpreter owns that. Reading it as a search here re-ran the whole query against
# the corrected district while discarding every other constraint the officer had
# already set. Excluded by shape, not by keyword.
_CORRECTION_SHAPE = re.compile(
    r"^\s*(?:no|nope|nah)\b|^\s*not\b|\bi\s+meant\b|\bi\s+said\b|^\s*actually\b"
    r"|^\s*sorry\b|\brather than\b|\binstead of\b", re.I)


def _names_scope(query: str) -> bool:
    if _CORRECTION_SHAPE.search(query or ""):
        return False
    from .semantic_interpreter import crime_type_from_query
    if crime_type_from_query(query):
        return True
    from data.districts import canonical_code
    from data.nlp import ner_extract
    return any(canonical_code(e.text) for e in ner_extract(query or "", "en")
               if e.label == "LOCATION")


# A ranking over PEOPLE. The offender word is what separates it from a ranking over
# cases ("which district has the most cases"), which is CASE_STATS below.
# "Criminal Breach of Trust" and "Criminal Intimidation" are OFFENCE names that begin
# with the word "criminal", so a bare `criminals?` made "which areas have the most
# Criminal Breach of Trust" a ranking over people. The plural is unambiguous; the
# singular is admitted only when it is not the start of one of those fixed legal
# phrases.
_OFFENDER_WORD = (r"(?:offenders?|criminals|criminal(?!\s+(?:breach|intimidation|"
                  r"damage|conspiracy|trespass|force|misappropriation))|accused|"
                  r"suspects?|persons?|people)")
_OFFENDER_RANKING = re.compile(
    # A genuine RANKING word plus the thing being ranked.
    r"\b(?:most|top|worst|biggest|main|leading|prolific|frequent|active)\b"
    r"[^?.]{0,40}?\b" + _OFFENDER_WORD + r"\b"
    # "repeat"/"habitual"/"chronic" are ATTRIBUTES, not rankings, so they only make a
    # ranking in the PLURAL. "Has this individual been flagged as a repeat offender?"
    # asks whether ONE named person carries the attribute — a question about him, not
    # a list — and matching it here answered it with a leaderboard.
    r"|\b(?:repeat|habitual|chronic)\s+(?:offenders|criminals)\b"
    r"|\b" + _OFFENDER_WORD + r"\b[^?.]{0,30}?\b(?:with the most|most cases|"
    r"ranked|most active|most wanted)\b"
    r"|\bwho\b[^?.]{0,30}?\bhas the most\b[^?.]{0,20}?\b(?:cases|firs?|records?)\b"
    r"|\bmost wanted\b",
    re.I)

# A statistic ABOUT the case set: a rate, a breakdown, or a ranking over places or
# offence types. Deliberately does NOT match "how many cases are pending in Mandya" —
# that is a filtered COUNT, which CRIME_SEARCH now answers correctly and better,
# because it returns the matching cases alongside the number.
_CASE_STATS = re.compile(
    r"\b(?:conviction|acquittal|clearance|disposal|pendency|detection|solve)\s*"
    r"(?:rate|ratio|percentage|percent)\b"
    r"|\brate of (?:conviction|acquittal|detection)\b"
    r"|\bwhich\s+(?:district|districts|police\s+station|station|stations|taluk)\b"
    r"[^?.]{0,40}\b(?:most|highest|top|worst|maximum|largest|fewest|lowest)\b"
    r"|\b(?:most|highest|top|worst|maximum|largest)\b[^?.]{0,30}\b"
    r"(?:district|districts|police\s+station|stations?)\b"
    r"|\b(?:most|commonest)\s+common\b[^?.]{0,30}\b(?:crimes?|offences?|offenses?|"
    r"cases?|sections?|types?)\b"
    r"|\bbreak\s*down\b[^?.]{0,30}\b(?:status|outcome|district|crime|station)\b"
    r"|\b(?:status|outcome)\s+(?:breakdown|split|distribution|summary)\b"
    r"|\bhow are (?:the )?cases (?:split|distributed|broken down)\b",
    re.I)

# Checked as shapes (like OFFENDER_RANKING/CASE_STATS above) rather than added as plain
# keywords, because each one collides with an existing bare word — "area profile" with
# HOTSPOT's "area", "this community" with PERSON_NETWORK's "network", "flagged
# transactions" with FINANCIAL's "transactions" — and a keyword-score tie is decided by
# dict registration order, which is a much easier property to break by accident later
# than a phrase these three never say at all.
_AREA_PROFILE_SHAPE = re.compile(
    r"\b(?:area|district)\s+profile\b|\bprofile\s+of\s+(?:the\s+)?(?:district|area)\b"
    r"|\bdistrict\s+overview\b|\bsocioeconomic\s+profile\b"
    r"|\btell\s+me\s+about\s+(?:this\s+)?district\b", re.I)

_COMMUNITY_PROFILE_SHAPE = re.compile(
    r"\bcommunity\s+#?\d+\b"
    r"|\bwho(?:'s|\s+is)\s+in\s+(?:this\s+)?(?:community|crew)\b"
    r"|\bmembers?\s+of\s+(?:this\s+)?community\b"
    r"|\bthis\s+(?:network\s+)?community\b", re.I)

# The trailing number, extracted separately from the routing shape above: "who is in
# community 0" matches THAT shape's own "who is in ... community" alternative first
# (re.search takes the leftmost successful alternative, and "who is in" starts earlier
# in the string than the bare "community 0" the number lives in), which never
# populates a capture group from a different alternative — so a single combined regex
# silently dropped the number on exactly this phrasing. A second, independent regex
# means the number is found regardless of which alternative above matched.
_COMMUNITY_ID_RE = re.compile(r"\bcommunity\s+#?(\d+)\b", re.I)

_WATCHLIST_SHAPE = re.compile(
    r"\bwatchlist\b|\bflagged\s+(?:transactions?|accounts?)\b"
    r"|\bsuspicious\s+transactions?\s+(?:across|statewide|in the state)\b"
    r"|\bstructuring\s+alerts?\b|\baml\s+(?:alerts?|watchlist)\b", re.I)

def community_id_from_query(query: str) -> Optional[int]:
    """The community number a COMMUNITY_PROFILE question names, if it names one at
    all ('this community'/'who is in this community' resolve against session focus
    instead — the orchestrator's job, not this module's)."""
    m = _COMMUNITY_ID_RE.search(query or "")
    return int(m.group(1)) if m else None


_WORKLOAD_SHAPE = re.compile(
    r"\bstation\s+workload\b|\bworkload\s+by\s+station\b|\bfalling\s+behind\b"
    r"|\bstalled\s+cases?\b|\bcases?\s+(?:going|gone)\s+cold\b|\bbacklog\b"
    r"|\buntouched\s+cases?\b|\bwhich\s+stations?\s+need", re.I)


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


# A record identifier: the 18-digit CrimeNo the generator writes and the case index
# renders, or the short "0112/2026" form. Floored at 12 digits so "the last 30 days"
# and "2026" can never be read as one. Lives here rather than in orchestrator.py
# (which imports it from here) because classify() below needs the same fact: whether
# this query names a record at all is part of what the question IS, not just how it
# is later answered.
FIR_NUMBER_RE = re.compile(r"\b(\d{3,4}/\d{4}|\d{12,20})\b")


# --- "name the people", in the words an officer actually uses -------------------
#
# CASE_PEOPLE's keyword list spells out a handful of phrasings ("who is involved",
# "people involved"). Real questions use the same SHAPE with different words, and
# each near-miss landed somewhere plausible and wrong — measured against the live
# deployment, not guessed:
#
#   "show everyone involved"        -> CRIME_SEARCH  ("show" is a CRIME_SEARCH verb)
#   "Who is connected?"             -> CASE_CONTEXT  (nothing matched; fell through)
#   "Anyone connected to this case?"-> CASE_CONTEXT
#
# All three ask one thing: name the people in the case in front of me. That is a
# question SHAPE — a who-word plus an involvement word — so it is matched here,
# alongside the other shape patterns, rather than by widening a keyword list one
# phrasing at a time.
#
# The exclusion is what keeps it honest: "who are the associates of Usha Naika" and
# "who is connected to Ramesh" name a SUBJECT, and belong to PERSON_NETWORK, not to
# the open case. A capitalised word after of/to/with is that subject, so those are
# routed to PERSON_NETWORK instead. Deliberately case-SENSITIVE: it is the capital
# letter that distinguishes a name from "to this case".
_PEOPLE_WORD = re.compile(
    r"\b(who|whom|everyone|everybody|anyone|anybody|people|persons?)\b", re.I)
_INVOLVEMENT = re.compile(
    r"\b(involved|involve|connected|linked|implicated|named in (this|it))\b", re.I)
# A capitalised name OR a third-person pronoun. "Who is she connected to?" names a
# subject as surely as "who is connected to Usha Naika" does — the population is that
# person's network, not the open case's accused list.
_NAMED_SUBJECT = re.compile(
    r"\b(?:of|to|with|around|near)\s+[A-Z][a-z]"
    r"|(?i:\b(?:of|to|with|around|near)\s+(?:him|her|them|he|she)\b)"
    r"|(?i:\bwho\s+(?:is|are|was|were)\s+(?:he|she|they|him|her|them)\b)"
    r"|(?i:\bwho\s+(?:has|have|had)\s+(?:he|she|they)\b)")

# "Who does she run with?", "who he hangs around with", "who does Ramesh work with"
# — the co-offending question, asked the way it is asked out loud. PERSON_NETWORK's
# keywords are all nouns ("associate", "network", "gang"), so a question built out
# of a verb matched none of them; measured live, "Who does she run with?" answered
# as NEXT_STEPS.
_RUNS_WITH = re.compile(
    r"\bwho\b[^?.]*\b(runs?|ran|works?|hangs?|goes|go|knocks?|moves?|deals?|"
    r"offend\w*|operate[sd]?)\b"
    r"\s*(?:around|about)?\s*\bwith\b", re.I)


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
    # Checked BEFORE _EXPLAIN_REASONING: "why are these events connected" and "how
    # are these connected" are requests for the two-entity timeline — a real
    # retrieval — and _EXPLAIN_REASONING's widened claim-level vocabulary now
    # overlaps both. The narrower, older pattern owns the phrasing it was built for;
    # everything it does not match falls through to the explanation branch below.
    if _TIMELINE_CONNECTION.search(query or ""):
        return "TIMELINE_CONNECTION"
    # The explanation branch is broad by design, so the one thing it must not swallow
    # is handed back first: "why is crime higher in this district" is causal analysis
    # over socioeconomics, not a request to explain the answer on screen.
    if (_EXPLAIN_REASONING.search(query or "")
            and not _WORLD_QUESTION.search(query or "")):
        return "EXPLAIN_REASONING"
    # Audit questions aimed at one KIND of result. Checked here — after the general
    # explanation shapes, before every topical keyword — because each one names the
    # operation it is questioning, and scoring on that name re-runs the operation
    # instead of explaining it.
    if _RESULT_AUDIT.search(query or ""):
        return "EXPLAIN_REASONING"
    if _EVIDENCE_FOR.search(query or ""):
        return "EVIDENCE_FOR"
    if _CASE_LOCATIONS.search(query or ""):
        return "CASE_LOCATIONS"
    if _CASE_REFERENCE_UNSUPPORTED.search(query or ""):
        return "CASE_REFERENCE_UNSUPPORTED"
    if _BOARD_PIN_EVENT.search(query or ""):
        return "BOARD_PIN_EVIDENCE"
    if _TIMELINE.search(query or ""):
        return "TIMELINE"
    # Both checked before keyword scoring, and OFFENDER_RANKING before CASE_STATS: a
    # ranking over PEOPLE and a ranking over PLACES share their superlative, and the
    # offender word is what tells them apart. "Top offenders in Mandya" names a
    # district and is still a question about people.
    # "Has he been arrested under a different name?" is an ALIAS question that happens
    # to be phrased as a conviction question, and the alias vocabulary is what says so.
    # Checked here rather than by narrowing the pattern: "arrested" genuinely belongs
    # to both readings, and which one applies depends on the rest of the sentence.
    # A field read off the case in view. Before the person shapes: "was there an
    # arrest" is about THIS case, not about somebody's record.
    if _CASE_PEOPLE_SHAPE.search(query or ""):
        return "CASE_PEOPLE"
    if _CASE_FIELD.search(query or ""):
        return "CASE_CONTEXT"
    if _PERSON_CONVICTION.search(query or "") and not _ALIAS_CONTEXT.search(query or ""):
        return "PERSON_HISTORY"
    if _WATCHLIST_SHAPE.search(query or ""):
        return "WATCHLIST"
    if _WORKLOAD_SHAPE.search(query or ""):
        return "STATION_WORKLOAD"
    if _COMMUNITY_PROFILE_SHAPE.search(query or ""):
        return "COMMUNITY_PROFILE"
    if _AREA_PROFILE_SHAPE.search(query or ""):
        return "AREA_PROFILE"
    if _OFFENDER_RANKING.search(query or ""):
        return "OFFENDER_RANKING"
    if _CASE_STATS.search(query or ""):
        return "CASE_STATS"
    if _RUNS_WITH.search(query or ""):
        return "PERSON_NETWORK"
    # Checked AFTER the timeline patterns on purpose: "why are these events
    # connected" is a two-entity timeline question and carries an involvement word
    # of its own.
    if _PEOPLE_WORD.search(query or "") and _INVOLVEMENT.search(query or ""):
        # Same shape, two questions, and the difference is whether a SUBJECT is
        # named. "who is connected?" means the open case; "who is connected to
        # Usha Naika?" means her network. Routing both to the case would answer
        # about the wrong population, and refusing the second would be worse.
        return "PERSON_NETWORK" if _NAMED_SUBJECT.search(query or "") else "CASE_PEOPLE"
    scores: dict[str, int] = {}
    for intent, (keywords, _) in INTENTS.items():
        hits = sum(1 for k in keywords if _KEYWORD_RE[k].search(q))
        if hits:
            scores[intent] = hits

    # FIR_LOOKUP is not a topic, it is "fetch the one record with this identifier" —
    # so a query that names no identifier cannot be one, however often it says "FIR".
    # Found live: "ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?" ("is there another FIR
    # related to that case?") scored FIR_LOOKUP on the bare word "FIR", and the
    # orchestrator's FIR_LOOKUP branch is guarded by the same regex — so it matched
    # nothing, produced no evidence, set no exact_lookup_missed flag, and dropped the
    # turn through to the unscoped semantic search at the bottom of _run_specialists,
    # which answered a case-scoped question with confidently-cited cases from other
    # districts. Removing it from scoring here lets the query reach the operation it
    # actually is, rather than widening a keyword list to cover one more phrasing.
    has_identifier = bool(FIR_NUMBER_RE.search(query or ""))
    if not has_identifier:
        scores.pop("FIR_LOOKUP", None)

    # CRIME_SEARCH is scored last, because its keywords are not topic words — "show",
    # "list", "find", "cases" are the verbs almost every question in this domain uses.
    # Counting them alongside specific ones let a generic pair outvote a precise single:
    # "Find cases similar to FIR 100222201202600022" scored CRIME_SEARCH 2 ("find",
    # "cases") against SIMILAR_CASES 1 ("similar") and was answered with five unrelated
    # criminal profiles. It is the fallback intent, so it behaves like one.
    specific = {i: n for i, n in scores.items() if i != "CRIME_SEARCH"}
    if specific:
        return max(specific, key=lambda i: (specific[i], -list(INTENTS).index(i)))
    # The converse of the rule above: an officer who pastes a bare record identifier
    # with no verb around it ("100010101202300001", "0112/2026 status") is asking for
    # that record. Nothing else in this table can mean anything by a record number.
    if has_identifier:
        return "FIR_LOOKUP"
    if not scores:
        # Nothing matched a keyword — but naming an offence or a district IS a search,
        # and "Hurt in Ballari" is the shortest way an officer asks for one. Checked
        # last, so it can never outrank a question that matched something specific,
        # and it stays UNKNOWN (deferring to the semantic tier) for anything that
        # names neither.
        return "CRIME_SEARCH" if _names_scope(query or "") else "UNKNOWN"
    return "CRIME_SEARCH"


# Not in INTENTS: these are matched by regex before keyword scoring runs (see
# classify()), so they carry no keyword tuple to read a visualization kind from.
_EXTRA_VISUALIZATION = {"CASE_LOCATIONS": "map", "TIMELINE": "timeline",
                        "TIMELINE_CONNECTION": "timeline",
                        # A ranking over people IS a network question once the
                        # names are on screen; a ranking over districts is not a
                        # map until someone asks where.
                        "OFFENDER_RANKING": "none", "CASE_STATS": "none",
                        "AREA_PROFILE": "none", "COMMUNITY_PROFILE": "none",
                        "WATCHLIST": "none", "STATION_WORKLOAD": "none"}

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
    "OFFENDER_RANKING", "CASE_STATS",
    "AREA_PROFILE", "COMMUNITY_PROFILE", "WATCHLIST", "STATION_WORKLOAD",
    "RESULT_SET_FOLLOWUP", "UNKNOWN",
}


def visualization_for(intent: str) -> str:
    if intent in _EXTRA_VISUALIZATION:
        return _EXTRA_VISUALIZATION[intent]
    return INTENTS.get(intent, ((), "none"))[1]


# The questions a magistrate puts to a machine before letting it near a case file.
# Each is answered by ITS OWN paragraph rather than by a general capability blurb: a
# judge asking "do you decide guilt" and being handed a feature list has been answered
# in form and not in substance, and that is the shape of an evasion.
#
# Routing these to CAPABILITY was half the fix (they used to reach UNKNOWN, or a
# retrieval that put five cited crime records under "is this biased?"). Answering them
# specifically is the other half.
_STANDING_ANSWERS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bguilt|\bconvict|\barrest\b|\bwho\s+would\s+you\b", re.I),
     "No. I do not decide guilt, name suspects, convict, or make arrests, and I am "
     "not built to. I report what the records state and what can be derived from "
     "them; every inference is labelled as one. Naming who is likely responsible is "
     "the one thing I refuse outright, because the records hold who was accused, "
     "arrested and charged — never who could be guilty."),
    (re.compile(r"\bwitness\b|\bevidence\b|\bin\s+court\b|\badmissib", re.I),
     "I am not a witness and my output is not evidence. What I produce is a pointer "
     "to records: every claim carries the FIR it came from, and those records — not "
     "my summary of them — are what a court would look at. Treat this as an index "
     "and a working note, and verify each cited record before relying on it."),
    (re.compile(r"\brely\s+on\s+(?:this|it)\s+alone|\bact\s+on\s+(?:this|it)\s+by\s+itself"
                r"|\breplace\b|\bhuman\b|\bautomat", re.I),
     "No. Everything here is decision support for a human investigator, and nothing "
     "acts on its own — no output of mine triggers any action. Do not act on an "
     "answer without opening the records it cites; where I have inferred something, "
     "the inference is mine and the responsibility for acting on it is yours."),
    (re.compile(r"\bbias|\bprofil|\bpredictive\s+policing|\bover.?police|\btarget\b", re.I),
     "Recorded crime reflects where policing happened as well as where crime "
     "happened, and I cannot separate the two — so any count, hotspot or ranking I "
     "produce describes the RECORD, not the world. No caste, religion or other "
     "protected attribute is used as a feature by any model here; those columns exist "
     "in the schema and no model reads them. Fairness is audited across demographic "
     "AND geographic subgroups, because geography is the axis an over-policing "
     "feedback loop actually travels along."),
    (re.compile(r"\bguess\b|\bmake\s+things\s+up|\bhallucinat|\bdo\s+not\s+know"
                r"|\bdon.t\s+know|\brecords\s+do\s+not\s+support", re.I),
     "When the records do not support an answer I say so and stop. I do not fill a "
     "gap with a plausible sentence: an answer with no supporting record is reported "
     "as a refusal, with the reason, rather than as a low-confidence finding."),
    (re.compile(r"\blogged\b|\baudit\b|\breproduc|\baccountab|\bwho\s+can\s+see", re.I),
     "Every answered request is written to a tamper-evident audit log — each entry "
     "carries the hash of the entry before it, so altering or removing one breaks "
     "every entry after it. Your queries are part of that record. The same question "
     "asked again returns the same answer unless the records themselves changed."),
    (re.compile(r"\ballowed\s+to\s+see|\baccess\s+scope|\bsenior\b|\bpresumed\s+innocent"
                r"|\bfair\s+to\s+the\s+accused|\baccusation\s+mean|\bimply\s+guilt", re.I),
     "Being named in these records means somebody was ACCUSED, which is not a finding "
     "that they did anything — accused, chargesheeted, convicted and acquitted are "
     "distinct statuses and I never collapse them. What I can show you is bounded by "
     "your rank and station: a more senior officer would see more cases, so a count I "
     "give you is a count within your own scope, not a count of everything."),
    (re.compile(r"\bwhat\s+data|\bwhat\s+records|\bdata\s+come\s+from|\bhow\s+(?:much|many)\s+data"
                r"|\bhow\s+current", re.I),
     "I read the FIR records held in this system — the case register, the people "
     "named on those cases, the accounts and transfers recorded against them, and the "
     "district reference data. I hold nothing else: no external database, no news, no "
     "internet. Everything I answer with is in those records or derived from them."),
)


def capability_answer(query: str = "") -> str:
    """What this engine can actually answer — and, where the question is about the
    engine's STANDING rather than its features, a direct answer to that instead.

    Deliberately not a chat feature: no retrieval, no citations, because there is
    nothing to cite. It is scoped to what the INTENTS table above actually implements,
    and it states the limits in the same breath as the capabilities, since a capability
    list that omits them is a sales pitch.
    """
    for pattern, answer in _STANDING_ANSWERS:
        if pattern.search(query or ""):
            return answer
    return (
        "I answer questions against the FIR records held in this system, and I cite "
        "the record behind every claim. I can look up a case by its FIR number; give "
        "a named person's prior cases, known associates and recorded aliases; trace "
        "money between accounts; map crime hotspots and forecast case volume for a "
        "district; score risk and recidivism; rank offenders by how many cases name "
        "them; report case statistics; and find cases similar to one you name. Every "
        "result can be asked WHY, and I will answer with the records and the "
        "derivation behind it. I answer in English or Kannada.\n\n"
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
