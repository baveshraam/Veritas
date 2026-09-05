# QA Functionality Matrix — independent inventory

**Purpose**: every user-facing or system capability the product actually contains,
derived from the code itself (routes, components, modules), not assumed from a defect
list.

**Method**: `apps/web/components/*.tsx` (UI), `apps/api/api/routers/*.py` (API routes),
`packages/rag_agent/rag_agent/intents.py`/`orchestrator.py` (conversation),
`packages/ml_models/ml_models/*` (analytics/ML), `data/data/nlp/*` (voice/Kannada),
`.github/workflows/`, `scripts/`, `catalyst.json` (deployment).

**Status legend**: `VERIFIED` (driven live/in-process, observed correct) / `PARTIAL`
(some but not all paths verified) / `BROKEN` (reproduced failing) / `UNKNOWN` (not
exercised) / `N/A` (not implemented). No row is blank, and "covered by tests" alone is
`PARTIAL`, never `VERIFIED` — only driving the real path earns that.

Full narrative for every pass (dates, screenshots, exact repro steps) is in
`docs/WORK_LOG.md`; this file keeps only the status and the one-line reason.

---

## 1. Console UI surfaces and controls

| ID | Surface | Source | What it does | Status | Notes |
|----|---------|--------|---------------|--------|----------|
| UI-01 | Login gate — roster load | `LoginGate.tsx` | `GET /auth/officers`, 6 roles | VERIFIED | Live, real roster |
| UI-02 | Login gate — sign in | `LoginGate.tsx` | `POST /auth/token`, stores JWT | VERIFIED | CDP: signed in as DSP |
| UI-03 | Login gate — `?as=ROLE` shortcut | `LoginGate.tsx` | Auto sign-in from URL param | VERIFIED | Used for every screenshot pass |
| UI-04 | Login gate — failure/slow state | `LoginGate.tsx` | 8s→"slow", real failure→fallback | VERIFIED | CDP: forced network failure, both states shown |
| UI-05 | Login gate — unverified entry clears token | `LoginGate.tsx` | `setToken(null)` before entry | VERIFIED | localStorage before/after confirmed |
| UI-06 | EN/KN toggle | `CommandBar.tsx` | Sets next-answer language | VERIFIED | Governs the *next answer*, not chrome i18n — by design |
| UI-07 | Voice on/off toggle | `CommandBar.tsx` | Sets `voiceOut` | UNKNOWN | No audio pipeline to observe; gated on NLP-06/07 |
| UI-08 | Export PDF button | `CommandBar.tsx` | Downloads session | VERIFIED both states | Disabled@0 turns, enabled+fires after one. Found+fixed: an HTML-fallback download (BUG-018) shipped silently — now flagged in-app |
| UI-09 | Switch (sign out) | `CommandBar.tsx` | Clears token, returns to gate | VERIFIED | `?as=` shortcut re-authenticating on remount is by design, not a bug |
| UI-10 | Health readout | `CommandBar.tsx` | FIR/node/index counts, status dot | VERIFIED | Matches `/health` |
| UI-11 | Send text query | `ChatPane.tsx` | Streams SSE | VERIFIED | Real query, real cited answer |
| UI-12 | Push-to-talk mic | `ChatPane.tsx` | Records, waveform | UNKNOWN | No audio input device in this environment |
| UI-13 | Citation chip click | `ChatPane.tsx` | Highlights evidence rail item | VERIFIED | CDP: evidence card highlights, thread line draws (UI-16) |
| UI-14 | Evidence rail item expand | `EvidenceRail.tsx` | Full content + source query | VERIFIED | Now also shows the retrieval SQL |
| UI-15 | "Ask about this case" → Copilot | `EvidenceRail.tsx` | Opens Copilot overlay | VERIFIED | Real timeline/leads/similar-cases/diary for a live FIR |
| UI-16 | Evidence thread line draw | `EvidenceThread.tsx` | SVG line, chip→card | VERIFIED | Real diagonal line renders, not just wired |
| UI-17 | Reasoning trace panel | `ReasoningTrace.tsx` | Plain-language trace, off by default | VERIFIED | 5 real steps with per-step durations |
| UI-18 | Case explorer search | `CaseExplorer.tsx` | Filters `/cases` by text | VERIFIED | Filtered count matched the crime-type chip count exactly |
| UI-19 | Crime-type filter chips | `CaseExplorer.tsx` | Toggles facet | VERIFIED | District count narrowed correctly on click |
| UI-20 | Case-status filter chips | `CaseExplorer.tsx` | Toggles facet | UNKNOWN | Visible with correct counts, not clicked |
| UI-21 | "Ask about this case" per card | `CaseExplorer.tsx` | Sends templated chat query | VERIFIED | Correct grounded, cited answer |
| UI-22 | "Copilot brief" per card | `CaseExplorer.tsx` | Opens Copilot overlay | VERIFIED | |
| UI-23 | Pane switcher | `ContextView.tsx` | Index vs. map/graph/sankey/trend | VERIFIED | Auto-switches on a hotspot query; manual toggle also confirmed |
| UI-24 | Map view | `viz/MapView.tsx` | Real OpenFreeMap (MapLibre "liberty") basemap + hotspot density + case points | VERIFIED | Replaced the self-drawn dark canvas — 5th documented Catalyst exception (§2). Overlays (points, density, legend, scale, attribution) unchanged. 4 queries checked (tight cluster, statewide fallback, distant district, no-evidence district). Still deferred: true district boundary polygons — no shapefile in this dataset |
| UI-25 | Network view | `viz/NetworkView.tsx` | Force-directed graph | VERIFIED, one gap fixed | A small/high-variance graph left 3 of 4 nodes unlabelled (40%-of-max-pagerank cutoff tuned for large graphs) — fixed with a node-count-aware threshold |
| UI-26 | Sankey view | `viz/SankeyView.tsx` | Money-flow diagram | FIXED | Above 25 nodes, only the top-20 by value keep a label; every node stays hoverable |
| UI-27 | Trend view | `viz/TrendView.tsx` | Forecast bands (ECharts) | VERIFIED | Proper bands, axis labels, real dates |
| UI-28 | Copilot overlay | `Copilot.tsx` | `/copilot/{id}`: timeline/leads/diary/similar | VERIFIED | All 4 sections real; similar-cases carry a structured explanation, not a bare score |
| UI-29 | Copilot "Copy" diary button | `Copilot.tsx` | Clipboard copy | VERIFIED | Real draft text landed in the captured clipboard call |
| UI-30 | Alert toasts | `AlertToasts.tsx` | SSE anomaly toasts (WS→SSE, v12) | VERIFIED backend, PARTIAL visual | `/alerts` streams real explanatory factors (district/metric/observed/expected/severity); reconnects on drop; not re-screenshotted in the toast-visible state |
| UI-31 | Investigation Board tab | `Board.tsx` (in `Copilot.tsx`) | Persistent per-case board | VERIFIED | Grouping by kind, inline forms, lead status buttons all confirmed via CDP+REST. Fixed a stale `turns.length`-keyed reload bug. Case-switch isolation confirmed |
| UI-32 | Pin to board (evidence rail) | `EvidenceRail.tsx` | Pins selected evidence card | VERIFIED | Pins the exact selected card (`active_evidence_id`), not just the first one |
| UI-33 | Open Case Board (rail + index) | `EvidenceRail.tsx`, `CaseExplorer.tsx` | Opens board tab | VERIFIED | Fixed: opening from the case index with no prior chat turn left "no case open" — now asks about the case first |
| UI-34 | Timeline tab (Copilot overlay) | `Copilot.tsx`, `viz/TimelineView.tsx` | `GET /timeline/case/{fir_id}` | VERIFIED | 23 events, correct order, RECORD/DERIVED badges; per-row pin works with no prior chat turn (reconstruction-fallback path) |
| UI-35 | Timeline view (chat context pane) | `ContextView.tsx`, `viz/TimelineView.tsx` | Renders a `TIMELINE`/`TIMELINE_CONNECTION` visualization | VERIFIED | Connecting-rail list, event-row selection syncs to evidence rail; 2-person connection banner + merged timeline confirmed |

