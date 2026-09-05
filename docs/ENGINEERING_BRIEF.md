# Veritas — Engineering Brief

**This is the one architecture/engineering document for Veritas, besides `CLAUDE.md`.**
Edited in place, not replaced by a new handoff/status/strategy doc each pass — update
the relevant section and add one line to the changelog at the bottom. `CLAUDE.md` is
authoritative for *why* the platform is built the way it is; this document is
authoritative for *how well it currently serves an investigator's conversation*.

Last verified against commit `9ef7a85` (2026-08-29), live at AppSail deployment
`52852000000346070` (custom_runtime, memory 2048). Test count 599
(`pytest --collect-only -q`), the live judge battery (`scripts/judge_flows.py`), the
latency figures in §12, and the browser session in §14a were all confirmed directly
against the running code and the deployed service, not copied from an earlier document.

**The suite is fully green for the first time in this document's history** — two
`test_acceptance.py` failures once carried across passes as "pre-existing and
unrelated" were actually a real product regression (an unreachable refusal message)
and a stale test helper. Treat a red suite as a finding, not background noise.

---

## 1. Product mission

Veritas exists because a KSP investigator's actual bottleneck is not "no data" — the
FIR/accused/financial/graph records already sit in Data Store — it is **turning a
records system into an answer to a specific investigative question, fast, without
having to know SQL, Cypher, or which of five different views to open.** Not "a
chatbot over FIRs." An officer asks in whatever words are natural to them, and gets
back an answer that is either grounded in a specific record they can click through to,
or an honest "not found" — never a plausible-sounding guess. See `CLAUDE.md §5`'s CRAG
discipline: refusal on missing evidence is the single most important property in the
system, not a fallback behaviour.

## 2. User reality

The officer using this is time-constrained, not naive. They will not read a manual and
will not memorize command syntax. Realistic input looks like: *"does he have priors"*,
*"only these?"*, *"ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"* (mixing English police
vocabulary into a Kannada sentence — how a bilingual professional actually talks, not
a deliberate translation exercise), a half-finished sentence with ASR noise, or a flat
correction ("no, the other one"). The system must absorb that register, not require
the officer to learn a cleaner one. §5 is honest about where it still falls short.

## 3. Current architecture

```
 text  ──┐
 audio ──┴─► node_voice_in (ASR, faster-whisper via data.nlp.speech)
              │
              ▼
         node_translate_in  (kn→en, data.nlp.translate — only if Kannada script present)
              │
              ▼
         node_orchestrate   (rag_agent/orchestrator.py:120)
              │  intents.classify() — keyword/regex intent (rag_agent/intents.py:249)
              │  intents.resolve_focus() — pronoun/session-focus resolution
              │  named-entity resolution against vx_person (ambiguity → clarify, not guess)
              ▼
         node_retrieve       (orchestrator.py:207)
              │  intent-scoped short-circuits: CAPABILITY, NOT_INFERABLE, meta-questions,
              │  CASE_LOCATIONS, TIMELINE(_CONNECTION), BOARD_* — none of these touch
              │  retrieval; each reads/writes structured state or storage directly.
              │  Otherwise: HippoRAG (Personalized PageRank) → specialist agent for the
              │  intent (sql_agent / graph_agent / prediction_agent) → Think-on-Graph
              │  deep-dive if weak/relational → hybrid vector search (skipped when a
              │  specialist already settled the question — orchestrator.py:645-675)
              ▼
         node_evaluate       (CRAG — rag_agent/evidence/evaluator.py)
              │  ACCEPT / REFINE (loop back to retrieve, once) / REJECT
              ▼
         node_synthesize     (orchestrator.py:1347)
              │  LLM (QuickML) if available → fluent prose; else extractive template.
              │  Both cite only `supporting()` evidence, ranked per-intent.
              ▼
         node_voice_out (TTS, if requested)
```

Built with LangGraph (`rag_agent/orchestrator.py:1532`, `build_graph()`); the state
object is `InvestigationState` (`rag_agent/state.py`). The whole thing is one function,
`run_investigation()`, called once per turn by `apps/api`.

