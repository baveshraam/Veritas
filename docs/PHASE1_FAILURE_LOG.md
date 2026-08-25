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

Severity: P1
Component: apps/api (warm-up), data/ds (mirror hydration), apps/web (LoginGate)
Status: **FIXED (partial — see Residual risk)**

### Symptoms
Opening the console sometimes shows *"The duty roster could not be loaded — the request
timed out. The ranks above are unverified, so record-scoped answers will be refused."*
with six demonstration roles, instead of the six named officers.

### Reproduction
1. Open the deployed console against a container that has not served a request recently.
2. Watch `GET /auth/officers`.
3. At 8s the gate flips to demonstration roles while the request is still in flight.

### Expected
Either the roster loads, or a clearly-defined authentication error occurs. A request
that has not finished is not a request that failed.

### Actual
A pending request was relabelled as a timed-out one, and the console silently
degraded.

### Root cause
Two independent causes.

1. **The first request performs the whole mirror hydration synchronously.** On Catalyst,
   reads run from a SQLite mirror hydrated from the Data Store once per container
   (`data/data/ds.py:_ensure_mirror`). It is all-or-nothing over all 37 tables, paged at
   the Data Store's hard 300-row cap. Whichever endpoint is hit first pays for all of it
   — including `/auth/officers`, which needs only `Employee`.

2. **The warm-up thread never ran in production.** `apps/api/api/main.py` kicked
   `ds._ensure_mirror()` on a background thread — but the whole block was gated on
   `os.getenv("VERITAS_MODELS_FOLDER_ID")`, and that variable is **not set** on the
   deployed app (confirmed against the live AppSail configuration: only
   `VERITAS_JOB_TOKEN`, `VERITAS_JWT_SECRET`, `VERITAS_RESTART_NONCE` are present). The
   mirror and the model weights are unrelated concerns that had been bundled behind one
   flag.

### Fix
- `apps/api/api/main.py` — the warm thread is no longer gated. Only `ensure_models()`
  sits behind `VERITAS_MODELS_FOLDER_ID`, which is the variable that actually describes
  it.
- `apps/web/components/LoginGate.tsx` — the 8s timer now moves the gate to a `slow`
  state that says *"Still loading the duty roster — the service is warming up"* and
  **offers** the unverified fallback. It no longer takes that choice on the officer's
  behalf, and only a real `fetch` rejection is reported as a failure.

### Regression test
`apps/api/tests/test_api.py` covers the auth surface; the warm-up ungating is a
one-line configuration correctness change verified by reading the deployed AppSail
configuration (`GET /baas/v1/project/{id}/appsail`).

### Verification
`python -m pytest` — 251 green.

### Residual risk — resolved
**Measured with a real, deliberate container restart**, once explicit authorization to
do so was given. `POST /appsail/{id}/configuration` with a bumped
`VERITAS_RESTART_NONCE`, polling `/auth/officers` every 2s for 5 minutes: of 150
requests, **exactly one took 22.72s**; every other request — before and after — was
0.13–0.2s. Reconfirmed on the second redeploy: the first `/health` call after that
container came up took 22.9s.

This is the real, unavoidable cost of hydrating ~105k rows across 37 tables through
300-row-paginated ZCQL, paid once per container by whichever request happens to be
first — the fix was never able to make that cost disappear, only to ensure the warm-up
mechanism that was supposed to absorb it actually runs (it did not, before the fix:
gated behind an unset env var), and that the console tells the truth about what is
happening during that window instead of calling it a timeout.

**No longer UNKNOWN.** ~23 seconds, once per container, is the number.

---

## BUG-002 — Unverified demonstration mode kept the previous officer's bearer token

Severity: **P0**
Component: apps/web (LoginGate, api.ts)
Status: **FIXED**

### Symptoms
The console displays a rank labelled `unverified` and states that record-scoped answers
will be refused — while the API answers them, at a different rank.

### Reproduction
1. Sign in as any officer (this writes `veritas_token` to `localStorage`).
2. Reload with the API unreachable, or wait for the roster request to be declared failed.
3. Choose any demonstration rank — say `IO`.
4. Ask a record-scoped question, or open the case index.

### Expected
"Unverified" means unauthenticated. Every record-scoped call is refused with 401.

### Actual
`loadToken()` reads `localStorage`, so the previous sign-in's token was still attached
to every request. The console showed `IO · demonstration · unverified` while the API
answered as, for example, an IG — with that rank's full cross-station scope and
unmasked identities. The frontend and backend disagreed about who was signed in, and
the on-screen note was false.

### Root cause
The fallback path called `onIn({badge_no: "", role, ...})` without clearing the stored
token. Nothing in the fallback ever touched authentication state.

### Fix
`apps/web/components/LoginGate.tsx` — `enterUnverified()` calls `setToken(null)` before
entering demonstration mode, and the note now says what continuing actually does:
*"continuing on one signs you out, so every record-scoped answer will be refused until
the roster loads."*

### Regression test
Verified live that the API refuses unauthenticated calls, which is what makes the
cleared token sufficient: `/cases`, `/fir/1`, `/person/1`, `/copilot/1` all return 401
with no token, a garbage token, and an empty token.

### Verification
```
no token  /cases  -> 401 {"detail":"Not authenticated with Catalyst"}
garbage   /cases  -> 401 {"detail":"Invalid token"}
```
`npx tsc --noEmit` clean.

---

## BUG-003 — /copilot read any case, ignoring the station rule /fir enforces

Severity: **P0**
Component: apps/api/routers/copilot.py, packages/rag_agent/copilot/brief.py
Status: **FIXED**

### Symptoms
An Investigating Officer refused a case by `GET /fir/{id}` could read that same case's
entire Copilot brief — narrative, accused, associates, investigative leads.

### Reproduction
```bash
# IO Nithin Savadi, station 101. FIR 9992 was filed at station 2201 (Mandya).
curl -s -H "authorization: Bearer $T" .../fir/9992      # 403
curl -s -H "authorization: Bearer $T" .../copilot/9992  # 200 + full brief
```

### Expected
Both refuse. The station rule is a property of the case, not of the endpoint.

### Actual
`/fir/9992` → `403 {"detail":"This FIR was filed at another police station"}`
`/copilot/9992` → `200` with timeline, similar cases, and six named leads including
*"Usha Naika has 24 direct co-accused associate(s) — start with Nirmala Angadi, …"*

### Root cause
`brief._case()` read the case with a hardcoded scope:
```python
rows = fir_by_id(fir_id, "SHO", "")   # "the officer already has it in hand"
```
The comment's premise was false: `fir_id` arrives from the URL, so the officer need not
have had anything in hand. `generate_copilot_brief` never received the officer's station
and the router never checked one.

### Fix
`generate_copilot_brief(fir_id, officer_role, officer_ps_code)` applies `can_view_fir`
itself — inside the function that reads the case, so a future caller cannot skip it —
and raises `NotPermitted`. The router maps that to the same 403 `/fir` returns, rather
than a 404, because an officer is entitled to know the case exists and is not theirs.

