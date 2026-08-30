"""A corpus of the things a Karnataka police officer actually types.

## Why this exists

Six questions typed by hand against the live engine found that an entire class of
ordinary requests — "who is the most active offender in Mandya", "how many cases are
pending", "show me cases under section 379", "what is the conviction rate" — was being
answered with a count of every case in the state plus five arbitrary FIRs, cited and
confident. None of the 670 tests in this repo caught it, because every one of them
tested a phrasing somebody had already thought of.

So this is a corpus, not a test list: ~1,000 inputs generated from real templates
crossed with the dataset's own districts, offence types, sections and stations, plus a
curated set of the awkward, adversarial and multilingual things people type. It is
checked with PROPERTIES rather than expected answers — an expected answer is a
snapshot, and a snapshot passes for the wrong reason the moment the data changes.

## What "acceptable" means here

Each entry names the operations that would be a DEFENSIBLE reading of the input, not
one right answer. Real questions are ambiguous — "show me theft in Mandya" is honestly
either a search or a map — and a corpus that insists on one reading tests the
classifier's habits rather than its correctness. `UNKNOWN` is acceptable wherever
deferring to the semantic tier is the honest outcome; it is NOT acceptable where a
deterministic reading exists, because falling through to a model that may be
unreachable is how an ordinary question becomes a refusal.

The generated half keeps the corpus honest about scale; the curated half keeps it
honest about difficulty. Both are checked by tests/test_officer_input_battery.py.
"""
from __future__ import annotations

# (query, acceptable operations). A frozenset so a reader sees immediately that
# several readings are allowed on purpose.
Entry = tuple[str, frozenset]


def _ops(*names: str) -> frozenset:
    return frozenset(names)


# The vocabulary the corpus is built from — read from the dataset's own reference data
# rather than invented, so a template can never generate a district or an offence this
# system has never heard of.
def _vocab() -> tuple[list[str], list[str]]:
    from data.districts import all_districts
    from data.generator.refdata import crime_type_names
    return [d.name for d in all_districts()], list(crime_type_names())


# --------------------------------------------------------------------------- #
# generated: the same question, asked about everything                         #
# --------------------------------------------------------------------------- #

_SEARCH_TEMPLATES = (
    "How many {crime} cases in {district}?",
    "how many {crime} cases are there in {district}",
    "Show me {crime} cases in {district}.",
    "list the {crime} cases in {district}",
    "{crime} in {district}",
    "Find all {crime} cases registered in {district}",
    "I need the {crime} cases for {district}",
    "pull up {crime} cases in {district}",
)

_STATUS_TEMPLATES = (
    "How many {crime} cases are pending in {district}?",
    "Show me convicted {crime} cases in {district}",
    "how many {crime} cases were acquitted in {district}",
    "chargesheeted {crime} cases in {district}",
    "which {crime} cases in {district} are still under investigation",
)

_HOTSPOT_TEMPLATES = (
    "Show me {crime} hotspots in {district}.",
    "where are the {crime} hotspots in {district}",
    "crime map for {district}",
    "Which areas in {district} have the most {crime}?",
)

_FORECAST_TEMPLATES = (
    "Forecast {crime} in {district}",
    "what is the crime trend in {district}",
    "how many cases do you expect in {district} next month",
)

_RANKING_TEMPLATES = (
    "Who is the most active offender in {district}?",
    "top 5 offenders in {district}",
    "give me the repeat offenders in {district}",
    "most prolific {crime} offenders in {district}",
    "who are the habitual offenders in {district}",
)

_STATS_TEMPLATES = (
    "What is the conviction rate in {district}?",
    "which police station in {district} has the most cases",
    "most common crime in {district}",
    "break down the cases in {district} by status",
)


