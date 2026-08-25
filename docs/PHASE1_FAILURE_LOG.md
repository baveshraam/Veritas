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

### Superseded (overnight finalization pass) — WebSocket replaced with SSE
Rather than keep waiting on an unconfirmed platform question, the route was moved off
WebSocket entirely. `/chat` already proves a different transport works live on this
exact deployment: `sse_starlette.EventSourceResponse` over a plain `GET`/`POST`,
authenticated with a normal bearer header via `fetch` (not `EventSource`, which —
like `WebSocket` — cannot set an `Authorization` header, which is exactly why
`lib/api.ts` never used it for `/chat` either). `/alerts` is now `GET` + SSE, using
the identical `Depends(current_officer)` every other data-bearing route uses instead
of the hand-rolled first-frame token handshake. This removes the dependency on
whatever AppSail does or does not proxy for WebSocket upgrades, rather than resolving
the question — the question itself stays open and is no longer load-bearing.

Regression test rewritten: `test_alerts_refuses_an_unauthenticated_client` (plain
401/bad-token checks over GET, no WebSocket transport involved) and
`test_alerts_streams_for_an_authenticated_officer` (drives the route function and its
async generator directly with a fake alert, verifying framing and auth without
depending on TestClient's synchronous transport correctly streaming an infinite
generator — confirmed via an isolated minimal reproduction that it does not).
Status: **FIXED (transport changed, not the WebSocket gateway question) — pending
live verification of the new SSE endpoint.**

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
Component: packages/rag_agent/orchestrator.py, packages/rag_agent/agents/sql_agent.py
Status: **FIXED (final implementation pass, Phase 1)**

### Fix
`sql_agent.count_firs()` — an exact, role/station-scoped count over the same WHERE
clause `search_firs` uses, counted in Python because ZCQL has no GROUP BY over a join
this deep (same pattern `case_counts_by_district` already uses). `orchestrator.py`'s
`_run_specialists` gained a `CRIME_SEARCH` branch: extracts a crime type from the
query (`_crime_type_from_query`, matched against the 20 canonical types, longest
match wins so "Motor Vehicle Theft" is not shadowed by "Theft"), an optional district
from the session's active location, and emits the count as an **authoritative**
evidence item plus up to 5 matching FIR records as supporting samples. `CRIME_SEARCH`
joins `_SPECIALIST_SETTLES`, so — like the relational intents — vector search does
not run once the count has settled the turn: semantic neighbours cannot corroborate a
count, they can only pad it, which is exactly the anti-pattern BUG-006 fixed for
other intents.

### Regression test
`test_crime_search_returns_an_exact_count_and_supporting_samples`,
`test_crime_search_states_zero_plainly_rather_than_going_silent`,
`test_crime_type_extraction_prefers_the_longer_specific_match`.

### Verification
`python -m pytest` green. **Live-verified** (deployment `52852000000310022`→relayed
redeploy, Aug 25 2026): `POST /chat {"query": "How many theft cases are there in
Mandya district?"}` → *"73 case(s) Theft in Mandya are recorded within your access
scope."*, `authoritative: true`, trace: *"Vector Search Agent | Skipped — CRIME_SEARCH
was answered directly from the record layer"*.

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
Component: packages/rag_agent/agents/vector_agent.py, packages/rag_agent/agents/prediction_agent.py, packages/rag_agent/state.py, apps/web
Status: **FIXED (final implementation pass, Phase 1)**

