# Phase 1 — Truth Table

**Audit date**: 2026-08-25
**Method**: every row was established by running the thing, not by reading about it.
Live rows were driven against the deployed API
(`https://veritas-api-50043864344.development.catalystappsail.in`) with real tokens for
all six roles. Unit/integration rows were established by `python -m pytest`.

**Baseline at the start of this audit**: 201 tests green.
**After this pass**: 271 tests green.

> **Status convention after the fix pass.** A row that read BROKEN and has since been
> fixed reads `FIXED (L3)` — verified at unit, integration and API level against the real
> dataset through the real HTTP surface, but **not** re-driven against the deployed
> service, because these changes are not deployed. `L3` is not `VERIFIED` and is not
> upgraded to it until the live run happens. See "Live verification status" at the foot
> of this document.

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
| A2 | Roster load on a **cold container** | Same, within the console's budget | Y | Y | N | N | Y | — | Y | FIXED (L3); duration UNKNOWN | Warm thread ungated; the console no longer calls a pending request a timeout. **The duration was never measured** — restarting the container was not permitted → **BUG-001** |
| A3 | Sign-in (`POST /auth/token`) | JWT for a known KGID | Y | Y | Y | Y | Y | Y | Y | VERIFIED | All 6 badges issue a token carrying the correct role |
| A4 | Unknown badge | 401 | Y | Y | Y | Y | Y | — | Y | VERIFIED | 401 "Unknown badge number" |
| A5 | No token on protected routes | 401 | — | Y | Y | Y | Y | — | Y | VERIFIED | `/cases`, `/fir`, `/person`, `/copilot` → 401 |
| A6 | Garbage / empty token | 401 | — | Y | Y | Y | Y | — | Y | VERIFIED | 401 "Invalid token" |
| A7 | Token expiry | Reject expired tokens | — | Y | Y | N | N | — | — | UNKNOWN | 12h TTL in code; not exercised live |
| A8 | Role comes from token, never body | Body `officer_role` ignored | — | Y | Y | Y | N | — | — | PARTIAL | Enforced in code (`chat.py`), no live negative test |
| A9 | **Unverified fallback mode** | Console opens; record-scoped calls refused | Y | — | N | N | Y | — | Y | FIXED (L3) | `enterUnverified()` clears the token first, so unverified now means unauthenticated → **BUG-002** |
| A10 | Fallback UI claim | Says what continuing actually does | Y | — | N | N | Y | — | Y | FIXED (L3) | Reworded: "continuing on one signs you out, so every record-scoped answer will be refused until the roster loads" → **BUG-002** |
| A11 | Retry after roster failure | Re-request the roster | Y | — | N | N | N | — | — | UNKNOWN | `loadRoster` is wired to the button; not exercised |
| A12 | IO station scoping (`/cases`) | IO sees own station only | Y | Y | Y | Y | Y | Y | Y | VERIFIED | IO total=81 (1 station); every other role 10000 |
| A13 | IO station scoping (`/fir/{id}`) | 403 on another station's FIR | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 403 "filed at another police station" |
| A14 | **IO station scoping (`/copilot/{id}`)** | Same rule as `/fir` | Y | Y | **Y** | **Y** | Y | Y | Y | FIXED (L3) | `can_view_fir` enforced inside `generate_copilot_brief`; the router returns the same 403 `/fir` does → **BUG-003 (P0)** |
| A15 | Person masking (`/person`) | `name_en`,`name_kn`,`dob` nulled below DSP | Y | Y | Y | Y | Y | Y | Y | VERIFIED | IG/DSP see names; SHO/IO get nulls |
| A16 | **Masking parity (`/fir` accused)** | Same fields, same rule | Y | Y | **Y** | **Y** | Y | Y | Y | FIXED (L3) | `policy.mask_person_name` applied to `AccusedName` and `VictimName` → **BUG-004** |
| A17 | **Masking parity (copilot leads/timeline)** | Same fields, same rule | Y | Y | **Y** | **Y** | Y | Y | Y | FIXED (L3) | A test asserts no DSP-visible name appears anywhere in an SHO's brief → **BUG-004** |
| A18 | Traversal depth cap by rank | IO/SHO 2 hops, DSP+ 4 | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested; no live rank-contrast measurement |
| A19 | Job endpoints (`/jobs/*`) | Shared-secret only | — | Y | N | N | Y | — | Y | VERIFIED | 401 "Bad job token" without the header |
| A20 | **WebSocket `/alerts`** | Should require an officer | Y | Y | **Y** | **Y** | N | — | — | FIXED (L3) | The token is the first frame; `officer_from_token` gates the stream → **BUG-005** |
| A21 | CORS for the hosted console | Allow the Slate origin | — | Y | N | N | Y | — | Y | VERIFIED | Correct `Access-Control-Allow-Origin` on GET and preflight |