def _generated() -> list[Entry]:
    districts, crimes = _vocab()
    out: list[Entry] = []
    # Cross every district with a rotating offence, so the corpus covers all 31
    # districts and all 20 offence types without being 31x20 of each template.
    for i, district in enumerate(districts):
        crime = crimes[i % len(crimes)]
        def fill(t: str) -> str:
            return t.format(crime=crime, district=district)
        # A search may honestly read as a map when it says "where", and a count is a
        # search; both are accepted where the phrasing genuinely allows it.
        for t in _SEARCH_TEMPLATES:
            out.append((fill(t), _ops("CRIME_SEARCH")))
        for t in _STATUS_TEMPLATES:
            out.append((fill(t), _ops("CRIME_SEARCH", "CASE_STATS")))
        for t in _HOTSPOT_TEMPLATES:
            out.append((fill(t), _ops("HOTSPOT", "CASE_STATS")))
        for t in _FORECAST_TEMPLATES:
            out.append((fill(t), _ops("FORECAST", "CRIME_SEARCH")))
        for t in _RANKING_TEMPLATES:
            out.append((fill(t), _ops("OFFENDER_RANKING")))
        for t in _STATS_TEMPLATES:
            out.append((fill(t), _ops("CASE_STATS", "CRIME_SEARCH")))
    # Offence types the district loop did not reach, asked plainly.
    for crime in crimes:
        out.append((f"How many {crime} cases are there?", _ops("CRIME_SEARCH")))
        out.append((f"Show me {crime} cases", _ops("CRIME_SEARCH")))
    # Sections, stations and dates — the three qualifiers that used to be dropped in
    # silence, so the corpus over-samples them deliberately.
    for section in ("379", "380", "302", "420", "406", "323", "324", "354", "457",
                    "392", "394", "66C", "66D", "304A", "409", "279", "337", "326"):
        out.append((f"Show me cases under section {section}", _ops("CRIME_SEARCH")))
        out.append((f"cases u/s {section}", _ops("CRIME_SEARCH")))
        out.append((f"IPC {section} cases in Mandya", _ops("CRIME_SEARCH")))
    for ps in ("2201", "2202", "501", "1201", "2301"):
        out.append((f"Show me all cases from PS {ps}", _ops("CRIME_SEARCH")))
        out.append((f"cases at police station {ps}", _ops("CRIME_SEARCH")))
    for month in ("January", "March", "June", "September", "December"):
        for year in ("2024", "2025", "2026"):
            out.append((f"cases filed in {month} {year}", _ops("CRIME_SEARCH")))
    for year in ("2023", "2024", "2025", "2026"):
        out.append((f"how many cases in {year}", _ops("CRIME_SEARCH")))
    return out


# --------------------------------------------------------------------------- #
# curated: the awkward half                                                    #
# --------------------------------------------------------------------------- #

_PERSON = (
    ("Does Usha Naika have priors?", _ops("PERSON_HISTORY")),
    ("does he have priors", _ops("PERSON_HISTORY")),
    ("has she been arrested before", _ops("PERSON_HISTORY")),
    ("what is her rap sheet", _ops("PERSON_HISTORY")),
    ("previous cases against Ramesh Gowda", _ops("PERSON_HISTORY")),
    ("Is this person known to us?", _ops("PERSON_HISTORY", "UNKNOWN")),
    ("Who are the associates of Usha Naika?", _ops("PERSON_NETWORK")),
    ("who does she run with", _ops("PERSON_NETWORK")),
    ("who does he hang around with", _ops("PERSON_NETWORK")),
    ("show me his co-accused", _ops("PERSON_NETWORK")),
    ("who is she connected to", _ops("PERSON_NETWORK", "CASE_PEOPLE")),
    ("Is Usha Naika recorded under another name?", _ops("ALIAS_CHECK")),
    ("any alias for this person", _ops("ALIAS_CHECK")),
    ("is this the same person as the one in the other case", _ops("ALIAS_CHECK")),
    ("Where did her money go?", _ops("FINANCIAL")),
    ("trace the money", _ops("FINANCIAL")),
    ("show me the bank transfers", _ops("FINANCIAL")),
    ("any suspicious transactions", _ops("FINANCIAL")),
    ("How likely is he to reoffend?", _ops("RISK")),
    ("what is her risk score", _ops("RISK")),
)

