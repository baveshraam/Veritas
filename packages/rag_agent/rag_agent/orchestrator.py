"""The LangGraph investigation engine.

    voice_in -> orchestrate -> retrieve -> evaluate -+-> synthesize -> voice_out
                                   ^                 |
                                   +---- refine <----+   (CRAG: widen and retry once)

The conditional edge out of `evaluate` is the whole point: retrieval that comes back
empty or weak does not proceed to synthesis. It either widens once, or it stops and
says so. Nothing downstream can invent an answer, because synthesis is only ever
handed the evidence list — it has no other input.
"""
import difflib
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from data import ds, upsert_session_focus
from policy import can_view_fir, mask_person_name

from . import behavioral_profile
from . import board as board_agent
from . import intents
from . import provenance
from . import semantic_interpreter
from . import series_detection
from . import timeline as timeline_agent
from .agents import (
    graph_agent, prediction_agent, sql_agent, synthesis_agent,
    translation_agent, vector_agent, voice_agent,
)
from .copilot import brief as copilot_brief
from .evidence.evaluator import evaluate, refusal_message, supporting
from .retrieval import hipporag, tog
from .state import AgentTraceEntry, Citation, EvidenceItem, InvestigationState


class _NoEvidenceInContext(Exception):
    """'Pin this' with nothing pinnable in the previous turn — distinct from
    board_agent.NotPermitted/KeyError (a case-access problem), so it must not be
    caught by the same except clause and misreported as one."""

# The two forms a FIR number takes in this system.
#
#   100222201202600022  the 18-digit CrimeNo the generator writes, the case index
#                       renders, and fir_by_number() has always queried
#   0112/2026           the short serial/year form officers also write by hand
#
# Only the short form was matched before, so every query carrying a real FIR number
# skipped the exact lookup entirely and was answered by semantic search — asking for
# a Hurt case in Mandya returned cyber-crime cases in Shivamogga. The long form is
# floored at 12 digits so ordinary numbers in a question ("the last 30 days", "2026")
# can never be mistaken for a record identifier.
# Defined in intents.py and re-exported here (this name is the one the tests and the
# rest of this module already use). It moved because classify() needs the same fact:
# whether a query names a record at all is part of what the question IS — a query
# that says "FIR" but names no number is not a record lookup, and used to become one.
FIR_NUMBER_RE = intents.FIR_NUMBER_RE

# A question that genuinely asks for a NUMBER, as opposed to one that asks for cases
# and happens to route through the counting branch. The difference matters only in
# the unfiltered case: "how many cases are there?" wants the corpus total and should
# get it; "find cases involving chain snatching near a bus stand" wants the cases and
# must not be handed that same total dressed up as an answer (see CRIME_SEARCH).
_COUNTING_QUESTION = re.compile(
    r"\bhow\s+many\b|\bhow\s+much\b|\bcount\s+(?:of|the)\b|\bnumber\s+of\b"
    r"|\btotal\s+(?:number|cases|firs)\b|\bcase\s+count\b", re.I)

TOG_CONFIDENCE_FLOOR = 0.55      # below this, HippoRAG alone isn't trusted
_RELATIONAL_INTENTS = {"PERSON_NETWORK", "FINANCIAL", "ALIAS_CHECK"}

# Intents whose specialist branch, once it runs for a resolved subject, IS the
# authoritative answer — see the Vector Search Agent skip in _run_specialists.
# CRIME_SEARCH joins this set once it has produced its own exact count (below):
# unlike PERSON_HISTORY/RISK/HOTSPOT/FORECAST, a counting question has one correct
# number, and semantic neighbours cannot corroborate a count — they can only pad it.
_SPECIALIST_SETTLES = _RELATIONAL_INTENTS | {
    "CAUSAL", "CRIME_SEARCH",
    # The four case-scoped conversational intents (see intents.NEEDS_CASE) each
    # produce their own complete answer once a case is open, for the same reason
    # PERSON_NETWORK/FINANCIAL/etc. do: semantic neighbours of the case are not
    # evidence for "what happened", "who's involved", "what next" or the briefing.
    "CASE_CONTEXT", "CASE_PEOPLE", "NEXT_STEPS", "BRIEFING",
    # Case-scoped SIMILAR_CASES (structured explanation, via the Copilot's own
    # retrieval) settles the same way; context-free SIMILAR_CASES (no open case)
    # produces no specialist output and still falls through to generic search.
    "SIMILAR_CASES",
    # A statistic and a ranking are complete answers computed over the whole scoped
    # case set. Semantic neighbours cannot corroborate a count, and appending five
    # narratives to "conviction rate 59%" only buries it — measured live, where the
    # rate arrived as citation [2] of 7 with five unrelated assault cases under it.
    "OFFENDER_RANKING", "CASE_STATS",
    # The six conversational additions below are each a complete answer once their
    # subject/case is resolved, for the same reason the case-scoped block above is:
    # semantic neighbours of an interview-prep briefing or a filing-readiness check
    # are not evidence for the specific gaps those branches already went and found.
    "INTERROGATION_PREP", "CASE_SIMILARITY_WATCH", "CASE_HANDOFF",
    "PREFILING_CHECK", "CROSS_STATION_LINKAGE",
    # series_detection.find_series already IS a similarity search (built on
    # copilot_brief.similar_cases_for) — the generic vector-search fallback would
    # only add the exact kind of "same crime type" semantic padding this module's
    # own MIN_MATCH_STRENGTH/distinctive-MO-match discipline exists to filter out.
    "SERIES_DISCOVERY",
    # A behavioral profile is a set of structural findings read across a person's
    # OWN cases — semantic neighbours of that person are not evidence for whether
    # their own incidents cluster by time, method, geography or severity.
    "BEHAVIORAL_PROFILE",
}


# A live view of the trace, for a caller that wants to show an officer what is
# happening WHILE the turn runs rather than replaying it afterwards.
#
# apps/api streamed the trace only after run_investigation() returned, so every frame
# arrived at once at the end. On a deterministic turn that is invisible (the whole turn
# is under a second); on a turn that consults QuickML it meant 20-35s of spinner with
# nothing behind it, which is the one case where showing progress actually matters.
# The console has always handled incremental frames — the server simply never sent
# any early.
#
# Thread-local rather than a field on the state: LangGraph owns the state objects
# between nodes and may hand each node a reconstructed copy, so an object the caller
# holds a reference to is not guaranteed to be the one being appended to. One
# investigation runs start-to-finish on one worker thread, which makes a thread-local
# sink exactly the right scope and costs the engine no plumbing.
_LIVE_TRACE = threading.local()


@contextmanager
def live_trace(sink: list):
    """Mirror every trace entry into `sink` as it is produced, for this thread."""
    _LIVE_TRACE.sink = sink
    try:
        yield
    finally:
        _LIVE_TRACE.sink = None


def _trace(state: InvestigationState, step: str, detail: str,
           t0: float, confidence: float | None = None) -> None:
    entry = AgentTraceEntry(
        step=step, detail=detail,
        duration_ms=int((time.perf_counter() - t0) * 1000),
        confidence=confidence,
    )
    state.agent_trace.append(entry)
    sink = getattr(_LIVE_TRACE, "sink", None)
    if sink is not None:
        sink.append(entry)


# --- nodes -------------------------------------------------------------------

def node_voice_in(state: InvestigationState) -> InvestigationState:
    if not state.input_audio:
        return state
    t0 = time.perf_counter()
    text, detail = voice_agent.transcribe(state.input_audio, state.language)
    if text:
        state.original_query = text
    _trace(state, "Voice Agent (ASR)", detail, t0)
    return state


def node_translate_in(state: InvestigationState) -> InvestigationState:
    """Kannada query -> English, BEFORE anything reads it.

    Everything downstream is English/Latin-script: the intent classifier's keywords,
    the IPC-section and number-plate regexes, and the district/name gazetteers. Feeding
    Kannada script straight into them matches nothing, so the turn would classify as
    the default intent, extract no entities, retrieve no evidence, and the CRAG
    evaluator would (correctly, but uselessly) refuse to answer. The answer is
    translated back on the way out in node_synthesize.
    """
    query = state.original_query or ""
    if not query or translation_agent.detect_language(query) != "kn":
        return state

    t0 = time.perf_counter()
    state.language = "kn"          # reply in the language the officer asked in
    state.original_query_kn = query      # survives translation for §4.2-style extraction
    english, note = translation_agent.to_english(query)
    if english != query:
        state.original_query = english
        _trace(state, "Translation Agent (kn->en)", f"Query understood as: {english}", t0)
    else:
        # Translation did not run. The turn STOPS here rather than carrying on with the
        # untranslated text, and that is the whole point: this module's own docstring
        # says an untranslated Kannada query "matches none of it and retrieves nothing
        # at all" — so continuing means sweeping the index with a string that cannot
        # match, and refusing with a message about the RECORDS ("no supporting evidence
        # was retrieved — check whether the record exists"). That message is a false
        # statement about the records. Nothing was looked up, because the question was
        # never read.
        #
        # Refusing here says the true thing instead, and says it in the officer's own
        # language on the way out like any other answer.
        state.refusal_reason = "translation_unavailable"
        _trace(state, "Translation Agent (kn->en)", note or "translation unavailable", t0)
    return state


def node_orchestrate(state: InvestigationState) -> InvestigationState:
    """Interpret the officer's query as a structured semantic request.

    Routes through the new semantic_interpreter (which tries LLM path, falls back to
    deterministic intents.classify()), then unpacks the result into InvestigationState
    fields so no downstream nodes need to change.
    """
    t0 = time.perf_counter()
    query = state.original_query or ""

    # Get the prior turn if it exists (for context on follow-ups like "the second one")
    prior_turn = _last_turn(state.session_id) if state.session_id else None

    # New semantic interpreter produces structured request
    sem_req = semantic_interpreter.interpret(
        query=query,
        language=state.language,
        focus=state.active_entities,
        prior_turn=prior_turn,
        # Emitted BEFORE the model round trip, not after it, so a streaming caller can
        # tell the officer what the 20-35s wait is for while they are waiting. Its own
        # duration is therefore ~0 by construction; the elapsed time shows up on the
        # "Orchestrator (semantic)" entry that follows it.
        on_model_call=lambda: _trace(
            state, "Semantic model (QuickML)",
            "No familiar phrasing matched — asking the model to interpret this "
            "question. This is the slow step.", time.perf_counter()),
    )

    # Map to current state contract (no downstream changes needed)
    state.intent = sem_req.operation
    state.decomposed_subqueries = [query]
    state.constraints = sem_req.constraints
    state.comparison_subject_ids = (
        sem_req.comparison_entities if len(sem_req.comparison_entities) == 2 else [])
    state.plan_steps = sem_req.plan_steps

    # Resolve subject if present
    resolved_note = ""
    if sem_req.subject_id:
        if sem_req.subject_type == "person":
            state.active_entities.active_person = sem_req.subject_id
            resolved_note = f"resolved '{sem_req.subject_text}' (pronoun)" if sem_req.reference_kind == "pronoun" else f"resolved '{sem_req.subject_text}'"
        elif sem_req.subject_type == "case":
            state.active_entities.active_fir = sem_req.subject_id
        elif sem_req.subject_type == "location":
            state.active_entities.active_location = sem_req.subject_text
    elif sem_req.subject_text and sem_req.subject_type == "person":
        # The turn names someone we hold no record for. The focus MUST be cleared,
        # never inherited: leaving the previous turn's subject in place makes the
        # engine answer about a different person entirely, and the officer is given
        # someone else's record with nothing to indicate a substitution happened.
        #
        # And the turn refuses HERE, with the reason it actually has, rather than
        # sweeping the vector index and refusing later with "check whether the record
        # exists in the system" — the system already knows the answer to that. This
        # was the behaviour before the semantic-interpreter migration (83b8695)
        # dropped it: two consequences followed, both real. The officer stopped being
        # told the specific, useful fact ("no person of that name appears in the
        # records available to you — I have not substituted a similarly-spelled
        # name"), and a decided refusal started running the generic search again,
        # which is exactly the Evidence-rail padding the guard in node_retrieve
        # exists to prevent.
        # ...but only when the turn actually DEPENDS on that person. NER's person tier
        # is a fallback that labels any unrecognised capitalised token, so a query that
        # never asked about anybody can still carry a spurious "name". Found live: the
        # Kannada "ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?" translates to "How many
        # cases of theft are there in District Mandya?", NER reads "District" as a
        # person, and an unconditional refusal here killed a CRIME_SEARCH that had a
        # district, a crime type and no need for a person at all — it answered
        # correctly the moment this branch stopped refusing for it.
        #
        # NEEDS_SUBJECT is the existing, single definition of "this operation is
        # meaningless without a resolved person". UNKNOWN joins it because a turn that
        # matched no operation has nothing else to go on: there, the unresolved name IS
        # the whole question ("Tell me about <someone we have no file on>").
        state.active_entities.active_person = None
        resolved_note = f"no person matching '{sem_req.subject_text}' exists in the records"
        if sem_req.operation in intents.NEEDS_SUBJECT or sem_req.operation == "UNKNOWN":
            state.refusal_reason = "person_not_on_file"
        else:
            resolved_note += f" — answering the {sem_req.operation} anyway, it needs no person"

    # Propagate any ambiguity/refusal from the interpreter
    if sem_req.ambiguous_candidates:
        state.refusal_reason = "ambiguous_person"
        state.ambiguous_candidates = sem_req.ambiguous_candidates
        resolved_note = f"'{sem_req.subject_text}' matches {len(sem_req.ambiguous_candidates)} people; asking rather than guessing"
    elif sem_req.refusal_reason and not state.refusal_reason:
        # `not state.refusal_reason`: a reason decided just above from the RESOLVED
        # subject (person_not_on_file) is strictly more specific than the
        # interpreter's own generic "no operation matched", and must not lose to it —
        # "Tell me about <someone we have no file on>" matches no keyword either, so
        # both fire on exactly the query where the specific one is the useful one.
        state.refusal_reason = sem_req.refusal_reason

    detail = f"Intent: {state.intent}"
    if resolved_note:
        detail += f"; {resolved_note}"
    _trace(state, "Orchestrator (semantic)", detail, t0, confidence=sem_req.confidence)

    # Snapshot of the last SUBSTANTIVE structured request — never touched by any
    # specialist branch below (unlike state.result_context, which several
    # overwrite wholesale). apps/api's chat router persists it so the NEXT turn's
    # interpreter can read what was actually asked, not just the prose answer,
    # when deciding whether a new query is a correction to it. See
    # semantic_interpreter._interpret_llm.
    #
    # A META operation (RESULT_SET_FOLLOWUP, CASE_LOCATIONS, a board action, ...)
    # is not itself something to correct — see intents.META_OPERATIONS for the
    # live bug this guards against. It carries the PRIOR turn's last_request
    # forward unchanged instead of overwriting it with its own meta-shaped one.
    if sem_req.operation in intents.META_OPERATIONS:
        state.last_request = (prior_turn.result_context.get("last_request")
                              if prior_turn else None) or {}
    else:
        state.last_request = {
            "operation": sem_req.operation, "subject_type": sem_req.subject_type,
            "subject_text": sem_req.subject_text, "subject_id": sem_req.subject_id,
            "constraints": sem_req.constraints,
        }

    # Persist focus so the *next* turn can resolve against it
    try:
        upsert_session_focus(state.session_id, state.officer_id, state.active_entities)
    except Exception:
        pass      # a session-store hiccup must not lose the answer we can still give
    return state


def node_retrieve(state: InvestigationState) -> InvestigationState:
    t0 = time.perf_counter()
    state.retrieval_attempts += 1
    widen = state.retrieval_attempts > 1

    query = state.original_query or ""
    pid = state.active_entities.active_person
    evidence: list[EvidenceItem] = []

    # node_orchestrate already refused (ambiguous_person, person_not_on_file, or a
    # pronoun with no candidate to offer) — retrieval has nothing left to look up.
    # Found live: without this, an ambiguous-name refusal still ran the generic
    # vector-search fallback at the bottom of _run_specialists (pid is None, so every
    # specialist branch is skipped, but that fallback has no such guard) and handed
    # the officer 5 unrelated criminal profiles in the Evidence rail — a citation
    # count and a set of "cited" records sitting right next to a message that says
    # "I will not guess which one you mean," which is exactly the citation-shaped
    # padding this project's own CRAG discipline exists to prevent (BUG-006's
    # failure mode, recurring through a different door: a refusal that already knows
    # it has nothing to cite must not keep searching for something to cite anyway).
    if state.refusal_reason:
        _trace(state, "Orchestrator",
               f"Refusing before retrieval: {state.refusal_reason}", t0)
        return state

    # Three questions that retrieval cannot answer, and must not be asked to try.
    #
    # Running them anyway is what produced the observed behaviour: "who could be the
    # suspect" and "show me the money trail" both swept the vector index, came back with
    # a handful of unrelated criminal profiles, and refused with a message telling the
    # officer to check whether the record exists — when the actual problem was that the
    # question named no record to check. Each of these now stops here with its own
    # reason, and each still refuses; none of them answers.
    if state.intent == "CAPABILITY":
        # Not a refusal — the only one of the three that gets an answer. The reason is
        # set so evaluate() and the conditional edge both leave the turn alone;
        # node_synthesize branches on the intent before it looks at refusals.
        state.refusal_reason = "capability"
        _trace(state, "Orchestrator", "Question is about this tool, not the records", t0)
        return state
    if state.intent == "NOT_INFERABLE":
        state.refusal_reason = "not_inferable"
        _trace(state, "Orchestrator",
               "Question asks for an inference the records do not license", t0)
        return state
    if state.intent == "CASE_REFERENCE_UNSUPPORTED":
        state.refusal_reason = "case_reference_unsupported"
        _trace(state, "Orchestrator",
               "Question names a case by its position in this session, not by FIR "
               "number — no case history is kept", t0)
        return state

    # Meta-questions ABOUT the conversation itself ("why are you showing me this",
    # "what evidence supports that") read the PREVIOUS turn, not the record layer —
    # running retrieval for them would search the index for the literal words "why"
    # or "evidence" and answer from whatever it happened to find. node_synthesize
    # does the actual work; this only routes the turn there untouched, the same way
    # CAPABILITY routes above.
    if state.intent in ("EXPLAIN_REASONING", "EVIDENCE_FOR", "CHALLENGE_FINDING"):
        state.refusal_reason = "meta"
        _trace(state, "Orchestrator",
               "Question is about the previous answer, not the records", t0)
        return state

    # A question that NAMES an FIR number is about that case, whatever else is (or is
    # not) open in the session.
    #
    # Only the FIR_LOOKUP branch resolved a named FIR number, so every other
    # case-scoped question that named one was refused for want of the case it had just
    # been given: "Who is involved in FIR 100242401202300001?" answered "give me an FIR
    # number, or open one first", and "Show me the timeline of FIR …" answered "a
    # timeline needs a case or a person to build it around". Found live 2026-09-06 by
    # clicking a case on the map — every action offered on the pin except one refused,
    # and the map's own buttons are exactly where an officer names a case by pointing
    # at it rather than by typing.
    #
    # Placed here, above the TIMELINE/CASE_LOCATIONS short-circuits and the NEEDS_CASE
    # gate, so one resolution serves all of them. Policy-scoped: a number the officer
    # may not see resolves to nothing and the ordinary refusal stands. It never
    # OVERRIDES a case already resolved by the semantic layer for this turn — that one
    # came from the officer's own words too, and re-deriving it here would be a second,
    # silently different reading of the same sentence.
    if not state.active_entities.active_fir:
        _m = FIR_NUMBER_RE.search(state.original_query or "")
        if _m:
            _rows = sql_agent.fir_by_number(
                _m.group(1), state.officer_role, _officer_ps(state.officer_id))
            if _rows:
                state.active_entities.active_fir = _rows[0]["fir_id"]
                _trace(state, "Orchestrator",
                       f"Question names FIR {_m.group(1)} — treating that case as the "
                       f"subject", t0)

    # "Where are those cases concentrated" names no subject of its own — "those" refers
    # to whatever case list the previous turn showed (e.g. SIMILAR_CASES). This tallies
    # districts over that specific list rather than running a fresh, unscoped HOTSPOT
    # detection — HOTSPOT already owns "where are the crime hotspots" without a "those".
    if state.intent == "CASE_LOCATIONS":
        _handle_case_locations(state, t0)
        return state

    # "Only these?" / "are there more?" — reads the PREVIOUS turn's own recorded
    # result_context (total/shown/is_sample), never a fresh unscoped search. See
    # semantic_interpreter._AMBIGUOUS_MORE_RE for how a turn gets routed here.
    if state.intent == "RESULT_SET_FOLLOWUP":
        _handle_more_results(state, t0)
        return state

    # Cross-entity timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 3) — reads dated
    # records across a case/person's related entities, not a fresh retrieval, so it
    # short-circuits here the same way CASE_LOCATIONS and BOARD_* do.
    if state.intent == "TIMELINE":
        _handle_timeline(state, t0)
        return state
    if state.intent == "TIMELINE_CONNECTION":
        _handle_timeline_connection(state, t0)
        return state

    if (state.intent in intents.NEEDS_CASE and not state.active_entities.active_fir
            and not state.refusal_reason and not state.plan_steps):
        state.refusal_reason = "no_case"
        _trace(state, "Orchestrator",
               f"{state.intent} needs an open case; none given", t0)
        return state
    # "Look at the financial trail around this case" / "who are this case's
    # associates" — a NEEDS_SUBJECT question with a case open but no person named.
    # The case itself supplies the subject when it has exactly one accused; resolving
    # it here is the difference between a real multi-step investigation ("this case"
    # -> its accused -> their money trail) and a refusal that already had the answer
    # sitting one join away. See _resolve_subject_from_open_case for the ambiguous
    # (2+ accused) and no-case-in-scope cases, both of which fall through to the
    # ordinary no_subject refusal below unchanged.
    if (state.intent in intents.NEEDS_SUBJECT and not pid
            and not state.comparison_subject_ids and not state.refusal_reason
            and not state.plan_steps and state.active_entities.active_fir):
        _resolve_subject_from_open_case(state)
        pid = state.active_entities.active_person
        if state.refusal_reason:  # ambiguous_person -- decided, not merely unresolved
            _trace(state, "Orchestrator",
                   f"{state.intent}: case has {len(state.ambiguous_candidates)} "
                   f"accused; asking rather than guessing", t0)
            return state

    if (state.intent in intents.NEEDS_SUBJECT and not pid
            and not state.comparison_subject_ids and not state.refusal_reason
            and not state.plan_steps):
        state.refusal_reason = "no_subject"
        _trace(state, "Orchestrator",
               f"{state.intent} needs a named subject; none given", t0)
        return state

    # The persistent case board (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 1) — a
    # mutation or a read of investigator-authored state, not a retrieval. Handled
    # entirely here and in node_synthesize's matching branch; node_evaluate and
    # _after_evaluate both skip CRAG scoring for these intents below, the same way
    # they already skip it for a refusal decided before retrieval ran.
    if state.intent.startswith("BOARD_"):
        _handle_board_intent(state, t0)
        return state

    # General N-step investigation plan (semantic_interpreter's LLM path only —
    # see SemanticRequest.plan_steps). Checked before the bounded two-entity
    # comparison below: the two are mutually exclusive in practice (comparison_
    # subject_ids only ever comes from the deterministic _COORDINATION_RE path,
    # plan_steps only from the model), but a plan is the more general mechanism
    # and does its own per-step subject/refusal handling.
    if state.plan_steps:
        _run_plan(state, widen, t0)
        return state

    # Bounded deterministic multi-step composition (design spec §3) — sequences
    # the SAME single-subject retrieval below once per compared subject, so it
    # short-circuits here rather than replacing the pid-based flow.
    if state.comparison_subject_ids:
        _handle_comparison(state, widen, t0)
        return state

    # 1. HippoRAG: seed personalized PageRank from the query's entities
    if pid:
        rows, ev = hipporag.retrieve(_entity_names(state), top_k=25 if widen else 15)
        state.graph_query_results += rows
        evidence += ev
        _trace(state, "HippoRAG retrieval",
               f"Personalized PageRank from {len(rows)} seeded nodes", t0)

    # 2. Intent-specific specialist agents
    evidence += _run_specialists(state, widen)

    # 3. ToG deep-dive when HippoRAG was weak or the question is explicitly relational
    from .evidence.evaluator import score_batch
    if (state.intent in _RELATIONAL_INTENTS or score_batch(evidence) < TOG_CONFIDENCE_FLOOR) and pid:
        t1 = time.perf_counter()
        labels = [r.get("name_en") or "subject"
                  for r in state.graph_query_results[:1]] or ["subject"]
        paths, ev = tog.search(query, [pid], labels, state.officer_role)
        evidence += ev
        _trace(state, "Think-on-Graph deep-dive",
               f"Beam-searched {len(paths)} reasoning path(s)", t1)

    state.evidence_items = _dedupe(state.evidence_items + evidence)

    # node_orchestrate already persisted the focus it resolved BEFORE retrieval ran —
    # but FIR_LOOKUP and CASE_PEOPLE (below) can resolve active_fir/active_person
    # DURING retrieval, from what this turn's specialists find. Without persisting
    # again here, that resolution lives only in this turn's response: the next turn
    # reads session focus from storage and finds neither ever happened. This is what
    # let "Open FIR X" followed by "What happened?" forget X was ever opened.
    try:
        upsert_session_focus(state.session_id, state.officer_id, state.active_entities)
    except Exception:
        pass
    return state