**Named modules**: intent/reference resolution — `rag_agent/intents.py`,
`rag_agent/semantic_interpreter.py`, `rag_agent/operation_semantics.py` (§12).
Retrieval — `rag_agent/retrieval/{hipporag,tog}.py`, `rag_agent/agents/vector_agent.py`.
Structured tools — `rag_agent/agents/{sql_agent,graph_agent,prediction_agent}.py`.
Evidence grounding — `rag_agent/evidence/evaluator.py`. Synthesis —
`rag_agent/agents/synthesis_agent.py`. Investigation memory — `data/models.py`
(`SessionFocus`, `ConversationTurn`), `rag_agent/board.py` + `data/board.py`. Language —
`data/nlp/{translate,speech,entities}.py`, `rag_agent/agents/translation_agent.py`.

## 4. What is genuinely strong today

- **CRAG evidence grounding is real, not aspirational.** `evaluate()`
  (`evidence/evaluator.py:105`) has three verdicts with a documented reason for each;
  `supporting()` separates relevance-scored support from authoritative findings so a
  refusal never gets padded with unrelated citations dressed up as evidence. Load-bearing
  property of the whole system, and it holds up under reading, not just its own docstrings.
- **Identity resolution and the graph it enables** (`CLAUDE.md §0, §4`) — F1 0.989, a
  genuine hard dependency of PERSON_HISTORY/PERSON_NETWORK/FINANCIAL/ALIAS_CHECK, not a
  demo feature bolted on top.
- **RBAC is enforced at query-construction time, not just response-shaping**
  (`CLAUDE.md §7`) — station filters live inside the SQL/Cypher, not as a post-hoc
  mask; `packages/policy` is the single shared enforcement point for REST and
  conversational surfaces alike.
- **The investigation board is a real persistent artifact**, not a session cache —
  `vx_case_board_item`, station-scoped through the same `can_view_fir` check every other
  case read uses, survives a new session (verified live, `CLAUDE.md` v16).
- **Negative findings are stated, not silently dropped** — ALIAS_CHECK's "no alias",
  FINANCIAL's "no account linked", NEXT_STEPS' "no co-accused to lead from" are each an
  explicit `authoritative=True` evidence item, not an empty list that reads as "nothing
  was found" when the true finding is "the records affirmatively show nothing exists
  here" — a real distinction for an investigator.
- **Voice degrades honestly**: no ASR/TTS weights → the turn continues as text, traced
  explicitly, never a hard failure.
- **The LLM cannot become the source of truth even if fully available** — synthesis is
  handed only the evidence list; degraded mode (no QuickML) produces the same citations
  via an extractive template. Enforced by data flow, not a system-prompt instruction a
  model could ignore.

## 5. What is actually weak — the architectural bottlenecks

Not a bug list (see `docs/PHASE1_FAILURE_LOG.md` for that). Four architectural
bottlenecks — not missing keywords — that used to cap how far natural conversation
could go; each now has a genuine fix, not a regex patch. Full history in §12 and §16.

1. **Understanding — three tiers now, not one flat 30-way classifier.**
   `intents.py`'s 21 keyword-scored intents + 8 regex shape pre-checks are the
   deterministic floor and remain the compatibility layer (the 30 current intents are
   valid values of a structured `operation` field, not torn out). Above that,
   `rag_agent/operation_semantics.py` is an embedding-based middle tier (~3.5ms,
   confidence-capped at 0.70). Above that, `semantic_interpreter.interpret()` calls
   QuickML when the lower tiers' confidence is below 0.75. All three paths produce the
   identical `SemanticRequest` shape, so nothing downstream of `node_orchestrate`
   changed to add either tier.
2. **Reference resolution is now general, not hand-built per phrase.**
   `semantic_interpreter.py` has structural extractors — ordinal/positional
   (`_ordinal_index`), "the other one" (`_resolve_other_candidate`), exhaustiveness vs.
   exploration (context-disambiguated), bare "why," a bare temporal relation, and a
   constraint-change repeat — each matched against *any* prior operation/subject, not a
   specific phrase. A new phrasing of any of these composes for free; a genuinely new
   *category* of reference still needs its own extractor.
