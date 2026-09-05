# Phase 1 — Failure Log

Every defect found during the Phase 1 audit, with a reproduction that does not depend
on knowing what the code does.

**Severity**
- **P0** — data corruption, security/auth failure, misleading evidence, major workflow failure
- **P1** — core feature broken or materially misleading
- **P2** — important but non-blocking
- **P3** — cosmetic/minor

Companion document: `docs/PHASE1_TRUTH_TABLE.md`.

Live reproductions were run against
`https://veritas-api-50043864344.development.catalystappsail.in`. `$T` below is a
bearer token from `POST /auth/token`.

---

## BUG-001 — A cold container blocks the first request; the console calls it a timeout

Severity: P1 · Component: apps/api (warm-up), data/ds (mirror hydration), apps/web
(LoginGate) · Status: **FIXED**

Opening the console against a container that hadn't served a request recently showed
*"The duty roster could not be loaded — the request timed out"* with six demonstration
roles substituted for the real officers — after only 8 seconds, while `GET
/auth/officers` was still in flight. A pending request was relabelled as a failed one.

**Root cause, two independent causes:**
1. On Catalyst, reads run from a SQLite mirror hydrated from the Data Store once per
   container (`data/data/ds.py:_ensure_mirror`), all-or-nothing over all 37 tables,
   paged at Data Store's hard 300-row cap. Whichever endpoint is hit first pays the
   full cost — including `/auth/officers`, which needs only `Employee`.
2. The background warm-up thread that should absorb this cost never ran in
   production: `apps/api/api/main.py` gated the whole block on
   `VERITAS_MODELS_FOLDER_ID`, a variable not set on the deployed app. The mirror and
   the model weights are unrelated concerns that had been bundled behind one flag.

**Fix:** the warm thread is no longer gated (only `ensure_models()` needs that
variable); `LoginGate.tsx`'s 8s timer now offers a *"still warming up"* state instead
of silently degrading, and only a real fetch rejection is reported as a failure.

**Verified**, with a real deliberate container restart: polling `/auth/officers`
every 2s for 5 minutes, 1 of 150 requests took 22.72s, every other request 0.13–0.2s.
This ~23-second, once-per-container cost — hydrating ~105k rows across 37 tables
through 300-row-paginated ZCQL — is real and unavoidable; the fix ensures the warm-up
mechanism actually absorbs it and the console tells the truth about the wait instead
of calling it a timeout. `python -m pytest` — 251 green.

---

## BUG-002 — Unverified demonstration mode kept the previous officer's bearer token

Severity: **P0** · Component: apps/web (LoginGate, api.ts) · Status: **FIXED**

Signing in, then falling back to an unverified "demonstration" rank, left the
console displaying `IO · demonstration · unverified` while the API answered as
whichever officer had signed in *previously* — full cross-station scope, unmasked
identities — because the fallback path never cleared `localStorage`'s stored token.
"Unverified" is supposed to mean unauthenticated; instead the frontend and backend
disagreed about who was signed in, and the on-screen note was false.

**Fix:** `enterUnverified()` calls `setToken(null)` before entering demonstration
mode, and the note now says what continuing actually does: *"continuing on one signs
you out, so every record-scoped answer will be refused until the roster loads."*

**Verified:** the API correctly refuses `/cases`, `/fir/1`, `/person/1`, `/copilot/1`
with 401 given no token, a garbage token, or an empty token — which is what makes
clearing the token sufficient. `npx tsc --noEmit` clean.

---

## BUG-003 — /copilot read any case, ignoring the station rule /fir enforces

Severity: **P0** · Component: apps/api/routers/copilot.py,
packages/rag_agent/copilot/brief.py · Status: **FIXED**

An Investigating Officer refused a case by `GET /fir/{id}` (403 — filed at another
station) could still read that same case's entire Copilot brief — narrative,
accused, associates, six named investigative leads — via `GET /copilot/{id}` (200).

**Root cause:** `brief._case()` read the case with a hardcoded scope,
`fir_by_id(fir_id, "SHO", "")`, on the premise "the officer already has it in hand" —
false, since `fir_id` arrives straight from the URL. `generate_copilot_brief` never
received the officer's station and the router never checked one.

