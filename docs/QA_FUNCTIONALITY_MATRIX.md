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
| UI-06 | Command bar — EN/KN toggle | `CommandBar.tsx` | Sets `language` state | **VERIFIED** (North Star hardening pass, 2026-08-26) | CDP: clicked live, `ಕನ್ನಡ` tab visibly activates (amber highlight moves off `EN`); the toggle governs the language of the *next answer*, not console chrome i18n — by design, not a gap |
| UI-07 | Command bar — voice on/off toggle | `CommandBar.tsx` | Sets `voiceOut` | UNKNOWN | Still not exercised — no audio pipeline to observe from a toggle click alone; genuinely gated on NLP-06/07 |
| UI-08 | Command bar — Export PDF button | `CommandBar.tsx` → `exportPdf()` | Downloads session as file | **VERIFIED both states** (North Star hardening pass) | CDP: `disabled=true` at 0 turns confirmed as before; after a real turn, `disabled=false` confirmed live and the click fires a real `/export/pdf` request (network-captured). **Found and fixed a real gap the same pass**: the response was HTTP 200 with an HTML body (BUG-018's fallback) and the console silently downloaded it with zero in-app indication "PDF" hadn't happened — `exportPdf()` now reports whether the blob was a real PDF, and the console shows "PDF renderer unavailable on this deployment — downloaded a printable HTML copy instead." Deployed and bundle-grepped live (`page-69a5dfde3ec8de99.js` contains the string) |
| UI-09 | Command bar — Switch (sign out) | `CommandBar.tsx` | `setToken(null)`, returns to LoginGate | VERIFIED | Live via a real manual sign-in (no `?as=` shortcut): click Switch -> token cleared, back at login gate. **Note**: testing this through the `?as=ROLE` URL shortcut instead looks like a failure (token restored, still signed in) -- that is the shortcut correctly re-authenticating on every LoginGate mount, by design, not a bug. Caught and ruled out before being misreported |
| UI-10 | Command bar — health readout | `CommandBar.tsx` | Shows FIR/node/index counts, live-status dot | VERIFIED | Screenshot matches `/health` exactly |
| UI-11 | Chat pane — send text query | `ChatPane.tsx:send` | Types, submits, streams SSE | VERIFIED | CDP: real query, real streamed answer, real citation |
| UI-12 | Chat pane — push-to-talk mic | `ChatPane.tsx:toggleMic` | Records audio, waveform | UNKNOWN | No audio input device in this environment |
| UI-13 | Chat pane — citation chip click | `ChatPane.tsx:withCitations` | Scrolls/highlights evidence rail item | **VERIFIED** (North Star hardening pass) | CDP: clicked the `[1]` chip live — evidence card highlighted/expanded and the evidence-thread line (UI-16) drew to it. Chrome relaunched with `--headless=new --remote-debugging-port`, driven over Node 22's global WebSocket per `[[veritas-console-verification]]` |
| UI-14 | Evidence rail — item expand | `EvidenceRail.tsx` | Shows full content + source query | VERIFIED | Visible in chat screenshot (1 cited, expanded); re-confirmed this pass, now also showing the `SELECT ... FROM fir WHERE fir_number = :n` source query line |
| UI-15 | Evidence rail — "Ask about this case" (Copilot open) | `EvidenceRail.tsx` | Opens Copilot overlay for a FIR | **VERIFIED** (North Star hardening pass) | CDP: clicked "Open Investigation Copilot" directly from a citation card — overlay opened with real timeline/leads/similar-cases/diary content for FIR 9992 |
| UI-16 | Evidence thread — citation-to-card line draw | `EvidenceThread.tsx` | SVG line from chip to card | **VERIFIED** (North Star hardening pass) | CDP screenshot shows a real diagonal line from the `[1]` citation chip to the evidence card — the signature visual feature genuinely renders, not merely wired |
| UI-17 | Reasoning trace panel (expand/collapse) | `ReasoningTrace.tsx` | Plain-language agent trace, off by default | **VERIFIED** (North Star hardening pass) | CDP: clicked the disclosure arrow — expanded to show all 5 real trace steps with per-step durations (Orchestrator 4ms, SQL Agent 1ms, Vector Search Agent 1ms — skipped, Evidence Evaluator 0ms, Evidence Synthesis 18ms) |
| UI-18 | Case explorer — search box | `CaseExplorer.tsx` | Filters `/cases` by text | **VERIFIED** (North Star hardening pass) | CDP: typed "Hurt" — every visible card became Hurt, and the footer read "Showing 60 of 1557 matching cases," exactly matching the Hurt filter-chip count (1557) shown on the same screen |
| UI-19 | Case explorer — crime-type filter chips | `CaseExplorer.tsx` | Toggles facet filter | VERIFIED | Live: clicked "Theft", chip highlighted, district count correctly narrowed 24->19, every visible card is Theft |
| UI-20 | Case explorer — case-status filter chips | `CaseExplorer.tsx` | Toggles facet filter | UNKNOWN | Not driven this pass either — status chips (Under Investigation/Convicted/etc.) were visible with correct live counts but not clicked |
| UI-21 | Case explorer — "Ask about this case" per card | `CaseExplorer.tsx` | Sends a templated chat query | **VERIFIED** (North Star hardening pass) | CDP: clicked on a real case card — sent "What is the status of FIR 100222201202600022?" and received the correct grounded, cited answer |
| UI-22 | Case explorer — "Copilot brief" per card | `CaseExplorer.tsx` | Opens Copilot overlay | VERIFIED | Live: clicked, overlay opened and rendered the officer's own header state correctly around it; re-confirmed this pass |
| UI-23 | Context view — pane switcher (index/viz) | `ContextView.tsx` | Toggles case index vs map/graph/sankey/trend | **VERIFIED** (North Star hardening pass) | CDP: a hotspot query auto-switched the pane to "Geospatial — hotspot density"; clicked "Case index" and it switched back live, tab highlight moved correctly both times |
| UI-24 | Map view | `viz/MapView.tsx` | Real OpenFreeMap (MapLibre "liberty") basemap, hotspot density, case points | **VERIFIED (2026-08-26, real-basemap pass)** | The self-drawn dark canvas (no roads, no terrain, no real place recognition) was replaced with a real OSM-derived MapLibre style — no API key/registration, the fifth documented Catalyst-exception (CLAUDE.md §2). Veritas's own overlays unchanged: FIR points, hotspot density polygons, district reference labels/dots (re-styled for legibility against a light basemap — two-tone dot, dark chip behind each name), legend, scale, zoom, and a new compact attribution control (ODbL requires crediting OSM, unlike the old canvas which had no third-party data to credit). Local CDP verification, 4 queries: a tight single-district cluster (Mandya — real roads/water/city labels), a bare statewide-phrased query (falls back to the true busiest district, Bengaluru Urban — recognizable city label from the basemap itself), a distant district (Bidar, on the Telangana border, to confirm re-centering works anywhere in the state), and a district with no hotspot evidence (Kodagu — honest refusal, graceful fallback to the case index, no broken map). See `docs/screenshots/2026-08-26-real-basemap/`, which supersedes `docs/screenshots/2026-08-26-map-investigator-grade/` (that pass's zoom-cap/legend fixes still apply, now drawn over real geography). **Still not done**: true district boundary polygons (unchanged, correctly deferred — no shapefile in this dataset); live (post-deploy) re-verification — see handoff. |
| UI-25 | Network view | `viz/NetworkView.tsx` | Force-directed graph | VERIFIED | Screenshotted live: 12 labeled nodes, correct sizing/coloring, legible |
| UI-26 | Sankey view | `viz/SankeyView.tsx` | Money-flow diagram | **FIXED** (North Star Phase 5) | Above 25 nodes, only the 20 highest-value nodes keep a label (every node stays hoverable via the existing tooltip, so no information is lost). Deployed bundle byte-verified identical (sha256) to the local build carrying the fix. Live data flow re-confirmed (Harish Savadi, 60-destination trail) |
| UI-27 | Trend view | `viz/TrendView.tsx` | Forecast bands (ECharts) | VERIFIED | Screenshotted live: proper band chart, axis labels, real dates |
| UI-28 | Copilot overlay — timeline/leads/diary/similar cases | `Copilot.tsx` | Renders `/copilot/{id}` | **VERIFIED** (North Star hardening pass) | CDP: overlay opened live for FIR 9992 with real content in all four sections — timeline (1 event), 5 MO-similar cases each with a distinct `text similarity` % and a real structured explanation (crime type/IPC sections/district/MO — confirms BUG-023's narrative fix holds up under interactive use, not just API sampling), 5 capped leads naming real graph signals (PageRank 0.0011, community 6, associate counts), and the draft case-diary paragraph |
| UI-29 | Copilot — "Copy" diary button | `Copilot.tsx` | Clipboard copy | **VERIFIED** (North Star hardening pass) | CDP: monkey-patched `navigator.clipboard.writeText`, clicked Copy, and the real draft-diary text landed in the captured clipboard call verbatim |
| UI-30 | Alert toasts | `AlertToasts.tsx` | SSE-driven anomaly toasts (transport changed from WebSocket, v12) | **VERIFIED (backend), PARTIAL (visual)** | `GET /alerts` re-confirmed live this pass: unauthenticated → 401, authenticated → real streaming payloads with genuine explanatory factors (`district_code`, `metric`, `observed` vs `expected`, `severity`) — an auditable anomaly, not an opaque "AI says suspicious" badge, satisfying the North Star's explainability bar for this surface. `AlertToasts.tsx` correctly reconnects on drop and renders `observed`/`expected` inline. Not re-screenshotted in the toast-visible state this pass (alerts arrive on an interval; the component itself and the feed behind it are both now independently confirmed correct) |

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
| API-08 | `POST /export/pdf` | `export.py` | PARTIAL, root-caused | Live-verified this pass: 2 real bugs found+fixed (wrong SDK method name, unbound SDK context — failure mode changed twice in the intended direction); still returns `text/html` due to a remaining `INVALID_ID`/"No such User" Catalyst identity question, only testable via a real Catalyst Auth sign-in this session's tooling cannot drive. Console still honest — never claims a PDF it didn't produce (BUG-018) |
| API-09 | `GET /alerts` (SSE, transport changed from WebSocket in v12) | `alerts.py` | **VERIFIED (live, North Star hardening pass)** | Re-confirmed live: unauthenticated → 401 `{"detail":...}`; authenticated → real SSE stream, 4 distinct district alerts received in 8s with genuine `observed`/`expected`/`severity` fields, not placeholder data |
| API-10 | `POST /jobs/refresh` | `jobs.py` | **VERIFIED (fixed)** | BUG-024 fixed: moved to a background thread. Redeployed (`52852000000310022`) — see the failure log for the live re-verification |
| API-11 | `GET /jobs/audit-verify` | `jobs.py` | VERIFIED | Triggered live with the real deployed job token: `{"intact":true,"first_bad_audit_id":null}` — the audit hash chain is genuinely intact |
| API-12 | `GET /health` | `main.py` | VERIFIED | Extensively, both deploys |

## 3. Conversational RAG — every intent

| ID | Intent | Source | Live-verified this session? | Status |
|----|--------|--------|------------------------------|--------|
| RAG-01 | `FIR_LOOKUP` (exact) | `orchestrator.py` | Yes, repeatedly | VERIFIED |
| RAG-02 | `FIR_LOOKUP` (nonexistent) | same | Yes | VERIFIED |
| RAG-03 | `PERSON_HISTORY` | same | Yes ("does X have priors") | **VERIFIED (content, not just routing) — North Star hardening pass** | Prior "VERIFIED" only checked that an answer with citations came back. This pass found live that every case's crime type/status/district/narrative rendered as "not recorded" (BUG-028, P0) — real data existed, `person_record()` just never fetched it (a ZCQL 4-JOIN-cap collision). Fixed, deployed, and re-verified: the same query now returns full case detail |
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
| RAG-17 | Pronoun/reference resolution ("does **he** have priors") | `intents.has_unresolved_reference` | Yes | VERIFIED — live 3-turn session: named subject, then "Does he have priors?", then "What about his money trail?", both pronouns correctly resolved against the session's carried-forward subject. Re-confirmed this pass with **"her"** specifically (a different pronoun than any prior session tried): turn 1 named Usha Naika, turn 2 "What about her money trail?" correctly resolved to her and returned the correct FINANCIAL negative-finding answer, not a misfire |
| RAG-18 | Multi-turn session continuity | `vx_session`/`vx_conversation_turn` | Yes | VERIFIED — same 3-turn session as RAG-17; subject persisted correctly across all three turns. This is also the session that surfaced BUG-028 (above) — worth noting that deeper conversational testing, not routing checks alone, is what actually finds content-level defects |
| RAG-19 | HippoRAG retrieval | `retrieval/hipporag.py` | Indirectly (trace shows it firing) | PARTIAL |
| RAG-20 | Think-on-Graph deep-dive | `retrieval/tog.py` | Indirectly (trace shows it firing on relational intents) | PARTIAL |
| RAG-21 | LLM-fluent synthesis | `llm.py`/`synthesis_agent.py` | Yes — confirmed NOT firing (extractive fallback used throughout) | BROKEN — see BUG-021/022 |
| RAG-22 | Extractive (deterministic) synthesis | `synthesis_agent._extractive` | Yes, every live answer this session | VERIFIED |
| RAG-23 | Citation numbering/grounding | `synthesis_agent.build_citations` | Yes, extensively | VERIFIED |
| RAG-24 | `CASE_CONTEXT` ("what happened?") | `orchestrator.py` (new, this pass) | Yes, live console + curl | VERIFIED — reads `SessionFocus.active_fir`, re-validated against station scope on every use (`fir_by_id`), not trusted from when the FIR was first opened |
| RAG-25 | `CASE_PEOPLE` ("who's involved?") | same | Yes, live console + curl | VERIFIED — lists the case's accused (network viz, real PageRank-sized nodes); auto-resolves `active_person` when exactly one, leaves it unset and names candidates when several rather than guessing |
| RAG-26 | `SIMILAR_CASES`, case-scoped (open case, no name needed) | same, reuses `copilot.brief.similar_cases_for` | Yes, live console + curl | VERIFIED — same structurally-explained similarity Copilot already used (crime type/IPC section/district/MO), now reachable from chat directly; confidence rendered as "text similarity", not evidential confidence |
| RAG-27 | `CASE_LOCATIONS` ("where are those cases concentrated?") | same | Yes, live console + curl | VERIFIED — tallies districts over the PREVIOUS turn's cited FIRs (not a fresh unscoped hotspot query), re-checked against policy scope before being shown; renders the map pane with those specific case points |
| RAG-28 | `NEXT_STEPS` ("what should I investigate next?") | same, reuses `copilot.brief.leads_for_case` | Yes, live console + curl | VERIFIED — identical lead-generation logic the `/copilot` endpoint already uses (direct co-accused only, PageRank/community-cited), now reachable from chat |
| RAG-29 | `BRIEFING` ("prepare the briefing") | same, reuses `copilot.brief.generate_copilot_brief` | Yes, live console via CDP, MULTI-accused case (2026-08-26 golden-conversation pass; FIR 100050504202300018, 4 accused) | VERIFIED — closes the "only verified against a single-accused case" gap: draft case-diary paragraph + leads over all 4 accused, station-scope-checked by the same function `/copilot` calls; `NotPermitted`/`KeyError` degrade to an empty, honest result rather than a leak or a crash |
| RAG-30 | `EXPLAIN_REASONING` ("why are you showing me these?") | same | Yes, live console + curl | VERIFIED — re-describes the PREVIOUS turn's own agent trace and citations from `vx_conversation_turn`, not a fresh retrieval; refuses honestly (`nothing_prior`) on a session's first turn |
| RAG-31 | `EVIDENCE_FOR` ("what evidence supports that?") | same | Yes, live curl | VERIFIED — re-shows the previous turn's citations/evidence; same `nothing_prior` refusal on a first turn |
| RAG-32 | Ambiguous person names ask instead of guess | `node_orchestrate` (new, this pass) | Yes, unit-tested; live-tested only the "clear leader" path (no tie found in the live dataset for the names tried) | PARTIAL — the tie-break logic itself has direct unit coverage (`test_an_ambiguous_name_asks_instead_of_guessing`); a live query that actually produces a tied `record_count` was not found this pass |
| RAG-33 | Session-focus persistence across the FULL turn (not just pre-retrieval) | `node_retrieve` (bug fix, this pass) | Yes, live: "Open FIR X" then, one turn later, "What happened?" answered about X | VERIFIED — this was a real, previously-unnoticed gap: `node_orchestrate` persisted focus BEFORE retrieval ran, but `FIR_LOOKUP` resolves `active_fir` DURING retrieval, so it was never saved; the next turn found no case ever opened. Fixed by persisting again after retrieval resolves |

| RAG-34 | Pronoun after a multi-person `CASE_PEOPLE` turn asks instead of refusing blindly | `orchestrator.py` (`_recent_person_candidates`, new 2026-08-26) | Yes, live console + curl, reproduced pre-fix first; re-verified live through the console (2026-08-26 golden-conversation pass, turn 19) against a REAL 4-way tie (Usha Naika, Prashanth Krishnamurthy, Nithin Madar, Naveen Nayak) | VERIFIED — found live in an earlier pass's conversational sanity check: "Who is involved?" (2 accused, correctly leaves `active_person` unset) → "Does he have priors?" used to fall to a bare `no_subject` refusal, discarding the two names the previous turn had just shown. Now checks the previous turn's own `accused:` citations and, with 2+ candidates, asks which one by name — reusing the existing `ambiguous_person` clarification path (RAG-32's mechanism), sourced from `vx_conversation_turn` instead of a fresh name search. **A deeper bug in the same mechanism was found and fixed in the 2026-08-26 golden-conversation pass**: `CASE_PEOPLE` with several accused only *set* `active_person` when there was exactly one — with several, it did nothing, so a person named several turns (and cases) earlier stayed silently "active" and a pronoun follow-up answered about THAT stale person instead of ever reaching this clarification path. Fixed by explicitly clearing `active_person` to `None` when several are accused. Also fixed in an earlier pass: `CASE_LOCATIONS`'s "nothing to map" refusal was reusing `EXPLAIN_REASONING`'s "this is the first answer" message verbatim, which is false on any turn but the actual first one — now has its own accurate message |
| RAG-35 | A decided refusal (`ambiguous_person`, `person_not_on_file`) does not still run a generic search | `orchestrator.py` (`node_retrieve`, new 2026-08-26) | Yes, live console via CDP + unit test, reproduced pre-fix first | VERIFIED — found live in the 2026-08-26 golden-conversation pass: `node_retrieve` only skipped retrieval for refusals it decides itself (CAPABILITY, NOT_INFERABLE) or re-derives (NEEDS_CASE/NEEDS_SUBJECT, guarded so as not to set a DUPLICATE reason but not returning early when one is already set) — so an ambiguous-person refusal (active_person cleared) skipped every specialist branch for lack of a subject, but the untargeted vector-search fallback at the bottom of `_run_specialists` had no such guard and searched anyway, populating the Evidence rail with 5 unrelated criminal-profile citations next to a chat message saying "I will not guess which one you mean." `node_retrieve` now returns immediately whenever `state.refusal_reason` is already set on entry |

**A note on how RAG-24–33 were found**: the mega-prompt this pass ran against asked whether the
conversational layer was "genuinely conversational" or "intent classification + isolated
deterministic tools + response formatting". Reading the orchestrator answered part of that
question directly — the Investigation Copilot's leads/similar-cases/briefing logic already
existed and was already correct, but was reachable only through `/copilot`, never through
`/chat`. The bigger finding was RAG-33: the session-focus mechanism that was supposed to make
follow-ups work had a real persistence bug undercutting it for the single most obvious
follow-up in the whole system ("Open FIR X" → "What happened?"). Also found and fixed live
during this verification pass, not part of the plan going in: `data/data/nlp/entities.py`'s
PERSON-span extraction clipped a surname that wasn't in the 271-name gazetteer sample off an
adjacent known first name ("Usha Naika" → "Usha"), which silently resolved to a DIFFERENT
person and answered about them at full confidence — see `PHASE1_FAILURE_LOG.md` for the write-up.

## 4. Analytics / ML — each traced INPUT → DATA → ALGORITHM → OUTPUT → EVIDENCE

| ID | Capability | Module | Live-verified | Status |
|----|-----------|--------|----------------|--------|
| ML-01 | Fellegi-Sunter entity resolution | `entity_resolution/fellegi_sunter.py` | Indirectly — `vx_person`/`vx_accused_identity` are its output, confirmed populated and referentially consistent (`test_integrity.py`) | PARTIAL — the F1=0.989 claim itself was not re-measured against the live dataset this session (still not recomputable there: the live 10k-case dataset predates this pass's fix, §19 gap below). **Fixed the recomputability gap itself**: `run.py` now persists `IDENTITY_ANSWER_KEY` the same way `AML_LABELS` already survives to disk (`docs/DATA_GENERATION_AUDIT.md` §19), and `data/generator/score_identity.py` recomputes precision/recall/F1 from it against whatever `vx_accused_identity` is currently bound — out-of-band, matching the `fairness_run_audit.py` precedent, not wired to any route. Deliberately not exercised against the live Catalyst dataset: the answer key file only exists from this point forward for a *future* generation run, and regenerating the currently-seeded 10k-case live dataset just to produce it would violate this project's own "don't regenerate casually" rule for a P2/nice-to-have gap |
| ML-02 | KDE + DBSCAN hotspots | `spatial/hotspots.py` | Yes (prior pass): named-district query returns real clusters + real incident points | VERIFIED (API level); map rendering UNKNOWN |
| ML-03 | Prophet + MinT forecast | `forecasting/forecast.py` | Yes (prior pass): 30-day series, plausible values | VERIFIED (API level); chart rendering UNKNOWN |
| ML-04 | XGBoost + SHAP risk scoring | `risk/scoring.py` | Yes, live this pass | PARTIAL, honestly — live returns 1.00 for a heavy-prior person, correctly labeled "NOT calibrated" because the live dataset's calibration split lacks class balance to fit isotonic regression; the fallback fires exactly as designed (BUG-014 fixed at the reporting level) |
| ML-05 | LightGBM recidivism | `risk/scoring.py` (via `predict_recidivism`) | Yes: fires alongside risk | PARTIAL — value not checked against the answer key |
| ML-06 | Isolation Forest district-spike alerts | `risk/anomalies.py` | **Yes (North Star hardening pass)** — `/alerts` is reachable and streaming (see API-09) | **VERIFIED** — 4 real alerts observed live in one 8s window, e.g. `KA05 monthly_fir_count 105.0 vs expected 73.5, high` |
| ML-07 | Louvain community detection | (via `data/gds.py`, not ml_models directly) | Yes: person 803 → community 28, plural communities confirmed in prior pass | VERIFIED |
| ML-08 | PageRank / betweenness (graph centrality) | `data/gds.py` | Yes, live this pass (North Star Phase 3) | VERIFIED — network view renders real PageRank-derived node sizing/color, live-verified via "Who are the associates of Usha Naika?"; field renamed `risk_score`→`pagerank` end to end (payload + TS type) since it was never a risk score, matching the BUG-011 confidence-kind discipline |
| ML-09 | Rule-based AML structuring detector | `financial/structuring.py` | Yes, live this pass (North Star Phase 5) | VERIFIED reachable, PARTIAL on a positive case — root-cause fix: the detector was checking `money_trail`'s incidental `from_account` (for a multi-hop transfer, an intermediate account nobody owns; structurally never the receiving side structuring targets), never the person's own account. Now checks every account via new `graph_agent.owned_accounts()`. Live-verified against 10 real people with real trails/accounts: detector genuinely runs (trace: "AML Detectors (structuring + GNN)"), correctly returns 0 flags on accounts with no sub-threshold deposit burst. No live positive example found this session (would need the original `.veritas/aml_labels.json`, not available outside the original seeding run) |
| ML-10 | GNN suspicious-subgraph AML | `financial/gnn.py` | Reachability fixed alongside ML-09 | PARTIAL — same reachability fix applies; `torch` is still absent from the deployed image (confirmed still true, hard AppSail bundle-sandbox size constraint, empirically measured in v7: 9.31GB and 4.66GB images both failed). `GNNUnavailable` degrades gracefully (verified in code: `serving.flag_transactions` catches it explicitly). A from-scratch numpy backprop reimplementation was considered and deliberately not attempted — a subtly-wrong hand-rolled gradient computation for a financial-crime detector is a worse failure mode than an honest unavailability, and the rule-based detector (now actually reachable) is the system's own documented primary/auditable detector regardless |
| ML-11 | DoWhy causal effects | `causal/effects.py` | Yes, this pass: confirmed declining with a precise reason (`dowhy` not installed in the deployed image) | BROKEN live (by design/image-size trade-off), correctly reported as such |
| ML-12 | Aequitas fairness audit | `fairness/audit.py` | Resolved by reading `serving.py`'s own module docstring | N/A (live product) | Explicitly designed as out-of-band: `serving.py` documents its callers as "fairness/run_audit.py: run_fairness_audit (out-of-band, pre-demo)" — a standalone CLI script (`packages/ml_models/fairness_run_audit.py`), never wired to any API route or UI control. Not a gap — by design |
| ML-13 | Isolation-Forest-driven `/alerts` feed | `serving.py:check_anomalies` | **Yes (North Star hardening pass)** | **VERIFIED** — see ML-06/API-09; BUG-005's blocker (WebSocket transport) was already superseded by the v12 SSE migration, re-confirmed live this pass |

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
| DEP-12 | Cron — `veritas_refresh` (6h) | **VERIFIED, unattended fire confirmed (North Star hardening pass)** | BUG-025's config fix (wrong hostname + stale token) is now proven, not just plausible: listed the live Cron job directly this pass and found `success_count: 1, failure_count: 0` (was 0/20) — a real unattended fire succeeded on schedule after the fix, with no manual trigger involved |
| DEP-13 | Cron — `veritas_audit_verify` (12h) | **Was still BROKEN unattended after BUG-025; root-caused and fixed this pass** | Listing the live job showed `success_count: 0, failure_count: 21` — one MORE failure than BUG-025 recorded, meaning the URL/token fix alone did not make the schedule succeed. Root cause: unlike `/jobs/refresh`, `/jobs/audit-verify` ran `verify_chain()` (a `ds.query()`) synchronously in the request — exactly the call that pays BUG-001's ~23s cold-container mirror-hydration cost, inside a request Cron abandons long before that. Fixed by applying the identical background-thread pattern `/jobs/refresh` already uses (commit `d5f0798`, deployed `52852000000316042`); a `sync=true` param preserves the original inline `{"intact":...}` response for a human running the check by hand. Live-verified post-deploy: default call returns `{"status":"started"}` in 0.2s, `?sync=true` still returns the real result. **The schedule's own next unattended fire (up to 12h out) is what would confirm success_count finally increments** — the defect that was actually causing every failure is now fixed and unit-tested (5 new tests), not merely reconfigured |
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

## BUG-026 — Copilot leads render a person's canonical name, not the as-filed name, with no visible link between them

Severity: P2 (UX/trust, not a correctness or masking defect)
Component: `packages/rag_agent/copilot/brief.py:_leads`
Status: **FIXED and live-verified (2026-08-26, finishing pass)** — `_leads()` now calls a
new `_lead_name(officer_role, canonical, as_filed)` helper, which renders `"Canonical
(filed as \"AsFiled\" on this FIR)"` whenever the two differ, and the masked placeholder
(never either raw name) for a masked role. Live-verified against Usha Naika's own FIR
100050504202300018 in the golden-conversation pass's `NEXT_STEPS`/`BRIEFING` turns —
`"Usha Naika (filed as \"Usha Neik D/o Srinivas\" on this FIR)"` renders correctly
throughout (`docs/screenshots/2026-08-26-full-investigation-walkthrough/t14-next-steps.png`,
`t15-briefing.png`). 2 new unit tests (the reconciliation, and the masking guard).

### Symptoms
Found live via CDP while verifying UI-28 (Copilot overlay): FIR 9992's own accused list
(`/fir/9992`) names the second accused **"Suma Nadkarni D/o Eshwar"** — the record as
filed. The same case's Copilot brief leads section reads *"**Soom Nadkarni** has 163
direct co-accused associate(s)..."* — a different spelling, for the same `PersonUID`
(877), with nothing in the UI indicating these are the same person.

### Root cause
This is entity resolution working *correctly*, not a data-integrity bug — confirmed by
checking `/person/877` directly: `name_en: "Soom Nadkarni"` matches `vx_person.CanonicalName`
exactly. `Accused.AccusedName` ("Suma Nadkarni") is the case-specific as-filed record,
which per `CLAUDE.md` §3's own documented generator behavior is expected to carry a
romanisation variant on ~35% of rows; Fellegi-Sunter correctly resolved it to the
person's canonical identity. `_leads()` renders `vx_person.CanonicalName` (line 209);
the case's own accused list renders `Accused.AccusedName` — both correct for what they
are, but nothing cross-references them for the officer reading both in the same brief.

### Why this matters
North Star §1.1 stage 3 (entity discovery) names exactly this requirement: "every
reconstructed person carries an inspectable match confidence, not just a merged name."
An officer reading the case's accused list and then the Copilot's leads section, in the
same investigation, has no way to tell "Suma Nadkarni" and "Soom Nadkarni" are the same
defendant without independently querying `/person/877` — which most officers would not
think to do, since nothing on screen suggests a name mismatch exists at all. This is
also §11's "aliases should be visible where appropriate" requirement, unmet on this one
surface (the `ALIAS_CHECK` intent, RAG-05, already does this correctly elsewhere in the
product).

### Recommended fix (not implemented — a scope decision, not a difficulty one)
`_leads()` already has both values (`a["CanonicalName"]` and `a["AccusedName"]`) in
scope. When they differ, render both: `"Soom Nadkarni (filed as \"Suma Nadkarni\" on
this FIR) has 163 direct co-accused..."` — small, uses data already fetched, no new
query. Left open rather than fixed in this pass to keep the pass's live-system changes
scoped to defects with a clear, singular fix; this one touches the same trust-critical
surface as BUG-004/BUG-011 and deserves its own regression test when picked up.

---

## What this matrix does NOT yet cover (honest, not silent)

- **CLOSED 2026-08-26 (finishing pass)**: the full 19-turn golden conversation specified
  by four consecutive prior mega-prompts (open case → ... → briefing → switch case →
  switch back → ambiguous reference → unauthorized case) was finally driven end to end
  through the live CONSOLE via CDP — not curl. Found and fixed 4 real bugs (a stale
  `active_person` surviving a case switch and blocking RAG-34's own clarification path
  from ever firing; `EXPLAIN_REASONING`'s regex missing natural verb phrasing; `NEXT_STEPS`
  missing a passive-voice keyword; a decided refusal still running generic search and
  padding the Evidence rail — see RAG-35, `docs/VERITAS_HANDOFF.md`, and
  `docs/screenshots/2026-08-26-full-investigation-walkthrough/`). All 19 turns plus a Kannada follow-up
  and an IO cross-station authorization check are now confirmed correct in a second,
  post-fix live run. QuickML and PDF export were both re-checked directly against the
  live AppSail configuration and a real `/export/pdf` call (not re-guessed) — both still
  correctly BLOCKED, unchanged.

- Full click-through of every UI control listed UNKNOWN in §1 — narrowed significantly
  this pass (UI-06/13/15/16/17/18/21/22/23/28/29 moved PARTIAL/UNKNOWN → VERIFIED via a
  real CDP session). Still not driven: UI-07 (voice toggle — hardware-gated), UI-20
  (case-status filter chips).
- Map rendering as an actual geographic tool — **now visually verified this pass** (see
  UI-24: real district labels, scale, zoom, hotspot clustering, all screenshotted live).
  Pan/drag interaction specifically was not driven (a screenshot proves render
  correctness, not drag-to-pan behavior).
- Voice pipeline end to end — no audio input device in this environment. This is a hard
  environmental constraint, not a skipped step.
- A real FINANCIAL trail (RAG-07) — every person queried this session either had no
  linked account or the query wasn't pointed at one; the empty-trail path is thoroughly
  verified, the populated path is not.
- **AML detectors against a real injected pattern (ML-09/10)** — a local
  `.veritas/aml_labels.json` exists from a prior generation run, but its TxnIDs
  (max 2354) could not be confidently matched against the live 10k-case dataset's own
  transaction numbering without a live database introspection path this session did not
  have (an admin ZCQL query attempt returned `INVALID_URL_PATTERN` against the one
  endpoint shape tried — not chased further, matching this project's own rule against
  guessing repeatedly at a live API). Still UNKNOWN for the positive-detection path;
  the reachability/negative-case path remains VERIFIED per the prior pass.
- ~~Multi-turn conversational context (RAG-17/18) — every live test used an isolated
  session~~ — **closed this pass**: a single live session was driven through a 14-turn
  investigation (open FIR → case context → accused → priors → associates → why-these →
  similar cases → their geography → financial trail → what-supports-that → next steps →
  briefing), both via curl and via the real console through CDP. See RAG-24–33.
- Ambiguous-name clarification (RAG-32) against a REAL tied NAME SEARCH in the live
  dataset — the pronoun-side variant of this same mechanism now has a live 4-way-tie
  proof (RAG-34, 2026-08-26 golden-conversation pass, turn 19); the original scope (a
  plain name search hitting a tied `record_count`) still hasn't happened by chance.
- ~~A populated `BRIEFING` path (RAG-29) against a multi-accused case~~ — **closed
  2026-08-26 (finishing pass)**: the golden conversation's turn 15 exercised `BRIEFING`
  against FIR 100050504202300018 (4 accused) live through the console.
- Whether Aequitas fairness auditing (ML-12) is reachable from the live product at all,
  or exists purely as an offline analysis script — unchanged this pass, still by-design
  out-of-band per `serving.py`'s own docstring.
- `BriefFacts` repetitiveness and its downstream effect on similarity/embeddings
  (DATA-06) — flagged by the user's own brief as a known concern; this pass's live
  Copilot verification (UI-28) directly observed 5 distinct, non-templated MO-similarity
  explanations for the same crime type, which is positive evidence BUG-023's fix holds,
  though not a full re-audit of DATA-06 itself.
- `veritas_audit_verify`'s Cron job's own NEXT unattended fire, post-BUG-027 — the fix is
  deployed and unit-tested; independently observing it succeed on its own 12h schedule
  (rather than via a manual `sync=true` call) was not done this pass.

These are named here so the next pass has a concrete, prioritized list rather than a
vague "test everything" — continuing this audit means working down this list, not
re-deriving it.