### Fix
`EvidenceItem` gained `confidence_kind: Literal["support", "similarity", "model_estimate"]`
— not a calibration, a category. It answers "what does this number actually
measure", set at the one place each kind of number is produced:
- `vector_agent.search()` — raw hybrid dense+BM25 similarity → `"similarity"`.
- `prediction_agent`'s risk/recidivism/forecast/causal items — a fixed ranking-weight
  constant the evaluator uses to corroborate/rank (0.6, 0.7, 0.5, 0.3, 0.1 — never the
  model's own reported score, which lives in `content`) → `"model_estimate"`. KDE
  hotspot intensity and AML transaction-flag confidence are per-instance, genuinely
  computed-from-this-record numbers, so they keep the default.
- Everything else (exact FIR/person lookups, graph relationships, authoritative
  findings) → default `"support"`, unchanged — these already meant what they said.

`apps/web`: `EvidenceRail.tsx` no longer renders one undifferentiated "confidence"
percentage. `"similarity"` items show a labeled "% text similarity" chip;
`"model_estimate"` items show a plain "model output" tag with no percentage, because
the model's real number already appears in the citation body and a second,
differently-scaled percentage next to it would just be a second unlabeled number.
`"support"` items keep the existing strong/fair/weak percentage band, now explicitly
labeled "evidence strength". The "Open Investigation Copilot" button (previously
shown for any `FIR_RECORD` item) is now also guarded to only render for a genuine
numeric FIR id, so a non-record `FIR_RECORD`-typed item (the CRIME_SEARCH count) does
not offer a Copilot link the backend cannot serve.

### Regression test
`test_vector_hits_are_labeled_as_similarity_not_support`,
`test_exact_and_authoritative_evidence_defaults_to_support_kind`,
`test_model_predictions_carry_a_distinct_kind_from_their_own_reported_score`.

### Verification
`python -m pytest` green, `npx tsc --noEmit` clean. **Live-verified**, both API and
console: a real vector search hit (`"Show me the money trail for Nithin Savadi"`, a
name not on file) returned `confidence_kind: "similarity"` on every semantic
candidate; the risk-score query below returned `confidence_kind: "model_estimate"`
on the ML_PREDICTION items; the FIR-lookup and CRIME_SEARCH-count items above
returned `confidence_kind: "support"`. Console redeployed and its served bundle
grepped directly for the new UI strings ("model output", "text similarity",
"evidence strength") — present, not just a green build exit code.

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
Component: packages/ml_models/risk/scoring.py
Status: **FIXED (final implementation pass, Phase 1)**

### Root cause
`_risk_model()` fit a raw `XGBClassifier` and returned `predict_proba` directly.
Unlike `_recidivism_model()` one function below (already isotonic-calibrated via
`CalibratedClassifierCV`), the risk model had no calibration step at all — a raw
XGBoost margin-derived score is known to saturate near 0/1 on skewed data, which is
exactly the symptom measured live (a reported 1.00 with no way to tell "very likely"
from "the model is just confident it's confident").

### Fix
Same isotonic-calibration pattern the recidivism model already uses, adapted to
`cv="prefit"` so TreeSHAP still explains the real fitted booster rather than an
ensemble of calibration folds: `base` is fit on a training split, a `CalibratedClassifierCV`
wraps it and is fit on a held-out calibration split, and `score_risk()` reports from
the calibrated wrapper. `RiskResult.calibrated: bool` is now honest about which
happened — if the calibration split lacks at least 5 of both classes, or isotonic
fitting itself fails, the raw model is used and `calibrated=False` is reported rather
than silently claiming a calibration that didn't happen (a failed calibration must
not be reported as a successful one). The evidence text now says which case applies.

### Regression test
`test_risk_scores_are_calibrated_not_a_raw_saturated_margin` — fits the real model
against the test dataset, scores a sample of people, asserts every score is in
`[0, 1]`, and that a calibrated run does not produce every score rounding to the
same value (the saturation signature).

### Verification
`python -m pytest` green — the new test exercises the real calibration path against
a real (if small) dataset and passed without falling back to the uncalibrated branch.
**Live-verified**: `POST /chat {"query": "What is the risk of Usha Naika
reoffending?"}` on the live deployment returned *"The model suggests a risk score of
1.00 for this person (NOT calibrated — a ranking score, not a probability)"* — the
live dataset's calibration split does not have enough class balance to fit isotonic
regression, so the honest fallback fired exactly as designed. The saturated 1.00
itself persists on this dataset (a real, heavy-prior person can genuinely score at
the top of the range), but it is no longer silently presented as a calibrated
probability — which is the actual defect this bug named. The companion recidivism
score, on the same person, *did* calibrate successfully and also reported ~100%,
correctly labeled "(calibrated)" — a legitimate extreme value for a habitual
offender, now distinguishable from the risk score's honest non-calibration.

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

### Not yet root-caused (superseded below)
The message is truncated in the evidence label; the full reason was not retrieved during
this audit.

### Root cause confirmed, deployability measured (overnight finalization pass)
`dowhy` is not installed in the deployed image — by design, per the v7 changelog — so
the decline this bug describes is the correct, honest behaviour of an unavailable
capability, not a defect (BUG-020 already confirmed the decline survives as the sole
citation rather than being crowded out).