## 2. API routes

| ID | Route | Source | Status | Notes |
|----|-------|--------|--------|----------|
| API-01 | `POST /auth/token` | `auth_routes.py` | VERIFIED | Every live session used it |
| API-02 | `GET /auth/officers` | `auth_routes.py` | VERIFIED | All 6 roles |
| API-03 | `POST /chat` (SSE) | `chat.py` | VERIFIED | Extensively, API and browser |
| API-04 | `GET /cases` | `records.py` | VERIFIED | All roles, scoping confirmed |
| API-05 | `GET /fir/{id}` | `records.py` | VERIFIED | Scoping + masking confirmed |
| API-06 | `GET /person/{id}` | `records.py` | VERIFIED | Masking confirmed |
| API-07 | `GET /copilot/{id}` | `copilot.py` | VERIFIED | Scoping + masking confirmed |
| API-08 | `POST /export/pdf` | `export.py` | PARTIAL, root-caused | Two SDK bugs found+fixed; still returns `text/html` — a remaining Catalyst-identity question (`INVALID_ID`) only testable via an interactive sign-in this tooling can't drive. Console never claims a PDF it didn't produce (BUG-018) |
| API-09 | `GET /alerts` (SSE, WS→SSE in v12) | `alerts.py` | VERIFIED | Unauth → 401; auth → real stream with genuine observed/expected/severity fields |
| API-10 | `POST /jobs/refresh` | `jobs.py` | VERIFIED, fixed | BUG-024: moved to a background thread |
| API-11 | `GET /jobs/audit-verify` | `jobs.py` | VERIFIED | `{"intact":true}` against the real live chain |
| API-12 | `GET /health` | `main.py` | VERIFIED | Extensively |
| API-13 | `GET /board/{fir_id}` | `board.py` | VERIFIED | RBAC (403/401), correct grouping, survives a new session |
| API-14 | `POST /board/{fir_id}/items` | `board.py` | VERIFIED | Real HTTP + via chat's BOARD_* intents; audit chain intact after |
| API-15 | `PATCH /board/{fir_id}/items/{item_id}` | `board.py` | VERIFIED | Lead transitions/edits; rejects bad status (400), cross-case id (404) |
| API-16 | `DELETE /board/{fir_id}/items/{item_id}` | `board.py` | VERIFIED | Rejects a lead (400, "dismiss instead"); real delete otherwise |
| API-17 | `GET /timeline/case/{fir_id}` | `timeline.py` | VERIFIED | Chronological, correct attribution, same RBAC as `/fir` |
| API-18 | `GET /timeline/person/{person_id}` | `timeline.py` | VERIFIED | Spans all cases, masks below DSP |

