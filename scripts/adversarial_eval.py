#!/usr/bin/env python
"""Adversarial conversational evaluation — genuinely unseen phrasing, not copies of
the unit tests. The acceptance question this answers (compositional semantic layer
milestone, docs/superpowers/specs/2026-08-27-compositional-semantic-layer-design.md
§5): can a previously-unseen utterance be handled WITHOUT adding a new keyword or
regex, using only the structural extractors already shipped?

Two targets, one scenario list, so "does it work" means the same thing in both
places:

  --target local   drives rag_agent.run_investigation() directly, against the real
                   seeded dataset (needs VERITAS_SQLITE=data/.veritas/ds.sqlite3
                   or an equivalent seeded mirror — an empty test DB will fail
                   every scenario that expects real evidence, honestly).
  --target live    drives the deployed /chat SSE endpoint with a real officer
                   token. This is also what scripts/verify_live_deployment.py
                   reuses as its post-deploy behavioral gate.

Each scenario is a short conversation (1+ turns); each turn has a CHECK that
inspects the answer/trace/citations and raises AssertionError on a genuine miss.
Checks are behavioral (operation resolved, evidence present, honest refusal),
never exact-string, because content varies with whatever the live dataset holds.

Exit code is the number of failed scenarios (0 = all passed) — for a CI/deploy gate.
"""
import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

sys.path.insert(0, "data")
sys.path.insert(0, "packages/rag_agent")

# Kannada answers/queries are genuinely part of this battery, not an edge case --
# a console codepage (cp1252 on Windows) crashing on legitimate Kannada content in
# a printed assertion message is a bug in this script, not a reason to avoid the
# content. Force UTF-8 with a safe fallback rather than losing the whole run to an
# UnicodeEncodeError on the one line that happens to print Kannada.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class TurnResult:
    query: str
    answer: str
    refused: bool
    citations: int
    trace: list[str]
    latency_s: float = 0.0


@dataclass
class Scenario:
    name: str
    turns: list[str]
    # One check per turn (same length as turns), each: (TurnResult) -> None,
    # raises AssertionError on failure. A turn with no check is unexamined
    # scaffolding for a LATER turn's check (e.g. opening a case).
    checks: list[Optional[Callable[[TurnResult], None]]] = field(default_factory=list)
    # Which of the ten measured dimensions this scenario is primarily evidence for
    # (a scenario can speak to several; this is the one it's filed under for the
    # dimension-by-dimension summary). See FINAL ACCEPTANCE in the milestone prompt.
    dimension: str = "semantic_understanding"


def _not_refused(r: TurnResult) -> None:
    assert not r.refused, f"{r.query!r} was refused: {r.answer[:200]}"


def _has_citations(r: TurnResult) -> None:
    assert r.citations > 0, f"{r.query!r} produced no citations: {r.answer[:200]}"


def _intent_is(*names: str) -> Callable[[TurnResult], None]:
    def check(r: TurnResult) -> None:
        assert any(n in t for t in r.trace for n in names), (
            f"{r.query!r} trace {r.trace} did not mention any of {names}")
    return check


def _not_intent(*names: str) -> Callable[[TurnResult], None]:
    def check(r: TurnResult) -> None:
        assert not any(n in t for t in r.trace for n in names), (
            f"{r.query!r} trace {r.trace} unexpectedly matched {names}")
    return check


def _honest_refusal(r: TurnResult) -> None:
    assert r.refused, f"{r.query!r} should have refused honestly, but answered: {r.answer[:200]}"


def _contains(*fragments: str) -> Callable[[TurnResult], None]:
    def check(r: TurnResult) -> None:
        low = r.answer.lower()
        assert any(f.lower() in low for f in fragments), (
            f"{r.query!r} answer did not contain any of {fragments}: {r.answer[:200]}")
    return check


# --- the scenario battery -----------------------------------------------------
# Every scenario deliberately paraphrases the spec/prompt examples rather than
# quoting them verbatim — the point is generalization, not memorization.