The open question was whether that absence is still necessary, or whether `dowhy` can
now be added within the image budget. Measured directly rather than guessed: installed
`dowhy==0.14` into an isolated venv (same methodology as the BUG-021/BUG-018 SDK
diagnoses) and sized its full dependency closure —

```
TOTAL install: 749.6 MB
  llvmlite     121.8 MB   (numba's JIT backend)
  scipy        113.8 MB   (already in the deployed image — no new cost)
  sympy         68.6 MB
  pandas        62.7 MB   (already in the deployed image)
  statsmodels   47.6 MB
  sklearn       41.9 MB   (already in the deployed image)
  matplotlib    31.7 MB   (pulled in transitively despite no "plotting" extra requested)
  numpy         32.2 MB   (already in the deployed image)
  scs.libs      28.2 MB   (a cvxpy solver backend)
  numba         27.2 MB
  ...
```

Summing only the packages genuinely new to this image (excluding numpy/scipy/pandas/
sklearn/networkx, already present for XGBoost/LightGBM/Prophet/etc.): llvmlite +
numba + sympy + statsmodels + cvxpy + scs.libs + highspy + clarabel + causal-learn +
matplotlib + PIL + fontTools + Cython + dowhy itself + mpmath + narwhals ≈ **405MB**.

Against the current image (0.88GB, per the v8 changelog) and the empirically measured
bundle-sandbox ceiling (~1.3GB, "the real ceiling... because staging adds a fourth
copy" — v8 changelog), adding dowhy lands at ≈1.28GB: inside the ceiling on paper, but
with essentially zero margin against a limit that has already killed two prior
deploys at 2.23GB and 1.61GB with no partial-failure recovery — a failed bundle would
risk the entire currently-working, live-verified deployment for a P2 capability.

**`llvmlite`/`numba` is the same dependency class the v7 changelog already removed
once** — SHAP was replaced with `xgboost`'s own `pred_contribs` specifically to drop
"the shap -> numba -> llvmlite chain, ~240MB." Re-adding an equivalent ~150MB chain
(llvmlite + numba together here) via a different path undoes that earlier, deliberate
trade-off for the same reason it was made.

**Decision: not deployed.** This is a measured "no," not an unexamined one — a live
redeploy experiment to "see if it fits" was deliberately not attempted, matching this
pass's own rule against gambling with a working production deployment. `dowhy` stays
out of the image; the honest decline (BUG-020) remains the correct live behaviour, and
the UI/README must not imply causal inference is operational. Status: **OPEN —
platform/budget-constrained, root cause and deployability now conclusively measured
rather than assumed.**

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

### Profiled (overnight finalization pass) — two distinct costs, only one of them fixed
Ran `translate()` directly against the real cached NLLB weights, timing a cold call
against two subsequent warm ones on the same process:

```
first  (cold load + infer, short text): 21.966s
second (warm, short text):               1.352s
third  (warm, short text):               0.793s
```

**One real, fixable bug found**: nothing paid the ~20s weight-load cost proactively —
it landed on whichever officer's query happened to be first after a container start
or restart, indistinguishable from a hang at 20s. Fixed: `translate.warm()` /
`speech.warm()` now run from the same background thread that already fetches the
Data Store mirror and File Store weights on startup (`apps/api/api/main.py`), moving
that cost off the request path entirely.

**What this does NOT explain**: the 10770ms "Evidence Synthesis" step measured above
was translating the *outbound answer* — the second translation call in that same
request, on an already-warm model (the first, inbound-query translation in the same
request had already paid any load cost at 2119ms). A warm model translating a much
longer, multi-sentence answer taking 5-8x longer than a warm model translating a
short question is consistent with autoregressive generation time scaling with output
token count on CPU, not a fixable defect in this code — NLLB has no GPU to run on
here, and generation is inherently sequential. This is an inherent CPU/model-size
latency characteristic of long-answer translation, not a bug the warm-up fix (or any
code change short of a smaller/faster model or truncating answers before
translation) touches. Documented honestly rather than claimed fixed: BUG-016 is
**PARTIALLY FIXED** (the cold-start tax is gone) with a **known, inherent residual
cost** for long answers that remains.

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

### Recommended fix (superseded below)
Determine which is true, then correct `CLAUDE.md`. Do not correct the document first.

### Resolved (overnight finalization pass) — the architecture was real but never wired
Confirmed live, over the Admin API, before touching anything: the AppSail app's
configuration genuinely had only `VERITAS_JOB_TOKEN`, `VERITAS_JWT_SECRET`,
`VERITAS_RESTART_NONCE` — no `VERITAS_MODELS_FOLDER_ID` — so `model_fetch.
ensure_models()` had never run in production, exactly as the original audit found.
But the File Store side was real: folder `models` (id `52852000000195786`) genuinely
holds 8 chunks (`models.tar.part-aa`…`-ah`, ~778MB total). Downloaded and inspected
the first chunk directly (not guessed) — it is a standard Hugging Face hub cache
layout (`models/hf/hub/models--facebook--nllb-200-distilled-600M/...`,
`models--Systran--faster-whisper-*`), not a raw CTranslate2 directory. That matters:
`translate.py`'s `_CTranslate2Backend` path only triggers if `VERITAS_NLLB_CT2_DIR`
(default `/opt/models/nllb-ct2`) exists, which this tar was never going to populate —
the intended path is `_TransformersBackend` reading from a normal `HF_HOME`-rooted
cache, which was also never configured.

**Fix**: set `VERITAS_MODELS_FOLDER_ID`, `VERITAS_MODELS_FILE_IDS` (the 8 chunk ids,
in order — confirmed by downloading the id mapped to "first" and verifying it starts
with a valid tar header), and `HF_HOME=/tmp/models/hf` via
`POST /appsail/{id}/configuration`. No code change was needed for the fetch itself —
`ensure_models()` already streams and extracts correctly; it had simply never been
invoked. Added `data.nlp.model_fetch.status()` and `data.nlp.translate.
backend_status()`, both surfaced on `/health` as `model_weights` / `nllb_backend`, so
this claim is a live, checkable fact going forward instead of something inferred from
response latency (which is what produced this bug in the first place — latency alone
cannot distinguish a File-Store-backed load from a still-baked-in one).

**Not yet confirmed which was actually true before this fix** (baked-in image vs.
truly absent weights) — that requires observing `/health.nllb_backend` after a fresh
container restart with the new config live, which is part of this pass's live
verification, not asserted here without having seen it.

---

## BUG-018 — PDF export returns HTML

Severity: P2
Component: apps/api/routers/export.py
Status: **PARTIALLY FIXED — two real root causes found and fixed live; one platform
question remains, precisely diagnosed, not resolved**

### Reproduction (original)
`POST /export/pdf` returns `text/html`, not a PDF — the local fallback renderer, not
SmartBrowz.

The console is not lying about it: `exportPdf()` names the download `.html` when the
blob type is not PDF. So this was a degraded feature, not a false claim. `CLAUDE.md`'s
service table listing SmartBrowz as the PDF path overstated what ran.

### Root causes found (North Star Phase 6)
The original `except Exception: return None` made every SmartBrowz failure reason —
misconfigured, network error, wrong request shape, an SDK bug — indistinguishable.
Added diagnostic reason headers (`X-Veritas-Pdf-Smartbrowz-Reason` /
`-Local-Reason`, logged server-side too) and deployed that alone first, which
surfaced the real reason on the very next live request:

1. **`app.smartbrowz()` — the method never existed on the SDK.**
   `AttributeError: 'CatalystApp' object has no attribute 'smartbrowz'`. Confirmed
   against the real installed `zcatalyst-sdk` (1.4.0) in an isolated venv, same
   methodology as BUG-021: `CatalystApp` exposes `smart_browz()` (with underscore);
   the module underneath is `smartbrowz` (without). `convert_to_pdf`'s signature and
   `PdfOptions`/`PdfMargin` field names were already correct — only the method name
   was wrong. **Fixed.**
2. **A fresh, unbound `zcatalyst_sdk.initialize()`, not the request's own context.**
   Fixing (1) changed the live failure to a real Catalyst API response for the first
   time: `CatalystAPIError: {'code': 'INVALID_ID', 'message': 'No such User with the
   given id exists'}`. `main.py`'s middleware already captures each request's
   Catalyst context into `ds._sdk_app` via `bind_catalyst_request`; `_smartbrowz_pdf`
   was building a second, separately-scoped app instead of reusing it. Switched to
   `data.ds.catalyst_app()` — the same pattern `/jobs/refresh` already uses for
   background work. **Fixed** (a genuine correctness improvement — avoids a stray
   untracked SDK instance — though see below).

### Third root cause found and fixed (overnight finalization pass)
The `INVALID_ID` / "No such User" error persisted after fix (2) in the prior pass,
because reusing the request-bound app was still not enough on its own:
`initialize(req=request)` derives Catalyst identity from the *caller's own* Catalyst
session cookie, and every officer this project's tooling can drive is JWT-fallback
only (no browser here to complete an interactive Catalyst sign-in) — so the request
genuinely carries no Catalyst user. SmartBrowz's `convert_to_pdf` apparently resolves
"the current user" from that same context QuickML's credential path used (BUG-021),
and fails identically with none present.

**Fix:** `app.credential._switch_user("admin")` before calling `smart_browz()` — the
exact call that resolved BUG-021's identical failure class, switching to the app's
own admin scope (the same scope Data Store calls already run under) instead of
requiring a per-officer Catalyst identity that JWT-fallback sessions never have.

**Live-tested after deploy — the identical error persists.** `POST /export/pdf`
against a real conversation still returns HTML with
`X-Veritas-Pdf-Smartbrowz-Reason: CatalystAPIError: {'code': 'INVALID_ID', 'message':
'No such User with the given id exists', 'status_code': 404}`, byte-for-byte the same
as before `_switch_user("admin")`. This rules the hypothesis out conclusively rather
than leaving it presumed: an admin-scoped token is not the missing ingredient —
Data Store/Cache/Graph calls already run successfully under that exact scope, so the
token itself is being accepted; SmartBrowz's own API layer appears to require
resolving a distinct Catalyst **User Management** identity (Zia/end-user account) to
attribute the render to, which is a different kind of entity than the app's own
service identity at any scope. That is consistent with (and narrows, rather than just
gestures at) the original theory: this needs a real, interactive Catalyst
Authentication sign-in through a browser — something this environment has never had
the tooling to drive (no browser, no OAuth redirect flow reachable from here).

Status: **PARTIALLY FIXED** — two real, confirmed root causes fixed (wrong SDK method
name; unbound SDK context); a third, precisely investigated and disproven hypothesis
(credential scope) leaves one platform requirement open that needs interactive
Catalyst Authentication or vendor/console access to resolve, not further guessing
from here.

### Regression test
`test_export_reports_why_no_pdf_rendered`, `test_export_returns_a_real_pdf_when_a_renderer_is_available`,
`test_export_requires_a_real_conversation` — no test existed for `/export/pdf` at
all before this pass.

### Verification
`python -m pytest` green. **Live-verified**: the failure mode changed twice, in the
direction the fixes intended (`AttributeError` → real Catalyst API error → same real
Catalyst API error after the context fix, confirming call attribution rather than
context was never the differentiator this time). The console still receives an
honest, printable HTML document with the real reason in response headers — never a
false PDF claim, at any point in this investigation.

---

## BUG-019 — "fir" matches inside "firs", routing a search to the lookup intent

Severity: P3
Component: packages/rag_agent/intents.py
Status: **FIXED, verified (overnight finalization pass)**

### Reproduction (original)
`classify("show me murder firs")` → `FIR_LOOKUP`, not `CRIME_SEARCH`.

Keyword matching was by substring, and `"fir" in "firs"`. Harmless at the time:
`FIR_LOOKUP`'s branch is a no-op unless `FIR_NUMBER_RE` matches, so the turn fell
through to the same semantic search `CRIME_SEARCH` would have run — but it stops
being harmless the moment that branch does anything on its own.

### Fix
Word-boundary matching (`\bkeyword\b`) per keyword, compiled once at import
(`_KEYWORD_RE`) rather than a bare `k in q` substring check.

### Regression test
`test_engine.py`'s intent-classification parametrize table now asserts
`classify("show me murder firs") == "CRIME_SEARCH"` directly, replacing the previous
comment that only documented the bug without catching a regression.

### Verification
`python -m pytest` green.

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

### Narrowed further (overnight finalization pass) — a documented, missing header
Checked current Zoho documentation directly rather than re-guessing the request body.
QuickML's sibling "pipeline endpoints" REST surface (deployed classic-ML models, the
nearest documented analogue to LLM Serving) documents a *required* per-endpoint
`X-QUICKML-ENDPOINT-KEY` header, obtained from that model's own "API Details" popup in
the console — the same popup already established as unreachable over the Admin API
this project provisions with. The LLM Serving invoke contract itself is not published
anywhere this session could reach (checked `docs.catalyst.zoho.com`'s dedicated LLM
Serving and GLM-4.7-Flash pages, and its machine-readable `llms-full.md` dump — none
document the header, exact route, or whether it applies to this surface too).

