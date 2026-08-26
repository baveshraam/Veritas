# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`d865293` — "deploy: relay the 'previous cases' keyword fix"
(main, pushed to `github.com/baveshraam/Veritas`)

Prior HEAD this pass started from: `23fffc1` (BUG-028 fix, prior session).

## Current live deployment
- API: AppSail app `50043864344` (appComputeId `52852000000204688`), deployment
  `52852000000318035`, redeployed 2026-08-26 carrying commit `cc46f75` — the third
  and last of three API deploys this pass (conversational architecture → NER fix →
  keyword fix), each live-verified before moving to the next.
- Console: unchanged this pass — **no frontend deploy needed**. Every capability added
  this pass is reachable through the existing chat pane; nothing in `apps/web/` changed.
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`

## Date/time of last verification
2026-08-26, this session (conversational-architecture pass). A single live session was
driven through a real 14-turn investigation — open FIR → case context → accused →
priors → associates → why-these → similar cases → their geography → financial trail →
what-supports-that → next steps → briefing — both over curl/SSE and through the real
console via a headless-Chrome/CDP session (8 screenshots, committed to
`docs/screenshots/2026-08-26-conversational-architecture/`, not just the scratchpad).

## Current North-Star status
Unchanged from the prior pass's own re-confirmation: all 6 phases
(`docs/IMPLEMENTATION_STRATEGY.md`) remain done, live-verified. This pass was **not**
a North-Star gap-closing pass — it answered a different, more foundational question a
separate mega-prompt raised: *how much of the conversational layer is genuinely
conversational, versus intent classification plus isolated deterministic tools?*
The honest answer going in was "mostly the latter, for anything beyond a single named
subject" — `SessionFocus` (active_person/active_fir/active_location) existed and
persisted across turns, but nothing let a follow-up talk ABOUT the open case itself or
ABOUT the previous answer, and one real bug (see below) undercut the persistence
mechanism for the single most obvious follow-up in the whole system.

## Current objective
Conversational architecture — see the mega-prompt this pass ran against (build
explicit case-scoped and meta-question conversational state, reuse existing correct
subsystems rather than duplicating them, keep RBAC enforced across turns, live-verify
through the real deployment). The next session should read this file +
`docs/QA_FUNCTIONALITY_MATRIX.md` §3 (RAG-24–33) + its "What this matrix does NOT yet
cover" section before deciding what to do next. The North Star document
(`docs/VERITAS_NORTH_STAR.md`) and its P0/P1 gap list were NOT re-audited this pass —
still current as of 2026-08-26's earlier hardening pass.

## Verified this pass (live, not assumed)
- **The persisted-focus bug, and its fix, live**: opened FIR 100222201202600022 (curl
  `/chat`), then one turn later asked "What happened?" in a NEW request — before the fix
  this would have found no case ever opened (the resolution from `FIR_LOOKUP` was never
  persisted); after the fix it correctly answers about the same case.
- A real 14-turn investigation in ONE session, both over curl/SSE and through the actual
  console via CDP: FIR_LOOKUP → CASE_CONTEXT → CASE_PEOPLE (network view, real
  PageRank-sized nodes) → named-person PERSON_HISTORY → PERSON_NETWORK → EXPLAIN_REASONING
  → case-scoped SIMILAR_CASES (structured explanation) → CASE_LOCATIONS (map view) →
  FINANCIAL (honest negative finding) → EVIDENCE_FOR → NEXT_STEPS (Copilot leads) →
  BRIEFING (Copilot draft). See `docs/QA_FUNCTIONALITY_MATRIX.md` RAG-24–33 and the 8
  screenshots in `docs/screenshots/2026-08-26-conversational-architecture/`.
- Authorization boundary: an IO officer (station-scoped) asking about a FIR at a
  different station correctly refuses at `FIR_LOOKUP` (`exact_lookup_missed`, because the
  scoped query itself finds nothing), and the follow-up "What happened?" then correctly
  refuses `no_case` rather than leaking anything — no case was ever legitimately opened
  in that session. The SAME IO, on a case within their own station, gets full
  `CASE_CONTEXT`/`CASE_PEOPLE` answers and correct pronoun resolution ("Does he have
  priors?" against a single auto-resolved accused).
- Kannada round-trip on a NEW intent: `ಏನಾಯಿತು?` ("What happened?") correctly translated,
  classified as `CASE_CONTEXT` against the session's `active_fir`, answered, and
  translated back — the new intents inherit Kannada support for free because
  `node_translate_in` runs before intent classification, not because anything
  Kannada-specific was added.
- A real, previously-live wrong-answer bug found and fixed: "Tell me more about Usha
  Naika" resolved to a DIFFERENT "Usha" (25 records, the most prolific one) and answered
  about her at full confidence — `data/data/nlp/entities.py`'s PERSON-span logic clipped
  "Naika" off "Usha" because the surname isn't in the 271-name gazetteer sample. Fixed;
  the same query now resolves to the right person.
- A real routing gap found live: "What previous cases involve her?" (plural) matched no
  `PERSON_HISTORY` keyword and fell to a generic global count. Fixed.
- `/health` re-checked directly: QuickML still `configured, not yet contacted` — the
  `QUICKML_ENDPOINT` is baked into the running container from a prior pass's manual patch,
  but `QUICKML_ENDPOINT_KEY` is confirmed still absent from the live AppSail configuration
  (fetched the full `configuration.environment.variables` object directly). Unchanged,
  correctly BLOCKED — see below.

## Partial capabilities
- **RAG-32 (ambiguous-name clarification)** — the tie-break logic (two people matching a
  searched name with an equal `record_count`, no clear leader) has direct unit coverage
  and is deployed, but no live query this pass happened to hit a genuine tie in the
  10k-case dataset — every name tried ("Usha", "Ramesh") had a clear leader. Worth trying
  a few more common first names next pass, or constructing one deliberately.
- **RAG-29 (`BRIEFING`)** — live-verified only against a single-accused case. The
  multi-accused draft-summary/leads combination is unit-tested (`test_briefing_uses_...`)
  but not independently live-driven this pass.
- PDF export (`BUG-018`) — unchanged, still genuinely unavailable on this deployment (not
  touched this pass; see the prior hardening pass's own entry for the SmartBrowz detail).
- Identity F1 (0.989 claim) — unchanged from the prior pass; still not exercised against
  the live dataset (would require regenerating it, which this project's own rules say not
  to do casually).
- AML detectors (`ML-09`/`ML-10`) — unchanged, not touched this pass.

## Unknown capabilities
- Unchanged from the prior pass (AML positive-case detection, voice pipeline hardware,
  Cron's next unattended `veritas_audit_verify` fire) — none of these were in this pass's
  scope. See the prior pass's entries below this file's git history, or
  `docs/QA_FUNCTIONALITY_MATRIX.md`'s own "does NOT yet cover" section.
- A genuine live ambiguous-name tie (RAG-32, above).

## External/platform blockers (unchanged, re-confirmed this pass)
- QuickML needs `X-QUICKML-ENDPOINT-KEY`, obtainable only from the QuickML console's
  per-model "API Details" popup — not reachable over the Admin API. Re-checked directly
  this pass (fetched the live `appsail` configuration object) rather than trusted from a
  prior doc: still absent.
- PDF export needs a Catalyst User Management identity via interactive OAuth — unchanged,
  not re-checked this pass (no code in this area was touched).
- `dowhy` (causal layer) stays out of the deployed image — unchanged, not re-checked.
- Stratus bucket creation is scope-blocked (`OAUTH_SCOPE_MISMATCH`, console-only) — the
  sqlite mirror + File Store already substitute for this; not a live blocker.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
Unchanged tracked-bug count from the prior pass (this pass's three fixes — the
focus-persistence gap, the NER surname-clipping bug, and the `previous cases` keyword
gap — were found AND fixed live in the same pass, so none were logged as standing open
bugs; each is described in its own commit and in `docs/QA_FUNCTIONALITY_MATRIX.md`
RAG-24–33 instead). BUG-015 (dowhy), BUG-016 (Kannada latency), BUG-022 (QuickML key),
BUG-026 (Copilot leads name mismatch) remain open, untouched this pass.

## Recently completed work (this pass)
1. **Eight new conversational intents, all gated on real session state** —
   `CASE_CONTEXT`, `CASE_PEOPLE`, a case-scoped branch of `SIMILAR_CASES`, `NEXT_STEPS`,
   `BRIEFING` (all gated on `SessionFocus.active_fir` via new `intents.NEEDS_CASE`), plus
   `EXPLAIN_REASONING`/`EVIDENCE_FOR` (read the previous stored turn) and
   `CASE_LOCATIONS` (tallies districts over the previous turn's cited FIRs). `NEXT_STEPS`/
   `BRIEFING`/case-scoped `SIMILAR_CASES` reuse the EXISTING Investigation Copilot logic
   (`copilot.brief.leads_for_case`/`similar_cases_for`/`generate_copilot_brief`, promoted
   from private helpers) rather than duplicating it — the capability already existed
   correctly behind `/copilot`, it just wasn't reachable from `/chat`.
   (`2e1da7d`, deployed `52852000000317055`)
2. **Ambiguous person names now ask instead of guessing** — a searched name with two
   equally-ranked matches (tied `record_count`, no clear leader) refuses with the
   candidate names named, rather than silently picking the first. `state.py` gained a
   transient `ambiguous_candidates` field for this (not persisted — it's a same-turn
   clarification, not session state).
3. **Fixed a real, previously-live persistence bug**: `node_orchestrate` persists
   `SessionFocus` BEFORE retrieval runs, but `FIR_LOOKUP` (and now `CASE_PEOPLE`) resolve
   `active_fir`/`active_person` DURING retrieval — that resolution was never saved.
   "Open FIR X" followed one turn later by "What happened?" forgot X was ever opened.
   `node_retrieve` now persists again after resolving. This was the single highest-value
   fix in the pass — without it, none of the case-scoped follow-ups above could ever
   fire on turn 2 of a real conversation.
4. **Fixed a real, previously-live wrong-answer bug in NER** (`data/data/nlp/entities.py`)
   — a capitalised surname not in the 271-name gazetteer sample was clipped off an
   adjacent known first name ("Usha Naika" → "Usha"), silently resolving to a DIFFERENT
   person and answering about them at full confidence. Found live while verifying the
   new conversational flow, not anticipated going in. (`d26f3fd`, deployed
   `52852000000325022`)
5. **Fixed a routing gap**: `PERSON_HISTORY`'s keyword list had "previous case" but not
   "previous cases" — a plural follow-up fell to a generic global count. (`cc46f75`,
   deployed `52852000000318035`)
6. **Every case-scoped branch re-validates station scope on every use**, via the same
   scoped `fir_by_id()` query `FIR_LOOKUP` already uses — not trusted from whenever
   `active_fir` was first set. Live-tested: an IO's cross-station refusal holds across
   both the FIR lookup AND the follow-up.
7. **QuickML re-checked, not re-guessed**: fetched the live AppSail `configuration`
   object directly this pass rather than trusting the prior pass's own note — confirmed
   `QUICKML_ENDPOINT_KEY` is still absent. No code change; the honest BLOCKED status
   (`llm.status()`) already distinguishes "configured, not yet contacted" from
   "deterministic (LLM degraded: ...)" from "deterministic (QuickML not configured)"
   from a real `quickml (model)` success, which is what the mega-prompt this pass ran
   against asked health/status reporting to do — already true before this pass, verified
   still true after it.
8. **Live screenshots committed to the repo, not left in a scratchpad** — first time
   this project has done so; see `docs/screenshots/2026-08-26-conversational-architecture/`.

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full — it is the single source of truth. In addition to the facts the
prior pass already listed here (ER has no person §0; sqlite mirror + ~23s cold-container
cost, BUG-001; ZCQL has no bind params and no cross-table JOINs live; image is code + CPU
wheels, weights stream from File Store): **`node_orchestrate` persists `SessionFocus`
before retrieval runs; anything retrieval itself resolves into `active_fir`/
`active_person` (FIR_LOOKUP, CASE_PEOPLE) must be persisted AGAIN at the end of
`node_retrieve`, or it never survives to the next turn** — this is exactly the bug this
pass found and fixed, and a new specialist branch that mutates `state.active_entities`
without relying on that existing re-persist call would silently reintroduce it. Also:
**the LLM is never used for conversation memory** — `EXPLAIN_REASONING`/`EVIDENCE_FOR`
read `vx_conversation_turn`'s stored citations/trace directly and re-describe them
deterministically; no chat history is ever concatenated into a prompt, by design, per
this pass's own mega-prompt ("do not simply concatenate the entire chat history into
every prompt").

## Known regressions / traps that must not return
- (Prior-pass traps, still current — see `CLAUDE.md`'s own listing: the `_case()`/
  `_CASE_SELECT` join-budget trap from BUG-028, the `VERITAS_RESTART_NONCE` warm-up-thread
  trap from BUG-001, the CAUSAL/FINANCIAL authoritative-evidence regression pair from
  BUG-006/BUG-020, the `/jobs/*` synchronous-work trap from BUG-024/BUG-027, and the
  `vx_graph_edge` multi-edge collapse trap.)
- **New this pass**: don't add a new case-scoped conversational branch that reads
  `state.active_entities.active_fir` without FIRST re-fetching it through a scoped query
  (`sql_agent.fir_by_id(fir_id, role, ps)` or equivalent) and checking the result is
  non-empty. `active_fir` being SET is not itself a permission — it must be re-proven on
  every use, because a session_id is the only thing binding it to an officer, and nothing
  stops a session_id being reused. Every one of `CASE_CONTEXT`/`CASE_PEOPLE`/
  `SIMILAR_CASES`/`NEXT_STEPS` does this; `BRIEFING` does the equivalent via
  `generate_copilot_brief`'s own internal `can_view_fir` check. A new branch that skips
  this re-check would be a real authorization bypass, not a style nit.
- **New this pass**: don't add a new intent whose keyword phrase shares a common word
  ("why", "where") with an existing topic intent (CAUSAL, HOTSPOT) via the normal
  keyword-scoring path — it will either lose the tie or win it wrongly depending on dict
  order. `EXPLAIN_REASONING`/`EVIDENCE_FOR`/`CASE_LOCATIONS` are matched by a dedicated
  regex checked BEFORE keyword scoring (same pattern as `CAPABILITY`/`NOT_INFERABLE`) for
  exactly this reason — see `intents.py`'s own comment on this.

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator or required regeneration (the NER fix is a query-time entity
extraction fix, not a data fix — the underlying `ka_names.csv` gazetteer sample and the
generated names in the dataset are both unchanged and correct as-is).

## Acceptance criteria for the current objective
Per the mega-prompt's own stop condition: the conversational architecture materially
improved (not just described), and the live system demonstrates a coherent multi-turn
investigation rather than isolated query handling. Met — see "Verified this pass" above
for the live 14-turn session, both over curl and through the real console. QuickML
remains platform-blocked, documented as such, not faked. Not done this pass, by the
mega-prompt's own explicit stop condition: no differentiator features, no North-Star
gap-closing beyond what this pass's own live verification happened to surface (the NER
and keyword bugs) — the North Star P0/P1 list from the prior pass is untouched and still
the next big-ticket item after this one.

## Last verification evidence
See `docs/QA_FUNCTIONALITY_MATRIX.md` RAG-24–33 for exact intents/traces/citations, and
`docs/screenshots/2026-08-26-conversational-architecture/` for the 8 live console
screenshots (committed to the repo this pass, not left in a scratchpad).

## Next recommended action
1. Find or construct a genuine live ambiguous-name tie to close RAG-32's live-verification
   gap (unit-tested, not yet observed live).
2. Live-drive `BRIEFING` against a multi-accused case (RAG-29's remaining gap).
3. Return to `docs/VERITAS_NORTH_STAR.md`'s Part 3 P0/P1 list — this pass did not touch it;
   P0-1/P0-2 (narrative diversity + its missing regression test) are still the largest
   named gaps in the whole project.
4. If someone obtains a real QuickML endpoint key or completes an interactive Catalyst
   OAuth sign-in once (even manually, outside this tooling), BUG-022 and BUG-018 could
   both close for real — both are "waiting on a credential," not "waiting on more code."
5. Consider whether `CASE_PEOPLE`'s "several accused, ask by naming them" behaviour should
   ALSO let a bare pronoun follow-up ("tell me about this person") disambiguate against
   the specific candidates the previous turn named, rather than only against an explicitly
   typed name — deliberately not built this pass (the existing `no_subject` refusal already
   asks the officer to name someone, which every live test this pass satisfied by doing
   exactly that) but worth revisiting if it proves to be a real friction point in use.
   introspection path (find the correct ZCQL admin REST endpoint shape, or run a
   `/jobs/*`-style diagnostic endpoint) rather than guessing further at REST paths.
