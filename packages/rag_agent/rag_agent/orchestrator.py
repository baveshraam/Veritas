"""The LangGraph investigation engine.

    voice_in -> orchestrate -> retrieve -> evaluate -+-> synthesize -> voice_out
                                   ^                 |
                                   +---- refine <----+   (CRAG: widen and retry once)

The conditional edge out of `evaluate` is the whole point: retrieval that comes back
empty or weak does not proceed to synthesis. It either widens once, or it stops and
says so. Nothing downstream can invent an answer, because synthesis is only ever
handed the evidence list — it has no other input.
"""
import re
import time
from datetime import datetime
from typing import Optional

from data import ds, upsert_session_focus
from policy import mask_person_name

from . import board as board_agent
from . import intents
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
FIR_NUMBER_RE = re.compile(r"\b(\d{3,4}/\d{4}|\d{12,20})\b")

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
}


def _trace(state: InvestigationState, step: str, detail: str,
           t0: float, confidence: float | None = None) -> None:
    state.agent_trace.append(AgentTraceEntry(
        step=step, detail=detail,
        duration_ms=int((time.perf_counter() - t0) * 1000),
        confidence=confidence,
    ))


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
    english, note = translation_agent.to_english(query)
    if english != query:
        state.original_query = english
        _trace(state, "Translation Agent (kn->en)", f"Query understood as: {english}", t0)
    else:
        _trace(state, "Translation Agent (kn->en)", note or "translation unavailable", t0)
    return state