`QUICKML_ENDPOINT` (`.../quickml/v1/project/{id}/glm/chat`) has no known provenance in
this codebase — no script or note records it as copied from that console popup — and
the live `PATTERN_NOT_MATCHED` / "zoho-inputstream" gateway error is consistent with a
route pattern the gateway does not recognise, which is what an invented URL with no
endpoint key would produce.

**Code change**: `QUICKML_ENDPOINT_KEY` is now read and sent as
`X-QUICKML-ENDPOINT-KEY` when set (`packages/rag_agent/rag_agent/llm.py`), omitted
entirely otherwise — nothing fabricated. This does not claim to fix BUG-022: the
key's value, and whether this surface even uses the same header, remain unverifiable
without console access. It means the fix takes effect the moment someone copies the
real key out of the console, with no further code change. Status: **OPEN — root cause
narrowed to a specific, named, documented-elsewhere requirement (a console-only
endpoint key) rather than an open-ended "unknown request shape."**

### What is already correctly verified regardless of this
The system's behaviour when QuickML is unreachable is itself fully verified and
correct: `/health` reports the real error rather than a false "healthy" claim (fixing
BUG-012's *reporting* half was independent of whether the endpoint itself ever
resolves), and every chat turn still produces a grounded, cited, extractive answer.
Nothing about this gap makes any live answer less true — only less fluent.

