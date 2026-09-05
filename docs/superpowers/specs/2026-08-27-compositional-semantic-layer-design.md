# Compositional semantic layer — design spec

**Status**: implemented (v17, per `CLAUDE.md`'s changelog). Kept as a historical design
record — the data structures and interfaces below are still how the shipped code works.
Extends the §5.1 semantic-interpreter migration (commit `83b8695`) already merged into `main`.

## 0. Scope

Follow-on to §5.1 (structured `SemanticRequest` replacing the flat 30-intent classifier):
generalized reference resolution, result-set awareness ("only these?"), bounded multi-step
composition, code-switching entity extraction (district-name gazetteer half only — not the
two untouchable translation-quality bugs), an adversarial eval set, and a live-deployment
verification gate.

**Constraint that shaped every phase**: `QUICKML_ENDPOINT_KEY` was unset on the live app at
design time, so the LLM path in `semantic_interpreter.py` could not be live-verified.
Everything demoed had to be deterministic. Where deterministic logic would otherwise become
"one regex per new sentence," the fix is a small number of **structural** extractors that
compose with any operation/subject, not a keyword list. The LLM path stays wired and activates
with zero further code change once a key exists (per §5.1).

## 1. Baseline (captured before change)

- Git HEAD: `83b869549ddedaac13a10a638d7e03bb0234057d`; live deployment `52852000000360005`
- `/health`: 10,000 FIRs, graph 16,918n/87,120e, 13,835 indexed vectors; QuickML configured but
  uncontacted (`QUICKML_ENDPOINT_KEY` absent)
- **Live-reproduced defect (Phase 1's target)**: turn 1 "How many theft cases are there in
  Bengaluru Urban?" → real count + 5 sampled citations. Turn 2 "Only these?" → `Intent: UNKNOWN`
  → CRAG widens twice, refuses with `no_evidence`. Phase 5's verification script re-runs this
  exact sequence post-deploy and asserts turn 2 no longer refuses.

## 2. Phase 1 — reference + result-set layer

### 2.1 Data model

`data/data/models.py` — add to `ConversationTurn`:

```python
result_context: dict[str, Any] = {}
# shape when populated: {"operation": str, "total_matched": int | None,
#                         "shown": int, "is_sample": bool, "shown_ids": list[str]}
```

`data/data/sessions.py`: `write_conversation_turn(...)` gains a `result_context` param, folded
into the same JSON blob `_pack()` builds (alongside `citations`/`evidence_items`/
`visualization`/`agent_trace`) — small, never triggers truncation, survives it regardless.
`get_conversation_history(...)` reads it back onto `ConversationTurn.result_context`.

`packages/rag_agent/rag_agent/state.py` — `InvestigationState.result_context: dict = {}`.
`apps/api/api/routers/chat.py` passes `result.result_context` into the existing
`write_conversation_turn(...)` call.

### 2.2 Producers

In `orchestrator.py::_run_specialists`, at the `CRIME_SEARCH` branch, right after
`count`/`samples` are computed:

```python
state.result_context = {
    "operation": "CRIME_SEARCH",
    "total_matched": count,
    "shown": len(samples) if count else 0,
    "is_sample": count > len(samples) if count else False,
    "shown_ids": [r["fir_id"] for r in samples] if count else [],
}
```

Same pattern at the equivalent sampling points in `PERSON_NETWORK`, `ALIAS_CHECK`, and
`SIMILAR_CASES` — each already caps a result list; this only records the cap.

### 2.3 Reference resolution — structural extractors

New functions in `semantic_interpreter.py`, each a general pattern matched against *any* prior
turn, not a phrase list per operation:

- `_ordinal_reference(q) -> Optional[int]` — "the second one" / "item 2" → a 0-based index.
  Closed set of ordinal words + digit forms (English only — a genuinely closed category).
- `_is_exhaustiveness_query(q) -> bool` — "only these?", "is that all?". Reads
  `prior_turn.result_context`: if `is_sample`, re-runs the same bounded query with an offset and
  reports "N more of M total"; if not, reports "that's all, N total" — both branches read the
  stored fact, neither guesses.
- `_is_constraint_change(q) -> Optional[dict]` — a bare location/date/crime-type phrase with no
  operation verb ("same thing for Bengaluru") reuses `prior_turn.result_context["operation"]`
  with the new constraint overlaid.
- `_exploration_cue(q) -> Optional[str]` — "go deeper" / "show more" → `exploration_direction`.

`_extract_constraints()` (a stub) is filled by relocating the orchestrator's existing
`_crime_type_from_query` / `_district_code` / date-range extraction here — a move, not a
rewrite, so existing per-intent tests stay green.

### 2.4 Orchestrator wiring

Three new branches in `node_retrieve`, shaped like the existing `_handle_case_locations`
(`orchestrator.py:725-758`) — read prior turn, re-check RBAC against *this* officer, answer or
refuse honestly:

- `exhaustiveness_check` → `_handle_more_results()`
- `positional` → resolve `subject_id` from `prior_turn.citations[index]`, then fall through the
  normal per-operation path as if typed explicitly
- `constraint_change` → set `state.intent` from `previous_result_context["operation"]`, apply
  the new constraint, fall through normally

### 2.5 Testing

`test_reference_resolution.py` / extended `test_semantic_interpreter.py`: each extractor
unit-tested against paraphrases of its trigger phrase; two live-reproducing regression tests
for §1's exact baseline defect (confirmed to fail against pre-fix code first).

## 3. Phase 2 — deterministic multi-step composition

Scope: bounded two-entity comparisons ("check whether either of those people had a prior case
in Bengaluru around the same time"), not open-ended multi-clause planning — that needs the LLM
path (build the deterministic floor now; the LLM path activates for free later).

`semantic_interpreter.py` gains `_plan_multi_step(...)`, triggered by an explicit coordination
grammar ("either of", "both of", "and also") combined with 2+ resolved `comparison_entities`.
Returns `list[SemanticRequest]` instead of one.

`node_orchestrate`/`node_retrieve`: when the interpreter returns a list, loop the *existing*
single-subject retrieval path once per sub-request — same RBAC, same evidence evaluator, same
citation chain per subject, no cross-subject invention. `node_synthesize` merges the evidence
sets, tagged by subject, into one side-by-side answer, each half independently cited.

**Non-goal**: no arbitrary N-step planning, no temporal-relation chaining beyond what
`TIMELINE`/`TIMELINE_CONNECTION` already do, no cross-operation joins beyond Data Store's own
4-JOIN cap (`CLAUDE.md` §3).

## 4. Phase 3 — code-switching structural hardening

### 4.1 District-name protection

`data/data/seed/karnataka_districts.csv` gains a `kannada_names` column (pipe-separated, same
convention as `aliases`), sourced from a verifiable public reference, round-trip-tested per
entry.

`translate.py::_protect_spans` gains a second pass, active only for `src == "kn"`: a span
matching a known Kannada district spelling is replaced with a placeholder whose restore value
is the *canonical English name* — a lookup substitution, unlike the existing FIR/IPC/plate
protection which restores verbatim. Closes the whole "ಮಂಡ್ಯ"→"Mandi" bug class, for all 31
districts, structurally.

### 4.2 Dual-text entity extraction

`node_translate_in` overwrote `state.original_query` with the English translation, and nothing
downstream saw the Kannada again. Add `state.original_query_kn: Optional[str]`, set before
translation. `semantic_interpreter._interpret_deterministic` and `intents.resolve_focus` run
district/IPC/plate extraction directly against `original_query_kn` when present (via the §4.1
gazetteer plus existing script-independent digit/plate regexes), so these closed-format
entities stop depending on translation quality. Person-name extraction stays
translation-dependent — no closed gazetteer is possible for arbitrary names.

### 4.3 Explicitly not attempted

The "priorities" mistranslation stays open. Suffix-stemming intent keywords (folding
"priorities" toward "prior") was rejected — it would make "this is a high priority case"
spuriously score `PERSON_HISTORY`. No principled deterministic fix exists; needs the LLM path.

## 5. Phase 4 — adversarial conversational eval set

`scripts/adversarial_eval.py` + fixture file, `--target local` (drives
`rag_agent.run_investigation()` directly) and `--target live` (drives `/chat` SSE with a
signed-in officer token). Cases cover incomplete English, colloquial phrasing, Kannada,
code-switching, voice-like disfluency, pronouns, ordinals, exhaustiveness follow-ups,
exploration cues, corrections, the Phase 2 multi-step example, and deliberately
ambiguous/unanswerable queries (asserting an honest refusal). Assertions are behavioral
(operation resolved / evidence present / refusal reason), never exact string matches.

## 6. Phase 5 — checkable live-deployment verification

`scripts/verify_live_deployment.py`: signs in, hits `/health` (asserts expected fields
present), then runs a fixed probe battery distinguishing *old* from *new* behavior — the §1
two-turn `CRIME_SEARCH` → "Only these?" sequence is the primary probe. Non-zero exit on any
probe failure. Run by hand post-deploy; wiring it into `relay-deploy.yml` as a post-deploy gate
was named as a natural follow-up, not built in this pass.

## 7. What "done" looks like

Full test suite green, adversarial set green locally, deploy, AppSail deployment id changed,
`/health` reflects the new build, `verify_live_deployment.py` passes live (§1's defect fixed),
console re-checked via CDP for the one visible surface ("only these?" rendering as a real
answer). `ENGINEERING_BRIEF.md` updated in place, changelog entry appended — no new
handoff/status document.

## 8. Explicit out-of-scope

Re-attempting to obtain `QUICKML_ENDPOINT_KEY` (already investigated, blocked for reasons
outside API access); voice-specific handling (already generic, per §11); IndicTrans2 migration
(licensing/ops decision, not architecture); true N-step temporal/causal planning beyond §3's
two-entity comparison.
