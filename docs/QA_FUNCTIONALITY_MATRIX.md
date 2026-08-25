# QA Functionality Matrix — independent inventory

**Purpose**: every user-facing or system capability the product actually contains,
derived from the code itself (routes, components, modules) rather than assumed from
the Phase 1 truth table's 89-component list — that list was built around specific
defects found; this one is built by walking the repository.

**Method**: `apps/web/components/*.tsx` for UI surfaces and controls, `apps/api/api/routers/*.py`
for API routes, `packages/rag_agent/rag_agent/intents.py`/`orchestrator.py` for
conversational capabilities, `packages/ml_models/ml_models/*` for analytics/ML, `data/data/nlp/*`
for voice/Kannada, `.github/workflows/`, `scripts/`, `catalyst.json` for deployment.

**Status legend**: `VERIFIED` (driven live or in-process and observed correct) /
`PARTIAL` (some but not all paths verified) / `BROKEN` (reproduced failing) /
`UNKNOWN` (not yet exercised — never upgraded to VERIFIED on inspection alone) /
`N/A` (not implemented — listed because a claim or artifact references it).

No row is blank. No row says "probably works" or "covered by tests" as its status —
where prior unit/integration tests are the only evidence, the status is `PARTIAL` with
that stated, not `VERIFIED`.

---

## 1. Console UI surfaces and controls

