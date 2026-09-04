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

---

## 2026-08-27 — Finalization pass: an adversarial stress test found three real bugs,
Cron's unattended-fire question finally closed, repo hygiene

No browser/CDP tooling was available in this session's environment (no Chrome,
puppeteer, or playwright installed) — everything this pass verified live went over
direct HTTP/SSE calls to the production API, not through the console UI. Stated
plainly here and in the handoff rather than glossed over.

**Ran a fresh adversarial conversation against the live API** — deliberately different
phrasing from the already-passing 19-turn golden script ("tell me more about this
person", "what about the other person", "go back to the first case", a Kannada query
mid-session, "how many gangs operate in this district?"), per this pass's own
instruction not to spend the session re-proving what already worked. Found three real
bugs, all in `packages/rag_agent/rag_agent/`:

1. A Kannada query crashed the whole turn — a tokenizer `TypeError` from the
   CTranslate2 backend escaped `translation_agent.to_english`/`to_language`'s narrow
   `except TranslationUnavailable`. Both functions now catch any backend exception and
   degrade to English with an honest note (`agents/translation_agent.py`).
2. "How many gangs operate in this district?" (no person named) was answered as an
   ambiguous-PERSON clarification — `intents._PRONOUNS` treated bare "this"/"that" as
   an unresolved person reference unconditionally, so any subject-less question
   containing a determiner phrase ("this district") got routed into person-pronoun
   resolution whenever 2+ people were named in the previous turn. Fixed by excluding
   "this"/"that" immediately followed by a domain noun (`intents.py`).
3. "Go back to the first case" (no case-history stack exists) fell to a bare
   `CRIME_SEARCH` keyword score and ran a real semantic search, confidently returning 5
   unrelated cited records. New `CASE_REFERENCE_UNSUPPORTED` intent refuses honestly
   instead and leaves the currently open case untouched (`intents.py`,
   `orchestrator.py`, `evidence/evaluator.py`).

7 new regression tests (2 intent, 2 orchestrator, 3 translation-agent), each targeting
the exact live-reproduced failure. **361 → 369 tests, all green.**

**Deployed** via the relay pipeline (commit `37cc5c6` → fresh signed URL →
`relay-deploy.yml` builds `Dockerfile.overlay` on the runner → local `appsail/upsert`,
deployment `52852000000306055`, polled to `deployment_status: success`) and
**re-verified all three fixes live** afterward. One real platform fact surfaced: the
first Kannada re-check, run ~1-2 minutes after the deployment reported success, still
reproduced the pre-fix crash — a redeploy does not instantly retire every running
container instance. A retry shortly after succeeded end to end. Recorded in the
handoff so the next pass doesn't misdiagnose a too-early spot-check as a failed fix.

**Closed the one item every prior pass's handoff had left open**: listed the live
`veritas_audit_verify` Cron job directly (not a manual trigger) and found
`success_count: 1, failure_count: 0` — its BUG-027 background-thread fix has now had a
real unattended success on its own 12h schedule. `veritas_refresh` shows `3, 0` in the
same listing.

**Re-confirmed, directly, unchanged**: QuickML (`QUICKML_ENDPOINT_KEY` absent from the
live AppSail config), PDF export (`/export/pdf` still `text/html`), RBAC (an IO
correctly refused a cross-station FIR with no leak).

**Repository hygiene** (explicit user request): removed the two `.pptx` files and the
redundant `Prototype_Deck.pdf` from the repo root; renamed
`docs/VERITAS_NORTH_STAR.md` → `docs/CAPABILITY_TARGET_AND_GAPS.md` and
`docs/screenshots/2026-08-26-golden-19turn/` →
`.../2026-08-26-full-investigation-walkthrough/`, updating every path reference —
internal-jargon-free names for a judge browsing the repo tree, content unchanged.

**Test suite**: 369 collected, all green.

**Docs updated**: `docs/VERITAS_HANDOFF.md` (rewritten for this pass), this file,
`docs/QA_FUNCTIONALITY_MATRIX.md` (DEP-13, new bullet section), `docs/VERITAS_STATUS.html`
(stale-as-of banner extended), `SUBMISSION.md` (deck reference removed).

**Not done this pass, named rather than silently skipped**: no console/UI
re-verification and no new screenshots (no browser tooling available — see above); the
tied-name-search variant of RAG-32; voice pipeline, case-status filter chips, map
pan/drag, AML positive-case verification, `dowhy` — all unchanged from prior passes,
same constraints as documented there.

---

## 2026-08-27 (later still) — Catalyst-blocker resolution + industry-gap analysis

