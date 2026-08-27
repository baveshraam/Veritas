# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`7d4e581` — "fix(web): unlabeled network nodes and evidence-rail toast overlap" (main,
`github.com/baveshraam/Veritas`). Below it: `f310c4a` (deploy-relay, no code), `23291eb`
(namesake-disambiguation fix), `0988f04` (deploy-relay, no code), `15ff976` (the three
core fixes this pass found). Prior HEAD this pass started from: `9ce69a6`.

## Current live deployment
- **API**: redeployed twice this pass. AppSail app `50043864344` (appComputeId
  `52852000000204688`); final deployment `52852000000318080`. `/health` clean post-deploy
  both times; every fix independently re-verified live afterward through the real
  console, not just the API (see below).
- **Console**: redeployed once this pass (`catalyst deploy --only client`, via the
  documented signed-URL/npm-global-bin workaround — the `catalyst` CLI shim wasn't on
  this shell's `PATH`; it lives at `~/AppData/Roaming/npm/catalyst` on this machine).
  Both `assetPrefix`/localhost guards in `scripts/deploy-console.sh` passed. Live at
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`.

## Date/time of last verification
2026-08-27, this session ("final live judge pass"). **Unlike the immediately prior
pass, real browser/CDP tooling was available and used throughout** — headless Chrome
(`--headless=new --remote-debugging-port=9222`) driven over Node 22's global WebSocket,
per `[[veritas-console-verification]]`. Every finding below was found live, through the
actual rendered console, not inferred from API responses alone; every fix was
re-verified the same way after deploying it.

## What this pass did, and why
The prompt asked for the FINAL live judge/acceptance pass: drive a full investigation
through the real UI, improvise natural investigator phrasing beyond any scripted golden
conversation, and judge every screen the way a competition judge — who knows nothing
about the code — would. This is exactly the kind of pass that has found real bugs before
(the 2026-08-26 CDP sessions, the adversarial-phrasing passes), and it did again.

Ran a ~25-turn live investigation through the real console (open FIR → what happened →
who's involved → priors → why-those-cases → associates → what-supports → similar cases
→ geography → financial trail → what's-unusual → evidence-for → next-steps → briefing →
switch case → follow-up → attempted return → explicit return → context-isolation check →
ambiguous-pronoun clarification → five improvised natural-language follow-ups → Kannada),
screenshotting key steps, then inspected every screenshot as a judge would.

**Found and fixed five real, live defects:**

1. **A refusal still shipped the evidence it had just rejected (P0 — the single most
   damaging finding).** `node_synthesize`'s general refusal branch (`requires_
   escalation`, reason `no_evidence` and others) cleared `state.citations` but not
   `state.evidence_items` — every *other* refusal branch in the same function
   (`CAPABILITY`, `nothing_prior`, `ambiguous_person`) clears both. Reproduced clean,
   live, single-turn: *"Tell me about the flying saucer incident on the moon"* → the
   chat pane correctly showed an honest red-bordered refusal — **and the Evidence rail
   simultaneously showed "8 cited"**, listing 8 unrelated Raichur robbery FIRs at ~40%
   "text similarity." A judge reading both panels side by side sees a direct
   contradiction: the system says it found nothing, while visibly displaying 8 pieces
   of "evidence." Same failure class as BUG-006/RAG-35, recurring through a third door.
   Screenshot: `repro-refusal-evidence.png`. Fixed by clearing `evidence_items` in that
   branch too; confirmed empty live post-deploy (`verify-fix1-refusal-clean.png`).
2. **`CASE_REFERENCE_UNSUPPORTED` only matched an ordinal directly before "case."** The
   already-shipped fix (v6/finalization pass) catches "go back to the **first** case."
   It does not catch **"go back to the case we started with"** — equally natural
   investigator phrasing, no ordinal at all. Live, this fell through to a real semantic
   search that had enough confidence to pass CRAG and returned 5 confidently-cited,
   completely unrelated records (an Attempt to Murder case in Ballari/Kolar, answering
   a question about a Kidnapping case). Broadened the regex to cover a trailing
   back-reference ("case we started/began/opened with") and a bare demonstrative
   ("back to that case"), not just a leading ordinal.
3. **Associate evidence text said `gang: Community 6`.** CLAUDE.md §4 documents this
   grouping as deliberately labelled honestly — "network community 6," never "gang,"
   since the ER records no gang and none is invented. `copilot/brief.py`'s leads
   already follow this; `_network_evidence()` (chat's `PERSON_NETWORK` path) was the
   one place still printing the literal word.
4. **A genuine namesake collision rendered as an apparent duplicate.** "Who are her
   associates?" for Usha Naika listed "Suma Nadkarni is a known associate..." twice,
   verbatim. Confirmed via the raw evidence `source_id`s these are two *different* real
   `PersonUID`s (7334, 8395) who happen to share a `CanonicalName` — not a duplicate-row
   bug, the same namesake possibility BUG-026 already documented for canonical/as-filed
   drift, surfacing here as two genuinely distinct people instead. `_network_evidence`
   now appends `(person <id>)` only when a real collision exists within that specific
   result set — an ordinary list of distinct names is untouched.
5. **Two UI-only defects, found from screenshots, judged as a judge would:**
   - `NetworkView.tsx` labelled a node only above 40% of the graph's max pagerank —
     tuned for large expanded networks, where it correctly thins ~30 nodes to the real
     hubs. On a small, high-variance graph (a bare 4-accused "who is involved" view,
     one clear organiser) that same cutoff left 3 of 4 accused as unlabelled dots — an
     investigator cannot tell who they are. Below a small node count, every node now
     keeps its label.
   - `.toast-stack` (live anomaly alerts) was pinned to the viewport's bottom-right
     corner — the same corner the Evidence rail's citation cards occupy. A stack of 3
     toasts could sit directly over several cards. Moved to anchor under the topbar
     instead (a fixed, predictable height, unlike the rail's dynamic content). Live
     re-check: this reduced the overlap from several cards to, at most, the panel's own
     header/first card when 3 toasts are simultaneously active — a real but smaller
     residual overlap, left as-is rather than redesigned further (see Not done, below).

All five ship with regression tests reproducing the underlying condition directly against
the affected code (not re-running the live repro, which isn't reproducible offline):
5 new backend tests (`packages/rag_agent/tests/test_engine.py`), **374 tests collected,
all green**. Frontend changes are `apps/web` only; `npx tsc --noEmit` clean (no frontend
test suite exists in this repo — none was added, matching existing project convention).

Commits: `15ff976` (fixes 1–3), `23291eb` (fix 4), `7d4e581` (fix 5, frontend). Deploys:
`0988f04`→`52852000000321046` (API, fixes 1–3), `f310c4a`→`52852000000318080` (API, fix
4), console deploy after `7d4e581` (fix 5).

## Verified live this pass (through the real console, not just the API)
- **The three core evidence-integrity/routing fixes** (1–3 above): re-driven clean,
  single-turn, post-deploy — `verify-fix1-refusal-clean.png` (0 evidence items, honest
  empty-state), the case-reference phrasing now refuses correctly, `network community`
  wording confirmed with zero `gang:` occurrences.
- **The namesake fix** (4 above): re-driven through the same 4-turn conversation that
  found it; both "Suma Nadkarni" entries now carry distinct `(person 7334)`/`(person
  8395)` suffixes.
- **Both UI fixes** (5 above): fresh screenshots post console-deploy —
  `verify-fix5-network-labels.png` (all 4 nodes labelled), `verify-fix6-toast-position.png`
  (toast-stack rect confirmed at `top:78` instead of the viewport bottom).
- **The full ~25-turn investigation itself**, end to end, live: open case → case context
  → accused → priors → associates → why-these → similar cases → geography → financial
  (honest negative finding — no account linked) → what's-unusual → evidence-for →
  next-steps → briefing → case switch (a malformed short-form FIR number correctly
  refused rather than guessing) → follow-up on the still-open case (proves a failed
  switch doesn't corrupt context) → attempted return by position (now refuses honestly)
  → explicit return → context-isolation re-check → ambiguous-pronoun clarification (all
  4 names offered) → five improvised natural-language follow-ups ("tell me more about
  her," "what about the other one," "are any of these people connected," "what should I
  focus on first" — correctly reused the prior NEXT_STEPS answer, "what information are
  we missing") → Kannada round-trip (3 citations, correct translation both ways).
- **The real MapLibre/OpenFreeMap basemap**: judged fresh (`06-geography-map.png`) —
  real street names, real district labels, legend, scale, zoom, correct OSM attribution.
  Genuinely judge-ready; no defect found here this pass.
- **RBAC, Cron, QuickML, PDF export**: re-confirmed unchanged from the prior pass (see
  below) — not re-exercised from scratch since nothing this pass touched those surfaces.

## Not verified / not done this pass, stated plainly
- **RBAC was not re-driven live through the console this specific pass** (the prior
  pass's API-level IO-cross-station-refusal check stands, unchanged code path).
- **The toast/evidence-rail overlap is reduced, not eliminated.** With 3 alerts active
  simultaneously the stack can still cover the Evidence panel's header and first card.
  A structurally different placement (e.g., a dedicated alert rail, or docking inside
  the topbar itself) would close this fully; not attempted this pass — the current fix
  already closes the far worse "covers most of the visible evidence" case, and further
  redesign felt like scope creep for a decision-support side-channel, not a core
  investigation surface.
- **Voice pipeline (STT/TTS), case-status filter chips (UI-20), map pan/drag gesture,
  AML positive-case verification, `dowhy`** — unchanged from all prior passes, same
  environmental/data constraints as documented there.
- **QuickML and PDF export** — not re-checked this pass (no code in either area
  changed); the prior pass's BLOCKED status stands: `QUICKML_ENDPOINT_KEY` absent from
  live AppSail config, `/export/pdf` still returns the honest HTML fallback.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
BUG-015 (dowhy), BUG-016 (Kannada latency), BUG-018 (PDF export — HTML fallback,
honest), BUG-022 (QuickML key), BUG-026 (Copilot leads canonical-vs-as-filed name, P2,
deliberately left open) remain open, externally blocked or deliberately scoped out,
unchanged this pass. This pass's five fixes are not yet assigned BUG-NNN numbers (same
pattern several prior passes have used) — see commits `15ff976`/`23291eb`/`7d4e581` for
full detail if numbers are wanted later.

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full, and every fact listed in prior passes' handoffs. New this pass:
**the `catalyst` CLI is installed but not on this shell's `PATH`** — it's the
`zcatalyst-cli` npm global package, shimmed at `~/AppData/Roaming/npm/catalyst[.cmd]`.
Either `export PATH=".../AppData/Roaming/npm:$PATH"` first, or invoke the shim by its
full path, before `scripts/deploy-console.sh` or any other script that shells out to
`catalyst`. Also: **`node_synthesize`'s refusal branches are the one place in this
codebase where "clear both citations and evidence_items" is a rule enforced only by
convention, not by structure** — three of four branches already did this correctly, one
didn't, and it went unnoticed until a live screenshot caught the contradiction. Worth a
second look next time any of those branches is touched.

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator.

## Next recommended action
1. If a QuickML endpoint key or a working Catalyst OAuth sign-in is ever obtained,
   BUG-022 and BUG-018 both close for real — both remain credential-blocked, not
   code-blocked.
2. Consider a real fix for the residual toast/evidence-rail overlap (see above) if it
   keeps coming up in review — a dedicated alert surface rather than a floating stack.
3. BUG-026 (Copilot leads canonical-vs-as-filed name) remains a well-scoped, still-open
   P2 with a documented recommended fix in `docs/QA_FUNCTIONALITY_MATRIX.md` — worth
   picking up in a future pass that isn't racing to close out a submission.
4. Consider whether a genuine "return to a specific earlier case" capability (an actual
   small case-history stack, not just an honest refusal) is worth building — unchanged
   recommendation from the prior pass.