def _entity_names(state: InvestigationState) -> list[str]:
    from data.nlp import ner_extract
    return [e.text for e in ner_extract(state.original_query or "", "en")
            if e.label == "PERSON"]


def _run_specialists(state: InvestigationState, widen: bool) -> list[EvidenceItem]:
    intent = state.intent
    pid = state.active_entities.active_person
    role, ps = state.officer_role, _officer_ps(state.officer_id)
    out: list[EvidenceItem] = []
    t0 = time.perf_counter()

    if intent in ("PERSON_HISTORY", "RISK") and pid:
        # person_record() has no station filter of its own (a person's cases can span
        # every station in the state) — the same "belt-and-braces" filter_viewable()
        # already applied to cases_by_ids() elsewhere (line ~1437) was missing here,
        # so an IO asking "does X have priors" got every case statewide in full detail
        # (FIR number, district, narrative), with only the person's NAME masked. Found
        # live: signed in as a station-101 IO, "Does Usha Naika have priors?" returned
        # 18 cases across 6 other districts/stations, none of them PS 101.
        rows = sql_agent.filter_viewable(sql_agent.person_record(pid), role, ps)
        state.sql_query_results += rows
        # "Does she have priors?" is a yes/no question, and the answer opened with a
        # cheating case in Davanagere — twelve FIRs, no name, no count, no verdict on
        # the question actually asked. The header is the answer; the cases are the
        # working. Emitted first so it is citation [1] (see _rank_evidence).
        who = mask_person_name(role, _person_name(pid) or f"person {pid}")
        if rows:
            convicted = sum(1 for r in rows if (r.get("case_status") or "") == "Convicted")
            kinds = sorted({r.get("crime_type") for r in rows if r.get("crime_type")})
            out.append(EvidenceItem(
                evidence_id=f"priors:{pid}", source_type="CRIMINAL_RECORD",
                source_id=str(pid),
                source_query="vx_accused_identity -> Accused -> CaseMaster, per person",
                content=(f"Yes — {who} is named as accused on {len(rows)} case(s) on "
                         f"record within your access scope"
                         + (f", of which {convicted} ended in conviction" if convicted
                            else ", none of which has ended in a conviction")
                         + (f". Offences: {', '.join(kinds[:6])}" if kinds else "")
                         + ". Each case is cited below."),
                confidence=0.96, authoritative=True))
        else:
            out.append(EvidenceItem(
                evidence_id=f"priors:{pid}", source_type="CRIMINAL_RECORD",
                source_id=str(pid),
                source_query="vx_accused_identity -> Accused -> CaseMaster, per person",
                content=(f"No — no case within your access scope names {who} as "
                         f"accused. This is a checked absence, not a failed search; a "
                         f"higher rank may see cases you cannot."),
                confidence=0.9, authoritative=True))
        out += [_fir_evidence(r) for r in rows]
        _trace(state, "SQL Agent", f"{len(rows)} criminal-record row(s)", t0)
        if intent == "RISK":
            t1 = time.perf_counter()
            r, ev = prediction_agent.risk(pid)
            rc, ev2 = prediction_agent.recidivism(pid)
            state.prediction_results["score_risk"] = r
            state.prediction_results["predict_recidivism"] = rc
            out += ev + ev2
            _trace(state, "Prediction Agent", "Risk + recidivism scored", t1)

    elif intent == "PERSON_NETWORK" and pid:
        rows = graph_agent.person_network(pid, role)
        state.graph_query_results += rows
        out += [_network_evidence(r, rows) for r in rows]
        # Exhaustive within the policy depth cap — not a sample of a larger
        # population, so "only these?" gets an honest "yes, that's the complete
        # network" rather than a re-search.
        state.result_context = {
            "operation": "PERSON_NETWORK", "total_matched": len(rows), "shown": len(rows),
            "is_sample": False, "shown_ids": [str(r["person_id"]) for r in rows],
        }
        _trace(state, "Graph Agent", f"{len(rows)} associate(s) within policy depth", t0)

    elif intent == "ALIAS_CHECK" and pid:
        rows = graph_agent.aliases(pid)
        state.graph_query_results += rows
        if rows:
            out += [_alias_evidence(r) for r in rows]
        else:
            # A *negative* finding is the answer here, and it has to be stated. Left
            # unsaid, unrelated context (a ToG path, a semantic match) becomes the
            # top citation and the officer is shown a reasoning chain in reply to a
            # yes/no question the records actually answer: no, there is no alias.
            out.append(EvidenceItem(
                evidence_id="same_as:none", source_type="GRAPH_RELATIONSHIP",
                source_id=pid, source_query="vx_accused_identity — duplicate-identity "
                             "check (probabilistic record linkage)",
                content=("No duplicate-identity (SAME_AS) links are recorded for this "
                         "person. Entity resolution found no other record matching them "
                         "under a different name or spelling."),
                confidence=0.9, authoritative=True))
        state.result_context = {
            "operation": "ALIAS_CHECK", "total_matched": len(rows), "shown": len(rows),
            "is_sample": False, "shown_ids": [str(r["person_id"]) for r in rows],
        }
        _trace(state, "Graph Agent (SAME_AS)", f"{len(rows)} alias record(s)", t0)

    elif intent == "FINANCIAL" and pid:
        rows = graph_agent.money_trail(pid, role)
        state.graph_query_results += rows
        out += [EvidenceItem(
            evidence_id=f"flow:{r['from_account']}:{r['to_account']}",
            source_type="GRAPH_RELATIONSHIP", source_id=str(r["to_account"]),
            source_query="TRANSFERRED_TO edges (vx_graph_edge), walked forward from "
                         "the account, policy-capped depth",
            content=(f"₹{r['amount']:,.0f} moved from account {r['from_account'][:8]}… "
                     f"to {r['to_account'][:8]}… across {r['hops']} transfer(s)."),
            confidence=0.8) for r in rows]
        if not rows:
            # A negative finding IS the answer, and it has to be stated — the same
            # reason ALIAS_CHECK states its own. Left unsaid, the semantic hits below
            # became the top citation, so "show me the money trail for X" was answered
            # with a summary of X's theft cases: a real record, cited, and not about
            # money at all. Measured live as visualization=none with zero flow evidence
            # and a confident answer on top of it.
            #
            # But "no rows" has two different real causes, and they are not the same
            # finding. `money_trail` walks OUTGOING TRANSFERRED_TO edges only (money
            # OUT of this person's accounts, by design — see its own docstring), so a
            # person who only ever RECEIVES money has real owned accounts and real
            # inbound transfers, yet zero rows here. Live-observed: a person's own
            # Timeline showed several real inbound transfers on their account, while
            # this branch's old unconditional message claimed "no bank account is
            # linked to this person" — false, and contradicting the Timeline's own
            # citations for the identical person in the identical session.
            owned = graph_agent.owned_accounts(pid)
            if owned:
                content = (
                    f"This person owns {len(owned)} account(s) on record, but no outbound "
                    "transfer trail was found from them within policy depth. This means "
                    "money is not documented as moving FROM their accounts onward — it does "
                    "not mean no account exists or that no money ever moved through it; any "
                    "incoming transfers are on their Timeline, not this trail.")
            else:
                content = ("No bank account is linked to this person in the records, and "
                           "no transfers are traceable to them. This is an absence in the "
                           "financial layer, not a finding that no money moved.")
            out.append(EvidenceItem(
                evidence_id=f"flow:none:{pid}", source_type="GRAPH_RELATIONSHIP",
                source_id=str(pid),
                source_query="OWNS_ACCOUNT -> TRANSFERRED_TO edges (vx_graph_edge), "
                             "walked forward, policy-capped depth",
                content=content, confidence=0.9, authoritative=True))
        _trace(state, "Graph Agent (money trail)", f"{len(rows)} transfer path(s)", t0)
        # AML detection runs against the accounts this PERSON owns, not the trail's
        # `from_account` — which for a multi-hop transfer can be an intermediate
        # account nobody in this case owns, and which for structuring specifically
        # (deposits INTO an account) was never the side the detector needed to see.
        # Checking only one owned account and stopping meant a person with several
        # accounts had the rest silently unchecked; every owned account is checked now.
        t3 = time.perf_counter()
        n_flags = 0
        for acct in graph_agent.owned_accounts(pid):
            _, ev = prediction_agent.transactions(acct)
            out += ev
            n_flags += len(ev)
        _trace(state, "AML Detectors (structuring + GNN)",
               f"{n_flags} flag(s) across the person's own account(s)", t3)

    elif intent == "FIR_LOOKUP":
        # The classifier has always had this intent; the branch was missing, so
        # "what is the status of FIR 0112/2026" fell through to semantic search and
        # got refused — an exact-ID lookup answered by the wrong retriever.
        m = FIR_NUMBER_RE.search(state.original_query or "")
        if m:
            rows = sql_agent.fir_by_number(m.group(1), role, ps)
            # A named FIR that returns nothing must not be answered from semantic
            # neighbours — see FIR_NUMBER_RE and node_evaluate.
            state.exact_lookup_missed = not rows
            state.exact_lookup_hit = bool(rows)
            state.sql_query_results += rows
            out += [EvidenceItem(
                evidence_id=f"fir:{r['fir_id']}", source_type="FIR_RECORD",
                source_id=str(r["fir_id"]),
                source_query="SELECT ... FROM fir WHERE fir_number = :n",
                content=_fir_content(r),
                confidence=0.97) for r in rows]
            state.active_entities.active_fir = rows[0]["fir_id"] if rows else \
                state.active_entities.active_fir
            _trace(state, "SQL Agent (FIR lookup)",
                   f"{len(rows)} record(s) for FIR {m.group(1)} within policy scope", t0)

    elif intent == "CRIME_SEARCH":
        # The classifier has always had this intent; until now nothing answered it —
        # every turn fell through to semantic search alone, so "how many theft cases
        # in Mandya" got five narrative excerpts and no number anywhere (BUG-008).
        # Counting is a question the structured layer answers exactly; vector search
        # cannot corroborate a count, it can only pad it.
        # state.constraints wins over per-query extraction: a constraint-change
        # follow-up ("same thing for Bengaluru") carries forward a crime type named
        # in an EARLIER turn that this turn's own text never restates.
        ct = state.constraints.get("crime_type") or semantic_interpreter.crime_type_from_query(
            state.original_query or "")
        district_name = state.constraints.get("district") or state.active_entities.active_location
        if district_name:
            # Say it the way the records say it. The filter canonicalises anyway
            # (sql_agent._filters), so an un-canonicalised caption only means the
            # count reads "in Bangalore" over a list of cases that all say
            # "Bengaluru Urban" — the officer's own word, disagreeing with every
            # record under it.
            from data.districts import canonical_code, canonical_name
            _code = canonical_code(district_name)
            district_name = canonical_name(_code) or district_name if _code else district_name
        # date_before/date_after: a relative-time constraint the model can propose
        # when a query reads as a corrected/narrowed repeat of a previous search
        # ("same thing but earlier") — see semantic_interpreter._interpret_llm's
        # correction handling. sql_agent.search_firs/count_firs have always taken
        # date_from/date_to; nothing before this read constraints for either, so
        # a temporal correction silently repeated the SAME window instead of a
        # narrowed one. Parsed leniently (ds.to_dt already handles the live Data
        # Store's string-typed dates); an unparseable value is dropped rather than
        # failing the whole turn — a best-effort filter, not a hard requirement.
        date_before = ds.to_dt(state.constraints.get("date_before"))
        date_after = ds.to_dt(state.constraints.get("date_after"))
        date_to = date_before.date() if date_before else None
        date_from = date_after.date() if date_after else None
        # The qualifiers an officer actually attaches to a case search. Every one of
        # these used to be dropped in silence, so "how many cases are pending in
        # Mandya" answered 263 — every Mandya case, of every status — and "show me
        # cases under section 379" answered 10,000. See semantic_interpreter's own
        # note on why answering a different question without saying so is the worst
        # thing this layer can do short of inventing a record.
        q = state.original_query or ""
        status = state.constraints.get("case_status") or \
            semantic_interpreter.case_status_from_query(q)
        section = state.constraints.get("section") or \
            semantic_interpreter.section_from_query(q)
        station = state.constraints.get("ps_code") or \
            semantic_interpreter.station_from_query(q)
        if not (date_from or date_to):
            date_from, date_to = semantic_interpreter.date_window_from_query(q)

        filters = dict(crime_type=ct, district=district_name, date_from=date_from,
                       date_to=date_to, case_status=status, ps_code=station,
                       section=section)
        count = sql_agent.count_firs(role, ps, **filters)

        # What was actually filtered on, stated. The officer has to be able to see
        # that the number in front of them answers the question they asked — and,
        # where a qualifier was understood, that it was applied rather than assumed.
        applied = [x for x in (
            ct, f"in {district_name}" if district_name else None,
            f"status {status}" if status else None,
            f"section {section}" if section else None,
            f"police station {station}" if station else None,
            f"from {date_from:%d %b %Y}" if date_from else None,
            f"before {date_to:%d %b %Y}" if date_to else None,
        ) if x]
        scope_desc = (" · ".join(applied) if applied
                      else "of every kind, in every district")
        # A description this branch cannot express as a filter must not be answered
        # with a count of the whole corpus. "Find cases involving chain snatching
        # near a bus stand" understood no crime type, district, status, section,
        # station or date — and answered "2500 cases match: of every kind, in every
        # district", cited and confident, followed by five arbitrary FIRs (found live
        # 2026-09-06). The words the officer typed carry real meaning; they are just
        # narrative meaning, which is what the semantic retriever below exists for.
        # A genuine counting question ("how many …", "total") still wants the number,
        # even unfiltered — that IS what was asked.
        wants_count = bool(_COUNTING_QUESTION.search(q))
        if not applied and not wants_count:
            _trace(state, "SQL Agent (crime count)",
                   "no expressible filter in the question — deferring to semantic "
                   "retrieval rather than counting the whole corpus", t0)
        else:
            # The id has to distinguish two different searches, because it is what a board
            # pin, a citation click and an explanation all address. It used to carry only
            # crime type and district, so "cases from PS 2201" and "cases filed in June
            # 2026" both landed on `crime_count:any:any` — two unrelated counts under one
            # identity.
            count_id = "crime_count:" + ":".join(
                (ct or "any", district_name or "any",
                 *(p for p in (status, f"s{section}" if section else None,
                               f"ps{station}" if station else None,
                               f"{date_from:%Y%m%d}" if date_from else None) if p)))
            out.append(EvidenceItem(
                evidence_id=count_id,
                source_type="FIR_RECORD", source_id="count",
                source_query="COUNT over CaseMaster, scoped by role/station",
                # "…{scope} are recorded within your access scope" printed the scope
                # phrase twice when nothing was filtered on: "10000 cases within your
                # access scope are recorded within your access scope."
                content=f"{count} case(s) match: {scope_desc}. Counted within your "
                        f"access scope.",
                confidence=0.95, authoritative=True))
            if section:
                # A section filter selects the offence GROUP that carries the section, not
                # only the offence type that names it — a real limit of the ER's own
                # section-to-head mapping, and one the officer must not have to discover
                # by noticing a burglary in a list of thefts.
                note = sql_agent.section_scope_note(section)
                if note:
                    out.append(EvidenceItem(
                        evidence_id=f"crime_count:section:{section}",
                        source_type="FIR_RECORD", source_id="scope",
                        source_query="CrimeHeadActSection -> CrimeMajorHeadID",
                        content=note, confidence=0.9, authoritative=True))
            samples: list[dict] = []
            if count:
                samples = sql_agent.search_firs(role, ps, limit=5, **filters)
                state.sql_query_results += samples
                out += [EvidenceItem(
                    evidence_id=f"fir:{r['fir_id']}", source_type="FIR_RECORD",
                    source_id=r["fir_id"], source_query="SELECT ... matching the count above",
                    content=_fir_content(r), confidence=0.9) for r in samples]
            # Recorded so a follow-up ("only these?", "same thing for Mysuru") can read
            # a real fact instead of the interpreter re-guessing — see
            # semantic_interpreter._AMBIGUOUS_MORE_RE / _REPEAT_CUE_RE.
            state.result_context = {
                "operation": "CRIME_SEARCH", "total_matched": count, "shown": len(samples),
                "is_sample": count > len(samples), "shown_ids": [str(r["fir_id"]) for r in samples],
                "constraints": {"crime_type": ct, "district": district_name,
                                "case_status": status, "section": section,
                                "ps_code": station},
            }
            _trace(state, "SQL Agent (crime count)",
                   f"{count} matching case(s) — {scope_desc}", t0)

    elif intent == "OFFENDER_RANKING":
        _handle_offender_ranking(state, out, role, ps, t0)

    elif intent == "CASE_STATS":
        _handle_case_stats(state, out, role, ps, t0)

    elif intent == "AREA_PROFILE":
        _handle_area_profile(state, out, role, ps, t0)

    elif intent == "COMMUNITY_PROFILE":
        _handle_community_profile(state, out, role, ps, t0)

    elif intent == "WATCHLIST":
        _handle_watchlist(state, out, role, ps, t0)

    elif intent == "STATION_WORKLOAD":
        _handle_station_workload(state, out, role, ps, t0)

    elif intent == "HOTSPOT":
        dc = _district_code(state)
        if dc:
            polys, ev = prediction_agent.hotspots(dc)
            state.prediction_results["detect_hotspots"] = polys
            # DBSCAN(eps=500m, min_samples=10) finding nothing is a RESULT — the
            # district's incidents are dispersed, not clustered — and it is one an
            # officer needs told. Without this the branch contributed no evidence at
            # all and the turn fell through to the unscoped semantic search at the
            # bottom of _run_specialists, which answered "show me hotspots in Kolar"
            # with five ordinary Kolar FIRs formatted exactly like a finding (found
            # live 2026-09-06). A checked absence, stated, is the whole point of the
            # CRAG evaluator; silently substituting a different answer is its opposite.
            if not polys:
                from data.districts import canonical_name as _cn
                ev = [EvidenceItem(
                    evidence_id=f"hotspot:{dc}:none",
                    source_type="GEOSPATIAL_ANALYSIS",
                    source_id=dc,
                    source_query="KDE (Scott) + DBSCAN(eps=500m, min_samples=10)",
                    content=(f"No statistically significant crime cluster was found in "
                             f"{_cn(dc) or dc} over the last two years — the recorded "
                             f"incidents there are dispersed rather than concentrated. "
                             f"This is a checked absence, not a failed search."),
                    confidence=0.7,
                    confidence_kind="model_estimate",
                )]
            out += ev
            # the incident scatter under the polygons — a hull with no points beneath
            # it is an assertion, not a hotspot
            state.sql_query_results += sql_agent.fir_points(dc)
            # No "sample" concept here (a hotspot map is exhaustive over the
            # district), but the operation+district still need recording so a bare
            # "and Mysuru?" follow-up (semantic_interpreter._REPEAT_CUE_BARE_RE)
            # has a prior operation to repeat — found live: it silently fell
            # through to UNKNOWN without this, since result_context stayed {}.
            from data.districts import canonical_name
            state.result_context = {
                "operation": "HOTSPOT", "total_matched": None, "shown": len(polys),
                "is_sample": False, "shown_ids": [],
                "constraints": {"district": canonical_name(dc)},
            }
            _trace(state, "Prediction Agent (hotspots)",
                   f"{len(polys)} cluster(s) over {len(state.sql_query_results)} incidents", t0)

    elif intent == "FORECAST":
        dc = _district_code(state)
        if dc:
            fc, ev = prediction_agent.forecast(dc)
            state.prediction_results["forecast_crime"] = fc
            out += ev
            from data.districts import canonical_name
            state.result_context = {
                "operation": "FORECAST", "total_matched": None, "shown": len(fc.series),
                "is_sample": False, "shown_ids": [],
                "constraints": {"district": canonical_name(dc)},
            }
            _trace(state, "Prediction Agent (forecast)",
                   f"Prophet+MinT, {len(fc.series)} day(s)", t0)

    elif intent == "CAUSAL":
        dc = _district_code(state) or "KA05"
        # The factor has to come from the question. Hardcoding one (this used to pass
        # "unemployment", which the Census cannot measure per district) means every
        # causal question gets the same answer — or, once the factor list changed,
        # none at all.
        factor = prediction_agent.factor_for(state.original_query or "")
        _, ev = prediction_agent.causal(factor, dc)
        out += ev
        _trace(state, "Prediction Agent (causal)",
               f"DoWhy backdoor adjustment on {factor}", t0)

    # --- case-scoped conversational intents (intents.NEEDS_CASE) -----------------
    #
    # Each of these re-fetches the case through the SAME scoped query FIR_LOOKUP
    # uses (sql_agent.fir_by_id, which applies the IO station filter exactly as
    # policy.can_view_fir would). This is deliberate, not a redundant lookup: the
    # NEEDS_CASE gate above already checked that active_fir was SET, but it was set
    # by a FIR_LOOKUP that may have run under a different officer's scope if this
    # session_id were ever reused by one — re-checking on every use, not trusting a
    # scope check performed on some earlier turn, is what keeps conversation state
    # from becoming an authorization bypass.
    elif intent == "CASE_CONTEXT" and state.active_entities.active_fir:
        rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        state.sql_query_results += rows
        out += [EvidenceItem(
            evidence_id=f"fir:{r['fir_id']}", source_type="FIR_RECORD", source_id=str(r["fir_id"]),
            source_query="SELECT ... FROM CaseMaster WHERE CaseMasterID = :cid (the open case)",
            content=_fir_content(r), confidence=0.97) for r in rows]
        _trace(state, "SQL Agent (case context)",
               f"{len(rows)} record(s) for the open case" if rows else
               "the open case is no longer within policy scope", t0)

    elif intent == "CASE_PEOPLE" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            accused = sql_agent.accused_on_case(state.active_entities.active_fir)
            state.graph_query_results += [
                {"person_id": a["PersonUID"], "name_en": a["CanonicalName"] or a["AccusedName"],
                 "hops": 1, "pagerank": float(a["PageRank"] or 0.0)} for a in accused]
            out += [EvidenceItem(
                evidence_id=f"accused:{a['PersonUID']}", source_type="CRIMINAL_RECORD",
                source_id=str(a["PersonUID"]),
                source_query='"Accused" JOIN "vx_accused_identity" JOIN "vx_person" '
                             'WHERE "CaseMasterID" = :cid',
                content=(f"{a['CanonicalName'] or a['AccusedName']} is accused on this case"
                         + (f" (network community {a['CommunityID']})"
                            if a.get("CommunityID") is not None else "") + "."),
                confidence=0.95) for a in accused]
            # Exactly one accused: name the follow-up subject the way a named PERSON
            # entity would, so "tell me about this person" resolves without asking.
            # More than one: CLEAR active_person — naming one of several would be the
            # same unlicensed guess the ambiguous-name check above refuses to make,
            # and the answer already lists names the officer can say back. This must
            # be an explicit clear, not a no-op: a person named several turns and
            # cases ago (still sitting in active_person from a stale turn) would
            # otherwise survive re-opening a DIFFERENT multi-accused case, so a later
            # pronoun ("does he have priors?") would silently resolve to that stale
            # person instead of asking which of THIS case's several accused is meant.
            state.active_entities.active_person = (
                str(accused[0]["PersonUID"]) if len(accused) == 1 else None)
            # "Nobody is recorded as accused on this case" is a FINDING, and an
            # authoritative one — the same distinction ALIAS_CHECK ("no alias"),
            # FINANCIAL ("no account linked") and NEXT_STEPS ("no co-accused to lead
            # from") already make. Without it the empty list falls through to the
            # generic CRAG refusal, which tells the officer to "check whether the
            # record exists in the system" — about a case they are currently looking
            # at. Found live: FIR 100010101202300001 has no accused, and "who else was
            # involved in it?" answered with exactly that false statement.
            if not accused:
                out.append(EvidenceItem(
                    evidence_id=f"no_accused:{case_rows[0]['fir_id']}",
                    source_type="FIR_RECORD", source_id=str(case_rows[0]["fir_id"]),
                    source_query='"Accused" WHERE "CaseMasterID" = :cid',
                    content=(f"No accused person is recorded on FIR "
                             f"{case_rows[0].get('fir_number') or case_rows[0]['fir_id']}. "
                             "The case exists and is readable; its accused list is empty."),
                    confidence=0.95, authoritative=True))
            _trace(state, "SQL Agent (accused on case)",
                   f"{len(accused)} accused person(s) on the open case", t0)
        else:
            _trace(state, "SQL Agent (accused on case)",
                   "the open case is no longer within policy scope", t0)

    elif intent == "SIMILAR_CASES" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            similar = copilot_brief.similar_cases_for(case_rows[0])
            out += [EvidenceItem(
                evidence_id=f"fir:{c['fir_id']}", source_type="FIR_RECORD",
                source_id=str(c["fir_id"]),
                source_query="hybrid_search over fir_narrative, ranked by structured overlap",
                content=f"{_fir_content(c)} Similar because: {c['explanation']}.",
                confidence=float(c["similarity"]), confidence_kind="similarity") for c in similar]
            # A ranked top-N, not a threshold count — there is no honest "total
            # similar cases exist" number, so total_matched stays None rather than
            # inventing one. is_sample=True is still correct: raising the limit (see
            # _handle_more_results) can always surface more, ranked lower.
            state.result_context = {
                "operation": "SIMILAR_CASES", "total_matched": None, "shown": len(similar),
                "is_sample": True, "shown_ids": [str(c["fir_id"]) for c in similar],
            }
            _trace(state, "Copilot (similar cases)",
                   f"{len(similar)} structurally-explained match(es) for the open case", t0)

    elif intent == "NEXT_STEPS" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            leads = copilot_brief.leads_for_case(state.active_entities.active_fir, role)
            if leads:
                out += [EvidenceItem(
                    evidence_id=f"lead:{state.active_entities.active_fir}:{i}",
                    source_type="COMMUNITY_SUMMARY", source_id=state.active_entities.active_fir,
                    source_query="graph-derived investigative leads (direct co-accused only)",
                    content=lead, confidence=0.85, authoritative=True)
                    for i, lead in enumerate(leads)]
            else:
                out.append(EvidenceItem(
                    evidence_id=f"lead:{state.active_entities.active_fir}:none",
                    source_type="COMMUNITY_SUMMARY", source_id=state.active_entities.active_fir,
                    source_query="graph-derived investigative leads (direct co-accused only)",
                    content="No direct co-accused associates are recorded for anyone on this "
                            "case, so there is no graph-derived lead to suggest beyond the "
                            "case record itself — this is an absence in the network, not a "
                            "failure to look.",
                    confidence=0.9, authoritative=True))
            _trace(state, "Copilot (leads)", f"{len(leads)} investigative lead(s)", t0)

    elif intent == "BRIEFING" and state.active_entities.active_fir:
        try:
            b = copilot_brief.generate_copilot_brief(state.active_entities.active_fir, role, ps)
            out.append(EvidenceItem(
                evidence_id=f"briefing:{state.active_entities.active_fir}",
                source_type="FIR_RECORD", source_id=state.active_entities.active_fir,
                source_query="Investigation Copilot brief (timeline + similar cases + leads)",
                content=b.draft_summary, confidence=0.95, authoritative=True))
            out += [EvidenceItem(
                evidence_id=f"briefing_lead:{state.active_entities.active_fir}:{i}",
                source_type="COMMUNITY_SUMMARY", source_id=state.active_entities.active_fir,
                source_query="Investigation Copilot brief — investigative leads",
                content=lead, confidence=0.85, authoritative=True)
                for i, lead in enumerate(b.leads)]
            _trace(state, "Copilot (briefing)",
                   f"draft summary + {len(b.leads)} lead(s) + {len(b.timeline)} "
                   f"timeline event(s)", t0)
        except KeyError:
            _trace(state, "Copilot (briefing)",
                   "the open case is no longer found within policy scope", t0)
        except copilot_brief.NotPermitted:
            _trace(state, "Copilot (briefing)",
                   "the open case is outside this officer's station scope", t0)

    elif intent == "INTERROGATION_PREP" and pid:
        rows = sql_agent.filter_viewable(sql_agent.person_record(pid), role, ps)
        who = mask_person_name(role, _person_name(pid) or f"person {pid}")
        prep = _interview_prep(pid, who, rows, role, ps)
        out += [EvidenceItem(
            evidence_id=f"interview:{pid}:{i}", source_type="CRIMINAL_RECORD",
            source_id=pid,
            source_query="person_record + arrest/chargesheet gaps + co-offending "
                         "network, assembled for interview preparation",
            content=p, confidence=0.9, authoritative=True) for i, p in enumerate(prep)]
        _trace(state, "Copilot (interrogation prep)", f"{len(prep)} preparation point(s)", t0)

    elif intent == "BEHAVIORAL_PROFILE" and pid:
        rows = sql_agent.filter_viewable(sql_agent.person_record(pid), role, ps)
        findings = behavioral_profile.build_profile(pid, rows)
        if not findings:
            out.append(EvidenceItem(
                evidence_id=f"profile:{pid}:none", source_type="CRIMINAL_RECORD",
                source_id=pid,
                source_query="behavioral_profile.build_profile over person_record",
                content="No recurring pattern clears the bar for a profile — either "
                        "too few recorded cases, or nothing lines up across them. "
                        "This is a checked absence, not a failed search.",
                confidence=0.85, authoritative=True))
            _trace(state, "Behavioral profile", "no pattern found", t0)
        else:
            out += [EvidenceItem(
                evidence_id=f"profile:{pid}:{i}", source_type="CRIMINAL_RECORD",
                source_id=pid,
                source_query="behavioral_profile.build_profile over person_record",
                content=f["claim"], confidence=0.88, authoritative=True)
                for i, f in enumerate(findings)]
            _trace(state, "Behavioral profile",
                  f"{len(findings)} finding(s) from {len(rows)} case(s)", t0)

    elif intent == "CASE_SIMILARITY_WATCH" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            candidates = copilot_brief.similar_cases_for(case_rows[0], limit=10)
            shown = [c for c in candidates
                    if (c.get("case_status") or "").lower() in
                       ("undetected", "closed as undetected")
                    or c.get("ps_code") == ps][:5]
            if shown:
                out += [EvidenceItem(
                    evidence_id=f"watch:{state.active_entities.active_fir}:{c['fir_id']}",
                    source_type="FIR_RECORD", source_id=str(c["fir_id"]),
                    source_query="similar_cases_for, filtered to your own open backlog "
                                 "and unsolved cases",
                    content=f"{_fir_content(c)} Matches your open case because: "
                            f"{c['explanation']}.",
                    confidence=float(c["similarity"]), confidence_kind="similarity")
                    for c in shown]
            else:
                out.append(EvidenceItem(
                    evidence_id=f"watch:{state.active_entities.active_fir}:none",
                    source_type="FIR_RECORD", source_id=state.active_entities.active_fir,
                    source_query="similar_cases_for, filtered to your own open backlog "
                                 "and unsolved cases",
                    content="Nothing in your own open cases or the unsolved backlog "
                            "structurally matches this one. This checks structural "
                            "overlap only — it is not a guarantee no connection exists.",
                    confidence=0.85, authoritative=True))
            _trace(state, "Copilot (case-similarity watch)",
                   f"{len(shown)} backlog/cold match(es)", t0)

    elif intent == "CASE_HANDOFF" and state.active_entities.active_fir:
        fir_id = state.active_entities.active_fir
        try:
            b = copilot_brief.generate_copilot_brief(fir_id, role, ps)
            board = board_agent.get_board(fir_id, role, ps)
            out.append(EvidenceItem(
                evidence_id=f"handoff:{fir_id}:summary", source_type="FIR_RECORD",
                source_id=fir_id, source_query="Investigation Copilot brief, read as a "
                             "case handoff",
                content=b.draft_summary, confidence=0.95, authoritative=True))
            notes = [i for i in board["items"] if i["item_type"] == "note"]
            leads_open = [i for i in board["items"]
                         if i["item_type"] == "lead" and i.get("status") == "open"]
            leads_dismissed = [i for i in board["items"]
                               if i["item_type"] == "lead" and i.get("status") == "dismissed"]
            pinned = [i for i in board["items"] if i["item_type"] in ("evidence", "person")]
            out.append(EvidenceItem(
                evidence_id=f"handoff:{fir_id}:board", source_type="COMMUNITY_SUMMARY",
                source_id=fir_id, source_query="Investigation board — what previous "
                             "officers left on this case",
                content=(f"The investigation board carries {len(pinned)} pinned "
                         f"item(s), {len(notes)} note(s), {len(leads_open)} open "
                         f"lead(s) and {len(leads_dismissed)} lead(s) already ruled "
                         f"out — nothing here needs to be rediscovered."
                         if board["items"] else
                         "Nothing has been pinned to the investigation board for this "
                         "case yet — you are the first to leave a record here."),
                confidence=0.95, authoritative=True))
            out += [EvidenceItem(
                evidence_id=f"handoff:{fir_id}:lead:{i}", source_type="COMMUNITY_SUMMARY",
                source_id=fir_id, source_query="Investigation board — open leads",
                content=f"Still open: {item['content']}", confidence=0.85,
                authoritative=True) for i, item in enumerate(leads_open[:5])]
            _trace(state, "Copilot (case handoff)",
                   f"handoff assembled — {len(board['items'])} board item(s)", t0)
        except KeyError:
            _trace(state, "Copilot (case handoff)",
                   "the open case is no longer found within policy scope", t0)
        except copilot_brief.NotPermitted:
            _trace(state, "Copilot (case handoff)",
                   "the open case is outside this officer's station scope", t0)

    elif intent == "PREFILING_CHECK" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            case = case_rows[0]
            gaps = _case_evidence_gaps(state.active_entities.active_fir, role, ps)
            if gaps:
                out += [EvidenceItem(
                    evidence_id=f"filing:{state.active_entities.active_fir}:{i}",
                    source_type="FIR_RECORD", source_id=state.active_entities.active_fir,
                    source_query="ArrestSurrender/ChargesheetDetails for the open case",
                    content=g, confidence=0.9, authoritative=True)
                    for i, g in enumerate(gaps)]
            else:
                out.append(EvidenceItem(
                    evidence_id=f"filing:{state.active_entities.active_fir}:none",
                    source_type="FIR_RECORD", source_id=state.active_entities.active_fir,
                    source_query="ArrestSurrender/ChargesheetDetails for the open case",
                    content="No structural gap was found — an arrest is on record and "
                            "the case either has a chargesheet or is still within a "
                            "normal open window. This checks the file's own "
                            "completeness only; it is not a judgement on the strength "
                            "of the evidence itself.",
                    confidence=0.9, authoritative=True))
            breakdown = sql_agent.status_breakdown(role, ps, crime_type=case.get("crime_type"))
            if breakdown:
                total = sum(breakdown.values())
                summary = ", ".join(f"{v} {k}" for k, v in
                                    sorted(breakdown.items(), key=lambda kv: -kv[1])[:4])
                offence = case.get("crime_type") or "this type of"
                out.append(EvidenceItem(
                    evidence_id=f"filing:{state.active_entities.active_fir}:context",
                    source_type="FIR_RECORD", source_id=state.active_entities.active_fir,
                    source_query="status breakdown for this crime type, within your "
                                 "access scope",
                    content=f"For context: of {total} {offence} case(s) you can see, "
                            f"the outcomes are {summary}.",
                    confidence=0.85, authoritative=True))
            _trace(state, "SQL Agent (filing readiness)",
                   f"{len(gaps)} structural gap(s) found", t0)

    elif intent == "CROSS_STATION_LINKAGE" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            case = case_rows[0]
            accused = sql_agent.accused_on_case(state.active_entities.active_fir)
            links: list[EvidenceItem] = []
            seen = {state.active_entities.active_fir}
            for a in accused[:10]:
                try:
                    other_cases = sql_agent.person_record(str(a["PersonUID"]))
                except Exception:
                    other_cases = []
                for oc in other_cases:
                    if oc["fir_id"] in seen or oc.get("ps_code") == case["ps_code"]:
                        continue
                    seen.add(oc["fir_id"])
                    name = a["CanonicalName"] or a["AccusedName"]
                    if can_view_fir(role, ps, oc.get("ps_code") or ""):
                        links.append(EvidenceItem(
                            evidence_id=f"linkage:{state.active_entities.active_fir}:"
                                       f"{oc['fir_id']}",
                            source_type="FIR_RECORD", source_id=oc["fir_id"],
                            source_query="person_record — this case's accused, "
                                         "cross-referenced by station",
                            content=(f"{name} is also named as accused on FIR "
                                    f"{oc.get('fir_number') or oc['fir_id']} "
                                    f"({oc.get('crime_type') or 'offence not recorded'}) "
                                    f"at {oc.get('ps_name') or oc.get('ps_code')} — a "
                                    f"different station."),
                            confidence=0.93, authoritative=True))
                    else:
                        links.append(EvidenceItem(
                            evidence_id=f"linkage:{state.active_entities.active_fir}:"
                                       f"{oc['fir_id']}",
                            source_type="FIR_RECORD", source_id=oc["fir_id"],
                            source_query="person_record — this case's accused, "
                                         "cross-referenced by station",
                            content=(f"{name} is also named as accused on an open case "
                                    f"at a station outside your access scope — the "
                                    f"link is real, the case cannot be named here. "
                                    f"Contact that station directly."),
                            confidence=0.9, authoritative=True))
            if links:
                out += links[:8]
            else:
                out.append(EvidenceItem(
                    evidence_id=f"linkage:{state.active_entities.active_fir}:none",
                    source_type="FIR_RECORD", source_id=state.active_entities.active_fir,
                    source_query="person_record — this case's accused, cross-referenced "
                                 "by station",
                    content="None of this case's accused are named on any case at a "
                            "different station, within what this check can see. This "
                            "is a checked absence, not a failed search.",
                    confidence=0.9, authoritative=True))
            _trace(state, "SQL Agent (cross-station linkage)",
                   f"{len(links)} cross-station link(s)", t0)

    elif intent == "SERIES_DISCOVERY" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            case = case_rows[0]
            result = series_detection.find_series(case)
            if result is None:
                out.append(EvidenceItem(
                    evidence_id=f"series:{state.active_entities.active_fir}:none",
                    source_type="FIR_RECORD", source_id=state.active_entities.active_fir,
                    source_query="series_detection.find_series — cross-station MO/section "
                                 "match, excluding cases already linked by a known accused",
                    content="No structural pattern was found spanning other stations for "
                            "this case. This checks for a specific kind of cross-jurisdiction "
                            "match — a shared distinctive method with no common suspect yet "
                            "— it is not a guarantee no connection exists.",
                    confidence=0.85, authoritative=True))
                _trace(state, "Series discovery", "no cross-station pattern found", t0)
            else:
                member_ids = [m.fir_id for m in result.members]
                by_id = {c["fir_id"]: c for c in sql_agent.cases_by_ids(member_ids)}
                out.append(EvidenceItem(
                    evidence_id=f"series:{state.active_entities.active_fir}:summary",
                    source_type="GEOSPATIAL_ANALYSIS", source_id=state.active_entities.active_fir,
                    source_query="series_detection.find_series",
                    content=(f"This case structurally matches {len(result.members)} other "
                            f"case(s) across {len(result.stations)} station(s) in "
                            f"{len(result.districts)} district(s) "
                            f"({', '.join(result.districts) or 'district not recorded'}) — "
                            f"nobody investigating any one of these cases would otherwise "
                            f"see the others. This is a structural pattern, not a confirmed "
                            f"common offender: none of these cases shares a known accused "
                            f"with this one yet."),
                    confidence=0.9, authoritative=True))
                state.sql_query_results.append(case)
                for m in result.members:
                    viewable = can_view_fir(role, ps, m.ps_code)
                    if viewable:
                        out.append(EvidenceItem(
                            evidence_id=f"series:{state.active_entities.active_fir}:{m.fir_id}",
                            source_type="FIR_RECORD", source_id=m.fir_id,
                            source_query="series_detection.find_series",
                            content=(f"FIR {m.fir_number or m.fir_id} at "
                                    f"{m.ps_name or m.ps_code} "
                                    f"({m.district or 'district not recorded'}) — matches "
                                    f"because: {'; '.join(m.matched_features) or 'unspecified'}."),
                            confidence=m.similarity, confidence_kind="similarity"))
                        if m.fir_id in by_id:
                            state.sql_query_results.append(by_id[m.fir_id])
                    else:
                        out.append(EvidenceItem(
                            evidence_id=f"series:{state.active_entities.active_fir}:{m.fir_id}",
                            source_type="FIR_RECORD", source_id=m.fir_id,
                            source_query="series_detection.find_series",
                            content="A matching case exists at a station outside your "
                                    "access scope — the pattern is real, that case cannot "
                                    "be named here. Contact that station directly.",
                            confidence=0.85, authoritative=True))
                _trace(state, "Series discovery",
                      f"{len(result.members)} cross-station match(es) across "
                      f"{len(result.stations)} station(s)", t0)

    # Vector search complements the graph on narrative/MO semantics — but not when a
    # specialist has already produced the whole answer. Two shapes of that:
    #
    #  - an exact identifier hit (FIR_LOOKUP): the nearest narratives to a named record
    #    are cases about something else, not evidence for it.
    #  - a relational/statistical specialist that settles its question on its own
    #    (PERSON_NETWORK, FINANCIAL, ALIAS_CHECK, CAUSAL): once one of these has run
    #    for a resolved subject, its result — a real relationship, an authoritative
    #    negative finding, or a declined estimate — IS the complete answer. Semantic
    #    neighbours of the SUBJECT are not evidence for the RELATIONSHIP or the
    #    ESTIMATE the question actually asked about. This is what let "show me the
    #    money trail for Usha Naika" answer from a summary of her theft cases (real
    #    record, cited, not about money), and "why does crime correlate with literacy"
    #    lose its honest decline under five unrelated criminal profiles that happened
    #    to clear the relevance floor.
    #
    # retrieval candidate != evidence: a specialist result speaks with the record
    # layer's own authority, and padding it with unrelated semantic hits does not
    # corroborate it — it just gives the officer more to wade through before finding
    # the one citation that actually answers the question. Scoped to exactly the
    # intents whose specialist branch IS the authoritative source for the question;
    # PERSON_HISTORY, RISK, HOTSPOT, FORECAST and CRIME_SEARCH still want narrative
    # corroboration from vector search, and still get it.
    if state.exact_lookup_hit:
        _trace(state, "Vector Search Agent",
               "Skipped — the query named a record and the exact lookup found it", t0)
        return out
    if state.intent in _SPECIALIST_SETTLES and out:
        _trace(state, "Vector Search Agent",
               f"Skipped — {state.intent} was answered directly from the record layer", t0)
        return out

    t2 = time.perf_counter()
    k = 8 if widen else 5
    rows, ev = vector_agent.search(state.original_query or "", k=k)
    state.vector_search_results += rows
    out += ev
    _trace(state, "Vector Search Agent",
           f"{len(rows)} semantic match(es) (hybrid dense+BM25)", t2)
    return out