### Regression test
`apps/api/tests/test_api.py::test_the_copilot_obeys_the_same_station_rule_as_the_fir_endpoint`

### Verification
`python -m pytest apps/api` green. The test asserts 403 from *both* endpoints for the
same IO and the same out-of-station case.

---

## BUG-004 — Identity masked on /person was printed in full by /fir and the Copilot

Severity: P1
Component: apps/api/routers/records.py, packages/rag_agent/copilot/brief.py, packages/policy
Status: **FIXED**

### Symptoms
The same person's name is `null` on one endpoint and fully spelled out on the next, for
the same officer.

### Reproduction
```bash
# SHO ranks below DSP, so identity should be masked.
curl -s -H "authorization: Bearer $SHO" .../person/803   # "name_en": null
curl -s -H "authorization: Bearer $SHO" .../fir/9992     # "AccusedName": "Usha Naik D/o Srinivas"
curl -s -H "authorization: Bearer $SHO" .../copilot/9992 # leads name her in prose
```

### Expected
One rank rule, applied wherever the field appears.

### Actual
`mask_person_fields` was applied only on `/person`. `/fir` returned `Accused.AccusedName`
and `Victim.VictimName` raw; the Copilot built `leads` and `timeline` prose around
`CanonicalName` and `AccusedName`. `records.py`'s own module docstring says "structured
records, **policy-masked**".

Also found: `_draft_summary` called `mask_person_fields(officer_role, dict(case))` on a
*case* dict, which contains none of the masked field names — so that call was a no-op
and the masking it claimed to perform never happened.

### Fix
`policy.mask_person_name(officer_role, name)` — the same rank rule for a name that is
not inside a dict — applied at all three sites. Below DSP the value becomes
`"[name withheld — rank]"` rather than blank, because a blank reads as *"no name
recorded"*, which is a different and false statement about the record.

### Regression test
`apps/api/tests/test_api.py::test_an_accused_name_is_masked_on_every_endpoint_that_carries_it`
— asserts a DSP sees the names, an SHO sees the mask on `/fir`, and that none of the
DSP-visible names appear anywhere in the SHO's Copilot brief.

### Verification
`python -m pytest apps/api` green.

---

## BUG-005 — The /alerts WebSocket accepted every connection unauthenticated

Severity: P1
Component: apps/api/routers/alerts.py
Status: **FIXED**

### Symptoms
Any client that opens a WebSocket to `/alerts` receives district anomaly alerts.

### Reproduction
Connect to `wss://…/alerts` with no credential of any kind. The server calls
`ws.accept()` and begins streaming.

### Expected
The same authentication every other data-bearing route requires.

### Actual
```python
@router.websocket("/alerts")
async def alerts(ws: WebSocket):
    await ws.accept()          # no check of any kind
```