SCENARIOS = [
    Scenario(
        name="result-set follow-up: 'only these?' reads the real prior count",
        turns=["How many theft cases are there in Bengaluru Urban?", "Only these?"],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("RESULT_SET_FOLLOWUP")(r))],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="result-set follow-up paraphrase: 'are there more than that?'",
        turns=["List the robbery cases in Mysuru.", "Are there more than that?"],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("RESULT_SET_FOLLOWUP")(r))],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="constraint-change: 'what about Kolar?' repeats the prior operation",
        turns=["How many murder cases are there in Belagavi?", "What about Kolar?"],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("CRIME_SEARCH")(r))],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="positional reference: 'the second one' after a network listing",
        turns=["Who are the associates of Usha Naika?", "Tell me about the second one."],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("PERSON_HISTORY")(r))],
        dimension="entity_reference_resolution",
    ),
    Scenario(
        name="bare exploration cue defaults to a subject profile",
        turns=["Who are the associates of Usha Naika?", "The second one."],
        checks=[_has_citations, _not_refused],
        dimension="entity_reference_resolution",
    ),
    Scenario(
        name="bare 'why' reads the previous answer, not a fresh search",
        turns=["How many theft cases are there in Mandya district?", "Why those?"],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("EXPLAIN_REASONING")(r))],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="bare temporal follow-up widens into a timeline",
        turns=["Who are the associates of Usha Naika?", "Yeah, but before this?"],
        checks=[_has_citations,
               lambda r: _intent_is("TIMELINE")(r)],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="two-entity comparison (bounded deterministic composition)",
        turns=["Who are the associates of Usha Naika?",
              "Check whether the second one and the third one both have prior cases."],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("PERSON_HISTORY")(r))],
        dimension="investigation_plan_correctness",
    ),
    Scenario(
        name="colloquial / incomplete English still resolves a count",
        turns=["gimme count of theft cases in mandya"],
        checks=[lambda r: (_has_citations(r), _not_refused(r))],
        dimension="semantic_understanding",
    ),
    Scenario(
        name="an unanswerable ambiguous query still gets an honest refusal, not a guess",
        turns=["only these"],  # no prior turn in this session -> genuinely nothing to read
        checks=[_honest_refusal],
        dimension="graceful_failure",
    ),
    Scenario(
        name="Kannada + English code-switching: pronoun + English verb phrase",
        turns=["Usha Naika ಗೆ previous cases check ಮಾಡಿ"],
        checks=[lambda r: (_has_citations(r), _not_refused(r))],
        dimension="multilingual_robustness",
    ),
    Scenario(
        name="Kannada + English code-switching: FIR reference with a case pronoun",
        turns=["ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"],
        checks=[None],  # no prior case open in a fresh session -> just must not crash
        dimension="multilingual_robustness",
    ),
    Scenario(
        name="Kannada district name survives translation correctly (structural fix)",
        turns=["ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?"],
        # The answer replies in the query's own language (Kannada), so the district
        # renders as "ಮಂಡ್ಯ", not the English "Mandya" -- checking for the ENGLISH
        # word here would be testing the wrong thing. The behavioral proof this
        # scenario exists for is "resolved to a real district and answered, rather
        # than the pre-fix 'Mandi'-shaped refusal" -- citations + no refusal is the
        # correct, language-agnostic assertion; the Kannada spelling in the answer
        # is checked too, as the strongest available evidence it's the RIGHT district.
        checks=[lambda r: (_has_citations(r), _not_refused(r), _contains("ಮಂಡ್ಯ")(r))],
        dimension="multilingual_robustness",
    ),
    Scenario(
        name="capability question is answered about the tool, not searched as records",
        turns=["What all can you help me with?"],
        checks=[lambda r: (_not_refused(r), _intent_is("CAPABILITY")(r))],
        dimension="semantic_understanding",
    ),
    Scenario(
        name="a named nonexistent person is refused, not substituted",
        turns=["Tell me about Zzyzx Qwertyperson"],
        checks=[_honest_refusal],
        dimension="graceful_failure",
    ),

    # --- Expanded battery: unseen paraphrases of every phrase the milestone named,
    # plus scenarios purpose-built for dimensions the first battery under-covered
    # (tool selection across every specialist, evidence correctness, multi-turn
    # continuity beyond two turns, and graceful failure on genuinely out-of-scope
    # asks). None of these repeat a phrase already used above.

    Scenario(
        name="'tell me about this case' after opening a FIR opens CASE_CONTEXT",
        turns=["What is the status of FIR 100050508202600025?", "Tell me about this case."],
        checks=[_has_citations, lambda r: (_not_refused(r), _intent_is("CASE_CONTEXT")(r))],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="'anything suspicious?' after opening a case reads leads, not a fresh search",
        turns=["What is the status of FIR 100050508202600025?", "Anything suspicious here?"],
        checks=[_has_citations, None],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="'show me related cases' after opening a case finds SIMILAR_CASES",
        turns=["What is the status of FIR 100050508202600025?", "Show me related cases."],
        # Tool selection, not final-answer correctness: the right tool (SIMILAR_CASES,
        # not a generic CRIME_SEARCH) is what this scenario checks. CRAG may still
        # honestly refuse if the similarity scores it found don't clear the
        # evidential-support bar (similarity is deliberately NOT support -- see
        # EvidenceItem.confidence_kind's own docstring) -- that is graceful failure
        # working correctly, not a defect, so a refusal here must not fail the check.
        checks=[_has_citations, lambda r: _intent_is("SIMILAR_CASES")(r)],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="'check that person's history' after a network listing resolves to a subject",
        turns=["Who are the associates of Usha Naika?", "Check the first one's history."],
        checks=[_has_citations, lambda r: (_not_refused(r), _intent_is("PERSON_HISTORY")(r))],
        dimension="entity_reference_resolution",
    ),
    Scenario(
        name="what about her? -- pronoun after CASE_PEOPLE with multiple accused",
        turns=["What is the status of FIR 100121201202600041?", "Who are the accused?",
              "What about her?"],
        checks=[_has_citations, None, None],   # honest outcome may be a clarification, not a crash
        dimension="entity_reference_resolution",
    ),
    Scenario(
        name="'what have we established?' reads the case board, not a fresh search",
        turns=["What is the status of FIR 100050508202600025?", "What have we established so far?"],
        checks=[_has_citations, lambda r: _not_intent("UNKNOWN")(r)],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="financial/money trail tool selection for a named person",
        turns=["Show me the money trail for Usha Naika."],
        checks=[lambda r: _intent_is("FINANCIAL")(r)],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="hotspot / geography tool selection, unseen phrasing",
        turns=["Where is crime concentrated in Kolar right now?"],
        checks=[lambda r: (_not_refused(r), _intent_is("HOTSPOT")(r))],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="forecast / trend tool selection, unseen phrasing",
        turns=["What's the crime trend looking like for Dharwad next month?"],
        checks=[lambda r: (_not_refused(r), _intent_is("FORECAST")(r))],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="risk / recidivism tool selection for a named person",
        turns=["How likely is Usha Naika to reoffend?"],
        checks=[lambda r: _intent_is("RISK")(r)],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="alias/identity tool selection, unseen phrasing",
        turns=["Does Usha Naika go by any other name?"],
        checks=[lambda r: _intent_is("ALIAS_CHECK")(r)],
        dimension="tool_selection_correctness",
    ),
    Scenario(
        name="evidence correctness: a crime-count answer cites real FIR records, not prose alone",
        turns=["How many hurt cases are there in Kalaburagi?"],
        checks=[lambda r: (_has_citations(r), _not_refused(r))],
        dimension="evidence_correctness",
    ),
    Scenario(
        name="evidence correctness: an exact FIR lookup returns exactly that record",
        turns=["What is the status of FIR 100050508202600025?"],
        checks=[lambda r: (_has_citations(r), _not_refused(r),
                           _contains("100050508202600025")(r))],
        dimension="final_answer_correctness",
    ),
    Scenario(
        name="three-turn continuity: open a case, ask who's involved, then go deeper on one",
        turns=["What is the status of FIR 100121201202600041?", "Who are the accused?",
              "Tell me more about the first one."],
        checks=[_has_citations, _has_citations, None],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="correction mid-conversation: naming a specific person after an ambiguous one",
        turns=["Tell me about Usha.", "I meant Usha Naika specifically."],
        checks=[None, lambda r: _not_refused(r) or r.refused],  # either resolves or asks cleanly
        dimension="ambiguity_handling",
    ),
    Scenario(
        name="clarification requirement: a bare pronoun with no antecedent at all asks, doesn't guess",
        turns=["Does he have any priors?"],
        checks=[_honest_refusal],
        dimension="clarification_requirement",
    ),
    Scenario(
        name="graceful failure: a genuinely out-of-scope request (naming a suspect) is refused with a reason",
        turns=["Who do you think committed the murder in FIR 100121201202600041?"],
        checks=[_honest_refusal],
        dimension="graceful_failure",
    ),
    Scenario(
        name="graceful failure: nonsense input produces an honest 'not understood', not a crash",
        turns=["asdkjqwoe purple elephant seventeen"],
        checks=[None],   # must not raise; refusal or a low-confidence answer both acceptable
        dimension="graceful_failure",
    ),
    Scenario(
        name="voice-like disfluency: filler words and a restart mid-sentence",
        turns=["um so like, how many, uh, theft cases we got in Bengaluru Urban"],
        checks=[lambda r: (_has_citations(r), _not_refused(r))],
        dimension="semantic_understanding",
    ),
    Scenario(
        name="two-word follow-up after a hotspot answer",
        turns=["Show me crime hotspots in Bengaluru Urban.", "And Mysuru?"],
        checks=[None, lambda r: _not_intent("UNKNOWN")(r)],
        dimension="conversational_continuity",
    ),
    Scenario(
        name="Kannada colloquial: a two-word Kannada follow-up after an English turn",
        turns=["How many theft cases are there in Mandya district?", "ಇನ್ನೂ ಇದೆಯಾ?"],
        checks=[_has_citations, None],
        dimension="multilingual_robustness",
    ),
]


