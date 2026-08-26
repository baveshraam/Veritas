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
surface. `docs/VERITAS_NORTH_STAR.md`'s prioritized gap list is untouched.