_CASE_SCOPED = (
    ("What happened in this case?", _ops("CASE_CONTEXT")),
    ("brief facts", _ops("CASE_CONTEXT")),
    ("summarise this case", _ops("CASE_CONTEXT")),
    ("Who are all involved?", _ops("CASE_PEOPLE")),
    ("show everyone involved", _ops("CASE_PEOPLE")),
    ("anyone connected to this case", _ops("CASE_PEOPLE")),
    ("who are the accused", _ops("CASE_PEOPLE")),
    ("What should I investigate next?", _ops("NEXT_STEPS")),
    ("what should I focus on", _ops("NEXT_STEPS")),
    ("prepare the briefing", _ops("BRIEFING")),
    ("draft the case diary", _ops("BRIEFING", "CRIME_SEARCH")),
    ("Find similar cases.", _ops("SIMILAR_CASES")),
    ("any comparable cases", _ops("SIMILAR_CASES")),
    ("same modus operandi cases", _ops("SIMILAR_CASES")),
    ("Show me the timeline.", _ops("TIMELINE")),
    ("what happened before this", _ops("TIMELINE")),
    ("chronology of events", _ops("TIMELINE")),
)

_META = (
    ("Why are you showing me these people?", _ops("EXPLAIN_REASONING")),
    ("Why is this person connected?", _ops("EXPLAIN_REASONING")),
    ("Why is this case in the timeline?", _ops("EXPLAIN_REASONING")),
    ("Why is that a hotspot?", _ops("EXPLAIN_REASONING")),
    ("How are you deriving all these?", _ops("EXPLAIN_REASONING")),
    ("How did you get this?", _ops("EXPLAIN_REASONING")),
    ("Show me the chain.", _ops("EXPLAIN_REASONING")),
    ("Why these?", _ops("EXPLAIN_REASONING")),
    ("What supports this?", _ops("EVIDENCE_FOR")),
    ("what evidence do you have", _ops("EVIDENCE_FOR")),
    ("how do you know", _ops("EVIDENCE_FOR")),
    ("prove that", _ops("EVIDENCE_FOR")),
    ("Where are those cases concentrated?", _ops("CASE_LOCATIONS")),
    ("Where are the related cases?", _ops("CASE_LOCATIONS")),
    ("What can you do?", _ops("CAPABILITY")),
    ("what all can you answer", _ops("CAPABILITY")),
    ("how do I use this", _ops("CAPABILITY")),
)

# Questions the system must REFUSE rather than answer. These are the ones where being
# helpful is the failure.
_MUST_REFUSE = (
    ("Who do you think committed the murder in FIR 100222201202600022?", _ops("NOT_INFERABLE")),
    ("who could be the suspect", _ops("NOT_INFERABLE")),
    ("who is guilty", _ops("NOT_INFERABLE")),
    ("who might have done it", _ops("NOT_INFERABLE")),
    ("Name the likely culprit.", _ops("NOT_INFERABLE")),
    ("go back to the first case", _ops("CASE_REFERENCE_UNSUPPORTED")),
    ("return to the previous case", _ops("CASE_REFERENCE_UNSUPPORTED")),
    ("back to that case", _ops("CASE_REFERENCE_UNSUPPORTED")),
    ("the case we started with", _ops("CASE_REFERENCE_UNSUPPORTED")),
)

# Out of domain. Answering these confidently is how "what is the capital of France"
# became a cited hotspot map (see operation_semantics' own note).
_OUT_OF_DOMAIN = (
    "what is the weather today",
    "tell me a joke",
    "how do I reset my password",
    "what time does the canteen close",
    "what is the capital of France",
    "who won the match yesterday",
    "translate this to Hindi",
    "book me a leave",
)

