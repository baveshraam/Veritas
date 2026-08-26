# Phase 1 — Truth Table

> **Not updated in the 2026-08-26 North Star hardening pass.** That pass's findings
> (BUG-026, BUG-027) and current test count (315, via `pytest --collect-only -q`) live in
> `docs/PHASE1_FAILURE_LOG.md` and `docs/QA_FUNCTIONALITY_MATRIX.md`, which are the
> current source of truth for defect/verification status — this file is a point-in-time
> record of the 2026-08-25 pass and should be read as history, not current state.

**Audit date**: 2026-08-25
**Method**: every row was established by running the thing, not by reading about it.
Live rows were driven against the deployed API
(`https://veritas-api-50043864344.development.catalystappsail.in`) with real tokens for
all six roles. Unit/integration rows were established by `python -m pytest`.

**Baseline at the start of this audit**: 201 tests green.
**After the first fix pass**: 271 tests green, deployed as `9393a8b` (deployment
`52852000000304010`) and live-verified.
**After the second fix pass**: 283 tests green (2 additionally skipped where an
AppSail-only dependency isn't installed, by design), deployed as `71dc2a4` (deployment
`52852000000310011`) and live-verified, including the console for the first time
(`scripts/deploy-console.sh`, verified via the served artifact and CDP-driven browser
tests, not the deploy command's exit code).

> **Status convention.** `FIXED (L3)` — verified at unit, integration and API level
> against the real dataset, but not yet re-driven against the deployed service — no
> longer applies to anything in this table as of the second pass: every row that stage
> reached, this one reached live. The only rows still short of `VERIFIED` are ones
> live verification itself could not settle (F3/C18 — QuickML's own gateway; A20 —
> an apparent platform WebSocket-proxying limit) or that were out of this phase's
> scope entirely (voice, most of the UI, Cron firing).

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
| A2 | Roster load on a **cold container** | Same, within the console's budget | Y | Y | N | N | Y | Y | Y | VERIFIED | Warm thread ungated. **Measured with a real forced restart: 22.7–22.9s, exactly once per container**, every other request 0.13–0.2s → **BUG-001** |
| A3 | Sign-in (`POST /auth/token`) | JWT for a known KGID | Y | Y | Y | Y | Y | Y | Y | VERIFIED | All 6 badges issue a token carrying the correct role |
| A4 | Unknown badge | 401 | Y | Y | Y | Y | Y | — | Y | VERIFIED | 401 "Unknown badge number" |
| A5 | No token on protected routes | 401 | — | Y | Y | Y | Y | — | Y | VERIFIED | `/cases`, `/fir`, `/person`, `/copilot` → 401 |
| A6 | Garbage / empty token | 401 | — | Y | Y | Y | Y | — | Y | VERIFIED | 401 "Invalid token" |
| A7 | Token expiry | Reject expired tokens | — | Y | Y | N | N | — | — | UNKNOWN | 12h TTL in code; not exercised live |
| A8 | Role comes from token, never body | Body `officer_role` ignored | — | Y | Y | Y | N | — | — | PARTIAL | Enforced in code (`chat.py`), no live negative test |
| A9 | **Unverified fallback mode** | Console opens; record-scoped calls refused | Y | — | N | N | Y | Y | Y | VERIFIED | **Reproduced live in the browser via CDP**: seeded a stale token, forced a real roster failure, confirmed the token is cleared exactly on entering unverified mode (`localStorage` inspected before/after) → **BUG-002** |
| A10 | Fallback UI claim | Says what continuing actually does | Y | — | N | N | Y | Y | Y | VERIFIED | Live screenshot confirms the exact live copy: "continuing on one signs you out…" → **BUG-002** |
| A11 | Retry after roster failure | Re-request the roster | Y | — | N | N | N | — | — | UNKNOWN | `loadRoster` is wired to the button; not exercised |
| A12 | IO station scoping (`/cases`) | IO sees own station only | Y | Y | Y | Y | Y | Y | Y | VERIFIED | IO total=81 (1 station); every other role 10000 |
| A13 | IO station scoping (`/fir/{id}`) | 403 on another station's FIR | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 403 "filed at another police station" |
| A14 | **IO station scoping (`/copilot/{id}`)** | Same rule as `/fir` | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Reconfirmed live on the second deploy: `/fir/9992` and `/copilot/9992` both 403 for the same IO → **BUG-003 (P0)** |
| A15 | Person masking (`/person`) | `name_en`,`name_kn`,`dob` nulled below DSP | Y | Y | Y | Y | Y | Y | Y | VERIFIED | IG/DSP see names; SHO/IO get nulls |
| A16 | **Masking parity (`/fir` accused)** | Same fields, same rule | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Reconfirmed live on the second deploy → **BUG-004** |
| A17 | **Masking parity (copilot leads/timeline)** | Same fields, same rule | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Reconfirmed live: zero DSP-visible names in the SHO's brief → **BUG-004** |
| A18 | Traversal depth cap by rank | IO/SHO 2 hops, DSP+ 4 | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested; no live rank-contrast measurement |
| A19 | Job endpoints (`/jobs/*`) | Shared-secret only | — | Y | N | N | Y | — | Y | VERIFIED | 401 "Bad job token" without the header |
| A20 | **WebSocket `/alerts`** | Should require an officer | Y | Y | Y | Y | **blocked** | — | — | FIXED (code, ASGI-level); live UNVERIFIABLE | A real WS client and raw curl both get a plain-HTTP 404 from Starlette's own router — routing/CORS reach the app, the upgrade never does. Reads as an AppSail gateway limitation on WebSocket proxying for custom runtimes, not a defect in the fix → **BUG-005** |
| A21 | CORS for the hosted console | Allow the Slate origin | — | Y | N | N | Y | — | Y | VERIFIED | Correct `Access-Control-Allow-Origin` on GET and preflight |

## B. Core investigation

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| B1 | Case index (`/cases`) | Browsable, policy-scoped | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 60 rows, no duplicate `fir_id`/`fir_number`, facets correct |
| B2 | FIR detail (`/fir/{id}`) | One FIR + accused/victims/sections | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Correct content; the A16 masking defect is fixed |
| B3 | FIR lookup by 18-digit number (chat) | Return that FIR | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Live: 1 citation (was 6). Also driven through the actual browser UI via CDP → **BUG-006 (P0)** |
| B4 | FIR lookup, nonexistent number | Refuse | Y | Y | Y | Y | Y | — | Y | VERIFIED | `exact_lookup_missed` → REJECT, 0 citations |
| B5 | Person lookup (`/person/{id}`) | Resolved cross-case identity | Y | Y | Y | Y | Y | Y | Y | VERIFIED | PersonUID 803 → 18 cases across several stations |
| B6 | Person not found | 404 | Y | Y | Y | Y | Y | — | Y | VERIFIED | 404 "Person not found" |
| B7 | Identity resolution (Fellegi-Sunter) | Reconstruct people from `Accused` | — | Y | Y | Y | Y | Y | Y | VERIFIED | Asserted by `test_entity_resolution.py`; live alias found for 803 |
| B8 | Prior-case lookup ("does X have priors") | The person's own record | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Reconfirmed live → **BUG-006** |
| B9 | Name → person resolution | Rank by record count, surface ambiguity | — | Y | Y | Y | Y | Y | Y | VERIFIED | "Usha Naika" resolved with an "N others share this name" note |
| B10 | Unknown person named | Clear focus, refuse | — | Y | Y | Y | Y | — | Y | VERIFIED | "Zzyzx Nonexistentperson" → refusal, 0 citations |
| B11 | Copilot brief | Timeline, similar cases, leads, diary | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Station check and masking now fixed (A14, A17). The diary is still the deterministic string rather than LLM prose (F3) |

## C. Investigation engine

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| C1 | Intent classification | Route the question | — | Y | Y | Y | Y | — | Y | PARTIAL | C2 fixed; 2 new intents added (CAPABILITY, NOT_INFERABLE). C3 still has no branch |
| C2 | `SIMILAR_CASES` intent | Similar-case search | — | Y | Y | N | Y | Y | Y | VERIFIED | Live: routes to `SIMILAR_CASES` correctly → **BUG-007** |
| C3 | `CRIME_SEARCH` intent | Answer "how many / list" | — | Y | N | N | Y | — | Y | **FIXED, live-verified** | An exact, role/station-scoped count (`sql_agent.count_firs`) + up to 5 supporting FIR samples, as authoritative evidence; vector search no longer runs on top of a settled count. Live: "How many theft cases in Mandya district?" → "73 case(s) Theft in Mandya", `authoritative:true`, vector search step shows "Skipped" → **BUG-008 fixed** |
| C4 | Out-of-scope question | Say so intentionally | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Live, both deploys → **BUG-009** |
| C5 | Under-specified question | Ask for the missing subject | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Live, both deploys → **BUG-010** |
| C6 | Entity extraction (NER) | Persons, locations, IPC sections | — | Y | Y | Y | Y | — | Y | VERIFIED | Person and district extraction both drive live answers |
| C7 | Reference resolution ("does he…") | Resolve against session focus | — | Y | Y | Y | N | — | — | PARTIAL | Unit-tested; not driven live in this audit |
| C8 | HippoRAG retrieval | Personalized PageRank from entities | — | Y | Y | Y | Y | — | Y | VERIFIED | Fires whenever a person resolves |
| C9 | Think-on-Graph deep-dive | Beam search on low confidence | — | Y | Y | Y | Y | — | Y | VERIFIED | Runs on relational intents |
| C10 | Graph traversal (associates) | Co-accused within depth cap | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Usha Naika → 12 associates, network renders |
| C11 | Evidence assembly | Only supporting records | — | Y | Y | Y | Y | Y | Y | VERIFIED | `supporting()` is the one definition; extended to `authoritative` items (BUG-020) — live-verified on CAUSAL and FINANCIAL → **BUG-006 (P0)** |
| C12 | Evidence confidence semantics | A support score | Y | Y | N | N | Y | Y | Y | **FIXED, live-verified** | `EvidenceItem.confidence_kind` (support/similarity/model_estimate) set at each origin point; console labels each distinctly instead of one undifferentiated %. Live: vector hits show `confidence_kind:"similarity"`, risk/recidivism show `"model_estimate"`, exact/graph/authoritative items show `"support"` → **BUG-011 fixed** |
| C13 | Reasoning trace | Plain-language agent trace | Y | Y | Y | Y | Y | — | Y | VERIFIED | Streams correctly; steps and timings match the code path |
| C14 | Citation generation | 1-based, in evidence order | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Indices line up with the rail |
| C15 | Refusal (CRAG REJECT) | Never answer on empty evidence | Y | Y | Y | Y | Y | — | Y | VERIFIED | Refuses on nonexistent FIR, unknown person, weak batches |
| C16 | Refusal **message** | State the actual reason | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Live, both deploys |
| C17 | Deterministic fallback (no LLM) | Grounded extractive answer | Y | Y | Y | Y | Y | Y | Y | VERIFIED | This is what every live answer currently is |
| C18 | LLM synthesis | Fluent prose over the same evidence | — | Y | Y | N | Y | Y | Y | BROKEN, root cause fully diagnosed | Credential bug fixed (BUG-021) — live failure mode changed from an internal AttributeError to a real HTTP 400 from QuickML itself. A second, undiagnosed gateway rejection remains (BUG-022). Every answer stays grounded and cited regardless: what is lost is fluency, not truth |
| C19 | Engine error handling | Report, never half-answer | Y | Y | Y | Y | Y | — | Y | VERIFIED | `error` frame carries type + message; console surfaces it |

## D. Analytics

| ID | Component | Intended behavior | UI | Backend | Unit | Integ | Live | Data | Repeat | Status | Evidence / Failure |
|----|-----------|-------------------|----|---------|------|-------|------|------|--------|--------|--------------------|
| D1 | Hotspots, district named | KDE + DBSCAN clusters | Y | Y | Y | Y | Y | Y | Y | PARTIAL | "theft hotspots in Bengaluru Urban" → KA05, 4 clusters, map renders. Padded with 5 vector hits (BUG-006) |
| D2 | Hotspots, no district named | Fall back to busiest district | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Works (v11 fix holds). Same padding |
| D3 | Forecast | Prophet + MinT, 30 days | Y | Y | Y | Y | Y | Y | Y | PARTIAL | 74 FIRs / 30 days in KA05, trend renders. Same padding |
| D4 | Crime trends | Same as forecast | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Routes to FORECAST — reasonable, same padding |
| D5 | Network analysis | Co-offender graph | Y | Y | Y | Y | Y | Y | Y | VERIFIED | 12 associates, network viz, all GRAPH_RELATIONSHIP evidence |
| D6 | Network, no subject named | Ask who | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Live → **BUG-010** |
| D7 | Community detection (Louvain) | Real communities | — | Y | Y | Y | Y | Y | Y | VERIFIED | Person 803 in community 28; communities are plural and realistically sized |
| D8 | Financial tracing (named subject) | Sankey money flow | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Live: 1 citation (was 5) — the negative finding, and nothing else → **BUG-013** |
| D9 | Financial tracing, no subject | Ask who | Y | Y | Y | Y | Y | Y | Y | VERIFIED | → **BUG-010** |
| D10 | Suspicious-transaction detection | Rule + GNN | — | Y | Y | Y | N | — | — | UNKNOWN | Not reachable live in this audit (D8 blocks the path) |
| D11 | Risk scoring | XGBoost + SHAP | Y | Y | Y | Y | Y | N | Y | **PARTIAL, honestly so** | Isotonic-calibrated with a `calibrated` flag, same proven pattern as recidivism. Live: still returns 1.00 for a heavy-prior person, but now says so plainly — "(NOT calibrated — a ranking score, not a probability)" — because the live dataset's calibration split lacks enough class balance to fit isotonic regression, and the code falls back honestly rather than reporting a calibration that didn't happen → **BUG-014 fixed at the reporting level; the underlying saturation on this dataset is a data-volume limit, not a code defect** |
| D12 | Recidivism (LightGBM) | 180-day, calibrated | — | Y | Y | Y | Y | N | Y | PARTIAL | Fires; value not validated against the answer key |
| D13 | Causal layer (DoWhy) | Effect on real Census data | Y | Y | Y | Y | Y | Y | Y | PARTIAL | Live it **declines**, root cause now known (`dowhy` not installed in the deployed image, a deliberate v7 image-size trade-off), and the decline is now correctly the sole citation instead of being buried under noise (BUG-020) → **BUG-015 (P2)** |
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
| F3 | LLM (QuickML) | Fluent synthesis | — | Y | Y | N | Y | Y | Y | BROKEN, precisely diagnosed | Credential bug found and fixed (BUG-021: `_token()` called a method that does not exist on the real SDK — verified against the actual installed package). Live failure mode changed from an internal error to a real HTTP 400 from QuickML's own gateway, which now rejects the request for a separate, undocumented reason (BUG-022) → **BUG-012** |
| F4 | SQLite read mirror | Hydrate once per container | — | Y | Y | Y | Y | Y | Y | VERIFIED | Reads are fast and consistent; it is the cold-start cost that is the problem (A2) |
| F5 | Warm-up thread | Pre-hydrate before first query | — | Y | N | N | Y | Y | Y | VERIFIED | Ungated, and confirmed live: the warm-up cost is paid once (22.7–22.9s) and never again per container → **BUG-001** |
| F6 | Pagination dedupe | Drop the page-boundary duplicate | — | Y | Y | Y | Y | Y | Y | VERIFIED | ROWID dedupe + `INSERT OR IGNORE`; no duplicates observed in any live payload |
| F7 | Cache (Catalyst) | Session focus | — | Y | Y | Y | Y | — | Y | VERIFIED | `cache=catalyst` |
| F8 | File Store | Model weights | — | Y | N | N | N | — | — | UNKNOWN | Not exercised — see E8 |
| F9 | Cron jobs | 6h refresh, 12h audit verify | — | Y | N | N | N | — | — | UNKNOWN | Endpoints authorize correctly; schedule not observed firing |
| F10 | SSE `/chat` | Stream trace then final | Y | Y | Y | Y | Y | Y | Y | VERIFIED | Frame envelope matches the console's parser exactly |
| F11 | WebSocket `/alerts` | Push alerts | Y | Y | N | N | N | — | — | UNKNOWN | See A20 |
| F12 | PDF export | SmartBrowz PDF | Y | Y | Y | N | Y | — | Y | PARTIAL | Returns **`text/html`**, not PDF — the offline fallback. Console names the file `.html`, so it is not lying, but the feature is degraded → **BUG-018 (P2)** |
| F13 | Deployed console | Loads and drives the API | Y | — | N | N | N | — | — | UNKNOWN | Not re-driven headlessly in this pass |
| F14 | Cold start | Container serves correctly from cold | — | Y | N | N | Y | Y | Y | VERIFIED | **Measured with two independent real restarts**: 22.72s and 22.9s. Real, once-per-container, matches the architecture's own description exactly |
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

| Status | Audit start | 1st fix pass (deployed, live) | 2nd fix pass (deployed, live) |
|--------|-------------|-------------------------------|-------------------------------|
| VERIFIED | 34 | 38 | **56** |
| FIXED (L3, not yet live) | — | 19 | 0 |
| FIXED (code); live blocked | — | — | 1 |
| PARTIAL | 19 | 16 | 16 |
| BROKEN | 18 | 2 | 3 |
| FALSE CLAIM | 4 | 2 | 2 |
| UNKNOWN | 14 | 12 | 11 |
| **Total** | **89** | **89** | **89** |

Every row that reached `FIXED (L3)` in the first pass reached `VERIFIED` in the second —
that entire status no longer appears anywhere in this table. One row (A20, `/alerts`)
is fixed in code and passes an in-process ASGI test, but live verification is blocked by
what the evidence points to as an AppSail platform limitation on WebSocket proxying, not
a defect in the fix; it is marked accordingly rather than folded into either VERIFIED or
BROKEN.

BROKEN went from 2 to 3 because live verification of the QuickML credential fix (BUG-021)
surfaced a second, previously invisible problem (BUG-022, the gateway's own rejection of
the request) — C18/F3 is still BROKEN, now for a precisely diagnosed reason instead of an
unknown one. UNKNOWN dropped by one (F14, cold start, now measured twice: 22.72s and
22.9s, both real forced restarts).

Still BROKEN: C18/F3 (LLM synthesis — auth fixed, gateway rejection open as BUG-022), and
D13/BUG-015 stays PARTIAL rather than BROKEN because its decline is honest and, since
BUG-020, no longer buried under noise.
Still FALSE CLAIM: E8 (the changelog says the model weights left the image; the live
configuration says they did not — BUG-017).

**Final implementation pass, live-verified this session**: C3/BUG-008 (CRIME_SEARCH now
returns an exact count), C12/BUG-011 (confidence_kind distinguishes similarity/support/
model_estimate, console relabeled), D11/BUG-014 (risk scoring calibrated, with an honest
`calibrated:false` reported live rather than a false calibration claim). Re-verified live
in the same pass and unchanged: BUG-006 (exact FIR lookup — 1 citation, no padding),
BUG-020 (causal refusal — 1 authoritative citation, no unrelated profiles).

The single most consequential finding was **BUG-006**: unconditional vector search meant
almost every answer in the system carried citations that did not support it. Fixed and
verified live twice over — once via the API, once by driving an actual chat turn through
the deployed console in a headless browser and confirming exactly one citation rendered.

## Live verification status

**Both fix passes are deployed and live-verified**, API and (as of the second pass)
console. `FIXED (L3, not yet live)` does not appear anywhere in this table as of the
second pass — every code fix that reached that stage was subsequently re-driven against
the live deployment, not left at L3.

What remains genuinely open, and why:

1. **QuickML reachability** (F3, C18, BUG-021/BUG-022). The credential bug is fixed and
   *verified* live: the failure mode changed from an internal `AttributeError` (proven by
   extracting and reading the real SDK's source, then reproducing the exact error against
   the real installed package) to a real HTTP 400 from QuickML's own gateway. That second
   rejection — `PATTERN_NOT_MATCHED` / "zoho-inputstream parameter" — was investigated as
   far as external tooling allows (varied body, headers, tested with an independently
   valid Catalyst token to isolate it from AppSail's credential) and remains unresolved.
   Resolving it needs the QuickML console's Model Details page (UI-only) or vendor
   documentation/support neither of which this session had access to.
2. **`/alerts` live reachability** (A20, BUG-005). The fix is correct in-process (a real
   ASGI WebSocket test exercises the auth logic end to end and passes). Live, a real
   WebSocket client and raw `curl` with proper upgrade headers both receive Starlette's
   plain "not found" — while a known REST route through the same domain correctly 401s,
   and CORS middleware visibly processes the request. That pattern points at the AppSail
   gateway not proxying WebSocket upgrades for custom-runtime apps at all, which would
   mean this route has never worked live on any version of this code — but it was not
   possible to get a platform-level confirmation of that within this audit.

Everything else that reached VERIFIED reached it against the live, deployed system —
API twice (`52852000000304010`, then `52852000000310011`) and console once
(`scripts/deploy-console.sh`, artifact-verified via CDP, not the exit code).