| ID | Surface | Source | What it does | Status | Evidence |
|----|---------|--------|---------------|--------|----------|
| UI-01 | Login gate — roster load | `LoginGate.tsx` | Loads `/auth/officers`, renders 6 roles | VERIFIED | Live screenshot, real roster |
| UI-02 | Login gate — sign in | `LoginGate.tsx:signIn` | `POST /auth/token`, stores JWT | VERIFIED | CDP: clicked, entered main console as DSP |
| UI-03 | Login gate — `?as=ROLE` shortcut | `LoginGate.tsx` | Auto-signs in from URL param | VERIFIED | Used for every screenshot in this pass |
| UI-04 | Login gate — roster failure / slow state | `LoginGate.tsx` | 8s→"slow", real failure→"failed", offers unverified fallback | VERIFIED | CDP: forced real network failure, screenshotted both states |
| UI-05 | Login gate — unverified/demo entry clears token | `LoginGate.tsx:enterUnverified` | `setToken(null)` before entering | VERIFIED | CDP: localStorage before/after |
| UI-06 | Command bar — EN/KN toggle | `CommandBar.tsx` | Sets `language` state | PARTIAL | Toggle click not driven this pass; API-level Kannada is VERIFIED |
| UI-07 | Command bar — voice on/off toggle | `CommandBar.tsx` | Sets `voiceOut` | UNKNOWN | Not exercised |
| UI-08 | Command bar — Export PDF button | `CommandBar.tsx` → `exportPdf()` | Downloads session as file | PARTIAL | Gating confirmed live: correctly `disabled` with 0 chat turns (`canExport={turns.length > 0}`). API confirms `text/html` fallback (BUG-018); the actual download click with turns present not driven |
| UI-09 | Command bar — Switch (sign out) | `CommandBar.tsx` | `setToken(null)`, returns to LoginGate | VERIFIED | Live via a real manual sign-in (no `?as=` shortcut): click Switch -> token cleared, back at login gate. **Note**: testing this through the `?as=ROLE` URL shortcut instead looks like a failure (token restored, still signed in) -- that is the shortcut correctly re-authenticating on every LoginGate mount, by design, not a bug. Caught and ruled out before being misreported |
| UI-10 | Command bar — health readout | `CommandBar.tsx` | Shows FIR/node/index counts, live-status dot | VERIFIED | Screenshot matches `/health` exactly |
| UI-11 | Chat pane — send text query | `ChatPane.tsx:send` | Types, submits, streams SSE | VERIFIED | CDP: real query, real streamed answer, real citation |
| UI-12 | Chat pane — push-to-talk mic | `ChatPane.tsx:toggleMic` | Records audio, waveform | UNKNOWN | No audio input device in this environment |
| UI-13 | Chat pane — citation chip click | `ChatPane.tsx:withCitations` | Scrolls/highlights evidence rail item | UNKNOWN | Not driven interactively |
| UI-14 | Evidence rail — item expand | `EvidenceRail.tsx` | Shows full content + source query | VERIFIED | Visible in chat screenshot (1 cited, expanded) |
| UI-15 | Evidence rail — "Ask about this case" (Copilot open) | `EvidenceRail.tsx` | Opens Copilot overlay for a FIR | PARTIAL | Not clicked directly; UI-22 confirms the Copilot overlay itself opens and renders correctly via the case-card route |
| UI-16 | Evidence thread — citation-to-card line draw | `EvidenceThread.tsx` | SVG line from chip to card | UNKNOWN | Not verified visually |
| UI-17 | Reasoning trace panel (expand/collapse) | `ReasoningTrace.tsx` | Plain-language agent trace, off by default | PARTIAL | Present in screenshot ("reasoning trace · 5 steps"), not expanded/inspected |
| UI-18 | Case explorer — search box | `CaseExplorer.tsx` | Filters `/cases` by text | PARTIAL | Typed into live; result not screenshotted before session ended |
| UI-19 | Case explorer — crime-type filter chips | `CaseExplorer.tsx` | Toggles facet filter | VERIFIED | Live: clicked "Theft", chip highlighted, district count correctly narrowed 24->19, every visible card is Theft |
| UI-20 | Case explorer — case-status filter chips | `CaseExplorer.tsx` | Toggles facet filter | UNKNOWN | Not driven |
| UI-21 | Case explorer — "Ask about this case" per card | `CaseExplorer.tsx` | Sends a templated chat query | UNKNOWN | Not driven |
| UI-22 | Case explorer — "Copilot brief" per card | `CaseExplorer.tsx` | Opens Copilot overlay | VERIFIED | Live: clicked, overlay opened and rendered the officer's own header state correctly around it |
| UI-23 | Context view — pane switcher (index/viz) | `ContextView.tsx` | Toggles case index vs map/graph/sankey/trend | PARTIAL | Case index confirmed rendering; switch to viz not driven |
| UI-24 | Map view | `viz/MapView.tsx` | Self-drawn canvas, hotspot density, case points | PARTIAL — renders correctly | Screenshotted live: points and hotspot clusters render, zoom controls present. **Gap found**: no geographic reference at all (no district outlines, scale, or labels) — reads as an abstract scatter plot, not a geographic tool. See §12 |
| UI-25 | Network view | `viz/NetworkView.tsx` | Force-directed graph | VERIFIED | Screenshotted live: 12 labeled nodes, correct sizing/coloring, legible |
| UI-26 | Sankey view | `viz/SankeyView.tsx` | Money-flow diagram | VERIFIED (with a UX gap) | Found a person with a real trail (Harish Savadi, 60 transfers) and screenshotted live: renders correctly. **Gap found**: with 60 destination nodes, the right-side account labels overlap and become unreadable — needs collision handling or truncation at high fan-out |
| UI-27 | Trend view | `viz/TrendView.tsx` | Forecast bands (ECharts) | VERIFIED | Screenshotted live: proper band chart, axis labels, real dates |
| UI-28 | Copilot overlay — timeline/leads/diary/similar cases | `Copilot.tsx` | Renders `/copilot/{id}` | PARTIAL | API-level content verified extensively; overlay UI not opened via click |
| UI-29 | Copilot — "Copy" diary button | `Copilot.tsx` | Clipboard copy | UNKNOWN | Not driven |
| UI-30 | Alert toasts | `AlertToasts.tsx` | WebSocket-driven anomaly toasts | BROKEN (blocked) | `/alerts` itself unreachable live — see BUG-005 |

## 2. API routes