3. **Result-set awareness is built.** `result_context`
   (`{operation, total_matched, shown, is_sample, shown_ids, constraints}`) is recorded
   on every bounded result (`CRIME_SEARCH`, `PERSON_NETWORK`, `ALIAS_CHECK`,
   `SIMILAR_CASES`). "Only these?" / "are there more?" routes to `RESULT_SET_FOLLOWUP`,
   which gives an honest "that was everything" or a genuinely wider re-query deduped
   against what was already shown. A bounded deterministic two-entity comparison
   (`_handle_comparison`) and a full N-step plan (`SemanticRequest.plan_steps`,
   `orchestrator._run_plan` — chained subjects, bounded fan-out, citation-position
   references) both exist, sequenced through the exact same single-subject
   retrieval/RBAC/CRAG path a plain turn uses.
4. **Kannada/English code-switching — mostly closed, one gap left open on purpose.**
   The "Mandya→Mandi" mistranslation class is closed structurally via a 31-entry
   Kannada district gazetteer lookup-substitution (§10) — the district name never
   reaches NLLB at all. "priorities" (a `\bpriors?\b` keyword miss after
   "priors"→"priorities" mistranslation) stays open: a keyword alias would be exactly
   the reflexive patch this section argues against, and the real fix is the semantic
   tiers in point 1 reading meaning instead of one exact surviving English noun.

## 6. Conversational architecture — target semantic concepts

Not "which of 30 intents." A turn decomposes into:

| Concept | What it captures | Where it exists today |
|---|---|---|
| **operation** | what the officer wants done: look up, count, compare, trace, forecast, explain-the-last-answer, save-to-board | `SemanticRequest.operation` — 30 values, either tier |
| **subject** | the case/person/district/account this is about | `SessionFocus.active_person/active_fir/active_location` |
| **reference** | how the subject was named: explicit, pronoun, "this case," positional | structural extractors, §5 point 2 |
| **constraints** | date range, crime type, district, confidence threshold | `_extract_constraints`; `date_before`/`date_after` wired into `CRIME_SEARCH` |
| **previous result set** | what the last turn returned, and whether it was exhaustive or a sample | `result_context`, §5 point 3 |
| **comparison** | "both of them," "which is worse" | `_handle_comparison` (bounded 2-entity) + full plans (3+, §5 point 3) |
| **correction** | "no, the other Ramesh" / "actually Bengaluru, not Mysuru" | `state.last_request` carried forward; QuickML merges old + new request semantically |
| **clarification response** | the officer answering "which one did you mean" | still just a re-classified query, not a distinct turn type |
| **exploration/expansion** | "go deeper," "what else" | `NEXT_STEPS`/`EVIDENCE_FOR` partially cover it; the bare-exploration extractor (§5.2) covers the rest |
| **explanation of prior results** | "why are you showing me this" | `EXPLAIN_REASONING` — reads the stored trace, not a fresh search |

The 30 original intents remain the values the `operation` field takes — an
implementation compatibility layer that was never torn out.

## 7. Tool selection

Correct in shape, and stays this way regardless of which understanding tier resolves
the `operation`:

| operation family | tool |
|---|---|
| person history / risk | `sql_agent.person_record` + `prediction_agent.risk/recidivism` |
| network / alias | `graph_agent.person_network/aliases` |
| financial | `graph_agent.money_trail` + AML detectors |
| hotspot / forecast | `prediction_agent.hotspots/forecast` |
| causal | `prediction_agent.causal` (DoWhy) |
| crime search / FIR lookup | `sql_agent.count_firs/search_firs/fir_by_number` |
| timeline / connection | `timeline_agent.person_timeline/case_timeline/connection_between` |
| board | `rag_agent/board.py` → `data/board.py` |
| open-ended narrative | `vector_agent.search` (hybrid dense+BM25), only when nothing structured settles it |

The mapping from "what does the officer want" to "which deterministic tool answers it"
is sound and always has been. The problem was entirely upstream, in how reliably a raw
utterance produces the right `operation` — §5, §12.

## 8. Result awareness