Prompt asked for a fresh, first-principles re-investigation of QuickML and PDF export
via the authenticated Catalyst CLI (not trusted from prior passes' notes), then either
the toast overlap or BUG-026 as fallback small fixes, then a live-research industry
gap analysis against Palantir Gotham/i2 Analyst's Notebook/Maltego.

**QuickML — re-investigated from the authenticated Catalyst environment directly,
confirmed BLOCKED for a concrete, newly-verified reason:**
- `catalyst project:list`/`catalyst help` (CLI v1.26.2, authenticated against the
  `Veritas` project) — no QuickML-related command exists anywhere in the CLI's
  command surface (only `ds:import/export`, `appsail:*`, `functions:*`, `client:*`,
  `slate:*`, `apig:*`).
- Minted an admin token (`scripts/catalyst-token.js`) and probed the Admin API
  directly for a QuickML discovery surface: `GET .../quickml/model`,
  `.../quickml/models`, `.../ml/model`, `.../quickml` — all `404
  INVALID_URL_PATTERN`. `GET .../connections` (Catalyst's OAuth-secret-manager
  feature, checked per this pass's own instruction to inspect Connections/secrets)
  returned `{"status":"success","data":[]}` — genuinely empty, nothing stored there
  either.
- Fetched the live AppSail app's configuration directly
  (`GET .../appsail/{appComputeId}`) and, separately, triggered a real `/chat` call
  and re-read `/health` immediately after: `QUICKML_ENDPOINT` **is** set on the live
  container (to the same unverified-provenance guessed URL documented in
  `PHASE1_FAILURE_LOG.md`'s BUG-022, `.../quickml/v1/project/{id}/glm/chat`) and the
  live call fails with the identical `PATTERN_NOT_MATCHED`/"zoho-inputstream" error
  every prior pass already recorded; `QUICKML_ENDPOINT_KEY` remains unset.
- Fetched the current Zoho documentation for LLM Serving directly
  (`docs.catalyst.zoho.com/en/quickml/help/generative-ai/llm-serving/`): the invoke
  URL and any required key are obtained **only** from the console's interactive
  "Model Details → API Details" popup — the docs page itself states this and
  documents no Admin API alternative.
- **Conclusion, established rather than re-guessed**: there is no CLI command, Admin
  API route, or Connections/secrets mechanism anywhere in this authenticated
  Catalyst environment that can discover, verify, or configure a working QuickML
  endpoint/key. This is a genuine platform gap (console-UI-only), not a credential
  this session simply failed to find. Per this pass's own instruction, stopped
  investigating here rather than continuing to guess request shapes against a live,
  billed endpoint. **Status unchanged: BLOCKED.**

**PDF export — re-confirmed BLOCKED, and the "real Catalyst user identity" question
specifically closed out:**
- Live `/export/pdf` call against a real session: `x-veritas-pdf-smartbrowz-reason:
  CatalystAPIError: {'code': 'INVALID_ID', 'message': 'No such User with the given id
  exists'}`, `x-veritas-pdf-local-reason: no Chromium-family browser found on this
  host` — byte-for-byte identical to every prior pass.
- New this pass: checked whether the officers have real Catalyst identities at all
  (`GET .../project-user` over the Admin API) — they do: 6 real, `ACTIVE` Catalyst
  App User accounts (Catalyst Authentication, `packages/policy`'s role source). But
  `apps/api/api/auth/jwt_auth.py`/`catalyst_auth.py` show the console's actual sign-in
  flow is a custom `POST /auth/token` REST call, never Catalyst's own hosted
  login/session flow — so no request ever carries a genuine Catalyst session cookie,
  which is what SmartBrowz's identity resolution needs regardless of the
  `_switch_user("admin")` workaround already in place. Minting a session for one of
  these real users server-side, without the officer completing Catalyst's own
  interactive sign-in, would be authentication bypass — explicitly out of scope per
  this pass's own instruction ("do not bypass authentication"). **Status unchanged:
  BLOCKED, root cause now stated precisely rather than left as "an identity
  question."**

**Fixed (commit `1aecd82`, console redeployed) — the toast/Evidence-rail overlap,
closed for real this time:**
`AlertToasts` moved out of `position: fixed` (which necessarily draws on top of
whatever is beneath it, wherever it's anchored) and into the Evidence rail pane's own
flexbox flow, between `.pane-head` and the scrollable `.pane-body`
(`apps/web/app/page.tsx`, `apps/web/app/globals.css`). A toast now displaces the
citation list downward structurally; it cannot occlude a card. `npx tsc --noEmit`
clean; live-verified via a headless-Chrome CDP session against the deployed console —
a real anomaly toast (`KA22 monthly_fir_count 13.0 vs expected 7.0`) confirmed as a
`position: static` child of `.pane.glass.rail`, positioned above `.pane-body`.

**BUG-026 — found to already be fixed, not re-fixed.** Read `copilot/brief.py`
directly before doing any work: `_lead_name()` already reconciles
`CanonicalName`/`AccusedName` (`"Soom Nadkarni (filed as \"Suma Nadkarni D/o Eshwar\"
on this FIR)"`), landed in the 2026-08-26 finishing pass per `WORK_LOG.md`'s own
entry for that day. Live-confirmed on FIR 9992 via `/copilot/9992` — the reconciled
string renders exactly as documented. The only real defect was documentation drift:
`docs/VERITAS_HANDOFF.md`'s "open bugs" list still called it open while
`docs/QA_FUNCTIONALITY_MATRIX.md`'s own detailed BUG-026 section already said FIXED —
corrected in this pass's doc updates rather than left contradicting itself.

**Industry gap analysis** — live web research (Palantir Gotham, IBM i2 Analyst's
Notebook, Maltego, DFIR chain-of-custody practice) cross-referenced against Veritas's
actual current capability. Full write-up: `docs/INDUSTRY_GAP_ANALYSIS.md`. Headline
finding: the single largest gap is that Veritas has no investigation memory that
survives past one chat session — every mature platform researched treats a
persistent, editable case artifact as the core object an analyst works with, and
Veritas currently re-derives everything from zero the next time anyone opens a case.
Recommended, smallest-first: (1) a persistent per-case board for pinning evidence/
leads with officer notes, (2) lead disposition (pursued/dismissed) built on the same
schema, (3) a cross-entity timeline correlation view — the one concrete i2 capability
Veritas structurally lacks. None of the three were built this pass (analysis and the
two named small fixes only, per the prompt's own scoping).

**Test suite**: 373 collected (derived directly via `pytest --collect-only -q`'s
per-file breakdown, summed — not trusted from a prior changelog line, matching this
project's own established discipline for this number), all green. No backend code
changed this pass, so this is a re-measurement, not a change.

**Deploys**: console only (`scripts/deploy-console.sh`, commit `1aecd82`) — nothing in
`apps/api` or the packages changed, so no API redeploy was needed. QuickML/PDF
investigation touched no code; nothing to deploy for either.

**Docs updated**: `docs/INDUSTRY_GAP_ANALYSIS.md` (new), `docs/VERITAS_HANDOFF.md`
(rewritten for this pass), this file, `docs/QA_FUNCTIONALITY_MATRIX.md` (toast
overlap closed, BUG-026 doc-drift corrected), `docs/VERITAS_STATUS.html` (stale-as-of
banner extended).

**Not done this pass, named rather than silently skipped**: none of the three
industry-gap recommendations were implemented (analysis only, as scoped); `dowhy`
was explicitly out of scope per this pass's own instruction not to prioritize it
without a clean way to fit the deployment constraints (unchanged, still declined on
image-size grounds — see CLAUDE.md v12); voice pipeline, case-status filter chips,
map pan/drag, AML positive-case verification — all unchanged from prior passes.

---

## 2026-08-27 (later, same day) — Final live judge pass: real browser tooling this time,
five defects found by actually looking at the screen

Unlike the immediately prior pass, real browser/CDP tooling was available and used:
headless Chrome (`--headless=new --remote-debugging-port=9222`), driven over Node 22's
global WebSocket, per `[[veritas-console-verification]]`. Every finding below was found
by driving the real console and inspecting real screenshots — not the API alone.

**Drove a ~25-turn live investigation through the actual UI** (open FIR → what happened
→ who's involved → priors → why-those-cases → associates → what-supports → similar
cases → geography → financial trail → what's-unusual → evidence-for → next-steps →
briefing → switch case → follow-up → attempted positional return → explicit return →
context-isolation check → ambiguous-pronoun clarification → five improvised natural
follow-ups → Kannada), screenshotting key steps, then judged every screenshot the way a
competition judge would. Found and fixed **five real, live defects**:

1. **P0 — a refusal still shipped the evidence it had just rejected.**
   `node_synthesize`'s general refusal branch (`requires_escalation`) cleared
   `state.citations` but not `state.evidence_items`, unlike every other refusal branch
   in the same function. Clean single-turn repro: *"Tell me about the flying saucer
   incident on the moon"* → honest refusal in chat, **and** the Evidence rail
   simultaneously showed "8 cited," listing 8 unrelated Raichur robbery FIRs at ~40%
   similarity. Same failure class as BUG-006/RAG-35, a third recurrence. Fixed by
   clearing both fields together, matching the other three branches.
2. **`CASE_REFERENCE_UNSUPPORTED` missed any phrasing without a leading ordinal.**
   "Go back to the case we started with" (no "first/previous/original") skipped the
   refusal and fell to a real semantic search that passed CRAG, returning 5
   confidently-cited, completely unrelated records — worse than a refusal, since
   nothing signalled the mismatch. Regex broadened to cover trailing back-references
   and bare demonstratives ("that case"), not just a leading ordinal.
3. **Associate evidence text said `gang: Community 6`**, contradicting CLAUDE.md §4's
   explicit "labelled honestly as what it is — never 'gang'" rule that
   `copilot/brief.py` already follows. Reworded to "network community 6."
4. **A genuine namesake collision read as a duplicate.** "Who are her associates?"
   listed "Suma Nadkarni" twice, verbatim. Raw evidence `source_id`s confirmed two
   different real `PersonUID`s (7334, 8395) sharing a `CanonicalName` — not a
   duplicate-row bug. `_network_evidence` now disambiguates with `(person <id>)` only
   when a real collision exists in that specific result list.
5. **Two UI defects found from screenshots**: `NetworkView.tsx`'s 40%-of-max label
   threshold (tuned for large graphs) left 3 of 4 nodes unlabelled on a small,
   high-variance 4-accused graph — fixed with a node-count-aware threshold. The live
   `.toast-stack` (anomaly alerts) was pinned to the same bottom-right corner as the
   Evidence rail's citation cards, sometimes covering several of them — moved to anchor
   under the topbar instead, reducing (not fully eliminating) the overlap.

5 new regression tests against the affected code directly. **369 → 374 tests, all
green.** Commits `15ff976` (fixes 1–3), `23291eb` (fix 4), `7d4e581` (fix 5).

**Deployed twice** via the relay pipeline (API: `0988f04`→`52852000000321046`,
`f310c4a`→`52852000000318080`; console: `catalyst deploy --only client`, after
discovering the CLI shim isn't on this shell's `PATH` — see handoff). **Every fix
re-verified live afterward**, through the real console: a clean single-turn repro for
fix 1 (evidence rail now empty on refusal), the exact reproducing phrasing for fixes 2–4,
fresh screenshots for fix 5 (all 4 network nodes labelled; toast-stack rect confirmed
anchored under the header).

**Also judged, found no defect**: the real MapLibre/OpenFreeMap basemap (real streets,
labels, legend, scale, attribution — genuinely judge-ready), the financial Sankey view,
the reasoning-trace panel, the Copilot overlay's timeline/leads/similar-cases, the
EN/KN toggle, and the Kannada round-trip (3 citations, correct both directions).

**Re-confirmed unchanged (not re-exercised, no code in these areas touched)**: RBAC,
QuickML (still `QUICKML_ENDPOINT_KEY`-blocked), PDF export (still the honest HTML
fallback), Cron (both jobs' prior unattended-success evidence stands).

**Test suite**: 374 collected, all green.

**Docs updated**: `docs/VERITAS_HANDOFF.md` (rewritten for this pass), this file,
`docs/QA_FUNCTIONALITY_MATRIX.md`, `docs/VERITAS_STATUS.html` (stale-as-of banner
extended).

**Not done this pass, named rather than silently skipped**: the toast/evidence-rail
overlap is reduced, not eliminated — a structurally different placement (dedicated
alert surface) would close it fully; judged as scope creep for a decision-support
side-channel in a pass that was finding and fixing core-trust defects. RBAC was not
re-driven live through the console this specific pass (API-level check from the prior
pass stands, unchanged code path). Voice pipeline, case-status filter chips, map
pan/drag, AML positive-case verification, `dowhy`, BUG-026 (Copilot canonical/as-filed
name) — all unchanged from prior passes, same constraints as documented there.

---

## 2026-08-27 (later still) — Built the persistent per-case investigation board:
`docs/INDUSTRY_GAP_ANALYSIS.md`'s top recommendation, now live

The prior pass's gap analysis named this the single largest gap against Gotham/i2/
Maltego: no investigation state survived past one chat session. Built it end to end —
schema, policy-checked backend, conversational integration, console UI, tests,
provisioning, deployment, and a real live-judge pass that found and fixed three defects
the deploy itself didn't catch.

**Schema and backend (commit `af3ad7a`):**
- `vx_case_board_item` (`data/data/schema.py`) — one table, `ItemType` discriminates six
  kinds (evidence, person, lead, note, question, finding) so a note can never render as
  a database fact. References the authoritative record (`RefType`/`RefID`) plus a
  content snapshot taken at pin time; never a second copy of FIR/person/financial/graph
  facts. Provisioned live over the Admin API (`python -m data.provision`, idempotent —
  37 existing tables untouched, 1 created).
- `data/data/board.py` (raw CRUD) → `rag_agent/board.py` (the ONE policy-checked entry
  point, station-scoped via `policy.can_view_fir`, cross-case item tampering blocked) →
  `apps/api/api/routers/board.py` (`GET/POST/PATCH/DELETE /board/{fir_id}`, every
  mutation audited). Deleting a lead is rejected (400) — dismiss (`status=dismissed`)
  instead, so "a dismissed lead must remain auditable" is enforced, not just documented.
- Six new case-scoped intents (`BOARD_VIEW`, `BOARD_PIN_EVIDENCE`, `BOARD_PIN_PERSON`,
  `BOARD_ADD_LEAD`, `BOARD_ADD_NOTE`, `BOARD_LEAD_STATUS`) extend the existing
  intent/orchestrator architecture rather than bolting on keyword patches — the same
  `NEEDS_CASE` gate, the same short-circuit-before-CRAG pattern `CAPABILITY` already
  uses. "Pin this" resolves against the evidence card the console had selected (new
  `active_evidence_id` on `/chat`, sourced from `apps/web`'s existing `activeEvidence`
  state) or falls back to the previous turn's top citation.
- Console: `Board.tsx` joins `Copilot.tsx`'s existing per-FIR overlay as a second tab
  ("Briefing" / "Investigation Board") instead of a new destination — reachable from the
  Evidence rail (new "Pin to board" / "Open Case Board" buttons), the case index (new
  "Investigation board" button per card), and chat. Distinct visual treatment per item
  kind (amber = record, blue = derived finding, dashed neutral = investigator note).

**25 new tests** (`data/tests/test_board.py`, `rag_agent/tests/test_board_policy.py`,
`apps/api/tests/test_board_acceptance.py`) covering RBAC, cross-case isolation, lead
lifecycle/auditability, and the full pin→note→lead→new-session-survives conversational
workflow end to end, before any live deploy.

**Deployed** (relay pipeline: signed URL → `relay-deploy.yml` build → `appsail/upsert`,
deployment `52852000000319069`; console via `scripts/deploy-console.sh`) and **then
actually driven live** — CDP over Node 22's global WebSocket, per
`[[veritas-console-verification]]`, not just curl. Found and fixed **three real defects
the deploy itself didn't catch**, each with a regression test, before calling the pass
done:

1. **Keyword collision misrouted the feature's own example phrasing.** "Pin this to the
   case board." and "Add that to the case board." (the spec's own literal examples) both
   contain "case board," which was also a bare `BOARD_VIEW` keyword — `classify()` picks
   the earliest-registered intent on a score tie, so every successful pin answered with
   a board *summary* instead of pinning anything. Found by actually typing the spec's
   own example sentences into the live console, not by reasoning about the keyword
   table. Fixed by removing the bare "case board"/"investigation board" fragments from
   `BOARD_VIEW`; added a systematic substring-collision guard across every intent's
   keyword list so a new one can't be introduced silently again.
2. **Every citation-free answer rendered as a refusal.** `ChatPane.tsx` inferred
   "refusal" from `citations.length === 0` — also true of a successful `CAPABILITY`
   answer or a board confirmation, so "Pinned this evidence…" rendered in the same red,
   left-bordered styling as "I could not find this in the records." Replaced the
   inference with an explicit `answer_is_refusal` field set by `node_synthesize` at the
   exact point a refusal-shaped answer is produced — not derived from
   `requires_escalation`, which is set generically before synthesis runs and does not
   track whether synthesis went on to answer successfully (a found
   `EXPLAIN_REASONING`/`EVIDENCE_FOR` prior turn re-shows real citations despite
   `requires_escalation` having been `True` on the way in).
3. **Board-panel reload timing.** The panel refetched on `turns.length`, which
   increments the instant a query is *sent*, not when its mutation lands server-side — a
   lead saved via the panel's own inline form read stale (pre-mutation) state and never
   refetched again. Reload now keys off the count of turns that have actually finished
   streaming.
   Also fixed in the same pass: opening the board directly from the case index (no prior
   chat turn) never established the session's active case, so the panel's note/lead
   forms — which operate through chat — refused with "no case is open." The board button
   now also asks about the case first, same as "Ask about this case" already does.

**Redeployed and re-verified live after each fix**: the spec's own example phrases now
classify correctly (`Pin this to the case board.` → `BOARD_PIN_EVIDENCE`); a genuine
refusal ("Tell me about the flying saucer incident on the moon") renders `msg-a
refusal` while a board confirmation renders plain `msg-a` — confirmed by reading the
live DOM's actual CSS class, not inferred from a screenshot; a lead saved via the
panel's own form appears immediately without a manual reopen; two different cases'
boards show completely different, correctly-scoped content (case isolation).

**Live-verified via real HTTP/SSE against production** (not just the browser): sign-in
→ open case → pin (conversational, falls back to top citation) → note → lead → `GET
/board` shows all three, correctly typed and grouped; a **second, brand-new session**
(fresh `session_id`, the same thing a new officer login produces) reopens the case and
`"What is on the board for this case?"` correctly lists all 3 items — the board survives
the session, not just the turn; `"Dismiss that lead"` correctly resolves "that lead" to
the most recent open one and the lead stays on the board with `status: dismissed`,
never deleted; an IO gets `403` reading or writing another station's board, `401` with
no token; `DELETE` on a lead returns `400`; `/jobs/audit-verify?sync=true` reports the
hash chain intact after every mutation above.

**Test suite**: 403 collected (399 after the feature, +4 for the three live-found
defects), all green.

**Docs updated**: this file, `docs/VERITAS_HANDOFF.md`, `docs/QA_FUNCTIONALITY_MATRIX.md`,
`docs/VERITAS_STATUS.html`. Screenshots in
`docs/screenshots/2026-08-27-investigation-board/`.

**Not done this pass, named rather than silently skipped**: the cross-entity timeline
correlation view (`docs/INDUSTRY_GAP_ANALYSIS.md` §7 item 3) — the analysis's own
ranking put the board first and named this the next step, not part of this pass's scope.
A "pin a relationship" affordance inside `NetworkView.tsx` itself (associates are
currently pinned only via the Evidence rail's generic "Pin to board," which works for
any evidence item including `GRAPH_RELATIONSHIP` ones, but has no in-graph click
target) — the conversational path ("add this person to the investigation" after asking
about someone) covers the same need and is tested; a dedicated graph-node pin button
would be a small follow-up, not a gap. QuickML and PDF export remain correctly BLOCKED,
unchanged, not re-investigated this pass (no new information available since the prior
pass's from-scratch re-check).

---

## 2026-08-27 (later) — cross-entity investigation timeline

Built `docs/INDUSTRY_GAP_ANALYSIS.md` §7 item 3 — the analysis's next-ranked
recommendation, explicitly deferred by the investigation-board pass immediately above.
One chronological event list spanning a case's own dates, its accused persons'
arrests, their OTHER cases, and money through any account they own — no new table,
every event traced to a real ER/vx_ column already in the record layer.

**Reconnaissance first** (per this pass's own instruction): read `copilot/brief.py`'s
existing single-case `_timeline()`, `queries.py`, `data/graph.py` (TRANSFERRED_TO edges
already carry `amount`/`date`/`txn_id` — no new query needed for financial events),
`orchestrator.py`'s BOARD_*/CASE_LOCATIONS short-circuit pattern, and the console's
Board.tsx/Copilot.tsx precedent, before writing anything.

**New module `packages/rag_agent/rag_agent/timeline.py`**:
- `case_timeline(fir_id, ...)` / `person_timeline(person_id, ...)` assemble events from
  `CaseMaster` registration/disposition, `ArrestSurrender`, `ChargesheetDetails`, and
  TRANSFERRED_TO graph edges. Every event carries `kind: "authoritative"` (a directly
  stated ER/vx_ fact) or `"derived"` — used for exactly one thing: a person's OTHER
  case, linked only by Fellegi-Sunter's inferred identity match, shown with its match
  confidence and never presented as a stated fact.
- `connection_between(...)` — "why are these connected" — reports only real graph/ER
  facts (co-accused, a shared case, a transfer between owned accounts) as a
  connection. Two events merely falling near each other in time are explicitly never
  reported as one, per this pass's own instruction not to call proximity a correlation.

**New REST endpoints**: `GET /timeline/case/{fir_id}`, `GET /timeline/person/{person_id}`
(`apps/api/api/routers/timeline.py`), same station-scope/masking discipline as
`/copilot` and `/board`.

**Conversational integration** (`orchestrator.py`, `intents.py`): two new intents,
`TIMELINE` and `TIMELINE_CONNECTION`, matched by shape (regex pre-check, like
`CASE_LOCATIONS`/`EXPLAIN_REASONING` already are) rather than keyword score — "what
happened before this incident" would otherwise tie `CASE_CONTEXT`'s bare "what
happened" keyword, and "why are these events connected" would otherwise score
`CAUSAL`'s bare "why". Each timeline event becomes an ordinary `EvidenceItem`, so
`EXPLAIN_REASONING`/`EVIDENCE_FOR` and board-pinning reuse the exact mechanisms every
other intent already has, with zero new plumbing there — confirmed by driving both
live, not assumed from the architecture.

**Three real defects found and fixed by driving this live**, each reproduced against
the running local API/console before being fixed, matching this project's own
established discipline:

1. **Keyword collision.** "Add this event to the investigation board" (a natural
   phrasing of the feature's own spec example) contains "investigation board" — a
   bare `BOARD_VIEW` keyword — so it misrouted to a board summary instead of pinning.
   The same collision class v16 already fixed for "case board"; not yet closed for
   this phrase. Fixed with a `_BOARD_PIN_EVENT` regex pre-check, same discipline as
   the existing "case board" fix.
2. **Silent wrong-item pin (the more serious one).** `_pin_evidence_from_context`'s
   fallback logic unconditionally grabbed the previous turn's TOP evidence item
   whenever a genuine `active_evidence_id` target didn't match anything in that
   turn's own pool — invisible until now, because until the Copilot overlay's new
   Timeline tab (which fetches over REST, so its events were never part of any chat
   turn) this mismatch could never actually happen. Reproduced live via curl: opened
   a case (turn 1, FIR-record evidence), then asked to pin a specific transaction
   event by id — the API silently pinned the unrelated FIR record from turn 1
   instead, with nothing in the response indicating a substitution had happened.
   Fixed the precedence: a target is now tried against the prior turn's pool, then
   its citations, then (if it looks like a timeline event) reconstructed directly
   from the case's own timeline — and ONLY when there was no target at all does it
   fall back to "whatever the previous turn showed." Re-verified live after the fix:
   the exact same pin request now correctly pins the named event.
3. **Pronoun-ambiguity collision.** `TIMELINE_CONNECTION`'s own pronoun ("both of
   them") was being caught by `node_orchestrate`'s pre-existing generic
   2-candidate ambiguous-person refusal (RAG-34's mechanism) before
   `_handle_timeline_connection` — which resolves exactly those two candidates by
   design — ever ran. Reproduced live: "Who are the accused on this case?" (2
   accused, correctly leaves `active_person` unset) → "Show me events involving
   both of them." fell to "I will not guess which one you mean" instead of showing
   the merged timeline. Fixed by exempting `TIMELINE_CONNECTION` specifically from
   that refusal branch, since its own pronoun semantics are plural-by-design, not
   the singular ambiguity that refusal exists to catch.

**Live-verified, both local and production, HTTP/SSE and real CDP**:
- `/timeline/case/{fir_id}` and `/timeline/person/{id}` — chronological, entity
  attribution correct, RBAC (403 cross-station via the same `can_view_fir` check as
  `/fir`/`/copilot`), 404 on a missing subject.
- Chat `TIMELINE` — "Show me the timeline for this case" produces a 23-event
  chronological timeline, ACCEPTs via an authoritative finding, 12 citations, correct
  `visualization.kind: "timeline"`.
- Chat `TIMELINE_CONNECTION` — "Show me events involving both of them" after a
  2-accused `CASE_PEOPLE` turn correctly resolves both people, finds their real
  co-accused connection, and renders a merged chronological timeline.
- Board pin from a chat-driven timeline event, AND from the Copilot overlay's own
  Timeline tab with no prior chat turn at all (the reconstruction-fallback path,
  defect #2 above) — both correctly pin the exact named event, confirmed via the
  live DOM (`.board-item-body` text matches the pinned event verbatim).
- Real headless-Chrome CDP against both `localhost` and the deployed console:
  chat → timeline visualization → click an event → Pin via the Evidence rail; case
  index → Copilot brief → Timeline tab → Pin directly from there → Investigation
  Board tab shows it. Screenshots captured for both.
- Kannada: `translation_agent.to_english()` + `intents.classify()` confirmed directly
  that "ಈ ಪ್ರಕರಣದ ಟೈಮ್‌ಲೈನ್ ತೋರಿಸಿ" translates to "Show the timeline of this case" and
  classifies as `TIMELINE`. The full round trip through a freshly-started local dev
  server was not captured within this session's test window — the first Kannada call
  on a cold local process exceeded it, consistent with BUG-016's already-documented
  cold-load latency, not a defect this pass introduced. Not re-attempted against the
  already-warm live deployment for lack of remaining session time; named here rather
  than silently claimed.

**One data observation, not a defect**: `TIMELINE_CONNECTION` between two specific
habitual offenders in the seeded dataset merged 750+ events — one of the two has 196
cases on file, an extreme hub in the generator's preferential-attachment scheme.
Genuine data, rendered honestly in a scrollable list; not capped, since capping would
mean silently hiding real history with no principled cutoff. Left as-is; worth a
"summarize when very large" affordance if this becomes a demo pain point.

**Deployed**: API via the established relay pipeline (deployment
`52852000000345002`); console via `scripts/deploy-console.sh`. Both re-verified live
after deploy, not just after the local run.

**Test suite**: 30 new tests (`test_timeline.py`: 25; `test_api.py`: +5;
`test_engine.py`: +5 minus overlap — see the file diff for the exact split), all
against the real dataset fixture, none mocked. 433 collected, all green.

**Docs updated**: this file, `docs/VERITAS_HANDOFF.md`, `docs/QA_FUNCTIONALITY_MATRIX.md`,
`docs/VERITAS_STATUS.html`.

**Not done this pass, named rather than silently skipped**: a dedicated "pin" click
target inside `NetworkView.tsx`/`MapView.tsx` for a timeline event's underlying
relationship (the Evidence rail's generic Pin button and the Timeline view's own Pin
button already cover this for every event type, tested) — small, additive, not a
functional gap. A true "before/after this specific event" filter beyond the two
`before`/`after` keyword cases implemented is not built — the anchor resolution
(`active_evidence_id` when set, else the timeline's own first event) covers the
spec's own example phrasing but not arbitrary date-range queries. QuickML and PDF
export remain correctly BLOCKED, not re-investigated (no new information since the
prior pass).

---

## 2026-08-28 — final completion pass: closed a documentation gap and one real
Kannada translation defect, everything else re-verified rather than re-built

Scope was a full-system completion audit (data, conversation, RAG, RBAC, UI, security,
docs, deployment) against the live production system. Chose inspection-then-fix over
another rebuild: this repo already carries ~10 real, live-verified passes since v16
(see `docs/ENGINEERING_BRIEF.md`'s dated entries — semantic interpreter, protected-span
translation, the compositional semantic layer, QuickML activation, the general N-step
planner, the cold-start fix, cross-entity timeline), and the freeze rule this project's
own brief argues for means finding and fixing a real defect beats inventing new scope.

**Found first**: `CLAUDE.md` itself was the stale artifact it kept warning about — its
own changelog stopped at v16 while 236 commits and ~10 real passes had landed since, and
its quoted test count (403) was stale against the real 602 (`pytest --collect-only -q`).
Its "there are no other design docs" claim was also false — `docs/WORK_LOG.md` and
`docs/ENGINEERING_BRIEF.md` have been the actual operational ledger for a while. Fixed:
CLAUDE.md now names that split explicitly and carries a real v17 entry; this file's own
narrative (dated 2026-08-27, describing the cross-entity-timeline pass specifically) is
several passes old and `docs/VERITAS_HANDOFF.md`'s top block now says so rather than
silently presenting stale state as current.

**Then verified against the live system, not against prior logs**: full local suite
(602 collected, all green), live `/health`, and — the actual acceptance test, since a
green pipeline proves nothing about conversational behavior — the repo's own automated
live-behavior gates run fresh against production: `scripts/verify_live_deployment.py`
(36/36 adversarial conversational scenarios: result-set follow-ups, positional/ordinal
reference, constraint-change, bare why/exploration/temporal cues, two-entity
comparison, colloquial phrasing, Kannada code-switching, honest refusals) and
`scripts/judge_flows.py` (26/26 realistic multi-turn officer sessions: lookup,
unseen phrasing, pronoun follow-up, previous-result reference, mid-conversation
correction, multi-step, network, financial, timeline, Kannada, code-switching,
ambiguity/clarification, no-evidence refusal, RBAC, capability/safety, continuity).
Both passed 100% before any change was made — the system was not "mostly working," it
was working, and this pass's job was to find the real remaining gap, not manufacture one.

**One real defect surfaced by that audit**: the live Kannada battery's own output
contained `"73 ಪ್ರಕರಣಗಳು(s)"` — synthesis writes count-agnostic `case(s)`/`record(s)`
markers throughout `orchestrator.py` (a deliberate convention for English readers, ~40
call sites), and NLLB translates the noun but copies the literal `"(s)"` through
untouched. Fixed structurally rather than patched per-phrase, the same discipline
`_protect_spans` already applies to identifiers and district names: new
`_resolve_plural_markers()` (`data/data/nlp/translate.py`) reads the real count already
sitting next to each marker and resolves it to correct English singular/plural *before*
the text reaches the translation model, so the ambiguity never reaches NLLB. One test
(`data/tests/test_nlp.py`, the case that takes the suite from 601 to 602).

**Deployed and live-verified**: commit `ddbc4f1` relayed (`get-signature` →
`.github/relay-upload.url` → `relay-deploy.yml` → local `appsail/upsert`) to deployment
`52852000000346070`. Both live gates re-run clean against the fresh container (36/36,
26/26). The exact query that surfaced the bug
(`"ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?"`) was re-run directly (parsing the raw SSE
response, not trusting the automated battery's summary line alone): the answer now
reads `"73 ಪ್ರಕರಣಗಳು"` with no residual `"(s)"` and the correct canonical district
spelling.

**One operational finding, not a code defect, flagged rather than acted on
unilaterally**: the AppSail `appsail/upsert` callback's own JSON response echoes the
app's full environment configuration — including `VERITAS_JWT_SECRET`,
`VERITAS_JOB_TOKEN`, and the QuickML OAuth client secret/refresh token — in plaintext.
This is the platform API's own behavior on every deploy through this pipeline, not
something this pass introduced. `scripts/rotate_secrets.py` already exists for the case
where rotation is warranted; not run unilaterally here, since it would invalidate live
JWT sessions and the Cron job token without the operator's coordination.

**Repo/security hygiene checked, nothing to fix**: `git status` clean, no untracked
files; `.gitignore` covers env files, build output, and local Catalyst config;
`git ls-files` for secret-shaped names turned up only `.env.example` (placeholders
only, verified) and the two legitimately-named scripts (`catalyst-token.js`,
`rotate_secrets.py`) that exist to handle secrets, not leak them.

**Test suite**: 602 collected, all green.

**Not done this pass, named rather than silently skipped**: no dataset regeneration —
the live audit found no data-quality defect, and regenerating 10,000 seeded cases on
spec-compliance grounds alone would be exactly the unrequested rebuild the freeze
discipline argues against. No UI zoom-level/browser click-through — this was a
backend-and-one-translation-file change; the investigation-board pass's own CDP
verification stands, unchanged. `docs/QA_FUNCTIONALITY_MATRIX.md`, `docs/VERITAS_STATUS.html`
and `CONTEXT.md` (dated 2026-07-15) were not individually re-verified line-by-line
against current state this pass — `CONTEXT.md` in particular is now materially stale
(it predates the semantic interpreter, compositional layer, QuickML activation, and
timeline features entirely) and is a real remaining documentation-consolidation gap,
named here rather than silently left. QuickML endpoint-key status, PDF export's
SmartBrowz identity block, and the "priorities" Kannada residual (`\bpriors?\b` vs.
"priorities") are unchanged from the prior passes' own from-scratch re-checks — nothing
in this pass's live audit surfaced new information that would change any of those three
findings.

---

## 2026-08-30 — a `double` column corrupting its own values

Started from a user-reported screenshot: the Network view for "Who are the associates
of Usha Naika?" rendered most of the graph as nodes labelled "Usha Naika" — the query's
own subject, not the associates the answer text correctly named. Investigated by driving
the real system, not by reading the diff, per this project's own standing discipline.

**Ruled out a frontend bug first.** Pulled the deployed `NetworkView.tsx` bundle
directly (fetched the live JS chunk, matched it by content against the app's static
chunk manifest) and diffed it module-for-module against this repo's source: identical.
So the console was rendering exactly what the current code says to render — the input
data had to be wrong, not the display logic.

**Confirmed via a controlled local/live diff.** Generated a clean local dataset from
scratch and compared `vx_person.PageRank` for the same PersonUIDs against what the live
API actually returns. Every value whose true magnitude sits below ~0.0001 came back
inflated 10,000-100,000x on live: `0.000851196807533056` (Nithin Madar) → `8.5119`;
`0.0000781711...` (Suma Nadkarni) → `7.8171`. The console's own `isRoot()` sentinel
(`pagerank >= 1` means "this is the query's subject") then fired on every one of those
corrupted associates, rendering them as duplicates of Usha Naika.

**First fix attempt was the wrong lever.** `data/data/schema.py`'s `_MAX_LEN["double"]`
(17) looked like the obvious cause — widened it to 32, wrote tests, all green. Checked
live before trusting it: a direct column-update request asking Data Store for
`max_length: 25, decimal_digits: 12` on the live `PageRank` column returned
`status: success` with the spec **unchanged** at `max_length: 15, decimal_digits: 4`.
Data Store silently clamps every `double` column to that precision regardless of what a
provisioning or update request asks for — `_MAX_LEN` was never a real lever, and the
first fix, while harmless, fixed nothing. Reverted the number, kept the corrected
reasoning in the comment.

**Second fix attempt was also wrong, and this time it shipped before being caught.**
`data.ds._sdk_row` — the one existing choke point every Catalyst write already passes
through for normalization — was given `round(v, 4)`: a plain Python float, which is
always in decimal notation (never scientific) by Python's own repr rules. Deployed
(`3b7482f` → `ba0cad9`, relayed to AppSail, deployment `52852000000355160` — the
`appsail/upsert` call itself returned `LIMIT_REACHED` ["Only one deployment can be
created concurrently"] but the deployment had actually started regardless, confirmed
via its build logs timestamped to the same call; polled to `deployment_status: success`
directly rather than trusting the error response). Triggered `POST /jobs/refresh` to
rewrite `PageRank`/`Betweenness` through the "fixed" path — and the live associates
query came back exactly as corrupted as before. Retriggering repeatedly returned
`{"status": "started"}` each time (the lock was free — each run finishing fast, not
hanging), with nothing changing. That combination (deploy succeeded, job "finishes,"
symptom unchanged) is the one this project's own discipline says not to wave away as
"just needs more time."

**Round-tripped the actual endpoint instead of guessing again.** Used the admin OAuth
token to call the exact row-write REST endpoint the SDK's `update_rows()` calls,
directly, bypassing the SDK entirely. Three results settled it: a bare JSON *number*
below the column's precision (`0.0009`) came back `400 INVALID_INPUT ("Please give a
correct double value")` — rejected outright, which is almost certainly why a batch
write containing any such value silently fails inside the refresh job's caught
exception, explaining the "finishes fast, fixes nothing" pattern exactly. A plain
fixed-point *string* (`"0.000851196807533056"`) round-tripped correctly (`8.0E-4`) at
every magnitude tried, including a large value (`"123.4567"` back exactly). But a
string that still *contained* scientific notation (`"7.817113529341168e-05"`) came
back `7.8171` — the identical corruption, string or number, meaning this really is a
text-level `E`-notation defect on Data Store's ingest that no amount of Python-side
`float` rounding was ever going to reach.

**Real fix**: every `float` through `_sdk_row` now becomes `f"{v:.4f}"` — a string,
always plain decimal, never `e`/`E`, at the precision the column already enforces.
Test rewritten to match (`test_sdk_row_formats_floats_as_exponent_free_decimal_strings`).
Full suite: 741 passed, 2 skipped (unchanged count, corrected assertions).

**Deployed a second time and the live data repaired, confirmed this time by actually
checking.** Committed (`b54e88b` → `0e31d41`), relayed to deployment
`52852000000356181` (clean `upsert` response this time, `deployment_status: success`
polled directly). `POST /jobs/refresh` on the corrected container ran
`data.gds.run_all()`, rewriting `PageRank`/`Betweenness` for every person through the
genuinely-fixed write path. Re-ran the exact query that started this investigation
against the live API: all 41 nodes now carry distinct real names and sane magnitudes
(`0.0101` down to `0.0001`), zero at or above `1`. Console also redeployed
(`scripts/deploy-console.sh`), carrying an unrelated fix from earlier the same
session: the sign-in screen's role list reordered by operational hierarchy and its em
dashes removed.

**Follow-up the same day: audited every other `double` column against live,
exhaustively, and found nothing else to repair.** Read every row of every table with a
`double` column directly through the admin token's row-read endpoint (paginating past
its own row cap where needed), not a sample:

- `RiskScore` (`vx_person`) and `FlagConfidence` (`vx_txn`) are never actually written
  by this codebase at all — `RiskScore` is scored on demand per query and never
  persisted; `FlagConfidence` would be set by an AML detector job that has never run
  against this live dataset (0 of 2,354 transactions flagged). Nothing to corrupt.
- `MatchConfidence` (`vx_accused_identity`, all 17,315 rows): `[0.90, 1.0]`, matching
  the code's own `LINK_THRESHOLD` floor exactly.
- `Weight` (`vx_graph_edge`, 20,000+ rows sampled, table larger): `1.0`-`26.0`.
- `Amount` (`vx_txn`, all 2,354 rows): `₹501.81`-`₹1,426,326.50`.
- `Confidence` (`vx_case_board_item`, all 11 rows, 3 non-null): `0.6`-`0.97`.
- The five socioeconomic columns (`vx_district_socioeconomic`, all 30 districts): real
  Census 2011 ratios and percentages — the ~58-79% literacy figures are legitimately
  large, not corrupted, and every fractional column (`UrbanRatio`, `PovertyIndex`,
  `MarginalWorkerRate`, `YouthRatio`) is a plausible real value.
- `CaseMaster.latitude`/`longitude` (all 10,000 rows): within Karnataka's real bounds.

Nothing needed repair, for a structural reason rather than luck: the corruption only
strikes a magnitude below ~0.0001, and every column audited here is either never
actually populated or has a domain floor well above that threshold (confidence scores
bounded at 0.90+, rupee amounts in the hundreds, edge weights ≥1, real-world ratios,
real coordinates). Only `PageRank`/`Betweenness` — raw graph centrality over a
17k-node graph — legitimately produce values that small, which is exactly why they
were the only two that actually broke. The exact internal mechanism on Data Store's
side that rejects a bare small JSON number yet still corrupts a scientific-notation
string was inferred with high confidence from the pattern across every case checked,
not confirmed from Zoho's own source or documentation.

---

## 2026-09-04 — six conversational additions, and the real `appsail/upsert` contract

Driven by a research pass into what real conversational-AI-for-policing products
(eSleuth, Case IQ, SymphonyAI Sensa Copilot) and the academic/DOJ literature actually
offer, cross-checked against the West Midlands Police Microsoft Copilot hallucination
incident (a fabricated match used to justify a real football banning order) as the
concrete argument for why every new feature had to inherit the existing cited-or-refuse
discipline rather than add a new surface that could bypass it.

**Six new conversational intents, each built entirely on data already in the record
layer — no new table, no new model:**
- `INTERROGATION_PREP` — priors, structural case gaps (no arrest, no chargesheet after
  a normal window), and direct associates, assembled before an officer questions someone.
- `CASE_SIMILARITY_WATCH` — the existing `SIMILAR_CASES` retrieval, narrowed to an
  officer's own open backlog and cases closed as undetected.
- `CASE_HANDOFF` — fuses the Copilot brief with the investigation board's own state
  into one "catch me up" narrative.
- `CHALLENGE_FINDING` — a new meta-turn (alongside `EXPLAIN_REASONING`/`EVIDENCE_FOR`)
  that actively looks for what would WEAKEN the previous answer, rather than explaining
  how it was reached.
- `PREFILING_CHECK` — the same structural-gap check as `CHALLENGE_FINDING`, run
  proactively before a case is sent up.
- `CROSS_STATION_LINKAGE` — reports when a case's accused is also named at a different
  station, following the same v20 partial-visibility discipline as associate
  explanations (the link is always reported, the other case named only where the
  officer's access allows it).

Also: the case-diary draft now tags its one DERIVED sentence inline (both the
templated and LLM-generated paths), so an unverified/derived claim can never ship
unlabeled into an exported document — the direct, deliberate answer to the West
Midlands incident above.

**A real Python-version bug caught by the deploy pipeline's own smoke-test import,
not by any local check.** `PREFILING_CHECK`'s status-breakdown sentence split a string
literal across a line inside an f-string's `{}` — valid under the relaxed f-string
grammar Python 3.12+ ships (PEP 701), so it parsed cleanly under this machine's local
Python 3.13 (`ast.parse` gave no warning). The deployed container runs 3.11, and the
import failed with a plain `SyntaxError` before the build ever reached AppSail. Fixed
by computing the fallback text as a local variable first; every touched file is now
also checked against a local Python 3.11 interpreter (`py -3.11`), not just whichever
version `python` happens to resolve to.

**A real conversational bug found live, on the very first end-to-end test, and fixed
the same pass.** "Poke holes in this." asked right after "Catch me up on this case." —
the single most natural way to chain these two new features — answered "nothing
structural stands out," even though the case had two real, findable gaps (no arrest,
no chargesheet in 65 days). Cause: `CASE_HANDOFF`'s own evidence is written as
`handoff:{fir_id}:summary`, and `CHALLENGE_FINDING`'s case-id extraction only
recognised the `fir:{fir_id}` shape a direct FIR lookup's citations use. Fixed to also
read the case id out of `handoff:`/`filing:`/`watch:`/`linkage:` evidence, and to fall
back to the session's own `active_fir` when the prior turn names no case at all.
Verified by reproducing the exact live sequence, both as a regression test and again
against the redeployed live API.

**The `appsail/upsert` contract — reverse-engineered, and now written down.** No prior
session's changelog entry contains the actual request shape, only the pipeline name
(`get-signature` → `.github/relay-upload.url` → `relay-deploy.yml` → local
`appsail/upsert`); every past deploy apparently reconstructed the call from scratch.
JSON bodies with `image`/`object_key` fields all returned an opaque `Invalid input
value for image` regardless of shape or nesting. The real contract, found by reading
the installed Catalyst CLI's own source
(`node_modules/zcatalyst-cli/lib/endpoints/lib/appsail.js`,
`customAppSailCallback`/`getSignedUrl`): `get-signature` and `upsert` take NO
resource-id path segment (only `.../appsail/{id}/configuration` does); `name` is a
query parameter for `get-signature` and a form FIELD for `upsert`; and `upsert` is a
**multipart/form-data PUT**, not JSON — fields `name`, `memory`, `platform` (must be
`"custom_runtime"`), `configuration` (a JSON **string**, not a nested object — e.g.
`'{"port": 8000}'`), and `local_object_key` (the bare base64 key `get-signature`
returns). Saved as `scripts/deploy-api.py` so this is a one-command operation from
here on, not tribal knowledge re-derived under time pressure every pass.

**Deployed and live-verified, end to end, twice** (deployment ids
`52852000000400007` then `52852000000391012`, the second carrying the
`CHALLENGE_FINDING` fix): `/health` 200 with the full dataset warm; a real multi-turn
session opened FIR `100222201202600022` and drove all six new intents plus `/explain`
against a `linkage:` evidence id — every one answered with real records, honest
absences where nothing existed, and a working provenance chain.

**Test suite: 830 passed, 2 skipped** (14 new — `packages/rag_agent/tests/
test_conversational_additions.py`).

**Not done this pass, named rather than silently skipped**: no console changes — every
new intent uses `visualization: "none"` and renders through the existing generic
citation/evidence rail, matching `CASE_CONTEXT`/`NEXT_STEPS`/`BRIEFING`'s own
precedent; a dedicated UI affordance (an "Interrogation prep" button on a person view,
a "Challenge this" button on an answer) would be a small, purely additive follow-up.
`docs/OFFICER_PITCH.md` (new) restates the whole platform in plain, non-technical
language for a law-enforcement audience — a different artifact from this file,
written this same session on request.

---

## 2026-09-04/05 — Strategic reset: independent audit, research, and Phases 0-2 of the
resulting roadmap

Full analysis (four-way gap analysis, product thesis, ranked capability list, blueprint,
hero scenario) is in `docs/STRATEGIC_RESET_2026-09-04.md` — this entry is the terse,
dated pointer to it plus what got built, per this file's own convention.

**Why.** On request: a ground-up product/investigative/technical audit before building
anything else, done by reading the live code directly rather than trusting `CLAUDE.md`'s
own claims. Found the six v24/25 conversational operations are the most under-sold part
of the product (buried at the end of a changelog dominated by infrastructure war
stories), and that "crime pattern discovery" and "behavioral profiling" — both named
explicitly by the challenge — were only half-built: reactive/query-driven, never
unprompted, despite the underlying signal (co-offending graph, `_signature_choice`
recurring-MO weighting) already sitting in the data.

**Research** (external, cited in the strategic-reset doc): CCTNS/ICJS adoption state,
linkage blindness (Egger 1984) as the named ViCAP-era failure mode this gap resembles,
India's own deployed AI-policing tools (Delhi FRS/CMAPS, UP Trinetra, Punjab PAIS) and
their documented failure pattern (AI match treated as sufficient with no corroboration,
no privacy assessment, no governing framework) as the sharpest available contrast for
Veritas's refuse-or-cite architecture, comparative case analysis theory (Burrell & Bull;
Davies 2019) on why the generator's current 3-template-per-crime-type MO text is common
rather than distinctive, and a live pull of a real competing Datathon 2026 submission
(KAVACH 360) confirming map+graph+forecast+chatbot is the default convergent solution —
table stakes, not a differentiator.

**Phase 0 — credibility fixes.**
- **BNS section citations.** `data/generator/refdata.py` cited only the retired IPC for
  every generated case, despite the dataset's own date range spanning the 2024-07-01
  BNS transition and `manifest.py` already (falsely) claiming an "IPC/BNS mix." Added a
  real, sourced (BPRD's official IPC↔BNS correspondence table, downloaded and read
  directly) date-aware lookup; NDPS/IT sections untouched. Backfilled onto the already-
  seeded live 10,000-case dataset in place via the existing narrative-backfill job, not
  a regeneration. 7 new tests.
- **QuickML hard spend guard**, done ahead of the phase work once real LLM-authorship
  work (Phase 4) was raised as a possibility: every QuickML request had no `max_tokens`
  cap at all (the model supports up to 128K tokens of output — open-ended cost per call,
  independent of any budget conversation). Added a cap
  (`VERITAS_LLM_MAX_TOKENS`, default 900) plus a persistent, Cache-backed call-count
  circuit breaker (`VERITAS_LLM_MAX_CALLS`, default 300, survives redeploys) that
  degrades to the existing deterministic fallback path once hit. Explicitly framed as
  defense-in-depth — the authoritative control is Catalyst's own Settings → Billing
  budget cap, which only the account owner can set, and was recommended over inventing
  a cost estimate Zoho does not publish.

**Phase 1 — unprompted cross-station series discovery** (the flagship; new module
`packages/rag_agent/rag_agent/series_detection.py`).
- Finds clusters of open, unresolved-suspect cases sharing a distinctive MO-clause match
  plus geographic/temporal proximity, with no common investigating officer — the general
  version of what `CROSS_STATION_LINKAGE` (v24) could only do when a suspect was already
  named on both cases.
- New conversational intent `SERIES_DISCOVERY` ("is this part of a pattern?"), a
  provenance handler, and — the genuinely proactive half — wired into `/jobs/refresh`'s
  existing 6h cadence and pushed through the existing `/alerts` SSE feed as a new
  `series` event type alongside the existing district-anomaly `alert` events, with the
  same partial-visibility discipline (a series is reported only if the officer can view
  its anchor case; an out-of-scope member is reported as existing without being named).
- Console: `AlertBell.tsx` renders a second, DERIVED-labeled "Cross-station patterns"
  section.
- Found and fixed live during this work: `/jobs/refresh` ran four independent derived
  layers inside one `try`/`except`, so the series scan's own exception handling needed
  isolating the same way three prior steps already were (§CLAUDE.md v23) — done as part
  of wiring this in, not a separate pass.

**Phase 2 — evidence-backed behavioral profile** (new module
`packages/rag_agent/rag_agent/behavioral_profile.py`).
- For a resolved person: recurring time-of-day (bucketed, majority-fraction gated),
  exact repeated MO-clause (reusing series_detection's own matching logic), geographic
  range (haversine span across all recorded incidents), escalation in offence severity
  (only where the record's own gravity classification — not the crime-type label alone —
  actually shows an increase over time), and co-accused who recur across more than one of
  the person's own cases. Requires at least 3 cases before reporting anything — fewer is
  "a history," not yet "a pattern." Never demographic by construction: caste/religion/
  gender columns are never read by this module at all.
- New intent `BEHAVIORAL_PROFILE` ("build a profile on him," "how does she operate").
- **A real bug caught by the handler's own new test, not by inspection**: an edit placed
  near the existing `INTERROGATION_PREP` block left its closing `_trace()` call orphaned
  inside the new `elif`, referencing a variable (`prep`) that only exists in the sibling
  branch — `UnboundLocalError` on every `BEHAVIORAL_PROFILE` turn. Fixed same pass.

**A second real bug, found and fixed the following day after the previous session ran
into its usage limit mid-verification.** The live-found routing fix for
`BEHAVIORAL_PROFILE` (committed as `9567318`, described as "not yet redeployed or
re-verified live") turned out to be dead code on closer inspection: it wrapped only the
pronoun alternative of `_BEHAVIORAL_PROFILE_SHAPE` in `(?i:...)` and left the literal
`how`/`does`/`operate` case-sensitive, while `classify()` matches the *raw*, non-
lowercased query — and a real sentence starts with a capital "How." The fix matched
nothing at all, for either the pronoun case (which only appeared to work, via the older
keyword-based fallback scorer matching on a separately-lowercased copy) or the named-
subject case it was written for. No test had asserted the exact named-subject phrasing
reported live ("How does Usha Naika operate?") — only the pronoun case, which would have
passed with or without the fix and proved nothing. Corrected by wrapping every
structural word in its own `(?i:...)`, keeping `[A-Z]\w+` case-sensitive (the one piece
that must stay that way, to tell a name apart from "the system"). Regression test added
first, confirmed to fail against the pre-fix code, then passed. Redeployed
(`52852000000389039`) and verified against the exact live query that had been reported
broken: `Intent: BEHAVIORAL_PROFILE; resolved 'Usha Naika'`, matched deterministically
(8ms, confidence 0.9, no QuickML call spent).

**A near-miss, caught before it became real data loss.** The prior session's very last
write — made as it hit its usage limit — truncated this file from 1293 lines to a 2-line
`PREPEND_MARKER` stub, mid-way through what looks like an intended prepend-then-restore
operation that never got the old content back in. Never committed in that state, so
`git restore docs/WORK_LOG.md` recovered it with nothing lost. Recorded here as the
reason `docs/STRATEGIC_RESET_2026-09-04.md` now exists as a durable artifact rather than
leaning on this file (or a chat transcript) as the only record of that session's
analysis.

**Test suite: 868 passed** (up from 830 at the start of the prior session), 2 skipped
(environment-gated, pre-existing, unrelated). Deployed and live-verified: `/health`
warm with the full dataset; the exact previously-broken behavioral-profile query now
answers correctly; the series-discovery and BNS fixes were already live from the prior
session's own deploys (`52852000000400007`-successor builds) and re-confirmed still
healthy post this session's redeploy.

**Not done this session, named rather than silently skipped**: Phase 3 (Aequitas wired
into the live refresh cycle; minimal graph/edge annotation), Phase 4 (LLM-authored
distinctive MO narrative — deliberately held pending a look at real Catalyst billing
history, not a technical blocker), Phase 5 (pitch/README rewrite beyond the two lines
already added, demo recording). The fused proactive-prevention advisory was scoped in
the strategic-reset doc but not built. `docs/CAPABILITY_TARGET_AND_GAPS.md` and
`docs/INDUSTRY_GAP_ANALYSIS.md` (both 2026-08-27) were not rewritten against this pass's
findings — they remain their own dated snapshots.
