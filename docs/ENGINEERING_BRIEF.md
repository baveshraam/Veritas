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

Last verified against the repository at commit `fdadf30` plus the uncommitted change
described in §16. Test count, file:line references and the mixed-script translation
findings in §10 were confirmed directly against the running code on 2026-08-27, not
copied from an earlier document.

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

1. **Understanding is 30 flat, mutually-competing pattern matches, not a decomposition.**
   `intents.py` has 21 keyword-scored intents plus 8 regex "shape" pre-checks
   (`intents.py:15-297`) — confirmed by direct count, not estimated. There is no
   structured representation of *what the officer is asking for* independent of
   *which of 30 buckets it most resembles*. The module's own docstring claims "the LLM
   used only to break ties" (`intents.py:3-6`); no such call exists anywhere in the
   codebase — that line is aspirational, not descriptive, and should be read as wrong
   until §12's migration lands. New capabilities have been added by adding more
   patterns and then adding a second pattern to stop the first one from colliding with
   something else — `_BOARD_PIN_EVENT` exists solely to stop "add this event to the
   investigation board" from being swallowed by `BOARD_VIEW`'s own keywords
   (`intents.py:223-228`); `_TIMELINE_CONNECTION` exists solely to stop CAUSAL's bare
   "why" from stealing "why are these events connected" (`intents.py:209-221`). Every
   addition raises the chance of the next collision. This is not a defect in any one
   intent — each one, read alone, is well-reasoned and well-tested — it is a property
   of having 30 of them voting on the same string with no shared representation
   underneath.
2. **Reference resolution is general for one thing (a person pronoun) and hand-built
   for everything else.** `SessionFocus`/`resolve_focus()` genuinely generalizes across
   any intent that reads `active_person` (`intents.py:340-352`,
   `orchestrator.py:161-190`). But "this case," "why," "only these," "go back to the
   first case," "both of them" each required their own regex specifically because the
   generic path doesn't cover them (`intents.py:143-221`). A *new* kind of reference —
   "the other one," "same district as before," "compare these two" — gets nothing for
   free; it needs its own hand-built branch, discovered by someone actually typing it.
3. **No result-set awareness at the state level.** `CRIME_SEARCH` computes an exact
   count and separately samples up to 5 FIRs for citation
   (`orchestrator.py:468-495`) — genuinely correct, not padded — but nothing in
   `InvestigationState` records "N matched, M shown, this is a sample" as a queryable
   fact the *next* turn can read. "Only these?" / "are there more?" as a literal
   follow-up to a crime-count answer has no handler; it would fall through to whatever
   the 30-intent classifier happens to score it as. `CASE_LOCATIONS` is the one place
   this pattern exists correctly (it re-reads the previous turn's own cited FIR ids —
   `orchestrator.py:750-783`) and is the template for what a generalized version should
   look like, not yet generalized past geography.
4. **Kannada/English code-switching is handled by the translation layer as an
   afterthought, not a first-class case** — see §10. This is the most concrete,
   immediately-fixable instance of bottleneck #1: garbled understanding of code-switched
   input isn't really an "intent" problem, it's an "the classifier never saw clean
   English" problem one layer upstream.

None of these four are "add another regex" problems. Bottleneck #1 is the one the
target architecture in §12 is aimed at; #2 and #3 are consequences of the same root
cause (no shared structured representation of a turn); #4 is fixable independently and
is where this pass's own milestone (§16) was spent.

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