`CRIME_SEARCH` reports an exact `COUNT(*)` scoped by role/station, not an estimate, and
separately samples for citation; `CASE_LOCATIONS` re-derives a tally from exactly the
FIRs the previous turn cited, re-checked against current policy scope, not a fresh
unscoped query. `result_context` (§5 point 3) generalizes this pattern to every bounded
operation. `SIMILAR_CASES` is deliberately recorded `total_matched=None, is_sample=True`
— a ranked top-N has no honest "total exists" number, and saying so is itself the
correct behavior.

## 9. Investigation memory — three tiers, kept genuinely distinct

1. **Conversation history** — `data.models.ConversationTurn`, one row per turn (query,
   answer, citations, evidence, visualization, trace), so `EXPLAIN_REASONING`/
   `EVIDENCE_FOR`/`CASE_LOCATIONS`/pin-to-board can read the *previous* turn without
   re-running retrieval.
2. **Active session focus** — `SessionFocus` (`data/models.py:15`): `active_person`,
   `active_fir`, `active_location`, `active_date_range`. Ephemeral, overwritten every
   turn, persisted so it survives a page reload.
3. **Persistent investigation state** — `vx_case_board_item`, discriminated by
   `ItemType ∈ {evidence, person, lead, note, question, finding}`. A `lead` carries its
   own status machine (`open → pursued | dismissed`) and is *never deleted*
   (`remove_item` explicitly refuses to delete one) — "a dismissed lead must remain
   auditable" is enforced structurally. `evidence`/`finding` store a reference plus a
   content *snapshot*, never a second copy of the record layer that could drift.

These three tiers are correctly kept distinct: the selected console card
(`active_evidence_id`) is a UI hint, not identity, and is not part of `SessionFocus`;
board items are investigator-authored state, not inferred context, and are not folded
into it either. Worth preserving through any future refactor.

## 10. Multilingual / code-switching — tested against the real model, not assumed

`node_translate_in` runs kn→en translation before anything else touches the query,
because every downstream matcher — keywords, IPC/plate regexes, gazetteers — is
Latin-script only. `detect_language()` is a single whole-string check (any Kannada
codepoint → `'kn'`) — deliberately simple, and correct enough to leave alone.

**Tested directly against `facebook/nllb-200-distilled-600M`** (the actual weights, not
mocked): ordinary code-switching translates well as a whole sentence (*"ಆ case ಗೆ
related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"* → *"Is there another FIR related to that case?"*,
correct); a long embedded FIR number survives digit-for-digit in every run.

**Two real bugs found, one fixed structurally, one left open on purpose:**

