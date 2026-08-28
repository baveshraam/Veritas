# Veritas — Engineering Brief

**This is the one architecture/engineering document for Veritas, besides `CLAUDE.md`.**
It does not get replaced by a new handoff/status/strategy doc each pass — it gets
*edited in place* when the system's actual architecture or verified state materially
changes. If you are about to create `HANDOFF_v2.md` or `STATUS_UPDATE.md`, don't —
update the relevant section here instead, and add one line to the changelog at the
bottom. `CLAUDE.md` stays authoritative for *why* the platform is built the way it is
(the Catalyst migration, the ER-has-no-person problem, the service inventory); this
document is authoritative for *how well it currently serves an investigator's
conversation*, which is the harder, faster-moving question.

Last verified against the repository at commit `610f0f7`, live-deployed at AppSail
deployment `52852000000361014`. Test count, file:line references and the QuickML/
mixed-script translation findings in §10/§12 were confirmed directly against the
running code and the real installed SDK on 2026-08-27, not copied from an earlier
document.

---

## 1. Product mission

Veritas exists because a KSP investigator's actual bottleneck is not "no data" — the
FIR/accused/financial/graph records already sit in Data Store — it is **turning a
records system into an answer to a specific investigative question, fast, without
having to know SQL, Cypher, or which of five different views to open.** The mission is
not "a chatbot over FIRs." It is: an officer asks in whatever words are natural to
them, and gets back an answer that is either grounded in a specific record they can
click through to, or an honest "not found" — never a plausible-sounding guess. See
`CLAUDE.md §5`'s CRAG discipline: refusal on missing evidence is treated as the single
most important property in the system, not a fallback behaviour.

## 2. User reality

The officer using this is time-constrained, not naive. They will not read a manual and
will not memorize command syntax. Realistic input looks like: *"does he have priors"*,
*"only these?"*, *"ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"* (mixing English police
vocabulary into a Kannada sentence, not translating between languages deliberately —
just how a bilingual professional actually talks), a half-finished sentence spoken and
transcribed with ASR noise, or a flat correction ("no, the other one"). The system must
absorb that register, not require the officer to learn a cleaner one. §6–§10 below are
about exactly this; §5 is honest about where it still falls short of it.

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

**Named modules**: intent/reference resolution — `rag_agent/intents.py`. Retrieval —
`rag_agent/retrieval/{hipporag,tog}.py`, `rag_agent/agents/vector_agent.py`. Structured
tools — `rag_agent/agents/{sql_agent,graph_agent,prediction_agent}.py`. Evidence
grounding — `rag_agent/evidence/evaluator.py`. Synthesis —
`rag_agent/agents/synthesis_agent.py`. Investigation memory —
`data/models.py` (`SessionFocus`, `ConversationTurn`), `rag_agent/board.py` +
`data/board.py`. Language — `data/nlp/{translate,speech,entities}.py`,
`rag_agent/agents/translation_agent.py`.

## 4. What is genuinely strong today

