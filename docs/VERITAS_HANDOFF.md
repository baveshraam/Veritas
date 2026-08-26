# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`23fffc1` — "deploy: relay BUG-028 fix (PERSON_HISTORY crime type/status)"
(main, pushed to `github.com/baveshraam/Veritas`)

## Current live deployment
- API: AppSail app `50043864344` (appComputeId `52852000000204688`), redeployed
  2026-08-26 carrying commit `152c313` (BUG-028 fix) — the most recent of three API
  deploys this pass (audit-verify fix, then this). `docs/VERITAS_STATUS.html`'s cited
  deployment id (`52852000000316042`, against commit `5022c46`) is now stale; that file
  is flagged as such at its own top rather than rewritten in full.
- Console: `https://veritas-60077763394.development.catalystserverless.in/app/index.html`
  — redeployed this pass, bundle-grepped live for the new export-honesty string
  (`page-69a5dfde3ec8de99.js` contains "PDF renderer unavailable on this deployment").

## Date/time of last verification
2026-08-26, this session (North Star hardening pass). Live health, `/chat`, `/alerts`,
`/export/pdf`, Cron config, and a real CDP-driven console session were all exercised
directly against the deployed system, not inferred.

## Current North-Star status
All 6 phases (`docs/IMPLEMENTATION_STRATEGY.md`) remain **done, live-verified** as of the
prior pass, re-confirmed where touched this pass. This pass was a **hardening pass**, not
a new phase: closed the one Cron job that was still failing unattended after BUG-025,
closed two nice-to-have gaps (identity-answer-key persistence, PDF-export UI honesty),
and substantially expanded live UI verification via a real headless-Chrome/CDP session
(see `docs/QA_FUNCTIONALITY_MATRIX.md` for exactly which rows moved).

## Current objective
North Star hardening — see the mega-prompt this pass ran against (23 sections: re-audit,
close solvable gaps, industry-baseline comparison, update ledgers). Not a new feature
push. The next session should read this file + `docs/QA_FUNCTIONALITY_MATRIX.md`'s "What
this matrix does NOT yet cover" section before deciding what to do next.

## Verified this pass (live, not assumed)
- `/health`, `/auth/officers`, `/auth/token`, `/chat` (FIR_LOOKUP), `/alerts` (SSE,
  auth-gated, real explainable payloads), `/export/pdf` (HTML fallback content + headers).
- Cron: `veritas_refresh` has a real unattended success (0→1) since BUG-025's fix.
  `veritas_audit_verify` did NOT (0/20→0/21) — root-caused and fixed this pass (BUG-027).
- Full console session via headless Chrome + CDP (`?as=IG`/`?as=DSP`): login, chat send,
  citation chip click, evidence-thread line draw, reasoning-trace expand, Copilot overlay
  (timeline/leads/similar-cases/diary), Copy-to-clipboard, case-explorer search + filter
  chips, "Ask about this case" per card, EN/KN toggle, Export PDF both disabled/enabled
  states. See `docs/QA_FUNCTIONALITY_MATRIX.md` for the row-by-row detail; screenshots
  and page-text dumps are in the session's scratchpad, not committed to the repo.

## Partial capabilities
- PDF export (`BUG-018`) — genuinely unavailable on this deployment: SmartBrowz needs a
  real interactive Catalyst Authentication sign-in this environment cannot drive
  (`INVALID_ID`/"No such User"), and the local fallback has no Chromium binary in the
  container either (`no Chromium-family browser found on this host`). The HTML fallback
  is real and usable (verified: proper conversation record with citations, officer
  attribution); the console now says so instead of silently substituting formats.
- QuickML LLM fluency (`BUG-022`) — `QUICKML_ENDPOINT_KEY` confirmed **not set** on the
  live AppSail app (checked the actual configuration this pass); every answer is still
  the deterministic extractive path, correctly reported as such by `/health`.