- **"Mandya→Mandi" — FIXED.** *"ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ FIR 100222201202600022 ...?"*
  translated "ಮಂಡ್ಯ" (Mandya) to "Mandi" — a real but wrong, more common Indian place
  name, specifically when "FIR" and a number both sit in the sentence. Live, this was
  worse than a wrong word: "Mandi" isn't a real district, so NER read it as an
  unresolved person and refused the whole query (`person_not_on_file`) even though the
  FIR number and intent both resolved correctly. Protected-span translation
  (`data/nlp/translate.py:_protect_spans/_restore_spans` — FIR numbers, IPC codes,
  plates removed before NLLB and spliced back verbatim) did not fix this on its own,
  since the district name isn't a numeric span. The actual fix: `_protect_spans` runs a
  second pass against a closed 31-entry Kannada-script district gazetteer
  (`data.districts.kannada_name_map`, sourced from kn.wikipedia.org, flagged for a
  native-speaker QA pass before extending past the districts it was verified against) —
  a lookup substitution, not a translation, so the model never sees the district name at
  all. A reverse-direction sibling bug (the synthesized *answer*'s en→kn translation
  rendered NLLB's own transliteration, "ಮಂಡಯಾ," instead of the canonical "ಮಂಡ್ಯ") was
  found live during verification and fixed the same way
  (`data.districts.english_to_kannada_district`). Both verified with a hostile stand-in
  backend that actively corrupts any district name it's shown — the correct name comes
  back regardless (`data/tests/test_nlp.py`).
- **"priorities" — left open, correctly.** *"Usha Naika ಗೆ priors ಇದ್ಯಾ?"* translates to
  *"Does Usha Naika have **priorities**?"*, and `\bpriors?\b` doesn't match. Blind
  suffix-stemming was considered and rejected (it would make "this is a high priority
  case" spuriously score `PERSON_HISTORY`). The principled fix is §5 point 1's semantic
  tiers reading meaning, not one exact English noun surviving machine translation
  intact — not a keyword alias.

## 11. Voice

`node_voice_in` → ASR (`data/nlp/speech.py`, faster-whisper, self-hosted — Zia has no
STT/TTS/translation service, `CLAUDE.md §2`) → the **identical** text pipeline every
typed query goes through → `node_voice_out` (TTS, same self-hosted layer). Voice needs
no special semantic handling: by the time `node_orchestrate` runs, a transcribed query
and a typed one are the same string. ASR noise/disfluency reaching the classifier as
literal text has not been evaluated against real (non-synthetic) ASR output — noted as
unverified rather than assumed fine.

## 12. QuickML — how it went from unreachable to load-bearing

**Current state, live in production.** QuickML (GLM-4.7-Flash) is called over plain
REST, not the SDK: `llm.py` authenticates via a self-client refresh-token grant
(`QUICKML_CLIENT_ID`/`_SECRET`/`_REFRESH_TOKEN`) and calls
`POST api.catalyst.zoho.in/quickml/v1/project/{id}/glm/chat` directly. `interpret()`
and `synthesize()` both route to it only when needed — see the routing fixes below —
not on every turn. Latency measured live over a 26-turn battery: **p50 0.53s, p95
12.82s, max 31.25s** (30s is the hard timeout); the deterministic and embedding tiers
are sub-second, the tail is entirely QuickML round trips.

**How this was reached:**

1. **The Python SDK's `quick_ml()` cannot do chat at all.** Reading `zcatalyst-sdk`
   1.4.0 directly (not the Node/Java-only marketing docs) showed it exposes only a
   generic ML-pipeline `predict(endpoint_key, input_data)` call. Every earlier `llm.py`
   had built a hand-guessed OpenAI-chat-shaped request against a guessed URL — neither
   the shape nor the URL matched anything real.
2. **Even the real SDK method is blocked project-wide, not per-runtime.** `predict()`
   fails before key validation with `CatalystAPIError: ORGID_HEADER_UNAVAILABLE` — the
   SDK's `CATALYST-ORG` header only attaches when `X_ZOHO_CATALYST_ORG_ID` is set, which
   this app's container lacks and cannot set (rejected as a reserved config keyword).
   Confirmed via two throwaway probes in the same project (a managed Python AppSail app,
   a Basic I/O Function) — both hit the byte-identical error, ruling out a
   `custom_runtime`-specific cause. Untested: whether publishing through the console UI
   itself establishes the missing org linkage server-side (needs console access this
   environment doesn't have).
3. **The working path is a different, undocumented-in-the-SDK contract.** The Catalyst
   console's own QuickML integration page (not the general SDK docs) names a plain REST
   endpoint reachable with a self-client OAuth grant and a static `CATALYST-ORG` header
   — no runtime SDK injection needed, so the custom_runtime-vs-managed distinction in
   point 2 turns out to be moot. Verified live with a temporary CLI token before
   rewriting `llm.py` around it.
4. **Two real bugs in the new integration, found by invoking it live**: the model's
   chain-of-thought is closed by a bare `</think>` with no matching opening tag (a naive
   regex never matched, leaking the whole reasoning trace through as "the answer" —
   fixed by stripping everything through the last `</think>` unconditionally); and the
   model non-deterministically refuses
   schema-shaped or "reply with exactly X" prompts as "exposing protected instructions"
   — `generate()` now retries once with a reassurance frame and degrades to
   `LLMUnavailable` on a second refusal.
5. **Routing is hybrid, not "call the LLM on every turn."** `interpret()` runs the
   deterministic path first (microseconds); QuickML is consulted only when that
   result's confidence is below `_LLM_ROUTING_THRESHOLD` (0.75) — a second opinion, not
   an automatic override, and it only wins if at least as confident. This fixed a real
   bug where even an exact FIR-number lookup paid a full 16.8s model round trip before
   reaching its own confidence-1.0 deterministic answer (now 9ms).
   `synthesis_agent.synthesize()` similarly calls QuickML only for
   `intents.NEEDS_NARRATIVE_SYNTHESIS` operations — a direct factual answer (a status, a
   count) never pays for prose it doesn't need (a FIR-status turn went from ~16.8s to
   1.4s total end to end).
6. **A third understanding tier exists below QuickML**: `rag_agent/operation_semantics.py`,
   an embedding match (bge-small — already warm for vector search, ~3.5ms) against ~35
   operation prototypes, confidence-capped at 0.70 (deliberately below the LLM routing
   threshold — QuickML still wins when reachable, since it also extracts constraints an
   argmax cannot). It exists because raw similarity does not separate real questions
   from nonsense for this model (0.59–0.85 vs. 0.51–0.72, fully overlapping); an
   explicit `NO_OPERATION` reject class — measured and tuned against a held-out
   battery, not asserted — is what actually works. It is a floor: a QuickML outage or
   cooldown now degrades to a real answer instead of a flat refusal.
7. **The reasoning trace only genuinely streams as of 2026-08-29.** An earlier pass
   claimed this was already true by reading `apps/web` (which does handle incremental
   frames correctly) — but the API ran the engine to completion and replayed the trace
   afterward, so a 20-35s QuickML turn showed a spinner with nothing behind it for its
   full duration. Reading one end of a pipe proved nothing about the other. Fixed with
   `orchestrator.live_trace()` (thread-local — LangGraph may hand each node its own
   state copy) plus a 200ms SSE poll; `interpret()` now fires its `on_model_call` trace
   entry *before* the round trip, not after.
8. **Six defects were found only by driving the deployed system, not by reading it**
   (§16, 2026-08-29): `person_not_on_file` had been silently unreachable since the
   semantic-interpreter migration dropped its only call site, so a named-but-unknown
   person swept the vector index instead of refusing; a bare "FIR" keyword could route
   to `FIR_LOOKUP` with no number to look up, falling through to unscoped semantic
   search across unrelated districts; a correction naming only new constraints lost the
   turn; `cannot_understand` had no message of its own; a Kannada `CRIME_SEARCH`
   refused because "District Mandya" made NER invent a person (a regression from the
   `person_not_on_file` fix, caught by the live battery, scoped to
   `intents.NEEDS_SUBJECT` + UNKNOWN only); and `CASE_PEOPLE` dropped an empty accused
   list into a generic refusal instead of stating the negative finding §4 claims the
   system makes. Session focus (case/person in view) is now shown on screen, rank-masked
   the same way every other surface masks a name.

## 13. Failure behavior

| Situation | What happens | Where |
|---|---|---|
| Understood, no evidence | `REJECT` verdict, explicit reason-specific text (14 distinct reasons, not one generic message) | `evidence/evaluator.py:154-238` |
| Ambiguous subject | Named, not guessed — candidates listed, officer asked to disambiguate | `orchestrator.py:139-142`, `REFUSAL_MESSAGES["ambiguous_person"]` |
| Cannot understand at all | Falls to `UNKNOWN` → `CRIME_SEARCH` fallback if any keyword scored, else a generic "not found" — **not** a distinct "I didn't understand you" message; a real, honest gap | `intents.py:293-297` |
| A tool fails | Per-tool `try/except` degrades to "no evidence from this specialist," not a crashed turn | throughout `_run_specialists` |
| LLM unavailable | `LLMUnavailable`/`{}` → deterministic template path, same citations, no degradation in *correctness*, only prose fluency | `llm.py:23-31`, `synthesis_agent.py:47-58` |
| Authorization blocks it | Refused with a station-scope-specific message, not folded into "not found" | `evidence/evaluator.py:212-219` |
| Translation backend fails | Answers in English, says so explicitly, never silently wrong-language | `translation_agent.py:22-58` |

The one gap worth naming: "I genuinely cannot parse this" is indistinguishable today
from "I searched and found nothing" — a different fact to tell an officer (one says
"rephrase," the other says "this isn't in the records"). A structured interpreter can
emit "operation: unknown" as its own explicit state, which the flat classifier's
`UNKNOWN`→fallback path cannot represent honestly.

## 14. Demo / acceptance standard

Not keyword tests. Representative of what an officer would actually say:

- *"does he have priors"* (mid-conversation pronoun) → resolves against
  `SessionFocus.active_person`, returns full case history. **Works today.**
- *"only these?"* right after a crime-count answer → reads the stored total vs. shown
  count and either lists more or says the count was exhaustive. **Works today** —
  verified against the real dataset, including a chained follow-up that carries the
  crime type forward while re-scoping only the district.
- *"ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"* → **works today**, verified against the
  real model, §10.
- *"Usha Naika ಗೆ priors ಇದ್ಯಾ?"* → **does not work via the deterministic path** —
  translates to "priorities," misses `PERSON_HISTORY`, and used to degrade to a
  confusing multi-person vector-search blend instead of either the right answer or a
  clean refusal. The semantic tiers (§12) are the intended fix; not independently
  re-verified against this exact sentence since they landed.
- *"ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ FIR 100222201202600022 ಬಗ್ಗೆ ಏನಿದೆ?"* → **works today** — the
  district-gazetteer fix means "ಮಂಡ್ಯ" never reaches NLLB at all.
- *"the second one"* after a network/associate listing → resolves against the previous
  turn's numbered citation list. **Works today.**
- *"go deeper"* / *"what else"* after a subject-scoped answer → **works today** when a
  subject is in focus with no bounded result set to disambiguate against; falls
  through honestly otherwise.
- A refusal ("tell me about the flying saucer incident on the moon") → clean refusal,
  no padded citations. **Works today**, and was a real regression once
  (`orchestrator.py:1437-1449`'s comment documents the exact failure it fixed).

### 14a. What was actually driven, 2026-08-29

Two independent surfaces, both against production, neither against the local sqlite
mirror.

**API — `scripts/judge_flows.py`, 16 scenarios / 26 turns, 25 passing.** Simple lookup,
unseen phrasing, follow-up + pronoun, previous-result reference, semantic correction,
multi-step, network, financial, timeline, pure Kannada, code-switching, ambiguity,
no-evidence refusal, RBAC denial, capability, safety (suspect nomination refused),
continuity. The one non-passing turn is an accepted degraded outcome documented in the
file, not a failure to answer.

**Browser — headless Chrome over CDP against the deployed console.** A four-turn
conversation (FIR lookup → pronoun follow-up → named person → an unseen phrasing, "Who
does she run with?", no keyword match) resolved through the embedding tier to
`PERSON_NETWORK` and returned real associates; the session-focus chip tracked both
subjects across turns. A second session drove the conversational fixes specifically: a
crime search, a result-set follow-up ("Only these?"), a semantic correction ("Actually
Mysuru, not Bengaluru Urban"), and an honest refusal — all rendering with the correct
DOM class (`msg-a` vs. `msg-a refusal`).

**Not driven this pass**: voice input/ASR (no microphone in a headless browser), PDF
export (still blocked on SmartBrowz), the investigation board's full UI flow (covered
by `test_board_acceptance.py` instead), and the map/Sankey/forecast visualizations
(confirmed present, not re-screenshotted).

**Known, deliberately not fixed**: the session-focus chip covers case and person, not
district — a purely district-scoped conversation shows no chip even though
`SessionFocus.active_location` is exactly what those turns resolve against. Small,
additive, scoped out for lack of remaining budget, not forgotten.

## 15. How to use this document going forward

- **When you fix a bug**: don't write a new failure-log entry format. If it changes
  what §4/§5 claims, edit those sections. Otherwise it doesn't belong here at all —
  `git log` is the record of individual fixes.
- **When QuickML behavior changes**: update §12 first — it gates whether any
  LLM-routed claim in this document can be called verified. Anything that currently
  says "degrades to deterministic" should be re-tested against the real model before
  being called done.
- **Verify the producer, not the consumer** (§12 item 7 is the concrete example: a
  streaming claim was wrong for a full pass because the check read only the client
  side). If a claim is about behaviour, the evidence has to be observed behaviour.
- **A red test is a finding.** Two `test_acceptance.py` failures were carried across
  several passes as "pre-existing and unrelated." One was a real product regression;
  the other was a stale helper. Nothing in this suite is background noise.

## 16. Changelog (append here; do not create a new file)

Full narrative for each entry below lives in `docs/WORK_LOG.md`; §4/§5/§10/§12 above
already hold the current-state detail that matters going forward. Keep new entries to
what shipped and the one number/lesson worth remembering.

- **2026-08-29** — third understanding tier (`operation_semantics.py`, embedding-based
  floor below the LLM routing threshold); reasoning-trace streaming genuinely fixed
  (§12 item 7); six defects fixed by driving the deployed system rather than reading it
  (§12 item 8). Rotated `VERITAS_JWT_SECRET`/`VERITAS_JOB_TOKEN` after an Admin API
  config read had leaked them into local tool output. 598 tests — first fully-green run
  in this document's history.
- **2026-08-28 (freeze pass)** — 16-category live judge simulation against production
  found one real bug (a correction after a meta/follow-up turn lost the real prior
  request — `intents.META_OPERATIONS` now carries it forward), one non-reproducible
  live LLM misclassification, and one pre-existing code-switch gap left deliberately
  unfixed per this pass's freeze instruction. Deterministic p50 1.6s/p95 1.8s;
  QuickML-invoked p50 21.4s/p95 34.4s under real load, including one observed 70s
  degrade-cooldown. 581 tests.
- **2026-08-28 (N-step planner)** — `SemanticRequest.plan_steps` +
  `orchestrator._run_plan`: chained subjects, bounded fan-out (max 5),
  citation-position references, all through the existing single-op RBAC/CRAG path.
  `state.last_request` persisted so corrections merge semantically instead of via
  regex; `date_before`/`date_after` wired into `CRIME_SEARCH` for temporal corrections.
  559 tests (37 new). Not done: graph-shaped (non-linear) plans, a single `date_range`
  field, deterministic multi-step attempts.
- **2026-08-27 (QuickML root-caused + adversarial pass)** — see §12 for the full SDK/
  org-id/REST finding. Five conversational gaps fixed by widening existing mechanisms,
  never a new phrase-specific regex: `NOT_INFERABLE` missed filler words between "who"
  and the verb ("who do you think committed X"); `SIMILAR_CASES`/`ALIAS_CHECK` missing
  vocabulary; a bare "And Mysuru?" fell to `UNKNOWN` after HOTSPOT/FORECAST (neither
  producer populated `result_context`); a named subject with no verb reached `UNKNOWN`
  despite a resolved subject. 492 tests (5 new). Deployed; all 36/36 live adversarial
  scenarios pass, p50 1.03s/p95 12.74s/max 13.87s.
- **2026-08-27 (compositional semantic layer)** — result-set awareness
  (`result_context`) and general reference resolution (ordinal/positional/"other"/
  exhaustiveness/bare-why/temporal/constraint-repeat extractors) built; bounded
  two-entity comparison added as a deterministic alternative to the full planner.
  "Mandya→Mandi" fixed via the district gazetteer, both translation directions. 488
  tests (33 new). Deployed twice — the second deploy fixing the reverse-direction
  district bug the first deploy's own live-verification gate caught.
- **2026-08-28 (semantic interpreter foundation)** — replaced the flat 30-intent
  classifier's ceiling with structured `SemanticRequest` decomposition; LLM path tried
  first, degrades to the existing deterministic `intents.classify()`. The 30 intents
  remain valid `operation` values, not removed. 202 tests (27 new).
- **2026-08-27 (protected-span translation)** — FIR numbers/IPC codes/vehicle plates
  now survive kn→en translation by construction, not by observed model behavior. Found
  and deliberately left open: "priorities," and the original (pre-gazetteer)
  "Mandya→Mandi" bug — both ruled out as fixable by span-protection alone. 437 tests.
  Deployed; live-tested the Mandya+FIR query, which turned out to fully refuse the turn
  in production (NER read "Mandi" as an unresolved person) — worse than the local
  finding alone suggested.
