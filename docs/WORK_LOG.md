# Veritas — Work Log

Chronological, append-only. Each entry: what was done, why, evidence. Prose history lives
in `CLAUDE.md`'s changelog and `docs/PHASE1_FAILURE_LOG.md`; this is the terser, dated
log a future session can skim to see what happened without re-reading either in full.

---

## 2026-08-26 — North Star hardening pass

Ran the full 23-section "North Star hardening" audit, re-established current state from
the live system rather than trusting prior docs (found one place they'd drifted — see
BUG-027 below).

**Re-audited live first**: `/health`, Cron config, `/chat`, `/alerts`, `/export/pdf`,
`/person/{id}`, `/fir/{id}`. `veritas_refresh`'s Cron job had a real unattended success
since BUG-025's fix (0→1); `veritas_audit_verify` did not (0/20→0/21) — the URL/token fix
alone hadn't fixed that job's schedule.

**Fixed (commit `152c313`, deployed `52852000000204688`):**
- **BUG-028 (P0)** — "Does X have priors?" had been silently answering "crime type not
  recorded, status not recorded" for every case in production, for the flagship
  capability CLAUDE.md §0 exists to enable. Root cause: `person_record()`'s query
  already spent 3 of ZCQL's 4-JOIN cap reaching a case id via the identity table,
  leaving no budget for the joins that resolve crime-type/status/district names. Fixed
  by chaining a second, separately-budgeted query (`sql_agent.cases_by_ids`) instead of
  exceeding the cap. 2 tests, confirmed to fail pre-fix. Live-verified against 12 real
  cases.

**Fixed (commit `d5f0798`, deployed `52852000000316042`):**
- `/jobs/audit-verify` ran `verify_chain()` synchronously — the call that pays BUG-001's
  ~23s cold-container mirror-hydration cost, inside a request Cron abandons before that
  completes. Applied `/jobs/refresh`'s background-thread pattern; kept `sync=true` for
  manual checks. 5 tests. Logged as **BUG-027**.

**CDP session** (first with real browser tooling in several sessions) moved 10 UI rows
from PARTIAL/UNKNOWN to VERIFIED: EN/KN toggle, citation-chip click, evidence-thread
line draw, reasoning-trace expand, full Copilot overlay, copy-to-clipboard,
case-explorer search, "Ask about this case," Export PDF's enabled state.

**Found live, documented, not fixed**: BUG-026 — Copilot leads show
`vx_person.CanonicalName` ("Soom Nadkarni") while the same case's accused list shows the
as-filed `Accused.AccusedName` ("Suma Nadkarni") for the same `PersonUID`, with nothing
linking them. Confirmed via `/fir/9992`/`/person/877` this is entity resolution working
correctly — just an unexposed cross-reference.

**Fixed (commit `21b2bd9`)**: `exportPdf()` returned `void`, so a 200-with-HTML-fallback
downloaded silently with no indication it wasn't a real PDF. Now reports whether the
blob was a real PDF.

**Fixed (commit `1fb0bdc`, generator-only)**: the identity-resolution answer key wasn't
persisted like the AML labels. `run.py` now writes `IDENTITY_ANSWER_KEY`; new
`data/generator/score_identity.py` recomputes P/R/F1 against whatever
`vx_accused_identity` is currently bound. 3 tests. Not exercised against the live
10k-case dataset (predates the fix; regenerating just for this would violate the
no-casual-regeneration rule).

**Re-confirmed unchanged (BLOCKED)**: QuickML (`QUICKML_ENDPOINT_KEY` unset), PDF export
(SmartBrowz `INVALID_ID`; no Chromium fallback either — confirmed absent explicitly for
the first time), Aequitas (out-of-band by design), `dowhy` (declined on image-size
grounds).

**Not pursued**: AML detector positive-case verification (couldn't match a local answer
key file to live transaction numbering; one admin ZCQL attempt failed
`INVALID_URL_PATTERN`, not retried); full click-through of remaining UI controls.

**Test suite**: 317 collected (10 new), all green. Docs updated: QA matrix, PHASE1
failure log, `docs/VERITAS_HANDOFF.md` (created), this file (created).

---

## 2026-08-26 (later, same day) — Conversational architecture pass

A different question this pass: how much of the conversational layer was genuinely
conversational (explicit state, follow-ups building on each other) vs. intent
classification over isolated tools sharing a session id.