def _officer_ps(officer_id: str) -> str:
    """The station an officer belongs to — the IO scope every query is filtered by.

    The ER's Employee.UnitID *is* the station code; there is no separate `ps_code`.
    """
    from data import ds
    try:
        r = ds.one('SELECT "UnitID" FROM "Employee" WHERE "EmployeeID" = :e',
                   {"e": int(officer_id)})
        return str(r["UnitID"]) if r else ""
    except Exception:
        return ""


def _resolve_subject_from_open_case(state: InvestigationState) -> None:
    """A NEEDS_SUBJECT question (financial trail, associates, priors, aliases) asked
    with a case open but no person named — resolve against that case's own accused,
    the same resolution discipline `semantic_interpreter._resolve_other_candidate` and
    the CASE_PEOPLE-citation pronoun fallback already apply elsewhere: don't refuse
    when the record layer already supplies an unambiguous subject one join away.

    Confirms RBAC scope on the case itself first — `accused_on_case()` is unscoped by
    station (per its own docstring), so the caller must check access to the case
    before reading who's on it, exactly as `CASE_PEOPLE`'s own handler already does.

    Leaves state untouched (falls through to the ordinary no_subject refusal) when the
    case isn't in scope, has no accused on file, or has more than one — the last case
    sets ambiguous_candidates instead of guessing, the same tied-name discipline a
    genuinely ambiguous person search already uses.
    """
    role, ps = state.officer_role, _officer_ps(state.officer_id)
    case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
    if not case_rows:
        return
    accused = sql_agent.accused_on_case(state.active_entities.active_fir)
    if not accused:
        return
    if len(accused) == 1:
        state.active_entities.active_person = str(accused[0]["PersonUID"])
        return
    state.refusal_reason = "ambiguous_person"
    state.ambiguous_candidates = [a["CanonicalName"] or a["AccusedName"] for a in accused]


def _case_evidence_gaps(fir_id: str, role: str, ps: str) -> list[str]:
    """Structural completeness gaps on ONE case file — no arrest on record, no
    chargesheet after a normal open window, or a chargesheet already marked false or
    undetected. Shared by PREFILING_CHECK ('would this hold up') and
    CHALLENGE_FINDING ('poke holes in this') — the same real gaps, asked about two
    different moments: before a case is sent up, and after an answer built on it has
    already been given. States an absence; never an opinion on guilt or strength."""
    rows = sql_agent.fir_by_id(fir_id, role, ps)
    if not rows:
        return []
    case = rows[0]
    gaps: list[str] = []
    arrests = ds.query(
        'SELECT "ArrestSurrenderID" FROM "ArrestSurrender" WHERE "CaseMasterID" = :cid',
        {"cid": int(fir_id)})
    if not arrests:
        gaps.append("No arrest is recorded on this case — the accusation alone is on file.")
    chargesheets = ds.query(
        'SELECT "cstype" FROM "ChargesheetDetails" WHERE "CaseMasterID" = :cid',
        {"cid": int(fir_id)})
    types = {c.get("cstype") for c in chargesheets}
    if not chargesheets:
        filed = ds.to_dt(case.get("date_filed"))
        if filed:
            age = (datetime.now() - filed).days
            if age > sql_agent.STALE_DAYS:
                gaps.append(f"No chargesheet has been filed in {age} days.")
    elif "B" in types:
        gaps.append("A chargesheet on this case is already marked closed as false.")
    elif "C" in types:
        gaps.append("A chargesheet on this case is already marked closed as undetected.")
    return gaps