## 3. Conversational RAG — every intent

| ID | Intent | Status | Notes |
|----|--------|--------|----------|
| RAG-01 | `FIR_LOOKUP` (exact) | VERIFIED | |
| RAG-02 | `FIR_LOOKUP` (nonexistent) | VERIFIED | Refuses correctly |
| RAG-03 | `PERSON_HISTORY` ("does X have priors") | VERIFIED (content, not just routing) | Found live: every case's crime type/status/district/narrative rendered "not recorded" (BUG-028, P0) — a ZCQL 4-JOIN-cap collision in `person_record()`. Fixed |
| RAG-04 | `PERSON_NETWORK` | VERIFIED | |
| RAG-05 | `ALIAS_CHECK` | VERIFIED | |
| RAG-06 | `FINANCIAL` (empty trail) | VERIFIED | |
| RAG-07 | `FINANCIAL` (real trail) | VERIFIED | 12 citations, zero padding, vector search correctly skipped |
| RAG-08 | `HOTSPOT` (named district) | VERIFIED | |
| RAG-09 | `HOTSPOT` (no district, fallback) | VERIFIED | |
| RAG-10 | `FORECAST` | VERIFIED | |
| RAG-11 | `RISK` | PARTIAL | Answers correctly; score calibration unvalidated (BUG-014) |
| RAG-12 | `CAUSAL` | VERIFIED | Correctly declines (BUG-020 fix confirmed) |
| RAG-13 | `SIMILAR_CASES` | VERIFIED | |
| RAG-14 | `CRIME_SEARCH` | VERIFIED | Authoritative, vector search skipped (BUG-008 fixed) |
| RAG-15 | `CAPABILITY` | VERIFIED | |
| RAG-16 | `NOT_INFERABLE` | VERIFIED | |
| RAG-17 | Pronoun resolution ("does he/her have priors") | VERIFIED | Confirmed across two different pronouns in a 3-turn session, correctly resolving the carried-forward subject each time |
| RAG-18 | Multi-turn session continuity | VERIFIED | Same session that surfaced BUG-028 above — deep conversational testing is what finds content-level defects, not routing checks alone |
| RAG-19 | HippoRAG retrieval | PARTIAL | Trace shows it firing; not directly asserted on |
| RAG-20 | Think-on-Graph deep-dive | PARTIAL | Trace shows it firing on relational intents |
| RAG-21 | LLM-fluent synthesis | BROKEN | Confirmed NOT firing (extractive fallback used throughout) — BUG-021/022 |
| RAG-22 | Extractive (deterministic) synthesis | VERIFIED | Every live answer this session |
| RAG-23 | Citation numbering/grounding | VERIFIED | |
| RAG-24 | `CASE_CONTEXT` ("what happened?") | VERIFIED | Re-validates `active_fir` against station scope on every use, not trusted from when opened |
| RAG-25 | `CASE_PEOPLE` ("who's involved?") | VERIFIED | Auto-resolves `active_person` when exactly one; asks when several rather than guessing |
| RAG-26 | `SIMILAR_CASES`, case-scoped | VERIFIED | Reuses Copilot's structured similarity explanation |
| RAG-27 | `CASE_LOCATIONS` | VERIFIED | Tallies districts over the previous turn's cited FIRs, re-checked against policy scope |
| RAG-28 | `NEXT_STEPS` | VERIFIED | Reuses Copilot's lead-generation logic (direct co-accused only) |
| RAG-29 | `BRIEFING` | VERIFIED | Confirmed against a multi-accused case (4 accused), not just single-accused |
| RAG-30 | `EXPLAIN_REASONING` | VERIFIED | Re-describes the previous turn's own trace/citations; refuses honestly on a first turn |
| RAG-31 | `EVIDENCE_FOR` | VERIFIED | Same `nothing_prior` refusal on a first turn |
| RAG-32 | Ambiguous person names ask instead of guess | PARTIAL | Unit-tested (`test_an_ambiguous_name_asks_instead_of_guessing`); no live tied `record_count` found this pass |
| RAG-33 | Session-focus persistence across a full turn | VERIFIED, fixed | `active_fir` was persisted BEFORE retrieval, but `FIR_LOOKUP` resolves it DURING retrieval — "Open FIR X" then "What happened?" found no case ever opened. Fixed by persisting again after retrieval resolves |
| RAG-34 | Pronoun after a multi-person `CASE_PEOPLE` turn asks instead of refusing | VERIFIED, two bugs fixed | (1) A pronoun follow-up discarded the previous turn's named candidates instead of asking which one — now checks `_recent_person_candidates`. (2) `CASE_PEOPLE` with several accused failed to clear `active_person`, so a stale person from turns earlier silently answered instead — fixed. Reproduced a real 4-way tie live |
| RAG-35 | A decided refusal doesn't still run a generic search | VERIFIED, fixed | An `ambiguous_person`/`no_subject` refusal skipped every specialist branch but the untargeted vector-search fallback had no such guard and searched anyway, padding the evidence rail. `node_retrieve` now returns immediately when `refusal_reason` is already set |
| RAG-36 | A `no_evidence` refusal doesn't ship the rejected evidence | VERIFIED, fixed | Same failure class as RAG-35 through a third door: `node_synthesize` cleared `citations` but not `evidence_items` on this branch. Fixed by clearing both together |
| RAG-37 | `BOARD_VIEW` | VERIFIED, one bug fixed | A keyword collision ("case board") misrouted the feature's own example pin phrase here instead — fixed |
| RAG-38 | `BOARD_PIN_EVIDENCE` | VERIFIED | Resolves the selected card or falls back to the previous turn's top citation |
| RAG-39 | `BOARD_PIN_PERSON` | VERIFIED | Refuses locally with a helpful message when no person is in view |
| RAG-40 | `BOARD_ADD_LEAD` | VERIFIED | Captures trailing free text; always created `status: open` |
| RAG-41 | `BOARD_ADD_NOTE` | VERIFIED | Refuses locally on empty note text |
| RAG-42 | `BOARD_LEAD_STATUS` | VERIFIED | Resolves "that lead" to the most recent open one; dismiss never deletes |
| RAG-43 | `TIMELINE` | VERIFIED, one bug fixed | Matched by shape, not keyword score, so it doesn't collide with `CASE_CONTEXT`. Before/after filters against the previously-selected event's timestamp |
| RAG-44 | `TIMELINE_CONNECTION` | VERIFIED, one bug fixed | The generic pronoun-ambiguity refusal caught its own plural pronoun before the handler ran — fixed by exempting this intent |
| RAG-45 | Timeline event pinned to the board | VERIFIED, two bugs fixed | (1) Collided with `BOARD_VIEW`'s bare "investigation board" keyword. (2) A REST-fetched (non-chat) evidence target silently fell back to pinning the wrong item — reproduced via curl, then fixed |