**Read the code first.** `SessionFocus` (active_person/active_fir/active_location)
already existed and persisted across turns, and pronoun resolution against it worked —
but nothing let a follow-up talk ABOUT the open case ("what happened," "who's
involved," "what next," "prepare the briefing") or ABOUT the previous answer ("why
these," "what evidence") — every such question fell through to literal-text vector
search. The Investigation Copilot already had correct logic for leads/similar-cases/
briefing; it just wasn't reachable from `/chat`, only `/copilot`.

**Built (commit `2e1da7d`):**
- Seven new intents: `CASE_CONTEXT`, `CASE_PEOPLE`, a case-scoped `SIMILAR_CASES`
  branch, `NEXT_STEPS`, `BRIEFING` (gated on `SessionFocus.active_fir` via new
  `intents.NEEDS_CASE`), plus `EXPLAIN_REASONING`/`EVIDENCE_FOR` (read the previous
  turn's stored citations/trace) and `CASE_LOCATIONS` (tallies districts over the
  previous turn's cited FIRs). The three Copilot-backed intents reuse
  `copilot.brief.leads_for_case`/`similar_cases_for`/`generate_copilot_brief` directly.
- Ambiguous person names (a tied top match by `record_count`) now ask which one instead
  of silently picking the first.
- Every case-scoped branch re-validates station scope on EVERY use via the same scoped
  `fir_by_id()` `FIR_LOOKUP` uses — `active_fir` in session state is not itself a
  permission.
- 33 new regression tests.

**Found and fixed live:**
- **The persisted-focus bug (most consequential fix this pass)**: `node_orchestrate`
  persists `SessionFocus` BEFORE retrieval runs, but `FIR_LOOKUP`/`CASE_PEOPLE` resolve
  `active_fir`/`active_person` DURING retrieval — never saved. "Open FIR X" then "What
  happened?" one turn later forgot X entirely; found live before it was ever
  unit-tested. Fixed by persisting again at the end of `node_retrieve` — without this,
  none of the new case-scoped intents could ever fire on turn 2.
- **NER bug** (`data/data/nlp/entities.py`): "Tell me more about Usha Naika" resolved
  to a DIFFERENT "Usha" (the database's most prolific one) at full confidence. Root
  cause: PERSON-span extraction spanned only pool-matching tokens; "Usha" is in the
  271-name sample, "Naika" isn't, so the span clipped to "Usha." Fixed by extending the
  span outward through adjacent capitalised tokens, stopping at a stopword or place
  name. (commit `d26f3fd`)
- **`PERSON_HISTORY` keyword gap**: "What previous cases involve her?" (plural) matched
  no keyword and fell to `CRIME_SEARCH`'s bare "cases," answering with a global
  10,000-case count. (commit `cc46f75`)

**Live-verified**: a 14-turn investigation over curl/SSE and a headless-Chrome/CDP
session — open FIR → case context → accused → priors → associates → why-these →
case-scoped similar cases → geography → financial trail → what-evidence → next steps →
briefing. Also: unknown FIR refuses; capability question answers without touching
records; IO cross-station refusal holds across both the lookup and its follow-up; a
Kannada follow-up round-trips with zero Kannada-specific code (translation runs before
intent classification). 8 screenshots in
`docs/screenshots/2026-08-26-conversational-architecture/`.

**QuickML**: re-checked directly — `QUICKML_ENDPOINT_KEY` still absent. Confirmed
BLOCKED.

**Deploys**: three, each live-verified — `52852000000317055` (feature),
`52852000000325022` (NER fix), `52852000000318035` (keyword fix). No console deploy
needed.

**Test suite**: 352 collected (35 new). Docs updated: handoff, this file, QA matrix.

**Not done**: no new North-Star gap-closing beyond what live verification surfaced;
`docs/CAPABILITY_TARGET_AND_GAPS.md` untouched.

---

## 2026-08-26 (later still) — "Final product pass": map made investigator-grade + a real conversational gap closed

A mega-prompt named the map a launch-blocking defect ("dark canvas, scattered points, no
geographic orientation") and asked for the conversational architecture to be verified
live, not just described.

**Inspected first**: compared the committed
`docs/screenshots/2026-08-26-conversational-architecture/06-case-locations-map.png`
against `MapView.tsx`. Confirmed the complaint and found the cause:
`fitBounds({maxZoom: 11})` zoomed a tight cluster in so far every neighbouring district
dot/label fell outside the viewport — the prior pass's "Phase 4" fix only held for a
broad query.

**Fixed (`MapView.tsx`, `globals.css`, commit `2a903ba`):**
- `maxZoom` capped at 9 (was 11).
- Legend added: amber dot = individual cited FIR, green→amber→red ramp = hotspot
  density — neither existed before.
- Hotspot polygon opacity raised (0.26→0.4, 1.6→2px) for visibility against the dark
  basemap.
- No district boundary polygons added — none exist in this dataset; not fabricated.

**Verified locally and live**: ran the API locally against the sqlite mirror. Surfaced
a platform fact: AppSail's CORS preflight is answered at the platform edge for exactly
the deployed console's own origin, not via `VERITAS_CORS_ORIGINS` — a POST from
`localhost:3000` to the live API fails preflight with no CORS headers at all (a testing
constraint, not an app bug). Screenshots for both a tight cluster and a broad statewide
query, local and live, in `docs/screenshots/2026-08-26-map-investigator-grade/`.

**Live conversational check** (9-turn curl/SSE session + 2-turn RBAC check, not the
full 19-turn script): FIR_LOOKUP → CASE_CONTEXT → CASE_PEOPLE → pronoun follow-up →
EXPLAIN_REASONING → EVIDENCE_FOR → CASE_LOCATIONS → guilt-probability question →
Kannada round-trip; station-scoped IO probing an out-of-station FIR twice.

**Found and fixed live:**
- **RAG-34**: "Who is involved?" (2 accused, `active_person` correctly unset) then
  "Does he have priors?" fell to a bare `no_subject` refusal, discarding the two names
  just shown — exactly the gap the prior pass's handoff had predicted. Fixed
  (`orchestrator.py`, `_recent_person_candidates`, commit `2d382d4`): a pronoun with no
  active person now checks the previous turn's stored `accused:` citations and, with
  2+ candidates, asks which one — reusing the existing `ambiguous_person` path. 2
  tests, positive one confirmed to fail pre-fix.
- `CASE_LOCATIONS`'s "nothing to map" refusal reused `EXPLAIN_REASONING`'s "first
  answer" message verbatim — false past turn 1. Given its own message
  (`nothing_prior_locations`).

**QuickML**: re-checked, still absent, still BLOCKED, no code change.

**Deploys**: console via `scripts/deploy-console.sh`; API via the relay pipeline,
deployment `52852000000325027`. Both live-verified post-deploy.

**Test suite**: 354 collected (352→354).

**Not done**: the full 19-turn golden script through the actual console (only
curl/SSE run); full UI judge-review click-through beyond the map.
`docs/CAPABILITY_TARGET_AND_GAPS.md` Part 3 (narrative diversity, QuickML-blocked LLM
fluency) remains the largest open item.

---

## 2026-08-26 (later still) — Real geographic basemap

A mega-prompt judged the self-drawn dark-canvas map (real district centroids, no roads
or terrain) as not good enough, asking for a real MapLibre + OpenFreeMap basemap while
keeping every Veritas overlay.

**Inspected first**: the basemap was a flat `background-color` (`MAP_BG = "#080d12"`),
with `NEXT_PUBLIC_MAP_STYLE` already wired as an escape hatch — the sound integration
was to change the default it resolves to, not rebuild the component.

**Built (`MapView.tsx`, `globals.css`, `palette.ts`):**
- Default style: `https://tiles.openfreemap.org/styles/liberty` (OSM-derived, no key/
  quota) — the fifth documented Catalyst exception (CLAUDE.md §2). Only a viewport tile
  z/x/y crosses the network.
- District dots/labels re-styled for contrast against a real basemap (two-tone dot,
  dark chip behind each name) — old low-opacity-white styling was tuned for
  near-black.
- `AttributionControl` added (ODbL requires crediting OSM); CSS now hides only the
  MapLibre logo, not all attribution.
- Every other overlay (FIR points, hotspot polygons, legend, scale, v14's `maxZoom: 9`)
  untouched. `MAP_BG` deleted from `palette.ts`.

**Verified locally then live**: four queries (Mandya tight cluster, bare statewide →
Bengaluru Urban fallback, Bidar near the Telangana border, Kodagu with no hotspot
evidence — honest refusal) judged against a "would a judge recognize this as Karnataka
within seconds" checklist. Deployed (`scripts/deploy-console.sh`, console-only) and
re-verified live, same four queries plus one refusal. One platform fact: first live CDP
attempt hit a cold AppSail container mid-warm-up (handled correctly by the sign-in
gate, not a map bug). The live dataset had Kodagu hotspot evidence the local mirror
didn't (a data-state difference, not a bug) — produced the pass's most striking
screenshot (Western Ghats forest around Madikeri).

**Test suite**: unchanged at 354 (frontend-only). Screenshots:
`docs/screenshots/2026-08-26-real-basemap/` (supersedes the prior map screenshot set,
kept for history).

**Not done**: true district boundary polygons (not part of the dataset); pan/drag
gesture interaction not driven live; the 19-turn golden conversation and North Star
P0/P1 items remain outstanding — out of this pass's map-only scope.

---

## 2026-08-26 (later still) — Finishing pass: the 19-turn golden conversation, four real bugs, and closing the last North Star MUST-HAVE

Built a CDP driver (headless Chrome, Node 22 WebSocket) and drove one continuous
19-turn investigation through the actual deployed console — DSP sign-in, FIR
100050504202300018 (Kidnapping, Bengaluru Urban, 4 accused), a case switch to an
unrelated FIR and back, and a deliberately ambiguous pronoun at the end.

**First run found four real bugs**, all in `packages/rag_agent/rag_agent/`:
1. `CASE_PEOPLE` only set `active_person` with exactly one accused; with several, it
   did nothing, leaving a stale person "active" from an earlier case — re-opening a
   different multi-accused case and asking a pronoun follow-up answered about the
   wrong old person. Fixed with an explicit clear.
2. `EXPLAIN_REASONING`'s regex required "why (are/were/did) you <verb>" with nothing
   in between — passive natural phrasing ("why were those associates surfaced") fell
   through to `CAUSAL`. Widened the verb list and allowed one noun between "those" and
   the participle.
3. `NEXT_STEPS` keywords had "investigate next" but not "investigated next" (passive)
   — added.
4. `node_retrieve` only skipped retrieval for refusals it decides/re-derives itself,
   guarded with `and not state.refusal_reason` — but an ambiguous-person refusal
   (which clears `active_person`) correctly skipped every specialist branch while the
   untargeted vector-search fallback had no such guard, handing the officer 5
   unrelated citations right next to "I will not guess which one you mean." Fixed with
   an early return in `node_retrieve` whenever a refusal is already decided.

Also closed **BUG-026**: Copilot leads and `NEXT_STEPS` now show `"Canonical (filed as
\"AsFiled\" on this FIR)"` via a new `_lead_name()` helper in `copilot/brief.py`.

6 new regression tests, each confirmed to fail pre-fix. **354 → 361 tests.**

**Deployed twice** via the relay pipeline (plus one self-inflicted broken deploy — a
`node -e ... > sig.json` redirect wrote an empty file because the async `fetch` hadn't
resolved before the shell opened the file; caught immediately, fixed within minutes).

**Second run verified all fixes live**: all 19 turns correct, including context
isolation (switch to an unrelated Mandya case and back — re-ask correctly names the
original case's 4 accused) and the ambiguous-pronoun clarification (asks which of the
4 accused, Evidence rail correctly empty). Also verified: a Kannada round-trip, and a
cross-station authorization refusal as IO.

**One false alarm ruled out**: a screenshot of "where are those cases concentrated?"
looked untargeted/zoomed-out — traced to the CDP driver's own timing (MapLibre's
`fitBounds` animation is 900ms, driver only waited 400ms). Raised to 1500ms; not a
product bug, recorded as a CDP-harness trap.

**QuickML and PDF export re-confirmed BLOCKED** by a direct live check, no code
change.

**Test suite**: 361 collected. Screenshots:
`docs/screenshots/2026-08-26-full-investigation-walkthrough/` (25 + log.json).

**Not done**: independently observing `veritas_audit_verify`'s next unattended Cron
fire (fix deployed, needs the schedule itself); the tied-name-search variant of RAG-32
hasn't hit a live tie by chance; a from-scratch full UI click-through beyond the golden
conversation itself.

---

## 2026-08-27 — Finalization pass: an adversarial stress test found three real bugs, Cron's unattended-fire question finally closed, repo hygiene

No browser/CDP tooling available this session — everything verified live went over
direct HTTP/SSE, not the console UI. Stated plainly rather than glossed over.

**Ran a fresh adversarial conversation** (deliberately different phrasing from the
already-passing golden script: "tell me more about this person," "what about the other
person," "go back to the first case," a mid-session Kannada query, "how many gangs
operate in this district?"). Found three real bugs:
1. A Kannada query crashed the turn — a tokenizer `TypeError` from the CTranslate2
   backend escaped `translation_agent`'s narrow `except TranslationUnavailable`. Both
   `to_english`/`to_language` now catch any backend exception and degrade to English.
2. "How many gangs operate in this district?" (no person named) was answered as an
   ambiguous-PERSON clarification — `intents._PRONOUNS` treated bare "this"/"that"
   unconditionally as an unresolved person reference. Fixed by excluding "this"/"that"
   immediately followed by a domain noun.
3. "Go back to the first case" (no case-history stack exists) fell to a bare
   `CRIME_SEARCH` score and ran a real semantic search, confidently returning 5
   unrelated cited records. New `CASE_REFERENCE_UNSUPPORTED` intent refuses honestly
   instead.

7 new regression tests. **361 → 369 tests.**

**Deployed** (commit `37cc5c6`, deployment `52852000000306055`) and re-verified all
three fixes live. One platform fact: a Kannada re-check run ~1-2 minutes after deploy
success still reproduced the pre-fix crash — a redeploy doesn't instantly retire every
running container instance; a retry shortly after succeeded.

**Closed the item every prior handoff had left open**: `veritas_audit_verify`'s Cron
job now shows `success_count: 1, failure_count: 0` — a real unattended success on its
12h schedule. `veritas_refresh` shows `3, 0`.

**Re-confirmed unchanged**: QuickML (key absent), PDF export (`text/html`), RBAC.

**Repository hygiene**: removed two `.pptx` files and a redundant PDF from the repo
root; renamed `docs/VERITAS_NORTH_STAR.md` → `docs/CAPABILITY_TARGET_AND_GAPS.md` and
the golden-conversation screenshot folder to a jargon-free name.

**Test suite**: 369 collected.

**Not done**: no console/UI re-verification (no browser tooling); the
tied-name-search variant of RAG-32; voice pipeline, map pan/drag, AML positive-case
verification, `dowhy` — unchanged from prior passes.

---

## 2026-08-27 (later still) — Catalyst-blocker resolution + industry-gap analysis

Fresh, first-principles re-investigation of QuickML and PDF export via the
authenticated Catalyst CLI, then small UI fixes, then a live-research industry gap
analysis against Palantir Gotham/i2 Analyst's Notebook/Maltego.

**QuickML — confirmed BLOCKED for a concrete, newly-verified reason:**
- `catalyst project:list`/`catalyst help` (CLI v1.26.2): no QuickML command exists
  anywhere in the CLI surface.
- Probed the Admin API directly: `.../quickml/model(s)`, `.../ml/model`,
  `.../quickml` — all `404 INVALID_URL_PATTERN`. `.../connections` (Catalyst's
  OAuth-secret manager) returned genuinely empty.
- Live AppSail config: `QUICKML_ENDPOINT` **is** set (to the unverified-provenance
  guessed URL from BUG-022) and a live call fails with the same
  `PATTERN_NOT_MATCHED`/"zoho-inputstream" error every prior pass recorded;
  `QUICKML_ENDPOINT_KEY` unset.
- Zoho's own docs (`docs.catalyst.zoho.com/.../llm-serving/`) state the invoke URL and
  key are obtained ONLY from the console's interactive popup — no Admin API
  alternative documented.
- **Conclusion**: no CLI command, Admin API route, or secrets mechanism in this
  authenticated environment can discover/verify/configure a working QuickML
  endpoint/key — a genuine console-UI-only platform gap. **Status unchanged:
  BLOCKED.**

**PDF export — re-confirmed BLOCKED, identity question closed out:**
- Live `/export/pdf` byte-for-byte identical error to every prior pass.
- New this pass: checked whether officers have real Catalyst identities
  (`GET .../project-user`) — they do, 6 real ACTIVE accounts. But the console's
  sign-in flow is a custom `POST /auth/token`, never Catalyst's own hosted login — so
  no request ever carries a genuine Catalyst session cookie, which is what
  SmartBrowz's identity resolution needs regardless of the existing
  `_switch_user("admin")` workaround. Minting a session server-side without the
  officer's own interactive sign-in would be auth bypass — explicitly out of scope.
  **Status unchanged: BLOCKED, root cause now precise.**

**Fixed (commit `1aecd82`)**: the toast/Evidence-rail overlap — `AlertToasts` moved
out of `position: fixed` into the Evidence rail's own flexbox flow, between
`.pane-head` and `.pane-body`. A toast now displaces the citation list downward
structurally; live-verified via CDP.

**BUG-026 — found already fixed, not re-fixed.** `copilot/brief.py`'s `_lead_name()`
already reconciles CanonicalName/AccusedName (landed the prior day). The only real
defect was documentation drift — corrected.

**Industry gap analysis** (`docs/INDUSTRY_GAP_ANALYSIS.md`, new): live research
against Gotham/i2/Maltego/DFIR chain-of-custody practice. Headline finding: Veritas
has no investigation memory surviving past one chat session — every mature platform
researched treats a persistent, editable case artifact as the core object.
Recommended, smallest-first: (1) a persistent per-case board, (2) lead disposition on
the same schema, (3) a cross-entity timeline correlation view. None built this pass
(analysis and two small fixes only, as scoped).

**Test suite**: 373 collected (no backend change this pass — a re-measurement).
**Deploys**: console only.

**Not done**: none of the three gap recommendations implemented; `dowhy` out of
scope; voice, filter chips, map pan/drag, AML verification unchanged.

---

## 2026-08-27 (later, same day) — Final live judge pass: real browser tooling this time, five defects found by actually looking at the screen

Real browser/CDP tooling available this time — every finding below came from driving
the console and inspecting real screenshots, not the API alone.

**Drove a ~25-turn live investigation through the actual UI**, screenshotted key
steps, judged each the way a competition judge would. Found and fixed **five real
defects**:
1. **P0 — a refusal still shipped the evidence it had just rejected.**
   `node_synthesize`'s general refusal branch (`requires_escalation`) cleared
   `state.citations` but not `state.evidence_items`, unlike every other refusal
   branch. Repro: *"Tell me about the flying saucer incident on the moon"* → honest
   refusal in chat, but the Evidence rail simultaneously showed 8 unrelated Raichur
   robbery FIRs at ~40% similarity. Same failure class as BUG-006/RAG-35, a third
   recurrence. Fixed by clearing both fields together.
2. `CASE_REFERENCE_UNSUPPORTED` missed phrasing without a leading ordinal ("Go back to
   the case we started with") — fell to a real semantic search returning 5
   confidently-cited unrelated records. Regex broadened to cover trailing
   back-references and bare demonstratives.
3. Associate evidence text said `gang: Community 6`, contradicting CLAUDE.md §4's
   "never 'gang'" rule. Reworded to "network community 6."
4. **A genuine namesake collision read as a duplicate.** "Who are her associates?"
   listed "Suma Nadkarni" twice — two different real `PersonUID`s (7334, 8395) sharing
   a `CanonicalName`, not a duplicate-row bug. `_network_evidence` now disambiguates
   with `(person <id>)` only when a real collision exists in that result list.
5. Two UI defects from screenshots: `NetworkView.tsx`'s 40%-of-max label threshold
   left 3 of 4 nodes unlabelled on a small 4-accused graph — fixed with a
   node-count-aware threshold. The `.toast-stack` was pinned to the same corner as the
   Evidence rail, sometimes covering cards — moved under the topbar (reduces, doesn't
   fully eliminate, the overlap).

5 new regression tests. Commits `15ff976`, `23291eb`, `7d4e581`. **369 → 374 tests.**

**Deployed twice** and re-verified every fix live afterward through the real console.

**Also judged, no defect found**: the real MapLibre/OpenFreeMap basemap, the
financial Sankey view, the reasoning-trace panel, the Copilot overlay, EN/KN toggle,
Kannada round-trip.

**Not done**: the toast overlap is reduced, not eliminated (a dedicated alert surface
would close it fully — judged as scope creep this pass); RBAC not re-driven live
through the console specifically; voice, filter chips, map pan/drag, AML verification,
`dowhy`, BUG-026 (Copilot canonical/as-filed name) unchanged.

---

## 2026-08-27 (later still) — Built the persistent per-case investigation board: docs/INDUSTRY_GAP_ANALYSIS.md's top recommendation, now live

The prior pass's gap analysis named this the largest gap against Gotham/i2/Maltego: no
investigation state survives past one chat session. Built it end to end — schema,
policy-checked backend, conversational integration, console UI, tests, provisioning,
deployment, and a live-judge pass that found and fixed three more defects.

**Schema and backend (commit `af3ad7a`):**
- `vx_case_board_item` — one table, `ItemType` discriminates six kinds (evidence,
  person, lead, note, question, finding) so a note can never render as a database
  fact. References the record (`RefType`/`RefID`) plus a content snapshot at pin time.
  Provisioned live idempotently.
- `data/data/board.py` (raw CRUD) → `rag_agent/board.py` (the ONE policy-checked entry
  point, station-scoped, cross-case tampering blocked) →
  `apps/api/api/routers/board.py` (REST). Deleting a lead is rejected (400) — dismiss
  instead, so auditability is enforced structurally.
- Six new case-scoped intents (`BOARD_VIEW`, `BOARD_PIN_EVIDENCE`, `BOARD_PIN_PERSON`,
  `BOARD_ADD_LEAD`, `BOARD_ADD_NOTE`, `BOARD_LEAD_STATUS`) extend `NEEDS_CASE`, same
  short-circuit-before-CRAG pattern as `CAPABILITY`. "Pin this" resolves against the
  console's selected evidence card or the previous turn's top citation.
- Console: `Board.tsx` joins `Copilot.tsx`'s per-FIR overlay as a second tab,
  reachable from the Evidence rail, case index, and chat.

**25 new tests** covering RBAC, cross-case isolation, lead lifecycle, and the full
pin→note→lead→new-session-survives workflow, before any live deploy.

**Deployed** (deployment `52852000000319069`, console via
`scripts/deploy-console.sh`) and **driven live via CDP**. Found and fixed **three
real defects the deploy itself didn't catch**:
1. **Keyword collision**: "Pin this to the case board."/"Add that to the case board."
   (the spec's own examples) both contain "case board," also a bare `BOARD_VIEW`
   keyword — every pin answered with a board summary instead. Fixed by removing the
   bare fragments from `BOARD_VIEW`; added a systematic substring-collision guard
   across every intent's keyword list.
2. **Every citation-free answer rendered as a refusal.** `citations.length === 0` is
   also true of a successful `CAPABILITY` answer or board confirmation. Replaced with
   an explicit `answer_is_refusal` field set by `node_synthesize` at the point a
   refusal-shaped answer is produced — not derived from `requires_escalation`, which
   doesn't track whether synthesis went on to answer successfully.
3. **Board-panel reload timing**: the panel refetched on `turns.length` (increments
   the instant a query is sent, not when the mutation lands) — a lead saved via the
   panel's own form read stale state. Reload now keys off turns that finished
   streaming. Also: opening the board from the case index with no prior chat turn
   left no active case — the board button now asks about the case first.

**Redeployed and re-verified live after each fix**, including reading the live DOM's
actual CSS class to confirm refusal vs. confirmation styling, and confirming two
different cases' boards show completely different content (case isolation).

**Live-verified via real HTTP/SSE**: pin→note→lead survives a brand-new session;
"Dismiss that lead" resolves to the most recent open one, stays with
`status: dismissed`, never deleted; IO gets 403/401 correctly; audit chain intact
after every mutation.

**Test suite**: 403 collected (399 + 4 for the live-found defects). Screenshots:
`docs/screenshots/2026-08-27-investigation-board/`.

**Not done**: the cross-entity timeline correlation view (analysis's next-ranked
item, out of scope); a dedicated in-graph "pin" click target (the conversational path
and Evidence rail already cover the need); QuickML/PDF export unchanged.

---

## 2026-08-27 (later) — cross-entity investigation timeline

Built `docs/INDUSTRY_GAP_ANALYSIS.md` §7 item 3, deferred by the board pass above. One
chronological event list spanning a case's own dates, its accused persons' arrests,
their OTHER cases, and money through any account they own — no new table.

**New module `packages/rag_agent/rag_agent/timeline.py`:**
- `case_timeline()`/`person_timeline()` assemble events from `CaseMaster`
  registration/disposition, `ArrestSurrender`, `ChargesheetDetails`, and
  TRANSFERRED_TO graph edges. Every event carries `kind: "authoritative"` or
  `"derived"` — a person's OTHER case, linked only by Fellegi-Sunter's inferred
  identity, is shown with its match confidence and never presented as a stated fact.
- `connection_between()` reports only real graph/ER facts as a connection; two events
  merely near each other in time are explicitly never reported as one.

**New endpoints**: `GET /timeline/case/{fir_id}`, `GET /timeline/person/{person_id}`,
same station-scope discipline as `/copilot`/`/board`.

**Conversational integration**: two new intents, `TIMELINE`/`TIMELINE_CONNECTION`,
matched by shape (regex pre-check) rather than keyword score, since bare "what
happened" or "why" would otherwise tie existing intents. Each timeline event becomes
an ordinary `EvidenceItem`, so explanation/board-pinning reuse existing mechanisms
with zero new plumbing.

**Three real defects found and fixed live:**
1. **Keyword collision**: "Add this event to the investigation board" contains
   "investigation board" — same collision class v16 already fixed for "case board,"
   not yet closed for this phrase. Fixed with a `_BOARD_PIN_EVENT` regex pre-check.
2. **Silent wrong-item pin (the serious one).** `_pin_evidence_from_context`'s
   fallback unconditionally grabbed the previous turn's TOP evidence item whenever a
   real `active_evidence_id` target didn't match anything in that turn's pool —
   invisible until the Copilot Timeline tab (fetched over REST, never part of a chat
   turn) made this mismatch possible. Reproduced live: pinning a specific transaction
   by id silently pinned an unrelated FIR record from an earlier turn instead, with no
   indication of the substitution. Fixed the precedence: prior turn's pool → its
   citations → (if it looks like a timeline event) reconstructed directly from the
   case's own timeline — falling back to "whatever the previous turn showed" only
   when there's no target at all.
3. **Pronoun-ambiguity collision**: `TIMELINE_CONNECTION`'s own plural pronoun ("both
   of them") was caught by the generic 2-candidate ambiguous-person refusal before the
   handler (which resolves exactly those two candidates by design) ever ran. Fixed by
   exempting `TIMELINE_CONNECTION` from that refusal branch.

**Live-verified, local and production, HTTP/SSE and CDP**: both endpoints (RBAC, 404
on missing subject); chat `TIMELINE` (23-event chronological answer, 12 citations);
`TIMELINE_CONNECTION` after a 2-accused turn; board pin from both a chat-driven event
and the Copilot Timeline tab with no prior chat turn; Kannada translation+
classification confirmed directly (full round trip not captured within this session's
window — a cold-load latency issue, not a defect this pass introduced).

**One data observation, not a defect**: `TIMELINE_CONNECTION` between two habitual
offenders merged 750+ events (one has 196 cases on file, an extreme hub in the
generator's preferential-attachment scheme) — genuine data, rendered honestly, not
capped.

**Deployed**: API (`52852000000345002`), console via `scripts/deploy-console.sh`, both
re-verified live.

**Test suite**: 30 new tests, 433 collected.

**Not done**: a dedicated in-graph "pin" click target for a timeline event's
underlying relationship (existing Pin buttons already cover this); a true
before/after date-range filter beyond the two keyword cases implemented; QuickML/PDF
export unchanged.

---

## 2026-08-28 — final completion pass: closed a documentation gap and one real Kannada translation defect, everything else re-verified rather than re-built

Full-system completion audit against live production. Chose inspection-then-fix over
another rebuild: ~10 real passes had landed since v16 (see
`docs/ENGINEERING_BRIEF.md`), and this project's own freeze rule favors finding a real
defect over inventing new scope.

**Found first**: `CLAUDE.md` itself was the stale artifact it warned about — its
changelog stopped at v16 while 236 commits and ~10 passes had landed since, and its
quoted test count (403) was stale against the real 602. Its "no other design docs"
claim was also false. Fixed: CLAUDE.md now names the split and carries a real v17
entry.

**Verified against the live system**: full local suite (602, green), live `/health`,
and the repo's own automated live-behavior gates run fresh against production:
`scripts/verify_live_deployment.py` (36/36 adversarial scenarios) and
`scripts/judge_flows.py` (26/26 realistic officer sessions). Both passed 100% before
any change — the system was working, and the job was to find the real remaining gap.

**One real defect**: the live Kannada battery's own output contained `"73
ಪ್ರಕರಣಗಳು(s)"` — synthesis writes count-agnostic `case(s)`/`record(s)` markers
throughout `orchestrator.py` (~40 call sites), and NLLB translates the noun but copies
the literal `"(s)"` through untouched. Fixed structurally, the same discipline
`_protect_spans` already uses: new `_resolve_plural_markers()`
(`data/data/nlp/translate.py`) resolves each marker to correct English
singular/plural from the real count before the text reaches NLLB. 1 test (601→602).

**Deployed and live-verified**: deployment `52852000000346070`. Both live gates
re-run clean (36/36, 26/26); the exact bug-surfacing query re-run directly — now
reads `"73 ಪ್ರಕರಣಗಳು"` with no residual `"(s)"`.

**One operational finding, flagged not acted on**: the `appsail/upsert` callback's
JSON response echoes the app's full environment configuration — including
`VERITAS_JWT_SECRET`, `VERITAS_JOB_TOKEN`, and the QuickML OAuth secret — in
plaintext. Platform behavior, not introduced by this pass. `scripts/rotate_secrets.py`
exists for if rotation is warranted; not run unilaterally (would invalidate live
sessions/Cron token without coordination).

**Repo hygiene checked, nothing to fix**: clean `git status`, `.gitignore` covers env
files, no secret-shaped filenames beyond the two scripts that legitimately handle
them.

**Test suite**: 602 collected.

**Not done**: no dataset regeneration (no data-quality defect found); no UI
click-through (backend-only change); `CONTEXT.md` (dated 2026-07-15) is now
materially stale — a real remaining documentation gap, named here. QuickML/PDF
export/the "priorities" Kannada residual unchanged.

---

## 2026-08-30 — a `double` column corrupting its own values

Started from a user-reported screenshot: the Network view for "Who are the associates
of Usha Naika?" rendered most of the graph as nodes labelled "Usha Naika" — the
query's own subject, not the real associates the answer text named.

**Ruled out a frontend bug first.** Pulled the deployed `NetworkView.tsx` bundle and
diffed it module-for-module against this repo's source: identical. The input data had
to be wrong.

**Confirmed via a controlled diff.** Generated a clean local dataset and compared
`vx_person.PageRank` for the same PersonUIDs against live. Every value with true
magnitude below ~0.0001 came back inflated 10,000-100,000x:
`0.000851196807533056` → `8.5119`; `0.0000781711...` → `7.8171`. The console's
`isRoot()` sentinel (`pagerank >= 1` = query subject) fired on every corrupted
associate.

**First fix attempt was the wrong lever.** `schema.py`'s `_MAX_LEN["double"]` (17)
looked like the obvious cause — widened to 32. Checked live before trusting it: a
direct column-update request asking for `max_length: 25, decimal_digits: 12` returned
`status: success` with the spec **unchanged** at 15/4. Data Store silently clamps
every `double` column to that precision regardless of the request. Reverted the
number, kept the corrected reasoning as a comment.

**Second fix attempt also shipped wrong.** `data.ds._sdk_row` was given
`round(v, 4)` — a plain Python float, never scientific by Python's own repr rules.
Deployed (`3b7482f`→`ba0cad9`, `52852000000355160`), triggered `/jobs/refresh` to
rewrite PageRank/Betweenness — the associates query came back exactly as corrupted.
Retriggering returned `{"status": "started"}` each time (lock free, finishing fast)
with nothing changing — the "deploy succeeded, job finishes, symptom unchanged"
pattern this project's own discipline says not to wave away.

**Round-tripped the actual endpoint instead of guessing again.** Called the exact
row-write REST endpoint the SDK's `update_rows()` uses, directly, with the admin
token. A bare JSON number below precision (`0.0009`) came back `400 INVALID_INPUT` —
rejected outright, explaining why a batch write silently failed inside the refresh
job's caught exception. A plain fixed-point string (`"0.000851196807533056"`)
round-tripped correctly. A string still *containing* scientific notation
(`"7.817113529341168e-05"`) came back `7.8171` — the identical corruption, proving
this is a text-level `E`-notation defect on ingest that no Python-side float rounding
could ever fix.

**Real fix**: every `float` through `_sdk_row` now becomes `f"{v:.4f}"` — a string,
always plain decimal, never `e`/`E`. 741 tests (unchanged count, corrected
assertions).

**Deployed a second time and confirmed the live data repaired**: deployment
`52852000000356181`. `/jobs/refresh` rewrote PageRank/Betweenness for every person;
the exact query that started this investigation now returns 41 nodes with distinct
names and sane magnitudes (`0.0101` down to `0.0001`), zero at or above `1`.

**Audited every other `double` column against live, exhaustively, and found nothing
else to repair**: `RiskScore`/`FlagConfidence` are never actually persisted by this
codebase; `MatchConfidence` `[0.90, 1.0]`; `Weight` `1.0`-`26.0`; `Amount`
₹501.81-₹1,426,326.50; `Confidence` `0.6`-`0.97`; the five socioeconomic columns and
lat/long all real, plausible values. Structural reason, not luck: corruption only
strikes below ~0.0001, and every other column has a domain floor well above that —
only raw graph centrality over a 17k-node graph legitimately gets that small.

---

## 2026-09-04 — six conversational additions, and the real `appsail/upsert` contract

Driven by research into real conversational-AI-for-policing products (eSleuth, Case
IQ, SymphonyAI Sensa Copilot) and the academic/DOJ literature, cross-checked against
the West Midlands Police Microsoft Copilot hallucination incident (a fabricated match
used to justify a real football banning order) as the argument for inheriting the
existing cited-or-refuse discipline rather than adding a bypassable surface.

**Six new intents, all built on data already in the record layer:**
- `INTERROGATION_PREP` — priors, structural case gaps, direct associates.
- `CASE_SIMILARITY_WATCH` — `SIMILAR_CASES` narrowed to an officer's own backlog and
  the unsolved pool.
- `CASE_HANDOFF` — fuses the Copilot brief with the board's own state into one "catch
  me up" narrative.
- `CHALLENGE_FINDING` — a new meta-turn that looks for what would WEAKEN the previous
  answer.
- `PREFILING_CHECK` — the structural-gap check, run proactively before filing.
- `CROSS_STATION_LINKAGE` — reports another station's accused-name match, same
  partial-visibility discipline as associate explanations.

Also: the case-diary draft tags its one DERIVED sentence inline in both the templated
and LLM-generated paths — the direct answer to the West Midlands incident.

**A real Python-version bug caught by the deploy pipeline's smoke-test import.**
`PREFILING_CHECK`'s status sentence split a string literal across a line inside an
f-string's `{}` — valid under Python 3.12+'s relaxed grammar (PEP 701), parsed cleanly
locally (3.13), but the deployed container runs 3.11 and failed with a plain
`SyntaxError` before the build reached AppSail. Fixed; every touched file now also
checked against a local Python 3.11 interpreter, not just whichever version `python`
resolves to.

**A real conversational bug found on the first end-to-end test, fixed the same
pass.** "Poke holes in this." right after "Catch me up on this case." — the most
natural way to chain the two features — found nothing to challenge, because
`CASE_HANDOFF`'s evidence is written `handoff:{fir_id}:summary` and the case-id
extraction only recognised the `fir:{fir_id}` shape. Fixed to also read
`handoff:`/`filing:`/`watch:`/`linkage:` evidence and fall back to `active_fir`.

**The `appsail/upsert` contract — reverse-engineered and finally written down.** No
prior changelog entry contains the actual request shape; every deploy apparently
reconstructed it from scratch. Found by reading the installed Catalyst CLI's own
source: it's a **multipart/form-data PUT**, not JSON — `name`, `memory`, `platform:
"custom_runtime"`, `configuration` as a JSON *string*, `local_object_key` (never
`image`/`object_key`, which 400 with an opaque `INVALID_INPUT`). Neither
`get-signature` nor `upsert` take a resource-id path segment (only `.../configuration`
does). Saved as `scripts/deploy-api.py`.

**Deployed and live-verified twice** (`52852000000400007`, then `52852000000391012`
carrying the `CHALLENGE_FINDING` fix): a real multi-turn session drove all six
intents plus `/explain` against a `linkage:` evidence id.

**Test suite: 830 passed, 2 skipped** (14 new).

**Not done**: no console changes — every new intent renders through the existing
generic citation/evidence rail; `docs/OFFICER_PITCH.md` (new) restates the platform
for a non-technical law-enforcement audience.

---

## 2026-09-04/05 — Strategic reset: independent audit, research, and Phases 0-2 of the resulting roadmap

Full analysis lives in `docs/STRATEGIC_RESET_2026-09-04.md`; this is the terse pointer
plus what got built.

**Why.** A ground-up audit, reading the live code directly rather than trusting
CLAUDE.md's own claims. Found the six v24/25 conversational operations are the most
under-sold part of the product, and that "crime pattern discovery" and "behavioral
profiling" — both named explicitly by the challenge — were only half-built:
reactive/query-driven, never unprompted, despite the underlying signal (co-offending
graph, `_signature_choice` recurring-MO weighting) already sitting in the data.

**Research** (cited in the strategic-reset doc): linkage blindness (Egger 1984) as the
named ViCAP-era failure mode; India's own deployed AI-policing tools (Delhi FRS/CMAPS,
UP Trinetra, Punjab PAIS) and their documented failure pattern (AI match treated as
sufficient, no corroboration, no governing framework) as the sharpest contrast for
Veritas's refuse-or-cite architecture; a live pull of a real competing Datathon
submission (KAVACH 360) confirming map+graph+forecast+chatbot is the default
convergent solution — table stakes, not a differentiator.

**Phase 0 — credibility fixes.**
- **BNS section citations.** `data/generator/refdata.py` cited only the retired IPC
  for every case, despite the dataset spanning the 2024-07-01 BNS transition. Added a
  real, sourced (BPRD's IPC↔BNS correspondence table) date-aware lookup; backfilled
  onto the live 10,000-case dataset in place via the existing narrative-backfill job.
  7 tests.
- **QuickML hard spend guard.** Every QuickML request had no `max_tokens` cap at all
  (open-ended cost per call). Added a cap (`VERITAS_LLM_MAX_TOKENS`, default 900) plus
  a persistent Cache-backed call-count circuit breaker (`VERITAS_LLM_MAX_CALLS`,
  default 300, survives redeploys) that degrades to the deterministic fallback once
  hit — defense-in-depth; the authoritative control is Catalyst's own billing budget
  cap.

**Phase 1 — unprompted cross-station series discovery** (new
`packages/rag_agent/rag_agent/series_detection.py`): finds clusters of open,
unresolved-suspect cases sharing a distinctive MO-clause plus geographic/temporal
proximity with no common IO — the general form of what `CROSS_STATION_LINKAGE` could
only do with a suspect already named on both cases. New intent `SERIES_DISCOVERY`,
wired into `/jobs/refresh`'s 6h cadence and pushed through `/alerts` as a new `series`
event, same partial-visibility discipline. Console: `AlertBell.tsx` gets a second
"Cross-station patterns" section. Found and fixed live: `/jobs/refresh`'s four
independent derived layers still shared one try/except in places — isolated the same
way three prior steps already were.

**Phase 2 — evidence-backed behavioral profile** (new
`packages/rag_agent/rag_agent/behavioral_profile.py`): for a resolved person with 3+
cases — recurring time-of-day, exact repeated MO-clause, geographic range (haversine),
escalation in offence severity (only where the gravity classification itself
increases), recurring co-accused. Never demographic by construction —
caste/religion/gender columns are never read. New intent `BEHAVIORAL_PROFILE`. A real
bug caught by the handler's own test: an edit left a `_trace()` call orphaned in the
wrong `elif`, referencing a sibling-branch variable — `UnboundLocalError` on every
turn. Fixed same pass.

**A second real bug, found the following day.** The live-found `BEHAVIORAL_PROFILE`
routing fix (`9567318`) was dead code: it wrapped only the pronoun alternative in
`(?i:...)` and left the literal structural words case-sensitive, while `classify()`
matches the raw, non-lowercased query — a real sentence starts with a capital "How."
No test had asserted the exact named-subject phrasing reported live. Corrected by
wrapping every structural word in its own `(?i:...)`, keeping `[A-Z]\w+`
case-sensitive (to tell a name apart from "the system"). Regression test added first,
confirmed to fail pre-fix. Redeployed (`52852000000389039`) and verified against the
exact broken live query.

**A near-miss, caught before real data loss.** The prior session's last write, made
as it hit its usage limit, truncated this file to a 2-line stub mid-prepend. Never
committed in that state — `git restore` recovered it with nothing lost. Recorded as
the reason `docs/STRATEGIC_RESET_2026-09-04.md` now exists as a durable artifact
rather than leaning on this file alone.

**Test suite: 868 passed** (up from 830), 2 skipped (pre-existing, unrelated).

**Not done**: Phase 3 (Aequitas live-wiring, minimal graph/edge annotation), Phase 4
(LLM-authored MO narrative — deliberately held pending real Catalyst billing
history), Phase 5 (pitch/README rewrite, demo recording). The fused
proactive-prevention advisory was scoped but not built.

---

## 2026-09-05 — Planning-only pass: state check, then the remaining-work plan written down

No code changed. Confirmed nothing was left running from the prior session (`git
status` clean, live `/health` idle) and turned the "not done" list into a real plan.

**The plan** is Part 9 of `docs/STRATEGIC_RESET_2026-09-04.md`, in priority order: (1)
Aequitas wired into `/jobs/refresh`, CRITICAL, ~1 day; (2) the fused
hotspot+trend+signature prevention advisory, DIFFERENTIATING, ~1-2 days; (3) minimal
graph-edge annotation reusing the board pin mechanism, SUPPORTING, ~1 day; (4) the
AI-authored MO narrative — re-checked live, QuickML remains at 0/300 calls used, so
there's still no billing history to decide against; still recommended to skip for the
competition unless a session is set aside for a small capped test batch; (5) the
pitch/demo/README rewrite, done last once the feature set is final.

---

## 2026-09-05 — Part 9, Items 1-3 built and tested (not yet deployed)

Started by re-verifying the state Part 9 itself claimed rather than trusting it: ran
the full suite (clean, 868/2 skipped, matching the recorded baseline) before touching
anything, per this session's own "fix bugs first" instruction. No regressions found —
nothing to fix. Moved straight to the three unblocked items.

**Item 1 — Aequitas.** `packages/ml_models/fairness_run_audit.py` was real and working
but never called except by hand. Added `("fairness", _run_fairness)` as its own
isolated step in `/jobs/refresh` (`apps/api/api/routers/jobs.py`), caching both
models' reports plus a combined `flagged` bool (`FAIRNESS_CACHE_KEY`,
`fairness_audit_v1`, 24h TTL — same reasoning as the series-scan cache). `/health`
now reports `"not yet run"` / `"clear"` / `"DISPARATE IMPACT FLAGGED"`, and the
console's System panel (`TopBar.tsx`) prints the same line. 4 new/changed tests in
`test_refresh_job.py` and `test_api.py`.

**Item 2 — fused prevention advisory.** New `prediction_agent.advisory_for()` reads
hotspot detection + trend forecasting for a district and returns `None` unless they
actually agree (a real cluster AND a rising forecast) — a hotspot with a flat/falling
forecast isn't news. When it fires, the headline names the district, the window, and
the point count; separate `disclosures` entries carry the confounder caveat (kept
static — a live DoWhy run per district per refresh cycle would price out for a line
of text that doesn't change day to day), a cross-station series-linkage count (joined
on district name, which `series_detection.SeriesResult.districts` and
`data.districts.canonical_name` already share), and the Item 1 fairness flag when set.
New `("advisory", _run_advisory)` step (runs last, after fairness/series so it can
read both caches), new `advisory_v1` cache key, pushed through the existing `/alerts`
SSE stream as a new `advisory` event (`AlertBell.tsx` gained a third "Prevention
advisories" section). 4 tests in `packages/rag_agent/tests/test_advisory.py`, 1 in
`test_refresh_job.py`.

**Item 3 — graph-edge annotation.** `NetworkView.tsx`'s force-graph `click` handler
already distinguished node clicks from empty-canvas clicks; added the third case
(`p.dataType === "edge"`) and a small card with a "Pin this connection" button, wired
through the same `onPinEvidence` callback the evidence rail already uses. The id sent
(`edge:{source}|{type}|{target}`) is graph structure, not an `EvidenceItem`, so it was
never going to be in a prior chat turn's own evidence pool — gave
`orchestrator._pin_evidence_from_context` a new branch, parallel to the existing
`timeline:` branch, that re-derives the edge directly from `data.graph.load_graph()`
and tags the board item `ref_type="graph_edge"`. 2 tests in `test_timeline.py`
(one genuine confluence, one stale/fabricated edge id refusing honestly).

**Verification**: full suite green at 874 tests (868 + 6), 2 skipped, unchanged from
baseline; `apps/web` typechecks (`tsc --noEmit`) and production-builds
(`next build`) cleanly with the new components.

**Not done**: not yet deployed/live-verified (next step); Item 4 (LLM-authored MO
narrative) stays deliberately deferred — unchanged from Part 9's own recommendation,
no real QuickML billing history yet; Item 5 (pitch/demo/README rewrite) untouched.