def _interview_prep(pid: str, who: str, rows: list[dict],
                    role: str, ps: str) -> list[str]:
    """Questions an officer can actually PUT TO THE PERSON, each grounded in a record.

    Deliberately NOT `_case_evidence_gaps`. That helper finds file-completeness gaps —
    no arrest entry, no chargesheet after N days — which are the investigating
    officer's OWN record-keeping to answer for. Asked across an interview table
    ("explain the 805-day delay in filing your chargesheet") it is a question nobody
    in the room is in a position to answer, and it was the entire body of this
    briefing until it was read out loud. Found live. Every line below is something
    the subject themselves can speak to; PREFILING_CHECK still owns the file gaps,
    which is the moment they genuinely matter.
    """
    if not rows:
        return [f"No case within your access scope names {who} as accused — there is "
                f"no prior record to prepare from, and nothing here to put to them."]

    def _label(r: dict) -> str:
        return f"FIR {r.get('fir_number') or r['fir_id']}"

    convicted = [r for r in rows if (r.get("case_status") or "") == "Convicted"]
    settled = {"convicted", "acquitted", "closed", "disposed"}
    open_cases = [r for r in rows
                  if (r.get("case_status") or "").strip().lower() not in settled]

    out = [f"{who} is named as accused on {len(rows)} case(s) on record within your "
           f"access scope — {len(convicted)} ended in conviction, {len(open_cases)} "
           f"still open. Everything below is a question to put to them, each with "
           f"the record it comes from; none of it asserts guilt."]

    # 1. Their own account of each open case — the reason the interview is happening.
    for r in open_cases[:3]:
        out.append(f"Ask for their account of {_label(r)} — "
                   f"{(r.get('crime_type') or 'offence not recorded')}, "
                   f"{(r.get('district') or 'district not recorded')}, filed "
                   f"{_fir_date(r.get('date_filed'))}, status "
                   f"{(r.get('case_status') or 'not recorded')}: where they were, "
                   f"who was with them, and what they say happened.")

    # 2. Co-accused named on the SAME file. The strongest question in the room, and
    #    it is a recorded fact rather than a derived one — the file names both.
    pairs = 0
    for r in rows[:6]:
        if pairs >= 2:
            break
        try:
            others = sql_agent.accused_on_case(r["fir_id"])
        except Exception:
            continue
        names = [mask_person_name(role, o.get("CanonicalName") or "")
                 for o in others if str(o.get("PersonUID")) != str(pid)]
        names = [n for n in names if n][:3]
        if names:
            pairs += 1
            out.append(f"{_label(r)} names them alongside {', '.join(names)} — ask "
                       f"how they know each other and what each of them did.")

    # 3. A repetition worth putting to them, stated as the count it is.
    from collections import Counter
    kinds = Counter((r.get("crime_type") or "").strip() for r in rows if r.get("crime_type"))
    places = Counter((r.get("district") or "").strip() for r in rows if r.get("district"))
    if kinds:
        kind, n = kinds.most_common(1)[0]
        if n > 1:
            where = f" — {places.most_common(1)[0][0]} most often" if places else ""
            out.append(f"Their record shows {n} case(s) of {kind}{where}. Ask them to "
                       f"account for the repetition; it is a pattern in the file, not "
                       f"a finding about them.")

    # 4. Convictions they have already been through — establish what they accept
    #    before asking about anything they do not.
    if convicted:
        out.append(f"Ask whether they accept the {len(convicted)} case(s) already "
                   f"ending in conviction ({', '.join(_label(r) for r in convicted[:3])})"
                   f" — settled record is the ground to establish before contested "
                   f"ground.")

    # 5. Associates reached through the co-offending graph. Flagged as derived,
    #    because a graph associate is not the same claim as a co-accused on file.
    net = graph_agent.person_network(pid, role)
    if net:
        top = sorted(net, key=lambda r: r.get("hops", 99))[:3]
        named = [x for x in (mask_person_name(role, r.get("name_en") or "")
                             for r in top if r.get("name_en")) if x]
        if named:
            out.append(f"Derived, not stated in any one file: {', '.join(named)} "
                       f"appear in the same co-offending network. Ask about the "
                       f"relationship — do not put it to them as an established fact.")

    out.append("Do not raise gaps in our own file-keeping (a missing arrest entry, an "
               "unfiled chargesheet) — those are for the investigating officer to "
               "answer, not the subject. Ask 'would this case hold up?' for those.")
    return out


def _network_challenges(pid: str, role: str) -> list[str]:
    """What would weaken a DERIVED co-offending answer, as opposed to a case file.

    Two things genuinely hold such an answer up, and both are checkable: how many of
    the people named are direct co-accused rather than transitively reached, and how
    strong the record-linkage that reconstructed the subject actually was. Neither is
    an opinion — CLAUDE.md §0 is explicit that the ER has no person, so every name in
    a network answer sits on top of `vx_accused_identity`, and that is exactly the
    assumption a defence would test first."""
    out: list[str] = []
    try:
        net = graph_agent.person_network(pid, role)
    except Exception:
        net = []
    if net:
        indirect = [r for r in net if int(r.get("hops") or 1) > 1]
        if indirect:
            out.append(f"{len(indirect)} of the {len(net)} people named are not direct "
                       f"co-accused — they were reached through someone else's case. A "
                       f"multi-hop link places two people in one network; it is not "
                       f"evidence that they know each other, and it is the first thing "
                       f"to drop if you need only people named on a shared file.")
    try:
        links = ds.query('SELECT "MatchConfidence" FROM "vx_accused_identity" '
                         'WHERE "PersonUID" = :pid', {"pid": int(pid)})
    except Exception:
        links = []
    scores = [float(r["MatchConfidence"]) for r in links
              if r.get("MatchConfidence") is not None]
    if scores:
        out.append(f"This person is not a row in the records — they are "
                   f"{len(scores)} separate accused entries linked into one identity "
                   f"by probabilistic record linkage, the weakest of them at "
                   f"{min(scores):.0%}. If that one entry is a different person, the "
                   f"cases it brought with it, and any associate reached only through "
                   f"those cases, come out of this answer.")
    return out


def _person_pattern_gaps(pid: str, role: str, ps: str) -> list[str]:
    """Whether this person's OTHER cases show a pattern worth knowing before relying
    on the one currently in view — never a judgement on the current case's own
    merits, only on what the rest of their record looks like."""
    try:
        cases = sql_agent.filter_viewable(sql_agent.person_record(pid), role, ps)[:10]
    except Exception:
        return []
    closed_without_conviction = 0
    for c in cases:
        rows = ds.query(
            'SELECT "cstype" FROM "ChargesheetDetails" WHERE "CaseMasterID" = :cid',
            {"cid": int(c["fir_id"])})
        if any(r.get("cstype") in ("B", "C") for r in rows):
            closed_without_conviction += 1
    if closed_without_conviction:
        return [f"{closed_without_conviction} of their other case(s) on record were "
                f"closed as false or undetected — worth checking whether this one "
                f"shares the same pattern."]
    return []


def _last_turn(session_id: str):
    """The most recent stored turn for this session, or None for a first turn.

    Backs the three meta-questions (EXPLAIN_REASONING, EVIDENCE_FOR, CASE_LOCATIONS)
    that answer from what the PREVIOUS answer showed rather than from fresh
    retrieval. A store hiccup degrades to "no prior turn" — the same "answer what
    you can, refuse rather than guess" posture the rest of this module uses.
    """
    from data import get_conversation_history
    try:
        history = get_conversation_history(session_id)
    except Exception:
        return None
    return history[-1] if history else None


def _last_substantive_turn(session_id: str, lookback: int = 6):
    """The most recent turn that actually PRODUCED a result, skipping meta-turns.

    An auditor asks in a chain — "how did you decide this?", then "could that be
    wrong?", then "what supports it?" — and every one of those is an explanation. With
    a plain "read the previous turn", the second question explained the first
    EXPLANATION rather than the result both were about, and the third explained the
    second. Measured live: "Could this be wrong?" answered "The previous answer to
    'How did you decide this?' rests on 12 items…".

    This is the same distinction `intents.META_OPERATIONS` already draws for
    `last_request`, applied to the turn being explained. Bounded, so a chain of
    meta-turns cannot walk back to an arbitrarily old part of the session; if the
    whole lookback is meta, the immediately previous turn stands, which is the honest
    fallback rather than a refusal.
    """
    def is_meta(turn) -> bool:
        # Re-classified from the turn's OWN query, not read off its result_context: a
        # meta-turn deliberately carries the prior substantive request forward under
        # `last_request` (see intents.META_OPERATIONS), so an explanation of a network
        # answer stores `operation: PERSON_NETWORK` and reads as substantive. The
        # question the officer typed is the thing that says what the turn was.
        return intents.classify(turn.query or "") in intents.META_OPERATIONS

    # The immediately previous turn wins whenever it produced something — the common
    # case, and the one every caller had before this existed.
    prior = _last_turn(session_id)
    if prior is None or not is_meta(prior):
        return prior

    from data import get_conversation_history
    try:
        history = get_conversation_history(session_id)
    except Exception:
        return prior
    for turn in reversed((history or [])[-lookback:]):
        if not is_meta(turn):
            return turn
    return prior


def _recent_person_candidates(session_id: str) -> list[str]:
    """Distinct person names the previous turn's own citations named — e.g. CASE_PEOPLE
    listing several accused without auto-resolving one to active_person. Lets a pronoun
    follow-up ask which one instead of refusing with no names to offer. Coupled to the
    exact CASE_PEOPLE content template ("{name} is accused on this case...", `accused:`
    evidence_id prefix) the same way `_fir_ids_from_turn` is coupled to the `fir:` one."""
    prior = _last_turn(session_id)
    if not prior:
        return []
    names, seen = [], set()
    for c in prior.citations:
        eid = c.get("evidence_id") or ""
        if not eid.startswith("accused:"):
            continue
        name = (c.get("label") or "").split(" is accused on this case")[0].strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _fir_ids_from_turn(prior) -> list[str]:
    """The CaseMasterIDs a stored turn put on screen.

    Two sources, because a case reaches an answer two ways. Most branches cite it
    directly under the `fir:{id}` convention (FIR_LOOKUP, CRIME_SEARCH,
    CASE_CONTEXT, SIMILAR_CASES). A TIMELINE turn cites the same case as an EVENT —
    `timeline:related_case:{person}:{date}` — whose evidence_id carries the person's
    id, not the case's; the case is on the item's `ref_id`/`source_id`.

    Reading only the first source is why "where are the related cases?" refused
    after a timeline answer that had just listed six cases in four districts by
    name (found live). A backreference has to reach whatever the previous answer
    actually showed, not only the shape of it this function happened to know.
    """
    out, seen = [], set()

    def add(fid: str) -> None:
        if fid and fid not in seen:
            seen.add(fid)
            out.append(fid)

    for c in prior.citations:
        eid = c.get("evidence_id") or ""
        if eid.startswith("fir:"):
            add(eid.split(":", 1)[1])
    for e in (prior.evidence_items or []):
        if (e.get("source_type") in ("FIR_RECORD", "CRIMINAL_RECORD")
                and str(e.get("source_id") or "").isdigit()):
            add(str(e["source_id"]))
    return out


def _recent_case_ids(session_id: str, lookback: int = 5) -> list[str]:
    """The cases the last answer that actually SHOWED cases put on screen.

    Not strictly the previous turn. A conversation interleaves substantive answers
    with meta-turns — "what supports the third event?", "why are you showing me
    these?" — and those re-show the same result rather than producing a new one. So
    "where are the related cases?" typed after one of them means the cases from the
    answer, not from the question about the answer; reading only the immediately
    previous turn refused with "the previous answer named no cases to map" while six
    cases in four districts were still on screen. Found live.

    This is the same distinction `intents.META_OPERATIONS` already draws for
    `last_request`, applied to the case list instead of to the request. Bounded, so
    a backreference can never reach an arbitrarily old part of the session.
    """
    prior = _last_turn(session_id)
    if prior:
        ids = _fir_ids_from_turn(prior)
        if ids:
            return ids                    # the immediately previous turn always wins

    from data import get_conversation_history
    try:
        history = get_conversation_history(session_id)
    except Exception:
        return []
    for turn in reversed((history or [])[-lookback:]):
        ids = _fir_ids_from_turn(turn)
        if ids:
            return ids
    return []


# How many rows a "top N" question asks for, when it says a number.
_TOP_N_RE = re.compile(r"\btop\s+(\d{1,2})\b|\b(\d{1,2})\s+most\b", re.I)


def _requested_n(query: str, default: int = 5) -> int:
    m = _TOP_N_RE.search(query or "")
    if not m:
        return default
    return max(1, min(20, int(m.group(1) or m.group(2))))


def _scope_of(state: InvestigationState) -> tuple[Optional[str], Optional[str]]:
    """(district, crime type) a statistics question is scoped to, if it names them."""
    q = state.original_query or ""
    district = state.constraints.get("district") or state.active_entities.active_location
    crime_type = state.constraints.get("crime_type") or \
        semantic_interpreter.crime_type_from_query(q)
    return district, crime_type


def _handle_offender_ranking(state: InvestigationState, out: list[EvidenceItem],
                             role: str, ps: str, t0: float) -> None:
    """'Who is the most active offender in Mandya?' — a ranking over PEOPLE.

    This is the payoff of the identity layer stated as plainly as it gets: the
    organizers' ER has no cross-case person, so "how many cases has this man been
    accused in" is a question that exists only because Fellegi-Sunter reconstructed
    him (CLAUDE.md §0). Before this branch existed the question fell to CRIME_SEARCH
    and came back as a count of every case in scope with five arbitrary FIRs under it.

    Ranked by CASE COUNT — a fact the records state — never by PageRank or RiskScore,
    which are derived and modelled and do not mean "most active". Putting a model's
    ranking under this question would be exactly the category error the console's
    provenance rails exist to prevent.
    """
    q = state.original_query or ""
    district, crime_type = _scope_of(state)
    habitual = bool(re.search(r"\bhabitual|repeat|chronic|prolific\b", q, re.I))
    n = _requested_n(q)

    people = sql_agent.ranked_offenders(role, ps, district=district,
                                        crime_type=crime_type, habitual_only=habitual,
                                        limit=n)
    scope = " · ".join(x for x in (
        crime_type, f"in {district}" if district else None,
        "recorded as habitual" if habitual else None) if x) or "within your access scope"

    if not people:
        out.append(EvidenceItem(
            evidence_id=f"ranking:none:{district or 'any'}",
            source_type="CRIMINAL_RECORD", source_id="none",
            source_query="Accused -> vx_accused_identity -> vx_person, counted per person",
            content=(f"No person on record has a case matching: {scope}. This is a "
                     f"checked absence within your access scope, not a failed search."),
            confidence=0.9, authoritative=True))
        _trace(state, "SQL Agent (offender ranking)", f"no people matched — {scope}", t0)
        return

    out.append(EvidenceItem(
        evidence_id=f"ranking:summary:{district or 'any'}",
        source_type="CRIMINAL_RECORD", source_id="summary",
        source_query="Accused -> vx_accused_identity -> vx_person, counted per person",
        content=(f"The {len(people)} people with the most cases matching {scope}, "
                 f"ranked by how many cases name them. Case count is a recorded fact; "
                 f"the ranking is over the cases you are permitted to see."),
        confidence=0.95, authoritative=True))
    for i, p in enumerate(people, start=1):
        masked = mask_person_name(role, p["name"])
        out.append(EvidenceItem(
            evidence_id=f"offender:{p['person_id']}",
            source_type="CRIMINAL_RECORD", source_id=str(p["person_id"]),
            source_query="COUNT(DISTINCT CaseMasterID) per resolved PersonUID",
            content=(f"{i}. {masked} — named as accused on {p['cases']} case(s) "
                     f"matching {scope}"
                     + (", recorded as a habitual offender" if p["habitual"] else "")
                     + (f", network community {p['community']}"
                        if p["community"] is not None else "") + "."),
            confidence=0.92, authoritative=True))
    # A person named here is the natural subject of the next question ("does she have
    # priors?"), but only when there is no ambiguity about which one — the top of a
    # ranked list is a defensible default in a way the middle of it is not.
    state.active_entities.active_person = str(people[0]["person_id"])
    state.result_context = {
        "operation": "OFFENDER_RANKING", "total_matched": len(people),
        "shown": len(people), "is_sample": False,
        "shown_ids": [p["person_id"] for p in people],
        "constraints": {"district": district, "crime_type": crime_type},
    }
    _trace(state, "SQL Agent (offender ranking)",
           f"{len(people)} person(s) ranked by case count — {scope}", t0)


# Which grouping a "which X has the most" question is asking about.
_GROUPING_RE = (
    (re.compile(r"\b(police\s+station|stations?|thana)\b", re.I), "station"),
    (re.compile(r"\bdistricts?\b", re.I), "district"),
    (re.compile(r"\b(crimes?|offences?|offenses?|types?|categor\w+)\b", re.I), "crime_type"),
    (re.compile(r"\b(status|outcome|disposal)\b", re.I), "status"),
)
_RATE_RE = re.compile(
    r"\b(conviction|acquittal|clearance|disposal|pendency|detection)\b", re.I)


def _handle_case_stats(state: InvestigationState, out: list[EvidenceItem],
                       role: str, ps: str, t0: float) -> None:
    """'What is the conviction rate in Mandya?' / 'Which station has the most pending?'

    A statistic ABOUT the case set, rather than a list of cases from it. Every one of
    these used to fall to CRIME_SEARCH and be answered with an unfiltered count.
    """
    q = state.original_query or ""
    district, crime_type = _scope_of(state)
    wants_rate = bool(_RATE_RE.search(q))
    # "Conviction rate" contains "conviction", which the status extractor reads as a
    # FILTER — and it is not one: it names the metric, not the subset. Applied, it
    # would divide convictions by convictions; merely printed, it captioned an
    # unfiltered 263 as "in Mandya · status Convicted", which is a caption that lies
    # about the number beside it. Found live on the pass's first statistics answer.
    status = None if wants_rate else semantic_interpreter.case_status_from_query(q)
    scope = " and ".join(x for x in (
        crime_type, f"in {district}" if district else None,
        f"with status {status}" if status else None) if x) \
        or "across every district in scope"

    grouping = next((g for pat, g in _GROUPING_RE if pat.search(q)), None)

    # "The most common IPC sections" is the one shape the ER cannot answer: a section
    # is attached to a crime HEAD, not to a case, so counting sections would count the
    # same head's sections once per case and read as a real frequency. Say so — and
    # then actually show the offence-type breakdown this promises, rather than falling
    # through to the status breakdown and leaving the sentence above it false.
    if re.search(r"\bsections?\b|\bipc\b|\bu/?s\b", q, re.I):
        out.append(EvidenceItem(
            evidence_id="stats:sections_unavailable",
            source_type="FIR_RECORD", source_id="none",
            source_query="CrimeHeadActSection is keyed by crime head, not by case",
            content=("These records attach IPC sections to an offence type, not to an "
                     "individual case, so there is no per-case section count to rank. "
                     "The offence-type breakdown below is the same question the records "
                     "can actually answer."),
            confidence=0.9, authoritative=True))
        grouping = "crime_type"

    # A rate is a share of the status breakdown; a ranking is a grouped count. A
    # question can ask for both ("which district has the best conviction rate") — the
    # breakdown is emitted first either way, because a rate with no denominator on
    # screen is a number an officer cannot check.
    if wants_rate or grouping in (None, "status"):
        breakdown = sql_agent.status_breakdown(role, ps, crime_type=crime_type,
                                               district=district)
        total = sum(breakdown.values())
        if not total:
            out.append(EvidenceItem(
                evidence_id="stats:none", source_type="FIR_RECORD", source_id="none",
                source_query="COUNT over CaseMaster grouped by CaseStatusName",
                content=f"No cases match {scope} within your access scope.",
                confidence=0.9, authoritative=True))
            _trace(state, "SQL Agent (case statistics)", f"no cases — {scope}", t0)
            return
        parts = "; ".join(f"{k} {v} ({v / total:.0%})"
                          for k, v in sorted(breakdown.items(), key=lambda kv: -kv[1]))
        out.append(EvidenceItem(
            evidence_id=f"stats:status:{district or 'any'}",
            source_type="FIR_RECORD", source_id="status",
            source_query="COUNT over CaseMaster grouped by CaseStatusName",
            content=(f"Of {total} case(s) matching {scope}: {parts}. These are case "
                     f"STATUSES as recorded, counted within your access scope — a "
                     f"different rank sees a different denominator."),
            confidence=0.95, authoritative=True))
        if wants_rate:
            convicted = breakdown.get("Convicted", 0)
            decided = convicted + breakdown.get("Acquitted", 0)
            out.append(EvidenceItem(
                evidence_id=f"stats:rate:{district or 'any'}",
                source_type="FIR_RECORD", source_id="rate",
                source_query="Convicted / (Convicted + Acquitted) over the same scope",
                content=(
                    (f"Conviction rate {convicted / decided:.0%} — {convicted} convicted "
                     f"of {decided} case(s) that reached a verdict. Cases still under "
                     f"investigation or chargesheeted are excluded from the denominator, "
                     f"because they have no outcome yet."
                     if decided else
                     "No case matching this scope has reached a verdict, so no "
                     "conviction rate can be computed. That is an absence of outcomes, "
                     "not a rate of zero.")),
                confidence=0.95, authoritative=True))

    if grouping and grouping != "status":
        ranked = sql_agent.counts_by(role, ps, grouping, crime_type=crime_type,
                                     district=district, case_status=status)
        label = {"district": "District", "station": "Police station",
                 "crime_type": "Offence type"}[grouping]
        n = _requested_n(q, default=5)
        if not ranked:
            out.append(EvidenceItem(
                evidence_id=f"stats:{grouping}:none", source_type="FIR_RECORD",
                source_id="none", source_query=f"COUNT grouped by {grouping}",
                content=f"No cases match {scope} within your access scope.",
                confidence=0.9, authoritative=True))
        else:
            total = sum(v for _, v in ranked)
            out.append(EvidenceItem(
                evidence_id=f"stats:{grouping}:{district or 'any'}",
                source_type="FIR_RECORD", source_id=grouping,
                source_query=f"COUNT over CaseMaster grouped by {grouping}",
                content=(f"{label} ranking, {scope}, most cases first — "
                         + "; ".join(f"{k} {v}" for k, v in ranked[:n])
                         + f". {total} case(s) counted in total, within your access "
                           f"scope."),
                confidence=0.95, authoritative=True))
    state.result_context = {
        "operation": "CASE_STATS", "total_matched": None, "shown": 0,
        "is_sample": False, "shown_ids": [],
        "constraints": {"district": district, "crime_type": crime_type},
    }
    _trace(state, "SQL Agent (case statistics)",
           f"{grouping or 'status'} statistics — {scope}", t0)


