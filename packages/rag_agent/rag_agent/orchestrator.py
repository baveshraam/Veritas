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

from data import ds, upsert_session_focus

from . import intents
from .agents import (
    graph_agent, prediction_agent, sql_agent, synthesis_agent,
    translation_agent, vector_agent, voice_agent,
)
from .evidence.evaluator import evaluate, refusal_message, supporting
from .retrieval import hipporag, tog
from .state import AgentTraceEntry, EvidenceItem, InvestigationState

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
        if hits:
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
    if state.intent in intents.NEEDS_SUBJECT and not pid and not state.refusal_reason:
        state.refusal_reason = "no_subject"
        _trace(state, "Orchestrator",
               f"{state.intent} needs a named subject; none given", t0)
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
        out += [_network_evidence(r) for r in rows]
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
                confidence=0.9))
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
        _trace(state, "Cypher Agent (money trail)", f"{len(rows)} transfer path(s)", t0)
        for acct in {r["from_account"] for r in rows}:
            _, ev = prediction_agent.transactions(acct)
            out += ev
            break

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

    # Vector search complements the graph on narrative/MO semantics — but NOT when the
    # question named one record and we found it. "What is the status of FIR X" is a
    # yes/no claim about a single row; the nearest narratives to it are cases about
    # something else, and attaching them to the answer makes a correct lookup look like
    # a fishing expedition. An exact identifier hit is the whole answer.
    if state.exact_lookup_hit:
        _trace(state, "Vector Search Agent",
               "Skipped — the query named a record and the exact lookup found it", t0)
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


def _fir_evidence(r: dict) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"fir:{r['fir_id']}", source_type="CRIMINAL_RECORD",
        source_id=str(r["fir_id"]),
        source_query="SELECT ... FROM criminal_record JOIN fir",
        content=_fir_content(r) + (" Convicted." if r.get("conviction") else ""),
        confidence=0.95)


def _network_evidence(r: dict) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"assoc:{r['person_id']}", source_type="GRAPH_RELATIONSHIP",
        source_id=str(r["person_id"]),
        source_query="MATCH (p)-[:CO_ACCUSED_WITH*]-(o)",
        content=(f"{r['name_en']} is a known associate ({r['hops']} hop(s) away"
                 + (f", gang: {r['gang']}" if r.get("gang") else "") + ")."),
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

    if state.requires_escalation:
        reason = state.refusal_reason or "no_evidence"
        answer = refusal_message(reason)
        note = None
        if state.language != "en":
            answer, note = translation_agent.to_language(answer, state.language)
        if note:
            answer = f"{answer}\n\n{note}"
        state.final_answer = answer
        state.citations = []
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
    if state.refusal_reason:
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