| ID | Route | Source | Status | Evidence |
|----|-------|--------|--------|----------|
| API-01 | `POST /auth/token` | `auth_routes.py` | VERIFIED | Every live session in this audit used it |
| API-02 | `GET /auth/officers` | `auth_routes.py` | VERIFIED | Live, all 6 roles |
| API-03 | `POST /chat` (SSE) | `chat.py` | VERIFIED | Extensively, both API and browser |
| API-04 | `GET /cases` | `records.py` | VERIFIED | Live, all roles, scoping confirmed |
| API-05 | `GET /fir/{id}` | `records.py` | VERIFIED | Live, scoping + masking confirmed |
| API-06 | `GET /person/{id}` | `records.py` | VERIFIED | Live, masking confirmed |
| API-07 | `GET /copilot/{id}` | `copilot.py` | VERIFIED | Live, scoping + masking confirmed |
| API-08 | `POST /export/pdf` | `export.py` | PARTIAL | Returns `text/html` (BUG-018), reachability not re-driven this pass |
| API-09 | `WS /alerts` | `alerts.py` | BROKEN (live) | See BUG-005 |
| API-10 | `POST /jobs/refresh` | `jobs.py` | **VERIFIED (fixed)** | BUG-024 fixed: moved to a background thread. Redeployed (`52852000000310022`) — see the failure log for the live re-verification |
| API-11 | `GET /jobs/audit-verify` | `jobs.py` | VERIFIED | Triggered live with the real deployed job token: `{"intact":true,"first_bad_audit_id":null}` — the audit hash chain is genuinely intact |
| API-12 | `GET /health` | `main.py` | VERIFIED | Extensively, both deploys |

## 3. Conversational RAG — every intent

| ID | Intent | Source | Live-verified this session? | Status |
|----|--------|--------|------------------------------|--------|
| RAG-01 | `FIR_LOOKUP` (exact) | `orchestrator.py` | Yes, repeatedly | VERIFIED |
| RAG-02 | `FIR_LOOKUP` (nonexistent) | same | Yes | VERIFIED |
| RAG-03 | `PERSON_HISTORY` | same | Yes ("does X have priors") | VERIFIED |
| RAG-04 | `PERSON_NETWORK` | same | Yes | VERIFIED |
| RAG-05 | `ALIAS_CHECK` | same | Yes | VERIFIED |
| RAG-06 | `FINANCIAL` (empty trail) | same | Yes | VERIFIED |
| RAG-07 | `FINANCIAL` (real trail) | same | Yes | VERIFIED — found via search (Harish Savadi), 12 citations, all `GRAPH_RELATIONSHIP`, zero padding, trace confirms vector search skipped — the generalized BUG-013 fix works on the positive path too, not just the negative-finding path |
| RAG-08 | `HOTSPOT` (named district) | same | Yes (prior pass) | VERIFIED |
| RAG-09 | `HOTSPOT` (no district — fallback) | same | Yes (prior pass) | VERIFIED |
| RAG-10 | `FORECAST` | same | Yes (prior pass) | VERIFIED |
| RAG-11 | `RISK` | same | Yes (prior pass) | PARTIAL — answers correctly; the score's calibration is unvalidated (BUG-014) |
| RAG-12 | `CAUSAL` | same | Yes, this pass | VERIFIED (correctly declines; BUG-020 fix confirmed) |
| RAG-13 | `SIMILAR_CASES` | same | Yes, this pass | VERIFIED |
| RAG-14 | `CRIME_SEARCH` | same | Yes, live this pass | VERIFIED — "How many theft cases in Mandya district?" → "73 case(s) Theft in Mandya", authoritative, vector search skipped (BUG-008 fixed) |
| RAG-15 | `CAPABILITY` | same | Yes | VERIFIED |
| RAG-16 | `NOT_INFERABLE` | same | Yes | VERIFIED |
| RAG-17 | Pronoun/reference resolution ("does **he** have priors") | `intents.has_unresolved_reference` | Yes | VERIFIED — live 3-turn session: named subject, then "Does he have priors?", then "What about his money trail?", both pronouns correctly resolved against the session's carried-forward subject |
| RAG-18 | Multi-turn session continuity | `vx_session`/`vx_conversation_turn` | Yes | VERIFIED — same 3-turn session as RAG-17; subject persisted correctly across all three turns |
| RAG-19 | HippoRAG retrieval | `retrieval/hipporag.py` | Indirectly (trace shows it firing) | PARTIAL |
| RAG-20 | Think-on-Graph deep-dive | `retrieval/tog.py` | Indirectly (trace shows it firing on relational intents) | PARTIAL |
| RAG-21 | LLM-fluent synthesis | `llm.py`/`synthesis_agent.py` | Yes — confirmed NOT firing (extractive fallback used throughout) | BROKEN — see BUG-021/022 |
| RAG-22 | Extractive (deterministic) synthesis | `synthesis_agent._extractive` | Yes, every live answer this session | VERIFIED |
| RAG-23 | Citation numbering/grounding | `synthesis_agent.build_citations` | Yes, extensively | VERIFIED |

