# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`1aecd82` — "fix(web): toast stack no longer overlays the Evidence rail" (main,
`github.com/baveshraam/Veritas`). Below it: `7759ec4` (final live judge pass docs),
`7d4e581` (unlabeled network nodes + the first toast fix attempt), `23291eb`
(namesake-disambiguation fix). No backend/API code changed this pass — the API
deployment (`52852000000318080`) is unchanged from the prior pass.

## Current live deployment
- **API**: unchanged this pass, still `52852000000318080` (AppSail app `50043864344`,
  appComputeId `52852000000204688`). Nothing in `apps/api` or the packages changed.
- **Console**: redeployed this pass (`scripts/deploy-console.sh`, commit `1aecd82`) for
  the toast/Evidence-rail structural fix. Live at
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`.

## Date/time of last verification
2026-08-27, this session ("Catalyst blocker resolution + industry gap analysis" pass).
Headless Chrome + CDP was available and used to verify the toast fix live (a real
in-flight anomaly toast confirmed structurally unable to overlap the Evidence rail).
QuickML/PDF were investigated via the authenticated Catalyst CLI and Admin API
directly, not re-guessed from prior notes.

## What this pass did, and why
The prompt asked for a from-scratch re-investigation of QuickML and PDF export via
the authenticated Catalyst CLI/Admin API — explicitly not to trust the prior "BLOCKED"
classification without re-checking — followed by the two named small fixes as
fallback (toast overlap, BUG-026), then a live-research industry gap analysis.

**QuickML: re-investigated, BLOCKED confirmed with a concrete, freshly-verified
reason** (not the same reason restated — actually re-derived):
- The Catalyst CLI (v1.26.2, authenticated) has no QuickML command at all.
- Probed the Admin API directly for a model/endpoint discovery route
  (`.../quickml/model`, `.../quickml/models`, `.../ml/model`, `.../quickml`) — all
  404. `.../connections` (Catalyst's Connections/secrets feature) returned a real,
  empty list — nothing stored there either.
- Fetched the live AppSail app's configuration and, separately, triggered a real
  `/chat` call and read `/health` immediately after: `QUICKML_ENDPOINT` **is**
  actually set on the live container (an earlier session's guessed URL,
  `.../quickml/v1/project/{id}/glm/chat`, no known provenance — see
  `PHASE1_FAILURE_LOG.md` BUG-022) and the live call still fails with the identical
  `PATTERN_NOT_MATCHED` error every prior pass recorded. `QUICKML_ENDPOINT_KEY`
  remains unset.
- Fetched Zoho's current LLM Serving documentation directly: it states the invoke
  URL/key come **only** from the console's "Model Details → API Details" popup, and
  documents no Admin API alternative.
- **No CLI command, Admin API route, or Connections mechanism in this authenticated
  environment can discover or configure a working QuickML endpoint.** This is a
  genuine console-UI-only platform gap, confirmed today, not a credential this
  session failed to locate. Stopped investigating here per the prompt's own
  instruction against repeated guessing. **BLOCKED, unchanged in outcome, changed in
  how firmly the reason is now established.**

**PDF export: re-confirmed BLOCKED, the identity question specifically closed out.**
Live `/export/pdf` still returns the identical `INVALID_ID`/"No such User" from
SmartBrowz and "no Chromium-family browser found on this host" from the local
fallback. New this pass: checked whether the 6 officer accounts have real Catalyst
identities — they do (`GET .../project-user`, all `ACTIVE` App Users) — but
`apps/api/api/auth/`'s actual sign-in flow is a custom `POST /auth/token` REST call,
never Catalyst's own hosted login, so no request ever carries a genuine Catalyst
session cookie for SmartBrowz to resolve. Minting one server-side without the
officer completing a real interactive Catalyst sign-in would be authentication
bypass — explicitly out of scope. **BLOCKED, root cause now stated precisely.**

**Fixed (commit `1aecd82`, console redeployed) — the toast/Evidence-rail overlap,
closed structurally rather than reduced further:**
`AlertToasts` moved out of `position: fixed` and into the Evidence rail pane's own
flexbox column, rendered between `.pane-head` and the scrollable `.pane-body`. A
toast can now only push the citation list down; it cannot occlude a card, regardless
of how many alerts are active. Live-verified via CDP: a real anomaly toast rendered
as a `position: static` child of `.pane.glass.rail`, above `.pane-body`.

**BUG-026: found already fixed, not re-fixed.** `copilot/brief.py`'s `_lead_name()`
already reconciles canonical/as-filed names (landed 2026-08-26, finishing pass).
Live-confirmed unchanged and correct on FIR 9992 via `/copilot/9992`. The only real
defect was this file's own "open bugs" list having drifted stale against
`docs/QA_FUNCTIONALITY_MATRIX.md`'s own detailed section, which already said FIXED —
corrected below.

**Industry gap analysis** — `docs/INDUSTRY_GAP_ANALYSIS.md` (new). Live research
against Palantir Gotham, IBM i2 Analyst's Notebook, Maltego, and DFIR chain-of-custody
practice. Headline finding: Veritas's largest gap is that it has no investigation
memory surviving past one chat session — every mature platform researched treats a
persistent, editable case artifact as the analyst's core object. Ranked, smallest
first: (1) a persistent per-case board (pin evidence/leads, officer notes, survives
across sessions and officers), (2) lead disposition (pursued/dismissed) on the same
schema, (3) a cross-entity timeline correlation view. None built this pass — analysis
plus the two named small fixes only, as scoped.

## Verified live this pass
- **Toast/Evidence-rail overlap**: CDP-confirmed structurally closed (see above).
- **BUG-026**: live-confirmed still correct via a real `/copilot/9992` call.
- **QuickML**: live-confirmed the exact current failure (`PATTERN_NOT_MATCHED`) via a
  real `/chat` call + `/health` re-check, and confirmed via the Admin API that the
  configured `QUICKML_ENDPOINT` has no working provenance and no key is set.
- **PDF export**: live-confirmed unchanged via a real `/export/pdf` call.

## Not verified / not done this pass, stated plainly
- **None of the three industry-gap recommendations were implemented** — this pass was
  scoped to analysis plus the two named small fixes, not new feature work.
- **No full UI click-through beyond the toast fix** — the console wasn't otherwise
  re-driven; the prior "final live judge pass" CDP verification of the rest of the UI
  stands, unrepeated here since nothing else in the UI changed.
- **`dowhy`** — explicitly out of scope this pass per the prompt's own instruction not
  to prioritize it without a clean way to fit the deployment size constraints.
  Unchanged from CLAUDE.md v12's measured-and-declined analysis.
- **Voice pipeline, case-status filter chips, map pan/drag, AML positive-case
  verification** — unchanged from all prior passes, same constraints as documented
  there.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
BUG-015 (`dowhy`), BUG-016 (Kannada latency), BUG-018 (PDF export — HTML fallback,
honest), BUG-022 (QuickML endpoint/key — now confirmed console-UI-only, no Admin API
path exists) remain open, externally/platform blocked, unchanged this pass. **BUG-026
is fixed** (corrected from this file's own stale prior listing — see above; the fix
landed 2026-08-26 and was never re-opened, this file simply hadn't caught up to it).

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full, and every fact listed in prior passes' handoffs. New this
pass: **QUICKML_ENDPOINT is genuinely set on the live AppSail container** (to an
unverified-provenance guessed URL from an earlier session) even though it does not
appear in every Admin API view of the app's configuration a session might fetch —
don't infer "not configured" from a configuration GET alone; a live `/health` check
after a real `/chat` call is the reliable signal, since `ENDPOINT`/`ENDPOINT_KEY` are
read from `os.getenv` once at process import in `llm.py`. **The 6 officer accounts
are real, ACTIVE Catalyst App User identities** (`GET .../project-user`) — but the
console's sign-in flow never establishes a Catalyst session cookie for any of them,
so that fact doesn't help SmartBrowz or anything else that needs a real Catalyst
Authentication session; it would take the officer completing Catalyst's own hosted
login flow, which nothing in this deployment currently drives.

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator.

## Next recommended action
1. **Build the case board** (`docs/INDUSTRY_GAP_ANALYSIS.md` §7, item 1) — the
   highest-ranked, smallest-effort item from this pass's gap analysis, and the most
   concrete answer available to "is this more than a chatbot."
2. If a QuickML endpoint URL/key or a working Catalyst hosted-login flow is ever
   obtained through the console UI directly (not the Admin API — confirmed this pass
   to have no path there), BUG-022 and BUG-018 both close for real.
3. Consider the lead-disposition feature (§7 item 2) once the case board exists — it
   is almost free once that schema is in place.
4. BUG-026 is closed; drop it from any future "open bugs" list rather than
   re-flagging it from an old copy of this file.