**How RAG-24–33 were found**: reading the orchestrator showed the Investigation
Copilot's leads/similar-cases/briefing logic already existed but was reachable only
through `/copilot`, never `/chat`. RAG-33 (the session-focus persistence bug) undercut
the single most obvious follow-up in the system ("Open FIR X" → "What happened?"). Also
found in the same pass: `entities.py`'s PERSON-span extraction clipped a surname not in
the gazetteer sample off an adjacent known first name ("Usha Naika" → "Usha"), silently
resolving to a different person at full confidence — see `docs/PHASE1_FAILURE_LOG.md`.

## 4. Analytics / ML

| ID | Capability | Module | Status | Notes |
|----|-----------|--------|--------|----------|
| ML-01 | Fellegi-Sunter entity resolution | `entity_resolution/fellegi_sunter.py` | PARTIAL | Output (`vx_person`/`vx_accused_identity`) confirmed populated/consistent; F1=0.989 not re-measured against the live dataset (predates the answer-key persistence fix, §3 audit gap). Fixed the *recomputability* gap: `run.py` now persists `IDENTITY_ANSWER_KEY`, and `data/generator/score_identity.py` recomputes P/R/F1 out-of-band, matching the AML-labels precedent |
| ML-02 | KDE + DBSCAN hotspots | `spatial/hotspots.py` | VERIFIED (API); UNKNOWN (map render) | Real clusters + incident points for a named district |
| ML-03 | Prophet + MinT forecast | `forecasting/forecast.py` | VERIFIED (API); UNKNOWN (chart render) | 30-day series, plausible values |
| ML-04 | XGBoost + SHAP risk scoring | `risk/scoring.py` | PARTIAL, honestly | Live returns 1.00 for a heavy-prior person, correctly labelled "NOT calibrated" — the live dataset's calibration split lacks class balance for isotonic regression; the fallback fires as designed (BUG-014) |
| ML-05 | LightGBM recidivism | `risk/scoring.py` | PARTIAL | Fires alongside risk; value not checked against an answer key |
| ML-06 | Isolation Forest district-spike alerts | `risk/anomalies.py` | VERIFIED | 4 real alerts in one 8s window, e.g. `KA05 monthly_fir_count 105.0 vs expected 73.5` |
| ML-07 | Louvain community detection | `data/gds.py` | VERIFIED | Plural communities confirmed |
| ML-08 | PageRank / betweenness | `data/gds.py` | VERIFIED | Field renamed `risk_score`→`pagerank` end to end since it was never a risk score |
| ML-09 | Rule-based AML structuring detector | `financial/structuring.py` | VERIFIED reachable, PARTIAL positive case | Root cause: was checking a transfer's incidental `from_account` (nobody's own), never the person's own account — fixed via `graph_agent.owned_accounts()`. No live positive example found (needs the original seeding run's `aml_labels.json`, unavailable) |
| ML-10 | GNN suspicious-subgraph AML | `financial/gnn.py` | PARTIAL | Same reachability fix applies; `torch` still absent from the deployed image (bundle-sandbox size, §CLAUDE.md v7). Degrades to `GNNUnavailable` gracefully — a hand-rolled numpy reimplementation was deliberately not attempted (a subtly-wrong gradient computation is worse than honest unavailability) |
| ML-11 | DoWhy causal effects | `causal/effects.py` | BROKEN by design | Correctly declines with a precise reason (`dowhy` not in the deployed image) |
| ML-12 | Aequitas fairness audit | `fairness/audit.py` | N/A (live product) | Explicitly out-of-band: a standalone CLI script (`fairness_run_audit.py`), never wired to a route — by design, not a gap |
| ML-13 | Isolation-Forest-driven `/alerts` feed | `serving.py` | VERIFIED | See ML-06/API-09 |