def _handle_area_profile(state: InvestigationState, out: list[EvidenceItem],
                         role: str, ps: str, t0: float) -> None:
    """'Profile of Mandya' — the recorded crime mix next to the one non-synthetic
    table in the schema: real Census 2011 socioeconomic ground truth for the same
    district. Deliberately puts the two side by side rather than combining them into
    one score: CLAUDE.md §9 already commits to auditing fairness across geography
    because that is the axis an over-policing feedback loop travels along, and a
    profile that quietly implied "poor district -> more crime" would be the causal
    claim this platform's own DoWhy layer refuses to make without naming its
    confounders. This shows the two facts; it draws no line between them.

    No finer area than District exists in this schema (the ER's own smallest
    administrative unit), so "area" here means district — the real granularity, not
    a narrower one this dataset was never given.
    """
    from data.districts import canonical_name

    district, _ = _scope_of(state)
    if not district:
        code = _district_code(state)
        district = canonical_name(code) if code else None
    if not district:
        out.append(EvidenceItem(
            evidence_id="area:none", source_type="FIR_RECORD", source_id="none",
            source_query="no district resolved", authoritative=True, confidence=0.9,
            content="No district was named and none could be inferred, so there is "
                    "no area to profile."))
        _trace(state, "SQL Agent (area profile)", "no district resolved", t0)
        return

    mix = sql_agent.counts_by(role, ps, "crime_type", district=district)
    total = sum(n for _, n in mix)
    census = sql_agent.district_socioeconomic(district)

    out.append(EvidenceItem(
        evidence_id=f"area:mix:{district}", source_type="FIR_RECORD", source_id=district,
        source_query="COUNT over CaseMaster grouped by CrimeSubHead, filtered to this district",
        confidence=0.95, authoritative=True,
        content=(f"{district}: {total} case(s) on record within your access scope. "
                 f"Offence mix, most common first — "
                 + "; ".join(f"{k} {v}" for k, v in mix[:6]) + ".")
                if mix else
                f"No cases matching {district} within your access scope."))

    if census:
        out.append(EvidenceItem(
            evidence_id=f"area:census:{district}", source_type="FIR_RECORD", source_id=district,
            source_query='SELECT ... FROM "vx_district_socioeconomic" WHERE DistrictID = ...',
            confidence=1.0, authoritative=True,
            content=(f"{district} — Census 2011: population {census['Population']:,}, "
                     f"literacy {census['LiteracyRate']:.1f}%, urban households "
                     f"{census['UrbanRatio']:.0%}, poverty index {census['PovertyIndex']:.0%}, "
                     f"youth share {census['YouthRatio']:.0%}. Real ground truth, not "
                     f"modelled — this is a socioeconomic fact ABOUT the district, not a "
                     f"claim about why its crime count is what it is.")))
    else:
        out.append(EvidenceItem(
            evidence_id=f"area:census_unavailable:{district}", source_type="FIR_RECORD",
            source_id=district, source_query="vx_district_socioeconomic lookup",
            confidence=0.9, authoritative=True,
            content=f"No Census 2011 socioeconomic row is on record for {district}."))

    state.result_context = {
        "operation": "AREA_PROFILE", "total_matched": total, "shown": len(mix),
        "is_sample": False, "shown_ids": [], "constraints": {"district": district},
    }
    _trace(state, "SQL Agent (area profile)", f"{district}: {total} case(s), "
           f"census {'found' if census else 'unavailable'}", t0)


def _handle_community_profile(state: InvestigationState, out: list[EvidenceItem],
                              role: str, ps: str, t0: float) -> None:
    """'Who is in community 28?' — a Louvain community as an investigative object, not
    just a label attached to a person elsewhere. Named "community", never "gang": the
    ER records no gang, so calling this anything else would assert a legal fact the
    records do not state (CLAUDE.md §4).

    The one thing this adds over reading a person's own GangAffiliation field is the
    GROUP view: every member ranked by network influence (never by risk — influence is
    a graph-position fact, not a threat score), plus what the group's cases actually
    have in common, so an officer can act on a whole crew at once instead of pulling
    each co-accused's record one at a time.
    """
    from data.gds import community_members

    q = state.original_query or ""
    cid = intents.community_id_from_query(q)
    if cid is None and state.active_entities.active_person:
        cid = sql_agent.person_community(state.active_entities.active_person)

    if cid is None:
        out.append(EvidenceItem(
            evidence_id="community:none", source_type="GRAPH_RELATIONSHIP",
            source_id="none", source_query="no community resolved", confidence=0.9,
            authoritative=True,
            content="No community number was named, and no person is currently in "
                    "focus to read one off. Name a community number, or ask about a "
                    "person first."))
        _trace(state, "Graph Agent (community profile)", "no community resolved", t0)
        return

    members = community_members(cid, limit=25)
    if not members:
        out.append(EvidenceItem(
            evidence_id=f"community:empty:{cid}", source_type="GRAPH_RELATIONSHIP",
            source_id=str(cid), source_query="vx_person WHERE CommunityID = :cid",
            confidence=0.9, authoritative=True,
            content=f"No person on record belongs to community {cid}."))
        _trace(state, "Graph Agent (community profile)", f"community {cid} is empty", t0)
        return

    profile = sql_agent.community_case_profile(
        [str(m["PersonUID"]) for m in members], role, ps)
    out.append(EvidenceItem(
        evidence_id=f"community:summary:{cid}", source_type="COMMUNITY_SUMMARY",
        source_id=str(cid), source_query="vx_person WHERE CommunityID = :cid",
        confidence=0.85, authoritative=False,
        content=(f"Community {cid}: {len(members)} known associate(s), derived from "
                 f"co-offending, across {profile['case_count']} distinct case(s)"
                 + (f", most often {profile['top_crime_type']}" if profile["top_crime_type"] else "")
                 + ". Membership is derived by the graph, not stated by any record — "
                   "this is not a legal designation.")))
    for i, m2 in enumerate(members, start=1):
        name = mask_person_name(role, m2["CanonicalName"])
        out.append(EvidenceItem(
            evidence_id=f"community:{m2['PersonUID']}", source_type="GRAPH_RELATIONSHIP",
            source_id=str(m2["PersonUID"]),
            source_query="vx_person WHERE CommunityID = :cid ORDER BY PageRank DESC",
            confidence=0.8, authoritative=False,
            content=f"{i}. {name} — network influence {m2['PageRank']:.3f}."))
    state.active_entities.active_person = str(members[0]["PersonUID"])
    state.result_context = {
        "operation": "COMMUNITY_PROFILE", "total_matched": len(members),
        "shown": len(members), "is_sample": False,
        "shown_ids": [str(m2["PersonUID"]) for m2 in members],
        "constraints": {"community": cid},
    }
    _trace(state, "Graph Agent (community profile)",
           f"community {cid}: {len(members)} member(s)", t0)


def _handle_watchlist(state: InvestigationState, out: list[EvidenceItem],
                      role: str, ps: str, t0: float) -> None:
    """The statewide financial watchlist — every transaction a detector has flagged,
    ranked. Distinct from FINANCIAL (a named person's own money trail): this is the
    database-wide readout OFFENDER_RANKING already established the pattern for, applied
    to the AML layer instead of the accused layer.

    Each row states WHICH detector flagged it, because CLAUDE.md §6 draws a hard line
    between the two: the rule-based structuring detector is what a court can audit line
    by line, and the GNN catches coordinated patterns the rule structurally cannot see
    but is an investigative lead, not a court-ready finding. Collapsing that distinction
    into one undifferentiated "flagged" list would erase the one thing that makes this
    list trustworthy rather than merely alarming.
    """
    flagged = sql_agent.flagged_transactions(role, ps, limit=25)
    if not flagged:
        out.append(EvidenceItem(
            evidence_id="watchlist:none", source_type="ML_PREDICTION", source_id="none",
            source_query='SELECT ... FROM "vx_txn" WHERE FlaggedSuspicious = true',
            confidence=0.9, authoritative=True,
            content="No transaction is currently flagged by either detector. This is "
                    "a checked absence, not a failed search."))
        _trace(state, "Financial Agent (watchlist)", "no flagged transactions", t0)
        return

    rule_n = sum(1 for t in flagged if "gnn" not in (t.get("Detector") or "").lower())
    out.append(EvidenceItem(
        evidence_id="watchlist:summary", source_type="ML_PREDICTION", source_id="summary",
        source_query='SELECT ... FROM "vx_txn" WHERE FlaggedSuspicious = true '
                     'ORDER BY FlagConfidence DESC',
        confidence=0.9, authoritative=True,
        content=(f"{len(flagged)} flagged transaction(s) statewide, ranked by detector "
                 f"confidence — {rule_n} from the rule-based structuring detector "
                 f"(court-auditable), {len(flagged) - rule_n} from the GNN pattern "
                 f"detector (an investigative lead, not a court-ready finding).")))
    for i, t in enumerate(flagged, start=1):
        is_gnn = "gnn" in (t.get("Detector") or "").lower()
        out.append(EvidenceItem(
            evidence_id=f"watchlist:{t['TxnID']}", source_type="ML_PREDICTION",
            source_id=str(t["TxnID"]),
            source_query="vx_txn WHERE FlaggedSuspicious = true", confidence=0.8,
            authoritative=not is_gnn,
            content=(f"{i}. Transaction {t['TxnID']}: account {t['SrcAccountID']} -> "
                     f"{t['DstAccountID']}, amount {t['Amount']}, flagged as "
                     f"{t.get('FlagType') or 'suspicious'} by "
                     f"{'the GNN pattern detector' if is_gnn else 'the rule-based structuring detector'} "
                     f"(confidence {t.get('FlagConfidence') or 0:.2f})"
                     + (f", case {t['CaseMasterID']}" if t.get("CaseMasterID") else "") + ".")))
    state.result_context = {
        "operation": "WATCHLIST", "total_matched": len(flagged), "shown": len(flagged),
        "is_sample": len(flagged) == 25, "shown_ids": [str(t["TxnID"]) for t in flagged],
        "constraints": {},
    }
    _trace(state, "Financial Agent (watchlist)",
           f"{len(flagged)} flagged transaction(s)", t0)


def _handle_station_workload(state: InvestigationState, out: list[EvidenceItem],
                             role: str, ps: str, t0: float) -> None:
    """'Which stations are falling behind?' — the question a supervisor actually asks,
    which is not "how many open cases" but "which specific cases has nobody touched".
    An IO/SHO's own scoping (`_ps_scope`) makes this double as a self-check: their own
    queue, not a statewide ranking. Every other rank sees every station, ranked by who
    needs backup most — a genuine gap in most crime-analytics demos, which stop at
    prediction and mapping and never surface where a human is failing to follow up.
    This never allocates anything itself; it only says where to look, which is exactly
    the human-in-the-loop framing CLAUDE.md §9 already commits to.
    """
    stations = sql_agent.station_workload(role, ps)
    if not stations:
        out.append(EvidenceItem(
            evidence_id="workload:none", source_type="FIR_RECORD", source_id="none",
            source_query='CaseMaster WHERE CaseStatusName = \'Under Investigation\'',
            confidence=0.9, authoritative=True,
            content="No case within your access scope is currently under investigation."))
        _trace(state, "SQL Agent (station workload)", "no open cases in scope", t0)
        return

    total_open = sum(s["open_cases"] for s in stations)
    total_stalled = sum(s["stalled_count"] for s in stations)
    out.append(EvidenceItem(
        evidence_id="workload:summary", source_type="FIR_RECORD", source_id="summary",
        source_query="CaseMaster JOIN Unit JOIN CaseStatusMaster, grouped by station",
        confidence=0.9, authoritative=True,
        content=(f"{len(stations)} station(s) in scope, {total_open} case(s) under "
                 f"investigation, {total_stalled} of them STALLED — open more than "
                 f"{sql_agent.STALE_DAYS} days with no investigation-board activity recorded. "
                 f"Ranked by stalled count, then average age.")))
    for i, s in enumerate(stations, start=1):
        out.append(EvidenceItem(
            evidence_id=f"workload:{s['ps_code']}", source_type="FIR_RECORD",
            source_id=s["ps_code"],
            source_query="CaseMaster JOIN Unit JOIN CaseStatusMaster, grouped by station",
            confidence=0.9, authoritative=True,
            content=(f"{i}. {s['station']}: {s['open_cases']} case(s) under "
                     f"investigation, average age {s['avg_age_days']} day(s), "
                     f"{s['stalled_count']} stalled.")))
        for cid in s["stalled_ids"]:
            out.append(EvidenceItem(
                evidence_id=f"stalled:{cid}", source_type="FIR_RECORD", source_id=cid,
                source_query="CaseMaster LEFT anti-join vx_case_board_item, age > "
                             f"{sql_agent.STALE_DAYS} days",
                confidence=0.85, authoritative=True,
                content=(f"Case {cid} at {s['station']} has been under investigation "
                         f"for more than {sql_agent.STALE_DAYS} days with no board activity "
                         f"recorded — nobody has pinned evidence, added a lead or left "
                         f"a note on it.")))
    state.result_context = {
        "operation": "STATION_WORKLOAD", "total_matched": len(stations),
        "shown": len(stations), "is_sample": False,
        "shown_ids": [s["ps_code"] for s in stations], "constraints": {},
    }
    _trace(state, "SQL Agent (station workload)",
           f"{len(stations)} station(s), {total_stalled} stalled case(s)", t0)


def _handle_case_locations(state: InvestigationState, t0: float) -> None:
    """'Where are those cases concentrated?' — a district tally over the FIRs the
    conversation last put on screen, re-checked against this officer's own policy
    scope before being shown (a citation from an earlier turn is not a permission)."""
    fir_ids = _recent_case_ids(state.session_id)
    if not fir_ids:
        state.refusal_reason = "nothing_prior_locations"
        _trace(state, "Orchestrator", "No previous case list to locate geographically", t0)
        return

    role, ps = state.officer_role, _officer_ps(state.officer_id)
    rows = sql_agent.filter_viewable(sql_agent.cases_by_ids(fir_ids), role, ps)
    if not rows:
        state.refusal_reason = "nothing_prior_locations"
        _trace(state, "Orchestrator",
               "The previously cited cases are no longer within policy scope", t0)
        return

    tally: dict[str, int] = {}
    for r in rows:
        d = r.get("district") or "district not recorded"
        tally[d] = tally.get(d, 0) + 1
    breakdown = "; ".join(f"{d} ({n})" for d, n in sorted(tally.items(), key=lambda kv: -kv[1]))

    state.sql_query_results += rows
    state.evidence_items = [EvidenceItem(
        evidence_id="case_locations:summary", source_type="GEOSPATIAL_ANALYSIS",
        source_id="none", source_query="district tally over the previously cited case list",
        content=f"The {len(rows)} case(s) from the previous answer are concentrated in: "
                f"{breakdown}.",
        confidence=0.9, authoritative=True)]
    _trace(state, "SQL Agent (case locations)",
           f"{len(rows)} case(s) tallied across {len(tally)} district(s)", t0)


# The row id field "only these?" dedupes and widens on, per producing operation.
# Everything not listed here is FIR-shaped (the original CRIME_SEARCH/SIMILAR_CASES
# behaviour); PERSON_NETWORK/ALIAS_CHECK/OFFENDER_RANKING rows are people.
_RESULT_ID_FIELD = {"PERSON_NETWORK": "person_id", "ALIAS_CHECK": "person_id",
                    "OFFENDER_RANKING": "person_id"}


def _more_result_evidence(op: str, r: dict, role: str = "") -> EvidenceItem:
    if op == "SIMILAR_CASES":
        return EvidenceItem(
            evidence_id=f"fir:{r['fir_id']}", source_type="FIR_RECORD",
            source_id=str(r["fir_id"]),
            source_query="hybrid_search over fir_narrative, ranked by structured overlap "
                         "— continuation of a previous 'only these?' follow-up",
            content=f"{_fir_content(r)} Similar because: {r['explanation']}.",
            confidence=float(r["similarity"]), confidence_kind="similarity")
    if op == "PERSON_NETWORK":
        return _network_evidence(r)
    if op == "ALIAS_CHECK":
        return EvidenceItem(
            evidence_id=f"same_as:{r['person_id']}", source_type="GRAPH_RELATIONSHIP",
            source_id=str(r["person_id"]),
                     source_query="vx_accused_identity — duplicate-identity check "
                     "(probabilistic record linkage) — continuation of a previous "
                     "'only these?' follow-up",
            content=(f"Record for '{r['name_en']}' was linked to this person by "
                     f"probabilistic record linkage (confidence {r['confidence']:.2f}) — "
                     f"the same individual recorded under a different spelling."),
            confidence=float(r["confidence"]))
    if op == "OFFENDER_RANKING":
        masked = mask_person_name(role, r["name"])
        return EvidenceItem(
            evidence_id=f"offender:{r['person_id']}", source_type="CRIMINAL_RECORD",
            source_id=str(r["person_id"]),
            source_query="COUNT(DISTINCT CaseMasterID) per resolved PersonUID"
                         " — continuation of a previous 'only these?' follow-up",
            content=(f"{masked} — named as accused on {r['cases']} case(s)"
                     + (", recorded as a habitual offender" if r["habitual"] else "")
                     + (f", network community {r['community']}"
                        if r["community"] is not None else "") + "."),
            confidence=0.92, authoritative=True)
    return EvidenceItem(
        evidence_id=f"fir:{r['fir_id']}", source_type="FIR_RECORD", source_id=r["fir_id"],
        source_query="SELECT ... continuation of a previous 'only these?' follow-up",
        content=_fir_content(r), confidence=0.9)


def _handle_more_results(state: InvestigationState, t0: float) -> None:
    """'Only these?' / 'are there more?' — reads the PREVIOUS turn's own recorded
    result_context and answers from that real fact, never a fresh unscoped search.
    Generalizes _handle_case_locations' own "read the previous turn, not a new
    query" discipline to any bounded/sampled result, not just a location tally."""
    prior = _last_turn(state.session_id)
    rc = (prior.result_context if prior else None) or {}
    op = rc.get("operation")
    total = rc.get("total_matched")
    shown = rc.get("shown", 0)
    shown_ids = {str(i) for i in (rc.get("shown_ids") or [])}

    if not op:
        state.refusal_reason = "nothing_prior_results"
        _trace(state, "Orchestrator", "No previous bounded result set to check", t0)
        return

    if not rc.get("is_sample"):
        # Already exhaustive — the honest answer is "no, that was everything".
        # result_context carries forward unchanged, so a SECOND "only these?" (or
        # "same thing for Mysuru") after this one still has a real fact to read.
        state.result_context = rc
        state.evidence_items = [EvidenceItem(
            evidence_id="result_followup:exhaustive", source_type="FIR_RECORD",
            source_id="none", source_query="re-read of the previous turn's own result_context",
            content=(f"That was the complete result — "
                     f"{total if total is not None else shown} record(s) total, "
                     f"all of them already shown."),
            confidence=0.95, authoritative=True)]
        _trace(state, "Orchestrator (result-set follow-up)",
               "Previous result was already exhaustive", t0)
        return

    # A genuine sample — re-run the SAME producer with a wider limit and report only
    # the records not already shown, rather than re-showing the same five.
    role, ps = state.officer_role, _officer_ps(state.officer_id)
    con = rc.get("constraints", {})
    wider: list[dict] = []
    if op == "CRIME_SEARCH":
        # Every filter the original search applied, not just the two this used to
        # carry: widening a status- or section-scoped search without them returns
        # cases the first answer correctly excluded, presented as "here are more".
        wider = sql_agent.search_firs(
            role, ps, limit=10, crime_type=con.get("crime_type"),
            district=con.get("district"), case_status=con.get("case_status"),
            section=con.get("section"), ps_code=con.get("ps_code"))
    elif op == "SIMILAR_CASES" and state.active_entities.active_fir:
        case_rows = sql_agent.fir_by_id(state.active_entities.active_fir, role, ps)
        if case_rows:
            wider = copilot_brief.similar_cases_for(case_rows[0], limit=10)
    elif op == "PERSON_NETWORK" and state.active_entities.active_person:
        # The graph traversal itself is already bounded (person_network caps at 40)
        # — "wider" here means "the rest of that same bounded set", not a deeper
        # walk, so re-running it costs one graph read, not a new search.
        wider = graph_agent.person_network(state.active_entities.active_person, role)
    elif op == "ALIAS_CHECK" and state.active_entities.active_person:
        wider = graph_agent.aliases(state.active_entities.active_person)
    elif op == "OFFENDER_RANKING":
        wider = sql_agent.ranked_offenders(
            role, ps, district=con.get("district"), crime_type=con.get("crime_type"),
            limit=total or 40)
    id_field = _RESULT_ID_FIELD.get(op, "fir_id")
    more_rows = [r for r in wider if str(r.get(id_field)) not in shown_ids][:5]

    if not more_rows:
        # Widening found nothing new -- effectively exhaustive now, so record it as
        # such rather than leaving is_sample=True to invite an identical re-check.
        state.result_context = {**rc, "is_sample": False}
        state.evidence_items = [EvidenceItem(
            evidence_id="result_followup:no_more", source_type="FIR_RECORD",
            source_id="none", source_query="re-read of the previous turn's own result_context",
            content=(f"{shown} of {total if total is not None else 'an unrecorded total'} "
                     f"were shown before; no further distinct records were found beyond "
                     f"those within your access scope."),
            confidence=0.8, authoritative=True)]
        _trace(state, "Orchestrator (result-set follow-up)",
               "Widened search found nothing beyond what was already shown", t0)
        return

    if id_field == "fir_id":
        state.sql_query_results += more_rows
    new_shown_ids = list(shown_ids) + [str(r.get(id_field)) for r in more_rows]
    state.result_context = {
        **rc, "shown": len(new_shown_ids), "shown_ids": new_shown_ids,
        "is_sample": (total is None) or (total > len(new_shown_ids)),
    }
    summary = EvidenceItem(
        evidence_id="result_followup:summary", source_type="FIR_RECORD", source_id="none",
        source_query="re-read of the previous turn's own result_context",
        content=(f"{total if total is not None else f'more than {shown}'} record(s) matched "
                 f"in total; {shown} were shown before — here are {len(more_rows)} more."),
        confidence=0.9, authoritative=True)
    state.evidence_items = [summary] + [_more_result_evidence(op, r, role) for r in more_rows]
    _trace(state, "Orchestrator (result-set follow-up)",
           f"{len(more_rows)} additional record(s) beyond the {shown} already shown", t0)


# Below this, two names are unrelated enough that pointing out they resolved to
# different people would be stating the obvious rather than auditing a real judgment
# call. Above it, an officer plausibly typed the two names BECAUSE they looked like
# the same person, which is exactly when Veritas's own identity-resolution decision
# is worth showing rather than leaving implicit.
_NAME_SIMILARITY_FLOOR = 0.55


def _comparison_identity_check(person_ids: list[str], names: list[str]) -> list[EvidenceItem]:
    """Compare Mode's one addition beyond running the same single-subject retrieval
    twice: when the two compared names are near-duplicates, say what Veritas's own
    Fellegi-Sunter identity resolution (CLAUDE.md §0) DID about that. This is the
    platform's headline claim made auditable rather than merely asserted — "did the
    record linkage get this right?" for the exact romanisation-variant case §0 exists
    to solve (BUG-026: 'Suma Nadkarni' on the file, 'Soom Nadkarni' everywhere derived).

    Deliberately narrow: only fires for exactly two person subjects with genuinely
    similar names, so an unrelated two-person comparison ("compare Usha Naika and
    Ravi Kumar's case histories") is not cluttered with a resolution note that has
    nothing to audit.
    """
    if len(person_ids) != 2 or person_ids[0] == person_ids[1]:
        return []
    a, b = names
    if not a or not b:
        return []
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    if ratio < _NAME_SIMILARITY_FLOOR:
        return []
    return [EvidenceItem(
        evidence_id=f"idcheck:{person_ids[0]}:{person_ids[1]}",
        source_type="CRIMINAL_RECORD", source_id=f"{person_ids[0]}:{person_ids[1]}",
        source_query="vx_accused_identity — two PersonUIDs compared for name similarity",
        confidence=round(ratio, 2), confidence_kind="similarity", authoritative=True,
        content=(f"'{a}' and '{b}' are similarly spelled ({ratio:.0%} text match), but "
                 f"identity resolution kept them as two SEPARATE people (PersonUID "
                 f"{person_ids[0]} and {person_ids[1]}) — nothing in the records links "
                 f"them as one person under two spellings. If you believe this is the "
                 f"same individual, that is a record-linkage judgment call to raise, "
                 f"not something these records currently support."))]