## B. Core investigation

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| B1 | Case index (`/cases`) | Browsable, policy-scoped | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 60 rows, no duplicate `fir_id`/`fir_number`, facets correct |
| B2 | FIR detail (`/fir/{id}`) | One FIR + accused/victims/sections | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Correct content; the A16 masking defect is fixed |
| B3 | FIR lookup by 18-digit number (chat) | Return that FIR | Y | Y | Y | **Y** | Y | Y | Y | FIXED (L3) | An acceptance test asserts every cited item's `source_id` is the target FIR → **BUG-006 (P0)** |
| B4 | FIR lookup, nonexistent number | Refuse | Y | Y | Y | Y | Y | — | Y | VERIFIED | `exact_lookup_missed` → REJECT, 0 citations |
| B5 | Person lookup (`/person/{id}`) | Resolved cross-case identity | Y | Y | Y | Y | Y | Y | Y | VERIFIED | PersonUID 803 → 18 cases across several stations |
| B6 | Person not found | 404 | Y | Y | Y | Y | Y | — | Y | VERIFIED | 404 "Person not found" |
| B7 | Identity resolution (Fellegi-Sunter) | Reconstruct people from `Accused` | — | Y | Y | Y | Y | Y | Y | VERIFIED | Asserted by `test_entity_resolution.py`; live alias found for 803 |
| B8 | Prior-case lookup ("does X have priors") | The person's own record | Y | Y | Y | Y | Y | Y | Y | FIXED (L3) | Below-floor vector hits are no longer citable → **BUG-006** |
| B9 | Name → person resolution | Rank by record count, surface ambiguity | — | Y | Y | Y | Y | Y | Y | VERIFIED | "Usha Naika" resolved with an "N others share this name" note |
| B10 | Unknown person named | Clear focus, refuse | — | Y | Y | Y | Y | — | Y | VERIFIED | "Zzyzx Nonexistentperson" → refusal, 0 citations |
| B11 | Copilot brief | Timeline, similar cases, leads, diary | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Station check and masking now fixed (A14, A17). The diary is still the deterministic string rather than LLM prose (F3) |

## C. Investigation engine

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| C1 | Intent classification | Route the question | — | Y | Y | Y | Y | — | Y | PARTIAL | C2 fixed; 2 new intents added (CAPABILITY, NOT_INFERABLE). C3 still has no branch |
| C2 | `SIMILAR_CASES` intent | Similar-case search | — | Y | **Y** | N | Y | — | Y | FIXED (L3) | `CRIME_SEARCH` is scored last, as the fallback it actually is → **BUG-007** |
| C3 | `CRIME_SEARCH` intent | Answer "how many / list" | — | Y | N | N | Y | — | Y | BROKEN | **No specialist branch exists.** "How many theft cases in Mandya?" is answered with 5 narratives and no count → **BUG-008 (P1)** |
| C4 | Out-of-scope question | Say so intentionally | Y | Y | **Y** | **Y** | Y | — | Y | FIXED (L3) | A `CAPABILITY` intent answers in one uncited paragraph, before retrieval runs → **BUG-009** |
| C5 | Under-specified question | Ask for the missing subject | Y | Y | **Y** | **Y** | Y | — | Y | FIXED (L3) | `NEEDS_SUBJECT` intents short-circuit before retrieval, with their own message → **BUG-010** |
| C6 | Entity extraction (NER) | Persons, locations, IPC sections | — | Y | Y | Y | Y | — | Y | VERIFIED | Person and district extraction both drive live answers |
| C7 | Reference resolution ("does he…") | Resolve against session focus | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested; not driven live in this audit |
| C8 | HippoRAG retrieval | Personalized PageRank from entities | — | Y | Y | Y | Y | — | Y | VERIFIED | Fires whenever a person resolves |
| C9 | Think-on-Graph deep-dive | Beam search on low confidence | — | Y | Y | Y | Y | — | Y | VERIFIED | Runs on relational intents |
| C10 | Graph traversal (associates) | Co-accused within depth cap | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Usha Naika → 12 associates, network renders |
| C11 | Evidence assembly | Only supporting records | — | Y | **Y** | **Y** | Y | Y | Y | FIXED (L3) | `supporting()` is the one definition, used by the evaluator **and** by synthesis → **BUG-006 (P0)** |
| C12 | Evidence confidence semantics | A support score | Y | Y | N | N | Y | Y | Y | FALSE CLAIM | Vector `confidence` is the raw hybrid similarity, rendered to the officer as evidential confidence → **BUG-011 (P1)** |
| C13 | Reasoning trace | Plain-language agent trace | Y | Y | Y | Y | Y | — | Y | VERIFIED | Streams correctly; steps and timings match the code path |
| C14 | Citation generation | 1-based, in evidence order | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Indices line up with the rail |
| C15 | Refusal (CRAG REJECT) | Never answer on empty evidence | Y | Y | Y | Y | Y | — | Y | VERIFIED | Refuses on nonexistent FIR, unknown person, weak batches |
| C16 | Refusal **message** | State the actual reason | Y | Y | **Y** | **Y** | Y | — | Y | FIXED (L3) | Five reasons, five messages; a test asserts none upgrades "not found" into "does not exist" |
| C17 | Deterministic fallback (no LLM) | Grounded extractive answer | Y | Y | Y | Y | Y | Y | Y | VERIFIED | This is what every live answer currently is |
| C18 | LLM synthesis | Fluent prose over the same evidence | — | Y | Y | N | Y | — | Y | BROKEN, now reported honestly | Still never fires. `/health` no longer claims it does → **BUG-012**. Answers remain grounded and cited: what is lost is fluency, not truth |
| C19 | Engine error handling | Report, never half-answer | Y | Y | Y | Y | Y | — | Y | VERIFIED | `error` frame carries type + message; console surfaces it |

