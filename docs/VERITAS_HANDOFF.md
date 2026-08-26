# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`942e323` — "feat(map): replace self-drawn canvas with a real OpenFreeMap/MapLibre
basemap" (main, `github.com/baveshraam/Veritas`). Prior HEAD this pass started from:
`9da83f8` — "docs: handoff/work-log/QA-matrix/changelog record the map + conversational
pass".

## Current live deployment
- API: **unchanged this pass** — `apps/api` and every package were untouched. Still
  AppSail app `50043864344` (appComputeId `52852000000204688`), deployment
  `52852000000325027` (the pronoun-disambiguation/CASE_LOCATIONS-message fixes, prior
  pass).
- Console: **redeployed this pass** (`scripts/deploy-console.sh`), carrying the real
  OpenFreeMap basemap. Live-verified via CDP screenshots against the deployed URL, not
  just a green build.
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`

## Date/time of last verification
2026-08-26, this session ("map basemap upgrade" pass). Local: API against the sqlite
mirror + console dev server, 4 queries driven headlessly over CDP. Live: the same 4
queries plus one explicit no-subject refusal, replayed against the deployed console after
`scripts/deploy-console.sh` — the first live attempt caught a cold AppSail container
mid-warm-up (handled gracefully by the sign-in gate's own copy, not a bug), the retry
after warm-up matched local rendering exactly.

## Current North-Star status
Unchanged — this pass did not touch `docs/VERITAS_NORTH_STAR.md`'s Part 3 P0/P1 list. It
was scoped narrowly to one thing named launch-blocking: the map basemap itself (a
self-drawn dark canvas with no real geography under it, even after v14's zoom/legend
fixes).

## Current objective
The mega-prompt that ran this pass asked for a real MapLibre + OpenFreeMap basemap while
keeping every existing Veritas overlay (FIR points, hotspot density, district labels,
legend, scale, evidence semantics), local QA, a live redeploy, and live re-verification.
All of that was completed — see "Verified this pass" below. The next session should read
this file + `docs/QA_FUNCTIONALITY_MATRIX.md`'s UI-24 row before deciding what to do next;
the broader "19-turn golden conversation through the console" and North Star P0/P1
gap-closing items named as outstanding in the prior two passes' handoffs are still
outstanding — nothing about them changed this pass.

## Verified this pass (live, not assumed)

**Map basemap** (`apps/web/components/viz/MapView.tsx`, `apps/web/app/globals.css`,
`apps/web/components/viz/palette.ts`):
- Replaced the flat self-drawn background with a real MapLibre style,
  `https://tiles.openfreemap.org/styles/liberty` (OSM-derived, no API key/registration) —
  the fifth documented Catalyst exception (`CLAUDE.md` §2: no service in the catalog is a
  map tile provider). `NEXT_PUBLIC_MAP_STYLE` still overrides it for a self-hosted tile
  server, zero code change.
- District reference dots/labels re-styled for contrast against a real (non-black)
  basemap. Compact `AttributionControl` added (ODbL requires it now that real OSM tile
  data is in use). `MAP_BG` deleted from `palette.ts` (no remaining callers). Every other
  overlay — FIR points, hotspot polygons, legend, scale, v14's `maxZoom: 9` fix —
  unchanged.
- Local CDP verification (4 queries): tight single-district cluster (Mandya), bare
  statewide-phrased query (correctly falls back to the true busiest district — Bengaluru
  Urban), a distant district (Bidar, Telangana border, to prove re-centering works
  anywhere in the state), a district with no hotspot evidence in the local mirror (Kodagu
  — honest refusal, graceful fallback to the case index).
- Deployed console-only (`scripts/deploy-console.sh` — nothing in `apps/api` or the
  packages changed) and re-verified live: same 4 queries plus one explicit no-subject
  refusal ("Show me the money trail"). The live dataset had hotspot evidence for Kodagu
  where the local mirror didn't (a data-state difference between the two backends, not a
  bug) — produced the most visually distinctive shot of the pass (dense Western Ghats
  forest around Madikeri).
- Screenshots: `docs/screenshots/2026-08-26-real-basemap/` (4 local + 5 live + README),
  supersedes `docs/screenshots/2026-08-26-map-investigator-grade/` (marked superseded in
  its own README, kept for history).

## Partial capabilities
Unchanged from the prior pass — RAG-32 (a genuine live ambiguous-NAME tie), RAG-29
(BRIEFING only live-verified against a single-accused case), PDF export, identity F1
against the live dataset, AML detectors against a real positive case. Nothing this pass
touched any of these.

## Unknown capabilities
Unchanged from the prior pass — the full 19-turn golden conversation was not driven end to
end through the live console this pass either; this pass's live verification was scoped to
the map (4 queries + 1 refusal), not a full conversational script.