## 5. NLP / Voice / Kannada

| ID | Capability | Module | Status | Notes |
|----|-----------|--------|--------|----------|
| NLP-01 | Kannada script detection | `translate.py` | VERIFIED | |
| NLP-02 | Kannada → English | `translate.py` | VERIFIED | |
| NLP-03 | English → Kannada | `translate.py` | VERIFIED | |
| NLP-04 | Full Kannada pipeline (translate→intent→retrieve→answer→translate back) | orchestrator + `translate.py` | VERIFIED | |
| NLP-05 | Kannada latency | — | VERIFIED (measurement) | 13.3–13.4s vs 0.4–0.6s English — the latency itself is BUG-016, open |
| NLP-06 | Speech-to-text (faster-whisper) | `speech.py` | UNKNOWN | No audio input device in this environment |
| NLP-07 | Text-to-speech | `speech.py` | UNKNOWN | Same constraint |
| NLP-08 | Translation-unavailable fallback | `translate.py` | UNKNOWN | Not triggerable without disabling the model |
| NLP-09 | Named-entity extraction | `entities.py` | VERIFIED | Every person/district resolution this session depended on it |
| NLP-10 | Transliteration variants | `translit.py` | PARTIAL | Indirect coverage via `test_entity_resolution.py` and live alias checks |
| NLP-11 | Model weight streaming from File Store at cold start | `model_fetch.py` | FALSE CLAIM (BUG-017) | `VERITAS_MODELS_FOLDER_ID` was unset live, yet Kannada worked in ~2s — weights were not being fetched the way the changelog claimed |