## D. Analytics

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| D1 | Hotspots, district named | KDE + DBSCAN clusters | Y | Y | Y | Y | Y | Y | Y | PARTIAL | "theft hotspots in Bengaluru Urban" → KA05, 4 clusters, map renders. Padded with 5 vector hits (BUG-006) |
| D2 | Hotspots, no district named | Fall back to busiest district | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Works (v11 fix holds). Same padding |
| D3 | Forecast | Prophet + MinT, 30 days | Y | Y | Y | Y | Y | Y | Y | PARTIAL | 74 FIRs / 30 days in KA05, trend renders. Same padding |
| D4 | Crime trends | Same as forecast | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Routes to FORECAST — reasonable, same padding |
| D5 | Network analysis | Co-offender graph | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 12 associates, network viz, all GRAPH_RELATIONSHIP evidence |
| D6 | Network, no subject named | Ask who | Y | Y | **Y** | **Y** | Y | — | Y | FIXED (L3) | "This question needs a subject before I can search for it" → **BUG-010** |
| D7 | Community detection (Louvain) | Real communities | — | Y | Y | Y | Y | Y | Y | VERIFIED | Person 803 in community 28; communities are plural and realistically sized |
| D8 | Financial tracing (named subject) | Sankey money flow | Y | Y | **Y** | Y | Y | N | Y | FIXED (L3) | The empty case now states its negative finding as evidence, so unrelated context cannot become citation [1] → **BUG-013** |
| D9 | Financial tracing, no subject | Ask who | Y | Y | **Y** | **Y** | Y | — | Y | FIXED (L3) | → **BUG-010** |
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
| F3 | LLM (QuickML) | Fluent synthesis | — | Y | **Y** | N | Y | Y | Y | Reporting FIXED (L3); reachability UNKNOWN | `status()` now separates configured / degraded / working, and the missing-credential path degrades like every other failure. Whether QuickML is reachable at all is still unknown → **BUG-012** |
| F4 | SQLite read mirror | Hydrate once per container | — | Y | Y | Y | Y | Y | Y | VERIFIED | Reads are fast and consistent; it is the cold-start cost that is the problem (A2) |
| F5 | Warm-up thread | Pre-hydrate before first query | — | Y | N | N | N | — | — | FIXED (L3) | Ungated; only `ensure_models()` stays behind `VERITAS_MODELS_FOLDER_ID`, which is the variable that describes it → **BUG-001** |
| F6 | Pagination dedupe | Drop the page-boundary duplicate | — | Y | Y | Y | Y | Y | Y | VERIFIED | ROWID dedupe + `INSERT OR IGNORE`; no duplicates observed in any live payload |
| F7 | Cache (Catalyst) | Session focus | — | Y | Y | Y | Y | — | Y | VERIFIED | `cache=catalyst` |
| F8 | File Store | Model weights | — | Y | N | N | N | — | — | UNKNOWN | Not exercised — see E8 |
| F9 | Cron jobs | 6h refresh, 12h audit verify | — | Y | N | N | N | — | — | UNKNOWN | Endpoints authorize correctly; schedule not observed firing |
| F10 | SSE `/chat` | Stream trace then final | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Frame envelope matches the console's parser exactly |
| F11 | WebSocket `/alerts` | Push alerts | Y | Y | N | N | N | — | — | UNKNOWN | See A20 |
| F12 | PDF export | SmartBrowz PDF | Y | Y | Y | N | Y | — | Y | PARTIAL | Returns **`text/html`**, not PDF — the offline fallback. Console names the file `.html`, so it is not lying, but the feature is degraded → **BUG-018 (P2)** |
| F13 | Deployed console | Loads and drives the API | Y | — | N | N | N | — | — | UNKNOWN | Not re-driven headlessly in this pass |
| F14 | Cold start | Container serves correctly from cold | — | Y | N | N | N | — | — | UNKNOWN | Mechanism understood and mitigated (A2, F5). **Duration never measured** — restarting the container was not permitted during this audit |
| F15 | Audit hash chain | Tamper-evident trail | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested (`verify_chain`); not verified against the live log |