Where it's missing: no field on `InvestigationState`/`ConversationTurn` records "N
existed, M were shown, this was/wasn't exhaustive." A literal "only these?" or "are
there more?" has no handler and would be scored by the flat classifier like any other
string — most likely `UNKNOWN` or a wrong topic match, not a correct "yes, N-M more
exist, here are the next 5." Fixing this the *right* way is the same fix as §6's
`previous_result` concept: store `(total_matched, shown, is_sample)` on every turn that
produces a bounded result set, and give the semantic interpreter (or, today, a small
set of new regex shapes exactly like `CASE_LOCATIONS`'s own) a path that reads it. Not
built this pass — named here as the concrete next step after §12, not a vague "improve
UX" gap.

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

**What this pass built** (§16): protected-span translation. FIR numbers, IPC codes and
vehicle plates are now removed before the string reaches NLLB and spliced back verbatim
after (`data/nlp/translate.py:_protect_spans/_restore_spans`, wired into `translate()`
at `data/nlp/translate.py:118-127`). This makes identifier fidelity a **structural
guarantee** — provably true regardless of what the model does with the rest of the
sentence (tested with a hostile stand-in backend, `data/tests/test_nlp.py`) — rather
than a "the model happened to get it right in every test we ran" hope. It does **not**
fix the two bugs above: "priorities" isn't a numeric span, and "Mandya→Mandi" was
ablated and shown *not* to be caused by the unprotected number.

**Why those two are correctly left open rather than patched here**: fixing "priorities"
by adding it as a `PERSON_HISTORY` keyword alias would be exactly the reflexive
keyword-patch this brief argues against in §5 — it treats a translation-quality symptom
as an intent-layer problem. The principled fix is the §12 migration: a semantic
interpreter reading "Does Usha Naika have priorities?" (or the untranslated Kannada
directly, if QuickML is ever given native Kannada understanding) infers `PERSON_HISTORY`
from meaning, not from one exact English noun surviving machine translation intact.
"Mandya→Mandi" is a translation-model quality issue with no principled fix available at
the application layer at all (IndicTrans2, the licensed, higher-quality alternative
`translate.py` already supports as a preferred backend, is the real fix — see
`CLAUDE.md`'s translation module docstring).

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

## 12. Resource constraints — and the fact that governs everything above right now

**QuickML (the LLM) is currently unreachable in production.** `BUG-022`,
`packages/rag_agent/rag_agent/llm.py:44-55`: the endpoint key needed for QuickML's
invoke contract has never been obtainable through the Admin API this project
provisions with — confirmed as still true as of the last direct check
(`CLAUDE.md` v14). This is not a detail — it means **any architecture change that
routes understanding through the LLM produces zero live improvement today**, and
cannot be live-verified until that credential is obtained. This is why §16's milestone
was deliberately chosen to be deterministic and self-hosted (translation, not QuickML)
— it is the only category of conversational improvement currently checkable against
the real deployment rather than against a hope that a blocked service starts working.

The target architecture in §6/§12 is still correct to build toward: `generate_json()`
already exists with exactly the right contract (schema-constrained, degrades to `{}`
on any failure — `llm.py:200-229`), so the semantic-interpreter layer can be written
and merged now, running in fully-degraded (deterministic-only) mode until the day
someone obtains the endpoint key, at which point it activates with no further code
change — the same discipline `ENDPOINT_KEY` itself already documents
(`llm.py:53-54`). Building it now and verifying only the degraded path is honest work;
claiming the LLM path is "verified" without a reachable endpoint would not be.

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
  shown count and either list more or say the count was exhaustive. **Does not work
  today** — §8/§5.3.
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
- *"ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ FIR 100222201202600022 ಬಗ್ಗೆ ಏನಿದೆ?"* → **does not work
  today** — confirmed live, post-deploy: refuses outright (`person_not_on_file`) on
  the mistranslated "Mandi," despite the FIR number and intent both resolving
  correctly. See §10 for the full mechanism. This is arguably the more urgent of the
  two open bugs, precisely because it fails **completely** rather than just
  unhelpfully, and because the deployed fix in this pass makes it *more* visible, not
  less: the FIR number now reliably survives translation, so this failure mode is the
  next thing standing between an officer and a correct answer on exactly this class
  of query, not a second, independent problem behind it.
- *"go deeper"* after a NEXT_STEPS answer → not evaluated this pass; flag as unverified
  rather than assumed working.
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