**Fix:** `generate_copilot_brief(fir_id, officer_role, officer_ps_code)` applies
`can_view_fir` itself, inside the function that reads the case (so a future caller
can't skip it), raising `NotPermitted` — mapped to the same 403 `/fir` returns, not
404, since an officer is entitled to know the case exists and isn't theirs.

**Verified:** a test asserts 403 from *both* endpoints for the same IO and the same
out-of-station case. `python -m pytest apps/api` green.

---

## BUG-004 — Identity masked on /person was printed in full by /fir and the Copilot

Severity: P1 · Component: apps/api/routers/records.py,
packages/rag_agent/copilot/brief.py, packages/policy · Status: **FIXED**

For the same below-DSP officer, the same person's name was `null` on `/person` but
fully spelled out on `/fir` (`Accused.AccusedName`, `Victim.VictimName` returned raw)
and in Copilot-generated leads/timeline prose. `mask_person_fields` had only ever
been wired into `/person`, despite `records.py`'s own docstring promising
"policy-masked" everywhere. Also found: `_draft_summary` called
`mask_person_fields(role, dict(case))` on a *case* dict, which contains none of the
masked field names — a silent no-op that never actually masked anything.

**Fix:** `policy.mask_person_name(role, name)` — the same rank rule applied to a bare
name, not just a dict — used at all three sites. Below DSP the value becomes
`"[name withheld — rank]"`, not blank, since blank would falsely read as "no name
recorded."

**Verified:** a test confirms a DSP sees the names, an SHO sees the mask on `/fir`,
and none of the DSP-visible names appear anywhere in the SHO's Copilot brief.
`python -m pytest apps/api` green.

---

## BUG-005 — The /alerts WebSocket accepted every connection unauthenticated

Severity: P1 · Component: apps/api/routers/alerts.py · Status: **FIXED (transport
changed to SSE)**

Any client opening a WebSocket to `/alerts`, with no credential of any kind, received
district anomaly alerts — the route called `ws.accept()` with no check at all. A
browser `WebSocket` can't set an `Authorization` header, and a query-string token
would leak officer identity into every access log the connection passes through
(which `lib/api.ts` explicitly avoids elsewhere); the route appears to have been
left open rather than resolved.

**First attempt:** the token as the first frame, verified before streaming — correct
in-process, but live verification hit a wall. A real `websocket-client` and raw curl
with explicit `Upgrade`/`Sec-WebSocket-*` headers both got Starlette's own bare 404
against the deployed AppSail gateway, while an ordinary REST route on the identical
domain returned 401 as expected and CORS middleware visibly processed the request —
evidence the request reaches FastAPI but the AppSail gateway may not proxy WebSocket
upgrades to a custom-runtime app at all.

**Final fix:** rather than keep chasing an unconfirmed platform question, `/alerts`
moved off WebSocket entirely to `GET` + `sse_starlette.EventSourceResponse` — the
transport `/chat` already proves works live on this deployment, authenticated with
the ordinary `Depends(current_officer)` every other route uses. This sidesteps the
WebSocket-proxying question rather than resolving it — that question stays open and
is no longer load-bearing.

**Verified:** `python -m pytest` green (rewritten as plain 401/streaming checks over
GET, no WebSocket transport involved).

---

## BUG-006 — Answers cited records that did not support them

Severity: **P0** · Component: packages/rag_agent (evaluator, orchestrator) ·
Status: **FIXED**

The most consequential finding in the audit — the one that makes the console's
central claim ("every claim carries the record it came from") literally true and
practically false.

An exact FIR lookup (`POST /chat {"query": "What is the status of FIR
100050510202600037?"}`) returned the correct FIR at 0.97 confidence, followed by
five **unrelated cyber-crime cases in a different district, three years earlier**,
each cited as supporting evidence at 0.48–0.49. Every one was a real record; five of
six were about a different crime entirely. The same five-item pad appeared under
**every** intent tested — hotspots, forecast, alias check, person history, causal.

**Root cause, one concept applied inconsistently, in two places:**
1. `RELEVANCE_FLOOR = 0.5` ("below this an item is context, not support") governed
   *whether to answer*, but `node_synthesize` cited the entire ranked batch — floor
   and all — discarding the distinction CRAG exists to draw. Compounding this,
   `RELEVANCE_FLOOR` sat *above* `ACCEPT_THRESHOLD` (0.45), so a batch where **no**
   item cleared the relevance floor could still be accepted on `max(confidence)`.
2. Semantic search ran unconditionally — even behind a successful exact-identifier
   lookup. A FIR number is a yes/no claim about one row; the nearest narratives to
   that row are cases about something else.

**Fix:** `evaluator.supporting(evidence)` is the single definition of "supports an
answer," used by scoring, acceptance, and citation alike.
`InvestigationState.exact_lookup_hit` suppresses semantic search once an exact
record lookup has already answered the question.

**Verified:** 4 new regression tests, including one guarding against
over-correction (a single exact record must still be enough on its own).
`python -m pytest` — 251 green. Not yet re-driven live at time of writing.

---

## BUG-007 — Generic verbs outvoted specific topic words in intent routing

Severity: P1 · Component: packages/rag_agent/intents.py · Status: **FIXED**

"Find cases similar to FIR …" routed to `CRIME_SEARCH` (unrelated person profiles)
instead of `SIMILAR_CASES`, because `CRIME_SEARCH`'s keyword list includes generic
verbs ("show", "list", "find", "cases") present in almost every question in this
domain — flat hit-count scoring let the generic pair beat the one specific word
("similar").

**Fix:** `CRIME_SEARCH` now scores last, as the fallback it actually is — only
winning if nothing more specific scored at all. 9 new test cases, `python -m pytest`
green.

---

## BUG-008 — "How many …" was answered with narratives and never a number

Severity: P1 · Component: packages/rag_agent/orchestrator.py,
packages/rag_agent/agents/sql_agent.py · Status: **FIXED**

`CRIME_SEARCH` had no branch in `_run_specialists`, so every counting question
("How many theft cases are there in Mandya district?") fell through to semantic
search alone and returned five narrative excerpts with no number anywhere.

**Fix:** `sql_agent.count_firs()` — an exact, role/station-scoped count over the same
WHERE clause `search_firs` uses (counted in Python, since ZCQL has no GROUP BY over a
join this deep), plus a crime-type extractor (longest-match against the 20 canonical
types) and an optional district from session focus. The count is emitted as
authoritative evidence with up to 5 matching FIRs as samples; `CRIME_SEARCH` now
settles the turn before vector search runs, since semantic neighbours can only pad a
count, never corroborate it.

**Verified live:** *"How many theft cases are there in Mandya district?"* →
*"73 case(s) Theft in Mandya are recorded within your access scope."*,
`authoritative: true`, vector search explicitly skipped in the trace.
`python -m pytest` green.

---

## BUG-009 — A question about the tool was routed through record retrieval

Severity: P1 · Component: packages/rag_agent (intents, orchestrator) ·
Status: **FIXED**

"what all could you answer" fell to `UNKNOWN`, ran the full retrieval pipeline
(8 profiles fetched and discarded across two widening attempts), and refused with a
generic "check whether the record exists" message — for a question that was never
about records.

**Fix:** a `CAPABILITY` intent, matched by shape before keyword scoring (so "what
**all** could you answer" — a word between the interrogative and auxiliary — still
matches), short-circuits before retrieval and returns one uncited paragraph
describing scope and limits together — there is no record behind a description of a
tool.

**Verified:** 4 new tests, including one guarding against the new intent swallowing
real questions. `python -m pytest` green.

---

## BUG-010 — Five different situations shared one refusal message

Severity: P1 · Component: packages/rag_agent (evaluator, orchestrator) ·
Status: **FIXED**

"who could be the suspect", "Show me the money trail"/"the co-offender network" (no
subject), a nonexistent named person, and a nonexistent FIR number all returned the
identical *"check whether the record exists in the system"* sentence — the wrong
problem named for four of the five, after each had swept the vector index and
thrown the results away. (Refusing "who could be the suspect" is itself correct — the
records hold who was accused/arrested/charged, never who is "the suspect" — the
defect was reporting a correct refusal as a failed lookup.)

**Fix:** `evaluator.REFUSAL_MESSAGES` — one message per situation, tracked via
`InvestigationState.refusal_reason`. `node_retrieve` now short-circuits the three
situations retrieval cannot answer (`CAPABILITY`, `NOT_INFERABLE`, a subject-needing
intent with no subject) **before** running retrieval, instead of sweeping the index
first. None of the messages upgrade "not found in the records" into "does not exist"
— the one message that says a record doesn't exist qualifies it with "within your
access scope."

**Verified:** 4 new tests, including one asserting no refusal message overclaims
non-existence. `python -m pytest` green.

---

## BUG-011 — Vector similarity is displayed to the officer as evidential confidence

Severity: P1 · Component: packages/rag_agent/agents/vector_agent.py,
packages/rag_agent/agents/prediction_agent.py, packages/rag_agent/state.py,
apps/web · Status: **FIXED**

A semantically-similar but substantively unrelated record showed a "fair"
confidence band in the evidence rail: `vector_agent.search` set
`confidence = r["score"]` — raw hybrid dense+BM25 similarity — which then fed three
places that all read it as something else: the CRAG accept/reject decision, citation
ranking, and the console's confidence-band colour. Cosine similarity to a query
string and "how well this record supports this claim" are different quantities —
the same category error the console's colour system separately made for severity vs.
confidence, one layer down.

**Fix:** `EvidenceItem.confidence_kind: Literal["support", "similarity",
"model_estimate"]` — a category, not a calibration — set at the point each kind of
number is produced. Raw vector hits → `"similarity"`; prediction-agent ranking-weight
constants → `"model_estimate"` (the model's own reported score stays in `content`);
exact lookups, graph facts, authoritative findings → default `"support"`. Console:
similarity shows a labeled "% text similarity" chip; model estimates show a plain
"model output" tag with no percentage; support keeps the existing band, relabeled
"evidence strength".

**Verified live**, API and console: a real vector-search hit (a name not on file)
returned `confidence_kind: "similarity"`; a risk-score query returned
`"model_estimate"`; FIR lookups and counts returned `"support"`. Console redeployed
and its bundle grepped directly for the new UI strings. `python -m pytest` green,
`npx tsc --noEmit` clean.

---

## BUG-012 — /health reported an LLM it had never reached

Severity: P1 · Component: packages/rag_agent/llm.py · Status: **FIXED (reporting) —
the actual reachability defect is BUG-021**

`/health` reported `"llm": "quickml (glm-4.7-flash)"` while every answer was the
deterministic extractive fallback. Two compounding causes: `status()` treated
"endpoint URL configured" as equivalent to "working," with no notion of "contacted";
and the real production failure (`_token()` returning `None`, from a bare
`except Exception: return None` swallowing the actual reason) raised
`LLMUnavailable` *directly* instead of going through the normal degrade path, so the
cooldown/status tracking never engaged at all.

**Fix:** the missing-credential raise now degrades normally; `status()` distinguishes
"configured, not yet contacted" from "working." This makes the *report* honest — it
does not fix reachability, which is BUG-021. The deterministic fallback is not a
correctness degradation: every answer it produces is grounded and cited, just less
fluent. `python -m pytest` green.

---

## BUG-013 — A money-trail question was answered with a theft record

Severity: P1 · Component: packages/rag_agent/orchestrator.py · Status: **FIXED**

"Show me the money trail for Usha Naika" returned `visualization: none`, zero
transfer evidence, and cited an unrelated criminal-history record as the answer.
When `graph_agent.money_trail()` found nothing, the branch added no evidence and
said nothing, so semantic search's top (irrelevant) hit filled the gap by default —
the neighbouring `ALIAS_CHECK` branch already solved this correctly with an explicit
"no alias recorded" item; `FINANCIAL` didn't.

**Fix:** an empty money trail now emits its own negative finding: *"No bank account
is linked to this person in the records, and no transfers are traceable to them.
This is an absence in the financial layer, not a finding that no money moved."*
`python -m pytest` green.

---

## BUG-014 — Risk score returns a saturated 1.00

Severity: P2 · Component: packages/ml_models/risk/scoring.py · Status: **FIXED
(reporting) — the underlying saturation is a real data-volume limit, not a defect**

`_risk_model()` returned a raw, uncalibrated `XGBClassifier.predict_proba` — unlike
the neighbouring recidivism model, already isotonic-calibrated. Raw XGBoost margins
are known to saturate near 0/1 on skewed data, which is what a reported 1.00 with no
way to distinguish "very likely" from "confidently confident" looked like.

**Fix:** the same isotonic-calibration pattern the recidivism model uses, adapted to
`cv="prefit"` so TreeSHAP still explains the real fitted booster. `RiskResult.
calibrated: bool` is now honest — if the calibration split lacks enough of both
classes, or isotonic fitting fails, the raw model is used and reported as
`calibrated=False` rather than silently claiming a calibration that didn't happen.

**Verified live:** on the real dataset, the calibration split doesn't have enough
class balance to fit isotonic regression, so the honest fallback correctly fires
(*"a ranking score, not a probability"*), while the companion recidivism score on the
same person calibrated successfully and reported ~100%, correctly labeled. The
saturated 1.00 itself can persist for a genuinely heavy-prior person — what's fixed
is that it's no longer silently presented as a calibrated probability.
`python -m pytest` green.

---

## BUG-015 — The causal layer declines to produce an estimate live

Severity: P2 · Component: packages/ml_models (DoWhy) · Status: **OPEN — a measured,
deliberate budget decision**

Causal questions get an honest, correctly-worded decline rather than a working
estimate, because `dowhy` is not installed in the deployed image, by design (v7
changelog) — this is correct behaviour for an unavailable capability, not a defect.

**Measured, not guessed, whether this could now change:** installing `dowhy==0.14`
in an isolated venv and sizing its dependency closure shows ≈405MB of genuinely new
weight (dominated by `llvmlite`+`numba`, ≈149MB — the same class of dependency
already removed once, when SHAP's numba chain was replaced with xgboost's own
`pred_contribs`). Against the ~0.88GB image and the empirically measured ~1.3GB
bundle-sandbox ceiling, that lands at ≈1.28GB — inside the ceiling on paper, with
essentially no margin against a limit that has already killed two prior deploys
outright.

**Decision: not deployed.** A live "see if it fits" gamble against a working
production deployment was deliberately not attempted. The honest decline remains
correct; the UI must not imply causal inference is operational.

---

## BUG-016 — A Kannada turn takes 13.4s against 0.5s for English

Severity: P2 · Component: data/nlp/translate.py · Status: **PARTIALLY FIXED — one
real bug fixed, one cost is inherent**

Measured breakdown of a Kannada turn: inbound translation 2.1s, retrieval <0.1s,
outbound translation of the answer **10.8s** — most of the total. Kannada works
correctly end to end; this is a latency finding, not a correctness one.

**Real bug found and fixed:** nothing paid the model's ~20–22s cold-load cost
proactively, so it landed on whichever officer's query happened to be first after a
container start — indistinguishable from a hang. `translate.warm()`/`speech.warm()`
now run from the same background startup thread that already fetches the Data Store
mirror and model weights.

**Not a bug, inherent cost:** the 10.8s outbound-translation cost is a *warm* model
translating a long, multi-sentence answer — autoregressive CPU generation time
scales with output length, and NLLB has no GPU here. Not fixable short of a
smaller/faster model or truncating answers before translation.

---

## BUG-017 — The architecture doc claimed model weights had left the image; they hadn't been wired up

Severity: P2 · Component: documentation / deployment configuration ·
Status: **FIXED (documentation + configuration)**

File Store genuinely held the model weights (confirmed by downloading and
inspecting a chunk directly — a standard Hugging Face hub-cache layout), but the
AppSail app had no `VERITAS_MODELS_FOLDER_ID`/`_FILE_IDS`/`HF_HOME` configured, so
`model_fetch.ensure_models()` had never run. Kannada worked live anyway because the
image still baked in a converted CTranslate2 directory at the code's default path —
the architecture the changelog described was real but never connected.

**Fix:** set the three env vars via the configuration API — no code change needed,
`ensure_models()` already worked correctly, it simply had never been invoked. Added
`/health` fields (`model_weights`, `nllb_backend`) so this claim is a live,
checkable fact going forward instead of something inferred from response latency
(which is what produced this bug in the first place).

---

## BUG-018 — PDF export returns HTML

Severity: P2 · Component: apps/api/routers/export.py · Status: **PARTIALLY FIXED —
two real root causes fixed; one platform requirement remains, precisely diagnosed**

The console never lied about this (`exportPdf()` names the file `.html` when the
blob isn't a real PDF), but the architecture doc overstated what actually ran.

**Root causes found and fixed, surfaced in order by adding diagnostic reason
headers:**
1. `app.smartbrowz()` doesn't exist on the SDK — confirmed against the real
   installed package; the correct method is `smart_browz()` (underscore). Fixed.
2. The call built a fresh, unbound `zcatalyst_sdk.initialize()` instead of reusing
   the request's own captured Catalyst context (`data.ds.catalyst_app()`, the
   pattern `/jobs/refresh` already uses). Fixed — this changed the live failure from
   an `AttributeError` to a real Catalyst API error for the first time (`INVALID_ID`:
   "No such User").
3. Tried `_switch_user("admin")` — the exact fix that resolved the identical error
   class for QuickML (BUG-021). Live-tested post-deploy: the identical error
   persists byte-for-byte, ruling the hypothesis out rather than leaving it assumed.
   Data Store/Cache/Graph calls already succeed under that same admin scope, so
   SmartBrowz's API layer appears to need a genuine interactive Catalyst User
   Management identity that a JWT-fallback session (no browser here to complete an
   OAuth sign-in) can never supply.

Two real defects fixed; the console degrades honestly to a clearly-labeled printable
HTML copy. `python -m pytest` green.

---

## BUG-019 — "fir" matches inside "firs", routing a search to the lookup intent

Severity: P3 · Component: packages/rag_agent/intents.py · Status: **FIXED**

`classify("show me murder firs")` matched `FIR_LOOKUP` via a bare substring check
(`"fir" in "firs"`) instead of `CRIME_SEARCH`. Fixed with word-boundary matching
(`\bkeyword\b`), compiled once at import. Test now asserts the correct
classification directly. `python -m pytest` green.

---

### Second deploy — console live, three architectural fixes, live-verified

Commit `71dc2a4`, deployment `52852000000310011`: the console was deployed live for
the first time in this pass, and verified as an artifact — bundle fetched and
grepped for the fix strings, confirmed absent of `localhost:8000`, driven headlessly
over CDP — rather than trusting the deploy command's exit code. Confirmed: the real
6-officer roster renders; a real chat turn shows exactly one citation (BUG-006's fix,
through the browser); BUG-002's fix holds under a genuine simulated network failure
(a seeded stale token is cleared from `localStorage` on entering demonstration mode).
BUG-005's client half could not be verified — the `/alerts` WebSocket appeared
blocked at the AppSail gateway for any client, browser or not.

---

## BUG-020 — The evaluator's relevance floor deleted authoritative refusals (CAUSAL regression)

Severity: P1 · Component: packages/rag_agent (evidence/evaluator.py, state.py,
agents/prediction_agent.py) · Status: **FIXED, live-verified**

Introduced by BUG-006's own fix, in the same session: "Why does crime correlate with
literacy?" lost its honest "cannot be produced" decline and answered instead from
five unrelated criminal profiles. `prediction_agent.causal()` signals its decline
with `confidence=0.0` by convention ("not applicable," not "weak") — which
`RELEVANCE_FLOOR` can't distinguish from genuinely weak evidence, so the decline was
dropped while five vector hits that happened to clear 0.5 became the whole answer.

**Fix:** `EvidenceItem.authoritative: bool`, orthogonal to confidence —
`supporting()` keeps an authoritative item regardless of its confidence value, and
`evaluate()` accepts one immediately rather than widening first. Applied to the
causal decline and, for consistency, to the ALIAS_CHECK/FINANCIAL negative findings
that had previously survived the floor only by luck (a manually-chosen high
confidence value).

**Verified live:** the causal question now returns exactly one citation, the honest
decline, no padding. `python -m pytest` green throughout.

---

## BUG-021 — QuickML `_token()` called a method that does not exist on the SDK

Severity: P1 · Component: packages/rag_agent/llm.py · Status: **FIXED
(authentication) — see BUG-022 for what surfaced next**

`/health` claimed QuickML was serving while every answer was extractive (BUG-012's
reporting symptom; this is its actual root cause). `catalyst_app()._app._credential.
get_token()` — confirmed by extracting and reading the real installed
`zcatalyst-sdk` 1.4.0 source directly: `initialize()` returns the `CatalystApp`
object with no `._app` wrapper, and credential objects expose `.token()`, never
`.get_token()`. Every call raised `AttributeError`, silently swallowed by a bare
`except Exception: return None` — the LLM had never once been successfully
reachable, in any environment, independent of AppSail.

**Fix:** call `credential.token()` — the same call the SDK's own internal HTTP
client makes — dispatched by credential type, after `_switch_user("admin")`,
matching the scope Data Store calls already run under (there is no per-officer token
to call an LLM with).

**Verified live:** the failure mode changed from an internal `AttributeError` to a
real HTTP response from QuickML's own gateway — proof the credential now resolves
correctly (see BUG-022 for what that response means).

---

## BUG-022 — QuickML's gateway rejects the request body/route, independent of auth

Severity: P2 · Component: packages/rag_agent/llm.py (QUICKML_ENDPOINT), external
(Zoho QuickML gateway) · Status: **OPEN at time of writing — narrowed to a specific,
named requirement** *(resolved in a later pass — QuickML is active in production per
CLAUDE.md v17)*

With BUG-021 fixed, every LLM call reached QuickML and was rejected with
`PATTERN_NOT_MATCHED` / "Error in processing `zoho-inputstream` parameter" —
identical regardless of request body content or added headers, tried directly
against the live endpoint with a separately-valid OAuth token to isolate this from
the credential fix.

**Ruled out:** not a credential problem (a valid token gets a service-level response,
not 401/403); not the request body shape; no documented header matched
`zoho-inputstream`.

**Narrowed:** Zoho's documented "pipeline endpoints" surface (the nearest analogue)
requires a per-endpoint `X-QUICKML-ENDPOINT-KEY` header obtained only from that
model's own console popup — unreachable over the Admin API this project provisions
with — and the configured `QUICKML_ENDPOINT` URL has no recorded provenance as
having come from that popup.

**Fix applied without resolving the bug:** the header is now sent whenever
`QUICKML_ENDPOINT_KEY` is configured, so the fix takes effect the moment someone
copies the real key from the console, with no further code change. Not affected by
this gap: the system's behaviour when QuickML is unreachable is fully correct —
`/health` reports the real error, and every chat turn still produces a grounded,
cited, extractive answer regardless.

---

## BUG-023 — Every FIR narrative for a given crime type is the same template

Severity: **P1** · Component: data/data/generator/build.py, narrative_backfill.py
(new), packages/rag_agent/rag_agent/copilot/brief.py · Status: **FIXED, verified
live**

Sampling 60 cases each of Theft, Hurt, Cyber Crime, and Robbery, every case of the
same crime type reduced to the exact same sentence once date and district were
normalized out — the generator's `_MO` dictionary had exactly one modus-operandi
sentence per crime type, covering only 8 of 20 crime types. **Not a data-integrity
bug** — every FIR is a real, distinct row (different case id, accused, victims,
coordinates); only the one free-text narrative field carried no case-specific
signal. Confirmed NOT to affect KDE/DBSCAN hotspots, Prophet/MinT forecasts, risk
scoring, or the graph/financial layers, none of which depend on narrative text.

**Consequence:** false similarity in `SIMILAR_CASES`/Copilot (unrelated cases scored
as "similar" purely because their narratives were identical templates), and
semantic-search "corroboration" that was frequently just near-duplicate boilerplate.

**Fix:** `_MO_VARIANTS` widens coverage to all 20 crime types with 3 variants each;
`_narrative()` derives real time-of-day and offender-count detail from each case's
own already-generated facts. Since the rest of the dataset was already correct, a
full regeneration was avoided — `narrative_backfill.py` deterministically recomputes
only `CaseMaster.BriefFacts` in place for the live dataset, run via `POST
/jobs/regenerate_narratives` inside AppSail (the SDK only authenticates from a real
request context). Copilot cross-case similarity now explains itself structurally
(shared crime type, IPC sections, district, MO clause) instead of exposing a bare
embedding score.

**Verified live:** previously-identical narratives now read with real per-case
detail; a 5-case Mandya theft sample returned 5 genuinely distinct narratives;
Copilot similar-cases shows an itemized explanation per match. `python -m pytest`
green, `npx tsc --noEmit` clean.

---

## BUG-024 — `POST /jobs/refresh` fails with a 500 against the live dataset

Severity: **P1** · Component: apps/api/routers/jobs.py, data/gds.py,
data/embeddings/index_job.py · Status: **FIXED, deployed, live-verified**

The scheduled graph/vector recompute job — 6-hourly, per Cron — failed with a
plain-text 500 in ~16s both times it was manually triggered against the full live
dataset. `/jobs/audit-verify`, tested with the identical token/header immediately
before and after, worked correctly both times, ruling out auth or the job-endpoint
mechanism generally.

**Investigated but not conclusively isolated** (no server log access was
available): local timing at production scale showed PageRank+Louvain+pivot-sampled
betweenness alone could take up to 179s on the *full* graph, but the pipeline
actually runs on the much smaller person-only co-offending projection (~7,000
nodes), where the same three algorithms together took only ~8s — arguing the ~16s
failure more likely belongs to one of the pipeline's other steps (bulk `vx_person`
row updates, or the 13,835+-document vector reindex), neither of which was timed
directly.

**Fix:** the recompute moves to a background thread (the pattern the AppSail
warm-up already uses), returning `{"status": "started"}` immediately; a
non-reentrant guard reports `{"status": "already_running"}` rather than overlapping
runs.

**Verified live**, letting the real job run to genuine completion: confirmed
`already_running` at the 2-minute mark, finished by 5-6 minutes — independent
confirmation the original job could never have completed inside any synchronous
HTTP timeout. `/health` afterward showed unchanged FIR/graph counts and a genuinely
changed (not cached) indexed-document count, with no regression on a known-good
query. Not verified at the time: whether Cron's own schedule actually invokes this
endpoint (tracked as DEP-12, resolved by BUG-025).

---

## BUG-025 — Both Catalyst Cron jobs had never once succeeded (DEP-12, resolved)

Severity: **P1** · Component: Catalyst Cron configuration (not application code) ·
Status: **FIXED, verified live**

Following up on BUG-024's own "unobserved" note, listing the live Cron jobs directly
showed both `veritas_refresh` and `veritas_audit_verify` at `success_count: 0,
failure_count: 20` since creation, and both disabled — despite CLAUDE.md documenting
them as running every 6h/12h.

**Root cause, two stacked defects:** (1) the configured job URL used the **org id**
instead of the AppSail app's own numeric id — almost certainly never resolved to the
deployed app at all; (2) after fixing that, the configured job token predated the
current `VERITAS_JOB_TOKEN` (rotated since the jobs were created) and no longer
matched. Either alone would fail every invocation, exactly what 20/20 showed.

**Fix:** corrected via `PUT /project/{id}/cron/{jobId}` — hostname, current token,
re-enabled. Not a code change; the job endpoints themselves were already correct.

**Verified live:** both endpoints called exactly as the corrected Cron config now
would, both succeeded for real. Not verified at the time: the schedule itself firing
unattended (followed up by BUG-027).

---

## BUG-026 — Copilot leads render a canonical name with no link to the as-filed name

Severity: P2 · Component: apps/web, packages/rag_agent/copilot · Status: **OPEN at
time of writing** *(closed — see CLAUDE.md v19)*

Found live via CDP: a case's own accused list shows the as-filed name ("Suma
Nadkarni") while the same case's Copilot leads name the identical `PersonUID` by its
resolved canonical name ("Soom Nadkarni") — a genuine romanisation-variant case
(exactly what entity resolution exists to catch), with nothing on screen linking the
two. Confirmed via `/fir` and `/person` that resolution itself is correct; the UI
simply never cross-referenced the two names it already had in scope.

---

## BUG-027 — `/jobs/audit-verify` still failed every unattended Cron fire after BUG-025

Severity: **P1** · Component: apps/api/routers/jobs.py · Status: **FIXED, deployed,
live-verified**

Rather than trust BUG-025's own fix, listing the live jobs again showed
`veritas_refresh` with a real success (0→1) while `veritas_audit_verify` had logged
one *more* failure than before.

**Root cause:** `/jobs/audit-verify` ran `verify_chain()` — a `ds.query()` —
synchronously before responding, which is exactly the call that pays BUG-001's
~23s cold-container mirror-hydration cost, inside a request Cron abandons long
before that finishes. `/jobs/refresh` never touches the data layer before
responding, which is why it alone survived a cold fire. This stayed invisible to
manual testing because a manual curl always hits an already-warm container from
prior checks in the same session.

**Fix:** the same background-thread pattern as BUG-024, plus a `sync=true` query
param that preserves the original blocking response for a human running the check
by hand — the exact mode every manual verification in this document had used, and
exactly why the bug hid from all of them.

**Verified live post-deploy:** default call returns `{"status":"started"}` in 0.2s
against a cold container; `sync=true` still returns the real intact/broken result.
Not confirmed at the time: the next unattended scheduled fire actually incrementing
`success_count`. `python -m pytest` — 256 total, green.

---

## BUG-028 — "Does X have priors?" rendered "crime type not recorded" for every case

Severity: **P0** · Component: packages/rag_agent/rag_agent/agents/sql_agent.py ·
Status: **FIXED, deployed, live-verified**

Found live while testing multi-turn pronoun resolution with a fresh pronoun. The
flagship reason identity resolution exists at all (CLAUDE.md §0) was silently
degraded in production: every case in the answer read *"crime type not recorded...
status not recorded"* — even though `GET /cases` confirms the same FIR has real
crime-type, status, district, and narrative data. The data was never missing; this
one code path never fetched it.

**Root cause:** `sql_agent.person_record()` ran the full-detail `_case()` formatter
over rows from `queries.cases_for_person()`, which selects only raw foreign-key ids
(no names) because that query's own join already spends 3 of ZCQL's 4-JOIN cap,
leaving no room for the joins `_case()` needs. No prior test caught this because
every `PERSON_HISTORY` test asserted intent routing, never answer content.

**Fix:** a new `cases_by_ids()` chains a second, separately-budgeted query reusing
the already-correct, fully-joined select `fir_by_id`/`fir_by_number` use, instead of
asking one query to exceed the join cap.

**Verified live:** the exact previously-broken query now returns full crime type,
district, status, and narrative for all of a real person's cases. `python -m pytest`
— 317 collected, green.

---

## BUG-029 — Session focus resolved during retrieval was never persisted for the next turn

Severity: **P0** · Component: packages/rag_agent/rag_agent/orchestrator.py ·
Status: **FIXED, deployed, live-verified** — the single highest-value fix in the
conversational-architecture pass

Found while building the first case-scoped follow-up and testing the real sequence:
"What is the status of FIR X?" then, one turn later, "What happened?" — which should
have stayed on the same case, and didn't; the second turn saw `active_fir: None`.

**Root cause:** `node_orchestrate` persists session focus once, early, right after
pronoun/entity resolution — but `FIR_LOOKUP`'s own resolution of `active_fir`
happens later, inside `node_retrieve`, as an in-memory-only assignment with no
corresponding write to storage. `node_orchestrate`'s one save had already run and
returned before that assignment ever happened. This predates every conversational
intent built on top of it and would have silently undercut any future case-scoped
follow-up. No prior test caught it because existing tests read the in-memory state
object directly, never simulating a second turn reading focus back from storage.

**Fix:** `node_retrieve` now persists session focus a second time, at the very end,
after all of HippoRAG/specialists/ToG have run — capturing whatever retrieval
itself additionally resolved on top of what orchestration already saved.

**Verified live:** the exact broken sequence now correctly stays on the same case,
re-confirmed through the real console over CDP. `python -m pytest` — 352 collected,
green.

---

## BUG-030 — A surname outside the name-pool sample was clipped off a known first name, resolving to a different person

Severity: **P0** · Component: data/data/nlp/entities.py · Status: **FIXED,
deployed, live-verified**

Found by literally copying the system's own previous answer back into the next
query — "Tell me more about Usha Naika," after the system itself had just named her
as one of two accused. The system silently answered about "Usha Pujari" instead — an
entirely different, more-documented person — at 0.95 confidence, with nothing on
screen indicating a substitution.

**Root cause:** the NER span-extraction logic builds a name span from the *first* to
the *last* token matching a 271-entry name-pool sample; "Usha" is in the pool,
"Naika" is not, so the span collapsed to "Usha" alone — and everything downstream
then correctly (and honestly) resolved "Usha" to whichever person by that truncated
name had the most records. The ambiguous-name safeguard added earlier in the same
pass never got a chance to run, because the query it saw was simply wrong, not
ambiguous. (A naive "span the whole capitalized group" fix was tried and rejected —
it would have broken the working case of "Was Ramesh Gowda", where "Was" is
capitalized only because it starts the sentence.)

**Fix:** extend the span outward from the pool-matched core one adjacent token at a
time in each direction, stopping only at a known query stopword or place name —
preserving "Was Ramesh Gowda" while correctly extending "Usha" to "Usha Naika".

**Verified live:** the identical query now resolves to the correct person and
answers about her, cited first. `python -m pytest` — 352 collected, green.

---

## BUG-031 — "previous cases" (plural) never matched PERSON_HISTORY

Severity: P2 · Component: packages/rag_agent/rag_agent/intents.py ·
Status: **FIXED, deployed, live-verified**

Same word-boundary-keyword class as BUG-019: the keyword list had "previous case"
(singular) only, so the fixed word-boundary regex correctly failed to match the
plural, and "What previous cases involve her?" fell to `CRIME_SEARCH` — a global
10,000-case count disconnected from the person a prior pronoun had just resolved.

**Fix:** added "previous cases" as a second literal keyword.

**Verified live:** the identical query now classifies `PERSON_HISTORY` and returns
the named person's own case history.

---

## Summary

| ID | Severity | Status |
|----|----------|--------|
| BUG-001 cold start / roster timeout | P1 | FIXED — duration measured live: ~23s, once per container |
| BUG-002 stale token in unverified mode | **P0** | FIXED, verified live in the browser |
| BUG-003 /copilot authorization bypass | **P0** | FIXED, verified live |
| BUG-004 masking not applied on /fir and Copilot | P1 | FIXED, verified live |
| BUG-005 unauthenticated /alerts WebSocket | P1 | FIXED — WebSocket replaced with SSE, live-verified |
| BUG-006 unsupporting citations | **P0** | FIXED, verified in API and browser |
| BUG-007 intent misrouting | P1 | FIXED |
| BUG-008 no count for "how many" | P1 | FIXED, verified live |
| BUG-009 capability question through retrieval | P1 | FIXED, verified live |
| BUG-010 one refusal message for five situations | P1 | FIXED, verified live |
| BUG-011 similarity shown as confidence | P1 | FIXED, verified live |
| BUG-012 /health reported an unreached LLM | P1 | FIXED (reporting) — reachability fixed by BUG-021 |
| BUG-013 money trail answered from a theft record | P1 | FIXED, verified live |
| BUG-014 saturated risk score | P2 | FIXED (reporting) — saturation itself is a data-volume limit, not a defect |
| BUG-015 causal layer declines live | P2 | OPEN — measured: `dowhy` costs ≈405MB against ≈420MB headroom; deliberately not deployed |
| BUG-016 Kannada latency | P2 | PARTIALLY FIXED — cold-start cost fixed; long-answer translation time is inherent |
| BUG-017 changelog vs deployed weights | P2 | FIXED, verified live — `/health` now reports real weight provenance |
| BUG-018 PDF export returns HTML | P2 | PARTIALLY FIXED — 2 root causes fixed; a Catalyst User Management identity requirement remains, needing an interactive sign-in |
| BUG-019 "fir" matches "firs" | P3 | FIXED, verified |
| BUG-020 evaluator floor deleted authoritative refusals | P1 | FIXED, verified live |
| BUG-021 QuickML credential call never worked | P1 | FIXED, verified live |
| BUG-022 QuickML gateway rejects the request shape | P2 | OPEN at the time — narrowed to a console-only endpoint key; resolved in a later pass |
| BUG-023 every narrative for a crime type is one template | **P1** | FIXED, verified live — 20/20 crime types, live backfill |
| BUG-024 `/jobs/refresh` 500s against the live dataset | **P1** | FIXED, deployed, live-verified |
| BUG-025 both Catalyst Cron jobs had never once succeeded | **P1** | FIXED, verified live |
| BUG-026 Copilot leads render canonical name with no link to as-filed name | P2 | OPEN at the time — closed later (CLAUDE.md v19) |
| BUG-027 `/jobs/audit-verify` still failed every unattended Cron fire | **P1** | FIXED, deployed, live-verified |
| BUG-028 "does X have priors" rendered "crime type not recorded" | **P0** | FIXED, deployed, live-verified |
| BUG-029 session focus resolved during retrieval was never persisted | **P0** | FIXED, deployed, live-verified — the highest-value fix in its pass |
| BUG-030 surname outside the NER name-pool clipped off a known first name | **P0** | FIXED, deployed, live-verified |
| BUG-031 "previous cases" (plural) never matched PERSON_HISTORY | P2 | FIXED, deployed, live-verified |

**6 P0, 17 P1, 8 P2, 1 P3 across 31 tracked defects.**

### One thing this audit got wrong, recorded deliberately

The first duplication hypothesis was wrong. `vx_graph_edge` holds 12
apparently-duplicate `TRANSFERRED_TO` rows; they are **one row per transaction**
between the same account pair (`acct:13 → acct:10` twice = two separate TxnIDs,
separate EdgeIDs, separate amounts). `load_graph()` builds a `MultiDiGraph`, so they
survive correctly — a `DiGraph` would have silently kept the last one and deleted
money from the trail. A blanket `DISTINCT` would have destroyed real data. The 12
reciprocal transfer edges are likewise 6 pairs of accounts that genuinely pay each
other — directed is not antisymmetric. Both are now asserted correctly in
`data/tests/test_integrity.py`, with the reasoning written down so it isn't
re-derived from a failing test.
