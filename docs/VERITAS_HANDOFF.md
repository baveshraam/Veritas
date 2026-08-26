# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/PHASE1_FAILURE_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`412839b` — "chore: remove slide deck files, rename judge-facing ambiguous doc/folder
names" (main, `github.com/baveshraam/Veritas`). Immediately below it: `35a1909`
(deploy-relay, no code) and `37cc5c6` — the actual fix commit for this pass's three
bugs. Prior HEAD this pass started from: `03be5ad`.

## Current live deployment
- API: redeployed once this pass. AppSail app `50043864344` (appComputeId
  `52852000000204688`), deployment `52852000000306055`. `/health` clean post-deploy;
  all three fixes independently re-verified live afterward (see below).
- Console: **unchanged this pass** — no `apps/web` file was touched. Still
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`.

## Date/time of last verification
2026-08-27, this session ("finalization pass"). Verified over direct HTTP/SSE calls to
the live production API (`/chat`, `/auth/token`, `/health`, the Admin API for AppSail
config and Cron), **not through the console UI** — no browser/CDP tooling (Chrome,
puppeteer, playwright) was available in this session's environment. This is a real gap
relative to prior passes, stated plainly rather than glossed over: everything reported
below as "live-verified" is API/engine-level, not console-rendering-level.

## What this pass did, and why
The prior handoff's own "19-turn golden conversation" already passes — re-running it
would prove nothing new. Per this pass's own instructions ("do not spend the session
producing another audit without implementing something"), this pass instead ran a
**fresh adversarial conversation** against the live API — natural investigator phrasing
("tell me more about this person", "what about the other person", "why did you show me
those cases", "go back to the first case", a Kannada follow-up mid-session, an
off-domain "how many gangs operate in this district?") deliberately different from the
already-passing script, specifically to find defects the golden script's exact wording
could not surface.

It found three real, live, previously-unknown bugs:

1. **A Kannada query mid-session crashed the whole turn.** A tokenizer `TypeError` from
   inside the CTranslate2 backend (`data/nlp/translate.py`) propagated past
   `translation_agent.to_english`/`to_language`'s exception handling, which only caught
   this module's own `TranslationUnavailable` — every OTHER exception type killed the
   turn with "the investigation engine failed on this query." Translation is a fluency
   layer, never load-bearing for correctness (the same rule `CLAUDE.md` already states
   for the LLM). Both functions now catch any backend exception and degrade to English
   with an honest note, exactly like every other translation failure already did.
2. **A district-scoped question with no person in it was answered as a person-ambiguity
   clarification.** "How many gangs operate in this district?" contains no PERSON
   entity, but `intents._PRONOUNS` treated bare "this"/"that" as an unresolved-person
   reference unconditionally — so with 2+ people named in the previous turn's citations
   (RAG-34's own candidate list), a district question got hijacked into "which person do
   you mean?". Root cause: "this"/"that" is ambiguous between a personal pronoun ("tell
   me about *this person*") and an ordinary determiner ("*this district*", "*this
   case*"). Fixed by excluding "this"/"that" from the pronoun match when immediately
   followed by a domain noun (district, case, FIR, record, evidence, ...) — "this
   person" still resolves as a pronoun; "this district" no longer does.
3. **"Go back to the first case" silently ran an irrelevant search instead of
   refusing.** No case-history stack exists (`SessionFocus` keeps only the case
   currently in view), so this phrasing scored a bare `CRIME_SEARCH` on the word "case"
   and ran a real semantic search over the literal text, confidently returning 5 cited
   but unrelated records — exactly the "generic vector retrieval after an unrecognized
   request" failure mode this project's own CRAG discipline exists to prevent. New
   `CASE_REFERENCE_UNSUPPORTED` intent now refuses honestly instead
   ("I do not keep an ordered history of every case opened this session...") and leaves
   whatever case was already open untouched.

All three ship with regression tests reproducing the exact live failure (7 new tests:
2 intent-classification, 2 orchestrator-level, 3 translation-agent — **369 tests
collected, all green**). Commit `37cc5c6`, deployed `52852000000306055`, and all three
fixes were re-driven against the live redeployed API afterward and confirmed working
(the Kannada case needed a second check — the first re-test hit a container that hadn't
finished rolling over post-deploy and still reproduced the crash; a retry ~2 minutes
later succeeded end to end, translating in and back out correctly).

## Verified this pass (live, over the API — see caveat above)
- **The three fixes above**, confirmed against the live redeployed API.
- **`veritas_audit_verify`'s Cron job's next unattended fire — closed.** Every prior
  pass's handoff named this as the one open item nothing but waiting could close.
  Listed the live Cron job directly (not a manual trigger): `success_count: 1,
  failure_count: 0` (`veritas_refresh`: `3, 0`) — a real unattended fire succeeded on
  its own 12h schedule with nobody watching. See `docs/QA_FUNCTIONALITY_MATRIX.md`
  DEP-13.
- **QuickML — re-confirmed BLOCKED.** Fetched the live AppSail app config directly
  (`GET .../appsail/52852000000204688`): `QUICKML_ENDPOINT_KEY` and `QUICKML_ENDPOINT`
  both absent from `configuration.environment.variables`. No code change; the
  deterministic fallback remains correct and is what answered every query this pass.
- **PDF export — re-confirmed BLOCKED.** `POST /export/pdf` against a real session with
  turns still returns `text/html` (SmartBrowz's known `INVALID_ID` failure, unchanged).
  No code change; the console's "downloaded a printable HTML copy instead" notice
  (fixed in an earlier pass) remains correct and honest.
- **RBAC boundary.** Signed in as IO (station 101), asked for a Mandya FIR (station
  2201) — refused with "No record with that number exists within your access scope,"
  no leak of the record's existence.
- **The broader investigation workflow, end to end over the API**: open case → what
  happened → who's involved → ambiguous-person clarification → pronoun follow-up →
  why-these → what-supports-that → similar cases → hotspot geography → next steps
  (Copilot leads, cross-referencing canonical/as-filed names) → briefing → open a
  second, unrelated case → attempt to return to the first by ordinal reference (now
  refuses honestly) → the still-open case answers correctly for its own accused →
  Kannada round-trip → RBAC refusal. Every step checked, not merely exercised.

## Not verified this pass, stated plainly
- **No console/UI verification** — no browser tooling in this session's environment.
  Every UI row in `docs/QA_FUNCTIONALITY_MATRIX.md` §1 verified by earlier passes' real
  CDP sessions is unchanged and was not re-driven; none of it is re-claimed as
  re-verified by this pass. The map, the graph pane, citation-thread drawing, the
  Copilot overlay, EN/KN toggle, Export PDF's button state — all last verified in the
  2026-08-26 passes, not this one.
- No new screenshots were captured this pass (same reason). The existing screenshot
  sets remain current for what they document; nothing in them is stale from this pass's
  changes, since this pass touched no frontend code.
- Voice pipeline (STT/TTS), case-status filter chips (UI-20), map pan/drag gesture,
  AML positive-case verification, `dowhy` — all unchanged from prior passes, same
  environmental/data constraints as documented there.

## Repository hygiene this pass
- Removed the two `.pptx` files and the redundant `Prototype_Deck.pdf` from the repo
  root (submission collateral, not product) — explicit user request.
- Renamed `docs/VERITAS_NORTH_STAR.md` → `docs/CAPABILITY_TARGET_AND_GAPS.md` and
  `docs/screenshots/2026-08-26-golden-19turn/` →
  `docs/screenshots/2026-08-26-full-investigation-walkthrough/`, updating every path
  reference — a judge browsing the repo tree should not need internal jargon ("North
  Star", "the golden 19-turn script") to understand what a file is. Content and
  historical changelog prose are unchanged; only names and the links pointing at them.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
BUG-015 (dowhy), BUG-016 (Kannada latency), BUG-018 (PDF export — HTML fallback,
honest), BUG-022 (QuickML key) remain open, externally blocked, re-confirmed this pass.
This pass's three fixes are not yet assigned BUG-NNN numbers (found and closed within
the same pass, same pattern several prior passes have used) — see commit `37cc5c6` for
full detail if numbers are wanted later.

## Important architecture facts a new session must not re-derive
See `CLAUDE.md` in full, and every fact listed in prior passes' handoffs (ER has no
person §0; sqlite mirror + ~23s cold-container cost; ZCQL has no bind params and no
cross-table JOINs live; `fitBounds` animation timing for CDP screenshots; intent
classification is a single label per turn). New this pass: **a redeploy does not
instantly retire every running container instance** — the first live re-check of the
Kannada fix, run ~1-2 minutes after `deployment_status: success`, still reproduced the
pre-fix crash; a second check shortly after succeeded. Give a redeploy a couple of
minutes before treating a still-failing spot-check as evidence the fix didn't take.

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator.

## Next recommended action
1. Get real browser/CDP tooling into whatever environment runs the next session, or
   have a human drive one console pass — this pass's biggest honest gap is that nothing
   about the console UI itself was re-checked, only the API/engine underneath it.
2. If a QuickML endpoint key or a working Catalyst OAuth sign-in is ever obtained, BUG-022
   and BUG-018 both close for real — both remain credential-blocked, not code-blocked.
3. Consider whether a genuine "return to a specific earlier case" capability (an actual
   small case-history stack, not just an honest refusal) is worth building — the refusal
   this pass shipped is the correct STOP-GAP for "don't fabricate a case switch," but a
   real capability would be strictly better if an investigator regularly needs it.
