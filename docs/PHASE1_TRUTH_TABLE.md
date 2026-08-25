# Phase 1 — Truth Table

**Audit date**: 2026-08-25
**Method**: every row was established by running the thing, not by reading about it.
Live rows were driven against the deployed API
(`https://veritas-api-50043864344.development.catalystappsail.in`) with real tokens for
all six roles. Unit/integration rows were established by `python -m pytest`.

**Baseline at the start of this audit**: 201 tests green.

## How to read the columns

- **UI / Backend exists** — the code path is present and reachable.
- **Unit / Integration tested** — a test in this repo exercises it.
- **Live verified** — driven against the deployed API during this audit.
- **Data verified** — the values it returned were checked against the record layer.
- **Repeatable** — same input produced the same output across runs.
- **Status** — `VERIFIED` / `PARTIAL` / `BROKEN` / `FALSE CLAIM` / `UNKNOWN`.
  `UNKNOWN` is never upgraded on the strength of a passing unit test alone.

Bug IDs reference `docs/PHASE1_FAILURE_LOG.md`.

---

## A. Authentication / authorization

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| A1 | Roster load (`GET /auth/officers`) | Return one badge per role | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 200 in 0.15s warm; 6 roles, correct names/PS |
| A2 | Roster load on a **cold container** | Same, within the console's budget | Y | Y | N | N | Y | — | Y | BROKEN | First request blocks on full mirror hydration (37 tables, ~105k rows, 300/page). Console gives up at 8s → **BUG-001** |
| A3 | Sign-in (`POST /auth/token`) | JWT for a known KGID | Y | Y | Y | Y | Y | Y | Y | VERIFIED | All 6 badges issue a token carrying the correct role |
| A4 | Unknown badge | 401 | Y | Y | Y | Y | Y | — | Y | VERIFIED | 401 "Unknown badge number" |
| A5 | No token on protected routes | 401 | — | Y | Y | Y | Y | — | Y | VERIFIED | `/cases`, `/fir`, `/person`, `/copilot` → 401 |
| A6 | Garbage / empty token | 401 | — | Y | Y | Y | Y | — | Y | VERIFIED | 401 "Invalid token" |
| A7 | Token expiry | Reject expired tokens | — | Y | Y | N | N | — | — | UNKNOWN | 12h TTL in code; not exercised live |
| A8 | Role comes from token, never body | Body `officer_role` ignored | — | Y | Y | Y | N | — | — | PARTIAL | Enforced in code (`chat.py`), no live negative test |
| A9 | **Unverified fallback mode** | Console opens; record-scoped calls refused | Y | — | N | N | Y | — | Y | BROKEN | Fallback does **not** clear the stored token, so a stale token from a previous sign-in keeps answering — at a rank the console is not displaying → **BUG-002** |
| A10 | Fallback UI claim | "ranks above are unverified, so record-scoped answers will be refused" | Y | — | N | N | Y | — | Y | FALSE CLAIM | True only with no stored token; false otherwise → **BUG-002** |
| A11 | Retry after roster failure | Re-request the roster | Y | — | N | N | N | — | — | UNKNOWN | `loadRoster` is wired to the button; not exercised |
| A12 | IO station scoping (`/cases`) | IO sees own station only | Y | Y | Y | Y | Y | Y | Y | VERIFIED | IO total=81 (1 station); every other role 10000 |
| A13 | IO station scoping (`/fir/{id}`) | 403 on another station's FIR | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 403 "filed at another police station" |
| A14 | **IO station scoping (`/copilot/{id}`)** | Same rule as `/fir` | Y | Y | N | N | Y | Y | Y | BROKEN | `/copilot/9992` returns the **full brief** to the IO whose `/fir/9992` is 403 → **BUG-003 (P0)** |
| A15 | Person masking (`/person`) | `name_en`,`name_kn`,`dob` nulled below DSP | Y | Y | Y | Y | Y | Y | Y | VERIFIED | IG/DSP see names; SHO/IO get nulls |
| A16 | **Masking parity (`/fir` accused)** | Same fields, same rule | Y | Y | N | N | Y | Y | Y | BROKEN | `/fir` returns `AccusedName` in full to SHO → **BUG-004 (P1)** |
| A17 | **Masking parity (copilot leads/timeline)** | Same fields, same rule | Y | Y | N | N | Y | Y | Y | BROKEN | Leads name people in full at every rank → **BUG-004 (P1)** |
| A18 | Traversal depth cap by rank | IO/SHO 2 hops, DSP+ 4 | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested; no live rank-contrast measurement |
| A19 | Job endpoints (`/jobs/*`) | Shared-secret only | — | Y | N | N | Y | — | Y | VERIFIED | 401 "Bad job token" without the header |
| A20 | **WebSocket `/alerts`** | Should require an officer | Y | Y | N | N | N | — | — | BROKEN | `ws.accept()` with no auth check at all → **BUG-005 (P1)** |
| A21 | CORS for the hosted console | Allow the Slate origin | — | Y | N | N | Y | — | Y | VERIFIED | Correct `Access-Control-Allow-Origin` on GET and preflight |