def _handle_comparison(state: InvestigationState, widen: bool, t0: float) -> None:
    """Bounded deterministic multi-step composition (design spec §3): 'check
    whether either of those people had a prior case in Bengaluru around the same
    time'. Sequences the EXISTING single-subject retrieval path (HippoRAG +
    _run_specialists) once per compared subject — each call is fully RBAC'd the
    same way any ordinary turn is (role/station scoping is baked into every
    specialist call, not bypassed here), and the merged evidence still passes
    through the SAME CRAG evaluator node right after this function returns.

    NOT a general N-step planner, and not claimed to be one: it is bounded to
    exactly the two-entity comparison the interpreter detected
    (semantic_interpreter._COORDINATION_RE), evaluates the merged evidence as one
    CRAG batch rather than accepting/rejecting each subject independently, and
    does not filter a subject's full history down to just the named constraint
    (e.g. "in Bengaluru") — the constraint shows up in each cited record's own
    content, the same honest, unfiltered PERSON_HISTORY answer a single-subject
    turn already gives. Open-ended multi-clause planning needs the LLM path
    (ENGINEERING_BRIEF.md §12), which can extend or replace this exact seam
    without touching retrieval, RBAC, CRAG or synthesis."""
    original_pid = state.active_entities.active_person
    all_evidence: list[EvidenceItem] = []
    labels: list[str] = []
    ids: list[str] = []
    for pid in state.comparison_subject_ids:
        name = sql_agent.person_name(pid) or f"person {pid}"
        labels.append(name)
        ids.append(pid)
        state.active_entities.active_person = pid
        sub_evidence: list[EvidenceItem] = []
        rows, ev = hipporag.retrieve([name], top_k=15)
        state.graph_query_results += rows
        sub_evidence += ev
        sub_evidence += _run_specialists(state, widen)
        all_evidence += [e.model_copy(update={
            "evidence_id": f"{e.evidence_id}#cmp:{pid}",
            "content": f"[{name}] {e.content}",
        }) for e in sub_evidence]
    all_evidence += _comparison_identity_check(ids, labels)
    state.active_entities.active_person = original_pid
    state.evidence_items = _dedupe(state.evidence_items + all_evidence)
    _trace(state, "Orchestrator (bounded comparison)",
           f"Compared {len(state.comparison_subject_ids)} subject(s): "
           f"{', '.join(labels)} — {len(all_evidence)} evidence item(s) total", t0)


# Bound on how many entities a fan_out plan step will actually run — see _run_plan.
# "which of them appear in other cases" over a PERSON_NETWORK result genuinely could
# mean dozens of associates; running a full retrieval pass per associate is the same
# cost/latency tradeoff TOG_CONFIDENCE_FLOOR and _run_specialists' own top_k caps
# already make elsewhere, applied to the same problem one layer up.
_MAX_FAN_OUT = 5


def _resolve_step_position(state: InvestigationState, position: int
                           ) -> Optional[tuple[str, str]]:
    """(kind, id_or_name) for a plan step's 'position' reference — the Nth citation
    from the PREVIOUS turn, via the exact resolution semantic_interpreter's own
    single-turn ordinal follow-up already uses for 'the second one'."""
    prior = _last_turn(state.session_id)
    if not prior:
        return None
    for c in prior.citations:
        if c.get("index") == position:
            return semantic_interpreter._citation_subject(c)
    return None


def _run_plan(state: InvestigationState, widen: bool, t0: float) -> None:
    """Execute a general N-step investigation plan (semantic_interpreter's LLM
    path — see SemanticRequest.plan_steps). Each step reuses the EXACT same
    per-operation retrieval every ordinary turn already uses (_run_specialists) —
    a plan only sequences and chains subjects across calls to it; it never adds a
    new way to reach the record layer, and every step's own operation is still
    the one validated against intents.ALL_OPERATIONS before this ever runs.

    Three ways a step names its subject, checked in this order:
      1. depends_on_step — reuse (or fan out over) an EARLIER step's own
         resolved subject(s): 'go deeper on the second person', 'which of them
         appear in other cases'. fan_out sources up to _MAX_FAN_OUT entities from
         the referenced step's own graph_query_results delta (e.g. PERSON_
         NETWORK's associates); without fan_out, reuses that step's one subject.
      2. position — the Nth item in the PREVIOUS TURN's own citation list
         ('compare the first and third').
      3. subject_text/subject_id, resolved by semantic_interpreter at
         interpretation time exactly like an ordinary single-op turn.

    Any step that cannot safely resolve a subject (an unresolved dependency, a
    position with nothing at that index, or a tied name search) stops the WHOLE
    plan with a clarification rather than guessing or silently skipping that
    step — the same "ask, don't guess" discipline _resolve_subject_from_open_case
    and the ambiguous-name check elsewhere in this module already apply. A
    partially-answered multi-step question with no indication which step failed
    would be a worse outcome than an honest refusal.
    """
    original_pid = state.active_entities.active_person
    original_fir = state.active_entities.active_fir
    original_location = state.active_entities.active_location
    original_constraints = dict(state.constraints)

    step_subject_ids: dict[int, Optional[str]] = {}
    step_person_pool: dict[int, list[str]] = {}
    all_evidence: list[EvidenceItem] = []
    labels: list[str] = []

    for i, step in enumerate(state.plan_steps, start=1):
        step_label = step.get("subject_text") or ""
        depends_on = step.get("depends_on_step")
        position = step.get("position")
        # None (not [None]) is the "this step names no subject of its own" sentinel
        # -- resolved below to whatever is CURRENTLY in focus, exactly like an
        # ordinary single-op turn reads state.active_entities.active_person
        # unchanged. A step that explicitly resolves to "no one" (a district-only
        # HOTSPOT/FORECAST/CRIME_SEARCH step) sets subject_ids = [None] itself, and
        # that None must NOT be reinterpreted as "fall back to focus" below.
        subject_ids: Optional[list[Optional[str]]] = None

        if depends_on is not None:
            if depends_on not in step_subject_ids:
                state.refusal_reason = "plan_step_unresolved"
                _trace(state, "Orchestrator (multi-step plan)",
                       f"Step {i} depends on step {depends_on}, which resolved no "
                       f"usable subject", t0)
                return
            if step.get("fan_out"):
                subject_ids = step_person_pool.get(depends_on, [])[:_MAX_FAN_OUT]
                if not subject_ids:
                    state.refusal_reason = "plan_step_unresolved"
                    _trace(state, "Orchestrator (multi-step plan)",
                           f"Step {i} fans out over step {depends_on}'s results, "
                           f"which found no entities to fan out over", t0)
                    return
            else:
                subject_ids = [step_subject_ids[depends_on]]
        elif position is not None:
            resolved = _resolve_step_position(state, position)
            if not resolved:
                state.refusal_reason = "plan_step_unresolved"
                _trace(state, "Orchestrator (multi-step plan)",
                       f"Step {i} refers to position {position} in the previous "
                       f"answer, which has no citation there", t0)
                return
            kind, ident = resolved
            if kind == "person_name":
                pid_i, ambiguous = semantic_interpreter._resolve_person_by_text(ident)
                if ambiguous:
                    state.refusal_reason = "ambiguous_person"
                    state.ambiguous_candidates = ambiguous
                    _trace(state, "Orchestrator (multi-step plan)",
                           f"Step {i}'s position reference names {len(ambiguous)} "
                           f"equally-matching people", t0)
                    return
                subject_ids = [pid_i]
                step_label = ident
            elif kind == "person":
                subject_ids = [ident]
            elif kind == "case":
                state.active_entities.active_fir = ident
        elif step.get("ambiguous_candidates"):
            state.refusal_reason = "ambiguous_person"
            state.ambiguous_candidates = step["ambiguous_candidates"]
            _trace(state, "Orchestrator (multi-step plan)",
                   f"Step {i} names {len(step['ambiguous_candidates'])} equally-"
                   f"matching people", t0)
            return
        elif step.get("subject_id"):
            subject_ids = [step["subject_id"]]

        if subject_ids is None:
            # Named no subject of its own — use whatever is CURRENTLY in focus
            # (the pre-plan focus for step 1, or unchanged from a prior step),
            # exactly like an ordinary single-op turn. Must not be confused with
            # a step that resolved TO "no one" (a district-only HOTSPOT/FORECAST/
            # CRIME_SEARCH step already produces its own [None] above via the
            # depends_on/position branches when applicable).
            subject_ids = [state.active_entities.active_person]

        step_constraints = dict(original_constraints)
        step_constraints.update(step.get("constraints") or {})
        if step.get("subject_type") == "location" and step_label:
            step_constraints.setdefault("district", step_label)

        found_person_ids: list[str] = []
        for sid in subject_ids:
            state.intent = step["operation"]
            state.constraints = step_constraints
            if step.get("subject_type") != "case":
                state.active_entities.active_person = sid
            before = len(state.graph_query_results)

            sub_evidence: list[EvidenceItem] = []
            if sid:
                rows, ev = hipporag.retrieve([step_label or (_person_name(sid) or "")],
                                             top_k=15)
                state.graph_query_results += rows
                sub_evidence += ev
            sub_evidence += _run_specialists(state, widen)

            found_person_ids += [str(r["person_id"]) for r in state.graph_query_results[before:]
                                 if "person_id" in r]
            name = _person_name(sid) if sid else None
            prefix = f"[Step {i}: {step['operation']}" + (f" — {name}" if name else "") + "]"
            all_evidence += [e.model_copy(update={
                "evidence_id": f"{e.evidence_id}#plan:{i}:{sid or 'none'}",
                "content": f"{prefix} {e.content}",
            }) for e in sub_evidence]
            if name:
                labels.append(name)

        step_subject_ids[i] = subject_ids[0] if subject_ids else None
        step_person_pool[i] = list(dict.fromkeys(found_person_ids))[:_MAX_FAN_OUT]

    state.active_entities.active_person = original_pid
    state.active_entities.active_fir = original_fir
    state.active_entities.active_location = original_location
    state.constraints = original_constraints
    # A stable marker for synthesis/visualization, distinct from any single step's
    # own operation — see intents.NEEDS_NARRATIVE_SYNTHESIS, which includes it so
    # QuickML weaves the steps together instead of the extractive template
    # rendering them as an unconnected list of per-step facts.
    state.intent = "INVESTIGATION_PLAN"
    state.evidence_items = _dedupe(state.evidence_items + all_evidence)
    _trace(state, "Orchestrator (multi-step plan)",
           f"Executed {len(state.plan_steps)} step(s)"
           + (f": {', '.join(labels)}" if labels else "")
           + f" — {len(all_evidence)} evidence item(s) total", t0)


_TIMELINE_BEFORE_RE = re.compile(r"\bbefore\b", re.I)
_TIMELINE_AFTER_RE = re.compile(r"\bafter\b", re.I)


def _timeline_subject(state: InvestigationState) -> tuple[Optional[str], Optional[str]]:
    """(anchor kind, id) to build the timeline around. A resolved PERSON takes
    priority over an open case — "what happened around the time HE was involved"
    names a person even on a turn where a case also happens to be open — and falls
    back to the open case otherwise (the ordinary "show me the timeline" case)."""
    pid = state.active_entities.active_person
    if pid:
        return "person", pid
    fir_id = state.active_entities.active_fir
    if fir_id:
        return "case", fir_id
    return None, None


def _timeline_evidence(e: dict) -> EvidenceItem:
    label = "(derived — inferred from resolved identity) " if e["kind"] == "derived" else ""
    return EvidenceItem(
        evidence_id=f"timeline:{e['event_type']}:{e['entity_id']}:{e['date']}",
        source_type="GRAPH_RELATIONSHIP" if e["entity_type"] == "transaction" else
                    ("CRIMINAL_RECORD" if e["kind"] == "derived" else "FIR_RECORD"),
        source_id=e.get("ref_id") or e.get("entity_id") or "",
        source_query=e.get("source_query"),
        content=f"{label}{e['date'][:10]}: {e['description']}",
        confidence=0.9 if e["kind"] == "authoritative" else 0.6,
        authoritative=e["kind"] == "authoritative",
        timestamp=ds.to_dt(e["date"]) or datetime.utcnow(),
    )


def _timeline_anchor_date(state: InvestigationState, fallback: Optional[str]) -> Optional[str]:
    """The date "before"/"after" is relative to — the timeline event the console had
    selected (active_evidence_id, the same field 'pin this' already reads) if one
    was, else the anchor case/person's own earliest event."""
    if state.active_evidence_id:
        prior = _last_turn(state.session_id)
        if prior:
            for e in prior.evidence_items:
                if e.get("evidence_id") == state.active_evidence_id:
                    ts = e.get("timestamp")
                    if ts:
                        return str(ts)
    return fallback


def _handle_timeline(state: InvestigationState, t0: float) -> None:
    role, ps = state.officer_role, _officer_ps(state.officer_id)
    kind, subject_id = _timeline_subject(state)
    if not subject_id:
        state.refusal_reason = "no_timeline_subject"
        _trace(state, "Timeline", "No case or person in view to build a timeline for", t0)
        return

    try:
        result = (timeline_agent.person_timeline(subject_id, role, ps) if kind == "person"
                 else timeline_agent.case_timeline(subject_id, role, ps))
    except KeyError:
        state.refusal_reason = "board_not_found"
        _trace(state, "Timeline", "Subject not found", t0)
        return
    except timeline_agent.NotPermitted:
        state.refusal_reason = "board_forbidden"
        _trace(state, "Timeline", "Outside this officer's station scope", t0)
        return

    events = result["events"]
    query = state.original_query or ""
    anchor = _timeline_anchor_date(state, events[0]["date"] if events else None)
    if anchor and _TIMELINE_BEFORE_RE.search(query):
        events = [e for e in events if e["date"] < anchor]
    elif anchor and _TIMELINE_AFTER_RE.search(query):
        events = [e for e in events if e["date"] > anchor]

    state.prediction_results["timeline"] = {**result, "events": events}
    if not events:
        state.evidence_items.append(EvidenceItem(
            evidence_id=f"timeline:{kind}:{subject_id}:none", source_type="FIR_RECORD",
            source_id=subject_id,
            source_query="cross-entity timeline over dated case/arrest/chargesheet/financial records",
            content="No dated events fall within this timeline and access scope.",
            confidence=0.9, authoritative=True))
        _trace(state, "Timeline", "No dated events found", t0)
        return

    state.evidence_items += [_timeline_evidence(e) for e in events]
    _trace(state, "Timeline",
           f"{len(events)} event(s) across {len(result['entities'])} entit(y/ies)", t0)


def _connection_targets(state: InvestigationState) -> list[tuple[str, str]]:
    """Up to two (name, person_id) pairs for a TIMELINE_CONNECTION turn. Prefers
    people named IN this query; falls back to the previous turn's own citations
    (the same source RAG-34's pronoun clarification reads) so "both of them" after
    a CASE_PEOPLE turn resolves without re-typing names. Deliberately takes the
    first two candidates rather than asking which two — with exactly the two people
    a prior CASE_PEOPLE turn just named, that IS "both of them"."""
    from data.nlp import ner_extract
    entities = ner_extract(state.original_query or "", "en")
    named = [e.text for e in entities if e.label == "PERSON"]
    pool = named or _recent_person_candidates(state.session_id)

    resolved: list[tuple[str, str]] = []
    seen_ids = set()
    for n in pool:
        hits = sql_agent.person_by_name(n)
        if not hits or hits[0]["person_id"] in seen_ids:
            continue
        seen_ids.add(hits[0]["person_id"])
        resolved.append((hits[0]["name_en"], hits[0]["person_id"]))
        if len(resolved) == 2:
            break
    return resolved


def _handle_timeline_connection(state: InvestigationState, t0: float) -> None:
    role = state.officer_role
    targets = _connection_targets(state)
    if len(targets) < 2:
        state.refusal_reason = "timeline_connection_no_subjects"
        _trace(state, "Timeline",
               "Fewer than two people in view to compare — name two, or ask this "
               "right after I list several people on a case", t0)
        return

    (name_a, pid_a), (name_b, pid_b) = targets
    masked_a, masked_b = mask_person_name(role, name_a), mask_person_name(role, name_b)
    conn = timeline_agent.connection_between(pid_a, masked_a, pid_b, masked_b)

    if conn["direct"]:
        content = " ".join(d["description"] for d in conn["direct"])
        state.evidence_items.append(EvidenceItem(
            evidence_id=f"connection:{pid_a}:{pid_b}", source_type="GRAPH_RELATIONSHIP",
            source_id=pid_b,
            source_query="graph co-accused / shared-case / financial-transfer check "
                         "between two resolved people",
            content=content, confidence=0.95, authoritative=True))
    else:
        state.evidence_items.append(EvidenceItem(
            evidence_id=f"connection:{pid_a}:{pid_b}:none", source_type="GRAPH_RELATIONSHIP",
            source_id=pid_b,
            source_query="graph co-accused / shared-case / financial-transfer check "
                         "between two resolved people",
            content=(f"No recorded connection (shared case, co-accused record, or "
                     f"financial transfer) links {masked_a} and {masked_b}. Any events "
                     f"involving them that fall near each other in time are not, on "
                     f"that basis alone, reported as connected — temporal proximity is "
                     f"not evidence of a relationship."),
            confidence=0.9, authoritative=True))

    # Attach both people's merged, chronological timeline as the visualization, so
    # "show me events involving both of them" actually shows the events, not just
    # the yes/no connection statement above.
    events: list[dict] = []
    for pid, name in ((pid_a, masked_a), (pid_b, masked_b)):
        t = timeline_agent.person_timeline(pid, role, _officer_ps(state.officer_id))
        events += t["events"]
    events.sort(key=lambda e: e["date"])
    state.prediction_results["timeline"] = {
        "anchor": "connection",
        "entities": [{"entity_type": "person", "entity_id": pid_a, "entity_name": masked_a},
                    {"entity_type": "person", "entity_id": pid_b, "entity_name": masked_b}],
        "events": events, "total": len(events),
        "connection": conn,
    }
    state.evidence_items += [_timeline_evidence(e) for e in events]
    _trace(state, "Timeline (connection)",
           f"{'direct connection found' if conn['direct'] else 'no direct connection'} "
           f"between {masked_a} and {masked_b}; {len(events)} merged event(s)", t0)


def _prior_operation(prior) -> str:
    """Which operation produced the previous answer.

    `result_context` carries it for every bounded/sampled producer; for everything
    else the chat router merges `last_request` in under its own key (see
    InvestigationState.last_request). Reading both means an explanation of a FIR
    lookup knows it was a lookup, not just that a FIR is on screen."""
    rc = (prior.result_context if prior else None) or {}
    return rc.get("operation") or (rc.get("last_request") or {}).get("operation") or ""


# The demonstratives an officer uses to point at ONE item on screen, mapped to the
# evidence_id prefix that kind of item is written under (the convention every
# producing branch in this module already follows). "Why is this PERSON connected"
# and "why is this CASE in the timeline" are questions about different rows of the
# same answer, and the noun is the only thing that says which.
_TARGET_NOUNS = {
    "person": ("assoc", "same_as"), "people": ("assoc",), "associate": ("assoc",),
    "suspect": ("assoc",), "accused": ("assoc",), "connection": ("assoc",),
    "case": ("fir",), "fir": ("fir",), "record": ("fir",),
    "event": ("timeline",), "timeline": ("timeline",),
    "hotspot": ("hotspot",), "cluster": ("hotspot",), "area": ("hotspot",),
    "transfer": ("flow",), "payment": ("flow",), "money": ("flow",),
    "account": ("flow",), "trail": ("flow",),
    "forecast": ("forecast",), "projection": ("forecast",), "trend": ("forecast",),
    "score": ("risk", "recidivism"), "risk": ("risk", "recidivism"),
    "flag": ("aml",), "alias": ("same_as",), "spelling": ("same_as",),
}
# "a"/"an" belong here alongside the demonstratives: "why is that A hotspot" is the
# way the question is actually asked, and it is unambiguous inside an explanation
# turn — the only thing an explanation can be about is the answer already on screen.
# Found live: that exact phrasing matched no noun at all and fell to the whole-set
# branch, which then reported the previous answer as having nothing to explain.
_TARGET_NOUN_RE = re.compile(
    r"\b(?:this|that|the|a|an)\s+(" + "|".join(sorted(_TARGET_NOUNS)) + r")\b", re.I)


def _explain_pool(prior) -> list[dict]:
    """The previous turn's items, or its citations standing in for them.

    A turn too large for the Data Store's text column sheds `evidence_items` and
    keeps `citations` (sessions._pack). The evidence_id is on both, and it is the
    only field provenance dispatch actually needs — so an answer big enough to be
    truncated must not become an answer that cannot be explained. Found live on a
    9-citation hotspot answer, which reported itself as having no records at all."""
    pool = list(prior.evidence_items or [])
    if pool:
        return pool
    return [{"evidence_id": c.get("evidence_id"), "content": c.get("label")}
            for c in (prior.citations or []) if c.get("evidence_id")]


def _explain_target(prior, state: InvestigationState) -> Optional[dict]:
    """Which single item the officer is asking about, or None for the whole set.

    Three ways of pointing, in the order they beat each other:

      1. a CLICK — `active_evidence_id`, the same field "pin this" already reads, so
         selecting a graph node or a map case and typing "why is this connected"
         explains that node and not whichever item happened to be cited first;
      2. an ORDINAL — "what supports the third event", resolved against the previous
         turn's own citation list (`semantic_interpreter._ordinal_index` is the same
         resolver the ordinal-reference follow-ups already use);
      3. a NOUN — "why is this PERSON connected", matched to the evidence_id prefix
         that kind of item is written under.

    Nothing matching means the question is about the answer as a whole, which is a
    different and equally real question ("how are you deriving all these?").
    """
    pool = _explain_pool(prior)
    if not pool:
        return None

    target = state.active_evidence_id
    if target:
        hit = next((e for e in pool if e.get("evidence_id") == target), None)
        if hit:
            return hit

    idx = semantic_interpreter._ordinal_index(state.original_query or "")
    if idx and 1 <= idx <= len(pool):
        return pool[idx - 1]

    m = _TARGET_NOUN_RE.search(state.original_query or "")
    if m:
        prefixes = _TARGET_NOUNS[m.group(1).lower()]
        hit = next((e for e in pool
                    if (e.get("evidence_id") or "").split(":", 1)[0] in prefixes), None)
        if hit:
            return hit
    return None


def _reasoning_explanation(prior, state: InvestigationState) -> str:
    """'Why is this here?' — the provenance chain behind the result, not the pipeline.

    This used to answer by restating the agent trace: *"HippoRAG retrieval:
    Personalized PageRank from 15 seeded nodes; Cypher Agent: 12 associate(s) within
    policy depth"*. Every word of that was true and none of it was what was asked.
    An officer asking why two people are connected wants the FIRs they are both named
    on. See rag_agent/provenance.py for the shape of the answer and why it is derived
    on demand rather than stored.

    The trace has not gone anywhere — it is one click away in the Reasoning Trace
    panel, where opening it is a deliberate act.
    """
    role, ps = state.officer_role, _officer_ps(state.officer_id)
    op = _prior_operation(prior)
    subject = state.active_entities.active_person

    item = _explain_target(prior, state)
    if item is not None:
        d = provenance.explain(item, role=role, ps=ps, operation=op, subject_id=subject)
        return provenance.as_text(d)

    # No single item was pointed at — the question is about the answer as a whole.
    pool = _explain_pool(prior)
    if not pool:
        return (f'The previous answer to "{prior.query}" carried no records to explain — '
                f"it was either a refusal or a description of this tool itself.")

    # A short answer gets every item explained; a long one gets each KIND explained
    # once, since items sharing an evidence_id prefix share a derivation. The cutoff
    # is where repetition stops being thoroughness: explaining nine near-identical
    # hotspot clusters one by one is nine copies of the same paragraph, but
    # explaining only the first of two named people reads as having answered about
    # one of them and forgotten the other — which is what it did, found live.
    if len(pool) <= _EXPLAIN_EACH_UPTO:
        chosen, grouped = pool, False
    else:
        by_kind: dict[str, dict] = {}
        for e in pool:
            by_kind.setdefault((e.get("evidence_id") or "").split(":", 1)[0], e)
        chosen, grouped = list(by_kind.values()), True

    head = f'The previous answer to "{prior.query}" rests on {len(pool)} item(s)'
    if grouped:
        head += (f", of {len(chosen)} kind(s). One of each kind is traced below; items "
                 f"of the same kind were arrived at the same way.")
    else:
        head += ", each traced below."
    lines = [head, ""]
    for i, e in enumerate(chosen):
        d = provenance.explain(e, role=role, ps=ps, operation=op, subject_id=subject)
        if i:
            lines.append("")
        lines.append(provenance.as_text(d))

    truth = provenance.describe_result_set((prior.result_context or {}))
    if truth:
        lines += ["", truth]
    # The same "(s)" convention the synthesis path resolves — an explanation is prose
    # an officer reads, and a form field in the middle of it is no better here.
    from data.nlp.translate import resolve_plural_markers
    return resolve_plural_markers("\n".join(lines))