## 6. RBAC / profile capability matrix

Six roles × operations, derived from `packages/policy/policy/rules.py` and live-tested.

| Role | Rank | `/cases` scope | Cross-station `/fir`, `/copilot` | Identity masking | Traversal depth | Live-tested |
|------|------|-----------------|------------------------------|-------------------|-------------------|----------------------------|
| IO | 1 | own station only | 403 / 403 | masked | 2 hops | Yes |
| SHO | 2 | all stations | 200 / 200 | masked | 2 hops | Yes |
| DSP | 3 | all stations | 200 / 200 | unmasked | 4 hops | Yes |
| SP | 4 | all stations | 200 / 200 | unmasked | 4 hops | Prior pass only |
| SCRB_Analyst | 4 | all stations | 200 / 200 | unmasked | 4 hops | Prior pass only |
| IG | 5 | all stations | 200 / 200 | unmasked | 4 hops | Yes — primary test role |

Not yet exercised for any role: analytics/hotspot endpoints apply no rank restriction —
worth confirming that's intentional.

## 7. Deployment chain

| ID | Stage | Status | Notes |
|----|-------|----------|----------|
| DEP-01 | Local → git commit | VERIFIED | |
| DEP-02 | git push → GitHub | VERIFIED | |
| DEP-03 | GitHub Actions build (`Dockerfile.overlay`) | VERIFIED | ~2min, green |
| DEP-04 | Image upload to Catalyst signed URL | VERIFIED | |
| DEP-05 | `appsail/upsert` finalization | VERIFIED | Confirmed via subsequent `GET /appsail` polling, not just the 200 |
| DEP-06 | AppSail cold start | VERIFIED | ~22.7–22.9s measured |
| DEP-07 | AppSail — Data Store binding | VERIFIED | `/health` reports real row counts |
| DEP-08 | AppSail — File Store (model weights) | CONTRADICTS DOCS | See NLP-11 / BUG-017 |
| DEP-09 | AppSail — QuickML | BROKEN, diagnosed | BUG-021 (fixed) / BUG-022 (open at the time) |
| DEP-10 | AppSail — Cache | VERIFIED | `/health` reports `cache=catalyst` |
| DEP-11 | Web Client Hosting deploy | VERIFIED | Artifact-verified via CDP, not just exit code |
| DEP-12 | Cron — `veritas_refresh` (6h) | VERIFIED, unattended fire confirmed | Listed the live job directly: `success_count: 1→3, failure_count: 0` after the hostname/token fix (BUG-025) |
| DEP-13 | Cron — `veritas_audit_verify` (12h) | VERIFIED, unattended fire confirmed | Same discipline: `success_count: 1, failure_count: 0` after the background-thread fix (BUG-027) |
| DEP-14 | Audit hash chain integrity | VERIFIED | `intact: true` against the real live log |
| DEP-15 | `python -m data.provision` on a live, populated Data Store | VERIFIED | `vx_case_board_item` created idempotently alongside the 37 already-live tables |

## 8. Data integrity