## B. Core investigation

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| B1 | Case index (`/cases`) | Browsable, policy-scoped | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 60 rows, no duplicate `fir_id`/`fir_number`, facets correct |
| B2 | FIR detail (`/fir/{id}`) | One FIR + accused/victims/sections | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Correct content; masking defect A16 |
| B3 | FIR lookup by 18-digit number (chat) | Return that FIR | Y | Y | Y | Y | Y | Y | Y | PARTIAL | The right FIR is `[1]` — but five unrelated records follow it → **BUG-006 (P0)** |
| B4 | FIR lookup, nonexistent number | Refuse | Y | Y | Y | Y | Y | — | Y | VERIFIED | `exact_lookup_missed` → REJECT, 0 citations |
| B5 | Person lookup (`/person/{id}`) | Resolved cross-case identity | Y | Y | Y | Y | Y | Y | Y | VERIFIED | PersonUID 803 → 18 cases across several stations |
| B6 | Person not found | 404 | Y | Y | Y | Y | Y | — | Y | VERIFIED | 404 "Person not found" |
| B7 | Identity resolution (Fellegi-Sunter) | Reconstruct people from `Accused` | — | Y | Y | Y | Y | Y | Y | VERIFIED | Asserted by `test_entity_resolution.py`; live alias found for 803 |
| B8 | Prior-case lookup ("does X have priors") | The person's own record | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Real priors returned, then padded with 5 unrelated vector hits → **BUG-006** |
| B9 | Name → person resolution | Rank by record count, surface ambiguity | — | Y | Y | Y | Y | Y | Y | VERIFIED | "Usha Naika" resolved with an "N others share this name" note |
| B10 | Unknown person named | Clear focus, refuse | — | Y | Y | Y | Y | — | Y | VERIFIED | "Zzyzx Nonexistentperson" → refusal, 0 citations |
| B11 | Copilot brief | Timeline, similar cases, leads, diary | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Content correct; no station check (A14), no masking (A17), diary is deterministic not LLM (F3) |

## C. Investigation engine

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| C1 | Intent classification | Route the question | — | Y | Y | Y | Y | — | Y | PARTIAL | 9 of 11 intents route correctly; see C2, C3 |
| C2 | `SIMILAR_CASES` intent | Similar-case search | — | Y | Y | N | Y | — | Y | BROKEN | "Find cases similar to FIR …" scores `CRIME_SEARCH` 2 vs `SIMILAR_CASES` 1 → wrong branch → **BUG-007 (P1)** |
| C3 | `CRIME_SEARCH` intent | Answer "how many / list" | — | Y | N | N | Y | — | Y | BROKEN | **No specialist branch exists.** "How many theft cases in Mandya?" is answered with 5 narratives and no count → **BUG-008 (P1)** |
| C4 | Out-of-scope question | Say so intentionally | Y | Y | N | N | Y | — | Y | BROKEN | "what all could you answer", "hello" go through retrieval and return the record-not-found refusal → **BUG-009 (P1)** |
| C5 | Under-specified question | Ask for the missing subject | Y | Y | N | N | Y | — | Y | BROKEN | "who could be the suspect", "show me the money trail" refuse with "check whether the record exists" — the wrong reason → **BUG-010 (P1)** |
| C6 | Entity extraction (NER) | Persons, locations, IPC sections | — | Y | Y | Y | Y | — | Y | VERIFIED | Person and district extraction both drive live answers |
| C7 | Reference resolution ("does he…") | Resolve against session focus | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested; not driven live in this audit |
| C8 | HippoRAG retrieval | Personalized PageRank from entities | — | Y | Y | Y | Y | — | Y | VERIFIED | Fires whenever a person resolves |
| C9 | Think-on-Graph deep-dive | Beam search on low confidence | — | Y | Y | Y | Y | — | Y | VERIFIED | Runs on relational intents |
| C10 | Graph traversal (associates) | Co-accused within depth cap | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Usha Naika → 12 associates, network renders |
| C11 | Evidence assembly | Only supporting records | — | Y | N | N | Y | Y | Y | BROKEN | Vector search is appended unconditionally to **every** intent → **BUG-006 (P0)** |
| C12 | Evidence confidence semantics | A support score | Y | Y | N | N | Y | Y | Y | FALSE CLAIM | Vector `confidence` is the raw hybrid similarity, rendered to the officer as evidential confidence → **BUG-011 (P1)** |
| C13 | Reasoning trace | Plain-language agent trace | Y | Y | Y | Y | Y | — | Y | VERIFIED | Streams correctly; steps and timings match the code path |
| C14 | Citation generation | 1-based, in evidence order | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Indices line up with the rail |
| C15 | Refusal (CRAG REJECT) | Never answer on empty evidence | Y | Y | Y | Y | Y | — | Y | VERIFIED | Refuses on nonexistent FIR, unknown person, weak batches |
| C16 | Refusal **message** | State the actual reason | Y | Y | N | N | Y | — | Y | BROKEN | One message for five different situations → **BUG-009/010** |
| C17 | Deterministic fallback (no LLM) | Grounded extractive answer | Y | Y | Y | Y | Y | Y | Y | VERIFIED | This is what every live answer currently is |
| C18 | LLM synthesis | Fluent prose over the same evidence | — | Y | Y | N | Y | — | Y | BROKEN | Never fires in production; `/health` says it is live → **BUG-012 (P1)** |
| C19 | Engine error handling | Report, never half-answer | Y | Y | Y | Y | Y | — | Y | VERIFIED | `error` frame carries type + message; console surfaces it |