# Above this many items, explain one per KIND rather than one per item.
_EXPLAIN_EACH_UPTO = 3


def _evidence_explanation(prior, state: InvestigationState) -> str:
    """'What supports this?' — the records under the claim, and how strongly.

    Where the question points at ONE item ("what supports the third event"), that
    item's own source records are named; otherwise the whole citation list is
    restated. Either way it reads from the previous turn rather than re-running
    retrieval, which would search the index for the literal words "what supports
    this" and answer from whatever it found.
    """
    if not prior.citations and not prior.evidence_items:
        return (f'The previous answer to "{prior.query}" carried no citations — it was '
                f"either a refusal or a description of this tool's own capabilities, not "
                f"a claim drawn from the records.")

    item = _explain_target(prior, state)
    if item is not None:
        d = provenance.explain(item, role=state.officer_role,
                               ps=_officer_ps(state.officer_id),
                               operation=_prior_operation(prior),
                               subject_id=state.active_entities.active_person)
        head = [d.claim, "", f"This is {d.basis.upper()} — {d.basis_meaning}", ""]
        if d.records:
            head.append("Supported by:")
            head += [f"  · {r.label}" + (f" — {r.detail}" if r.detail else "")
                     for r in d.records]
        else:
            head.append("Supported by the record it was read from; nothing further is "
                        "cited beneath it.")
        if d.qualifies:
            head += ["", f"Strength: {d.qualifies}"]
        if d.caveat:
            head += ["", f"What it does not establish: {d.caveat}"]
        return "\n".join(head)

    lines = [f'The previous answer to "{prior.query}" is supported by:']
    for c in prior.citations:
        lines.append(f"  [{c.get('index')}] {c.get('label')}")
    truth = provenance.describe_result_set((prior.result_context or {}))
    if truth:
        lines += ["", truth]
    return "\n".join(lines)


def _challenge_explanation(prior, state: InvestigationState) -> str:
    """'Poke holes in this' — actively looks for what would WEAKEN the previous
    answer, rather than explaining how it was reached (EXPLAIN_REASONING's job).
    Reuses the same gap-detection PREFILING_CHECK runs before a case is filed — the
    same real gaps, asked about an answer already given rather than a case not yet
    sent up. Never invents a weakness: an absence of one is reported honestly."""
    role, ps = state.officer_role, _officer_ps(state.officer_id)
    pool = _explain_pool(prior)
    if not pool:
        return (f'There is nothing to challenge — the previous answer to '
                f'"{prior.query}" cited no records, so there is no finding resting '
                f"on anything to argue against.")

    # A prior turn's own evidence carries the case id two different shapes:
    # `fir:{fir_id}` (a direct FIR citation) and `{prefix}:{fir_id}:{suffix}` (every
    # case-scoped addition this pass built — handoff/filing/watch/linkage all write
    # their case id as the SECOND segment, not the whole tail). Live-found: "poke
    # holes in this" right after "catch me up on this case" read no case at all,
    # because CASE_HANDOFF's own evidence is `handoff:{fir_id}:summary`, not
    # `fir:{fir_id}` — this checked only the first shape and found nothing to check.
    _CASE_SCOPED_PREFIXES = {"handoff", "filing", "watch", "linkage"}

    def _fir_id_of(eid: str) -> Optional[str]:
        parts = (eid or "").split(":")
        if not parts:
            return None
        if parts[0] == "fir" and len(parts) >= 2:
            return parts[1]
        if parts[0] in _CASE_SCOPED_PREFIXES and len(parts) >= 2 and parts[1].isdigit():
            return parts[1]
        return None

    fir_ids = list(dict.fromkeys(
        fid for e in pool if (fid := _fir_id_of(e.get("evidence_id") or ""))))[:3]
    if not fir_ids and state.active_entities.active_fir:
        # The pool named no case at all (e.g. every item is a board/summary line) —
        # the case still open in this session is the one the prior answer was about.
        fir_ids = [state.active_entities.active_fir]
    # `assoc`/`same_as`/`community` were missing here, so a PERSON_NETWORK answer —
    # the single most-challenged kind, since every associate in it is DERIVED —
    # yielded no person, no case, and therefore no structural check at all. Found
    # live: "Convince me this is wrong" after an associates answer printed one
    # degenerate line and nothing else.
    _PERSON_PREFIXES = ("accused", "priors", "offender", "assoc", "same_as",
                        "community", "interview")
    person_ids = list(dict.fromkeys(
        e.get("evidence_id", "").split(":", 1)[1] for e in pool
        if (e.get("evidence_id") or "").split(":", 1)[0] in _PERSON_PREFIXES
        and e.get("evidence_id", "").split(":", 1)[1].isdigit()))[:1]
    # A derived-network answer is challenged at its DERIVATION, not at each
    # associate's own file: the subject the graph was walked from is the session's
    # own focus, which outlives the stored turn.
    derived_net = any((e.get("evidence_id") or "").split(":", 1)[0] in ("assoc", "same_as")
                      for e in pool)

    lines = [f'Looking for what would weaken the previous answer to "{prior.query}":']
    found = False
    for fid in fir_ids:
        for g in _case_evidence_gaps(fid, role, ps):
            found = True
            lines.append(f"- On FIR {fid}: {g}")
    for pid in person_ids:
        for g in _person_pattern_gaps(pid, role, ps):
            found = True
            lines.append(f"- {g}")

    if derived_net and state.active_entities.active_person:
        for g in _network_challenges(state.active_entities.active_person, role):
            found = True
            lines.append(f"- {g}")

    # Two guards, both from one live output that read:
    #   'The least-supported single point this rests on: "" (confidence 100%)'
    #   1. `sessions._pack` sheds evidence BODIES on a large turn (it keeps ids and
    #      confidences), so `content` is legitimately empty on exactly the big
    #      answers most worth challenging — the citation label survives and says
    #      the same thing, so fall back to it rather than quoting nothing.
    #   2. A point at 100% confidence is not "the least-supported" anything; it is
    #      the minimum of a set that is uniformly certain. Naming it as a weakness
    #      is the same false-positive class §8's contradiction check exists to
    #      avoid — an officer told a 100% item is the weak link stops reading.
    labels = {c.get("evidence_id"): (c.get("label") or "") for c in (prior.citations or [])}
    scored = [e for e in pool
              if not e.get("authoritative") and e.get("confidence") is not None
              and float(e["confidence"]) < 0.8]
    if scored:
        weakest = min(scored, key=lambda e: e["confidence"])
        excerpt = ((weakest.get("content") or "")
                   or labels.get(weakest.get("evidence_id")) or "").strip()[:160]
        if excerpt:
            found = True
            lines.append(
                f'- The least-supported single point this rests on: "{excerpt}" '
                f"(confidence {float(weakest['confidence']):.0%}). If that one does "
                f"not hold, the rest of the finding is unaffected, but that specific "
                f"point is.")

    if not found:
        lines.append(
            "- Nothing structural stands out: every record cited is a direct, dated "
            "entry with no missing arrest or chargesheet gap on file. That does not "
            "certify the finding is correct — only that this check found no "
            "structural weakness to name.")
    from data.nlp.translate import resolve_plural_markers
    return resolve_plural_markers("\n".join(lines))


def _district_code(state: InvestigationState) -> str | None:
    from data.districts import canonical_code
    # state.constraints wins over active_location: a constraint-change follow-up
    # ("same thing for Bengaluru" after a HOTSPOT/FORECAST turn) carries its new
    # district here without touching session focus — see semantic_interpreter's
    # _REPEAT_CUE_RE branch, which deliberately does not set active_location.
    loc = state.constraints.get("district") or state.active_entities.active_location
    if loc:
        return canonical_code(loc)
    rows = sql_agent.crime_counts_by_district(limit=1)
    return rows[0]["district_code"] if rows else None


def _fir_date(value) -> str:
    """Live Data Store returns every column as a string (CONTEXT.md), so a date spec
    applied straight to the value raises. ds.to_dt() is the shared coercion; a row
    with no date still has to render, because the record identifier is the point."""
    dt = ds.to_dt(value)
    return f"{dt:%d %b %Y}" if dt else "date not recorded"


def _fir_content(r: dict) -> str:
    """One FIR, as a sentence — built ONLY from keys sql_agent._case() returns.

    It previously reached for 'ipc_sections' and 'modus_operandi', which that mapping
    has never produced. The code never ran, because the branch calling it was
    unreachable until the 18-digit FIR number was recognised."""
    where = ", ".join(x for x in (r.get("district"), f"PS {r['ps_code']}" if r.get("ps_code") else None) if x)
    text = (f"FIR {r['fir_number']}" + (f" ({where})" if where else "")
            + f" — {r.get('crime_type') or 'crime type not recorded'}, "
              f"filed {_fir_date(r.get('date_filed'))}, "
              f"status {r.get('case_status') or 'not recorded'}.")
    if r.get("narrative"):
        text += f" {r['narrative']}"
    return text


_NOTE_RE = re.compile(r"\bnote(?:\s+that)?\s*:?\s*(.+)$", re.I)
_LEAD_CONTENT_RE = re.compile(r"\bas\s+a?\s*lead\s*:?\s*(.+)$", re.I)


def _person_name(pid: Optional[str]) -> Optional[str]:
    if not pid:
        return None
    row = ds.one('SELECT "CanonicalName" FROM "vx_person" WHERE "PersonUID" = :p',
                {"p": int(pid)})
    return row["CanonicalName"] if row else None


def _extract_note_text(query: str) -> str:
    m = _NOTE_RE.search(query or "")
    return m.group(1).strip(" :,-—") if m else ""


def _extract_lead_content(query: str) -> str:
    m = _LEAD_CONTENT_RE.search(query or "")
    return m.group(1).strip(" :,-—") if m else ""


def _parse_lead_status(query: str) -> str:
    ql = (query or "").lower()
    if re.search(r"\b(dismiss|remove|drop|cancel)\b", ql):
        return "dismissed"
    if re.search(r"\bpursu", ql):
        return "pursued"
    return "open"


def _resolve_target_lead(leads: list[dict], state: InvestigationState) -> Optional[dict]:
    """Which saved lead 'that lead' means: prefer one naming the person currently in
    view, else the most recently created OPEN lead — 'that' reads most naturally as
    the thing just discussed, not an arbitrary dismissed one from days ago."""
    open_leads = [l for l in leads if l.get("status") == "open"]
    pool = open_leads or leads
    if not pool:
        return None
    name = _person_name(state.active_entities.active_person)
    if name:
        named = [l for l in pool if name.lower() in (l.get("content") or "").lower()]
        if named:
            pool = named
    return sorted(pool, key=lambda l: l.get("created_at") or "", reverse=True)[0]


def _pin_evidence_from_context(state: InvestigationState, fir_id: str, role: str, ps: str) -> dict:
    """'Pin this' — resolves to the evidence card the console had selected
    (`active_evidence_id`, sent by apps/web's own `activeEvidence` state) or, absent
    a selection, the previous turn's top citation. Reads the PREVIOUS turn's own
    evidence/citations (the same source EXPLAIN_REASONING/EVIDENCE_FOR already read),
    never the current turn's — a board action gathers no evidence of its own.

    A genuine selection (`target` below) must be tried against every source before
    ever falling back to "whatever the previous turn showed" — found live: with a
    target set but absent from the previous turn's own pool (e.g. an event picked
    from the Copilot overlay's Timeline tab, which fetches over REST and so was
    never part of any chat turn), the old code fell through to `pool[0]` anyway and
    silently pinned the wrong thing with no indication a substitution had happened.
    """
    prior = _last_turn(state.session_id)
    target = state.active_evidence_id
    ev: Optional[dict] = None

    if prior and target:
        # Only items that still carry a body are pinnable: a truncated turn stores
        # evidence SKELETONS (sessions._skeleton), and pinning one would put an empty
        # card on the board under a real record's id. The citation fallback below
        # carries the label, which is what the officer actually saw.
        pool = [e for e in (prior.evidence_items or []) if e.get("content")]
        ev = next((e for e in pool if e.get("evidence_id") == target), None)
        if not ev:
            c = next((c for c in prior.citations if c.get("evidence_id") == target), None)
            if c:
                ev = {"evidence_id": c["evidence_id"], "source_type": "FIR_RECORD",
                     "source_id": c["evidence_id"], "content": c["label"],
                     "confidence": None, "authoritative": False, "source_query": None}

    if not ev and target and target.startswith("timeline:"):
        # The Copilot overlay's own Timeline tab (Copilot.tsx) fetches the case
        # timeline over REST, not through /chat — so "pin this event" from there has
        # no prior CONVERSATION turn to read. The event ids are deterministic (see
        # _timeline_evidence), so it is re-derived directly from the same case
        # timeline the tab is showing, rather than requiring a priming chat turn
        # first the way opening the board from the case index used to.
        result = timeline_agent.case_timeline(fir_id, role, ps)
        for e in result["events"]:
            if f"timeline:{e['event_type']}:{e['entity_id']}:{e['date']}" == target:
                item = _timeline_evidence(e)
                ev = {"evidence_id": item.evidence_id, "source_type": item.source_type,
                     "source_id": item.source_id, "content": item.content,
                     "confidence": item.confidence, "authoritative": item.authoritative,
                     "source_query": item.source_query}
                break

    if not ev and target and target.startswith("edge:"):
        # NetworkView.tsx's own edge click (STRATEGIC_RESET Part 9, Item 3) — an
        # edge is graph structure, not an EvidenceItem, so it has no citation to
        # read from a prior turn's own pool. Same reasoning as the "timeline:"
        # branch above: re-derived directly from the graph itself rather than
        # requiring it to have already passed through /chat as a citation.
        parts = target[len("edge:"):].split("|")
        if len(parts) == 3:
            src, etype, dst = parts
            from data.graph import load_graph
            g = load_graph()
            candidates = g.get_edge_data(src, dst) or {}
            match = next((d for d in candidates.values() if d.get("rel") == etype),
                        next(iter(candidates.values()), None))
            if match:
                def _label(node_id: str) -> str:
                    if node_id.startswith("person:"):
                        return _person_name(node_id.split(":", 1)[1]) or node_id
                    return node_id
                weight = match.get("weight")
                content = (f"{_label(src)} and {_label(dst)} are linked via {etype}"
                          + (f" (weight {weight:.2f})" if weight is not None else "") + ".")
                ev = {"evidence_id": target, "source_type": "graph_edge",
                     "source_id": target, "content": content,
                     "confidence": None, "authoritative": False, "source_query": None}

    if not ev and prior and not target:
        # No specific card was selected — "pin this" meaning "whatever you just
        # showed me". Only reached with no target at all; a target that failed to
        # resolve above must never silently fall back to a different item.
        pool = [e for e in (prior.evidence_items or []) if e.get("content")]
        if pool:
            ev = pool[0]
        elif prior.citations:
            c = prior.citations[0]
            ev = {"evidence_id": c["evidence_id"], "source_type": "FIR_RECORD",
                 "source_id": c["evidence_id"], "content": c["label"],
                 "confidence": None, "authoritative": False, "source_query": None}

    if not ev:
        raise _NoEvidenceInContext()
    item_type = "finding" if ev.get("authoritative") else "evidence"
    return board_agent.create_item(
        fir_id, role, ps, state.officer_id, item_type,
        ev.get("content") or "", ref_type=ev.get("source_type"),
        ref_id=ev.get("source_id") or ev.get("evidence_id"),
        confidence=ev.get("confidence"), source_query=ev.get("source_query"))


def _handle_board_intent(state: InvestigationState, t0: float) -> None:
    fir_id = state.active_entities.active_fir
    role, ps = state.officer_role, _officer_ps(state.officer_id)
    try:
        if state.intent == "BOARD_VIEW":
            b = board_agent.get_board(fir_id, role, ps)
            state.board_result = {"ok": True, "kind": "view", "board": b}
            _trace(state, "Case Board", f"{b['total']} item(s) on the board", t0)
            return

        if state.intent == "BOARD_PIN_EVIDENCE":
            try:
                item = _pin_evidence_from_context(state, fir_id, role, ps)
            except _NoEvidenceInContext:
                state.board_result = {"ok": False, "kind": "error",
                                      "message": "There's nothing in view to pin yet — "
                                                 "ask a question first, then pin what it finds."}
                _trace(state, "Case Board", "Nothing to pin", t0)
                return
            state.board_result = {"ok": True, "kind": "pinned", "item": item}
            _trace(state, "Case Board", f"Pinned: {item['content'][:60]}", t0)
            return

        if state.intent == "BOARD_PIN_PERSON":
            pid = state.active_entities.active_person
            if not pid:
                state.board_result = {"ok": False, "kind": "error",
                                      "message": "No person is currently in view to add — "
                                                 "name someone first, or open their record."}
                _trace(state, "Case Board", "No person to add", t0)
                return
            name = _person_name(pid) or f"person {pid}"
            item = board_agent.create_item(fir_id, role, ps, state.officer_id, "person",
                                           name, ref_type="vx_person", ref_id=pid)
            state.board_result = {"ok": True, "kind": "pinned", "item": item, "label": name}
            _trace(state, "Case Board", f"Added {name} to the investigation", t0)
            return

        if state.intent == "BOARD_ADD_LEAD":
            pid = state.active_entities.active_person
            name = _person_name(pid) if pid else None
            content = _extract_lead_content(state.original_query or "")
            if not content:
                content = f"Follow up on {name}." if name else \
                    "Follow up — flagged from conversation."
            item = board_agent.create_item(fir_id, role, ps, state.officer_id, "lead",
                                           content, ref_type="vx_person" if pid else None,
                                           ref_id=pid, status="open")
            state.board_result = {"ok": True, "kind": "lead_added", "item": item}
            _trace(state, "Case Board", f"Lead saved: {content[:60]}", t0)
            return

        if state.intent == "BOARD_ADD_NOTE":
            text = _extract_note_text(state.original_query or "")
            if not text:
                state.board_result = {"ok": False, "kind": "error",
                                      "message": "Say what the note should record — e.g. "
                                                 "\"add a note that this connection needs "
                                                 "verification\"."}
                _trace(state, "Case Board", "No note text given", t0)
                return
            item = board_agent.create_item(fir_id, role, ps, state.officer_id, "note", text)
            state.board_result = {"ok": True, "kind": "note_added", "item": item}
            _trace(state, "Case Board", f"Note recorded: {text[:60]}", t0)
            return

        if state.intent == "BOARD_LEAD_STATUS":
            new_status = _parse_lead_status(state.original_query or "")
            b = board_agent.get_board(fir_id, role, ps)
            target = _resolve_target_lead(b["by_type"]["lead"], state)
            if not target:
                state.board_result = {"ok": False, "kind": "error",
                                      "message": "No matching saved lead found to update — "
                                                 "open the board to see the current leads."}
                _trace(state, "Case Board", "No matching lead", t0)
                return
            item = board_agent.update_item(fir_id, role, ps, state.officer_id,
                                           target["item_id"], status=new_status)
            state.board_result = {"ok": True, "kind": "lead_status", "item": item}
            _trace(state, "Case Board", f"Lead -> {new_status}: {item['content'][:60]}", t0)
            return
    except board_agent.NotPermitted:
        state.refusal_reason = "board_forbidden"
        _trace(state, "Case Board", "Case is outside this officer's station scope", t0)
    except KeyError:
        state.refusal_reason = "board_not_found"
        _trace(state, "Case Board", "Case not found", t0)


def _board_answer(intent: str, result: dict) -> str:
    if not result.get("ok", True):
        return result.get("message", "That could not be completed.")
    if intent == "BOARD_VIEW":
        b = result["board"]
        if not b["total"]:
            return (f"The investigation board for FIR {b['fir_number']} is empty — "
                    f"nothing has been pinned, noted or saved as a lead yet.")
        labels = [("evidence", "pinned evidence"), ("finding", "findings"),
                 ("person", "people added"), ("lead", "leads"),
                 ("note", "notes"), ("question", "open questions")]
        lines = [f"Board for FIR {b['fir_number']} ({b['total']} item(s)):"]
        for key, label in labels:
            items = b["by_type"].get(key) or []
            if not items:
                continue
            if key == "lead":
                open_n = sum(1 for i in items if i.get("status") == "open")
                lines.append(f"- {len(items)} {label} ({open_n} open, "
                             f"{len(items) - open_n} closed)")
            else:
                lines.append(f"- {len(items)} {label}")
        lines.append("Ask to see any section, or say what to add next.")
        return "\n".join(lines)
    if intent == "BOARD_PIN_EVIDENCE":
        item = result["item"]
        kind = "finding" if item["item_type"] == "finding" else "evidence"
        return f'Pinned this {kind} to the case board: "{item["content"][:200]}"'
    if intent == "BOARD_PIN_PERSON":
        return f"Added {result.get('label') or 'this person'} to the investigation board."
    if intent == "BOARD_ADD_LEAD":
        return f'Saved as a lead: "{result["item"]["content"]}" (status: open).'
    if intent == "BOARD_ADD_NOTE":
        return f'Note recorded on the case board: "{result["item"]["content"]}"'
    if intent == "BOARD_LEAD_STATUS":
        item = result["item"]
        return f'Lead marked {item["status"]}: "{item["content"][:200]}"'
    return "Done."


def _fir_evidence(r: dict) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"fir:{r['fir_id']}", source_type="CRIMINAL_RECORD",
        source_id=str(r["fir_id"]),
        source_query="SELECT ... FROM criminal_record JOIN fir",
        content=_fir_content(r) + (" Convicted." if r.get("conviction") else ""),
        confidence=0.95)


def _network_evidence(r: dict, siblings: list[dict] | None = None) -> EvidenceItem:
    # CLAUDE.md §4: the ER records no gang, so the derived Louvain grouping is
    # labelled honestly as what it is — "network community 6", never "gang" — the
    # same discipline copilot/brief.py already follows. This rendering was the one
    # place still printing the literal word "gang" in front of an officer.
    name = r["name_en"]
    if siblings and sum(1 for s in siblings if s["name_en"] == name) > 1:
        # Two DIFFERENT real PersonUIDs can share a CanonicalName — a genuine
        # namesake, the same possibility BUG-026 documented elsewhere for
        # canonical-vs-as-filed drift. Found live: "Suma Nadkarni" listed twice in
        # one associates answer with identical text and nothing to indicate they
        # are two different people, reading as a rendering bug rather than two
        # real associates. Disambiguated only when this list actually has a
        # collision — every other list is untouched.
        name = f"{name} (person {r['person_id']})"
    return EvidenceItem(
        evidence_id=f"assoc:{r['person_id']}", source_type="GRAPH_RELATIONSHIP",
        source_id=str(r["person_id"]),
        source_query="CO_ACCUSED_WITH subgraph (vx_graph_edge), shortest-hop "
                     "traversal in NetworkX, policy-capped depth",
        content=(f"{name} is a known associate ({r['hops']} hop(s) away"
                 # r['gang'] is already formatted "Community 47" (data/gds.py); lower-
                 # cased to match the "network community 6" phrasing used everywhere
                 # else this same derived grouping is shown (copilot/brief.py's leads).
                 + (f", network {r['gang'].lower()}" if r.get("gang") else "") + ")."),
        confidence=1.0 / max(1, int(r.get("hops") or 1)))