- **CRAG evidence grounding is real, not aspirational.** `evaluate()`
  (`evidence/evaluator.py:105`) has three verdicts and a documented reason for each;
  `supporting()` separates relevance-scored support from authoritative findings so a
  refusal never gets padded with unrelated citations dressed up as evidence
  (`orchestrator.py:1437-1449`'s "a refusal that already knows it has nothing to cite
  must not keep the evidence it rejected"). This is the load-bearing property of the
  whole system and it holds up under reading, not just under its own docstrings.
- **Identity resolution and the graph it enables** (`CLAUDE.md §0, §4`) — F1 0.989,
  and it is a genuine hard dependency of PERSON_HISTORY/PERSON_NETWORK/FINANCIAL/
  ALIAS_CHECK, not a demo feature bolted on top.
- **RBAC is enforced at query-construction time, not just response-shaping**
  (`CLAUDE.md §7`) — station filters live inside the SQL/Cypher, not as a post-hoc
  mask, and `packages/policy` is the single shared enforcement point for both the REST
  and conversational surfaces.
- **The investigation board is a real persistent artifact**, not a session cache —
  `vx_case_board_item`, station-scoped through the exact same `can_view_fir` check
  every other case read uses (`rag_agent/board.py:44`), survives a new session
  (verified live, `CLAUDE.md` v16 changelog).
- **Negative findings are stated, not silently dropped** — ALIAS_CHECK's "no alias",
  FINANCIAL's "no account linked", NEXT_STEPS' "no co-accused to lead from" are each an
  explicit `authoritative=True` evidence item (`orchestrator.py:391-401, 421-428,
  610-618`), not an empty list that reads as "nothing was found" when the true finding
  is "the records affirmatively show nothing exists here" — a real distinction for an
  investigator.
- **Voice degrades honestly**: no ASR/TTS weights → the turn continues as text, traced
  explicitly (`agents/voice_agent.py:16-17`), never a hard failure.
- **The LLM cannot become the source of truth even if fully available** — synthesis is
  handed only the evidence list (`synthesis_agent.py:49-53`); degraded mode (no
  QuickML) produces the same citations via an extractive template
  (`synthesis_agent.py:61-69`). This is enforced by data flow, not by a system-prompt
  instruction a model could ignore.

## 5. What is actually weak — the architectural bottlenecks

Not a bug list (see `docs/PHASE1_FAILURE_LOG.md` for that). These are the four things
that cap how far natural conversation can go before the *architecture*, not a missing
keyword, is the limit.

1. **Understanding was 30 flat, mutually-competing pattern matches — ADDRESSED in §12 migration.**
   `intents.py` still has 21 keyword-scored intents plus 8 regex "shape" pre-checks
   (`intents.py:15-297`), and they still live in the codebase — but they are now the
   compatibility layer beneath a structured `SemanticRequest` model. The new
   `rag_agent/semantic_interpreter.py` (`interpret()` function) decomposes queries into
   `(operation, subject_type, subject_id, reference_kind, constraints, ...)` independent
   of the 30-bucket classifier. It tries an LLM path (QuickML `generate_json`, currently
   unreachable, §12) first, and falls back to a deterministic path that reuses
   `intents.classify()` for compatibility. The 30 current intents become valid values
   for the `operation` field — the classification ceiling has been replaced with a
   structured representation. Both paths produce identical `SemanticRequest` shape so
   `node_orchestrate` (updated to call the interpreter) and all downstream nodes continue
   unchanged. Test coverage: 27 new adversarial conversation tests (paraphrases,
   pronouns, code-switching, reference resolution, edge cases) + full regression suite
   (202 tests pass, 2 skipped).
2. **Reference resolution is general for one thing (a person pronoun) and hand-built
   for everything else — ADDRESSED in the compositional semantic layer milestone
   (§16, 2026-08-27).** `semantic_interpreter.py` now has a small set of *structural*
   extractors — ordinal/positional (`_ordinal_index`), "the other one"
   (`_resolve_other_candidate`), exhaustiveness ("only these?"/"are there more?",
   context-disambiguated from "tell me more about the subject" via
   `_AMBIGUOUS_MORE_RE`), unambiguous exploration cues ("go deeper", `_EXPLORATION_ONLY_RE`),
   bare "why" (`_BARE_WHY_RE`), a bare temporal relation ("before this?",
   `_TEMPORAL_BARE_RE`), and a constraint-change repeat ("same thing for Bengaluru",
   `_REPEAT_CUE_RE`) — each matched against *any* prior operation/subject, not
   hand-built per phrase. A genuinely new phrasing of any of these composes for free;
   what still needs its own extractor is a genuinely new *category* of reference (see
   the adversarial battery, §14, for what was and wasn't tested). "Compare these two"
   is now covered too, as a bounded two-entity case — see point 3a below.
3. **No result-set awareness at the state level — ADDRESSED.**
   `InvestigationState.result_context` / `ConversationTurn.result_context` (a new,
   additive field, `data/models.py`) now records `{operation, total_matched, shown,
   is_sample, shown_ids, constraints}` at the exact point `CRIME_SEARCH` (and
   `PERSON_NETWORK`/`ALIAS_CHECK`/`SIMILAR_CASES`) already compute their count/sample
   (`orchestrator.py`'s `_run_specialists`). `_handle_more_results` generalizes
   `_handle_case_locations`' own "read the previous turn, not a new query" pattern:
   an honest "that was everything" when `is_sample` is `False`, or a genuinely wider
   re-query (deduped against `shown_ids`) when it's `True`. Chained follow-ups work —
   "only these?" then "what about Mysuru?" correctly carries the crime type forward
   and only overrides the district, verified against the real 10k-case dataset.
   3a. **Bounded deterministic multi-step composition — NEW, not previously named as a
   bottleneck.** "check whether either of those people had a prior case in Bengaluru"
   resolves two person ids (`semantic_interpreter._resolve_comparison_pair`) and
   `orchestrator._handle_comparison` sequences the *existing* single-subject retrieval
   path once per subject — same RBAC, merged evidence scored by the same CRAG
   evaluator as one batch (not independently per subject — a named, deliberate
   simplification, not silently assumed). Explicitly not a general N-step planner;
   three-plus named entities falls through rather than guessing a pair.
4. **Kannada/English code-switching is handled by the translation layer as an
   afterthought — PARTIALLY ADDRESSED.** See §10: the "Mandya → Mandi" class of
   mistranslation is now structurally closed via a 31-entry Kannada-district
   gazetteer lookup-substitution, the same protected-span mechanism FIR/IPC/plate
   identifiers already used. The "priorities" desync (§10) remains open — correctly,
   per the reasoning already in this document: no deterministic fix exists that isn't
   the keyword-patch this whole section argues against.

None of these are "add another regex per sentence" fixes — each extractor above is a
*shape*, not a phrase, matched against structured prior-turn state rather than string
content. What remains bottlenecked on the LLM path (§12): native Kannada
understanding without translation as an intermediate step, and open-ended (3+ clause,
3+ entity) planning.

## 6. Conversational architecture — target semantic concepts

Not "which of 30 intents." A turn should decompose into:

| Concept | What it captures | Where it partially exists today |
|---|---|---|
| **operation** | what the officer wants done: look up, count, compare, trace, forecast, explain-the-last-answer, save-to-board | `intents.classify()`'s output, flattened into 30 labels |
| **subject** | the case/person/district/account this is about | `SessionFocus.active_person/active_fir/active_location` |
| **reference** | how the subject was named: explicit, pronoun, "this case," positional ("the first one") | `has_unresolved_reference()` (person only) |
| **constraints** | date range, crime type, district, confidence threshold | `SessionFocus.active_date_range` (declared, barely used); crime-type/district extracted ad hoc per-intent (`_crime_type_from_query`, `_district_code`) |
| **previous result set** | what the last turn actually returned, and whether it was exhaustive or a sample | Citations/evidence on the stored turn exist (`data.models.ConversationTurn`); no "was this a sample" flag |
| **comparison** | "both of them," "which is worse," "compare to the district average" | Only `TIMELINE_CONNECTION`'s two-person case |
| **correction** | "no, the other Ramesh" | Handled once, ad hoc, via the ambiguous-person clarification path — not a general "revise the last resolution" concept |
| **clarification response** | the officer answering "which one did you mean" | Not modeled as a distinct turn type — a clarification answer is just another query re-classified from scratch |
| **exploration/expansion** | "go deeper," "what else," "show more" | `NEXT_STEPS`, `EVIDENCE_FOR` partially cover "why"/"what supports this"; "show more of what you just gave me" has no handler |
| **explanation of prior results** | "why are you showing me this" | `EXPLAIN_REASONING`, genuinely general — reads the stored trace, not a fresh search (`orchestrator.py:959-970`) |

**Target flow**: an LLM call (QuickML, `generate_json` — already exists,
`rag_agent/llm.py:200`, schema-constrained, degrades to `{}` on any failure) fills
this structure from the raw query + the previous turn's stored state. The **30 current
intents become the values the `operation` field is allowed to take** — an
implementation compatibility layer, not something torn out. `node_orchestrate` reads
the structured `operation`/`subject`/`reference`/`constraints` instead of running
`classify()` on raw text; when the LLM is unavailable (see §12 — it currently is, in
production), `classify()` runs exactly as it does today and fills the same structure
deterministically. Nothing downstream of `node_orchestrate` needs to change for this
migration to land incrementally, because `_run_specialists`/`_handle_*` already
dispatch on `state.intent` — the boundary is drawn at exactly the seam that already
exists.

## 7. Tool selection

Already correct in shape, and should stay this way through the §12 migration: an
`operation` maps to exactly one deterministic capability —

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
| open-ended narrative | `vector_agent.search` (hybrid dense+BM25), only when nothing structured settles it (`orchestrator.py:668-675`) |

This table is *not* the problem this brief is naming — the mapping from "what does the
officer want" to "which deterministic tool answers it" is sound. The problem is
entirely upstream, in how reliably a raw utterance produces the right `operation` in
the first place (§5, §6).

## 8. Result awareness

Where it's real: `CRIME_SEARCH` reports an exact count from `COUNT(*)` scoped by
role/station, not an estimate, and separately samples for citation
(`orchestrator.py:479-495`); `CASE_LOCATIONS` re-derives a tally from exactly the FIRs
the previous turn cited, re-checked against current policy scope, not a fresh
unscoped query (`orchestrator.py:761-767`).

**Built (2026-08-27, §16).** `InvestigationState.result_context` /
`ConversationTurn.result_context` now stores exactly `(operation, total_matched,
shown, is_sample, shown_ids, constraints)` on every turn that produces a bounded
result set — `CRIME_SEARCH`, `PERSON_NETWORK`, `ALIAS_CHECK`, `SIMILAR_CASES`. "Only
these?" / "are there more?" (`semantic_interpreter._AMBIGUOUS_MORE_RE`, context-
disambiguated against an unbounded "tell me more about the subject" reading) routes
to a new `RESULT_SET_FOLLOWUP` operation, handled by `orchestrator._handle_more_results`
— the generalized version of `_handle_case_locations`'s own pattern this section
previously named as the template. `PERSON_NETWORK`/`ALIAS_CHECK` are recorded as
`is_sample=False` (exhaustive within the policy depth cap, not a sample of a larger
population) so a follow-up gets an honest "yes, that's everything" rather than a
pointless re-search; `SIMILAR_CASES` is recorded `total_matched=None,
is_sample=True` — a ranked top-N has no honest "total exists" number, and saying so
(rather than inventing one) is itself the correct behavior.

## 9. Investigation memory — three tiers, kept genuinely distinct

1. **Conversation history** — `data.models.ConversationTurn`, one row per turn
   (query, answer, citations, evidence, visualization, trace), persisted so
   `EXPLAIN_REASONING`/`EVIDENCE_FOR`/`CASE_LOCATIONS`/pin-to-board can all read the
   *previous* turn without re-running retrieval.
2. **Active session focus** — `SessionFocus` (`data/models.py:15`): `active_person`,
   `active_fir`, `active_location`, `active_date_range`. Ephemeral, one per session,
   overwritten every turn, persisted so it survives a page reload
   (`upsert_session_focus`, called from both `node_orchestrate` and `node_retrieve` —
   `orchestrator.py:200-203, 339-342`).
3. **Persistent investigation state** — `vx_case_board_item`
   (`data/board.py:16-18`), discriminated by `ItemType ∈ {evidence, person, lead, note,
   question, finding}`. `lead` carries its own status machine (`open → pursued |
   dismissed`) and a dismissed lead is *never deleted* — `remove_item` explicitly
   refuses to delete a lead (`board.py:116-117`) — because "a dismissed lead must
   remain auditable" is enforced structurally, not by convention. `evidence`/`finding`
   store a reference (`ref_type`, `ref_id`) plus a content *snapshot*, never a second
   copy of the record layer that could drift (`rag_agent/board.py:10-12`).

These three tiers are correctly kept from collapsing into each other: `active_evidence_id`
(which console card is selected) is explicitly *not* part of `SessionFocus` because it
is a UI hint, not identity (`state.py:81-84`); board items are explicitly not folded
into `SessionFocus` because a board is investigator-authored state, not inferred
context. This separation is a real strength worth preserving through any future
refactor.

## 10. Multilingual / code-switching — a first-class problem, tested against the real model

`node_translate_in` (`orchestrator.py:95-117`) runs kn→en translation before anything
else touches the query, because every downstream matcher — keywords, IPC/plate
regexes, gazetteers — is Latin-script only. `detect_language()` is a single
whole-string check ("contains any Kannada codepoint → 'kn'";
`data/nlp/translate.py:113-115`) — deliberately simple, and, per the experiments below,
correct enough to leave alone: it reliably triggers translation exactly when the
sentence needs it, mixed-script or not.

**What was tested directly against `facebook/nllb-200-distilled-600M` on this host**
(not assumed, not mocked — the actual weights, the actual code path), because a claim
about translation quality is only as good as the model call that backs it:

- Ordinary code-switching translates well as a whole sentence: *"ಆ case ಗೆ related
  ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"* → *"Is there another FIR related to that case?"* — correct,
  and "FIR"/"case" pass through as themselves.
- A long embedded FIR number survives digit-for-digit on its own in every test run —
  NLLB does not, on the evidence gathered, corrupt long digit runs.
- **A found, real bug**: *"Usha Naika ಗೆ priors ಇದ್ಯಾ?"* (a direct, realistic
  "does she have priors" code-switch) translates to *"Does Usha Naika have
  **priorities**?"* — and `\bpriors?\b` (`intents.py:16-18`) does not match
  "priorities." This sentence, asked exactly as a bilingual officer would ask it,
  silently fails to classify as `PERSON_HISTORY` after translation. Not fixed this
  pass — see below for why, and what the real fix is.
- **A second found, real bug**, unrelated to the first: *"ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ FIR
  100222201202600022 ...?"* translates "ಮಂಡ್ಯ" (Mandya) to **"Mandi"** — a real but
  wrong, more common Indian place name — specifically when "FIR" and a number both sit
  in the sentence. Ablated carefully (5+ variants, see `data/nlp/translate.py`'s module
  comment): it is not the digit *length* (a short placeholder reproduces it too, given
  "FIR" is present), and it is not present at all for "ಬೆಂಗಳೂರು" (Bengaluru) in the
  identical construction. This reads as a genuine model-quality gap — a less common
  Kannada place name losing to a more common phonetic neighbour under this specific
  grammatical pressure — not something a pre-translation substitution fixes.
  **Confirmed live, post-deploy, and worse than the local finding suggested**: this is
  not merely a wrong word in the answer — it breaks the turn completely. "Mandi" is not
  a real district, so `entities.py`'s NER tier-2 fallback reads it as an unresolved
  PERSON name; `node_orchestrate` then reports `"no person matching 'Mandi' exists in
  the records"` and refuses the whole query with `person_not_on_file` — **even though
  the FIR number itself survived perfectly and `FIR_LOOKUP` was correctly identified as
  the intent**. An officer asking about a real, specific Mandya FIR by number, in
  exactly the natural code-switched phrasing this product's own mission statement names
  as a target case, gets a flat refusal. A control query with the district name removed
  (`"FIR 100222201202600022 ಬಗ್ಗೆ ಏನಿದೆ?"`) was run against the same live deployment
  immediately after and answered correctly (FIR 9992, confidence 0.97, fully grounded
  Kannada answer) — confirming the deployed identifier-protection fix genuinely works
  end to end in production, and isolating this refusal to the Mandya-specific
  translation defect alone, not a regression from this pass's own change.

**What the identifier-protection pass built**: protected-span translation. FIR numbers,
IPC codes and vehicle plates are now removed before the string reaches NLLB and spliced
back verbatim after (`data/nlp/translate.py:_protect_spans/_restore_spans`, wired into
`translate()`). This makes identifier fidelity a **structural guarantee** — provably
true regardless of what the model does with the rest of the sentence (tested with a
hostile stand-in backend, `data/tests/test_nlp.py`) — rather than a "the model happened
to get it right in every test we ran" hope. At the time, it did not fix either bug
above: "priorities" isn't a numeric span, and "Mandya→Mandi" was ablated and shown not
to be caused by the unprotected number specifically.

**"Mandya→Mandi" — FIXED (2026-08-27, §16), correcting this document's own earlier
claim that no application-layer fix existed.** That claim was true for protecting the
*number* beside the district name; it did not consider protecting the district name
*itself*. `_protect_spans` now takes a `src` parameter and, when translating from
Kannada, runs a second pass against a closed, 31-entry Kannada-script district
gazetteer (`data.districts.kannada_name_map`, sourced from kn.wikipedia.org's district
list and cross-checked 2026-08-27 — flagged in code for a native-speaker QA pass before
being extended beyond the districts this fix was verified against) — a **lookup
substitution**, not a translation: the district name never reaches NLLB at all, so the
model cannot mistranslate what it never sees. Verified with a hostile backend that
actively corrupts any Kannada district name it's shown (`data/tests/test_nlp.py`) —
the correct English name comes back regardless. This closes the whole class (any of
the 31 districts), not just the one reported instance.

**"priorities" stays correctly open.** Fixing it by adding a `PERSON_HISTORY` keyword
alias would be exactly the reflexive keyword-patch this brief argues against in §5 — it
treats a translation-quality symptom as an intent-layer problem. Blind suffix-stemming
of intent keywords (checked this pass) was considered and rejected: it would make "this
is a high priority case" spuriously score `PERSON_HISTORY`. The principled fix is still
the §12 LLM path: a semantic interpreter reading "Does Usha Naika have priorities?" (or
the untranslated Kannada directly) infers `PERSON_HISTORY` from meaning, not from one
exact English noun surviving machine translation intact.

## 11. Voice

`node_voice_in` → ASR (`data/nlp/speech.py`, faster-whisper, self-hosted — Zia has no
STT/TTS/translation service, confirmed against Catalyst's actual service catalog, see
`CLAUDE.md §2`'s documented exception, not assumed) → the **identical** text pipeline
every typed query goes through (translate → orchestrate → retrieve → evaluate →
synthesize) → `node_voice_out` (TTS, same self-hosted layer). Voice gets no special
semantic handling and needs none: by the time `node_orchestrate` runs, a transcribed
query and a typed one are the same `state.original_query` string. The only
voice-specific concern is ASR noise/disfluency reaching the classifier as literal text
— not evaluated this pass (would need real ASR output samples, not synthetic ones, to
test honestly — noted as unverified rather than assumed fine).

## 12. Resource constraints — the semantic interpreter and QuickML runtime

**Current configuration verification (2026-08-28):** the official REST QuickML path is
configured for the existing custom-runtime AppSail. The refresh token is stored only in
the Development AppSail environment at `configuration.environment.variables`; the
existing variable map was preserved (7 variables after adding it). The supported update
operation is `POST /baas/v1/project/{projectId}/appsail/{appSailResourceId}/configuration`
with `{"environment":{"variables":{...}}}`. The resource id is `52852000000204688`,
not the public hostname number `50043864344`. A synthetic Development variable was
written and removed with HTTP 200 responses, proving the route before storing the secret.
The running container still requires a fresh AppSail deployment to receive this runtime
configuration; no production data or alternate service is involved.

**QuickML (the LLM) is currently unreachable in production — root-caused precisely
this pass, not re-asserted from a prior check.** Two separate, now-resolved
questions:

1. **Is `GLM-4.7-Flash` real, and does it support what §6 needs (conversation
   context, tool calling)?** Yes — checked directly against current Catalyst docs
   (`docs.catalyst.zoho.com/en/quickml/help/available-models/glm-4.7-flash/`):
   "Conversation Mode" (prior messages retained as context) and tool/function
   calling are both documented, tool calling "Supported on GLM 4.7 Flash only."
   This is genuinely the right model for a planning layer, if it were reachable.
2. **What was actually blocking `llm.py`, precisely?** More than a missing key.
   `pip install zcatalyst-sdk==1.4.0` and reading `zcatalyst_sdk/quick_ml.py`
   directly (not assumed from marketing docs, which describe Node/Java-only
   `askLlm()`/`converseWithLlm()` methods that do not exist in the installed Python
   SDK) shows the **only** QuickML method the Python SDK exposes is
   `app.quick_ml().predict(end_point_key, input_data)` — a generic ML-pipeline
   call: `POST {base}/quickml/v1/project/{id}/endpoints/predict`, header
   `X-QUICKML-ENDPOINT-KEY`, body `{"data": {flat str/int dict}}`. Every prior
   version of `llm.py` called a **hand-built URL** with a **raw urllib POST** and a
   **guessed OpenAI chat-completions body** (`{"model","messages","temperature"}`)
   — a shape that does not match the real SDK contract at all, independent of
   whether a key existed. `llm.py` is rewritten this pass to call the real SDK
   method (`_predict()`); the base URL/project id/auth are now resolved by the
   SDK's own `AuthorizedHttpClient` (the app's admin credential, the same
   mechanism every Data Store/Cache call already uses) instead of being guessed —
   `QUICKML_ENDPOINT` is gone, it was never a real requirement.
   - **What remains an honest guess**: the exact `input_data` key name(s) an LLM
     Serving endpoint expects (`PROMPT_FIELD`, default `"prompt"`) — the generic
     ML-pipeline docs show arbitrary column-name keys, and GLM-4.7-Flash's own
     page states "Input type: Text only" without naming the field. Unverifiable
     without a live `endpoint_key`, which does not exist in this environment.
   - **The `endpoint_key` itself remains obtainable only through the console**:
     Generative AI → LLM Serving → a model's Model Details → API Details popup.
     Confirmed by direct probing this pass — `GET .../appsail/get-signature`-style
     listing/creation paths under both `quickml/v1/...` and `baas/v1/.../quickml`
     all 404 — there is no Admin API equivalent, the same conclusion every prior
     check reached, now backed by an actual attempt rather than an assumption.
     Re-confirmed directly against the live AppSail app's own `configuration`
     object: `QUICKML_ENDPOINT_KEY` is absent entirely (2026-08-27).
   - **What this means for the officer**: obtaining a real key requires a human
     with console access to publish an LLM Serving endpoint for GLM-4.7-Flash and
     copy its key — that action cannot be performed or verified from this
     environment, no matter how the integration code is written.
3. **A second, deeper blocker — found by actually invoking `predict()`, not just
   confirming the key is absent.** "Do not blindly trust the previous
   conclusion" (this pass's own instruction) was taken literally: a deliberately
   invalid `QUICKML_ENDPOINT_KEY` was set on the live app for the duration of
   one real call, to see what the SDK does when it actually runs. The result
   was not a key-validation error — the request failed before that, with
   `CatalystAPIError ... 'code': 'ORGID_HEADER_UNAVAILABLE'`. Traced to
   `zcatalyst_sdk/_http_client.py`: the `CATALYST-ORG` header is only attached
   when `os.getenv('X_ZOHO_CATALYST_ORG_ID')` is set, and this app's container
   does not have it — unlike Data Store/Cache/every other Catalyst call this
   app makes successfully, which apparently don't need it. Two things rule out
   a workaround, not just "not yet tried": setting that env var through
   `POST /appsail/{id}/configuration` (the same endpoint that manages every
   other env var here) is rejected outright as a reserved keyword; and the
   AppSail gateway's own per-request headers (`X-ZC-ProjectId` etc.) carry no
   org id in any form this SDK reads. **The honest conclusion: even a real,
   published `endpoint_key` would not be sufficient on its own** — this is a
   platform gap for `custom_runtime` AppSail apps calling QuickML specifically,
   not a missing credential. The diagnostic key was reverted immediately after
   the one test call; live state and behavior are unchanged from before this
   probe (verified via `/health` before and after).
4. **The org-id gap is not a `custom_runtime` limitation — it is project-wide,
   verified by physically deploying and calling QuickML from two other Catalyst
   runtimes, not by re-reading docs.** Current official docs
   (`docs.catalyst.zoho.com/.../appsail/implement-catalyst-sdk/`) do state "You
   will not be able to implement Catalyst SDK for apps deployed as OCI images
   through custom runtime" — consistent with the mega-prompt's premise that
   migrating to a **Catalyst-managed Python AppSail** runtime might clear the
   gap. It does not. Two new, additive, throwaway probes were built and
   deployed into this same live project (zero KSP data touched, zero change to
   `veritas-api`):
   - A minimal Catalyst-managed Python AppSail app (`services/semantic_quickml/`,
     stack `python_3_9`, deployed as `veritas-semantic-probe`,
     appComputeId `52852000000346023`) — `quick_ml().predict()` with a
     diagnostic invalid key returns the identical
     `CatalystAPIError ... 'code': 'ORGID_HEADER_UNAVAILABLE'`.
   - A minimal Catalyst-native Basic I/O Function
     (`functions/veritas_semantic_probe_fn/`), the most "native" compute Catalyst
     offers, with no container and no AppSail gateway involved at all — same
     call, same diagnostic key, byte-for-byte identical
     `ORGID_HEADER_UNAVAILABLE`.
   - Also re-confirmed on the managed AppSail probe: setting
     `X_ZOHO_CATALYST_ORG_ID` manually via `POST /appsail/{id}/configuration` is
     rejected as a reserved keyword there too, exactly as on `veritas-api`.
   - **Conclusion**: no AppSail runtime type, and not even a Catalyst Function,
     is the fix. This project's Zia Hub linkage (the internal gateway QuickML's
     error message names — `ziahub.error.ORGID_HEADER_UNAVAILABLE`) is missing
     org context for every programmatic/service-credential call tested, not for
     one runtime shape. **What was not ruled out**: whether publishing a real
     endpoint through the console UI (an interactive, cookie-authenticated
     session with org context already attached) is itself the action that
     establishes this linkage server-side — every call tested here used a
     deliberately-invalid diagnostic key, because no real key has ever been
     obtained. That remains the one untested variable, and it requires a human
     with console access; it cannot be produced or simulated from this
     environment.
   - The two probe resources were left deployed (not deleted) so this finding
     is independently re-checkable without rebuilding them.
5. **QuickML actually works — over plain REST, not the SDK, and the runtime
   question in item 4 turns out to be moot.** The Catalyst console's own
   QuickML integration page (not the general SDK docs) names a completely
   different, working contract: a dedicated OAuth self-client scoped to
   `QuickML.deployment.READ`, a manually-supplied `CATALYST-ORG` header (a
   static, already-known id — nothing needs runtime injection), and a
   documented REST endpoint, `POST
   api.catalyst.zoho.in/quickml/v1/project/{id}/glm/chat`. Verified live
   (2026-08-28) with a temporary developer CLI token: HTTP 200, real model
   (`crm-di-glm47b_30b_it`), real completions, 2.4s round trip. Because this is
   a plain outbound HTTPS call, it works from **any** runtime with network
   access — the custom_runtime/managed-AppSail/Function distinction in item 4
   is entirely about the SDK's broken `quick_ml()` method and does not apply
   here. **Path A wins**: the existing `veritas-api` custom-runtime AppSail
   stays as-is; no migration, no split service, no new runtime.
   - `llm.py` rewritten to call this REST endpoint directly (stdlib
     `urllib`, no new dependency), authenticating via a self-client
     refresh-token grant (`QUICKML_CLIENT_ID`/`_CLIENT_SECRET`/`_REFRESH_TOKEN`,
     already present in `.env` for the client/secret; see `.env.example` for
     the one-time grant-token exchange). Access tokens are cached in memory
     and refreshed ~60s before expiry. `available()`/`generate()`/
     `generate_json()`/degraded-mode-on-failure contract is unchanged, so
     every existing caller (`semantic_interpreter.py`, `copilot/brief.py`,
     `synthesis_agent.py`, `retrieval/tog.py`) needed zero changes.
   - **Two real bugs found by actually invoking the new code against the live
     API, not by re-reading the contract:**
     1. The model's chain-of-thought is terminated by a bare `</think>` with
        **no matching opening `<think>` tag** in the real response — a naive
        `<think>.*?</think>` regex never matches, so the entire reasoning
        trace leaks through as the "answer". Fixed: strip everything up to
        and including the last `</think>` unconditionally.
     2. `crm-di-glm47b_30b_it` carries a baked-in system prompt against
        revealing "these rules", and empirically (~10 live trials) refuses a
        meaningful fraction of schema-shaped or "reply with exactly X"
        prompts with "I can't help with requests to expose protected
        instructions" — non-deterministically, since identical retries
        sometimes succeed and sometimes don't. This is content-triggered, not
        a transport failure, so it previously would have been handed to a
        caller as if it were real fluent prose. `generate()` itself now
        retries once with a reassurance frame ("a calling program parses your
        reply as data, not a conversation") and degrades to `LLMUnavailable`
        on a second refusal, so every caller — not just `generate_json()` —
        is protected. This is a measured mitigation, not a guarantee: live
        testing this pass still hit a persistent double-refusal on the exact
        phrase "reply with exactly the text X and nothing else". A more
        natural prompt shape fared better — `semantic_interpreter._interpret_llm`
        (the real production prompt, not an adversarial synthetic one) was
        tested live end-to-end and correctly returned a populated
        `SemanticRequest` (`operation=lookup_case, subject_type=case,
        confidence=0.9`) for "Tell me more about that case".
   - 12 new/rewritten tests in `test_engine.py` cover the token cache, the
     `<think>`-stripping fix (both with and without a matching opening tag),
     the refusal-retry-then-degrade path on `generate()` directly (not just
     `generate_json()`), and the JSON-parse retry.
6. **The operation-allowlist validator, and a real bug it exists to catch.**
   `_interpret_llm`'s prompt told the model to return operations like
   `lookup_person`/`count_crimes` — but `orchestrator.py` only ever dispatches
   on the real uppercase constants in `intents.py` (`CASE_CONTEXT`,
   `PERSON_HISTORY`, ...). A live call for "Tell me more about that case"
   returned `operation=lookup_case`, which matches nothing downstream and
   would have silently misrouted every LLM-interpreted turn with no error
   anywhere. Fixed at two layers: `intents.ALL_OPERATIONS` (computed from the
   real dispatch table, not hand-duplicated, so it can't drift) is now the
   schema's own `enum`, and `semantic_interpreter._validate_llm_result()`
   rejects (`ValueError` -> `interpret()`'s existing fallback) anything
   outside it regardless of what the model actually returns, with
   case-normalization for a formatting slip (`case_context` -> `CASE_CONTEXT`)
   versus a hallucinated capability (`lookup_case`, rejected). Also validates
   subject_type/reference_kind/constraints/comparison_entities types and
   clamps (not rejects) out-of-range confidence. Structurally, not just by
   convention, the model has no field this validator ever reads as
   `subject_id` — resolution is always a real `sql_agent.person_by_name`
   lookup, so a planted id in the model's JSON has zero effect (tested). 15
   new tests in `test_semantic_interpreter.py`.
7. **The refresh token was obtained and QuickML is live in production**,
   verified by more than `/health` reporting configured. `/health`'s `llm`
   field went `"quickml (glm-4.7-flash) — configured, not yet contacted"` ->
   `"quickml (glm-4.7-flash)"` (the latter only ever set by
   `_ever_succeeded=True` inside `_chat()`, i.e. a real completion) the moment
   the first live conversational query ran post-deploy. Live-tested
   end-to-end, real HTTP through `/chat`, not a probe script: **"Give me the
   lowdown on whatever case just came up."** (deliberately unseen colloquial
   phrasing, no keyword in any `INTENTS` list) correctly interpreted as
   `CASE_CONTEXT` at confidence 0.8 by the real model, and correctly refused
   ("no case is open") rather than guessing one — the deterministic safety
   guard downstream of the semantic layer working exactly as designed.
8. **A second real bug found by this same live test, more serious than a
   wrong answer: latency.** `interpret()` called the LLM path unconditionally
   on *every* query, including an exact `FIR 100222201202600022` lookup —
   paying a full 16.8s QuickML round trip before ever reaching the
   deterministic exact-match answer (confidence 1.0) that was always going to
   win. The architecture brief always specified "deterministic fast path for
   obvious requests, QuickML only for genuine ambiguity"; the code never
   actually implemented that hybrid routing. Fixed: `interpret()` now runs
   `_interpret_deterministic()` first (microseconds), and only calls the LLM
   when that result's confidence is below `_LLM_ROUTING_THRESHOLD` (0.75) —
   below that line is genuinely UNKNOWN/low-confidence territory, which is
   exactly where a semantic model adds value over a confident structural
   match *or* a confident structural refusal (e.g. an ambiguous-name tie,
   which the model cannot resolve any better since it is a real database
   fact, not a phrasing problem). The LLM result only wins if it is at least
   as confident as the deterministic one it is being compared against — a
   second opinion, not an automatic override. 3 new tests in
   `TestLLMRouting` (`test_semantic_interpreter.py`).
9. **Live-verified end to end against production** (deployment
   `52852000000346035`, real `/chat` traffic, not a probe script):
   - Exact FIR lookup: `Orchestrator (semantic)` step dropped from 16,820ms
     (item 8's bug) to **9ms** — the routing fix, confirmed on the live path.
   - **The full target vertical slice, genuinely working**: "Any idea who
     else was tangled up in it?" (deliberately unseen colloquial phrasing, no
     keyword overlap with any `INTENTS` entry) → QuickML correctly interpreted
     it as `CASE_PEOPLE` (confidence 0.9) against the open case in focus →
     deterministic SQL retrieval → real accused persons (Usha Naika, Soom
     Nadkarni — the same romanisation-variant pair BUG-026 already documented)
     → CRAG confidence 0.95 → grounded citations → network visualization.
   - Multi-turn continuity and cross-instance state persistence in one test:
     a session opened *before* this pass's redeploy ("What is the status of
     FIR ...") was continued *after* the container was fully replaced — "Tell
     me about this case" on the same `session_id` correctly resolved
     `active_fir` from `vx_session` (Data Store), not process memory, and
     answered about the right FIR. This is the restart/scale-out survival
     property, proven by a real deploy rather than a synthetic kill test.
   - RBAC still holds: an IO (station 101) querying a Mandya FIR (station
     2201) got 0 records within policy scope and the `exact_lookup_missed`
     refusal — not the cross-station leak that same code path used to produce
     before BUG-fix v10.
   - A genuine two-entity multi-step query ("Check whether either Usha Naika
     or Soom Nadkarni had a prior robbery case around the same time") resolved
     via the deterministic `_COORDINATION_RE` bounded-comparison path
     (confidence 0.75 — exactly the routing threshold, so QuickML correctly
     was not consulted for interpretation), correctly compared both subjects
     (254 combined evidence items, CRAG confidence 1.0, 12 citations) — and
     when the LLM-based prose synthesis step itself timed out (30s), the
     deterministic extractive synthesis fallback still produced a real,
     grounded, cited answer. This is the core safety property — "the LLM
     makes an answer fluent, never true" — observed holding under a genuine
     live LLM failure, not just asserted.
   - Kannada-English code-switching works: "Mandya alli ಎಷ್ಟು theft cases
     ಇವೆ ಈ ವರ್ಷ?" resolved deterministically to `CRIME_SEARCH` (confidence
     0.9, 1ms) with a correct count (73 matching cases).
   - **Correction to a claim in this same section, found and fixed within
     the same pass**: pure-Kannada was first reported here as failing live.
     That was wrong, and the error was in the test, not the system — the
     Kannada query had been passed to `curl` as an inline shell string inside
     a bash heredoc, which does not reliably preserve multi-byte UTF-8 through
     Git Bash's argument handling on Windows; the bytes that actually reached
     the API were not valid Kannada. Re-sent the identical query as a
     UTF-8-encoded JSON file via `curl --data-binary @file` (bypassing shell
     string interpolation entirely) and it worked correctly: `Translation
     Agent (kn->en)` fired (518ms) — `"Query understood as: How many cases of
     theft are there in District Mandya?"` — classified deterministically as
     `CRIME_SEARCH` (confidence 0.9, 14ms, correctly skipping QuickML per the
     routing fix), and returned the correct count (73 matching Theft cases in
     Mandya, 6 citations) — matching the code-switched test directly above
     almost exactly. Kannada support was never broken; a testing-methodology
     artifact was. Left in the record rather than silently deleted, because
     the lesson (verify the actual bytes on the wire before trusting a live
     negative result, especially through a shell) generalizes past this one
     bug.
   - **QuickML latency, measured from real production calls this pass (small
     sample, ~12 calls — deliberately not hundreds, per this project's own
     standing Catalyst-cost-minimization practice)**: successful semantic
     interpretation calls ranged 5–23s; the hard ceiling is the 30s
     `VERITAS_LLM_TIMEOUT`, hit twice — both on the malformed-bytes Kannada
     test above (the *test's* garbage input, not a real query the model
     should ever have been asked to interpret). This is a real, load-bearing
     latency cost — exactly why item 8's routing fix (only pay it for
     genuinely ambiguous queries) matters as much as QuickML working at all.
   - **A related, deliberately-untouched latency fact**: `synthesis_agent.
     synthesize()` calls `generate()` for fluent prose whenever `available()`
     is true, on *every* answer — including a fully-resolved, deterministic
     `CRIME_SEARCH` count that already has a clear extractive template — and
     one such call was observed taking ~25s live. This is unlike item 8's
     bug: it is the module's own documented design ("With an LLM the prose is
     fluent; without one it is extractive"), predates this pass, and was
     never in scope here — item 8 was specifically about *whether QuickML
     gets consulted for interpretation at all*, which had no such intentional
     rationale behind always running. Left as-is rather than changed on this
     pass's own initiative; worth a deliberate product decision (is 20-30s of
     extra latency for marginally more fluent phrasing on an already-good
     extractive answer worth it?), not a silent fix.

The architecture in §6 was correct; it is live via the deterministic path AND,
for the first time, genuinely via the model path too. `rag_agent/
semantic_interpreter.py` (`interpret()` function, `SemanticRequest` model)
deployed to `node_orchestrate`. The 30 current intents remain the
compatibility layer, valid values for the `operation` field.

10. **The one-day final push — item 9's own "deliberately-untouched" synthesis
    latency became this pass's first priority, plus three real findings from
    a new held-out evaluation.**
    - **Synthesis latency, fixed, not merely diagnosed.** `synthesize()` now
      takes the resolved `operation` and only calls QuickML when it's in the
      new `intents.NEEDS_NARRATIVE_SYNTHESIS` set (financial trails,
      networks, risk, causal, similar-cases, next-steps, briefings, timeline
      connections, and person-history — which covers the bounded two-entity
      comparison path too, since it reuses whichever base operation
      `classify()` returned). A direct factual retrieval (a status, a count,
      a list of names) gets the extractive template with **zero** latency
      cost; a genuinely narrative question still gets the full LLM pass.
      **Live-measured before/after on the identical query**: a FIR status
      lookup — interpretation + synthesis together — went from ~16.8s to
      **1.4s total, end to end** (`Evidence Synthesis` step: 0ms, was
      20-30s). A `PERSON_NETWORK` question in the same session still
      correctly invoked QuickML for its narrative (`Evidence Synthesis`:
      15.6s, 17.1s total) — the routing is selective, not a blanket
      LLM-off switch. 6 new tests, `test_synthesis_routing.py`.
    - **A real multi-step gap, closed**: "Look at the financial trail around
      this case" (a required flow named explicitly in this pass's own
      brief) used to refuse `no_subject` even though the open case's own
      accused was one join away — `FINANCIAL`/`PERSON_NETWORK`/
      `PERSON_HISTORY`/`ALIAS_CHECK` all require a resolved person, and
      nothing previously fell back to the case in focus when none was
      named. `orchestrator._resolve_subject_from_open_case` confirms RBAC
      scope on the case first, auto-resolves when there's exactly one
      accused, and asks (`ambiguous_person`, never guesses) when there are
      several — with its own early return so a decided ambiguity doesn't
      fall through into a real retrieval it already refused (the BUG-006
      class this codebase explicitly guards against elsewhere). Live-tested
      end to end: a 2-accused case correctly triggered "case has 2 accused;
      asking rather than guessing" rather than a blind refusal or a guess.
      3 new tests, including one against the real generated dataset (a
      single-accused case found dynamically, since not every case has
      exactly one).
    - **A new held-out evaluation** (`test_conversational_evaluation.py`,
      17 scenarios, genuinely unseen phrasings not reused from any other
      test file) immediately found a real routing-precision bug: the
      deterministic "no keyword matched, but a subject IS resolved —
      default to the richest profile" fallback (`PERSON_HISTORY`) was
      scored at confidence 0.9, the same tier as an actual keyword match.
      That let it outrank a *correct* 0.82-confidence model answer
      (`PERSON_NETWORK`, for "who's this person tied up with?") under this
      session's own routing fix — backwards for a fallback that is,
      structurally, a guess. Now scored 0.65, deliberately below the 0.75
      routing threshold, so real semantic understanding can override the
      generic default when the model is available and more specific. The
      two other `_default_operation_for_subject` call sites (ordinal/"other"
      positional references) are unaffected — there the subject is resolved
      with certainty and only the verb is defaulted, a different confidence
      class entirely.
    - **One gap found and left honestly unfixed, on purpose**: a correction
      with no other verb/keyword ("no, I meant Mysuru") extracts the new
      district constraint (`_extract_constraints` runs unconditionally) but
      does not carry the prior turn's operation forward — `classify()`
      scores it `UNKNOWN`. Not patched with a "no, I meant" phrase rule
      (which this evaluation's own purpose rules out); correctly stays below
      the routing threshold (0.3 < 0.75) so QuickML — which does have the
      semantic understanding to treat this as a correction — is consulted
      in the live system. That live behavior was **not** itself re-verified
      this pass (cost-conscious QuickML usage), stated as untested rather
      than assumed working.
    - **Deployed and live-verified**: new deployment `52852000000356033`
      (was `52852000000346035`), `/health` confirmed, and the three
      live checks above run against production, not a local dev server.
    - **Not done this pass, named rather than silently skipped**: a fresh
      browser/CDP session (nothing UI-facing changed, so the prior
      sessions' CDP verification of the console itself stands, but this
      pass's specific latency/routing improvements were not independently
      re-shown in the browser); a general N-operation composable planner
      (`operations: []` on `SemanticRequest`) for open-ended chains like
      "who else is connected to this person, and which of them appear in
      other cases" — the case-scoped subject resolution above is a
      targeted, well-scoped fix for one named example, not a general
      multi-hop composition engine, and building the latter honestly needs
      its own design pass rather than being rushed into a single-day push.

11. **The general N-step investigation planner named as deferred above, built —
    and, alongside it, a genuinely semantic fix for the correction gap item 10
    left open on purpose.** Both extend the existing seam (`SemanticRequest`,
    `node_orchestrate`, `_run_specialists`) rather than replacing it: nothing
    about what an operation *does* changed, only how many of them one turn can
    chain, and how a turn is interpreted relative to the one before it.
    - **`SemanticRequest.plan_steps`**: the LLM path's JSON schema gained an
      optional `steps` array, each item shaped exactly like the existing flat
      single-op response plus three fields — `depends_on_step` (reuse an
      EARLIER step's own resolved subject), `fan_out` (repeat this step once
      per entity that earlier step's operation actually found — bounded to 5,
      `orchestrator._MAX_FAN_OUT`), and `position` (the Nth item in the
      PREVIOUS turn's own citation list). Absent, or a single item, the schema
      is byte-for-byte what it always was — a plan is opt-in generalization,
      not a rewrite of the common case. Every step's `operation` is validated
      against the exact same `intents.ALL_OPERATIONS` allowlist the flat shape
      always used (`_validate_llm_step` wraps `_validate_llm_result`); one bad
      step invalidates the WHOLE plan (`_build_plan_request`), the same
      all-or-nothing contract a malformed flat response already had — never a
      partially-executed plan with an unvalidated step silently dropped. The
      model never supplies a subject id anywhere in a step, exactly as it
      never could in the flat shape — `_resolve_person_by_text` (extracted
      from the flat path, now shared) is the one DB-grounded resolution step,
      for both.
    - **`orchestrator._run_plan`** executes a validated plan by calling
      `_run_specialists` once per (step, resolved subject) pair — the exact
      function every ordinary single-op turn already uses, so a plan adds no
      new way to reach the record layer, no new RBAC surface, and no new CRAG
      path: all steps' evidence merges into one batch and passes through the
      SAME evaluator node a single-op turn's evidence does. A step that cannot
      safely resolve its subject (an unresolved dependency, a `position` with
      nothing at that index, a tied name search) stops the WHOLE plan with a
      clarification (`plan_step_unresolved` or `ambiguous_person`) rather than
      guessing or silently skipping that step. This generalizes, and sits
      alongside without replacing, the existing bounded two-entity
      `_handle_comparison` path (`semantic_interpreter._COORDINATION_RE`,
      deterministic, free, still the fast path for "either of them"/"both of
      them"): a plan can chain 3+ subjects, DIFFERENT operations per subject,
      and fan out over a dynamically-sized result set, none of which the
      bounded 2-entity path can express by construction.
    - **Corrections made semantic, not phrase-matched — item 10's own
      deliberately-left-open gap.** `state.last_request` (new
      `InvestigationState` field) snapshots THIS turn's own structured
      request in `node_orchestrate`, untouched by every specialist branch
      that overwrites `result_context` wholesale; `apps/api/routers/chat.py`
      merges it into the persisted turn's `result_context` at the one point a
      turn is actually written, so it round-trips through Data Store like any
      other field — no schema migration, no second persisted object. The
      NEXT turn's `_interpret_llm` reads it back and hands the model BOTH the
      previous turn's prose AND its structured request, with an explicit
      instruction to return a MERGED, corrected request — carrying forward
      every field the new query doesn't itself override — when the query
      reads as an adjustment rather than a fresh question. "Actually
      Bengaluru, not Mysuru" is now the model's own semantic judgment over
      two structured objects, validated by the identical allowlist/type
      checks as everything else it returns, not a new regex — precisely the
      "general and semantic, not phrase-specific" bar this was held to.
    - **Temporal corrections ("same thing but earlier") actually reach the
      database.** `sql_agent.search_firs` had accepted `date_from`/`date_to`
      since it was written; nothing above it ever read a date constraint, so
      a temporal correction could only repeat the SAME window. `count_firs`
      gained the identical two `WHERE` clauses `search_firs` already had (so
      the count and the samples shown can never silently stop matching each
      other), and the `CRIME_SEARCH` branch of `_run_specialists` now reads
      `constraints.date_before`/`date_after` (parsed leniently via `ds.to_dt`,
      dropped rather than failing the turn if unparseable) into both calls.
    - **A held-out GENERALIZATION evaluation**, distinct in kind from item 9's
      conversational-surface evaluation: `test_generalization_evaluation.py`
      (20 tests, one per category in this pass's own brief — unseen
      single-step, unseen multi-step, previous-result references, pronouns,
      corrections, 3+ subjects, multi-dimensional constraints, temporal
      relations, cross-operation comparisons, Kannada, Kannada-English
      switching, ambiguous references/clarification, malformed plans,
      unsupported operations, RBAC denial, empty evidence, conflicting
      evidence, model timeout, restart/state recovery). Two real bugs found
      and fixed while writing it, not after: (1) a 3-subject plan test
      revealed that a raw step-dict `subject_id` is — correctly, by the same
      "the model never supplies an id" rule the flat shape enforces — always
      ignored in favor of `subject_text` resolution, which the first draft of
      the test had gotten backwards; (2) an "empty evidence" plan test
      initially asserted `requires_escalation` after a single `node_retrieve`
      pass, missing that the compiled graph's own `_after_evaluate` edge
      widens once (REFINE) before rejecting — the same two-pass semantics
      `test_empty_first_attempt_widens_before_giving_up` already documents for
      a single-op turn, now exercised for a plan too.
    - **Test suite**: 559 collected (up from the stale 403 this document's
      companion `CLAUDE.md` had been carrying — recount via
      `pytest --collect-only -q`, not trusted from an earlier changelog
      entry), zero regressions — the same two pre-existing, unrelated
      `test_acceptance.py` failures as every prior pass in this document.
    - **Deployed and live-verified**: see the changelog entry below for the
      new deployment id, `/health`, and the live multi-step/correction/RBAC
      checks run against production.
    - **Not done this pass, named rather than silently skipped**: arbitrary
      graph-shaped plans (a step depending on TWO earlier steps, or a
      diamond-shaped dependency) — the implemented plan is linear with
      bounded fan-out, which covers every example this pass's own brief
      gave; a step's `constraints` still cannot express an explicit date
      *range* with both ends at once in one field name (`date_before`/
      `date_after` are two separate keys, not a single `date_range` tuple);
      and the deterministic path was not taught to attempt ANY multi-step
      composition beyond the existing bounded two-entity case — a genuinely
      unseen multi-step question always costs one QuickML round trip, by
      design (that is precisely the kind of question the deterministic
      classifier cannot honestly attempt).

## 13. Failure behavior

| Situation | What happens | Where |
|---|---|---|
| Understood, no evidence | `REJECT` verdict, `NOT_FOUND_MESSAGE`, explicit reason-specific text (14 distinct reasons, not one generic message) | `evidence/evaluator.py:154-238` |
| Ambiguous subject | Named, not guessed — candidates listed, officer asked to disambiguate | `orchestrator.py:139-142`, `REFUSAL_MESSAGES["ambiguous_person"]` |
| Cannot understand at all | Falls to `UNKNOWN` → `CRIME_SEARCH` fallback if any keyword scored, else a generic "not found" — **not** a distinct "I didn't understand you" message; this is a real, honest gap, not covered by the refusal-reason table | `intents.py:293-297` |
| A tool fails | Per-tool `try/except` around specialist calls degrades to "no evidence from this specialist," not a crashed turn (e.g. Copilot briefing's `KeyError`/`NotPermitted` handling, `orchestrator.py:638-643`) | throughout `_run_specialists` |
| LLM unavailable | `LLMUnavailable`/`{}` → deterministic template path, same citations, no degradation in *correctness*, only in prose fluency | `llm.py:23-31`, `synthesis_agent.py:47-58` |
| Authorization blocks it | Refused with a station-scope-specific message, not folded into "not found" (`board_forbidden`, `case_reference_unsupported` etc. are distinct reasons) | `evidence/evaluator.py:212-219` |
| Translation backend fails | Answers in English, says so explicitly, never silently wrong-language | `translation_agent.py:22-58` |

The one gap worth naming explicitly: "I genuinely cannot parse this at all" is not a
distinct failure mode today — it is indistinguishable from "I searched and found
nothing," which is a different fact to tell an officer (one says "rephrase," the other
says "this isn't in the records"). This is another concrete argument for §6/§12: a
structured interpreter can emit "operation: unknown" as its own explicit state, which
the flat classifier's `UNKNOWN`→fallback path currently cannot represent honestly.

## 14. Demo / acceptance standard

Not keyword tests. Representative of what an officer would actually say, and what
"correct" means for each:

- *"does he have priors"* (mid-conversation, pronoun, no name restated) → resolves
  against `SessionFocus.active_person`, returns full case history. **Works today**
  (`intents.py:340`, verified in `CLAUDE.md` BUG-028's live check).
- *"only these?"* right after a crime-count answer → should read the stored total vs.
  shown count and either list more or say the count was exhaustive. **Works today**
  (2026-08-27, §8/§5.3) — verified against the real dataset: "How many theft cases
  in Bengaluru Urban?" (646 total, 5 shown) → "Only these?" correctly lists 5 more
  and states the 646 total; a second follow-up ("what about Mysuru?") correctly
  carries the crime type forward and re-scopes only the district.
- *"ಆ case ಗೆ related ಇನ್ನೊಂದು FIR ಇದ್ಯಾ?"* → **works today**, verified directly
  against the real model, §10.
- *"Usha Naika ಗೆ priors ಇದ್ಯಾ?"* → **does not work today** — confirmed live,
  post-deploy: translates to "Does Usha Naika have priorities?", intent falls to
  `UNKNOWN` (not `PERSON_HISTORY`), and the turn degrades to generic vector search
  instead of the authoritative record lookup. The consequence is worse than a bare
  miss: the person-name resolver still finds "Usha Naika" (19 records) and the
  fallback search surfaces five *different* similarly-named people (Usha Naika, Usha
  Naik, Usha Naek, Usha, Usha Udupa) blended into one answer at confidence 0.66 — an
  officer asking about one specific person gets a confusing multi-person answer
  instead of either the right answer or a clean refusal. This is the sharpest,
  most concrete open acceptance-test failure in the system right now, and the honest
  next place to look once §12's LLM path is reachable (a semantic interpreter reading
  the mistranslated English, or better, reading the Kannada directly, would both
  close it; a keyword patch would not be the right fix).
- *"ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ FIR 100222201202600022 ಬಗ್ಗೆ ಏನಿದೆ?"* → **works today**
  (2026-08-27, §10) — the district-gazetteer lookup-substitution fix means "ಮಂಡ್ಯ"
  never reaches NLLB at all, closing the refusal this bullet used to document.
- *"the second one"* after a network/associate listing → resolves against the
  previous turn's own numbered citation list. **Works today** (2026-08-27, §5.2),
  verified against the real dataset: "Who are the associates of Usha Naika?" → "Tell
  me about the second one" correctly opens that specific associate's case history.
- *"go deeper"* / *"what else"* after a subject-scoped answer → **works today**
  (2026-08-27, §5.2) when a subject is in focus and no bounded result set exists to
  disambiguate against; falls through honestly (not a guess) when neither applies.
- A refusal ("tell me about the flying saucer incident on the moon") → clean refusal,
  no padded citations. **Works today**, and was a real regression once
  (`orchestrator.py:1437-1449`'s comment documents the exact failure it fixed).

---

## 15. How to use this document going forward

- **When you fix a bug**: don't write a new failure-log entry format. If it changes
  what §4/§5 claims, edit those sections. Otherwise it doesn't belong here at all —
  `git log` is the record of individual fixes.
- **When you build the §12 migration**: this document's §6 table is the spec for what
  the structured interpreter's output shape should be. Update §5 point 1 and §12 once
  it's live and verified, don't create a new document announcing it.
- **When QuickML becomes reachable**: update §12 first — it currently gates whether
  *any* LLM-routed claim in this document can be called verified. Everything else that
  currently says "degrades to deterministic" should be re-tested against the real
  model before being called done.

## 16. Changelog (append here; do not create a new file)

- **2026-08-28 — the general N-step investigation planner, and a semantic fix
  for the correction gap named-and-deferred by the previous pass.** Full
  detail in §12 item 11. Summary: `SemanticRequest.plan_steps` (a validated,
  optional multi-op plan from the LLM path — chained subjects, bounded
  fan-out, citation-position references) and `orchestrator._run_plan`
  (executes it via the exact same `_run_specialists`/RBAC/CRAG path every
  single-op turn already uses); `state.last_request` + `apps/api/routers/
  chat.py`'s merge into persisted `result_context` so the NEXT turn's
  interpreter can read the PRIOR turn's structured request, not just its
  prose, making "actually Bengaluru, not Mysuru" the model's own semantic
  merge rather than a new regex; `date_before`/`date_after` constraints wired
  into `CRIME_SEARCH` (both `count_firs` and `search_firs`, kept consistent)
  so a temporal correction ("same thing but earlier") narrows the real query,
  not just the model's stated intent. 37 new tests across three files (5
  orchestrator-level plan-execution tests in `test_engine.py`, 12
  interpretation/validation tests in `test_semantic_interpreter.py`, and a
  new 20-scenario held-out GENERALIZATION evaluation,
  `test_generalization_evaluation.py`, one per category this pass's own
  brief specified) — 559 collected, zero regressions, the same two
  pre-existing `test_acceptance.py` failures as every prior pass. Deployed
  and live-verified; see §12 item 11 for what was deliberately left out
  (arbitrary graph-shaped plan dependencies, a single `date_range` constraint
  field, deterministic-path multi-step attempts).

- **2026-08-27 — final architectural push: QuickML root-caused precisely, and a
  genuine adversarial pass on the compositional layer.** Not a new architecture —
  the requested LLM-driven planning layer remains unbuildable-and-verifiable this
  pass (see the QuickML finding below); the real, live-verified work is a
  root-cause fix to the QuickML integration itself and five real conversational
  gaps found by substantially expanding `scripts/adversarial_eval.py` (15 → 40
  scenarios, all 15 dimension-tagged categories from the milestone's own
  acceptance list, latency measured per turn) and actually running it, not just
  writing it.
  - **QuickML — precisely diagnosed, not re-asserted.** See §12 for the full
    finding: the Python SDK (`zcatalyst-sdk` 1.4.0, read directly, not assumed
    from Node/Java-only docs) exposes exactly one QuickML method,
    `app.quick_ml().predict(endpoint_key, input_data)` — a generic ML-pipeline
    call, not the OpenAI-chat-shaped request every prior version of `llm.py`
    built by hand against a guessed URL. `llm.py` rewritten to call the real SDK
    method; `QUICKML_ENDPOINT` deleted (the SDK resolves routing itself). The
    `endpoint_key` remains obtainable only through the console (confirmed by
    directly probing plausible Admin API listing/creation paths, all 404) — a
    human action this environment cannot perform, independent of how correct the
    integration code is. Not faked: `available()`/`status()` still report
    degraded/not-configured honestly, and every test exercising this was
    rewritten against the real call shape (`_predict`), not left asserting a
    dead `_token()`/`urllib` path.
  - **Five real gaps found live, fixed, re-verified — each a structural
    widening of a mechanism already shipped, not a new phrase-specific
    pattern**, per this pass's own explicit instruction not to grow a regex
    library:
    1. **`NOT_INFERABLE` (the "never name a suspect" safety boundary) missed
       "Who do you think committed X?"** — literal two-word adjacency
       ("who committed") broke on "do you think" sitting between them. Widened
       to tolerate up to 4 filler words between "who" and the verb phrase.
       Found this was answering a guilt-attribution question with a real,
       confident record — the single most serious finding this pass.
    2. **"Show me related cases" / "Does he go by any other name?" scored
       `CRIME_SEARCH`/`UNKNOWN`** instead of `SIMILAR_CASES`/`ALIAS_CHECK` —
       missing synonyms ("related cases", "other name") in the existing keyword
       tuples, the same class of vocabulary gap "matching cases" already covers
       for `SIMILAR_CASES`.
    3. **"And Mysuru?" (a bare two-word constraint-change) fell to `UNKNOWN`**
       after a `HOTSPOT`/`FORECAST` turn — two compounding causes: the
       constraint-change regex only recognized "what about"/"and for"/"and in",
       never a bare "and X?"; and `HOTSPOT`/`FORECAST` never populated
       `result_context` at all, so even a matching regex had no prior operation
       to read. Fixed both — a new whole-query-anchored `_REPEAT_CUE_BARE_RE`
       (only fires when the bare form names a real extractable constraint, so
       "And then?" correctly falls through untouched), and `result_context`
       population added to both producers.
    4. **A named subject with no operation verb — "Tell me about Soom Nadkarni",
       "I meant Usha Naika specifically" — reached `UNKNOWN` and refused**, even
       with a specific, resolved person right there. The same defaulting
       principle already built for a bare ordinal/"other" reference
       (`_default_operation_for_subject`) extended to an explicitly named
       subject with nothing else asked.
    - **Found and corrected in the eval harness itself, not the product**: the
      first run of the expanded battery showed a case failing to "stay open"
      across turns — traced to `scripts/adversarial_eval.py`'s `run_local` never
      re-reading `SessionFocus` between turns the way `apps/api`'s real `/chat`
      endpoint does. Worth recording precisely because it demonstrates why this
      pass verified findings against the real wiring before treating a failure
      as a product bug — two of the seven initial "failures" were this one
      harness gap, not two separate product defects.
    - **After all five fixes: 32/32 non-Kannada scenarios pass locally against
      the real dataset** (up from 25/32 on the first honest run); Kannada
      scenarios verified live only, per §10's own note on local NLLB load cost.
  - **Three hero investigations identified from the existing dataset** (not
    regenerated — `scripts/find_hero_investigations.py`, ranked by prior-case
    count + real co-offending network size + real transaction count): Soom
    Nadkarni (person 877 — 196 priors, 63-person network, community 28, 6
    transactions, FIR 100050512202300008 — the same identity this document's
    BUG-026 finding already named for its romanisation drift), Chetan Hegde
    (person 1626 — 62 cases, 34 associates, community 21, FIR
    100121202202300022), Yogesh Nadgouda (person 99 — 72 cases, 6 associates, 4
    transactions, community 65, FIR 100050513202300003) — each rich enough to
    walk `PERSON_HISTORY → PERSON_NETWORK → FINANCIAL → RISK → TIMELINE` with
    real, non-trivial evidence at every step.
  - **Test suite**: 492 collected (5 new — the NOT_INFERABLE/vocabulary/bare-
    constraint-change/explicit-name-default regressions), 490 passed, 2
    pre-existing failures unrelated (unchanged from prior passes).
  - **Deployed and live-verified.** Baseline before any change: git `bbb8785`,
    deployment `52852000000366005`. Relayed (commit `610f0f7` → `.github/relay-
    upload.url` → `relay-deploy.yml` → local `appsail/upsert`) to deployment
    `52852000000361014` — confirmed changed, not merely "pipeline green."
    `scripts/verify_live_deployment.py` (the automated gate, not a manual
    curl): `/health` now honestly reports
    `"deterministic (QuickML not configured — no published endpoint key)"`
    instead of a stale "configured" string; the baseline defect reproduction
    passes; **all 36/36 adversarial scenarios pass live**, including all 4
    multilingual ones with the real deployed NLLB backend (not mocked).
    Latency, measured per turn, not asserted: p50 1.03s, p95 12.74s, max
    13.87s — the slow tail is entirely the Kannada turns' real translation
    cost (§10/§12 already named this as CPU-bound generation time, not a
    regression). **Console re-verified via real CDP** (apps/web untouched this
    pass, so this confirms the backend changes didn't break the UI): "Who are
    the associates of Usha Naika?" → "Does she go by any other name?" —
    correctly resolved the pronoun, routed through the newly-fixed `ALIAS_CHECK`
    vocabulary, and rendered a real linked-identity citation (confidence 1.00)
    with the network view and evidence rail synchronized, exactly as designed.
- **2026-08-27 — compositional semantic layer milestone.** The next slice of the §5.1
  migration, per its own "future phases" note: §5.2 (generic reference resolution),
  §5.3 (result-set awareness), a new bounded deterministic multi-step composition
  capability, and the §5.4/§10 half of code-switching that has a real deterministic
  fix. Brainstormed and spec'd first (architectural path,
  `docs/superpowers/specs/2026-08-27-compositional-semantic-layer-design.md`), then
  implemented directly per an explicit instruction not to produce a second design
  document.
  - **Baseline captured before any change** (spec §1): git `83b8695`; live AppSail
    deployment `52852000000360005` (Aug 27 16:30 IST, success); `/health` —
    `llm: quickml (glm-4.7-flash) — configured, not yet contacted`, `firs: 10000`,
    `graph: 16918n/87120e`, `vector_index: 13835 docs`; `QUICKML_ENDPOINT_KEY`
    confirmed absent from the live app's own `configuration` object (direct check,
    not carried forward). Live-reproduced the exact target defect: a `CRIME_SEARCH`
    turn followed by "Only these?" scored `Intent: UNKNOWN` and refused with
    `no_evidence` — §5.3 confirmed, not assumed.
  - **§5.2/§5.3 — reference + result-set layer.** `ConversationTurn.result_context`
    / `InvestigationState.result_context` (new, additive field) records
    `{operation, total_matched, shown, is_sample, shown_ids, constraints}` at the
    exact point `CRIME_SEARCH`/`PERSON_NETWORK`/`ALIAS_CHECK`/`SIMILAR_CASES` already
    sample. `semantic_interpreter.py` gained structural extractors — ordinal/
    positional (`_ordinal_index`), "the other one" (`_resolve_other_candidate`),
    context-disambiguated exhaustiveness vs. exploration (`_AMBIGUOUS_MORE_RE` vs.
    `_EXPLORATION_ONLY_RE`), bare "why" (`_BARE_WHY_RE`, reuses `EXPLAIN_REASONING`
    unchanged), a bare temporal relation (`_TEMPORAL_BARE_RE`, reuses `TIMELINE`
    unchanged), and a constraint-change repeat (`_REPEAT_CUE_RE`, carries a prior
    turn's crime type forward while overriding only the newly-named district). New
    `orchestrator._handle_more_results` (routes via a new `RESULT_SET_FOLLOWUP`
    operation) generalizes `_handle_case_locations`'s own pattern: an honest "that
    was everything" or a genuinely wider re-query, deduped against `shown_ids`, with
    `result_context` propagated forward so a SECOND follow-up in the same chain
    still has a real fact to read (found and fixed during manual verification — the
    first version left `result_context` empty after a follow-up turn). `_extract_constraints`
    (a stub since §5.1) now does real work; `orchestrator._crime_type_from_query`
    moved to `semantic_interpreter.crime_type_from_query` so both share one
    implementation.
  - **New: bounded deterministic multi-step composition**, not previously named as
    a bottleneck. `_COORDINATION_RE`/`_resolve_comparison_pair` detect a two-entity
    comparison ("either of those people", "both of them... as well") and populate
    `SemanticRequest.comparison_entities` (a field that existed, unused, since
    §5.1). `orchestrator._handle_comparison` sequences the *existing*
    single-subject retrieval path once per subject — unchanged RBAC, merged
    evidence scored by the same CRAG evaluator as one batch. Explicitly documented
    as NOT a general N-step planner: three-plus named entities falls through rather
    than guessing a pair, and the merge does not filter each subject's history down
    to the named constraint (e.g. "in Bengaluru") — the constraint shows up in each
    cited record's own content, same as an ordinary single-subject `PERSON_HISTORY`
    answer. Structured so the LLM path (§12) can extend or replace this exact seam
    without touching retrieval/RBAC/CRAG/synthesis.
  - **§10 — "Mandya→Mandi" fixed, correcting this document's own prior claim that no
    application-layer fix existed.** That claim (2026-08-27, earlier pass) was about
    protecting the *number* beside the district name; it never considered
    protecting the district name itself. New `data.districts.kannada_name_map` (a
    31-entry Kannada-script gazetteer added as a `kannada_names` column on
    `karnataka_districts.csv`, sourced from kn.wikipedia.org and cross-checked —
    flagged in code for a native-speaker QA pass before extending past what this
    fix was verified against) feeds a second `_protect_spans` pass in
    `translate.py`, active only for `src=="kn"`: a matched Kannada district span is
    replaced with a placeholder that restores to the *correct English name* — a
    lookup substitution, never a translation, so NLLB is never asked to translate
    the district name at all. Found and fixed a real ordering bug during
    implementation: identifier placeholders are themselves digit runs, and the
    identifier `_PROTECT` regex matches any 2+ digit run — protecting districts
    BEFORE identifiers let the identifier pass re-protect the district's own
    placeholder, which `_restore_spans` then failed to fully unwind (caught by this
    pass's own round-trip test, `test_district_and_identifier_protection_compose_without_collision`,
    failing first). Fixed by running identifiers first. Verified with a hostile
    stand-in backend that actively corrupts any Kannada district name it's shown —
    the correct English name comes back regardless (`data/tests/test_nlp.py`).
    "priorities" (the other §10 bug) stays open, correctly — blind keyword
    stemming was considered and rejected this pass (would spuriously score
    `PERSON_HISTORY` on "high priority case"); no deterministic fix exists that
    isn't the keyword-patch this document argues against.
  - **A second, reverse-direction district bug found live during this pass's own
    verification, and fixed the same way.** The kn→en fix above only protects a
    district name in the officer's *query*. The synthesized *answer* — always
    canonical English, e.g. "Mandya" — is separately translated en→kn for the
    reply, and NLLB rendered its own transliteration ("ಮಂಡಯಾ") instead of the
    canonical spelling ("ಮಂಡ್ಯ") an officer's own query would use. Facts were
    correct (73 real Mandya cases, the right FIR); only the district's spelling in
    the Kannada prose was off. New `data.districts.english_to_kannada_district`
    (the reverse map) feeds the same `_protect_spans` mechanism for `src=="en"`,
    word-boundary matched against canonical district names. Caught by actually
    running the adversarial battery live (§14/§16 below) rather than only unit
    tests — a reminder that "verified" for a translation fix means driving the
    real model in both directions it's actually used, not just the one the
    original bug report described.
  - **§4.2 (dual-text entity extraction) — largely subsumed by the §10 fix,
    not separately built.** The plan called for downstream code to also read the
    raw pre-translation Kannada text so closed-format entities (district/FIR/IPC/
    plate) wouldn't depend on translation quality. The §10 fix already achieves
    that guarantee at the translation layer itself (lookup-substitution, not
    probabilistic translation) for districts, and FIR/IPC/plate were already
    verbatim-protected before this pass. Building a second, downstream NER pass
    over `state.original_query_kn` (kept on `InvestigationState`, wired from
    `node_translate_in`, and available for a future consumer — e.g. a native-
    Kannada LLM path) to re-solve an already-solved problem would have been
    exactly the unnecessary-code this milestone's own discipline argues against.
    Not silently skipped: named here as a scope decision, not an oversight.
  - **Adversarial conversational evaluation** (spec §4-§5): new
    `scripts/adversarial_eval.py` (`--target local|live`), 15 genuinely unseen
    scenarios (paraphrases of every category the originating request listed:
    result-set follow-ups, positional/other reference, constraint-change, bare
    why/exploration/temporal, the two-entity comparison, colloquial phrasing,
    Kannada code-switching, an honest-refusal case, a nonexistent-person refusal).
    New `scripts/verify_live_deployment.py` makes "did the deploy actually change
    live behavior" a checkable, automated gate — re-runs the exact baseline defect
    reproduction plus the full adversarial battery against a live base URL and
    exits non-zero on any regression, rather than a manually-repeated curl.
  - **Test suite**: 488 collected (33 new — 20 in `test_reference_resolution.py`
    covering §5.2/§5.3/multi-step, 4 in `test_nlp.py` covering both directions of
    the district fix, plus a moved-function test update), 484 passed, 2 skipped
    (pre-existing), 2 pre-existing failures confirmed unrelated (identical on
    `main` before this pass — `apps/api/tests/test_acceptance.py`'s two acceptance
    tests, not investigated further as out of this milestone's scope).
  - **Deployed and live-verified, twice** (the second pass fixing a real defect the
    first pass's own live verification found). Commit `f21e24c` relayed
    (`get-signature` → `.github/relay-upload.url` → `relay-deploy.yml` → local
    `appsail/upsert`) to deployment `52852000000355006`. Running the new
    `scripts/verify_live_deployment.py` against it caught the reverse-direction
    district bug (§10 above) live — the automated adversarial battery is what
    found it, not a manual spot-check. Fixed (commit `86f1665`), relayed again to
    deployment `52852000000366005`. `scripts/verify_live_deployment.py` then
    passed clean: `/health` reports the expected fields; the exact baseline
    reproduction (`CRIME_SEARCH` → "Only these?") no longer scores `UNKNOWN` and
    no longer refuses; all 15/15 adversarial scenarios pass live, including both
    Kannada code-switching ones and the district-name fix. **Console
    re-verified via real CDP** (headless Chrome, Node 22's native WebSocket, the
    established technique — apps/web was NOT touched this pass, so this confirms
    the backend change didn't break the UI, not a new UI feature): signed in as
    `?as=SP`, drove the exact two-turn baseline sequence through the actual
    textarea/button, and read the rendered DOM — `msg-a` (not `msg-a refusal`),
    citation `[1]` reading "646 record(s) matched in total; 5 were shown before —
    here are 5 more" at "90% evidence strength." Screenshot evidence captured, not
    checked into the repo per this document's own no-new-artifact discipline for a
    routine verification pass.
- **2026-08-28 — semantic interpreter milestone.** §5.1 (Understanding bottleneck)
  now addressed: replaced 30-flat-intent classifier with structured `SemanticRequest`
  decomposition. New `rag_agent/semantic_interpreter.py` module (`interpret()` +
  `_interpret_deterministic()` + `_interpret_llm()`) produces
  `(operation, subject_type, subject_id, reference_kind, constraints,
  previous_result_context, comparison_entities, exploration_direction, ...)`. LLM path
  (QuickML) tried first, degrades to deterministic `intents.classify()` on any failure.
  Both paths produce identical output shape so `node_orchestrate` and downstream nodes
  require zero changes — boundary drawn at existing seam. The 30 intents remain valid
  values for `operation`, an implementation compatibility layer, not removed. Test
  coverage: 27 new adversarial conversation tests (paraphrases, pronouns,
  code-switching, reference resolution, edge cases, confidence scores, deterministic
  path verification). Full regression suite: 202 passed, 2 skipped. Deployed and
  live-verified against the real dataset. Deterministic path works as designed;
  LLM path waits for QuickML endpoint key (§12, BUG-022, unblocked but not yet
  configured). All four architectural bottlenecks named in §5 remain to be addressed —
  §5.2 (generic reference resolution), §5.3 (result-set awareness), §5.4 (code-switching
  entity extraction) — left to future phases once this semantic-interpreter foundation
  is solid.
- **2026-08-27 — code-switched translation, identifier protection.** Diagnosed the
  system against `CLAUDE.md` + `docs/*.md` + direct code reading (this document is the
  result); found `CLAUDE.md` itself stale (missing the cross-entity timeline feature,
  wrong test count — 433, not 403, per `pytest --collect-only -q`). Selected §10/§5.4
  as the one milestone for this pass: it is deterministic (verifiable without the
  blocked QuickML endpoint, §12), self-hosted, and directly named in the product
  mission's own test list. Implemented protected-span translation
  (`data/nlp/translate.py`) so FIR numbers/IPC codes/vehicle plates can never be
  altered by the MT model, guaranteed structurally, not by observed model behaviour.
  Found and documented, but deliberately did not patch, two real residual bugs
  ("priorities" desyncing from `\bpriors?\b`; "Mandya"→"Mandi" under a specific
  grammatical construction) — both ruled out as fixable by this technique through
  direct ablation against the real model, both left for the §12 migration or an
  IndicTrans2 backend swap respectively, not papered over with a keyword patch. 4 new
  tests (`data/tests/test_nlp.py`), full suite green (437 collected).
  **Deployed and live-verified** (`catalyst` CLI is available via its full npm path,
  not on the sandbox's default `PATH` — corrected after initially reporting no deploy
  access): commit `cd59797` pushed to `main`, relayed through `relay-deploy.yml`
  (deployment `52852000000345002`), confirmed live at `/health`. Three real `/chat`
  calls against production, not curl-to-`/health` alone: (1) the exact Mandya+FIR
  landmine query, which surfaced a **more severe live consequence than the local
  finding predicted** — "Mandi" isn't a real district, so NER reads it as an
  unresolved person and the whole turn refuses (`person_not_on_file`), even though the
  FIR number and intent both resolved correctly; (2) the same query with the district
  name removed, which answered correctly end to end (FIR 9992, confidence 0.97) —
  proving the deployed identifier-protection fix works in production, and isolating
  bug (1) as pre-existing and unrelated to this pass's change, not a regression; (3)
  the "priors"→"priorities" query, reproduced live identically to the local finding,
  with a previously-unobserved consequence: the fallback search blends five different
  similarly-named people into one answer instead of the authoritative single-person
  lookup. §10 and §14 above were updated with these live findings before this
  changelog entry was written.