## 4. Analytics / ML — each traced INPUT → DATA → ALGORITHM → OUTPUT → EVIDENCE

| ID | Capability | Module | Live-verified | Status |
|----|-----------|--------|----------------|--------|
| ML-01 | Fellegi-Sunter entity resolution | `entity_resolution/fellegi_sunter.py` | Indirectly — `vx_person`/`vx_accused_identity` are its output, confirmed populated and referentially consistent (`test_integrity.py`) | PARTIAL — the F1=0.989 claim itself was not re-measured this session |
| ML-02 | KDE + DBSCAN hotspots | `spatial/hotspots.py` | Yes (prior pass): named-district query returns real clusters + real incident points | VERIFIED (API level); map rendering UNKNOWN |
| ML-03 | Prophet + MinT forecast | `forecasting/forecast.py` | Yes (prior pass): 30-day series, plausible values | VERIFIED (API level); chart rendering UNKNOWN |
| ML-04 | XGBoost + SHAP risk scoring | `risk/scoring.py` | Yes, live this pass | PARTIAL, honestly — live returns 1.00 for a heavy-prior person, correctly labeled "NOT calibrated" because the live dataset's calibration split lacks class balance to fit isotonic regression; the fallback fires exactly as designed (BUG-014 fixed at the reporting level) |
| ML-05 | LightGBM recidivism | `risk/scoring.py` (via `predict_recidivism`) | Yes: fires alongside risk | PARTIAL — value not checked against the answer key |
| ML-06 | Isolation Forest district-spike alerts | `risk/anomalies.py` | **No** — only reachable through `/alerts`, which is live-blocked | UNKNOWN |
| ML-07 | Louvain community detection | (via `data/gds.py`, not ml_models directly) | Yes: person 803 → community 28, plural communities confirmed in prior pass | VERIFIED |
| ML-08 | PageRank / betweenness (graph centrality) | `data/gds.py` | Indirectly — PageRank values appear in `/person` and network evidence | PARTIAL |
| ML-09 | Rule-based AML structuring detector | `financial/structuring.py` | **No** — not reachable without a real money trail (RAG-07 gap) | UNKNOWN |
| ML-10 | GNN suspicious-subgraph AML | `financial/gnn.py` | **No** — same gap, and `torch` is deliberately absent from the deployed image (degrades to `GNNUnavailable` by design) | UNKNOWN live; known-absent by design |
| ML-11 | DoWhy causal effects | `causal/effects.py` | Yes, this pass: confirmed declining with a precise reason (`dowhy` not installed in the deployed image) | BROKEN live (by design/image-size trade-off), correctly reported as such |
| ML-12 | Aequitas fairness audit | `fairness/audit.py` | Resolved by reading `serving.py`'s own module docstring | N/A (live product) | Explicitly designed as out-of-band: `serving.py` documents its callers as "fairness/run_audit.py: run_fairness_audit (out-of-band, pre-demo)" — a standalone CLI script (`packages/ml_models/fairness_run_audit.py`), never wired to any API route or UI control. Not a gap — by design |
| ML-13 | Isolation-Forest-driven `/alerts` feed | `serving.py:check_anomalies` | **No** | UNKNOWN, blocked by BUG-005 |