- Identity F1 (0.989 claim) — recomputability gap closed (`data/generator/score_identity.py`
  + persisted answer key), but not yet exercised against the live 10k-case dataset,
  which predates this pass's fix.
- AML detectors (`ML-09`/`ML-10`) — reachability verified in a prior pass; a real positive
  example was not found this pass either (see Unknown below).

## Unknown capabilities
- AML detector true-positive behavior against the live dataset's actual injected patterns
  — a local `.veritas/aml_labels.json` exists but its TxnID range didn't confidently map
  to the live dataset, and a direct admin ZCQL query attempt failed
  (`INVALID_URL_PATTERN`) without a documented endpoint shape to retry against.
- Voice pipeline (ASR/TTS) — no audio hardware in any session that has worked on this
  repo. Environmental constraint, not a code gap.
- Map pan/drag interaction specifically (the render itself, the pane switcher, and
  hotspot clustering are now all screenshotted and VERIFIED this pass — see
  `docs/QA_FUNCTIONALITY_MATRIX.md` UI-23/UI-24).
- Cron's *next* unattended fire for `veritas_audit_verify` (up to 12h out) — the fix is
  deployed and unit-tested, but only a real scheduled fire proves success_count moves.

## External/platform blockers (unchanged, re-confirmed)
- PDF export needs a Catalyst User Management identity via interactive OAuth — no browser
  automation reaches Catalyst's login redirect from any environment this project has used.
- QuickML needs `X-QUICKML-ENDPOINT-KEY`, obtainable only from the QuickML console's
  per-model "API Details" popup — not reachable over the Admin API.
- `dowhy` (causal layer) stays out of the deployed image — measured at ≈405MB against a
  ≈420MB headroom to the ~1.3GB bundle-sandbox ceiling; a real, measured "no," not
  unexamined.
- Stratus bucket creation is scope-blocked (`OAUTH_SCOPE_MISMATCH`, console-only) — the
  sqlite mirror + File Store already substitute for this; not a live blocker.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
27 tracked (3 P0, 16 P1, 7 P2, 1 P3). Genuinely open: BUG-015 (dowhy, platform-budget),
BUG-016 (Kannada long-answer latency, inherent CPU cost), BUG-022 (QuickML endpoint key),
BUG-026 (Copilot leads name mismatch, new this pass, not fixed by design/scope choice).
Everything else tracked is FIXED and live-verified.

## Recently completed work (this pass)
1. **BUG-028 (P0, the most consequential fix this pass)** — "Does X have priors?" had
   been silently answering "crime type not recorded" for every case, in production, for
   the flagship identity-resolution capability CLAUDE.md §0 names. Fixed and live-verified
   (`152c313`, deployed `52852000000204688`).
2. **BUG-027** — `/jobs/audit-verify` no longer blocks Cron on a cold container
   (`d5f0798`, deployed `52852000000316042`).
3. **Identity answer-key persistence** — `run.py` + new `score_identity.py`
   (`1fb0bdc`), closing `DATA_GENERATION_AUDIT.md` §19's minor gap.
4. **Export-PDF UI honesty** — the console now tells the officer when "Export PDF"
   silently degraded to HTML (`21b2bd9`, console redeployed).
5. **BUG-026 found and documented** — a real identity-display gap in the Copilot leads
   section, via live CDP verification (not fixed — a scope decision, see the bug entry).
6. Substantially expanded live UI verification (10+ previously PARTIAL/UNKNOWN rows
   moved to VERIFIED) via a real headless-Chrome/CDP session — see
   `docs/QA_FUNCTIONALITY_MATRIX.md`.