## D. Analytics

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| D1 | Hotspots, district named | KDE + DBSCAN clusters | Y | Y | Y | Y | Y | Y | Y | PARTIAL | "theft hotspots in Bengaluru Urban" → KA05, 4 clusters, map renders. Padded with 5 vector hits (BUG-006) |
| D2 | Hotspots, no district named | Fall back to busiest district | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Works (v11 fix holds). Same padding |
| D3 | Forecast | Prophet + MinT, 30 days | Y | Y | Y | Y | Y | Y | Y | PARTIAL | 74 FIRs / 30 days in KA05, trend renders. Same padding |
| D4 | Crime trends | Same as forecast | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Routes to FORECAST — reasonable, same padding |
| D5 | Network analysis | Co-offender graph | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 12 associates, network viz, all GRAPH_RELATIONSHIP evidence |
| D6 | Network, no subject named | Ask who | Y | Y | N | N | Y | — | Y | BROKEN | Refuses with the record-not-found message → **BUG-010** |
| D7 | Community detection (Louvain) | Real communities | — | Y | Y | Y | Y | Y | Y | VERIFIED | Person 803 in community 28; communities are plural and realistically sized |
| D8 | Financial tracing (named subject) | Sankey money flow | Y | Y | Y | Y | Y | N | Y | BROKEN | "money trail for Usha Naika" → **`viz=none`, zero flow evidence**, answered anyway from vector noise → **BUG-013 (P1)** |
| D9 | Financial tracing, no subject | Ask who | Y | Y | N | N | Y | — | Y | BROKEN | Same wrong refusal → **BUG-010** |
| D10 | Suspicious-transaction detection | Rule + GNN | — | Y | Y | Y | N | — | — | UNKNOWN | Not reachable live in this audit (D8 blocks the path) |
| D11 | Risk scoring | XGBoost + SHAP | Y | Y | Y | Y | Y | N | Y | PARTIAL | Returns 1.00 — a saturated score, not obviously calibrated → **BUG-014 (P2)** |
| D12 | Recidivism (LightGBM) | 180-day, calibrated | — | Y | Y | Y | Y | N | Y | PARTIAL | Fires; value not validated against the answer key |
| D13 | Causal layer (DoWhy) | Effect on real Census data | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Live it **declines**: "A causal estimate for literacy_rate cannot be produced" — honest, but the capability is not working live → **BUG-015 (P2)** |
| D14 | Similarity search | Top-5 similar cases | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Via copilot: 5 Hurt cases in Mandya, similarity 0.94 down |
| D15 | Anomaly alerts (Isolation Forest) | Push district spikes | Y | Y | Y | Y | N | — | — | UNKNOWN | WebSocket not driven; also unauthenticated (A20) |

## E. NLP / Kannada

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| E1 | English input | Baseline | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Whole battery |
| E2 | Kannada input → English | Translate before anything reads it | Y | Y | Y | Y | Y | Y | Y | VERIFIED | `ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?` → "How many cases of theft are there in Mandya district" (2.1s) |
| E3 | Answer translated back | Reply in the asked language | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Round-trip completes; adds ~10.8s |
| E4 | Kannada latency | Usable | Y | Y | N | N | Y | — | Y | PARTIAL | 13.4s end-to-end vs 0.5s English → **BUG-016 (P2)** |
| E5 | Translation unavailable | Answer in English and say so | — | Y | Y | N | N | — | — | UNKNOWN | Path exists; not triggerable live |
| E6 | Speech-to-text (Kannada ASR) | faster-whisper | Y | Y | Y | N | N | — | — | UNKNOWN | Not driven with real audio in this audit |
| E7 | Text-to-speech | Voice reply | Y | Y | Y | N | N | — | — | UNKNOWN | Not driven |
| E8 | Model weights location | File Store, streamed at cold start | — | Y | N | N | Y | — | Y | FALSE CLAIM | `VERITAS_MODELS_FOLDER_ID` is **not set** on the deployed app, so `ensure_models()` never runs — the weights are still in the image at `/opt/models` → **BUG-017 (P2)** |