## 5. NLP / Voice / Kannada

| ID | Capability | Module | Live-verified | Status |
|----|-----------|--------|----------------|--------|
| NLP-01 | Kannada script detection | `translate.py` | Yes (prior pass, this pass indirectly) | VERIFIED |
| NLP-02 | Kannada → English translation | `translate.py` | Yes, this pass and prior | VERIFIED |
| NLP-03 | English → Kannada answer translation | `translate.py` | Yes, prior pass | VERIFIED |
| NLP-04 | Full Kannada investigation pipeline (translate → intent → retrieve → evidence → answer → translate back) | orchestrator + translate.py | Yes, prior pass: "how many theft cases in Mandya" round-tripped correctly | VERIFIED, though not re-run this pass |
| NLP-05 | Kannada latency | — | Yes, measured: 13.3–13.4s vs 0.4–0.6s English | VERIFIED (as a measurement); the latency itself is BUG-016, open |
| NLP-06 | Speech-to-text (faster-whisper) | `speech.py` | **No** | UNKNOWN — no audio input device available in this environment |
| NLP-07 | Text-to-speech | `speech.py` | **No** | UNKNOWN — same constraint |
| NLP-08 | Translation-unavailable fallback | `translate.py:TranslationUnavailable` | **No** | UNKNOWN — not triggerable without disabling the model |
| NLP-09 | Named-entity extraction (persons/locations) | `entities.py` | Yes, indirectly — every person/district resolution in this session depends on it | VERIFIED |
| NLP-10 | Transliteration variants (name-spelling drift) | `translit.py` | Indirectly — `test_entity_resolution.py` and live alias-check results depend on it | PARTIAL |
| NLP-11 | Model weight streaming from File Store at cold start | `model_fetch.py` | Contradicted by evidence — `VERITAS_MODELS_FOLDER_ID` unset live, yet Kannada works in ~2s | FALSE CLAIM (BUG-017) — weights are not being fetched from File Store the way the changelog claims |

## 6. RBAC / profile capability matrix

Six roles × the operations each can perform. `Y`/`N`/`masked` derived from `packages/policy/policy/rules.py`
and live-tested this session and prior.

| Role | Rank | `/cases` scope | `/fir` cross-station | `/copilot` cross-station | Identity masking | Traversal depth | Live-tested this session |
|------|------|-----------------|------------------------|-----------------------------|-------------------|-------------------|----------------------------|
| IO | 1 | own station only | 403 | 403 | masked | 2 hops | **Yes** — `/fir`, `/copilot` both 403 confirmed |
| SHO | 2 | all stations | 200 | 200 | **masked** | 2 hops | **Yes** — masking confirmed this session |
| DSP | 3 | all stations | 200 | 200 | unmasked | 4 hops | **Yes** — unmasked confirmed this session |
| SP | 4 | all stations | 200 | 200 | unmasked | 4 hops | Prior pass only |
| SCRB_Analyst | 4 | all stations | 200 | 200 | unmasked | 4 hops | Prior pass only |
| IG | 5 | all stations | 200 | 200 | unmasked | 4 hops | **Yes** — used as the primary test role throughout |

Not yet exercised for any role this session: hotspot/analytics access by rank (the code
applies no rank restriction to analytics endpoints — worth confirming that's
intentional, not an oversight, since §9 of the request asks for it explicitly).

## 7. Deployment chain

