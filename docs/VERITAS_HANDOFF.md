# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`06fa7e1` — "deploy: relay the pronoun-clarification and CASE_LOCATIONS message fixes"
(main, pushed to `github.com/baveshraam/Veritas`)

Prior HEAD this pass started from: `839f9b5` (conversational-architecture pass, prior
session).

## Current live deployment
- API: AppSail app `50043864344` (appComputeId `52852000000204688`), deployment
  `52852000000325027`, redeployed 2026-08-26 carrying commit `2d382d4` (the
  pronoun-disambiguation and CASE_LOCATIONS-message fixes) — the only API deploy this
  pass, live-verified with the exact reproduction sequence that found the bug.
- Console: redeployed this pass (`scripts/deploy-console.sh`), carrying commit
  `2a903ba` (the map fix). Live-verified via CDP screenshot against the deployed URL,
  not just a green build.
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`

## Date/time of last verification
2026-08-26, this session ("final product pass" — map + conversational verification).
Map: CDP screenshots against the live console, both the previously-broken tight-cluster
query and a broad statewide one. Conversational: a 9-turn live curl/SSE session against
the production API (not a mock), plus a 2-turn cross-station RBAC check, run BEFORE and
AFTER the API redeploy to prove the fix.

## Current North-Star status
Unchanged — `docs/VERITAS_NORTH_STAR.md`'s Part 3 P0/P1 list was not re-audited this
pass. This pass was scoped to two things a "final product pass" mega-prompt named as
launch-blocking: the map's actual visual/geographic legibility (inspected and confirmed
broken, then fixed), and whether the conversational architecture holds up under a real
live multi-turn session (mostly yes — it found and fixed one real gap rather than zero).

## Current objective
The mega-prompt that ran this pass asked for the FULL scope: map, a 19-turn golden
conversation, a UI judge-review click-through, QuickML re-investigation, and North Star
baseline gap-closing. This pass completed the map fix and a live conversational
verification pass in depth (not breadth) — see "Not done this pass" below for exactly
what remains of that original scope. The next session should read this file +
`docs/QA_FUNCTIONALITY_MATRIX.md`'s new RAG-34 row and "does NOT yet cover" section
before deciding what to do next.

## Verified this pass (live, not assumed)

**Map** (`apps/web/components/viz/MapView.tsx`):
- The defect was real, not a stale screenshot: compared the mega-prompt's complaint
  against the already-committed `docs/screenshots/2026-08-26-conversational-
  architecture/06-case-locations-map.png` (a genuine CASE_LOCATIONS answer) and found
  `fitBounds`'s `maxZoom:11` was the cause — a tight cluster (a handful of FIRs in one
  taluk) zoomed in so far that every neighbouring district label fell outside the
  viewport.
- Fixed: `maxZoom` capped at 9, a legend added, hotspot fill/line opacity raised.
- Live-verified via CDP against the deployed console, both regimes: a tight
  single-district cluster now shows 2-3 neighbouring district labels + legend + scale
  (`docs/screenshots/2026-08-26-map-investigator-grade/01-...png`); a broad statewide
  query shows 6 labels + a visible hotspot polygon outline
  (`.../02-...png`).
- Also verified locally first (API run against the existing sqlite mirror,
  `data/.veritas/ds.sqlite3`, same 10,000-case dataset) before touching the live
  deployment — see "Important architecture facts" below for a real platform constraint
  this surfaced (AppSail's CORS preflight allow-list).

**Conversational architecture** (`packages/rag_agent/rag_agent/orchestrator.py`):
- A 9-turn live session against the production API (IG role): FIR_LOOKUP → CASE_CONTEXT
  → CASE_PEOPLE (2 accused named, correctly left unresolved) → a pronoun follow-up →
  EXPLAIN_REASONING → EVIDENCE_FOR → CASE_LOCATIONS → a guilt-probability question
  (correctly refused, no probability-of-guilt ever given) → a Kannada round-trip. All
  intents routed correctly; RBAC/session persistence from the prior pass still holds.
- **Found and fixed live**: the pronoun follow-up ("Does he have priors?") fell to a
  bare `no_subject` refusal instead of asking which of the two named CASE_PEOPLE
  candidates was meant. Fixed by reusing the existing `ambiguous_person` clarification
  path, sourced from the previous turn's own stored citations. Re-ran the exact same
  9-turn sequence after redeploying: turn 4 now reads "More than one person named in
  this question matches equally well: Usha Naika, Soom Nadkarni. I will not guess which
  one you mean..." — confirmed live, not just in the test suite.
- **Found and fixed live**: `CASE_LOCATIONS`'s "nothing to map" refusal was reusing
  `EXPLAIN_REASONING`'s "this is the first answer" message, which was false on turn 7
  (where it was actually observed). Now has its own message.
- A 2-turn RBAC check (IO role, cross-station): FIR_LOOKUP correctly refuses with no
  leak; the follow-up "What happened?" correctly refuses `no_case` (no case was
  legitimately opened) — both re-confirmed unchanged from the prior pass.
- **QuickML re-checked directly** (fetched the live AppSail `configuration.environment.
  variables` object over the Admin API): `QUICKML_ENDPOINT_KEY` is still absent.
  Unchanged, correctly BLOCKED.

## Partial capabilities
Unchanged from the prior pass — RAG-32 (a genuine live ambiguous-NAME tie was never
observed; RAG-34 above is a related but distinct mechanism, triggered by a previous
turn's candidate list rather than a fresh name search), RAG-29 (BRIEFING only
live-verified against a single-accused case), PDF export, identity F1 against the live
dataset, AML detectors against a real positive case.

## Unknown capabilities
Unchanged from the prior pass, plus: the full 19-turn golden conversation (with an
explicit case-switch-and-back and a genuine ambiguous-name tie) was not driven end to
end through the live CONSOLE this pass — only a 9-turn subset, over curl/SSE against the
API (same orchestrator code path, but doesn't exercise console rendering beyond the map).

## External/platform blockers (unchanged, re-confirmed this pass)
- QuickML — re-checked directly this pass, still absent.
- PDF export, `dowhy`, Stratus bucket creation — unchanged, not re-checked this pass (no
  code in these areas was touched).

## New platform fact this pass surfaced
**AppSail answers CORS preflight (`OPTIONS`) at the platform edge for exactly one
allow-listed origin — the deployed console's own — not via the app's own
`VERITAS_CORS_ORIGINS` env var or its `CORSMiddleware`.** A POST with a JSON body (which
triggers a preflight) from any other origin, including `localhost:3000` in local dev,
gets a bare `200` with NO CORS headers on the `OPTIONS` response and fails in the
browser with "Failed to fetch" — even though a simple GET (no preflight) from the same
origin succeeds via the app's own CORS headers. This is why `?as=DSP` sign-in worked
against a LOCAL API (uvicorn + `VERITAS_DEV_MODE=1`, no AppSail edge involved) but failed
against the LIVE API from local dev. Not a bug in this codebase — a measured fact about
the platform, worth knowing before the next session assumes local-dev-against-live-API
should just work for any POST route.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
Unchanged tracked-bug count — this pass's two fixes (the tight-cluster map zoom, the
pronoun-after-CASE_PEOPLE refusal, and the CASE_LOCATIONS message) were found AND fixed
live in the same pass, so none were logged as standing open bugs. BUG-015 (dowhy),
BUG-016 (Kannada latency), BUG-018 (PDF export), BUG-022 (QuickML key), BUG-026 (Copilot
leads name mismatch) remain open, untouched this pass.

## Recently completed work (this pass)
1. **Map's geographic orientation fixed for tight result clusters** — `maxZoom` capped
   at 9, a legend added (individual FIR point vs. hotspot density), hotspot fill/line
   opacity raised. (`2a903ba`, console redeployed)
2. **A pronoun after a multi-person CASE_PEOPLE turn now asks instead of refusing
   blindly** — reuses the existing ambiguous-name clarification path, sourced from the
   previous turn's stored citations. (`2d382d4`, deployed `52852000000325027`)
3. **CASE_LOCATIONS' refusal message no longer claims "this is the first answer" when
   it demonstrably isn't** — same commit.
4. **QuickML re-confirmed BLOCKED** by fetching the live AppSail configuration directly.
5. **Live screenshots and a live conversational log committed**, not left in a
   scratchpad — `docs/screenshots/2026-08-26-map-investigator-grade/`.

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full. In addition to every fact the prior two passes already listed
here (ER has no person §0; sqlite mirror + ~23s cold-container cost; ZCQL has no bind
params and no cross-table JOINs live; `node_orchestrate` persists focus before
retrieval, `node_retrieve` must persist again for anything retrieval itself resolves):
**a pronoun-disambiguation candidate list is sourced from the PREVIOUS turn's stored
citations (`vx_conversation_turn`), never from a new persisted session-focus field** —
`SessionFocus` maps 1:1 to `vx_session`'s columns, and adding a new column there is a
live Data Store schema change, out of proportion for this kind of UX fix. If a future
session needs candidates to survive MORE than one turn back, that's the point to
reconsider a schema change, not before. Also: **the map's `DISTRICTS` array (31 real
centroids) always renders every district's dot/label — `maxZoom` is what determines how
many stay inside the viewport after `fitBounds`**, so a "not enough labels visible" bug
is a zoom/bounds problem, not a missing-data problem, and should be diagnosed there
first.

## Known regressions / traps that must not return
- (Every prior-pass trap — `_case()`/`_CASE_SELECT` join-budget, `VERITAS_RESTART_NONCE`
  warm-up-thread, CAUSAL/FINANCIAL authoritative-evidence pair, `/jobs/*`
  synchronous-work, `vx_graph_edge` multi-edge collapse, the case-scoped
  re-authorization-on-every-use rule, the shared-keyword intent-routing trap — all still
  current, see `CLAUDE.md`'s own listing.)
- **New this pass**: don't test a POST route against the LIVE API from local dev and
  conclude the route is broken — check whether it's the AppSail CORS-preflight
  allow-list first (see "New platform fact" above). Run the API locally
  (`VERITAS_DS_BACKEND=sqlite`, `VERITAS_DEV_MODE=1`) for local dev testing instead.
- **New this pass**: a `refusal_reason` string is directly coupled to a
  `REFUSAL_MESSAGES` dict entry (`evidence/evaluator.py`) — reusing an existing reason
  for a new situation silently inherits that situation's wording, which can become
  factually wrong (this is exactly how the CASE_LOCATIONS bug happened). A new refusal
  situation with different truth conditions needs its own reason string, even if the
  triggering logic looks superficially similar to an existing one.

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator.

## Acceptance criteria for the current objective
The mega-prompt's stop condition was broad (map + 19-turn golden conversation + full UI
judge review + North Star gaps). This pass met it for the map (inspected, fixed, visually
judged, live-verified) and made real, live-verified progress on the conversational
architecture (found and fixed a genuine gap, not just re-confirmed what already worked)
— but did not attempt the full breadth (19-turn console-driven script, full UI
click-through, North Star P0/P1 closure) in the time available. See "Not done this pass"
for the precise remainder.

## Last verification evidence
`docs/screenshots/2026-08-26-map-investigator-grade/` (2 live screenshots + README);
the 9-turn conversational session's output is not separately committed as a transcript
file — reproduce it via `packages/rag_agent/tests/test_engine.py::
test_a_bare_pronoun_after_case_people_asks_which_of_the_named_candidates` (unit-level)
or by replaying the turn sequence in this file's "Verified this pass" section against
the live `/chat` endpoint.

## Next recommended action
1. Drive the full 19-turn golden conversation through the actual live CONSOLE via CDP
   (not curl) — this pass's 9-turn check used curl/SSE, which proves the orchestrator
   logic but not console rendering across a long session (context switches, citation
   chip clicks mid-conversation, the map updating from a conversational turn).
2. Construct a genuine ambiguous-NAME tie (RAG-32) deliberately, since no live query has
   ever hit one naturally across three passes of trying.
3. Return to `docs/VERITAS_NORTH_STAR.md`'s Part 3 P0/P1 list — untouched across the
   last three passes. Narrative diversity (already fixed per the matrix) and the
   LLM-fluency gap (QuickML-blocked, re-confirmed blocked again this pass) are the
   largest remaining named items.
4. If a QuickML endpoint key or a Catalyst OAuth sign-in is ever obtained outside this
   tooling, BUG-022 and BUG-018 both close for real — both are credential-blocked, not
   code-blocked, unchanged after three passes of re-checking.
5. Consider whether the new `_recent_person_candidates` mechanism (RAG-34) should also
   back other pronoun-adjacent situations (e.g. "the second person" / "the first one" as
   an explicit ordinal reference into the same candidate list) — deliberately scoped to
   the plain-pronoun case this pass, since that's the one a real live session actually
   hit.