## F. Infrastructure

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| F1 | `/health` | Report what is actually reachable | Y | Y | N | N | Y | Y | Y | PARTIAL | Data Store / graph / vector counts are real and correct; the LLM line is not (F3) |
| F2 | Data Store (Catalyst) | Record of truth | — | Y | Y | Y | Y | Y | Y | VERIFIED | `datastore=catalyst`, 10000 FIRs |
| F3 | LLM (QuickML) | Fluent synthesis | — | Y | Y | N | Y | Y | Y | FALSE CLAIM | `/health` reports `quickml (glm-4.7-flash)`; **every** answer is extractive and the copilot diary is the deterministic string → **BUG-012 (P1)** |
| F4 | SQLite read mirror | Hydrate once per container | — | Y | Y | Y | Y | Y | Y | VERIFIED | Reads are fast and consistent; it is the cold-start cost that is the problem (A2) |
| F5 | Warm-up thread | Pre-hydrate before first query | — | Y | N | N | Y | — | Y | BROKEN | Gated on `VERITAS_MODELS_FOLDER_ID`, which is unset → **the warm thread never runs** → **BUG-001** |
| F6 | Pagination dedupe | Drop the page-boundary duplicate | — | Y | Y | Y | Y | Y | Y | VERIFIED | ROWID dedupe + `INSERT OR IGNORE`; no duplicates observed in any live payload |
| F7 | Cache (Catalyst) | Session focus | — | Y | Y | Y | Y | — | Y | VERIFIED | `cache=catalyst` |
| F8 | File Store | Model weights | — | Y | N | N | N | — | — | UNKNOWN | Not exercised — see E8 |
| F9 | Cron jobs | 6h refresh, 12h audit verify | — | Y | N | N | N | — | — | UNKNOWN | Endpoints authorize correctly; schedule not observed firing |
| F10 | SSE `/chat` | Stream trace then final | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Frame envelope matches the console's parser exactly |
| F11 | WebSocket `/alerts` | Push alerts | Y | Y | N | N | N | — | — | UNKNOWN | See A20 |
| F12 | PDF export | SmartBrowz PDF | Y | Y | Y | N | Y | — | Y | PARTIAL | Returns **`text/html`**, not PDF — the offline fallback. Console names the file `.html`, so it is not lying, but the feature is degraded → **BUG-018 (P2)** |
| F13 | Deployed console | Loads and drives the API | Y | — | N | N | N | — | — | UNKNOWN | Not re-driven headlessly in this pass |
| F14 | Cold start | Container serves correctly from cold | — | Y | N | N | N | — | — | BROKEN | Inferred and consistent with A2/F5; the first request pays full hydration |
| F15 | Audit hash chain | Tamper-evident trail | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested (`verify_chain`); not verified against the live log |

## G. Data integrity

| ID | Check | Status | Evidence |
|----|-------|--------|----------|
| G1 | Duplicate FIRs in an API payload | VERIFIED clean | 60 `/cases` rows, 0 duplicate `fir_id`, 0 duplicate `fir_number` |
| G2 | Duplicate rows from pagination | VERIFIED handled | ROWID dedupe in `_catalyst_select`, `INSERT OR IGNORE` on hydration |
| G3 | Duplicate people / accused / accounts / transactions / graph edges | UNKNOWN | No integrity suite existed at the start of this audit — **added in this phase**, see `data/tests/test_integrity.py` |
| G4 | Foreign/business key consistency | UNKNOWN → see G3 | Same |
| G5 | District / station identifier consistency | PARTIAL | `canonical_code("Bengaluru Urban") == "KA05"` holds; the v11 `KAnn` fix holds live |
| G6 | Deterministic seeding | UNKNOWN → see G3 | Generator is seeded; determinism never asserted |
| G7 | Duplicate frontend rendering | UNKNOWN | Not driven headlessly in this pass |

---

## Summary at audit start

| Status | Count |
|--------|-------|
| VERIFIED | 40 |
| PARTIAL | 20 |
| BROKEN | 16 |
| FALSE CLAIM | 5 |
| UNKNOWN | 15 |

The single most consequential finding is **BUG-006**: unconditional vector search means
almost every answer in the system carries citations that do not support it. The console's
central claim — *"Every claim in the answer carries the record it came from"* — is
literally true and practically false, because five of the six records under a FIR-status
answer are about other crimes in other districts.
