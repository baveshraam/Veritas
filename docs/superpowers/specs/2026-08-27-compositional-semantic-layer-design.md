# Compositional semantic layer — design spec

**Status**: approved for implementation planning
**Supersedes nothing** — extends the §5.1 semantic-interpreter migration (commit `83b8695`)
already merged into `main`. This is phases 2-5 of the roadmap that migration's own
`ENGINEERING_BRIEF.md` §5/§6/§12 named as follow-up work.

## 0. Why this document exists

The originating request asked for a complete conversational-architecture overhaul: natural
Kannada/English/code-switched input, pronoun and positional reference resolution, result-set
awareness ("only these?"), multi-step investigative planning, and a live-verified deploy. Most
of this is not new — it is already tracked, in the same terms, in `ENGINEERING_BRIEF.md` §5-§12,
and §5.1 (replacing the flat 30-intent classifier with a structured `SemanticRequest`) already
shipped. This spec is the next slice: §5.2 (generalized reference resolution), §5.3 (result-set
awareness), a new multi-step composition capability, §5.4/§10's code-switching entity-extraction
half (not the two named untouchable translation-quality bugs), an adversarial eval set, and an
automated live-deployment verification gate.

**Hard platform constraint that shapes every phase below**: `QUICKML_ENDPOINT_KEY` is unset on
the live AppSail app (re-confirmed directly against the live `configuration` object this pass,
not carried forward from a prior check — see §7). The LLM path in `semantic_interpreter.py`
therefore cannot be live-verified. Everything in this spec that must be demoed working today is
deterministic. Where deterministic logic would otherwise degrade into "one regex per new
sentence" (the anti-pattern the originating request explicitly forbids), the fix is to build a
small number of **structural** extractors that compose with any operation/subject, not a
keyword/phrase list — detailed per-phase below. The LLM path stays wired and activates with zero
further code change the moment a key exists, exactly as §5.1 already established.

## 1. Baseline (captured before any change)

- Git HEAD: `83b869549ddedaac13a10a638d7e03bb0234057d`
- AppSail app id: `52852000000204688` (not the `50043864344` host-subdomain number used in
  older changelog prose — confirmed by listing `/appsail` directly)
- Live deployment id: `52852000000360005`, deployed 2026-08-27 16:30 IST, status `success`
- `/health`: `llm: quickml (glm-4.7-flash) — configured, not yet contacted`, `datastore:
  catalyst`, `firs: 10000`, `graph: 16918 nodes / 87120 edges`, `vector_index: 13835 docs`,
  `cache: catalyst`, `model_weights: configured, not yet fetched`, `nllb_backend: not yet
  loaded`
- `QUICKML_ENDPOINT_KEY`: absent from the live app's `configuration.environment.variables`
  (direct check)
- Live-reproduced defect (the concrete target for Phase 1): session turn 1 "How many theft
  cases are there in Bengaluru Urban?" → real count + 5 sampled citations. Turn 2 "Only
  these?" → `Intent: UNKNOWN` → CRAG widens twice, finds nothing, refuses with
  `no_evidence`. This is exactly §5.3's named gap, reproduced live, not assumed.

Phase 5's verification script re-runs this exact two-turn sequence (plus others) post-deploy
and asserts turn 2 no longer refuses.

## 2. Phase 1 — reference + result-set layer

### 2.1 Data model

`data/data/models.py` — add to `ConversationTurn`:

```python
result_context: dict[str, Any] = {}
# shape when populated: {"operation": str, "total_matched": int | None,
#                         "shown": int, "is_sample": bool, "shown_ids": list[str]}
```

`data/data/sessions.py`:
- `write_conversation_turn(...)` gains a `result_context: dict` parameter, folded into the
  same JSON blob `_pack()` already builds (alongside `citations`/`evidence_items`/
  `visualization`/`agent_trace`). It is small (a handful of scalars + an id list capped at
  the same 5 ids already sampled) so it never triggers the truncation path, and is listed
  among the fields that survive truncation regardless (same tier as citations/trace).
- `get_conversation_history(...)` reads it back onto `ConversationTurn.result_context`.

`packages/rag_agent/rag_agent/state.py` — add `InvestigationState.result_context: dict = {}`.

`apps/api/api/routers/chat.py` — pass `result.result_context` into the existing
`write_conversation_turn(...)` call (~line 135).

### 2.2 Producers

In `orchestrator.py::_run_specialists`, at the existing `CRIME_SEARCH` branch (~line 443-470),
right after `count`/`samples` are computed:

