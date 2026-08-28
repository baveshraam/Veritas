# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s
changelog and `docs/WORK_LOG.md`. This file answers "where do things stand right now and
what's next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`dca3739` — "docs: bring CLAUDE.md's changelog and test count current" (main,
`github.com/baveshraam/Veritas`). Feature commit below it: `ddbc4f1` ("fix: resolve
English plural markers before Kannada translation"). This handoff's own narrative
below (cross-entity investigation timeline) is now several passes old — kept as
accurate history of that specific pass, not of current HEAD. For the real pass-by-pass
record between then and now (semantic interpreter, compositional semantic layer,
QuickML activation, the general N-step planner, the cold-start fix), read
`docs/ENGINEERING_BRIEF.md`'s dated entries directly rather than trusting a summary
here — this file is a pointer, not the ledger.

## Current live deployment
- **API**: AppSail deployment `52852000000346070` (appComputeId `52852000000204688`,
  app id `50043864344`) — the Kannada plural-marker fix, relayed and live-verified
  2026-08-28 (see CLAUDE.md's v17 entry). Carries every prior pass's work.
- **Console**: unchanged this pass (backend/translation-only change); last redeployed
  during the investigation-board pass. Live at
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`.

## Date/time of last verification
2026-08-28 (final completion pass). `python -m pytest` — 602 collected, all green.
Live, against the fresh deployment above: `scripts/verify_live_deployment.py`
(36/36 adversarial conversational scenarios) and `scripts/judge_flows.py` (26/26
realistic officer sessions), both via real HTTP/SSE against production, plus a direct
parse of the raw SSE response for the exact Kannada query that surfaced this pass's
bug. Console/UI was NOT re-driven via CDP this pass (no frontend change) — the
investigation-board pass's own CDP verification stands for the UI surfaces it covers.

## What the cross-entity-timeline pass did, and why (historical — see above for current state)
Built `docs/INDUSTRY_GAP_ANALYSIS.md` §7 item 3 — cross-entity timeline correlation,
the analysis's next-ranked recommendation, explicitly named as deferred by the
investigation-board pass immediately before this one. The concrete capability: pick a
case or a person, see one chronological event list spanning their own dates, their
co-accused's arrests, their OTHER cases, and money through any account they own —
answering "was X active around the same time as Y" the way i2 Analyst's Notebook's
Timeline Chart does, which was the one concrete capability the gap analysis named
Veritas as structurally lacking.

**No new table.** Every event traces to a real column already in the record layer:
`CaseMaster.CrimeRegisteredDate`, `ArrestSurrender.ArrestSurrenderDate`,
`ChargesheetDetails.csdate`, and the TRANSFERRED_TO graph edge's own `amount`/`date`/
`txn_id` props (already written by `data/generator/graph_sync.py` from `vx_txn` — no
new query needed for the financial events).

**Backend** (`packages/rag_agent/rag_agent/timeline.py`, new):
- `case_timeline(fir_id, officer_role, officer_ps_code)` and
  `person_timeline(person_id, officer_role, officer_ps_code)` assemble events, each
  carrying `kind: "authoritative"` (a directly stated ER/vx_ fact) or `"derived"`. Only
  one thing is ever labelled derived: a person's OTHER case, linked purely by
  Fellegi-Sunter's inferred identity match (shown with its match confidence) — never
  presented as a directly stated fact.
- `connection_between(person_a_id, name_a, person_b_id, name_b)` — "why are these
  connected" — reports ONLY real graph/ER facts (a CO_ACCUSED_WITH edge, a shared
  `CaseMasterID`, a TRANSFERRED_TO edge between accounts either person owns) as a
  connection. Two events merely close in time are never reported as one — this is a
  hard rule the analysis itself named, not a nice-to-have.
- Both functions are unscoped person-wise (a resolved person is not a station-owned
  record, same precedent `/person/{id}` already set) but check `can_view_fir` per
  case, exactly like every other case-reading path.

**New REST endpoints** (`apps/api/api/routers/timeline.py`): `GET /timeline/case/{fir_id}`,
`GET /timeline/person/{person_id}` — same station-scope/masking discipline as
`/copilot` and `/board`, registered in `main.py`.

**Conversational integration** (`packages/rag_agent/rag_agent/orchestrator.py`,
`intents.py`): two new intents, `TIMELINE` and `TIMELINE_CONNECTION`, matched by
regex **shape** pre-check (like `CASE_LOCATIONS`/`EXPLAIN_REASONING` already are),
not keyword score — "what happened before this incident" would otherwise tie
`CASE_CONTEXT`'s bare "what happened" keyword, and "why are these events connected"
would otherwise score `CAUSAL`'s bare "why". Both short-circuit in `node_retrieve`
before the `NEEDS_CASE`/`NEEDS_SUBJECT` gates (own local "no subject" refusal
messages: `no_timeline_subject`, `timeline_connection_no_subjects`). Each timeline
event becomes an ordinary `EvidenceItem` (with a real `timestamp` set to the event's
own date) — so `EXPLAIN_REASONING`/`EVIDENCE_FOR` and board-pinning reuse the exact
mechanisms every other intent already has, confirmed by driving both live rather than
assumed from the architecture. `_rank_evidence` special-cases these two intents to
preserve chronological order instead of re-sorting by confidence.

**Console**: `apps/web/components/viz/TimelineView.tsx` (new) — a connecting-rail
vertical list, shared by the chat-driven `ContextView` pane (`visualization.kind ===
"timeline"`) and a new third "Timeline" tab in the `Copilot.tsx` overlay (alongside
Briefing / Investigation Board), fetching `GET /timeline/case/{fir_id}` directly. Kind
badges (`record` vs `derived`) reuse the board's own `.board-kind` visual language.
Clicking an event selects it in the Evidence rail (`timelineEvidenceId()` in `api.ts`
reconstructs the exact evidence_id client-side, deterministically, matching the
server's `_timeline_evidence` formula); a per-row Pin button reuses the existing
board-pin flow (`send({query: "Add this event to the investigation board.", ...})`)
unchanged.

## Three real defects found by a live pass, after the deploy already "worked"
Consistent with every prior pass's own finding: a green `/health` and a clean deploy
prove nothing about a conversational feature actually working. All three found by
driving the exact phrasing an officer would type, against a real local stack first,
then reproduced/fixed/reverified against the live deployment:

1. **Keyword collision** — "Add this event to the investigation board." (a natural
   phrasing of the feature's own spec examples) contains "investigation board," a
   bare `BOARD_VIEW` keyword, so it misrouted to a board summary instead of pinning.
   The exact collision class v16 already fixed for "case board"; this specific
   phrase was not yet covered. Fixed with a `_BOARD_PIN_EVENT` regex pre-check.
2. **Silent wrong-item pin** (the more serious one) — `_pin_evidence_from_context`'s
   fallback unconditionally grabbed the previous turn's TOP evidence item whenever a
   genuine `active_evidence_id` target didn't match anything in that turn's own
   pool. This was always latently possible but never actually triggerable until the
   Copilot Timeline tab (REST-fetched, so its events are never part of any chat
   turn) made a real target/pool mismatch possible for the first time. Reproduced
   live via curl: asked to pin a specific transaction event by id right after a
   different turn had shown a FIR record — the system silently pinned the unrelated
   FIR record instead, with nothing indicating a substitution had happened. Fixed
   the precedence (try every source against the actual target before EVER falling
   back to "whatever was last shown") and added a reconstruction fallback so a
   Timeline-tab event can be pinned with no priming chat turn.
3. **Pronoun-ambiguity collision** — `TIMELINE_CONNECTION`'s own pronoun ("both of
   them") was being caught by `node_orchestrate`'s pre-existing generic 2-candidate
   ambiguous-person refusal (RAG-34's own mechanism) before
   `_handle_timeline_connection` — which resolves exactly those two candidates by
   design — ever ran. Fixed by exempting `TIMELINE_CONNECTION` from that branch.

All three fixed, redeployed, and re-verified live. See
`packages/rag_agent/tests/test_timeline.py` for the regression coverage (each
confirmed against a real repro before being marked fixed).

## Verified live this pass
- **`GET /timeline/case/{fir_id}` / `GET /timeline/person/{id}`** — both local and
  production: chronological ordering, correct entity attribution, RBAC (403
  cross-station via the same `can_view_fir` every other case-reading endpoint uses),
  404 on a missing subject, name masking below DSP.
- **Chat `TIMELINE`** — "Show me the timeline for this case" → 23-event chronological
  timeline, ACCEPTs via an authoritative finding, 12 citations, correct
  `visualization.kind: "timeline"`. Identical result local and production.
- **Chat `TIMELINE_CONNECTION`** — "Show me events involving both of them" right
  after a 2-accused `CASE_PEOPLE` turn correctly resolves both people (no
  clarification needed — RAG-34's own reasoning applied one level up), finds their
  real co-accused connection (6 shared cases), renders the merged chronological
  timeline. Identical local and production (750 vs 753 events — a live/local data
  state difference, not a bug, same class already documented for other features).
- **Board pin from a chat-driven timeline event** — via the Evidence rail's own Pin
  button after clicking a `.timeline-item` row, confirmed via CDP DOM inspection of
  the resulting `.board-item-body`.
- **Board pin from the Copilot overlay's own Timeline tab, with NO prior chat turn
  at all** — the reconstruction-fallback path (defect #2 above), confirmed the same
  way. This is the harder case and the one that actually exercises the new fallback
  code path, not just the pre-existing one.
- **Real CDP against the deployed console**: case index → Copilot brief → Timeline
  tab → Pin → Investigation Board tab shows it; chat → timeline visualization →
  click event → Pin via Evidence rail. Screenshots captured for both, both local and
  live.
- **RBAC, audit chain**: unchanged, not re-broken — every existing check that
  touches the case-read path (which the timeline endpoints reuse) still passes.

## Not verified / not done this pass, stated plainly
- **Full Kannada round trip for a `TIMELINE` query through the browser.** The
  translate+classify pipeline was confirmed directly (`translation_agent.to_english()`
  → `intents.classify()` correctly returns `TIMELINE` for the Kannada phrase), but a
  live browser round trip on a freshly-started local dev process exceeded this
  session's test window — consistent with `BUG-016`'s already-documented cold-NLLB-load
  latency (~20s cold, ~13s to translate one multi-sentence answer even warm), not a
  defect this pass introduced. Not re-attempted against the already-warm live
  deployment for lack of remaining session time.
- **A dedicated "pin" click target inside `NetworkView.tsx`/`MapView.tsx`** for a
  timeline event's underlying relationship — the Evidence rail's generic Pin button
  and the Timeline view's own per-row Pin button already cover every event type,
  tested; not a functional gap, a small additive follow-up if wanted.
- **Arbitrary date-range filtering** beyond the two `before`/`after` keyword cases
  implemented (anchored on `active_evidence_id` when set, else the timeline's own
  first event) — covers the spec's own example phrasing, not a general date-range
  query language.
- **A "summarize when very large" affordance** — one real pair in the seeded dataset
  merges 750+ events (one person has 196 cases on file, an extreme hub in the
  generator's preferential-attachment scheme). Genuine data, rendered honestly and
  fully in a scrollable list; not capped, since capping would mean silently hiding
  real history with no principled cutoff. Worth revisiting if this becomes a demo
  pain point, not fixed this pass.
- **QuickML / PDF export** — unchanged, correctly BLOCKED, not re-investigated this
  pass (no new information since the prior pass's from-scratch re-check).
- **`dowhy`** — unchanged, deliberately excluded.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
BUG-015 (`dowhy`), BUG-016 (Kannada latency), BUG-018 (PDF export — HTML fallback,
honest), BUG-022 (QuickML endpoint/key — console-UI-only, no Admin API path exists),
BUG-026 (Copilot canonical/as-filed name reconciliation, P2, small and scoped) remain
open, unchanged this pass.

## Important architecture facts a new session must not re-derive
Everything in prior handoffs still holds (see `CLAUDE.md` in full). New this pass:
- **Local dev against the real sqlite dataset needs THREE env vars, not zero.** The
  repo's own `.env` sets `CATALYST_PROJECT_ID`, which makes `data.ds.backend()`
  default to `"catalyst"` even locally (it checks `CATALYST_PROJECT_ID` presence, not
  a real Catalyst context) — so a bare local `uvicorn` run raises
  `ModuleNotFoundError` on every Data Store call (`zcatalyst_sdk` genuinely isn't
  installed locally) with no other symptom. Set `VERITAS_DS_BACKEND=sqlite`
  explicitly. Also needed: `VERITAS_DEV_MODE=1` (else `issue_token` raises on the
  missing `VERITAS_JWT_SECRET`) and `VERITAS_SQLITE=<absolute path to
  data/.veritas/ds.sqlite3>` (the default is CWD-relative `.veritas/ds.sqlite3`, so
  running uvicorn from `apps/api/` silently opens a different, empty database).
- **The local `data/.veritas/ds.sqlite3` dataset predates the investigation-board
  table.** `vx_case_board_item` did not exist in it; created it locally via
  `data.schema.emit_sqlite()`'s `CREATE TABLE IF NOT EXISTS` statement for that one
  table before board-pin flows could be tested locally. Not needed on the live
  Catalyst Data Store, which already has it (provisioned in the board pass).
- **A genuine `active_evidence_id` target must never silently fall back to a
  different item than the one asked for.** See defect #2 above —
  `_pin_evidence_from_context` now tries the target against every known source
  (prior turn's evidence pool, prior turn's citations, timeline reconstruction)
  before EVER falling back to "whatever the previous turn showed," and that
  fallback now only fires when there was no target at all.
- **A new plural-subject intent must be exempted from `node_orchestrate`'s generic
  singular pronoun-ambiguity refusal**, or it can never run — that refusal assumes
  every pronoun names exactly one person and treats 2+ recent candidates as
  ambiguity to refuse on, which is exactly the opposite of what a "both of them"
  intent wants from the same 2 candidates.
- **`Get-NetTCPConnection -LocalPort N -State Listen ... | Stop-Process` (PowerShell)
  is the reliable way to free a dev port on Windows** — `pkill -f` from git-bash
  does not reliably match Windows-native python.exe process command lines.

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator. No new table this pass (timeline reads existing columns only).

## Next recommended action
1. **A cross-graph/map "pin" click target** — the one item explicitly named as not
   done by both this pass and the board pass before it. Small, additive.
2. **BUG-026** (Copilot canonical/as-filed name) — small, well-scoped, deliberately
   deferred across three passes now; pick up alongside any pass touching
   `copilot/brief.py`.
3. **Analyst correction into entity resolution**
   (`docs/INDUSTRY_GAP_ANALYSIS.md` §4 item 4) — the gap analysis's own explicitly
   deferred item, named there as touching the trust-critical identity layer directly
   and deserving a dedicated pass of its own, not a bolt-on.
4. If a QuickML endpoint URL/key or a working Catalyst hosted-login flow is ever
   obtained through the console UI directly, BUG-022 and BUG-018 both close for real
   — unchanged guidance from every prior pass.