## External/platform blockers (unchanged, not re-checked this pass)
QuickML, PDF export, `dowhy`, Stratus bucket creation — nothing in this pass's scope
touched any of these; last checked in the two prior passes (still all BLOCKED/deferred as
documented there).

## New platform fact this pass surfaced
**A cold AppSail container's warm-up is visible and handled at the UI layer, not just the
API layer.** The sign-in gate already shows "Still loading the duty roster — the service
is warming up" while `/auth/officers` is slow to answer — this pass's first live CDP
attempt hit exactly that screen (the composer textarea doesn't exist yet, so a query sent
too early fails with a JS `TypeError: Illegal invocation` from calling a native property
setter with a null `this`). Not a map bug — a CDP driver against a **freshly-deployed**
console needs to either wait long enough for the roster to load or poll for the composer's
existence before sending a query, the same way a human officer would just wait for the
spinner. Worth remembering the next time a live CDP session's first query inexplicably
fails right after a deploy.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
Unchanged — this pass found no new bug, only a UX/platform question (the cold-start CDP
trap above) that isn't a product defect. BUG-015 (dowhy), BUG-016 (Kannada latency),
BUG-018 (PDF export), BUG-022 (QuickML key), BUG-026 (Copilot leads name mismatch) remain
open, untouched this pass.

## Recently completed work (this pass)
1. **Real MapLibre + OpenFreeMap basemap replaces the self-drawn dark canvas** — every
   existing Veritas overlay kept and re-tuned for legibility against real (non-black)
   terrain. Console redeployed and live-verified.
2. **OSM attribution restored** — the old CSS unconditionally hid it; now a styled compact
   control, correct now that real third-party tile data is in use.
3. **Local + live CDP screenshots committed**, not left in a scratchpad —
   `docs/screenshots/2026-08-26-real-basemap/`, with the superseded prior set marked as
   such rather than silently orphaned.

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full. In addition to every fact the prior passes already listed here
(ER has no person §0; sqlite mirror + ~23s cold-container cost; ZCQL has no bind params
and no cross-table JOINs live; `node_orchestrate`/`node_retrieve` persistence split; the
map's `DISTRICTS` array always renders every district's dot/label, `maxZoom` determines
how many stay in frame): **every map-producing intent (`HOTSPOT`, `CRIME_SEARCH`'s map
path) is single-district-scoped by design** (`_district_code()` in
`packages/rag_agent/rag_agent/orchestrator.py`) — there is no "statewide, all districts at
once" map query in this system, by architecture, not by oversight. A bare/unscoped
question falls back to the single busiest district (`crime_counts_by_district(limit=1)`),
never to a multi-district scatter. "Broad Karnataka" QA therefore means "the viewport at
`maxZoom: 9` keeps several neighbouring districts in frame," not "the data spans multiple
districts" — don't chase a multi-district data view as if it were a missing feature.

## Known regressions / traps that must not return
- (Every prior-pass trap — see `CLAUDE.md`'s own listing — all still current.)
- **New this pass**: a headless CDP session against a console **right after a fresh
  deploy** can hit a cold AppSail container. Wait for the roster to load (or poll for the
  composer textarea) before sending the first query — see "New platform fact" above.

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator.

## Acceptance criteria for the current objective
Met in full: real basemap (OpenFreeMap/MapLibre), every existing overlay preserved, local
QA against 4 representative queries with self-judged screenshots, a console-only deploy,
and live re-verification of the same queries plus one refusal case — all documented in
`docs/screenshots/2026-08-26-real-basemap/`.

## Last verification evidence
`docs/screenshots/2026-08-26-real-basemap/` — 4 local screenshots + 5 live screenshots +
README explaining each.

## Next recommended action
1. Drive the full 19-turn golden conversation through the actual live CONSOLE via CDP
   (still not done across four passes now) — this pass's own live check was scoped to the
   map (4 queries + 1 refusal), not a full conversational script.
2. Return to `docs/VERITAS_NORTH_STAR.md`'s Part 3 P0/P1 list — untouched across the last
   four passes.
3. If a QuickML endpoint key or a Catalyst OAuth sign-in is ever obtained outside this
   tooling, BUG-022 and BUG-018 both close for real — both are credential-blocked, not
   code-blocked.
4. Consider whether real district *boundary* polygons are worth sourcing (e.g. a public
   Karnataka district shapefile bundled into the repo) now that the basemap itself is
   real — the centroids-only approach was originally a compromise forced by having no
   basemap at all to place a boundary against; that constraint is gone, though sourcing
   and licensing a boundary dataset is new scope, not a trivial follow-on.