def _alias_evidence(r: dict) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"same_as:{r['person_id']}", source_type="GRAPH_RELATIONSHIP",
        source_id=str(r["person_id"]),
        source_query="vx_accused_identity — duplicate-identity check "
                     "(probabilistic record linkage)",
        content=(f"Record for '{r['name_en']}' was linked to this person by "
                 f"probabilistic record linkage (confidence {r['confidence']:.2f}) — "
                 f"the same individual recorded under a different spelling."),
        confidence=float(r["confidence"]))


def _dedupe(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen, out = set(), []
    for e in items:
        if e.evidence_id not in seen:
            seen.add(e.evidence_id)
            out.append(e)
    return out


def node_evaluate(state: InvestigationState) -> InvestigationState:
    t0 = time.perf_counter()
    # A turn that already stopped in node_retrieve was never a retrieval failure, so it
    # does not get scored as one — running the evaluator over an empty batch would
    # relabel "you named no subject" as "no supporting records found".
    if state.refusal_reason:
        state.requires_escalation = True
        state.confidence_score = 0.0
        return state
    if state.intent.startswith("BOARD_"):
        # A board action is a mutation/read of investigator state, not retrieval —
        # nothing here for CRAG to score, and scoring an empty batch would relabel a
        # successful pin as "no supporting records found".
        state.requires_escalation = False
        state.confidence_score = 1.0
        return state

    verdict, confidence, detail = evaluate(state.evidence_items, state.retrieval_attempts - 1,
                                           state.exact_lookup_missed)
    state.confidence_score = confidence
    state.requires_escalation = verdict == "REJECT"
    if verdict == "REJECT" and not state.refusal_reason:
        state.refusal_reason = ("exact_lookup_missed" if state.exact_lookup_missed
                                else "no_evidence")
    _trace(state, "Evidence Evaluator (CRAG)", detail, t0, confidence)
    return state


def node_synthesize(state: InvestigationState) -> InvestigationState:
    t0 = time.perf_counter()

    # A capability question is answered, not refused: the honest answer to "what can you
    # do" is a description of this tool. It carries no citations because there is no
    # record behind it, and the console renders a citation-free turn as a refusal — so
    # the answer says plainly that it is about the system rather than the records.
    if state.intent == "CAPABILITY":
        # The query decides WHICH answer: "do you decide guilt" and "what can
        # you do" are both capability questions and must not get the same
        # paragraph — a judge handed a feature list in reply to the first has
        # been answered in form and not in substance.
        answer = intents.capability_answer(state.original_query or "")
        if state.language != "en":
            answer, _ = translation_agent.to_language(answer, state.language)
        state.final_answer = answer
        state.citations = []
        state.evidence_items = []
        _trace(state, "Synthesis",
               "Described this system's scope — no records were consulted", t0)
        return state

    # The case board (see node_retrieve's BOARD_* short circuit) — the answer is the
    # outcome of the mutation/read itself, not evidence synthesis. No citations: a
    # note/lead the officer just wrote is not a record the record layer produced.
    if state.intent.startswith("BOARD_") and state.board_result is not None:
        answer = _board_answer(state.intent, state.board_result)
        note = None
        if state.language != "en":
            answer, note = translation_agent.to_language(answer, state.language)
        if note:
            answer = f"{answer}\n\n{note}"
        state.final_answer = answer
        state.citations = []
        state.evidence_items = []
        # A board action's own local "couldn't do that" (nothing to pin, no
        # matching lead) reads as a refusal and should be styled like one; a
        # successful pin/note/lead/view should not.
        state.answer_is_refusal = not state.board_result.get("ok", True)
        _trace(state, "Synthesis", "Case board action", t0)
        return state

    # Meta-questions about the PREVIOUS turn — see node_retrieve's "meta" short
    # circuit. Answered here rather than there because the answer is built from
    # storage, not from anything node_retrieve/node_evaluate compute.
    if state.intent in ("EXPLAIN_REASONING", "EVIDENCE_FOR", "CHALLENGE_FINDING"):
        prior = _last_substantive_turn(state.session_id)
        if not prior:
            answer = refusal_message("nothing_prior")
            note = None
            if state.language != "en":
                answer, note = translation_agent.to_language(answer, state.language)
            if note:
                answer = f"{answer}\n\n{note}"
            state.final_answer = answer
            state.citations = []
            state.evidence_items = []
            state.answer_is_refusal = True
            _trace(state, "Synthesis", "Refused to answer — nothing_prior", t0)
            return state

        answer = (_reasoning_explanation(prior, state) if state.intent == "EXPLAIN_REASONING"
                 else _evidence_explanation(prior, state) if state.intent == "EVIDENCE_FOR"
                 else _challenge_explanation(prior, state))
        note = None
        if state.language != "en":
            answer, note = translation_agent.to_language(answer, state.language)
        if note:
            answer = f"{answer}\n\n{note}"
        state.final_answer = answer
        # Re-show the same citations the previous turn had — the officer asked what
        # backs THAT answer, not for a new one. citations always survive storage;
        # evidence_items may come back as SKELETONS (identity fields only, no body)
        # when the stored turn was over the Data Store's text-column budget, and a
        # skeleton cannot be rehydrated into an EvidenceItem — `content` has no
        # default and never should, since an evidence item with no content is not
        # evidence. Skeletons are still read for their ids by the explanation path
        # above; they simply do not go back on screen as sources.
        state.citations = [Citation(**c) for c in prior.citations]
        state.evidence_items = [EvidenceItem(**e) for e in prior.evidence_items
                                if e.get("content")]
        _trace(state, "Synthesis",
               f"Explained the previous turn ({len(prior.citations)} citation(s))", t0)
        return state

    if state.requires_escalation:
        reason = state.refusal_reason or "no_evidence"
        if reason == "ambiguous_person" and state.ambiguous_candidates:
            names = ", ".join(state.ambiguous_candidates)
            answer = (f"More than one person named in this question matches equally well: "
                      f"{names}. I will not guess which one you mean — say which one, or add "
                      f"a case number or district to tell them apart.")
        else:
            answer = refusal_message(reason)
        # Found live: "ಮಧು ಯರಗಟ್ಟಿಗೆ ಹಿಂದಿನ ಪ್ರಕರಣಗಳಿವೆಯೇ?" (a real, common first name +
        # "does X have previous cases") translated clean end-to-end except for one
        # thing — NLLB rendered "ಮಧು" (Madhu, the name) as "honeydew" (its literal
        # meaning), so PERSON_HISTORY correctly classified at 0.9 confidence and then
        # had no name left to resolve. This is a real, structural gap (no Kannada-
        # script name gazetteer exists to protect a person's name the way
        # data/nlp/translate.py already protects district names and record
        # identifiers — building one needs either a transliteration library, which
        # would require rebuilding the base deploy image, not just the fast overlay
        # path, or a hand-built name table, neither safe to attempt unattended) — so
        # this does not fix the mistranslation, only stops leaving the officer with
        # no idea why a clearly-named question came back empty.
        if (reason in ("no_subject", "cannot_understand") and state.original_query_kn):
            answer += (" (If you named a person, note that a Kannada name is "
                       "sometimes mistranslated during automatic translation — "
                       "try spelling the name in English letters instead.)")
        note = None
        if state.language != "en":
            answer, note = translation_agent.to_language(answer, state.language)
        if note:
            answer = f"{answer}\n\n{note}"
        state.final_answer = answer
        # Every other refusal branch in this function clears both fields together
        # (see CAPABILITY and "nothing_prior" above). This one only cleared citations,
        # so a widened search that came back with low-confidence neighbours the
        # evaluator correctly REJECTed still shipped those neighbours in evidence_items
        # — the Evidence rail rendered 8 unrelated FIRs, each with its own "X% text
        # similarity" chip, right next to a message saying nothing was found. Found
        # live: asking about a subject with no records at all ("Tell me about the
        # flying saucer incident on the moon") still populated the rail with unrelated
        # robbery cases at ~40% similarity. A refusal that already knows it has
        # nothing to cite must not keep the evidence it rejected.
        state.citations = []
        state.evidence_items = []
        state.answer_is_refusal = True
        _trace(state, "Synthesis", f"Refused to answer — {reason}", t0)
        return state

    # Cite only what supports the answer. Retrieval deliberately casts wide and most of
    # what it returns is context; the evaluator already draws that line to decide whether
    # to answer at all, and synthesis now honours the same line instead of citing the
    # whole neighbourhood.
    evidence = supporting(_rank_evidence(state))[:12]
    _reconcile_shown_with_cap(state, evidence)

    # "case(s)" is a convention for a count the producing branch does not always
    # have at the point the sentence is written. It was only ever resolved on the
    # way into the translation model, so an English reader was left with the marker
    # itself — a form field in the middle of a finding.
    #
    # Resolved BEFORE synthesis, not after: a citation's label is built from the
    # evidence content (synthesis_agent._label), so resolving afterwards cleaned the
    # answer and the evidence rail while leaving every citation chip still reading
    # "1 hop(s) away". Found by driving the console, not by a test — the answer and
    # the chip beside it disagreed about the same sentence.
    from data.nlp.translate import resolve_plural_markers
    for e in evidence:
        e.content = resolve_plural_markers(e.content)

    reasoning_sink: list[str] = []
    answer, citations = synthesis_agent.synthesize(
        state.original_query or "", evidence, operation=state.intent,
        reasoning_sink=reasoning_sink)
    answer = resolve_plural_markers(answer)

    # What KIND of result set this is — sampled, filtered, ranked, exhaustive,
    # modelled. Stated because the quiet failure is the dangerous one: five cases
    # listed under a question that asked for "the cases" reads as all of them, and
    # the officer has no way to tell from the answer that it was a sample. The fact
    # is already recorded by whichever branch produced the set (result_context);
    # this is where it stops being internal.
    truth = provenance.describe_result_set(state.result_context or {})
    if truth:
        answer = f"{answer}\n\n{truth}"

    # Structured fields beat generated prose. Checked BEFORE translation, so a
    # contradiction cannot be laundered through the model into a language the check
    # does not read.
    answer = _reconcile_with_records(answer, evidence, state)

    note = None
    if state.language != "en":
        answer, note = translation_agent.to_language(answer, state.language)
    if note:
        answer = f"{answer}\n\n{note}"

    state.final_answer = answer
    state.citations = citations
    state.evidence_items = evidence
    state.visualization = synthesis_agent.build_visualization(state.intent, state)
    if reasoning_sink:
        # Chain-of-Thought the model already did to reach this answer — one entry,
        # capped, not a second retrieval step. Shown collapsed like every other
        # trace step; never treated as a citation source.
        _trace(state, "Reasoning", reasoning_sink[0][:600], t0)
    _trace(state, "Evidence Synthesis",
           f"Answer grounded in {len(citations)} citation(s); "
           f"visualization: {state.visualization.kind}", t0)
    return state


# --- contradiction checking: the structured field beats the generated sentence ----
#
# A case whose CaseStatusName is "Convicted" and whose generated narrative says "the
# investigation is being carried out" is not a wording problem — it is the system
# telling an officer something the file contradicts, in the register of a finding. The
# status column is authoritative; the prose is a rephrasing, and where they disagree
# the prose is what is wrong.
#
# The check runs BEFORE translation, deliberately: a contradiction laundered through
# NLLB into Kannada is one no English pattern here would ever see again.
#
# Only two things are checked, and both are checked narrowly. This is a place where a
# false positive is expensive — an officer told "the record says otherwise" about a
# sentence that was in fact correct learns to ignore the warning — so anything that
# cannot be decided from a structured column the cited records actually carry is left
# alone rather than guessed at.

# Status families. Two phrases in DIFFERENT families are a contradiction; two in the
# same family are a paraphrase. Keyed by the family the CaseStatusName itself falls in.
_STATUS_FAMILIES: dict[str, re.Pattern] = {
    "open": re.compile(
        r"\b(under investigation|investigation is (ongoing|continuing|underway|in progress"
        r"|being carried out|pending|yet to)|still being investigated|remains? open"
        r"|enquiry is (ongoing|underway|in progress))\b", re.I),
    "chargesheeted": re.compile(
        r"\b(charge ?sheet (has been |was )?filed|charge ?sheeted)\b", re.I),
    "convicted": re.compile(r"\b(was convicted|has been convicted|conviction was)\b", re.I),
    "acquitted": re.compile(r"\b(was acquitted|has been acquitted|acquittal)\b", re.I),
    "closed": re.compile(r"\b(case (was |has been )?closed|closed as|disposed of)\b", re.I),
}


def _status_family(status: str) -> Optional[str]:
    s = (status or "").lower()
    if not s:
        return None
    if "convict" in s:
        return "convicted"
    if "acquit" in s:
        return "acquitted"
    if "charge" in s:
        return "chargesheeted"
    if "clos" in s or "dispos" in s:
        return "closed"
    if "investigat" in s or "pending" in s or "open" in s:
        return "open"
    return None


# "[3, 7, 9, 11]"-style citation groups inside a generated sentence. Used only by
# check 0 below — matches "status <Name>" the same way a FIR citation's own label is
# built (synthesis_agent._label is just the evidence content's first line).
_CITATION_INDEX_GROUP_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_STATUS_IN_CONTENT_RE = re.compile(r"\bstatus\s+([A-Za-z][A-Za-z ]*?)(?:[.,;]|$)")


def _status_family_from_content(content: str) -> Optional[str]:
    m = _STATUS_IN_CONTENT_RE.search(content or "")
    return _status_family(m.group(1)) if m else None


def _reconcile_with_records(answer: str, evidence: list[EvidenceItem],
                            state: InvestigationState) -> str:
    """Append a correction where the prose contradicts a structured field.

    The prose is not rewritten. String surgery on a generated sentence produces a
    sentence nobody wrote and nobody can audit; naming the record's own value beside
    it leaves both on screen and makes the disagreement itself visible, which is what
    an officer needs in order to trust the rest of the answer.
    """
    flags: list[str] = []

    # 0. A citation-scoped status claim, inside a multi-status answer. Check 1 below
    #    deliberately never runs when a history spans several statuses — but that
    #    leaves exactly the gap a synthesized narrative's own grouping error hides
    #    in: found live, a priors answer read "Other cases include Theft [3, 7, 9,
    #    11] ... which are Chargesheeted or Under Investigation," while citation [7]
    #    was recorded Acquitted. Scoped to one SENTENCE naming both a status family
    #    and a bracketed citation index, so an ordinary sentence with neither is
    #    never touched; every status family the sentence names is collected (an "X
    #    or Y" grouping is not wrong about a citation matching either), and only a
    #    citation matching NONE of them is flagged.
    for sentence in re.split(r"(?<=[.!?])\s+", answer):
        idx_groups = _CITATION_INDEX_GROUP_RE.findall(sentence)
        if not idx_groups:
            continue
        claimed = [fam for fam, pat in _STATUS_FAMILIES.items() if pat.search(sentence)]
        if not claimed:
            continue
        seen_idx: set[int] = set()
        for group in idx_groups:
            for tok in group.split(","):
                tok = tok.strip()
                if not tok.isdigit():
                    continue
                idx = int(tok)
                if idx in seen_idx or not (1 <= idx <= len(evidence)):
                    continue
                seen_idx.add(idx)
                recorded = _status_family_from_content(evidence[idx - 1].content)
                if recorded and recorded not in claimed:
                    flags.append(
                        f"Correction from the record: citation [{idx}] is grouped above "
                        f"with a different status than the one on file. The recorded "
                        f"status is what governs.")

    # 1. Case status. Only checked when the cited records agree on ONE status — a
    #    person's history legitimately spans several, and any status phrase in the
    #    prose is then legitimately about one of them.
    statuses = {r.get("case_status") for r in state.sql_query_results if r.get("case_status")}
    if len(statuses) == 1:
        recorded = next(iter(statuses))
        fam = _status_family(recorded)
        if fam:
            for other, pat in _STATUS_FAMILIES.items():
                if other != fam and pat.search(answer):
                    flags.append(
                        f"Correction from the record: the case status on file is "
                        f'"{recorded}". The sentence above describes it differently; '
                        f"the recorded status is what governs.")
                    break

    # 2. A district named in the prose that no cited record and no part of the
    #    question mentions. A district is the coarsest thing an FIR states, so a
    #    district appearing from nowhere is the cheapest hallucination to catch.
    #
    #    "Grounded" has to mean grounded in the EVIDENCE, not in one particular
    #    field of one particular producer. The first version read only
    #    sql_query_results, which the timeline, graph and financial branches never
    #    populate — so a timeline answer citing five real FIRs in five real
    #    districts was flagged as naming four districts "in none of the records
    #    cited here", with those exact districts printed in the citations directly
    #    above. Found live on the second turn of the flow this check was written
    #    for. A false positive here is expensive: an officer told the record says
    #    otherwise about a correct sentence learns to ignore the warning.
    try:
        from data.districts import all_districts
        known = {d.name for d in all_districts()}
    except Exception:
        known = set()
    if known:
        grounded_text = " ".join(
            [str(r.get("district") or "") for r in state.sql_query_results]
            + [e.content for e in evidence])
        asked = (state.original_query or "") + " " + " ".join(
            str(v) for v in (state.constraints or {}).values() if v)
        invented = sorted(
            d for d in known
            if re.search(r"\b" + re.escape(d) + r"\b", answer, re.I)
            and not re.search(r"\b" + re.escape(d) + r"\b", grounded_text, re.I)
            and not re.search(r"\b" + re.escape(d) + r"\b", asked, re.I))
        if invented:
            flags.append(
                f"Not supported by the cited records: {', '.join(invented)} "
                f"{'is' if len(invented) == 1 else 'are'} named above but appear"
                f"{'s' if len(invented) == 1 else ''} in none of the records cited here.")

    if not flags:
        return answer
    _trace(state, "Record reconciliation",
           f"{len(flags)} contradiction(s) between the answer and the structured "
           f"record", time.perf_counter())
    return answer + "\n\n" + "\n".join(flags)


def _reconcile_shown_with_cap(state: InvestigationState, evidence: list[EvidenceItem]) -> None:
    """A producer branch (PERSON_NETWORK, ALIAS_CHECK, OFFENDER_RANKING) records
    result_context['shown']/'is_sample'/'shown_ids'] from its OWN full row count,
    before the citation cap two lines above ever runs — so a 40-associate network
    could claim 'EXHAUSTIVE -- 40 record(s)' and the 'only these?' follow-up could
    then say 'all of them already shown' while only 12 actually were. Found live:
    "Who are the associates of Usha Naika?" did exactly this.

    Recomputed here, once, from the citations that actually survived the cap — the
    one place both readers (the result-truth sentence below and the next turn's
    'only these?' handler) get their numbers from, so they can no longer disagree.
    """
    rc = state.result_context
    if not rc or not rc.get("shown_ids"):
        return
    recorded_ids = {str(i) for i in rc["shown_ids"]}
    surviving = {e.evidence_id.split(":", 1)[-1] for e in evidence
                if e.evidence_id.split(":", 1)[-1] in recorded_ids}
    if len(surviving) >= len(recorded_ids):
        return                          # nothing was capped away — already honest
    total = rc.get("total_matched")
    state.result_context = {
        **rc, "shown": len(surviving), "shown_ids": sorted(surviving),
        "is_sample": True if total is None else total > len(surviving),
    }


# The evidence type that most directly answers each intent. Confidence alone ranks a
# high-confidence FIR fact above the risk score the officer actually asked for, so the
# answer to "what is his risk of reoffending" would open with an unrelated theft.
_INTENT_ANSWERS_WITH = {
    "RISK": "ML_PREDICTION",
    "FORECAST": "ML_PREDICTION",
    "CAUSAL": "ML_PREDICTION",
    "HOTSPOT": "GEOSPATIAL_ANALYSIS",
}


def _rank_evidence(state: InvestigationState) -> list[EvidenceItem]:
    """Citation [1] should be the best support for THIS question, not merely the
    most confident thing retrieved."""
    if state.intent in ("TIMELINE", "TIMELINE_CONNECTION",
                        "OFFENDER_RANKING", "CASE_STATS"):
        # Emitted in the order that IS the answer — chronological for a timeline,
        # rank 1..N for a ranking, denominator-before-rate for a statistic. Resorting
        # by confidence would scramble it, and a "top 5" whose first line is number
        # three is not a ranking.
        return list(state.evidence_items)
    preferred = _INTENT_ANSWERS_WITH.get(state.intent)
    alias = state.intent == "ALIAS_CHECK"

    def key(e: EvidenceItem):
        on_point = 0
        if preferred and e.source_type == preferred:
            on_point = -1
        elif alias and e.evidence_id.startswith("same_as:"):
            on_point = -1
        return (on_point, -e.confidence)

    return sorted(state.evidence_items, key=key)


def node_voice_out(state: InvestigationState) -> InvestigationState:
    if not state.respond_with_voice or not state.final_answer:
        return state
    t0 = time.perf_counter()
    audio, detail = voice_agent.synthesize(state.final_answer, state.language)
    state.output_audio = audio
    _trace(state, "Voice Agent (TTS)", detail, t0)
    return state


# --- graph -------------------------------------------------------------------

def _after_evaluate(state: InvestigationState) -> str:
    """CRAG's conditional edge — the reason a weak batch can't reach synthesis."""
    # Widening is for a batch that came back too thin. It is not a remedy for a question
    # that named no subject, asked for an inference, or asked about the tool itself —
    # retrying those searches the index twice and refuses on the second pass anyway.
    if state.refusal_reason or state.intent.startswith("BOARD_"):
        return "synthesize"
    verdict, _, _ = evaluate(state.evidence_items, state.retrieval_attempts - 1,
                             state.exact_lookup_missed)
    return "retrieve" if verdict == "REFINE" else "synthesize"


def build_graph():
    from langgraph.graph import END, StateGraph

    g = StateGraph(InvestigationState)
    g.add_node("voice_in", node_voice_in)
    g.add_node("translate_in", node_translate_in)
    g.add_node("orchestrate", node_orchestrate)
    g.add_node("retrieve", node_retrieve)
    g.add_node("evaluate", node_evaluate)
    g.add_node("synthesize", node_synthesize)
    g.add_node("voice_out", node_voice_out)

    g.set_entry_point("voice_in")
    g.add_edge("voice_in", "translate_in")   # ASR may itself return Kannada text
    g.add_edge("translate_in", "orchestrate")
    g.add_edge("orchestrate", "retrieve")
    g.add_edge("retrieve", "evaluate")
    g.add_conditional_edges("evaluate", _after_evaluate,
                            {"retrieve": "retrieve", "synthesize": "synthesize"})
    g.add_edge("synthesize", "voice_out")
    g.add_edge("voice_out", END)
    return g.compile()


_GRAPH = None


def run_investigation(state: InvestigationState,
                      trace_sink: Optional[list] = None) -> InvestigationState:
    """The single entrypoint apps/api calls, once per turn.

    `trace_sink`, when given, receives each AgentTraceEntry as it is produced, so a
    streaming caller can show progress during the turn instead of after it. It is a
    view, not a substitute: the returned state's `agent_trace` is still the complete,
    authoritative record.
    """
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    if trace_sink is None:
        result = _GRAPH.invoke(state)
    else:
        with live_trace(trace_sink):
            result = _GRAPH.invoke(state)
    return InvestigationState.model_validate(result)