## G. Data integrity

| ID | Check | Status | Evidence |
|----|-------|--------|----------|
| G1 | Duplicate FIRs in an API payload | VERIFIED clean | 60 `/cases` rows, 0 duplicate `fir_id`, 0 duplicate `fir_number` |
| G2 | Duplicate rows from pagination | VERIFIED handled | ROWID dedupe in `_catalyst_select`, `INSERT OR IGNORE` on hydration |
| G3 | Duplicate people / accused / accounts / transactions / graph edges | VERIFIED clean | 23 checks in `data/tests/test_integrity.py`. The 12 apparent duplicate graph edges are **one row per transaction** — see the note at the foot of the failure log |
| G4 | Foreign/business key consistency | VERIFIED clean | Accused→CaseMaster, identity→person/accused, case→station→district, officer→station, txn→account, and every graph node→record all resolve |
| G5 | District / station identifier consistency | PARTIAL | `canonical_code("Bengaluru Urban") == "KA05"` holds; the v11 `KAnn` fix holds live |
| G6 | Deterministic seeding | UNKNOWN → see G3 | Generator is seeded; determinism never asserted |
| G7 | Duplicate frontend rendering | UNKNOWN | Not driven headlessly in this pass. The API payloads it renders are duplicate-free (G1) |

---

## Summary

89 rows audited. Counted from this table, not estimated.

| Status | At audit start | After the fix pass |
|--------|----------------|--------------------|
| VERIFIED | 34 | 38 |
| FIXED (L3, not yet live) | — | 19 |
| PARTIAL | 19 | 16 |
| BROKEN | 18 | 2 |
| FALSE CLAIM | 4 | 2 |
| UNKNOWN | 14 | 12 |
| **Total** | **89** | **89** |

The transitions: 15 BROKEN and 2 FALSE CLAIM and 2 PARTIAL became FIXED; 3 UNKNOWN data-
integrity rows became VERIFIED once the suite existed to check them; and 1 BROKEN row
(F14, cold start) became **UNKNOWN**, because the mechanism was fixed but the duration was
never measured — which is a demotion to honesty, not a regression.

Still BROKEN: C3 (`CRIME_SEARCH` answers "how many" with narratives and no count —
BUG-008, deliberately left open, see the failure log) and C18 (LLM synthesis never fires).
Still FALSE CLAIM: C12 (vector similarity displayed as evidential confidence — BUG-011)
and E8 (the changelog says the model weights left the image; the live configuration says
they did not — BUG-017).

The single most consequential finding was **BUG-006**: unconditional vector search meant
almost every answer in the system carried citations that did not support it. The console's
central claim — *"Every claim in the answer carries the record it came from"* — was
literally true and practically false, because five of the six records under a FIR-status
answer were about other crimes in other districts. It is fixed, and there is now an
acceptance test that fails if any cited item is about a different record.

## Live verification status

**The pre-fix behaviour recorded in this table was measured live.** The post-fix behaviour
was not: none of these changes is deployed. Every `FIXED (L3)` row is verified at unit,
integration and API level against the real dataset through the real HTTP surface with no
mocks — but the deployed container is still running the previous image.

Two things therefore remain genuinely unknown, and are not marked otherwise:

1. **Cold-start duration** (A2, F14). The mechanism is established from the code and from
   the live AppSail configuration; the number of seconds is not. Measuring it requires
   restarting the container, which was not permitted during this audit.
2. **Whether QuickML is reachable from the container at all** (F3, C18). The reporting is
   fixed, so a deployed `/health` will now say which of "not configured", "degraded:
   &lt;reason&gt;" or "working" is true. Until it is deployed and read, this is UNKNOWN.

Both resolve on the next deploy. Nothing in this table should be upgraded to VERIFIED
before that run happens.