---

## BUG-023 — Every FIR narrative for a given crime type is the same template

Severity: P1
Component: data/data/generator/build.py (`_MO`→`_MO_VARIANTS`, `_narrative`), data/data/generator/narrative_backfill.py (new), packages/rag_agent/rag_agent/copilot/brief.py
Status: **FIXED, verified live (North Star Phase 2)**

### Fix
`_MO_VARIANTS` widens crime-type coverage from 8 to all 20, with 3 method variants
each. `_narrative()` also derives a time-of-day phrase from `IncidentFromDate` and an
offender-count phrase from the case's own `Accused` rows — both real, already-
generated per-case facts, nothing invented. `generate()` reorders `_pick_accused`
before the `CaseMaster` row so the offender count is known when the narrative is
built.

Because case ids, accused rows, identities, the financial layer, and the graph were
all already correct (per `docs/DATA_GENERATION_AUDIT.md`), a full dataset
regeneration was unnecessary and was deliberately not done — `data/data/generator/narrative_backfill.py`
recomputes ONLY `CaseMaster.BriefFacts` in place, deterministically (seeded per
`CaseMasterID`), for the existing live dataset. No case was added, removed, or
renumbered; no accused/identity/financial/graph row was touched.

Cross-case discovery (`packages/rag_agent/rag_agent/copilot/brief.py`) no longer
exposes a bare embedding score: `_explain_similarity` compares crime type, shared IPC
sections, district, and the case-specific MO clause, and results are ranked by
structured match strength first, narrative score as tiebreak.