| ID | Check | Status |
|----|-------|--------|
| DATA-01 | No duplicate FIRs / accused / accounts / transactions / graph edges | VERIFIED (23 checks, `test_integrity.py`) |
| DATA-02 | Foreign-key consistency across ER + `vx_` tables | VERIFIED |
| DATA-03 | District/station identifier consistency | VERIFIED |
| DATA-04 | Generator determinism | VERIFIED |
| DATA-05 | Live `/cases` payload duplication | VERIFIED clean (0 dup `fir_id`) |
| DATA-06 | `BriefFacts` narrative repetitiveness → false similarity risk | FIXED, live-verified | `_MO_VARIANTS` now covers all 20 crime types (3 variants each) plus slot-filling; live backfill recomputed narratives without touching case/accused/identity/financial/graph rows. `_similar_cases` now returns a structured explanation instead of a bare score (BUG-023) |

---

## Open items

- **BUG-026** (P2, UX/trust) — Copilot leads rendered a person's canonical name
  (`vx_person.CanonicalName`) while the same case's own accused list shows the as-filed
  name (`Accused.AccusedName`), with nothing linking them — entity resolution working
  *correctly* (§3's documented romanisation drift), just not cross-referenced on this one
  surface. **Fixed and live-verified**: `_lead_name()` now renders `"Canonical (filed as
  \"AsFiled\" on this FIR)"` whenever they differ, and the masked placeholder for a
  masked role. 2 new unit tests.
- Full click-through of every UI control — closed except UI-07 (voice, hardware-gated)
  and UI-20 (case-status chips, visible but not clicked).
- Voice pipeline end to end — no audio input device in this environment (hard
  environmental constraint, not a skipped step).
- A real populated `FINANCIAL` trail (RAG-07) — verified once via a found positive
  example; not exhaustively re-tested.
- AML detectors against a real injected pattern (ML-09/10) — reachability and the
  negative-case path are verified; the positive-detection path needs the original
  generation run's `aml_labels.json`, which doesn't confidently map onto the live
  dataset's transaction numbering.
- Ambiguous-name clarification (RAG-32) against a real tied *name search* (as opposed to
  the pronoun-side variant, RAG-34, which does have a live 4-way-tie proof).
- Whether Aequitas (ML-12) is reachable from the live product — confirmed out-of-band by
  design, not a gap.

### Pass-by-pass defect log (condensed; full detail in `docs/WORK_LOG.md`)

- **Golden-conversation pass**: drove the full 19-turn scripted investigation through
  the live console via CDP. Found and fixed 4 bugs: a stale `active_person` surviving a
  case switch, `EXPLAIN_REASONING` missing a verb phrasing, `NEXT_STEPS` missing a
  passive-voice keyword, and a decided refusal still running a generic search (RAG-35).
- **Finalization pass** (curl/SSE adversarial stress, deliberately different phrasing
  from the golden script): found and fixed 3 bugs — a Kannada tokenizer crash now
  degrades to English with a note; a bare "this"/"that" was misread as an unresolved
  person pronoun even as an ordinary determiner; "go back to the first case" (no history
  stack) fell to an unrelated semantic search instead of refusing (new
  `CASE_REFERENCE_UNSUPPORTED`). 369 tests.
- **Final live judge pass** (real CDP, ~25-turn investigation, judged as a competition
  judge would): found and fixed 5 bugs — a `no_evidence` refusal shipping rejected
  evidence (RAG-36, P0); `CASE_REFERENCE_UNSUPPORTED` missing non-ordinal phrasing;
  associate evidence text saying "gang" (contradicts §4's rule); a namesake collision
  rendering as an apparent duplicate; the network-label cutoff (UI-25). 374 tests. Also
  closed the toast/evidence-rail overlap structurally — `AlertToasts` moved into the
  rail's own flexbox column so a toast can only push the list down, never cover it.
- **Investigation-board pass**: built the board feature (§1 UI-31–33, §2 API-13–16, §3
  RAG-37–42). Found and fixed 2 bugs on live-judging the deployed console: a keyword
  collision misrouting the feature's own example pin phrase, and a citation-count-based
  refusal inference painting a successful board confirmation red. RBAC/audit/case
  isolation re-verified specifically for the new endpoints. 403 tests.
- **Cross-entity timeline pass**: built the timeline feature (§1 UI-34–35, §2 API-17–18,
  §3 RAG-43–45). Found and fixed 3 bugs before deploy: a "investigation board" keyword
  collision (same class as the board pass's own fix), a silent wrong-item pin fallback
  exposed by the REST-fetched Timeline tab, and a pronoun-ambiguity collision on
  `TIMELINE_CONNECTION`'s own "both of them". 433 tests.