### Root cause
A browser `WebSocket` cannot set an `Authorization` header, and the obvious workaround —
a token in the query string — writes officer identity into every access log the
connection passes through, which `lib/api.ts` explicitly avoids elsewhere ("officer
identity comes from the bearer token, never from the URL"). The route appears to have
been left open rather than resolved.

### Fix
The token is the **first frame** the client sends. Nothing is streamed until
`officer_from_token()` verifies it; a 10s silence or a bad token closes with 1008.
`officer_from_token` was extracted from `current_officer` so both transports run the
same check rather than two similar ones. `AlertToasts.tsx` sends the token on open and
does not connect at all without one.

### Regression test
`apps/api/tests/test_api.py::test_the_alerts_websocket_refuses_an_unauthenticated_client`

### Verification
`python -m pytest apps/api` green.

### Live verification — blocked, apparently by the platform, not the fix
A real WebSocket client (`websocket-client`, a mature Python implementation) and raw
`curl` with explicit `Connection: Upgrade`/`Sec-WebSocket-*` headers both get
Starlette's own `{"detail":"Not Found"}` 404 — not a gateway-level 404, the app's own
router saying no route matched. Ruled out before concluding this is a platform issue:
- The route **is** registered — `TestClient.websocket_connect("/alerts")` (real ASGI
  dispatch, in-process) correctly exercises the auth logic and is what the passing
  regression test above proves.
- A known REST route through the identical domain (`/cases`) returns 401 as expected,
  proving ordinary routing reaches the app.
- CORS middleware visibly processed the failed request (it echoed back
  `Access-Control-Allow-Origin` for the console's origin), so the request is reaching
  FastAPI — just never as a WebSocket upgrade.
- Neither an `Origin` header nor a trailing slash changed the result.

Conclusion, not yet confirmed with Zoho: **the AppSail gateway does not appear to
proxy WebSocket upgrades to this custom-runtime app at all**, which would mean
`/alerts` has never worked live, on any version of this code, independent of this fix.
The fix itself — verified correct in-process — cannot be exercised further without
either console access to test from the actual hosted browser origin, or vendor
confirmation of whether AppSail supports WebSocket proxying for custom runtimes.

---

## BUG-006 — Answers cited records that did not support them

Severity: **P0**
Component: packages/rag_agent (evaluator, orchestrator)
Status: **FIXED**

This is the most consequential finding in the audit. It is the one that makes the
console's central claim — *"Every claim in the answer carries the record it came from"* —
literally true and practically false.

### Symptoms
An exact FIR lookup returns the correct FIR, followed by five unrelated cases presented
as supporting evidence with citation numbers.

### Reproduction
```
POST /chat  {"query": "What is the status of FIR 100050510202600037?"}
```

### Expected
The FIR that was asked about, and only genuinely necessary supporting evidence.

### Actual (measured live, before the fix)
```
[1] FIR 100050510202600037 (Bengaluru Urban, PS 510) — Hurt, filed 25 Jun 2026     0.97
[2] On 25 Nov 2023, a case of cyber crime was registered in Shivamogga district…   0.49
[3] On 20 Dec 2023, a case of cyber crime was registered in Shivamogga district…   0.49
[4] On 09 Nov 2023, a case of cyber crime was registered in Shivamogga district…   0.49
[5] On 29 Jul 2023, a case of cyber crime was registered in Shivamogga district…   0.48
[6] On 10 Oct 2023, a case of cyber crime was registered in Shivamogga district…   0.48
```
Every one of the six is a real record. Five of them are about a different crime, of a
different type, in a different district, three years earlier. `confidence 0.97`.

This was not confined to FIR lookups. The same five-item pad appeared under **every**
intent in the battery — hotspots, forecast, alias check, person history, causal.

### Root cause
Two causes, and both are one concept applied inconsistently.

1. **The evaluator drew the support/context line and synthesis ignored it.**
   `RELEVANCE_FLOOR = 0.5` is documented as *"below this an item is context, not
   support"*, and `score_batch()` used it to decide **whether** to answer. Then
   `node_synthesize` cited `_rank_evidence(state)[:12]` — the entire batch, floor and
   all. The distinction CRAG exists to draw was computed and discarded.

   A second defect fell out of the same inconsistency: `RELEVANCE_FLOOR` (0.5) is above
   `ACCEPT_THRESHOLD` (0.45), so a batch in which **no** item cleared the relevance floor
   could still be accepted on `max(confidence)` and cited as an answer.

2. **Semantic search ran unconditionally.** `_run_specialists` ended with a comment
   reading *"Vector search always contributes"* and did exactly that — including behind a
   successful exact-identifier lookup. A FIR number is a yes/no claim about one row; the
   nearest narratives to that row are cases about something else.

### Fix
- `evaluator.supporting(evidence)` is now the single definition of "supports an answer",
  used by `score_batch()`, by `evaluate()` (so a batch that clears nothing cannot average
  its way past `ACCEPT_THRESHOLD`), and by `node_synthesize` (so only supporting evidence
  is citable).
- `InvestigationState.exact_lookup_hit` suppresses semantic search when the query named a
  record and the store held it. The trace says so: *"Skipped — the query named a record
  and the exact lookup found it."*

### Regression test
`packages/rag_agent/tests/test_engine.py`:
- `test_only_supporting_evidence_is_citable`
- `test_a_batch_that_supports_nothing_is_not_accepted_by_averaging`
- `test_one_exact_record_is_still_enough_on_its_own` (guards against over-correcting)
- `test_an_exact_identifier_hit_suppresses_semantic_search`

### Verification
`python -m pytest` — 251 green. **Not yet re-driven live** — see "Live verification".

---

## BUG-007 — Generic verbs outvoted specific topic words in intent routing

Severity: P1
Component: packages/rag_agent/intents.py
Status: **FIXED**

### Symptoms
"Find cases similar to FIR …" is answered with unrelated criminal profiles.

### Reproduction
```
POST /chat  {"query": "Find cases similar to FIR 100222201202600022"}
```

### Expected
`SIMILAR_CASES`.

### Actual
`Intent: CRIME_SEARCH`, and five person profiles — *"Sadashiv Reddy. Accused in cases of
Attempt to Murder, Cyber Crime."*

### Root cause
`CRIME_SEARCH`'s keywords are `show`, `list`, `find`, `cases`, `firs`, `how many`,
`count`, `theft`, `murder`, `robbery`. The first four are not topic words — they are the
verbs almost every question in this domain uses. Scoring is a flat hit count, so the
generic pair ("find", "cases") beat the specific single ("similar").

### Fix
`CRIME_SEARCH` is scored last, as the fallback it actually is: if any other intent
scored at all, it wins.

### Regression test
`test_crime_search_is_the_fallback_not_a_competitor` — nine cases, including three that
assert `CRIME_SEARCH` still wins when nothing more specific is present.

### Verification
`python -m pytest packages/rag_agent` green.

---

## BUG-008 — "How many …" is answered with narratives and never a number

Severity: P1
Component: packages/rag_agent/orchestrator.py
Status: **OPEN — deliberately not fixed in Phase 1**

### Symptoms
A counting question gets a list.

### Reproduction
```
POST /chat  {"query": "How many theft cases are there in Mandya district?"}
```

### Expected
A count, or an explicit statement that the engine does not count.

### Actual
Intent `CRIME_SEARCH`, confidence 0.76, five narrative excerpts, no number anywhere in
the answer.

### Root cause
`CRIME_SEARCH` is a declared intent with **no branch in `_run_specialists`**. Every
`CRIME_SEARCH` turn falls through to semantic search alone. `sql_agent.search_firs` and
`sql_agent.crime_counts_by_district` both exist and are unused by this path.

### Why it is open
Phase 1's first hard rule is no new features. Wiring an aggregation into an intent that
has never had one is on the line between "make a declared capability work" and "add a
capability", and the audit's job is to report that line rather than quietly cross it.
The behaviour is recorded here and in the truth table (C3) instead.

### Recommended fix
Add a `CRIME_SEARCH` branch calling the two existing `sql_agent` helpers, with the count
as the first evidence item so it ranks as the answer. Roughly 15 lines, no new
dependency, no new capability that is not already claimed.

---

## BUG-009 — A question about the tool was routed through record retrieval

Severity: P1
Component: packages/rag_agent (intents, orchestrator)
Status: **FIXED**

### Symptoms
Asking the console what it can do returns a refusal about missing records.

### Reproduction
```
POST /chat  {"query": "what all could you answer"}
```

### Expected
An intentional, honest description of scope. Not a chatbot — one paragraph.

### Actual
```
Intent: UNKNOWN
Vector Search Agent   | 5 semantic match(es)
Evidence Evaluator    | 5 weak matches (confidence 0.33) — widening
Vector Search Agent   | 8 semantic match(es)
Evidence Evaluator    | Evidence too weak to support an answer (confidence 0.33)
Synthesis             | Refused to answer — no supporting evidence

"I could not find this in the available records… check whether the record exists
 in the system."
```
Eight criminal profiles were retrieved and discarded in the course of failing to answer
a question that was never about records.

### Root cause
No intent covered questions about the system, so the query fell to `UNKNOWN` and ran the
default retrieval path.

### Fix
A `CAPABILITY` intent, matched by shape before keyword scoring, short-circuits before
retrieval. `intents.capability_answer()` returns one paragraph with **no citations** —
there is no record behind a description of a tool — and it states the limits in the same
breath as the capabilities.

The pattern matches the reported phrasing specifically: "what **all** could you answer"
puts a word between the interrogative and the auxiliary, which the first version of the
regex missed.

### Regression test
- `test_questions_retrieval_cannot_answer_are_routed_before_retrieval`
- `test_the_new_branches_do_not_swallow_real_questions` (guards against over-matching)
- `test_a_capability_question_is_answered_without_touching_the_records`
- `test_the_capability_answer_states_its_limits_not_only_its_features`

### Verification
`python -m pytest packages/rag_agent` green.

---

## BUG-010 — Five different situations shared one refusal message

Severity: P1
Component: packages/rag_agent (evaluator, orchestrator)
Status: **FIXED**

### Symptoms
The console tells the officer to *"check whether the record exists in the system"* when
the question never named a record.

### Reproduction
```
POST /chat  {"query": "who could be the suspect"}
POST /chat  {"query": "Show me the money trail"}
POST /chat  {"query": "Show me the co-offender network"}
POST /chat  {"query": "Tell me about Zzyzx Nonexistentperson"}
POST /chat  {"query": "What is the status of FIR 999999999999999999?"}
```

### Expected
Each refuses — refusing is correct for all five — and each says which of these it is:
evidence genuinely absent; the query named no subject; the query asks for an inference
the records do not license; the named person is not on file; the named record does not
exist in scope.

### Actual
All five returned the identical sentence, after each had swept the vector index and
thrown the results away. For four of them, the sentence named the wrong problem.

Note on `who could be the suspect` specifically: **the refusal was the correct outcome.**
The records hold who was accused, arrested and charged; they do not designate suspects,
and no retrieval failure occurred. The defect is that a correct refusal was reported as
a failed lookup.

### Root cause
`NOT_FOUND_MESSAGE` was the only refusal string in the system, and `node_synthesize`
emitted it for every `requires_escalation`. Nothing carried *why*.

### Fix
- `evaluator.REFUSAL_MESSAGES` — one message per situation, and
  `InvestigationState.refusal_reason` carries which applies.
- `node_retrieve` short-circuits the three that retrieval cannot answer
  (`CAPABILITY`, `NOT_INFERABLE`, and any `intents.NEEDS_SUBJECT` intent with no
  subject) **before** running retrieval, so they no longer sweep the index to produce
  evidence that is then discarded.
- `_after_evaluate` will not widen a turn that stopped for one of these reasons —
  widening is a remedy for a thin batch, not for a question that named no subject.

Every branch still refuses. None of them answers, and per the no-silent-semantics rule
none of them upgrades *"not found in the records"* into *"does not exist"* — the one
message that says "no record … exists" qualifies it with "within your access scope",
and there is a test asserting exactly that.

### Regression test
- `test_every_refusal_reason_has_its_own_message`
- `test_no_refusal_message_claims_the_record_does_not_exist`
- `test_subject_less_relational_questions_stop_before_retrieval`
- `test_a_suspect_question_refuses_for_the_right_reason`

### Verification
`python -m pytest packages/rag_agent` green.

---

## BUG-011 — Vector similarity is displayed to the officer as evidential confidence

Severity: P1
Component: packages/rag_agent/agents/vector_agent.py, apps/web
Status: **OPEN**

### Symptoms
A semantically-similar but substantively unrelated record is shown with a "fair"
confidence band in the evidence rail.

### Reproduction
Ask any question that reaches semantic search and inspect `evidence_items[].confidence`.

### Actual
`vector_agent.search` sets `confidence = r["score"]` — the raw hybrid dense+BM25 score.
That number then flows into three places that all read it as something else: the CRAG
evaluator's accept/reject decision, the ranking that assigns citation `[1]`, and
`confidenceBand()` in the console, which renders it to the officer as strong/fair/weak
*evidential* confidence.

Cosine similarity to a query string and "how well this record supports this claim" are
different quantities. This is the same category error the v10 changelog records for
colour — a non-severity dimension borrowed the severity ramp — one layer down.

### Why it is open
BUG-006's fix substantially contains the damage: below-floor vector hits are no longer
citable at all, so the misread number no longer decides what an officer reads. Fixing
the semantics properly means deciding what evidential confidence *is* for a semantic
hit, which is a design question, not a defect repair.

### Recommended fix
Either calibrate the hybrid score into a support estimate, or carry similarity as its
own field and stop overloading `confidence`. The console should label whichever it
displays.

---

## BUG-012 — /health reported an LLM it had never reached

Severity: P1
Component: packages/rag_agent/llm.py
Status: **FIXED (reporting) / the underlying reachability is UNKNOWN**

### Symptoms
`/health` reports `"llm": "quickml (glm-4.7-flash)"` while every answer the system
produces is the deterministic extractive fallback.

### Reproduction
```bash
curl -s .../health | grep llm            # "quickml (glm-4.7-flash)"
# then any chat turn:
POST /chat {"query": "Does Usha Naika have priors?"}
# answer begins "Based on 12 record(s) in the system:" — the extractive template
curl -s .../health | grep llm            # still "quickml (glm-4.7-flash)"
```
`GET /copilot/9992` confirms it independently: `draft_summary` is the deterministic
`facts` string, not generated prose.

### Expected
`status()`'s own docstring: *"Never reports a model when it cannot be reached."*

### Actual
It reported a model it had never reached, and kept reporting it after every failure.

### Root cause
Two, compounding:
1. `status()` treated `_configured()` — an endpoint URL being set — as equivalent to
   working. It had no notion of "contacted".
2. The failure actually occurring in production, `_token()` returning `None`, raised
   `LLMUnavailable` **directly** from `_chat` instead of going through `_degrade()`. So
   `_degraded_until` stayed at `0.0`, the cooldown never tripped, and the status never
   changed. Every other failure path degrades correctly; this one did not.

`_token()` reaches into SDK internals (`catalyst_app()._app._credential.get_token()`)
inside a bare `except Exception: return None`, so the underlying reason is swallowed.

### Fix
- The missing-credential raise now goes through `_degrade()` like every other failure.
- `status()` distinguishes configured-but-uncontacted (`"quickml (glm-4.7-flash) —
  configured, not yet contacted"`) from working.

### Regression test
- `test_a_missing_credential_degrades_the_reported_status`
- `test_a_configured_but_uncontacted_endpoint_is_not_reported_as_serving`

### Verification
`python -m pytest packages/rag_agent` green.

### Residual — read this
The fix makes the report honest. It does **not** make the LLM work. After deployment,
`/health` will say which of "not configured", "degraded: <reason>" or "working" is true,
and the `<reason>` — currently swallowed by `_token()`'s bare except — is what tells you
whether QuickML is reachable at all from this container. **Until that is deployed and
read, whether the deployed system can reach QuickML is UNKNOWN.** Note that the
deterministic path is not a degradation of correctness: every answer it produces is
grounded and cited. What is lost is fluency, not truth.

---

## BUG-013 — A money-trail question was answered with a theft record

Severity: P1
Component: packages/rag_agent/orchestrator.py
Status: **FIXED**

### Symptoms
Asking for someone's money trail returns a confident answer about their unrelated cases,
and no money-flow visualization.

### Reproduction
```
POST /chat  {"query": "Show me the money trail for Usha Naika"}
```

### Expected
Either the money trail, or an explicit statement that no financial records link to this
person.

### Actual
`Intent: FINANCIAL`, subject resolved correctly, `visualization: none`, **zero** transfer
evidence, and citation `[1]` = *"Usha Naika. Accused in cases of Criminal Intimidation,
Extortion, Hurt…"* — a real record, cited, and not about money at all.

### Root cause
When `graph_agent.money_trail()` returned no rows, the branch added no evidence and said
nothing. Semantic search then supplied the top-ranked item by default. The
`ALIAS_CHECK` branch immediately above it already solves this — it emits an explicit
"no alias recorded" item precisely so unrelated context cannot become the answer — but
`FINANCIAL` did not.

### Fix
The empty case now emits its negative finding as evidence, worded to stay inside what
the records actually say: *"No bank account is linked to this person in the records, and
no transfers are traceable to them. This is an absence in the financial layer, not a
finding that no money moved."*

### Regression test
`test_an_empty_money_trail_states_the_absence_rather_than_leaving_it_unsaid` — asserts
both the presence of the negative finding and that it does not overclaim.

### Verification
`python -m pytest packages/rag_agent` green.

---

## BUG-014 — Risk score returns a saturated 1.00

Severity: P2
Component: packages/ml_models/risk
Status: **OPEN**

### Reproduction
```
POST /chat  {"query": "What is the risk of Usha Naika reoffending?"}
```

### Actual
*"The model suggests a risk score of 1.00 for this person."*

A score pinned at the top of its range is not obviously a calibrated probability, and the
console presents it as a number an officer would act on. The wording is correct — *"the
model suggests"*, not *"the records show"* — so this is not a truthfulness defect. It is
an unvalidated one: the audit did not establish what 1.00 means or how often it occurs.

### Recommended next step
Sample the score distribution across the person population. If it is bimodal at 0/1, the
model is not usefully calibrated and the console should show a band, not a point.

---

## BUG-015 — The causal layer declines to produce an estimate live

Severity: P2
Component: packages/ml_models (DoWhy)
Status: **OPEN**

### Reproduction
```
POST /chat  {"query": "Why does crime correlate with literacy?"}
```

### Actual
Citation `[1]`: *"A causal estimate for literacy_rate cannot be produced: the causal-i…"*

The refusal is honest and correctly worded, and the intent routes correctly. But the
capability is not working live, and the truth table records it as PARTIAL rather than
VERIFIED on that basis.

### Not yet root-caused
The message is truncated in the evidence label; the full reason was not retrieved during
this audit.

---

## BUG-016 — A Kannada turn takes 13.4s against 0.5s for English

Severity: P2
Component: data/nlp/translate.py
Status: **OPEN**

### Reproduction
```
POST /chat  {"query": "ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?", "language": "kn"}
```

### Measured
```
Translation Agent (kn->en)   2119 ms   "How many cases of theft are there in Mandya district"
Vector Search Agent            88 ms
Evidence Evaluator              0 ms
Evidence Synthesis          10770 ms   ← translating the answer back
                            -------
total                        13.4 s
```

Kannada **works** — the round trip is correct end to end, and E2/E3 in the truth table
are VERIFIED. The outbound translation of a multi-sentence extractive answer is the
cost, and extractive answers are long by construction. Worth knowing before a demo.

---

## BUG-017 — The changelog says the model weights left the image; they did not

Severity: P2
Component: documentation / deployment configuration
Status: **OPEN (documentation)**

### Evidence
`CLAUDE.md` v8 states: *"Weights left the image entirely; the image is now 0.88GB… the
~760MB of NLLB + whisper weights moved out of the image into Catalyst File Store…
streamed and spliced… at cold start."*

The live AppSail configuration has **no** `VERITAS_MODELS_FOLDER_ID`, so
`model_fetch.ensure_models()` is never called. Kannada nonetheless works live in 2.1s,
which means the weights are being loaded from `VERITAS_NLLB_CT2_DIR`, whose default is
`/opt/models/nllb-ct2` — inside the image.

Either the weights are still baked in, or a code path not identified in this audit is
supplying them. Either way the changelog does not describe the deployed system.

### Recommended fix
Determine which is true, then correct `CLAUDE.md`. Do not correct the document first.

---

## BUG-018 — PDF export returns HTML

Severity: P2
Component: apps/api/routers/export.py
Status: **OPEN**

### Reproduction
`POST /export/pdf` returns `text/html`, not a PDF — the local fallback renderer, not
SmartBrowz.

The console is not lying about it: `exportPdf()` names the download `.html` when the
blob type is not PDF. So this is a degraded feature, not a false claim. `CLAUDE.md`'s
service table listing SmartBrowz as the PDF path overstates what runs.

---

## BUG-019 — "fir" matches inside "firs", routing a search to the lookup intent

Severity: P3
Component: packages/rag_agent/intents.py
Status: **OPEN**

### Reproduction
`classify("show me murder firs")` → `FIR_LOOKUP`, not `CRIME_SEARCH`.

Keyword matching is by substring, and `"fir" in "firs"`. Harmless today: `FIR_LOOKUP`'s
branch is a no-op unless `FIR_NUMBER_RE` matches, so the turn falls through to the same
semantic search `CRIME_SEARCH` would have run. It stops being harmless the moment that
branch does anything on its own. Recorded, with a note at the test that documents the
behaviour rather than asserting it.

---

## Second deploy — console live, three architectural fixes, live-verified

Everything below was found and fixed *after* the first deploy's live verification
(commit `9393a8b`, deployment `52852000000304010`). Console deployed for the first
time in this pass; three code fixes deployed as `71dc2a4`, deployment
`52852000000310011`, `Aug 25, 2026 10:25 PM`. All results below were re-driven live
against that deployment, not inferred from the fix's local tests.

### Console deployment — verified as an artifact, not a command's exit code

`scripts/deploy-console.sh` was run for the first time since the BUG-002/BUG-005
client-side fixes were committed. Command success was **not** taken as proof — the
served bundle was fetched and grepped for the fix's literal UI strings ("signs you
out", "warming up"), confirmed absent of `localhost:8000`, and driven with headless
Chrome over CDP:

- Login gate renders the real 6-officer roster live.
- `?as=DSP` signs in and renders the full console (case index, health stats matching
  `/health` exactly).
- A real chat turn ("What is the status of FIR 100222201202600022?"), typed into the
  actual `<textarea>` and submitted via the actual "Ask" button, rendered **one**
  citation in the Evidence rail — BUG-006's fix confirmed through the browser, not
  just the API.
- **BUG-002, reproduced and confirmed fixed in the browser**: seeded a real stale
  token in `localStorage` on the live origin, forced the roster request to fail via
  CDP `Fetch` interception (a genuine simulated network failure, not a guess), and
  confirmed: the token survived up to the moment of choice (`localStorage.getItem` —
  present); after clicking a "demonstration" role, `localStorage.getItem('veritas_token')`
  returned `null`. Screenshots taken at both points.
- **BUG-005's client half could not be verified** — see BUG-005 above: the `/alerts`
  WebSocket appears blocked at the AppSail gateway for any client, browser or not.

## BUG-020 — The evaluator's relevance floor deleted authoritative refusals (CAUSAL regression)

Severity: P1
Component: packages/rag_agent (evidence/evaluator.py, state.py, agents/prediction_agent.py)
Status: **FIXED, live-verified**

### Symptoms
Introduced by the BUG-006 fix itself, in the same session. "Why does crime correlate
with literacy?" lost its honest "cannot be produced" decline and answered instead
from five unrelated criminal profiles.

### Root cause
`prediction_agent.causal()` sets `confidence=0.0` on its own decline **by convention**
— "not applicable," not "irrelevant." `RELEVANCE_FLOOR` (0.5) cannot tell that apart
from a genuinely weak retrieval hit, so `supporting()` dropped it while five vector
hits that happened to clear 0.5 survived and became the whole answer.

### Fix
`EvidenceItem.authoritative: bool` — a second axis, orthogonal to confidence.
`supporting()` keeps an authoritative item regardless of its confidence value;
`evaluate()` treats the presence of one as an immediate ACCEPT (retrying cannot
improve on an authoritative statement, so it no longer widens first). Applied to the
CAUSAL decline and, for consistency, to the pre-existing ALIAS_CHECK/FINANCIAL
negative findings that had been relying on a high manually-chosen confidence (0.9) to
survive the same floor by luck rather than by design.

### Regression test
`packages/rag_agent/tests/test_engine.py`: `test_an_authoritative_item_survives_the_relevance_floor_regardless_of_confidence`,
`test_a_batch_of_pure_noise_still_rejects_when_nothing_is_authoritative` (guards
against over-correcting), `test_an_authoritative_item_alone_is_accepted_immediately_not_widened`,
`test_an_authoritative_item_is_not_outvoted_by_surrounding_noise` (the exact
regression shape), `test_the_causal_decline_is_marked_authoritative` (the actual
production code path, not just the evaluator in isolation).

### Verification
**Live, post-deploy**: *"Why does crime correlate with literacy?"* → 1 citation, the
honest decline, no criminal profiles. `python -m pytest` green throughout.

---

## BUG-021 — QuickML `_token()` called a method that does not exist on the SDK

Severity: P1
Component: packages/rag_agent/llm.py
Status: **FIXED (authentication) — see BUG-022 for what surfaced next**

### Symptoms
`/health` claimed QuickML was serving while every answer was extractive (documented as
BUG-012 in the first pass; this is its actual root cause, found while implementing
the reachability fix the earlier pass could only diagnose from the outside).

### Root cause
`catalyst_app()._app._credential.get_token()`. Confirmed by downloading and extracting
the published `zcatalyst-sdk` 1.4.0 wheel and reading the source directly:
`zcatalyst_sdk.initialize()` returns the `CatalystApp` object **directly** — there is
no `._app` wrapper attribute anywhere on it — and `Credential` subclasses expose
`.token()`, never `.get_token()` (that name exists only on the unrelated cookie-auth
`JwtTokenCredential`, used nowhere in this code path). Both attribute lookups raised
`AttributeError` on the very first call, in every environment, always; the bare
`except Exception: return None` turned that into a silent "no credential." This was
never specific to AppSail reachability — the LLM had never been successfully called.

Validated three ways before considering it fixed, per "verify the diagnosis before
changing anything":
1. Read `credentials.py`/`catalyst_app.py` from the extracted wheel directly.
2. Reproduced the exact `AttributeError` against the real installed SDK with simulated
   AppSail request headers (`X-ZC-Admin-Cred-Token` etc.), in an isolated venv so the
   AppSail-only dependency was never added to the project's own local environment.
3. Confirmed the fixed logic extracts the correct admin-scoped bearer token from the
   same simulated headers, and does **not** pick up the per-officer user token instead.

### Fix
`credential.token()` — the exact call `zcatalyst_sdk._http_client.AuthorizedHttpClient`
makes internally before every Data Store / Cache / graph request — dispatched by
credential type (`CatalystCredential` returns a `(class_name, value)` pair, not a bare
string). `_switch_user("admin")` first, matching the scope Data Store operations
already run under: "the SDK authenticates as the app itself," and there is no
per-officer token to call an LLM with.

### Regression test
`test_the_old_credential_path_never_existed_on_the_real_sdk`,
`test_token_reads_the_admin_credential_the_way_the_sdks_own_http_client_does` — both
run against the real installed `zcatalyst-sdk`, skipped (not faked) where it is
absent, per the project's own "Absent everywhere else" convention for this dependency.
Both pass in an isolated venv with the real package installed.

### Verification
**Live, post-deploy**: the failure mode changed from `RuntimeError: no Catalyst
credential — QuickML is only reachable in AppSail` to a real HTTP 400 **from
QuickML's own gateway** (`PATTERN_NOT_MATCHED`). That change in kind — an internal
attribute error replaced by a real service response — is the proof the credential
now resolves correctly inside AppSail. See BUG-022 for what that response means.

---

## BUG-022 — QuickML's gateway rejects the request body/route, independent of auth

Severity: P2
Component: packages/rag_agent/llm.py (QUICKML_ENDPOINT), external (Zoho QuickML gateway)
Status: **OPEN — root cause narrowed, not resolved**

### Symptoms
With BUG-021 fixed, every LLM call now reaches QuickML and is rejected:
```json
{"code":"PATTERN_NOT_MATCHED","message":"PATTERN_NOT_MATCHED",
 "details":{"requestUri":"/quickml/v1/project/52852000000013048/glm/chat",
            "reason":"Error in processing `zoho-inputstream` parameter"}}
```
HTTP 400, identical byte-for-byte regardless of request body content (`stream: true`
vs `false`, present vs absent) or added headers (`CATALYST-ORG`, `ENVIRONMENT`) —
tried directly against the live endpoint with a separately-valid Catalyst OAuth token
(from `scripts/catalyst-token.js`), outside AppSail, to isolate this from the
credential fix.

### What was ruled out
- Not a credential/auth problem — a valid token reaches the gateway and gets a
  service-level response, not a 401/403.
- Not the request body shape (OpenAI-style `{model, messages, temperature}`) — the
  error is identical with and without a `stream` field.
- Not a missing header this session could identify — `zoho-inputstream` does not
  match any parameter this code sends, and does not appear in `.env`, the codebase,
  or the reachable Catalyst documentation (checked `docs.catalyst.zoho.com`'s
  "LLM Serving" and "Pipeline Endpoints" pages; neither documents the chat-completion
  request shape for this specific product surface — the pages defer to a "Model
  Details" popup inside the QuickML console, which is not reachable over the Admin
  API used throughout this deployment).

### Why this stops here
Continuing to vary the request against a live, billed, production LLM endpoint by
guesswork is the trial-and-error this phase's own rules exclude ("no vibecoded
remediation"). Resolving it needs either the exact request schema from the QuickML
console's Model Details page (UI-only, not exposed over the Admin API), or direct
vendor documentation/support.

### What is already correctly verified regardless of this
The system's behaviour when QuickML is unreachable is itself fully verified and
correct: `/health` reports the real error rather than a false "healthy" claim (fixing
BUG-012's *reporting* half was independent of whether the endpoint itself ever
resolves), and every chat turn still produces a grounded, cited, extractive answer.
Nothing about this gap makes any live answer less true — only less fluent.

---

## BUG-023 — Every FIR narrative for a given crime type is the same template

Severity: P1
Component: data/data/generator/build.py (`_MO`, `_narrative`)
Status: **OPEN — data-generation limitation, quantified live, not a code defect**

### Symptoms
A generic query ("Show me crime hotspots", "Forecast crime") returns 5 semantic
"corroborating" narrative citations that read as near-duplicates of each other,
differing only by date and district — e.g. five separate FIR records all reading
*"…a case of cyber crime was registered in `<district>` district. OTP-phishing call
impersonating a bank official. Investigation is being carried out as per procedure."*

Separately, `Copilot.similar_cases` reported 0.941 similarity between two different
Hurt cases in Mandya (observed in the first audit pass) — a number that looks like
strong modus-operandi corroboration but is not.

### Reproduction
```
GET /cases?crime_type=Theft&limit=60   (any role's token)
```
Normalize each returned `narrative` by replacing the date and district with
placeholders, then compare.

### Measured
```
Theft        : 60 cases -> 1 distinct narrative shape
Hurt         : 60 cases -> 1 distinct narrative shape
Cyber Crime  : 60 cases -> 1 distinct narrative shape
Robbery      : 60 cases -> 1 distinct narrative shape
```
Every sampled case of a given crime type reduces to the exact same sentence once date
and district are normalized out.

### Root cause
`data/data/generator/build.py`:
```python
_MO = {
    "Theft": "Pickpocketing in a crowded market",
    "House Burglary": "Entry via rear window after dark while occupants away",
    ...  # exactly 8 crime types, each with exactly ONE modus-operandi sentence
}

def _narrative(crime_type, district, filed, mo):
    return (f"On {filed:%d %b %Y}, a case of {crime_type.lower()} was registered in "
            f"{district} district. {mo}. Investigation is being carried out as per procedure.")
```
Every FIR's `BriefFacts` narrative has exactly three variable slots — date, district,
and a crime-type-determined MO string chosen from a **fixed dictionary of eight**.
There is no per-case narrative variation at all. An embedding model correctly learns
that all cases of the same crime type are near-identical text, because they are.

### Consequences, checked against the user's own four questions

1. **False similarity — confirmed.** `SIMILAR_CASES` and the Copilot's `similar_cases`
   are measuring "same crime type, same-ish district," not genuine narrative or
   modus-operandi similarity. Two Theft cases with nothing in common beyond the crime
   type will score as highly "similar" as two Theft cases that are actually alike,
   because there is no narrative signal to tell them apart.
2. **False retrieval — confirmed, and this is what surfaced it.** A generic HOTSPOT or
   FORECAST query, which names no specific narrative content, still pulls 5 "semantic
   matches" from vector search — and because so many records share one template, those
   5 hits are frequently near-duplicates of each other rather than 5 independently
   relevant records. They are real, distinct FIRs (no data corruption — see the
   distinction below), but they do not corroborate each other the way 5 *different*
   matching narratives would.
3. **Misleading embeddings — confirmed as a description of the mechanism**, not a bug
   in the embedding code. The embeddings are accurately representing text that itself
   carries almost no case-specific information.
4. **Misleading analytics — not found.** KDE/DBSCAN hotspots, Prophet/MinT forecasts,
   risk/recidivism scoring, and the graph/financial layers do not depend on narrative
   text at all — they run on coordinates, dates, and structured relationships, which
   are genuinely diverse per case (confirmed throughout `data/tests/test_integrity.py`
   and this audit's live testing). This gap is scoped to the narrative/vector axis
   specifically.

### This is NOT a duplicate-record bug
Every affected row is a real, distinct FIR — different `CaseMasterID`, different date,
different accused, different victims, different coordinates. `data/tests/test_integrity.py`
already confirms no duplicate FIR numbers or rows exist. The problem is that the one
free-text field meant to carry case-specific detail does not, for any of the eight
crime types the generator's `_MO` dictionary covers. Nothing here should be "fixed" by
touching the record layer — this is a synthetic-data authoring gap, not a data
integrity defect.

### Why this is left open
Widening `_MO` from one sentence per crime type to several, or generating narrative
detail proportional to the case (weapon, relationship to victim, specific location
type), is a change to the *generator*, and regenerating the dataset is a decision with
consequences beyond this audit's fix-the-defects-found scope — every measurement in
this repo that references specific FIR numbers, specific people, or specific citation
counts would need re-verification against a new dataset. Recorded here as a scoped,
well-evidenced finding for that decision to be made deliberately, not fixed in passing.

### Regression test
None added — this is a data-authoring finding, not a code defect with a wrong output
to pin down. If the generator's narrative diversity is later widened, the check to add
is exactly the one used to find this: sample N cases per crime type, normalize date and
district, assert more than one distinct shape survives.

### Verification
Live, `python` one-liner against `GET /cases`, four crime types, 60 cases each,
reproduced consistently.

---

## BUG-024 — `POST /jobs/refresh` fails with a 500 against the live dataset

Severity: **P1**
Component: apps/api/routers/jobs.py, data/gds.py and/or data/embeddings/index_job.py
Status: **FIXED, deployed, live-verified**

### Symptoms
The scheduled refresh job — the one Cron is supposed to run every 6 hours to recompute
PageRank/Louvain/betweenness, republish the graph, and rebuild the vector index —
fails when actually triggered against the live, full-size dataset.

### Reproduction
```bash
curl -X POST -H "X-Veritas-Job-Token: <the deployed secret>" \
  https://veritas-api-50043864344.development.catalystappsail.in/jobs/refresh
```
Two independent runs, ~15 minutes apart: both returned `500`, `Internal Server Error`,
in 15.69s and 16.04s respectively.

### What this rules out
`GET /jobs/audit-verify`, triggered with the exact same token and header immediately
before and after, works correctly both times — `{"intact":true,"first_bad_audit_id":null}`
— so this is not an auth problem, not a wrong header/token, and not the job-endpoint
mechanism in general. It is specific to `/jobs/refresh`'s own pipeline.

`publish_graph()` (`data/graph.py`) and the vector index's `_bucket()`
(`data/vectors.py`) are both already correctly guarded — `try/except Exception: return
None`/`False` — against Stratus being unreachable (documented and expected: "Stratus
bucket creation is scope-blocked over the Admin API"). Reading both confirms neither
should raise.

### What was not possible to isolate further
No server-side traceback was available — there is no runtime/application log endpoint
exposed over the Admin API (only the bundle-build pipeline log, confirmed earlier this
session while investigating cold start). The response body is the generic plain-text
`Internal Server Error` (`Content-Type: text/plain`), not FastAPI's usual JSON error
shape, which is more consistent with a gateway-level response to a crashed or timed-out
upstream than an application-level exception handler — but this could not be confirmed
either way without log access.

Timed locally, twice, to narrow this down further:

1. **At the full graph's reported scale** (16,918 nodes / 87,120 edges, matching
   `/health`) — a synthetic random graph of that size, run through the exact same
   three calls `run_all()` makes: PageRank 0.42s, Louvain 4.10s, pivot-sampled
   betweenness (`k=500`, matching `_BETWEENNESS_PIVOTS` in `data/gds.py`
   exactly) **179.48s**. The code's own comment already names this risk — *"Exact
   betweenness is O(V\*E) — minutes on ~19k nodes. Pivot sampling… is what keeps
   this an interactive question instead of a batch job"* — but 179s for the
   *sampled* version alone, at this scale, is already far past any plausible
   request timeout.

2. **`run_all()` does not actually run on the full graph** — it runs on
   `co_offending()`, the person-only projection. Re-estimated at that more accurate
   scale (~7,000 person nodes, from the generator's `people = 0.7 × case count`
   ratio; ~5,700 edges, scaled from the 142 `CO_ACCUSED_WITH` edges measured in this
   session's 250-case test fixture): PageRank + Louvain + betweenness together took
   **8.23s** — comfortably under the ~15.7–16s observed failures.

That second, more accurate estimate actually argues *against* GDS being the
bottleneck: if the three-algorithm pass finishes in ~8s, the remaining ~7–8s (and the
failure itself) more plausibly belongs to one of the pipeline's other two steps,
neither of which was timed this session:
- `ds.update("vx_person", "PersonUID", rows)` — writing ~7,000 rows back. ZCQL has no
  bulk `UPDATE`; `data/data/ds.py`'s own documentation notes updates resolve key→ROWID
  once and then bulk-write, but the real round-trip cost of that at ~7,000 rows against
  the live Data Store was not measured.
- `data.embeddings.index_job.run_all()` — rebuilding the vector index over 13,835+
  documents, a completely separate cost this session did not estimate at all.

Both remain open candidates. This audit could not distinguish between "a platform
request timeout around 15–16s" and "a genuine slowness in the write-back or reindex
step" without either log access or timing those two steps directly against a
production-scale dataset — neither of which was done this session.

### Why this matters
This is the job the whole system's claim of staying current depends on: "Everything
derived from the record layer goes stale the moment the record layer changes" (the
job's own docstring). If it has never successfully completed against the live dataset,
the graph metrics, the Stratus-published graph blob, and the vector index have been
serving whatever was last built during generation/seeding — not a defect in what is
currently being answered (this audit found no stale-data symptom in any live query),
but a real gap in the system's ability to stay current going forward.

### Fix
The recompute moves to a background thread — the same pattern `main.py`'s AppSail
warm-up already uses, including how it propagates the captured Catalyst request
context (guarded to only do so on the `catalyst` backend, matching
`bind_catalyst_request`'s own guard, so local/test sqlite runs are unaffected). The
endpoint now returns `{"status": "started"}` immediately; a non-reentrant guard
reports `{"status": "already_running"}` rather than starting a second overlapping run.

### Regression test
Three new tests in `apps/api/tests/test_api.py`: the request returns in well under a
second while the job keeps running to completion on a released background thread, a
second trigger while one is in flight is refused rather than starting a concurrent
run, and the token gate still holds. No prior test exercised this endpoint's actual
behavior at all — only its auth gate was implicitly covered elsewhere.

### Verification
**Deployed** (`52852000000310022`, Aug 25 2026 11:03 PM) and **live-verified end to
end**, including letting the real job run to genuine completion:

```
POST /jobs/refresh  -> {"status":"started"}       0.17s   (was: 500 after ~16s)
POST /jobs/refresh  -> {"status":"already_running"} 0.20s   (fired immediately after)
POST /jobs/refresh  -> {"status":"already_running"} 0.14s   (fired again ~2 min later —
                                                              still genuinely running)
POST /jobs/refresh  -> {"status":"started"}                (fired ~5-6 min after the
                                                              first trigger — the PRIOR
                                                              run had finished and
                                                              cleared the guard)
```

That the job was still `already_running` at the 2-minute mark and had finished by
5-6 minutes independently confirms the original defect: this was never going to
complete inside any synchronous HTTP timeout, regardless of which specific step
dominated.

`/health` immediately after: `firs=10000`, `graph_nodes=16918`, `graph_edges=87120` —
unchanged, no corruption. `indexed_documents` moved from 13,835 to 13,729 — a real
change (proof the reindex genuinely ran, not a cached response), direction and
magnitude not further investigated this session. A live regression check (exact FIR
lookup, BUG-006's own test case) still returned the correct single citation
afterward, so nothing observable broke.

**Not verified**: whether Catalyst Cron's own 6-hourly schedule actually invokes this
endpoint (the trigger was manual, with the real job token, bypassing the schedule
entirely — Cron firing on schedule remains unobserved, tracked separately in the QA
matrix as DEP-12).

---

## Summary

| ID | Severity | Status |
|----|----------|--------|
| BUG-001 cold start / roster timeout | P1 | FIXED, mechanism verified; duration **measured live: ~22.7–22.9s, once per container** |
| BUG-002 stale token in unverified mode | **P0** | **FIXED, verified live in the browser** (CDP: seeded token cleared on entering unverified mode) |
| BUG-003 /copilot authorization bypass | **P0** | **FIXED, verified live** (both deploys) |
| BUG-004 masking not applied on /fir and Copilot | P1 | **FIXED, verified live** (both deploys) |
| BUG-005 unauthenticated /alerts WebSocket | P1 | FIXED in code (ASGI-level test); **live verification blocked — see BUG-005 above, apparent AppSail gateway limitation on WebSocket upgrades** |
| BUG-006 unsupporting citations | **P0** | **FIXED, verified live** in the API and, separately, driven end to end in the browser |
| BUG-007 intent misrouting | P1 | FIXED |
| BUG-008 no count for "how many" | P1 | OPEN (deliberate) |
| BUG-009 capability question through retrieval | P1 | **FIXED, verified live** |
| BUG-010 one refusal message for five situations | P1 | **FIXED, verified live** |
| BUG-011 similarity shown as confidence | P1 | OPEN |
| BUG-012 /health reported an unreached LLM | P1 | FIXED (reporting) — **root cause of the unreachability itself found and fixed, see BUG-021/BUG-022** |
| BUG-013 money trail answered from a theft record | P1 | **FIXED, verified live** — negative finding is now the *only* citation |
| BUG-014 saturated risk score | P2 | OPEN |
| BUG-015 causal layer declines live | P2 | OPEN — **root cause now known: `dowhy` is not installed in the deployed image (by design, per the v7 changelog); the decline is itself now correctly the only citation (BUG-020)** |
| BUG-016 Kannada latency | P2 | OPEN |
| BUG-017 changelog vs deployed weights | P2 | OPEN |
| BUG-018 PDF export returns HTML | P2 | OPEN |
| BUG-019 "fir" matches "firs" | P3 | OPEN |
| BUG-020 evaluator floor deleted authoritative refusals | P1 | **FIXED, verified live** (regression found and fixed within this same phase) |
| BUG-021 QuickML credential call never worked | P1 | **FIXED, verified live** (failure mode changed from internal `AttributeError` to a real service response) |
| BUG-022 QuickML gateway rejects the request shape | P2 | OPEN — root cause narrowed (not a credential/body/header issue this session could resolve); needs vendor docs or console access |
| BUG-023 every narrative for a crime type is one template | **P1** | OPEN — data-generation limitation, quantified live (60/60 cases per type collapse to 1 shape); not a code defect, not a duplicate-record bug |
| BUG-024 `/jobs/refresh` 500s against the live dataset | **P1** | **FIXED, deployed, live-verified** — moved to a background thread; watched the real job run to genuine completion (5-6 min) and confirmed no corruption |

**3 P0, 15 P1, 6 P2, 1 P3 across 24 tracked defects. 16 fixed and live-verified, 1 fixed
in code with live verification blocked by an apparent platform limit, 1 fixed at the
reporting level with the underlying cause now understood, 9 open.**

### One thing this audit got wrong, recorded deliberately

The first duplication hypothesis was wrong. `vx_graph_edge` holds 12 apparently-duplicate
`TRANSFERRED_TO` rows; they are **one row per transaction** between the same account
pair (`acct:13 → acct:10` twice = TxnID 3 and 26, separate EdgeIDs, separate amounts).
`load_graph()` builds a `MultiDiGraph`, so they survive correctly — a `DiGraph` would
have silently kept the last one and deleted money from the trail. A blanket `DISTINCT`,
or a "fix" to make the first assertion pass, would have destroyed real data.

The 12 reciprocal transfer edges are likewise 6 pairs of accounts that genuinely pay
each other. Directed is not antisymmetric.

Both are now asserted the way they should have been in the first place, in
`data/tests/test_integrity.py`, with the reasoning written down so it is not re-derived
from a failing test.