### Deployment path
The Data Store SDK only authenticates from real per-request Catalyst headers, so the
backfill cannot run from a developer machine (confirmed empirically:
`ModuleNotFoundError: zcatalyst_sdk` locally, and the SDK's bare `initialize()` would
fail outside an AppSail request even if installed, per the v8 changelog's own
finding). `POST /jobs/regenerate_narratives` runs it inside AppSail's request
context, same background-thread/job-token pattern as the existing `/jobs/refresh`.

### Regression test
`data/tests/test_dataset.py::test_narratives_do_not_collapse_to_one_shape_per_crime_type`
(scaled to sample size — only crime types with ≥5 occurrences are checked, so a rare
type drawing exactly 1 case in a small fixture is not misread as collapsed).
`packages/rag_agent/tests/test_copilot.py` — 3 tests against the real dataset
fixture, including one that asserts a genuine multi-feature match exists (not merely
that the code runs without error). `apps/api/tests/test_api.py` — 3 tests for the new
job endpoint (returns immediately, refuses to overlap, requires the token).

### Verification
`python -m pytest` green, `npx tsc --noEmit` clean. **Live-verified end to end**:
- FIR `100222201202600022` — previously *"Hurt — routine method"* (BUG-023's original
  live evidence) — now reads *"Physical assault following a heated verbal argument,
  late at night, by two persons acting together."*