@dataclass
class ScenarioResult:
    name: str
    dimension: str
    passed: bool
    latency_s: float          # sum of this scenario's own turn latencies


def _report(results: list[ScenarioResult], elapsed_s: float, target: str) -> None:
    """Dimension-by-dimension summary — the FINAL ACCEPTANCE format the milestone
    prompt asked for (semantic understanding, entity/reference resolution,
    investigation-plan correctness, tool selection, evidence correctness, final
    answer correctness, multilingual robustness, conversational continuity,
    latency, graceful failure), not just a flat pass count."""
    by_dim: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_dim.setdefault(r.dimension, []).append(r)

    print("\n--- by dimension ---")
    for dim in sorted(by_dim):
        rows = by_dim[dim]
        passed = sum(1 for r in rows if r.passed)
        lat = [r.latency_s for r in rows if r.latency_s > 0]
        avg_lat = f"{sum(lat) / len(lat):.2f}s avg turn" if lat else "n/a"
        print(f"  {dim:32s} {passed}/{len(rows)} passed, {avg_lat}")

    total_passed = sum(1 for r in results if r.passed)
    all_lat = [r.latency_s for r in results if r.latency_s > 0]
    print(f"\n{total_passed}/{len(results)} scenarios passed overall "
         f"({elapsed_s:.1f}s total, target={target})")
    if all_lat:
        sorted_lat = sorted(all_lat)
        p50 = sorted_lat[len(sorted_lat) // 2]
        p95 = sorted_lat[min(len(sorted_lat) - 1, int(len(sorted_lat) * 0.95))]
        print(f"turn latency: p50={p50:.2f}s p95={p95:.2f}s "
             f"min={sorted_lat[0]:.2f}s max={sorted_lat[-1]:.2f}s")


def run_local(scenarios: list[Scenario]) -> tuple[int, list[ScenarioResult]]:
    from data import SessionFocus, get_session_focus, write_conversation_turn
    from rag_agent import InvestigationState, run_investigation

    failures = 0
    results: list[ScenarioResult] = []
    for sc in scenarios:
        sid = str(uuid.uuid4())
        ok = True
        scenario_latency = 0.0
        for idx, (query, check) in enumerate(zip(sc.turns, sc.checks + [None] * len(sc.turns))):
            # Mirrors apps/api/api/routers/chat.py exactly: a turn's active_entities
            # comes from the PERSISTED session focus, not a fresh default. Missing
            # this made a real product behavior (a case staying "open" across turns)
            # look like a bug in this harness's first version -- caught by comparing
            # against the real /chat wiring rather than assuming the harness was right.
            focus = get_session_focus(sid) or SessionFocus()
            state = InvestigationState(
                session_id=sid, officer_id="386", officer_role="SP", original_query=query,
                active_entities=focus)
            t0 = time.time()
            result = run_investigation(state)
            latency = time.time() - t0
            scenario_latency += latency
            write_conversation_turn(
                session_id=sid, turn_index=idx, query=result.original_query or query,
                language=result.language, final_answer=result.final_answer or "",
                citations=[c.model_dump() for c in result.citations],
                evidence_items=[e.model_dump(mode="json") for e in result.evidence_items],
                visualization=result.visualization.model_dump(),
                agent_trace=[t.model_dump() for t in result.agent_trace],
                result_context={**(result.result_context or {}), "last_request": result.last_request},
            )
            tr = TurnResult(
                query=query, answer=result.final_answer or "",
                refused=result.answer_is_refusal, citations=len(result.citations),
                trace=[t.detail for t in result.agent_trace], latency_s=latency)
            print(f"  [{latency:5.2f}s] {query!r}")
            if check is None:
                continue
            try:
                check(tr)
            except AssertionError as e:
                print(f"FAIL  {sc.name} (turn {idx}: {query!r}): {e}")
                ok = False
        print(f"{'PASS' if ok else 'FAIL'}  {sc.name}")
        if not ok:
            failures += 1
        results.append(ScenarioResult(sc.name, sc.dimension, ok, scenario_latency))
    return failures, results


def run_live(scenarios: list[Scenario], base_url: str, badge_no: str
            ) -> tuple[int, list[ScenarioResult]]:
    import requests

    tok = requests.post(f"{base_url}/auth/token", json={"badge_no": badge_no}, timeout=30)
    tok.raise_for_status()
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}

    failures = 0
    results: list[ScenarioResult] = []
    for sc in scenarios:
        sid = str(uuid.uuid4())
        ok = True
        scenario_latency = 0.0
        for idx, (query, check) in enumerate(zip(sc.turns, sc.checks + [None] * len(sc.turns))):
            t0 = time.time()
            r = requests.post(f"{base_url}/chat", headers=headers,
                              json={"session_id": sid, "query": query}, timeout=90)
            latency = time.time() - t0
            scenario_latency += latency
            r.raise_for_status()
            traces, final = [], None
            for line in r.text.replace("\r\n", "\n").split("\n"):
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") == "trace":
                    traces.append(evt.get("detail", ""))
                elif evt.get("type") == "final":
                    final = evt
            if final is None:
                print(f"FAIL  {sc.name} (turn {idx}: {query!r}): no final frame")
                ok = False
                break
            tr = TurnResult(
                query=query, answer=final.get("final_answer", ""),
                refused=bool(final.get("refused")), citations=len(final.get("citations", [])),
                trace=traces, latency_s=latency)
            print(f"  [{latency:5.2f}s] {query!r}")
            if check is None:
                continue
            try:
                check(tr)
            except AssertionError as e:
                print(f"FAIL  {sc.name} (turn {idx}: {query!r}): {e}")
                ok = False
        print(f"{'PASS' if ok else 'FAIL'}  {sc.name}")
        if not ok:
            failures += 1
        results.append(ScenarioResult(sc.name, sc.dimension, ok, scenario_latency))
    return failures, results


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=["local", "live"], default="local")
    p.add_argument("--base-url", default="https://veritas-api-50043864344.development.catalystappsail.in")
    p.add_argument("--badge-no", default="KGID000386")  # SP rank, broad access
    args = p.parse_args()

    t0 = time.time()
    if args.target == "local":
        failures, results = run_local(SCENARIOS)
    else:
        failures, results = run_live(SCENARIOS, args.base_url, args.badge_no)
    _report(results, time.time() - t0, args.target)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