```python
state.result_context = {
    "operation": "CRIME_SEARCH",
    "total_matched": count,
    "shown": len(samples) if count else 0,
    "is_sample": count > len(samples) if count else False,
    "shown_ids": [r["fir_id"] for r in samples] if count else [],
}
```

Same pattern added at the equivalent sampling points already present in `PERSON_NETWORK`,
`ALIAS_CHECK`, and `SIMILAR_CASES` (each already caps a result list — this only records the
cap, it does not change retrieval behavior).

### 2.3 Reference resolution — structural extractors

New functions in `semantic_interpreter.py`, each a general pattern matched against *any*
prior turn, not a phrase list per operation:

- `_ordinal_reference(q) -> Optional[int]` — "the second one" / "item 2" / "number three" →
  a 0-based index. Small closed set of ordinal words + digit forms (English only; this is a
  genuinely closed linguistic category, unlike open-ended intent phrasing, so it does not
  grow the way keyword lists do).
- `_is_exhaustiveness_query(q) -> bool` — "only these?", "is that all?", "are there more?",
  "anything else in the records?". Reads `prior_turn.result_context`; if `is_sample`, answers
  "N more of M total, here are the next 5" via a re-run of the *same* bounded query with an
  offset; if not `is_sample`, answers "that's all of them, N total" — both branches read the
  real stored fact, neither guesses.
- `_is_constraint_change(q) -> Optional[dict]` — detects a bare location/date/crime-type
  phrase with no operation verb ("same thing for Bengaluru", "what about last month") and, if
  matched, reuses `prior_turn.result_context["operation"]` as the operation with the new
  constraint overlaid.
- `_exploration_cue(q) -> Optional[str]` — "go deeper" / "what else" / "show more" →
  `exploration_direction`.

`_extract_constraints()` (currently a stub) is filled by relocating the orchestrator's
existing `_crime_type_from_query` / `_district_code` / date-range extraction here — a move,
not a rewrite, so existing single-turn behavior is provably unchanged (covered by the
existing per-intent tests, which stay green).

### 2.4 Orchestrator wiring

Three new branches in `node_retrieve`, following the exact shape of the existing
`_handle_case_locations` (`orchestrator.py:725-758`) — read prior turn, re-check RBAC against
*this* officer before reusing anything, answer or refuse honestly:

- `reference_kind == "exhaustiveness_check"` → `_handle_more_results()`
- `reference_kind == "positional"` → resolve `subject_id` from
  `prior_turn.citations[index]`, then fall through the *normal* per-operation path as if that
  subject had been typed explicitly (no new retrieval code path)
- `reference_kind == "constraint_change"` → set `state.intent` from
  `previous_result_context["operation"]`, apply the new constraint, fall through normally

### 2.5 Testing