def node_orchestrate(state: InvestigationState) -> InvestigationState:
    t0 = time.perf_counter()
    query = state.original_query or ""

    focus, entities = intents.resolve_focus(query, state.active_entities)
    state.intent = intents.classify(query)

    named = intents.named_person(entities)
    resolved_note = ""
    if named:
        hits = sql_agent.person_by_name(named)
        if hits and len(hits) > 1 and hits[0].get("record_count", 0) == hits[1].get("record_count", 0):
            # Genuinely ambiguous: the top two matches are tied on the only signal
            # used to rank them (record_count), so there is no principled leader to
            # pick. Guessing would hand the officer someone else's record with
            # nothing to indicate a substitution happened — the same failure mode
            # the "no record for this name" branch below already refuses to risk.
            # Asking is the honest answer; the candidates are named so it costs the
            # officer one turn, not a search.
            focus.active_person = None
            state.refusal_reason = "ambiguous_person"
            state.ambiguous_candidates = [h["name_en"] for h in hits[:4]]
            resolved_note = f"'{named}' matches {len(hits)} people with no clear leader"
        elif hits:
            # hits are ranked by record count; ambiguity is surfaced, not hidden —
            # several people really do share a name in this database.
            focus.active_person = str(hits[0]["person_id"])
            resolved_note = (f"resolved '{named}' to {hits[0]['name_en']} "
                             f"({hits[0].get('record_count', 0)} record(s))")
            if len(hits) > 1:
                resolved_note += f"; {len(hits) - 1} other person(s) share this name"
        else:
            # The turn names someone we hold no record for. The focus MUST be cleared,
            # never inherited: leaving the previous turn's subject in place makes the
            # engine answer about a different person entirely, and the officer is given
            # someone else's record with nothing to indicate a substitution happened.
            # Clearing it means retrieval finds nothing and the evaluator refuses —
            # which is the correct answer to "tell me about a person we have no file on".
            focus.active_person = None
            state.refusal_reason = "person_not_on_file"
            resolved_note = f"no person matching '{named}' exists in the records"
    elif intents.has_unresolved_reference(query, entities):
        if state.active_entities.active_person:
            focus.active_person = state.active_entities.active_person
            resolved_note = "resolved pronoun against the session's active person"
        else:
            # CASE_PEOPLE deliberately leaves active_person unset when a case has
            # several accused (naming one would be the same unlicensed guess the
            # ambiguous-name check above refuses to make) — but it DOES name every
            # candidate in that turn's own citations. A pronoun follow-up ("does he
            # have priors?") used to fall straight to "no_subject" and throw those
            # names away, forcing the officer to retype one from scratch even though
            # the system had just listed them. This reuses the same ask-don't-guess
            # clarification path the tied-name search above already uses, sourced
            # from the previous turn instead of a fresh search.
            candidates = _recent_person_candidates(state.session_id)
            # TIMELINE_CONNECTION's own pronoun ("both of them", "these two") names
            # MULTIPLE people by design — 2 recent candidates is exactly its intended
            # input, not the singular ambiguity this branch otherwise refuses on.
            # Found live: "Show me events involving both of them" right after a
            # 2-accused CASE_PEOPLE turn fell to this generic refusal before
            # _handle_timeline_connection (which resolves the identical 2 candidates
            # itself) ever ran.
            if len(candidates) >= 2 and state.intent != "TIMELINE_CONNECTION":
                state.refusal_reason = "ambiguous_person"
                state.ambiguous_candidates = candidates[:4]
                resolved_note = (f"pronoun could mean any of {len(candidates)} people "
                                  "named last turn; asking rather than guessing")
            else:
                resolved_note = "pronoun used with no active person in session"

    state.active_entities = focus
    state.decomposed_subqueries = [query]

    detail = f"Intent: {state.intent}"
    if resolved_note:
        detail += f"; {resolved_note}"
    _trace(state, "Orchestrator", detail, t0)

    # persist the focus so the *next* turn can resolve against it
    try:
        upsert_session_focus(state.session_id, state.officer_id, focus)
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
    if state.intent in ("EXPLAIN_REASONING", "EVIDENCE_FOR"):
        state.refusal_reason = "meta"
        _trace(state, "Orchestrator",
               "Question is about the previous answer, not the records", t0)
        return state

    # "Where are those cases concentrated" names no subject of its own — "those" refers
    # to whatever case list the previous turn showed (e.g. SIMILAR_CASES). This tallies
    # districts over that specific list rather than running a fresh, unscoped HOTSPOT
    # detection — HOTSPOT already owns "where are the crime hotspots" without a "those".
    if state.intent == "CASE_LOCATIONS":
        _handle_case_locations(state, t0)
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

    if state.intent in intents.NEEDS_CASE and not state.active_entities.active_fir and not state.refusal_reason:
        state.refusal_reason = "no_case"
        _trace(state, "Orchestrator",
               f"{state.intent} needs an open case; none given", t0)
        return state
    if state.intent in intents.NEEDS_SUBJECT and not pid and not state.refusal_reason:
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
        rows = sql_agent.person_record(pid)
        state.sql_query_results += rows
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
        _trace(state, "Cypher Agent", f"{len(rows)} associate(s) within policy depth", t0)

    elif intent == "ALIAS_CHECK" and pid:
        rows = graph_agent.aliases(pid)
        state.graph_query_results += rows
        if rows:
            out += [EvidenceItem(
                evidence_id=f"same_as:{r['person_id']}", source_type="GRAPH_RELATIONSHIP",
                source_id=r["person_id"], source_query="MATCH (p)-[:SAME_AS]-(o)",
                content=(f"Record for '{r['name_en']}' was linked to this person by "
                         f"probabilistic record linkage (confidence {r['confidence']:.2f}) — "
                         f"the same individual recorded under a different spelling."),
                confidence=float(r["confidence"])) for r in rows]
        else:
            # A *negative* finding is the answer here, and it has to be stated. Left
            # unsaid, unrelated context (a ToG path, a semantic match) becomes the
            # top citation and the officer is shown a reasoning chain in reply to a
            # yes/no question the records actually answer: no, there is no alias.
            out.append(EvidenceItem(
                evidence_id="same_as:none", source_type="GRAPH_RELATIONSHIP",
                source_id=pid, source_query="MATCH (p)-[:SAME_AS]-(o)",
                content=("No duplicate-identity (SAME_AS) links are recorded for this "
                         "person. Entity resolution found no other record matching them "
                         "under a different name or spelling."),
                confidence=0.9, authoritative=True))
        _trace(state, "Cypher Agent (SAME_AS)", f"{len(rows)} alias record(s)", t0)

    elif intent == "FINANCIAL" and pid:
        rows = graph_agent.money_trail(pid, role)
        state.graph_query_results += rows
        out += [EvidenceItem(
            evidence_id=f"flow:{r['from_account']}:{r['to_account']}",
            source_type="GRAPH_RELATIONSHIP", source_id=str(r["to_account"]),
            source_query="MATCH (a)-[:TRANSFERRED_TO*1..n]->(b)",
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
            out.append(EvidenceItem(
                evidence_id=f"flow:none:{pid}", source_type="GRAPH_RELATIONSHIP",
                source_id=str(pid),
                source_query="MATCH (p)-[:OWNS_ACCOUNT]->(a)-[:TRANSFERRED_TO*1..n]->(b)",
                content=("No bank account is linked to this person in the records, and "
                         "no transfers are traceable to them. This is an absence in the "
                         "financial layer, not a finding that no money moved."),
                confidence=0.9, authoritative=True))
        _trace(state, "Cypher Agent (money trail)", f"{len(rows)} transfer path(s)", t0)
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
        ct = _crime_type_from_query(state.original_query or "")
        district_name = state.active_entities.active_location
        count = sql_agent.count_firs(role, ps, crime_type=ct, district=district_name)
        scope_bits = [x for x in (ct, f"in {district_name}" if district_name else None) if x]
        scope_desc = " ".join(scope_bits) if scope_bits else "within your access scope"
        out.append(EvidenceItem(
            evidence_id=f"crime_count:{ct or 'any'}:{district_name or 'any'}",
            source_type="FIR_RECORD", source_id="count",
            source_query="COUNT over CaseMaster, scoped by role/station",
            content=f"{count} case(s) {scope_desc} are recorded within your access scope.",
            confidence=0.95, authoritative=True))
        if count:
            samples = sql_agent.search_firs(role, ps, crime_type=ct, district=district_name,
                                            limit=5)
            state.sql_query_results += samples
            out += [EvidenceItem(
                evidence_id=f"fir:{r['fir_id']}", source_type="FIR_RECORD",
                source_id=r["fir_id"], source_query="SELECT ... matching the count above",
                content=_fir_content(r), confidence=0.9) for r in samples]
        _trace(state, "SQL Agent (crime count)",
               f"{count} matching case(s){f' for {ct}' if ct else ''}"
               f"{f' in {district_name}' if district_name else ''}", t0)

    elif intent == "HOTSPOT":
        dc = _district_code(state)
        if dc:
            polys, ev = prediction_agent.hotspots(dc)
            state.prediction_results["detect_hotspots"] = polys
            out += ev
            # the incident scatter under the polygons — a hull with no points beneath
            # it is an assertion, not a hotspot
            state.sql_query_results += sql_agent.fir_points(dc)
            _trace(state, "Prediction Agent (hotspots)",
                   f"{len(polys)} cluster(s) over {len(state.sql_query_results)} incidents", t0)

    elif intent == "FORECAST":
        dc = _district_code(state)
        if dc:
            fc, ev = prediction_agent.forecast(dc)
            state.prediction_results["forecast_crime"] = fc
            out += ev
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
    """The CaseMasterIDs cited by a stored turn — every citation whose evidence_id
    follows the `fir:{id}` convention every FIR-producing branch in this module
    already uses (FIR_LOOKUP, CRIME_SEARCH, CASE_CONTEXT, SIMILAR_CASES)."""
    out = []
    for c in prior.citations:
        eid = c.get("evidence_id") or ""
        if eid.startswith("fir:"):
            out.append(eid.split(":", 1)[1])
    return out


def _handle_case_locations(state: InvestigationState, t0: float) -> None:
    """'Where are those cases concentrated?' — a district tally over the FIRs the
    PREVIOUS turn cited, re-checked against this officer's own policy scope before
    being shown (a citation from an earlier turn is not itself a permission)."""
    prior = _last_turn(state.session_id)
    fir_ids = _fir_ids_from_turn(prior) if prior else []
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


def _reasoning_explanation(prior) -> str:
    """'Why are you showing me these people?' — re-describe the previous turn's own
    agent trace, which is already the plain-language explainability surface the
    console's Reasoning Trace panel renders. Nothing new is inferred; this restates
    what that turn already recorded about itself."""
    steps = [t.get("detail") for t in prior.agent_trace if t.get("detail")]
    n = len(prior.citations)
    if steps:
        return (f'The previous answer to "{prior.query}" was built from {n} cited '
                f"record(s). How it got there: " + "; ".join(steps) + ".")
    return (f'The previous answer to "{prior.query}" cited {n} record(s) directly '
            f"relevant to that question.")


def _evidence_explanation(prior) -> str:
    """'What evidence supports that?' — the previous turn's own citation list, restated
    plainly rather than re-run through retrieval (which would search the index for the
    literal words 'what evidence supports that' and answer from whatever it found)."""
    if not prior.citations:
        return (f'The previous answer to "{prior.query}" carried no citations — it was '
                f"either a refusal or a description of this tool's own capabilities, not "
                f"a claim drawn from the records.")
    lines = [f'The previous answer to "{prior.query}" is supported by:']
    for c in prior.citations:
        lines.append(f"  [{c.get('index')}] {c.get('label')}")
    return "\n".join(lines)


def _crime_type_from_query(query: str) -> str | None:
    """Which of the 20 canonical crime types (if any) a question names — the longest
    match wins so "Motor Vehicle Theft" is not shadowed by the bare "Theft" it
    contains."""
    from data.generator.refdata import crime_type_names
    q = (query or "").lower()
    matches = [ct for ct in crime_type_names() if ct.lower() in q]
    return max(matches, key=len) if matches else None


def _district_code(state: InvestigationState) -> str | None:
    from data.districts import canonical_code
    loc = state.active_entities.active_location
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
        pool = prior.evidence_items or []
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

    if not ev and prior and not target:
        # No specific card was selected — "pin this" meaning "whatever you just
        # showed me". Only reached with no target at all; a target that failed to
        # resolve above must never silently fall back to a different item.
        pool = prior.evidence_items or []
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
        source_query="MATCH (p)-[:CO_ACCUSED_WITH*]-(o)",
        content=(f"{name} is a known associate ({r['hops']} hop(s) away"
                 # r['gang'] is already formatted "Community 47" (data/gds.py); lower-
                 # cased to match the "network community 6" phrasing used everywhere
                 # else this same derived grouping is shown (copilot/brief.py's leads).
                 + (f", network {r['gang'].lower()}" if r.get("gang") else "") + ")."),
        confidence=1.0 / max(1, int(r.get("hops") or 1)))


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
        answer = intents.capability_answer()
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
    if state.intent in ("EXPLAIN_REASONING", "EVIDENCE_FOR"):
        prior = _last_turn(state.session_id)
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

        answer = (_reasoning_explanation(prior) if state.intent == "EXPLAIN_REASONING"
                 else _evidence_explanation(prior))
        note = None
        if state.language != "en":
            answer, note = translation_agent.to_language(answer, state.language)
        if note:
            answer = f"{answer}\n\n{note}"
        state.final_answer = answer
        # Re-show the same citations the previous turn had — the officer asked what
        # backs THAT answer, not for a new one. evidence_items round-trips only when
        # the stored turn wasn't truncated (sessions._pack sheds it first under the
        # Data Store text-column cap); citations always survive, so they always show.
        state.citations = [Citation(**c) for c in prior.citations]
        state.evidence_items = [EvidenceItem(**e) for e in prior.evidence_items]
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
    answer, citations = synthesis_agent.synthesize(state.original_query or "", evidence)

    note = None
    if state.language != "en":
        answer, note = translation_agent.to_language(answer, state.language)
    if note:
        answer = f"{answer}\n\n{note}"

    state.final_answer = answer
    state.citations = citations
    state.evidence_items = evidence
    state.visualization = synthesis_agent.build_visualization(state.intent, state)
    _trace(state, "Evidence Synthesis",
           f"Answer grounded in {len(citations)} citation(s); "
           f"visualization: {state.visualization.kind}", t0)
    return state


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
    if state.intent in ("TIMELINE", "TIMELINE_CONNECTION"):
        # Already chronological (see _handle_timeline/_handle_timeline_connection) —
        # resorting by confidence would scramble the order that IS the answer.
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


def run_investigation(state: InvestigationState) -> InvestigationState:
    """The single entrypoint apps/api calls, once per turn."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    result = _GRAPH.invoke(state)
    return InvestigationState.model_validate(result)
