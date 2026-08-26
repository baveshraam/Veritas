# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`5b33622` — "fix(rag_agent): a decided refusal still ran generic search, padding the
Evidence rail" (main, `github.com/baveshraam/Veritas`), plus two deploy-only commits on
top of it (`62fa880`, `d26c040` — a broken empty relay URL from a shell redirect mistake,
immediately caught and fixed with a corrected one; no code changed in either). Prior HEAD
this pass started from: `6e77f6c`.

## Current live deployment
- API: **redeployed twice this pass**. Final: AppSail app `50043864344`
  (appComputeId `52852000000204688`/`52852000000204690`), deployment
  `52852000000306056` (the refusal-short-circuit fix, on top of the intent-classifier +
  BUG-026 fixes from the same pass's first deploy, `52852000000312040`). `/health` clean
  post-deploy.
- Console: **unchanged this pass** — no `apps/web` file was touched. Still
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`.

## Date/time of last verification
2026-08-26, this session ("finishing pass" — the full 19-turn golden conversation +
North Star closure mega-prompt). Live, through the actual deployed console over CDP
(Chrome `--headless=new --remote-debugging-port`), not curl: the full 19-turn script run
twice (once pre-fix, which found 4 real bugs; once post-fix, all 19 turns + a Kannada
follow-up + an IO cross-station authorization check all correct) — see
`docs/screenshots/2026-08-26-golden-19turn/`.

## Current North-Star status
Every MUST-HAVE item in Part 4's industry-baseline table is now closed or was already
closed: BUG-026 (Copilot leads / NEXT_STEPS now cross-reference canonical vs. as-filed
names) fixed and live-verified this pass. `veritas_audit_verify`'s Cron reliability fix
(BUG-027, prior pass) has not had its "next unattended fire" independently re-observed
this pass — this requires waiting for the schedule itself, not more code, and was not
re-checked. The two SHOULD-HAVE items (QuickML LLM fluency, real PDF via SmartBrowz) were
both **directly re-confirmed still BLOCKED this pass** (see below) — correctly so, not
re-guessed.

## Current objective
The mega-prompt asked for two gates: (1) the full 19-turn golden conversation driven
through the live console via CDP, fixing any real bug found before moving on, and (2)
returning to North Star Part 3's P0/P1 list to close every technically solvable item. Both
gates are met: the golden conversation passes end-to-end post-fix (screenshots +
`log.json` committed), and every open MUST-HAVE was either fixed (BUG-026) or is
externally blocked and re-confirmed as such (QuickML, PDF, the Cron unattended-fire
observation).

## Verified this pass (live, not assumed)

**Four real conversational bugs, found by the golden conversation's FIRST run (not
committed), fixed, redeployed, and re-verified by a SECOND full run (committed) — see
`docs/screenshots/2026-08-26-golden-19turn/README.md` for the full narrative**:

1. **`CASE_PEOPLE` never cleared a stale `active_person`.** The prior code only set
   `active_person` when exactly one accused existed; with several, it did nothing —
   which meant a person named several turns (and cases) earlier silently stayed "active."
   Re-opening a DIFFERENT multi-accused case and then asking a pronoun follow-up ("does
   he have priors?") answered about the stale person instead of asking which of THIS
   case's several accused was meant — the exact scenario RAG-34's ambiguous-person
   clarification exists for, silently bypassed. Fixed in
   `packages/rag_agent/rag_agent/orchestrator.py` (`state.active_entities.active_person =
   ... if len(accused) == 1 else None`, explicit clear). Live-verified at turn 19 of the
   fixed run: the engine now correctly asks "More than one person named in this question
   matches equally well: Usha Naika, Prashanth Krishnamurthy, Nithin Madar, Naveen
   Nayak..." instead of silently answering about a stale subject.
2. **`EXPLAIN_REASONING`'s regex only matched "why (are/were/did) you <verb>" or "why
   ... those <adjective>" with nothing between "those" and the adjective.** Natural
   investigator phrasing from this exact mega-prompt's own example turns — "why did you
   *select* those cases," "why were those associates *surfaced*" (passive, no "you") —
   fell through to `CAUSAL` (on the bare word "why") or a bare repeat of the prior topic
   intent. Fixed in `packages/rag_agent/rag_agent/intents.py`: widened the verb list
   ("select/selecting/selected/choose/...") and the passive-voice branch now allows one
   noun between "those" and the participle. Live-verified at turns 6 and 8.
3. **`NEXT_STEPS`'s keyword list had "investigate next" (active) but not "investigated
   next" (passive).** "What should be investigated next?" — this mega-prompt's own
   phrasing — matched nothing and refused ("I could not find this in the available
   records") instead of returning leads. Fixed by adding the passive form (and "should be
   investigated") to the keyword list. Live-verified at turn 14 — now returns real,
   cited leads.
4. **A refusal `node_orchestrate` already decided (`ambiguous_person`,
   `person_not_on_file`) still let `node_retrieve` run its generic vector-search
   fallback**, because the NEEDS_CASE/NEEDS_SUBJECT guards only skip *setting* a
   duplicate reason (`and not state.refusal_reason`) and never return early when one is
   already set. Every specialist branch requires a subject and was skipped correctly, but
   the untargeted fallback at the bottom of `_run_specialists` has no such guard — it
   searched anyway and handed the officer 5 unrelated criminal-profile citations in the
   Evidence rail, right next to a chat message saying "I will not guess which one you
   mean." Fixed by returning immediately from `node_retrieve` whenever
   `state.refusal_reason` is already set on entry. Live-verified: the Evidence rail on
   the ambiguous-pronoun refusal turn now correctly shows "Evidence for the current
   answer appears here" (empty), not 5 stale citations.

All four ship with regression tests confirmed to fail against pre-fix code first (6 new
tests total this pass: 3 for the intent/state fixes, 1 for the refusal short-circuit, 2
for BUG-026 below). **354 → 361 tests, all green.**

**BUG-026 fixed** (`packages/rag_agent/rag_agent/copilot/brief.py`): Copilot leads and
`NEXT_STEPS` now render `_lead_name()`, which shows `"Soom Nadkarni (filed as \"Suma
Nadkarni\" on this FIR)"` when `vx_person.CanonicalName` differs from the case's own
`Accused.AccusedName`, masked identically to every other name on the surface (a masked
role sees only the placeholder, never a hint that a reconciliation happened). Live-
verified at turns 14 and 15 of the golden conversation: `"Usha Naika (filed as \"Usha
Neik D/o Srinivas\" on this FIR)"` renders correctly throughout.

**Context isolation across a case switch, verified live**: turns 16-17 open an unrelated
case (Mandya, Hurt); turns 18a-18b return to the original case and re-ask "who is
involved" — the answer correctly names the original case's 4 accused, not the Mandya
case's people. This is what turn 18 was designed to catch, and (once bug #1 above was
fixed) it holds.

**Authorization boundary, verified live through the console** (not curl): signed in as
IO (station 101), asked for FIR 100050504202300018 (station 504) — refused with "No
record with that number exists within your access scope," no leak of the record's
existence. Screenshot: `t21-io-cross-station-refused.png`.

**Map re-centering on CASE_LOCATIONS, verified live**: the FIRST run's screenshot of
"where are those cases concentrated?" looked like an untargeted statewide view — turned
out to be a screenshot-timing artifact in the CDP driver (MapLibre's `fitBounds` has a
900ms animation; the driver's post-turn wait was only 400ms). Raised to 1500ms and
re-run: the map correctly re-centers tightly on the real Bengaluru-area FIR points with
recognizable streets/labels. **Not a product bug** — worth remembering for any future CDP
harness against this console (see `[[veritas-console-verification]]`).

**Kannada round-trip, verified live** mid-conversation (not a fresh session): a Kannada
hotspot-count query after 20 English turns returns correctly-cited, RBAC-scope-aware
results; translation grammar is imperfect in places (documented pre-existing limitation,
NLP-05/BUG-016, not new).

**QuickML re-confirmed BLOCKED, directly** (not re-guessed): fetched the live AppSail app
config over the Admin API (`GET .../appsail/52852000000204688`) and read
`configuration.environment.variables` directly — `QUICKML_ENDPOINT_KEY` is absent. No
code change; the honest extractive-fallback path remains correct.

**PDF export re-confirmed BLOCKED, directly**: `POST /export/pdf` against a real session
with a turn still returns `text/html`, byte-identical failure mode to every prior pass
(SmartBrowz's `INVALID_ID`/"No such User" — needs an interactive Catalyst Authentication
sign-in this environment cannot drive). No code change; the console's own "downloaded a
printable HTML copy instead" notice (fixed two passes ago) remains correct and honest.

## Partial capabilities
- **RAG-32/34's ambiguous-person clarification now has a live, non-synthetic
  ambiguity example** (turn 19 of this pass's golden conversation) — the "genuine live
  tie in the dataset" gap noted by several prior passes is closed for the pronoun path
  specifically (the tied name-search path, RAG-32's original scope, still hasn't hit a
  live `record_count` tie by chance).
- RAG-29 (BRIEFING) is now live-verified against a MULTI-accused case (turn 15, FIR 1154,
  4 accused) — closes the "only verified against a single-accused case" gap the QA matrix
  flagged.
- Everything else in the QA matrix's "PARTIAL" column is unchanged this pass — see that
  file directly rather than this summary; the full click-through of every UI control was
  not repeated (this pass's live-console time went to the golden conversation + the
  fixes it found, not a fresh full UI audit).

## Unknown capabilities
- `veritas_audit_verify`'s Cron job's own *next* unattended fire, post-BUG-027, was not
  independently re-observed this pass (it fires on a 12h schedule; re-checking it needs
  either waiting for that window or a manual trigger with `sync=true`, neither of which
  this pass did — not because it's hard, just out of this pass's chosen scope).
- Voice pipeline (STT/TTS), case-status filter chips (UI-20), pan/drag map gesture
  interaction, AML detector positive-case verification — all unchanged from prior passes,
  same environmental/data constraints as documented there.

## External/platform blockers (re-confirmed this pass, not re-guessed)
- **QuickML** (`QUICKML_ENDPOINT_KEY` absent from the live AppSail config, checked
  directly over the Admin API).
- **PDF export** (SmartBrowz `INVALID_ID`, checked directly against a live session).
- **`dowhy`** and **Stratus bucket creation** — untouched this pass, no new information;
  still as documented in `CLAUDE.md` §2 and the v12 changelog.

## New platform fact this pass surfaced
**A CDP screenshot taken before a `fitBounds` animation completes looks like a rendering
bug and isn't one.** MapLibre's `fitBounds({duration: 900})` needs its full 900ms before
the viewport reflects the final zoom/center; a driver that screenshots ~400ms after a
turn finishes streaming will catch the map mid-flight (or, worse, still at its
pre-animation default state) and can misdiagnose a genuine data/rendering issue that
isn't there. Wait at least 1.5s after a turn that switches to the map pane before judging
its screenshot.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
BUG-015 (dowhy), BUG-016 (Kannada latency), BUG-018 (PDF export — HTML fallback, honest),
BUG-022 (QuickML key) remain open, externally blocked, re-confirmed this pass.
BUG-026 is now **CLOSED** (fixed and live-verified this pass, see above). Four newly
found-and-fixed bugs this pass have no BUG-NNN numbers assigned (found and closed within
the same pass) — see the commit messages on `d3eba10` and `5b33622` for full detail if a
number is wanted later.

## Recently completed work (this pass)
1. **The full 19-turn golden investigation, driven live through the console via CDP** —
   the item four consecutive prior-pass handoffs named as the top outstanding action.
   Found and fixed 4 real conversational bugs (above), redeployed, and re-ran the entire
   script to confirm all 19 turns + a Kannada follow-up + an IO cross-station
   authorization check are correct. Screenshots + machine-readable log committed at
   `docs/screenshots/2026-08-26-golden-19turn/`.
2. **BUG-026 fixed** — Copilot leads/`NEXT_STEPS` now show the as-filed name alongside
   the canonical one when entity resolution reconciled a romanisation variant, masked
   identically to every other name on the surface.
3. **QuickML and PDF export both re-confirmed BLOCKED by direct live check**, not
   re-asserted from a prior pass's note — per this pass's own instruction not to waste
   time re-guessing platform APIs that have already been root-caused.
4. Two API redeploys via the relay pipeline (GitHub Actions build → Catalyst signed URL
   → `appsail/upsert`), both polled to `deployment_status: success` and confirmed via
   `/health` before proceeding — plus one self-inflicted broken deploy commit (an empty
   `relay-upload.url` from a shell redirect that ran before the async fetch resolved),
   caught by the workflow failing and fixed with a corrected commit within minutes.

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full, and every fact listed in the last four passes' handoffs (ER has
no person §0; sqlite mirror + ~23s cold-container cost; ZCQL has no bind params and no
cross-table JOINs live; the map's `maxZoom: 9` / single-district-scoping design; the
`fitBounds` animation timing note above — new this pass). One more, from this pass:
**intent classification is a single label per turn** — a compound query like "Go back to
FIR X. Who is involved?" scores both FIR_LOOKUP and CASE_PEOPLE, and the tie-break (favor
the intent declared earlier in `INTENTS`) picks FIR_LOOKUP, silently dropping the second
half of the question. This is a real architectural limit of the deterministic keyword
classifier, not a bug to chase — an officer conversation naturally comes as separate
turns anyway, and the golden-conversation script was corrected to phrase turn 18 as two
turns (`t18a`/`t18b`) rather than one compound sentence, which is also the more realistic
phrasing.

## Known regressions / traps that must not return
- Every prior-pass trap (see `CLAUDE.md`) is still current.
- **New this pass**: the four bugs above, each now covered by a regression test — if any
  of them regress, `pytest` catches it before a live pass has to rediscover it the hard
  way again.
- **New this pass**: do not judge a map-pane screenshot taken less than ~1.5s after a
  turn finishes streaming (see "New platform fact" above).

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator.

## Acceptance criteria for the current objective
Met: the golden conversation passes end-to-end live through the console; the map updates
correctly in context; every technically-solvable North Star P0/P1 gap is closed
(BUG-026) or genuinely, directly re-confirmed blocked (QuickML, PDF); the API deployment
is stable post-redeploy (`/health` clean); screenshots are committed and were visually
judged before writing this file, not merely captured.

## Last verification evidence
`docs/screenshots/2026-08-26-golden-19turn/` — 25 screenshots (19 golden turns + sign-in
+ a citation-click attempt + Kannada + the IO authorization check) + `log.json` (every
turn's query/answer/citation-count/refusal-flag/active-pane, machine-readable) + a
README narrating what each screenshot proves and the four bugs found along the way.

## Next recommended action
1. **Independently observe `veritas_audit_verify`'s next unattended Cron fire** — the
   fix (BUG-027) is deployed and unit-tested, but its own "does the schedule actually
   succeed with nobody watching" claim wasn't re-checked this pass. `GET
   /jobs/audit-verify` (no `sync=true`) should show `success_count` incrementing on its
   own next time someone lists the live Cron job.
2. If a QuickML endpoint key or a working Catalyst OAuth sign-in is ever obtained outside
   this tooling, BUG-022 and BUG-018 both close for real — both remain credential-blocked,
   not code-blocked, confirmed directly this pass.
3. RAG-32's ORIGINAL scope (a genuine tied `record_count` from a plain name SEARCH, not
   a pronoun) still hasn't been hit live by chance — low priority, the mechanism is
   already unit-tested and now has a live pronoun-side proof (this pass's turn 19).
4. Consider assigning BUG-NNN numbers to this pass's four fixes if `PHASE1_FAILURE_LOG.md`
   is the canonical place future audits expect to find them — this pass fixed them
   in-line from the golden-conversation script's own findings rather than logging them
   there first, which is faster but leaves that log's numbering one pass behind.