New `test_reference_resolution.py` / extends `test_semantic_interpreter.py`: each extractor
unit-tested against paraphrases (not copies) of its trigger phrase; two live-reproducing
regression tests for the exact baseline defect in §1 (confirmed to fail against pre-fix code
first, per this repo's own testing discipline).

## 3. Phase 2 — deterministic multi-step composition

Scope: the originating request's own literal example — "check whether either of those people
had a prior case in Bengaluru around the same time" — and structurally similar two-entity
comparisons. Not open-ended multi-clause planning; that is named as the thing that needs the
LLM path (consistent with how every other LLM-shaped gap in this codebase is already handled
per §12: build the deterministic floor, wire the LLM path to activate for free later).

`semantic_interpreter.py` gains `_plan_multi_step(...)`, triggered by a small explicit
coordination grammar ("either of", "both of", "and also", "as well") combined with 2+ resolved
`comparison_entities` (from `prior_turn`'s candidate list or explicit names). It returns
`list[SemanticRequest]` instead of one.

`node_orchestrate`/`node_retrieve`: when the interpreter returns a list, loop the *existing*
single-subject retrieval path once per sub-request — same RBAC checks, same evidence
evaluator, same citation chain per subject, no shortcut and no cross-subject invention.
`node_synthesize` merges the two (or more) evidence sets, tagged by subject, into one
side-by-side answer, each half independently cited.

**Explicit non-goal, stated up front rather than discovered late**: this does not attempt
arbitrary N-step planning, temporal-relation chaining beyond what `TIMELINE`/
`TIMELINE_CONNECTION` already do, or cross-operation joins the record layer cannot itself
answer in ≤4 JOINs (Data Store's own cap, §3 of `CLAUDE.md`).

## 4. Phase 3 — code-switching structural hardening

### 4.1 District-name protection

`data/data/seed/karnataka_districts.csv` gains a `kannada_names` column (pipe-separated, same
convention as the existing `aliases` column), sourced from a verifiable public reference (not
guessed) during implementation, and round-trip-tested per entry.

`data/data/nlp/translate.py::_protect_spans` gains a second pass, active only for `src == "kn"`:
any span matching a known Kannada district spelling is replaced with a placeholder whose
restore value is the *canonical English name* (a lookup substitution), not the original
Kannada text — unlike the existing FIR/IPC/plate protection, which restores verbatim. This
closes the whole class the "ಮಂಡ್ಯ"→"Mandi" bug belongs to, for all 31 districts, structurally
— not a patch for the one instance found.

### 4.2 Dual-text entity extraction

`node_translate_in` currently overwrites `state.original_query` with the English translation
and nothing downstream ever sees the Kannada again. Add `state.original_query_kn: Optional[str]`,
set before translation. `semantic_interpreter._interpret_deterministic` and
`intents.resolve_focus` gain the option to run district/IPC/plate extraction directly against
`original_query_kn` when present (via the new Kannada gazetteer from §4.1 plus the existing
script-independent digit/plate regexes), so these closed-format entities no longer depend on
translation quality at all. Person-name extraction stays translation-dependent — no closed
gazetteer is possible for arbitrary names — and this limit is stated, not silently left
implied.

### 4.3 Explicitly not attempted

The "priorities" mistranslation (§10) stays open. Investigated as part of this spec's own
prep: blind suffix-stemming of intent keywords (so "priorities" folds toward "prior") was
considered and rejected — it would make "this is a high priority case" spuriously score
`PERSON_HISTORY`. No principled deterministic fix exists; this needs the LLM path, exactly as
`ENGINEERING_BRIEF.md` §10 already concludes. Restated here so this pass doesn't quietly
re-attempt something already ruled out.

## 5. Phase 4 — adversarial conversational eval set

New `scripts/adversarial_eval.py` + fixture file, `--target local` (drives
`rag_agent.run_investigation()` directly) and `--target live` (drives the real `/chat` SSE
endpoint with a signed-in officer token). Cases are genuinely new phrasing — not copies of
existing unit tests — covering every category the originating request listed: incomplete
English, colloquial phrasing, Kannada, code-switching, voice-like disfluency, pronouns,
ordinals, exhaustiveness follow-ups, exploration cues, corrections, the Phase 2 multi-step
example, and deliberately ambiguous/unanswerable queries (asserting an honest refusal, not a
guess). Assertions are behavioral (operation resolved / evidence present / refusal reason),
never exact string matches, since phrasing is not deterministic even on the deterministic
path (evidence content varies with the live dataset).

## 6. Phase 5 — checkable live-deployment verification

`scripts/verify_live_deployment.py`: given an API base URL, signs in, hits `/health` (asserts
expected fields present, not just 200), then runs a fixed probe battery specifically chosen to
distinguish *old* from *new* behavior — the exact two-turn `CRIME_SEARCH` → `"Only these?"`
sequence from §1 is the primary probe, since it is already confirmed to fail on the current
live deployment. Non-zero exit on any probe failure. Run by hand post-deploy for this pass;
wiring it into `.github/workflows/relay-deploy.yml` as a post-deploy gate is named as a
natural follow-up, not built this pass, to keep the deploy pipeline change itself reviewable
separately from the semantic-layer change.

## 7. What "done" looks like

Per the originating request's own acceptance list: full test suite green, adversarial set
green against local, git commit, push, relay-deploy run, AppSail deployment id changed,
`/health` reflects the new build, `verify_live_deployment.py` passes against the live URL
(specifically: the §1 baseline defect is fixed live), and the live console re-checked via CDP
for the one visible surface this touches (a follow-up like "only these?" rendering as a real
answer, not a refusal, in the chat pane). `ENGINEERING_BRIEF.md` §5/§6/§8/§10/§12 updated in
place and a changelog entry appended — no new handoff/status document, per this repo's own
standing rule.

## 8. Explicit out-of-scope, carried from the brainstorming pass

Re-attempting to obtain `QUICKML_ENDPOINT_KEY` (already investigated twice, blocked for
reasons outside API access); voice-specific handling (already generic, confirmed in §11);
IndicTrans2 migration (a licensing/ops decision, not an architecture one); true N-step
temporal/causal planning beyond §3's two-entity comparison.