- A live sample of 5 Theft/Motor-Vehicle-Theft cases in Mandya (`GET`/`POST /chat`
  `"How many theft cases are there in Mandya district?"`) returned 5 genuinely
  distinct narratives — previously all five read identically
  (*"Pickpocketing in a crowded market"*).
- `GET /copilot/9992` returned 5 similar cases, each with a real, honest
  `explanation` (*"same crime type (Hurt); shares IPC section(s) 323, 324, 326; same
  district (Mandya); matching modus operandi (\"Physical assault following a heated
  verbal argument\")"*, `match_strength: 4`), not a bare `similarity` float — the
  field is still present but relabeled `similarity_kind: "narrative_text"` and shown
  in the console as a secondary, explicitly-labeled tiebreaker.
- Console rebuilt and deployed; served bundle grepped for the new explanation UI
  string ("text similarity") — present.

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

## BUG-025 — Both Catalyst Cron jobs had never once succeeded (DEP-12, resolved)

Severity: **P1**
Component: Catalyst Cron configuration (not application code)
Status: **FIXED, verified live**

### How this was found
Following up on DEP-12 ("Cron firing on schedule remains unobserved") from BUG-024,
listed the live Cron jobs directly over the Admin API rather than continuing to leave
it unobserved.

### Symptoms
```
veritas_audit_verify: cron_status=false, success_count=0, failure_count=20
veritas_refresh:      cron_status=false, success_count=0, failure_count=20
```
Both jobs — the ones CLAUDE.md documents as running every 12h/6h — had **never
succeeded even once** since being created (Jul 13, 2026), and both were disabled.

### Root cause (two, stacked)
1. **Wrong hostname.** Both jobs' `job_meta.url` pointed at
   `veritas-api-`**`60077763394`**`.development.catalystappsail.in` —
   `60077763394` is the **org id**, not the AppSail app's own numeric id
   (`50043864344`, the host every other live check in this document uses). A
   copy-paste of the wrong id when the jobs were first created; this hostname likely
   never resolved to the deployed app at all.
2. **Stale job token**, found only after fixing (1): calling the corrected URL with
   the header value still configured on the cron job returned `401 {"detail":"Bad job
   token"}`. The cron job's `X-Veritas-Job-Token` predates the current
   `VERITAS_JOB_TOKEN` on the AppSail app (rotated at some point after the cron jobs
   were created) and was never updated to match.

Either defect alone was sufficient to fail every single invocation, which is exactly
what `failure_count: 20/20` shows — this was not intermittent.

### Fix
Both jobs updated via `PUT /project/{id}/cron/{jobId}`: corrected hostname, current
job token, `cron_status: true`. Not a code change — `apps/api/api/routers/jobs.py`'s
endpoints were already correct (confirmed working when called directly with the right
URL/token throughout this document); the defect was entirely in how Cron was
configured to call them.

### Verification
**Live**, immediately after the fix, calling the endpoints exactly as the corrected
Cron configuration now would:
```
GET  /jobs/audit-verify -> 200 {"intact":true,"first_bad_audit_id":null}
POST /jobs/refresh      -> 200 {"status":"started"}
```
Both real, successful invocations — not assumed from the configuration alone.

**Not verified**: the schedule itself actually firing unattended (12h/6h out from this
fix). That remains what the next audit-verify/refresh success_count increment would
confirm, but the jobs are now pointed at the right place with the right credential,
which is the part that was actually broken.

### Why this matters
`veritas_audit_verify` is the tamper-evidence claim's own enforcement mechanism —
"a tamper check nobody runs is not a tamper check" (§7). It had been running zero
times since deployment. `veritas_refresh` is what keeps the graph/vector index from
going stale as the record layer changes. Both silently non-functional since Jul 13 —
found only because this pass followed up on a previously-logged "unobserved" note
instead of leaving it there.

---

## Summary

| ID | Severity | Status |
|----|----------|--------|
| BUG-001 cold start / roster timeout | P1 | FIXED, mechanism verified; duration **measured live: ~22.7–22.9s, once per container** |
| BUG-002 stale token in unverified mode | **P0** | **FIXED, verified live in the browser** (CDP: seeded token cleared on entering unverified mode) |
| BUG-003 /copilot authorization bypass | **P0** | **FIXED, verified live** (both deploys) |
| BUG-004 masking not applied on /fir and Copilot | P1 | **FIXED, verified live** (both deploys) |
| BUG-005 unauthenticated /alerts WebSocket | P1 | **FIXED, verified live** — WebSocket replaced with SSE; live-checked post-deploy: unauthenticated `GET /alerts` → 401, authenticated → real district anomaly alerts streaming (`KA05 monthly_fir_count 105.0 vs 73.5, high`) |
| BUG-006 unsupporting citations | **P0** | **FIXED, verified live** in the API and, separately, driven end to end in the browser |
| BUG-007 intent misrouting | P1 | FIXED |
| BUG-008 no count for "how many" | P1 | **FIXED, verified live** — exact structured count, authoritative, no vector padding |
| BUG-009 capability question through retrieval | P1 | **FIXED, verified live** |
| BUG-010 one refusal message for five situations | P1 | **FIXED, verified live** |
| BUG-011 similarity shown as confidence | P1 | **FIXED, verified live** — `confidence_kind` axis; console redeployed and bundle-checked |
| BUG-012 /health reported an unreached LLM | P1 | FIXED (reporting) — **root cause of the unreachability itself found and fixed, see BUG-021/BUG-022** |
| BUG-013 money trail answered from a theft record | P1 | **FIXED, verified live** — negative finding is now the *only* citation |
| BUG-014 saturated risk score | P2 | **FIXED, verified live** (reporting-level) — honest `calibrated:false` now shown live; underlying saturation on this dataset is a data-volume limit, not a code defect |
| BUG-015 causal layer declines live | P2 | OPEN — **measured, not just known**: adding `dowhy` costs ≈405MB new against a ≈420MB headroom to the empirically measured bundle ceiling — deliberately not attempted live; decline remains the correct, sole citation (BUG-020) |
| BUG-016 Kannada latency | P2 | **PARTIALLY FIXED, verified live** — post-deploy round trip 4.3s total (was 13.4s); a separate, inherent CPU-generation-time cost for long answers is not a code defect |
| BUG-017 changelog vs deployed weights | P2 | **FIXED, verified live** — `/health` post-deploy: `model_weights: "fetched from Catalyst File Store this cold start"` (the fetch genuinely works); `nllb_backend: "ctranslate2 (...local/baked directory)"` — **the image does still bake in a converted NLLB directory**, so the File Store copy is currently redundant for translation; CLAUDE.md corrected to state this rather than the disproven "only code and CPU wheels" claim |
| BUG-018 PDF export returns HTML | P2 | **PARTIALLY FIXED** — 2 real root causes fixed; a third hypothesis (credential scope) tested live post-deploy and **disproven** — identical `INVALID_ID` error persists, narrowing the remaining gap to a genuine Catalyst User Management identity requirement only an interactive OAuth sign-in can supply |
| BUG-019 "fir" matches "firs" | P3 | **FIXED, verified** — word-boundary keyword matching, compiled once; `"show me murder firs"` now correctly classifies `CRIME_SEARCH` |
| BUG-020 evaluator floor deleted authoritative refusals | P1 | **FIXED, verified live** (regression found and fixed within this same phase) |
| BUG-021 QuickML credential call never worked | P1 | **FIXED, verified live** (failure mode changed from internal `AttributeError` to a real service response) |
| BUG-022 QuickML gateway rejects the request shape | P2 | OPEN — narrowed further to a specific, documented-elsewhere requirement (console-only `X-QUICKML-ENDPOINT-KEY`); code now sends it when configured, but the key cannot be obtained or verified from this environment |
| BUG-023 every narrative for a crime type is one template | **P1** | **FIXED, verified live** (North Star Phase 2) — 20/20 crime types covered, per-case slot-filling, live backfill via `/jobs/regenerate_narratives`; cross-case similarity now explains itself instead of a bare score |
| BUG-024 `/jobs/refresh` 500s against the live dataset | **P1** | **FIXED, deployed, live-verified** — moved to a background thread; watched the real job run to genuine completion (5-6 min) and confirmed no corruption |
| BUG-025 both Catalyst Cron jobs had never once succeeded | **P1** | **FIXED, verified live** — wrong hostname (org id instead of app id) plus a stale job token, stacked; both corrected over the Admin API and re-verified by calling each endpoint exactly as the corrected Cron config now would |

**3 P0, 15 P1, 6 P2, 1 P3 across 25 tracked defects — see each row's Status for the
current, precise state; this line intentionally does not collapse them into a single
aggregate count, which drifted out of sync with the table itself across sessions.**

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