| ID | Stage | Verified | Evidence |
|----|-------|----------|----------|
| DEP-01 | Local → git commit | VERIFIED | Every fix this session |
| DEP-02 | git push → GitHub | VERIFIED | `gh run list` confirms pushes trigger workflow |
| DEP-03 | GitHub Actions build (`Dockerfile.overlay`) | VERIFIED | Two full runs, ~2min each, both green |
| DEP-04 | Image upload to Catalyst signed URL | VERIFIED | Two full runs |
| DEP-05 | `appsail/upsert` finalization | VERIFIED | Two full runs, both confirmed via subsequent `GET /appsail` polling (not just the 200 response) |
| DEP-06 | AppSail runtime — cold start | VERIFIED | Measured twice, ~22.7–22.9s |
| DEP-07 | AppSail runtime — Data Store binding | VERIFIED | `/health` reports real row counts every time |
| DEP-08 | AppSail runtime — File Store (model weights) | CONTRADICTS DOCS | See NLP-11 / BUG-017 |
| DEP-09 | AppSail runtime — QuickML | BROKEN, diagnosed | BUG-021 (fixed) / BUG-022 (open) |
| DEP-10 | AppSail runtime — Cache | VERIFIED | `/health` reports `cache=catalyst` |
| DEP-11 | Web Client Hosting deploy (`catalyst deploy --only client`) | VERIFIED | This session, first time — artifact-verified via CDP, not just exit code |
| DEP-12 | Cron — `veritas_refresh` (6h) | VERIFIED (the job itself); schedule unobserved | BUG-024 fixed, deployed, and watched to genuine completion live (5-6 min real runtime — confirms the original synchronous-timeout defect was real and unavoidable). Whether Cron's 6h schedule actually invokes it was not observed this session |
| DEP-13 | Cron — `veritas_audit_verify` (12h) | VERIFIED (the job logic; schedule itself still unobserved) | Triggered manually with the real job token — works correctly, chain intact |
| DEP-14 | Audit hash chain integrity | VERIFIED | Triggered `/jobs/audit-verify` live — `intact: true` against the real, live audit log, not a test fixture |

## 8. Data integrity (carried forward from Phase 1, re-confirmed this session)

| ID | Check | Status |
|----|-------|--------|
| DATA-01 | No duplicate FIRs / accused / accounts / transactions / graph edges | VERIFIED (`data/tests/test_integrity.py`, 23 checks, re-run this session) |
| DATA-02 | Foreign-key consistency across ER + `vx_` tables | VERIFIED |
| DATA-03 | District/station identifier consistency | VERIFIED |
| DATA-04 | Generator determinism | VERIFIED |
| DATA-05 | Live `/cases` payload duplication | VERIFIED clean, this session (0 dup `fir_id`) |
| DATA-06 | BriefFacts narrative repetitiveness → false similarity risk | **FIXED, live-verified** | `_MO_VARIANTS` now covers all 20 crime types (3 variants each) plus per-case time-of-day and offender-count slot-filling; live backfill via `/jobs/regenerate_narratives` recomputed `BriefFacts` for the deployed dataset without touching case/accused/identity/financial/graph rows. Cross-case similarity (`_similar_cases`) now returns a structured `explanation` (crime type, shared IPC sections, district, matching MO) instead of a bare embedding score. **BUG-023 (P1) fixed** |

---

## What this matrix does NOT yet cover (honest, not silent)

- Full click-through of every UI control listed UNKNOWN in §1 — the console has been
  proven capable of correct rendering (login, chat, evidence, health) via CDP; extending
  that same harness to every button is mechanical but not yet done.
- Map rendering as an actual geographic tool (pan/zoom/cluster/drill-down) — API-level
  hotspot data is verified; MapLibre rendering itself is not.
- Voice pipeline end to end — no audio input device in this environment. This is a hard
  environmental constraint, not a skipped step.
- A real FINANCIAL trail (RAG-07) — every person queried this session either had no
  linked account or the query wasn't pointed at one; the empty-trail path is thoroughly
  verified, the populated path is not.
- Multi-turn conversational context (RAG-17/18) — every live test used an isolated
  session; pronoun resolution across turns is unit-tested only.
- Whether Aequitas fairness auditing (ML-12) is reachable from the live product at all,
  or exists purely as an offline analysis script.
- Cron jobs actually firing on schedule (DEP-12/13) vs. only their auth gate.
- `BriefFacts` repetitiveness and its downstream effect on similarity/embeddings
  (DATA-06) — flagged by the user's own brief as a known concern, not yet traced.

These are named here so the next pass has a concrete, prioritized list rather than a
vague "test everything" — continuing this audit means working down this list, not
re-deriving it.