# Real record identifiers, in every form an officer types them.
_IDENTIFIERS = (
    ("What is the status of FIR 100222201202600022?", _ops("FIR_LOOKUP")),
    ("FIR 100222201202600022", _ops("FIR_LOOKUP")),
    ("100222201202600022", _ops("FIR_LOOKUP")),
    ("status of 0112/2026", _ops("FIR_LOOKUP")),
    ("case number 0112/2026", _ops("FIR_LOOKUP")),
    ("pull up FIR 100222201202600022 please", _ops("FIR_LOOKUP")),
    # A number that is NOT a record identifier must never be read as one. (The bare
    # "how many cases in 2026" lives in the generated year loop; repeating it here
    # would make the corpus's own uniqueness guard fail for a cosmetic reason.)
    ("cases in the last 30 days", _ops("CRIME_SEARCH")),
    ("give me case 0112/2026 and 0113/2026", _ops("FIR_LOOKUP")),
)

_BOARD = (
    ("Pin this to the case board", _ops("BOARD_PIN_EVIDENCE")),
    ("add that to the board", _ops("BOARD_PIN_EVIDENCE")),
    ("add this event to the investigation board", _ops("BOARD_PIN_EVIDENCE")),
    ("save this as a lead", _ops("BOARD_ADD_LEAD")),
    ("flag this as a lead", _ops("BOARD_ADD_LEAD")),
    ("add a note that the complainant was re-examined", _ops("BOARD_ADD_NOTE")),
    ("what is on the investigation board", _ops("BOARD_VIEW")),
    ("what have we established", _ops("BOARD_VIEW")),
    ("dismiss that lead", _ops("BOARD_LEAD_STATUS")),
    ("mark the lead as pursued", _ops("BOARD_LEAD_STATUS")),
)

# The way people actually talk: elliptical, mistyped, impatient, code-mixed.
_MESSY = (
    ("theft mandya", _ops("CRIME_SEARCH")),
    ("mandya theft cases pls", _ops("CRIME_SEARCH")),
    ("HOW MANY THEFT CASES IN MANDYA", _ops("CRIME_SEARCH")),
    ("how many theft cases in mandya?????", _ops("CRIME_SEARCH")),
    ("   show me theft cases   ", _ops("CRIME_SEARCH")),
    ("show me teh theft cases in mandya", _ops("CRIME_SEARCH")),
    ("hotspots", _ops("HOTSPOT")),
    ("forecast", _ops("FORECAST")),
    ("timeline", _ops("TIMELINE")),
    ("priors?", _ops("PERSON_HISTORY")),
    ("associates?", _ops("PERSON_NETWORK")),
    ("money trail", _ops("FINANCIAL")),
)

_KANNADA = (
    # Kannada is translated to English inside the container before routing, so these
    # are checked through interpret(), not classify(). Listed here so the corpus
    # documents them as covered rather than leaving the coverage implicit.
    "ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?",
    "ಈ ಪ್ರಕರಣದಲ್ಲಿ ಯಾರು ಭಾಗಿಯಾಗಿದ್ದಾರೆ?",
    "ಅಪರಾಧ ಹಾಟ್‌ಸ್ಪಾಟ್‌ಗಳನ್ನು ತೋರಿಸಿ",
)


def curated() -> list[Entry]:
    out: list[Entry] = []
    for group in (_PERSON, _CASE_SCOPED, _META, _MUST_REFUSE, _IDENTIFIERS, _BOARD,
                  _MESSY):
        out.extend(group)
    return out


def corpus() -> list[Entry]:
    """Every input, generated and curated."""
    return _generated() + curated()


def out_of_domain() -> tuple[str, ...]:
    return _OUT_OF_DOMAIN


def kannada() -> tuple[str, ...]:
    return _KANNADA