7. `/alerts` (SSE) and its Isolation Forest backend re-confirmed live and reachable —
   the v12 changelog's claim was previously untested this deeply; now it is.

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full — it is the single source of truth. The facts most likely to
matter immediately: the ER has no person (identity is inferred, §0); Data Store reads run
off a sqlite mirror hydrated once per container, and the FIRST such query on a cold
container costs ~23s (BUG-001) — **any new `/jobs/*` endpoint must kick real work to a
background thread and return immediately, or it will fail every unattended Cron fire
exactly like BUG-027 did**; ZCQL has no bind parameters and no JOINs between
value-related tables live; the deployed image is code + CPU wheels only, weights stream
from File Store at cold start.

## Known regressions / traps that must not return
- **Don't feed a query built for one join budget into a row-shape parser built for
  another** (BUG-028) — `_case()` expects `_CASE_SELECT`'s fully-joined columns
  (`CrimeHeadName`/`CaseStatusName`/`DistrictName`/`UnitName`/`BriefFacts`); any query
  reaching `CaseMaster` through 3+ of its own joins (e.g. via `vx_accused_identity`) has
  no join budget left to also resolve those names and must fetch ids first, then a
  second `_CASE_SELECT ... WHERE CaseMasterID IN (...)` call, never one query trying to
  do both. If a new caller feeds `_case()` rows from a query you didn't write yourself,
  check what columns that query actually selects before trusting the output.
- Don't gate a background warm-up thread behind an unrelated env var (BUG-001's original
  cause) — verify with a fresh `VERITAS_RESTART_NONCE` bump if touching startup code.
- Don't let a new evaluator/floor change silently drop an authoritative low-confidence
  item (BUG-006/BUG-020's regression pair) — re-run the CAUSAL and FINANCIAL-empty-trail
  regression tests after any evaluator change.
- Don't add a new `/jobs/*` endpoint that does real Data Store work synchronously before
  responding (BUG-024, BUG-027) — background thread + immediate response, always.
- Don't collapse `vx_graph_edge`'s legitimate multi-edges (the 2026 audit already caught
  this once — see the failure log's closing note).

## Data-generation constraints
Do not regenerate the live 10k-case dataset casually — see `CLAUDE.md` §20 and this
pass's own explicit decision not to regenerate merely to backfill the identity answer key
for a P2 gap. If a data problem is found, diagnose generator-vs-dataset-vs-model-vs-
retrieval-vs-presentation *before* touching anything, per the established discipline.

## Acceptance criteria for the current objective
Per the mega-prompt's own §23 stop condition: every North-Star weakness investigated,
technically-solvable gaps fixed, important paths live-verified, remaining limitations
explicitly classified (VERIFIED/PARTIAL/UNKNOWN/BLOCKED/BROKEN/OUT-OF-SCOPE), industry
gaps identified, ledgers updated. This pass materially advanced all of these; it did not
close every remaining UNKNOWN (AML positive case, voice, map render, viz-pane-switcher) —
those are named above and in the QA matrix precisely so the next pass doesn't have to
re-derive the list.

## Last verification evidence
See `docs/PHASE1_FAILURE_LOG.md` BUG-027 and `docs/QA_FUNCTIONALITY_MATRIX.md`'s updated
rows for exact commands, response bodies, and CDP screenshots' content (text dumps
described inline; the PNGs themselves live in this session's scratchpad, not the repo).

## Next recommended action
1. Confirm `veritas_audit_verify`'s Cron `success_count` actually increments on its next
   unattended fire (check any time after ~12h from this deploy) — the one thing this pass
   could not observe directly.
2. Decide on BUG-026 (Copilot leads name mismatch) — small, well-scoped fix, left open
   deliberately.
3. If someone obtains a real QuickML endpoint key or completes an interactive Catalyst
   OAuth sign-in once (even manually, outside this tooling), BUG-022 and BUG-018 could
   both close for real — both are "waiting on a credential," not "waiting on more code."
4. Pursue the AML positive-detection verification with a proper live database
   introspection path (find the correct ZCQL admin REST endpoint shape, or run a
   `/jobs/*`-style diagnostic endpoint) rather than guessing further at REST paths.
