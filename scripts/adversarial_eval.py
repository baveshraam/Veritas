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


@dataclass
class TurnResult:
    query: str
    answer: str
    refused: bool
    citations: int
    trace: list[str]


@dataclass
class Scenario:
    name: str
    turns: list[str]
    # One check per turn (same length as turns), each: (TurnResult) -> None,
    # raises AssertionError on failure. A turn with no check is unexamined
    # scaffolding for a LATER turn's check (e.g. opening a case).
    checks: list[Optional[Callable[[TurnResult], None]]] = field(default_factory=list)


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
    ),
    Scenario(
        name="result-set follow-up paraphrase: 'are there more than that?'",
        turns=["List the robbery cases in Mysuru.", "Are there more than that?"],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("RESULT_SET_FOLLOWUP")(r))],
    ),
    Scenario(
        name="constraint-change: 'what about Kolar?' repeats the prior operation",
        turns=["How many murder cases are there in Belagavi?", "What about Kolar?"],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("CRIME_SEARCH")(r))],
    ),
    Scenario(
        name="positional reference: 'the second one' after a network listing",
        turns=["Who are the associates of Usha Naika?", "Tell me about the second one."],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("PERSON_HISTORY")(r))],
    ),
    Scenario(
        name="bare exploration cue defaults to a subject profile",
        turns=["Who are the associates of Usha Naika?", "The second one."],
        checks=[_has_citations, _not_refused],
    ),
    Scenario(
        name="bare 'why' reads the previous answer, not a fresh search",
        turns=["How many theft cases are there in Mandya district?", "Why those?"],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("EXPLAIN_REASONING")(r))],
    ),
    Scenario(
        name="bare temporal follow-up widens into a timeline",
        turns=["Who are the associates of Usha Naika?", "Yeah, but before this?"],
        checks=[_has_citations,
               lambda r: _intent_is("TIMELINE")(r)],
    ),
    Scenario(
        name="two-entity comparison (bounded deterministic composition)",
        turns=["Who are the associates of Usha Naika?",
              "Check whether the second one and the third one both have prior cases."],
        checks=[_has_citations,
               lambda r: (_not_refused(r), _intent_is("PERSON_HISTORY")(r))],
    ),
    Scenario(
        name="colloquial / incomplete English still resolves a count",
        turns=["gimme count of theft cases in mandya"],
        checks=[lambda r: (_has_citations(r), _not_refused(r))],
    ),
    Scenario(
        name="an unanswerable ambiguous query still gets an honest refusal, not a guess",
        turns=["only these"],  # no prior turn in this session -> genuinely nothing to read
        checks=[_honest_refusal],
    ),
    Scenario(
        name="Kannada + English code-switching: pronoun + English verb phrase",
        turns=["Usha Naika ಗೆ previous cases check ಮಾಡಿ"],
        checks=[lambda r: (_has_citations(r), _not_refused(r))],
    ),
    Scenario(
        name="Kannada + English code-switching: FIR reference with a case pronoun",
        turns=["ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"],
        checks=[None],  # no prior case open in a fresh session -> just must not crash
    ),
    Scenario(
        name="Kannada district name survives translation correctly (structural fix)",
        turns=["ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?"],
        checks=[lambda r: (_has_citations(r), _contains("mandya")(r))],
    ),
    Scenario(
        name="capability question is answered about the tool, not searched as records",
        turns=["What all can you help me with?"],
        checks=[lambda r: (_not_refused(r), _intent_is("CAPABILITY")(r))],
    ),
    Scenario(
        name="a named nonexistent person is refused, not substituted",
        turns=["Tell me about Zzyzx Qwertyperson"],
        checks=[_honest_refusal],
    ),
]


def run_local(scenarios: list[Scenario]) -> int:
    from data import write_conversation_turn
    from rag_agent import InvestigationState, run_investigation

    failures = 0
    for sc in scenarios:
        sid = str(uuid.uuid4())
        ok = True
        for idx, (query, check) in enumerate(zip(sc.turns, sc.checks + [None] * len(sc.turns))):
            state = InvestigationState(
                session_id=sid, officer_id="386", officer_role="SP", original_query=query)
            result = run_investigation(state)
            write_conversation_turn(
                session_id=sid, turn_index=idx, query=result.original_query or query,
                language=result.language, final_answer=result.final_answer or "",
                citations=[c.model_dump() for c in result.citations],
                evidence_items=[e.model_dump(mode="json") for e in result.evidence_items],
                visualization=result.visualization.model_dump(),
                agent_trace=[t.model_dump() for t in result.agent_trace],
                result_context=result.result_context,
            )
            tr = TurnResult(
                query=query, answer=result.final_answer or "",
                refused=result.answer_is_refusal, citations=len(result.citations),
                trace=[t.detail for t in result.agent_trace])
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
    return failures


def run_live(scenarios: list[Scenario], base_url: str, badge_no: str) -> int:
    import requests

    tok = requests.post(f"{base_url}/auth/token", json={"badge_no": badge_no}, timeout=30)
    tok.raise_for_status()
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}

    failures = 0
    for sc in scenarios:
        sid = str(uuid.uuid4())
        ok = True
        for idx, (query, check) in enumerate(zip(sc.turns, sc.checks + [None] * len(sc.turns))):
            r = requests.post(f"{base_url}/chat", headers=headers,
                              json={"session_id": sid, "query": query}, timeout=90)
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
                trace=traces)
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
    return failures


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=["local", "live"], default="local")
    p.add_argument("--base-url", default="https://veritas-api-50043864344.development.catalystappsail.in")
    p.add_argument("--badge-no", default="KGID000386")  # SP rank, broad access
    args = p.parse_args()

    t0 = time.time()
    if args.target == "local":
        failures = run_local(SCENARIOS)
    else:
        failures = run_live(SCENARIOS, args.base_url, args.badge_no)
    print(f"\n{len(SCENARIOS) - failures}/{len(SCENARIOS)} scenarios passed "
         f"({time.time() - t0:.1f}s, target={args.target})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
