# Veritas — Work Log

Chronological, append-only. Each entry: what was done, why, evidence. Prose history lives
in `CLAUDE.md`'s changelog and `docs/PHASE1_FAILURE_LOG.md`; this is the terser, dated
log a future session can skim to see what happened without re-reading either in full.

---

## 2026-08-26 — North Star hardening pass

Ran the full 23-section "North Star hardening + industry-baseline completion" audit.
Re-established current state from the repo + live system rather than trusting prior
docs at face value (found one place they'd already drifted — see BUG-027 below).

**Re-audited live, first:**
- `/health`, Cron config (Admin API), `/chat`, `/alerts`, `/export/pdf`, `/person/{id}`,
  `/fir/{id}` — all checked directly, not assumed from docs.
- Found: `veritas_refresh` Cron had a real unattended success since BUG-025's fix
  (0→1); `veritas_audit_verify` did not (0/20→0/21) — the URL/token fix alone hadn't
  actually fixed the schedule for that one job.

**Fixed (commit `152c313`, deployed `52852000000204688`) — the most consequential finding
this pass:**
- **BUG-028 (P0)** — "Does X have priors?" had been silently answering "crime type not
  recorded, status not recorded" for every case, in production, for the flagship
  capability `CLAUDE.md` §0 names as the reason identity resolution exists at all. Found
  while live-testing multi-turn pronoun resolution with a fresh pronoun ("her"). Root
  cause: `person_record()`'s query already spent 3 of ZCQL's 4-JOIN cap reaching a case
  id via the identity table, leaving no budget for the joins that resolve crime-type/
  status/district names — every answer silently degraded to case numbers and dates.
  Fixed by chaining a second, separately-budgeted, already-correct query
  (`sql_agent.cases_by_ids`) instead of asking one query to exceed the cap. 2 new tests,
  confirmed to fail against the pre-fix code first. Live-verified: the same query now
  returns full case detail (crime type, district, status, narrative) for all 12 of the
  test subject's cases.

**Fixed (commit `d5f0798`, deployed `52852000000316042`):**
- `/jobs/audit-verify` was running `verify_chain()` synchronously — the exact call that
  pays BUG-001's ~23s cold-container mirror-hydration cost inside a request Cron
  abandons long before that. Applied `/jobs/refresh`'s existing background-thread
  pattern; kept a `sync=true` escape hatch for a human running the check by hand.
  5 new tests. Logged as **BUG-027**.

**Ran a real CDP session** (headless Chrome, `--remote-debugging-port`, driven over
Node 22's global WebSocket per the `veritas-console-verification` pattern) against the
live console for the first time in several sessions with actual browser tooling
available. Moved 10 previously PARTIAL/UNKNOWN UI rows to VERIFIED: EN/KN toggle,
citation chip click, evidence-thread line draw, reasoning-trace expand, Copilot overlay
(all 4 sub-panels), Copy-to-clipboard, case-explorer search box, "Ask about this case"
per card, Export PDF's enabled state (previously only the disabled state was verified).

**Found live during that session, documented, not fixed:** BUG-026 — Copilot leads
render a person's `vx_person.CanonicalName` ("Soom Nadkarni") while the same case's own
accused list shows the as-filed `Accused.AccusedName` ("Suma Nadkarni") for the same
`PersonUID`, with no visible link between them. Confirmed via `/fir/9992` and
`/person/877` that this is entity resolution working correctly (not a data bug) — just
an unexposed cross-reference. Left open as a scoped, documented finding (see
`docs/QA_FUNCTIONALITY_MATRIX.md` and `docs/PHASE1_FAILURE_LOG.md`).

**Fixed (commit `21b2bd9`, console redeployed):**
- `exportPdf()` returned `void`, so a 200-with-HTML-body (BUG-018's fallback) downloaded
  silently with no indication "Export PDF" hadn't produced a PDF. Now returns whether the
  blob was a real PDF; the console shows a brief note when it wasn't. Verified live by
  grepping the deployed bundle for the new string.

**Fixed (commit `1fb0bdc`, generator-only, not deployed to the live API):**
- `DATA_GENERATION_AUDIT.md` §19's minor gap: the identity-resolution answer key wasn't
  persisted the way the AML labels already are. `run.py` now writes
  `IDENTITY_ANSWER_KEY`; new `data/generator/score_identity.py` recomputes
  precision/recall/F1 from it against whatever `vx_accused_identity` is currently bound,
  via cluster-size combinatorics (fast at full dataset scale, unlike
  `fellegi_sunter.py`'s own O(n²) self-check loop). 3 new tests. Deliberately not
  exercised against the live 10k-case dataset — that dataset predates this fix, and
  regenerating it just to backfill a P2 auditability gap would violate this project's
  own "don't regenerate casually" rule.

**Re-confirmed unchanged (BLOCKED, correctly so):**
- QuickML (`BUG-022`) — checked the live AppSail configuration directly:
  `QUICKML_ENDPOINT_KEY` is not set. Still `PATTERN_NOT_MATCHED` on every call. `/health`
  correctly reports the degradation.
- PDF export (`BUG-018`) — SmartBrowz still `INVALID_ID`/"No such User"; the in-container
  local-renderer fallback also confirmed absent (`no Chromium-family browser found on
  this host`) — a fact not previously stated this explicitly. The HTML fallback body
  itself was inspected directly and is a genuine, well-formed, citation-carrying
  conversation record — a usable artifact, just not a PDF.
- Aequitas (`ML-12`) — unchanged, still an out-of-band script by design.
- `dowhy` (`BUG-015`) — unchanged, still measured-and-declined on image-size grounds.

**Not pursued further this pass, and why:**
- AML detector positive-case verification (`ML-09`/`ML-10`) — a local
  `.veritas/aml_labels.json` exists but couldn't be confidently matched to the live
  dataset's transaction numbering; one admin ZCQL REST attempt failed
  (`INVALID_URL_PATTERN`) and was not retried further, matching this project's own rule
  against repeated guessing at a live API's exact request shape.
- Full click-through of every remaining UI control (voice toggle, case-status filter
  chips, viz pane switcher, MapLibre render) — voice is hardware-gated in every
  environment this project has run in; the rest are named in the QA matrix for the next
  pass rather than rushed here.

**Test suite**: 317 collected, all green throughout (10 new this pass: 5 audit-verify +
3 score-identity + 2 sql_agent/BUG-028; the 251/196/189-style counts in older docs were
already stale before this pass — `pytest --collect-only -q` is the way to get the real
current number, not a changelog entry). `npx tsc --noEmit` clean after the frontend
changes.

**Docs updated**: `docs/QA_FUNCTIONALITY_MATRIX.md` (many rows), `docs/PHASE1_FAILURE_LOG.md`
(BUG-026, BUG-027, summary counts), `docs/VERITAS_HANDOFF.md` (created), this file
(created).

---

## 2026-08-26 (later, same day) — Conversational architecture pass

A separate mega-prompt this pass: not a North-Star gap-closing audit, a question about
the conversational layer's own architecture — how much of it was genuinely conversational
(explicit state, follow-ups that build on each other) versus intent classification over
isolated deterministic tools that happened to share a session id.

**Read the orchestrator/intents/state code first**, rather than assuming. Found:
`SessionFocus` (active_person/active_fir/active_location) already existed and persisted
across turns, and pronoun/named-entity resolution against it already worked — but nothing
let a follow-up talk ABOUT the open case itself ("what happened", "who's involved", "what
next", "prepare the briefing") or ABOUT the previous answer ("why these", "what
evidence") — every such question fell through to a literal-text vector search of the
words in the question, which could not possibly be about either. The Investigation
Copilot already had correct, tested logic for leads/similar-cases/briefing — it just
wasn't reachable from `/chat`, only from `/copilot`.

**Built (commit `2e1da7d`):**
- Seven new intents: `CASE_CONTEXT`, `CASE_PEOPLE`, a case-scoped branch of
  `SIMILAR_CASES`, `NEXT_STEPS`, `BRIEFING` (all gated on `SessionFocus.active_fir` via
  new `intents.NEEDS_CASE`, mirroring the existing `NEEDS_SUBJECT` pattern), plus
  `EXPLAIN_REASONING`/`EVIDENCE_FOR` (read the previous turn's own stored citations/trace)
  and `CASE_LOCATIONS` (tallies districts over the previous turn's cited FIRs). The three
  Copilot-backed intents reuse `copilot.brief.leads_for_case`/`similar_cases_for`/
  `generate_copilot_brief` directly (promoted from private helpers) rather than
  duplicating the logic.
- Ambiguous person names (a tied top match by `record_count`, no clear leader) now ask
  which one instead of silently picking the first.
- Every case-scoped branch re-validates station scope on EVERY use, through the same
  scoped `fir_by_id()` query `FIR_LOOKUP` already uses — not trusted from whenever
  `active_fir` was first set. `active_fir` being present in session state is not itself a
  permission.
- 33 new regression tests (350 → collected count at this point), covering routing,
  authorization, focus persistence, and the meta-question fallbacks.

**Found and fixed while live-verifying (this is where the pass earned its keep):**
- **The persisted-focus bug (the most consequential single fix this pass)**:
  `node_orchestrate` persists `SessionFocus` BEFORE retrieval runs, but `FIR_LOOKUP` (and
  the new `CASE_PEOPLE`) resolve `active_fir`/`active_person` DURING retrieval — that
  resolution was never saved. "Open FIR X" followed one turn later by "What happened?"
  forgot X was ever opened, discovered live over curl before it was ever unit-tested.
  Fixed by persisting again at the end of `node_retrieve`. Without this fix, none of the
  new case-scoped intents could ever fire on turn 2 of a real conversation — the feature
  work above would have shipped genuinely dead.
- **`data/data/nlp/entities.py` NER bug**: "Tell me more about Usha Naika" resolved to a
  DIFFERENT "Usha" (25 records, the database's most prolific one) and answered about her
  at full confidence — a wrong-person answer, not an honest refusal. Root cause:
  PERSON-span extraction spanned only from the first to the last POOL-matching token in a
  capitalised run; "Usha" is in the 271-name `ka_names.csv` sample, "Naika" is not, so the
  span clipped to just "Usha". Fixed by extending the span from the pool-matched core
  outward through adjacent capitalised tokens, stopping only at a query stopword or a
  known place name — verified this doesn't regress the existing "Was Ramesh Gowda" →
  "Ramesh Gowda" (excludes "Was") test case. (commit `d26f3fd`)
- **`PERSON_HISTORY` keyword gap**: "What previous cases involve her?" (plural) matched no
  keyword ("previous case" was singular-only) and fell to `CRIME_SEARCH`'s bare "cases",
  answering with a global 10,000-case count instead of the named person's own record.
  (commit `cc46f75`)

**Live-verified, real deployment, real console — not curl alone:**
A single session was driven through a real 14-turn investigation, both over curl/SSE
and through the actual console via a headless-Chrome/CDP session: open FIR → case
context → accused (network view, real PageRank-sized nodes) → named-person priors →
associates → why-these → case-scoped similar cases (structured explanation, not a bare
score) → their geography (map view) → financial trail (honest negative finding) →
what-evidence-supports-that → next steps (Copilot leads) → prepare the briefing (Copilot
draft). Also verified: an unknown FIR refuses correctly; the capability question answers
without touching records; an IO's cross-station refusal holds across BOTH the FIR lookup
and its case-scoped follow-up (no leak); a Kannada follow-up ("ಏನಾಯಿತು?") round-trips
correctly through a brand-new intent with zero Kannada-specific code, because translation
runs before intent classification. 8 screenshots committed to
`docs/screenshots/2026-08-26-conversational-architecture/` — this project's first
screenshot set kept in the repo rather than a session scratchpad.

**QuickML**: re-checked directly (fetched the live AppSail `configuration.environment.
variables` object over the Admin API) rather than trusted from a prior pass's note.
`QUICKML_ENDPOINT_KEY` is still absent. No code change — `llm.status()` already
distinguishes "configured, not yet contacted" / "deterministic (LLM degraded: ...)" /
"deterministic (QuickML not configured)" / a real `quickml (model)` success, which is
what this pass's mega-prompt asked health reporting to do. Confirmed still BLOCKED, not
faked.

**Deploys**: three, each live-verified before moving to the next — `52852000000317055`
(the conversational-architecture feature commit), `52852000000325022` (the NER fix),
`52852000000318035` (the keyword fix). No console/frontend deploy — nothing in
`apps/web/` changed; every new capability is reachable through the existing chat pane.

**Test suite**: 352 collected, all green throughout (35 new: 33 conversational + 1 NER +
1 keyword regression test).

**Docs updated**: `docs/VERITAS_HANDOFF.md` (rewritten for this pass), this file,
`docs/QA_FUNCTIONALITY_MATRIX.md` (RAG-24–33 added, "does NOT yet cover" section
updated), `docs/screenshots/2026-08-26-conversational-architecture/` (new).

**Not done, by the mega-prompt's own stop condition**: no differentiator features, no
North-Star P0/P1 gap-closing beyond what this pass's own live verification happened to
surface. `docs/CAPABILITY_TARGET_AND_GAPS.md`'s prioritized gap list is untouched.

---

## 2026-08-26 (later still) — "Final product pass": map made investigator-grade + a real conversational gap closed

A "VERITAS FINAL PRODUCT PASS" mega-prompt named the map a launch-blocking defect
("current screenshot shows a very dark canvas with scattered points and insufficient
geographic orientation") and asked for the conversational architecture to be verified,
not just described, against a live multi-turn session.

**Inspected before touching anything**, per the prompt's own instruction: compared the
already-committed `docs/screenshots/2026-08-26-conversational-architecture/
06-case-locations-map.png` (a real CASE_LOCATIONS answer, 5 cases, all in Mandya)
against `apps/web/components/viz/MapView.tsx`. Confirmed the complaint was real and
found the exact cause: `fitBounds({maxZoom: 11})` zoomed a tight cluster in so far that
every neighbouring district dot/label fell outside the viewport — the prior pass's own
"Phase 4" fix (real district labels + scale control) only ever held for a broad,
spread-out query; it was never tested against a tight one, which is exactly what a
case-scoped follow-up produces.

**Fixed (`apps/web/components/viz/MapView.tsx`, `apps/web/app/globals.css`,
commit `2a903ba`):**
- `maxZoom` capped at 9 (was 11) — a tight cluster now keeps 2-3 neighbouring district
  labels in frame instead of zooming past all of them.
- A legend added: amber dot = individual cited FIR location, green→amber→red ramp =
  hotspot density. Neither existed before — there was no way to tell an exact record
  from a modeled estimate on the map itself.
- Hotspot polygon fill/line opacity raised (0.26→0.4, 1.6→2px) so the aggregate region
  is visible against the dark basemap where large enough to render, distinct from the
  individual points inside it.
- No district boundary polygons added — none exist in this dataset, and the prompt
  explicitly forbade fabricating geographic precision.

**Verified before AND after deploying**, both locally and live: ran the API locally
against the existing sqlite mirror (`data/.veritas/ds.sqlite3`, same 10,000-case
dataset) with the web dev server pointed at it — sidesteps a real platform fact worth
recording: AppSail's CORS preflight (`OPTIONS`) is answered at the platform edge for
exactly one allow-listed origin (the deployed console's own), not via the app's
`VERITAS_CORS_ORIGINS` env var, so a POST from `localhost:3000` straight to the live
API fails preflight with no CORS headers at all — a genuine, previously-undocumented
constraint on testing against the live API from local dev, not a bug in the app.
Screenshotted both the previously-broken tight-cluster query and a broad statewide one
via headless Chrome over CDP, then again against the live console after
`scripts/deploy-console.sh`. Screenshots committed to
`docs/screenshots/2026-08-26-map-investigator-grade/`.

**Live conversational sanity check** (not the full 19-turn golden script the prompt
specified — a shorter, targeted 9-turn session over curl/SSE against the live
production API, plus a 2-turn RBAC check under a different officer): FIR_LOOKUP →
CASE_CONTEXT → CASE_PEOPLE → a pronoun follow-up → EXPLAIN_REASONING → EVIDENCE_FOR →
CASE_LOCATIONS → a guilt-probability question → a Kannada round-trip; then a
station-scoped IO probing a FIR outside their station, twice.

**Found and fixed live (this is where the check earned its keep):**
- **RAG-34**: "Who is involved?" (CASE_PEOPLE, 2 accused, correctly leaves
  `active_person` unset since naming one of several would be a guess) followed by
  "Does he have priors?" fell to a bare `no_subject` refusal — the two names the
  previous turn had just shown were discarded entirely. This is exactly the gap the
  prior conversational-architecture pass's own handoff had predicted and deliberately
  left unbuilt ("consider whether CASE_PEOPLE's several-accused behaviour should also
  let a bare pronoun disambiguate against the specific candidates the previous turn
  named"). Fixed (`packages/rag_agent/rag_agent/orchestrator.py`,
  `_recent_person_candidates`, commit `2d382d4`): a pronoun with no active person now
  checks the previous turn's own stored `accused:` citations, and with 2+ named
  candidates, asks which one — reusing the EXACT `ambiguous_person` clarification path
  a tied name search already uses (RAG-32), sourced from `vx_conversation_turn`
  instead of a fresh search or any new persisted session-focus field. 2 new regression
  tests; the positive one confirmed to fail against the pre-fix code first (a bare git
  stash of the one changed file, per this project's own test discipline).
- A second bug in the same session: `CASE_LOCATIONS`'s "nothing to map" refusal reused
  `EXPLAIN_REASONING`'s "this is the first answer" message verbatim — false on turn 7,
  which is when it was actually observed. Given its own message
  (`nothing_prior_locations`); one existing test's assertion updated to match.

**QuickML**: re-checked directly against the live AppSail `configuration.environment.
variables` object (fetched over the Admin API, not trusted from a prior pass's note).
`QUICKML_ENDPOINT_KEY` remains absent. No code change — still correctly BLOCKED.

**Deploys**: console via `scripts/deploy-console.sh` (map fix); API via the relay
pipeline (`GET .../appsail/get-signature` → push `.github/relay-upload.url` →
`relay-deploy.yml` builds `Dockerfile.overlay` + smoke-tests the import → local
`PUT .../appsail/upsert`), deployment `52852000000325027`. Both independently
live-verified post-deploy against the real URLs, not assumed from a green CI run.

**Test suite**: 354 collected (352 → 354), all green throughout.

**Docs updated**: `CLAUDE.md` (v14 changelog + test count), this file,
`docs/QA_FUNCTIONALITY_MATRIX.md` (UI-24 rewritten, RAG-34 added, "does NOT yet cover"
section updated), `docs/VERITAS_STATUS.html` (extended its own existing "stale as of"
banner rather than rewritten in full — matches the pattern the prior pass already
established there), `docs/VERITAS_HANDOFF.md` (rewritten for this pass),
`docs/screenshots/2026-08-26-map-investigator-grade/` (new, 2 live screenshots + a
README explaining the defect and the fix).

**Not done, named rather than silently skipped**: the full 19-turn golden conversation
specified by the mega-prompt (including an explicit case-switch-and-back and a genuine
ambiguous-name tie) was not driven end to end through the live CONSOLE — the 9-turn
check above ran over curl/SSE against the live API, which exercises the identical
orchestrator/retrieval/synthesis code path the console calls but does not exercise
console rendering itself beyond the two map screenshots. A full UI judge-review
click-through (every panel, every failure state, every export path) was not repeated
in full this pass — the prior North Star hardening pass's own CDP verification of most
UI rows stands, re-confirmed only where this pass's fixes actually touched them (the
map). `docs/CAPABILITY_TARGET_AND_GAPS.md`'s Part 3 P0/P1 list remains untouched — narrative
diversity and the LLM-fluency gap (still QuickML-blocked) are still the largest named
items there.

---

## 2026-08-26 (later still) — Real geographic basemap

A "VERITAS MAP BASEMAP UPGRADE" mega-prompt judged the self-drawn dark-canvas map (real
district centroids labeled, but no roads, no terrain, no basemap at all underneath) as
still not good enough for a competition-final product, and asked for a real MapLibre +
OpenFreeMap basemap while keeping every existing Veritas overlay.

**Inspected `MapView.tsx` first.** The basemap was a flat `background-color` layer
(`MAP_BG = "#080d12"`), with `NEXT_PUBLIC_MAP_STYLE` already wired as an escape hatch for
a real style URL — the smallest sound integration was to change the *default* that
fallback resolves to, not to rebuild the component.

**Built (`apps/web/components/viz/MapView.tsx`, `apps/web/app/globals.css`,
`apps/web/components/viz/palette.ts`):**
- Default style is now `https://tiles.openfreemap.org/styles/liberty` (OSM-derived, no
  API key/registration/quota) — the fifth documented Catalyst exception (`CLAUDE.md` §2):
  no service in the catalog is a map tile provider. Only a viewport tile z/x/y crosses the
  network, never an FIR's coordinates.
- District reference dots/labels re-styled for contrast against a real (non-black)
  basemap: two-tone dot (light fill, dark ring), dark chip behind each name — the old
  low-opacity-white styling was tuned for a near-black canvas and would nearly vanish on
  liberty's pale cropland/light terrain.
- A compact `AttributionControl` added, styled to match the console's glass chrome — ODbL
  requires crediting OSM now that real tile data is in use, unlike the old canvas which
  had no third-party data to credit. The CSS that force-hid all attribution now hides only
  the MapLibre logo.
- Every other overlay (FIR points, hotspot polygons, legend, scale, v14's `maxZoom: 9`
  fix) is untouched. `MAP_BG` deleted from `palette.ts` — no remaining callers.

**Verified locally before deploying**: API on `localhost:8000` against the existing
sqlite mirror (`data/.veritas/ds.sqlite3`), console on `localhost:3000`, signed in via
`?as=DSP`, driven headlessly over CDP (Chrome `--headless=new
--remote-debugging-port=9222`). Four queries, each screenshotted and judged against a
"would a competition judge recognize this as Karnataka within seconds" checklist: a tight
Mandya cluster, a bare statewide-phrased query (correctly falls back to the true busiest
district — Bengaluru Urban, with the basemap's own "Bengaluru" label visible), a distant
district (Bidar, on the Telangana border, to prove re-centering works anywhere in the
state, not just near Bengaluru), and a district with no hotspot evidence (Kodagu — honest
refusal, graceful fallback to the case index, no broken map).

**Deployed** (`scripts/deploy-console.sh` — console-only; nothing in `apps/api` or the
packages changed) and **re-verified live** against
`https://veritas-60077763394.development.catalystserverless.in/app/index.html`, replaying
the same four queries plus one explicit no-subject refusal ("Show me the money trail").
One real platform fact surfaced along the way: the first live CDP attempt hit a cold
AppSail container mid-warm-up (the sign-in gate's own "still loading the duty roster" copy
handled it correctly — this was not a map bug); waiting for warm-up and retrying
reproduced identical rendering to local. The live dataset turned out to have hotspot
evidence for Kodagu where the local sqlite mirror didn't (a data-state difference between
the two backends, not a bug) and produced the most visually striking screenshot of the
pass — dense Western Ghats forest green around Madikeri, immediately recognizable as a
hill district.

**Test suite**: unchanged at 354 (frontend-only change). `npx tsc --noEmit` clean.

**Docs updated**: `CLAUDE.md` (v15 changelog, §2's exception table, §8), this file,
`docs/QA_FUNCTIONALITY_MATRIX.md` (UI-24 rewritten),
`docs/screenshots/2026-08-26-real-basemap/` (new — 4 local + 5 live screenshots + README),
`docs/screenshots/2026-08-26-map-investigator-grade/README.md` (marked superseded, kept
for history), `docs/VERITAS_HANDOFF.md`, `docs/VERITAS_STATUS.html`.

**Not done this pass**: true district *boundary* polygons — still not part of this
dataset, still correctly not fabricated rather than approximated. Pan/drag gesture
interaction was not driven live (a screenshot proves render correctness, not drag
behavior) — unchanged from v14's own note on this. The broader "19-turn golden
conversation through the console" and North Star P0/P1 gap-closing items named as
outstanding in the prior two entries remain outstanding — this pass was scoped to the
map, as its own mega-prompt asked.

---

## 2026-08-26 (later still) — Finishing pass: the 19-turn golden conversation, four
real bugs it found, and closing the last North Star MUST-HAVE

The item four consecutive prior handoffs had named as the top outstanding action. Built a
small CDP driver (Chrome `--headless=new --remote-debugging-port`, talked over Node 22's
global WebSocket) and drove one continuous 19-turn investigation through the actual
deployed console — signed in as DSP, subject FIR 100050504202300018 (Kidnapping,
Bengaluru Urban, 4 accused), with a case switch to an unrelated FIR and back (context
isolation) and a deliberately ambiguous pronoun at the end.

**First run (not committed) found four real, live bugs**, all in
`packages/rag_agent/rag_agent/`:

1. `orchestrator.py`'s `CASE_PEOPLE` branch only *set* `active_person` when exactly one
   accused existed; with several, it did nothing, leaving a stale person from an earlier
   turn/case silently "active" — so re-opening a different multi-accused case and asking
   a pronoun follow-up answered about the wrong (old) person instead of asking, exactly
   the case RAG-34's ambiguous-person clarification exists for. Fixed with an explicit
   clear.
2. `intents.py`'s `EXPLAIN_REASONING` regex required "why (are/were/did) you <verb>" or
   "why ... those <adjective>" with nothing in between — natural phrasing straight out of
   this session's own mega-prompt ("why did you *select* those cases," "why were those
   associates *surfaced*," passive, no "you") fell through to `CAUSAL` or a repeat of the
   prior topic intent. Widened the verb list and let one noun sit between "those" and the
   participle.
3. `intents.py`'s `NEXT_STEPS` keywords had "investigate next" (active) but not
   "investigated next" (passive) — "what should be investigated next," again straight
   from the mega-prompt, matched nothing and refused. Added the passive form.
4. `orchestrator.py`'s `node_retrieve` only skipped retrieval for refusals it decides
   itself (CAPABILITY, NOT_INFERABLE) or re-derives (guarded with `and not
   state.refusal_reason`, which stops it setting a DUPLICATE reason but does not return
   early when node_orchestrate already set one) — an ambiguous-person refusal clears
   `active_person`, so every specialist branch was correctly skipped, but the untargeted
   vector-search fallback at the bottom of `_run_specialists` has no such guard and
   searched anyway, handing the officer 5 unrelated criminal-profile citations in the
   Evidence rail right next to "I will not guess which one you mean." Fixed with an
   early return in `node_retrieve` whenever a refusal is already decided on entry.

Also fixed **BUG-026** (open since the prior North-Star hardening pass): Copilot leads
and the new `NEXT_STEPS` answer now show `"Canonical (filed as \"AsFiled\" on this FIR)"`
when entity resolution reconciled a romanisation variant, via a new `_lead_name()`
helper in `copilot/brief.py` — masked identically to every other name on that surface.

6 new regression tests (3 intent/state, 1 refusal-short-circuit, 2 BUG-026), each
confirmed to fail against pre-fix code first. **354 → 361 tests, all green.**

**Deployed twice** via the relay pipeline (one deploy for the intent/BUG-026 fixes, a
second for the refusal-short-circuit fix found by re-running the golden script after the
first redeploy) — plus one self-inflicted broken deploy commit (a `node -e ... >
sig.json` redirect that wrote an empty file because the async `fetch` hadn't resolved
before the shell redirect opened the file — caught immediately when the workflow failed
on an empty upload URL, fixed with a corrected commit within minutes). Both real deploys
polled to `deployment_status: success` and confirmed via `/health`.

**Second run (committed) verified all fixes live**: all 19 turns correct, including the
context-isolation check (turns 16-18 switch to an unrelated Mandya case and back; the
"who is involved" re-ask correctly names the original case's 4 accused, not the Mandya
case's people) and the ambiguous-pronoun clarification (turn 19 now asks which of the 4
accused is meant, and the Evidence rail is correctly empty rather than padded). Also
verified in the same live session: a Kannada round-trip follow-up, and — signed in
separately as IO — a cross-station authorization refusal for the same FIR ("No record
with that number exists within your access scope").

**One false alarm, caught and ruled out rather than reported**: the first run's
screenshot of "where are those cases concentrated?" looked like an untargeted, zoomed-out
statewide map. Traced to the CDP driver's own timing — MapLibre's `fitBounds` animation
is 900ms and the driver only waited 400ms after a turn finished streaming before
screenshotting. Raised to 1500ms; the second run's screenshot shows the map correctly
tight on the real Bengaluru-area FIR points. Not a product bug — recorded as a trap for
any future CDP harness against this console.

**QuickML and PDF export both re-confirmed BLOCKED by a direct live check** this pass
(the AppSail app's live config for QuickML's key; a real `/export/pdf` call against a
session with a turn for PDF) rather than re-asserted from a prior pass's note, per this
session's own instruction against repeatedly guessing at platform APIs already
root-caused. No code change for either; both fallbacks remain honest and correct.

**Test suite**: 354 → 361, all green.

**Docs updated**: `docs/VERITAS_HANDOFF.md` (rewritten for this pass), this file,
`docs/screenshots/2026-08-26-full-investigation-walkthrough/` (new — 25 screenshots + `log.json` +
README), `docs/QA_FUNCTIONALITY_MATRIX.md`, `docs/VERITAS_STATUS.html`.

**Not done this pass**: independently observing `veritas_audit_verify`'s Cron job's next
*unattended* fire (the fix is deployed and unit-tested; its own "does this actually
succeed with nobody watching" claim needs the schedule itself, or a deliberate wait, not
more code — out of this pass's chosen scope). The tied-name-search variant of RAG-32
(as opposed to the pronoun variant this pass's turn 19 exercised) still hasn't hit a live
`record_count` tie by chance. A from-scratch full UI click-through beyond what the golden
conversation itself exercised was not repeated — the prior passes' CDP verification of
most of the QA matrix's UI rows stands, unrepeated where this pass's fixes didn't touch
them.
