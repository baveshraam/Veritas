# Veritas — Handoff

Operational pointer for the next session. Not a history — that's `CLAUDE.md`'s changelog
and `docs/WORK_LOG.md`. This file answers "where do things stand right now and what's
next," and should be updated after any meaningful pass rather than left stale.

## Current HEAD
`efc6472` — "deploy: relay a fresh signed upload URL for the live-judge-pass fixes"
(main, `github.com/baveshraam/Veritas`). Below it: `e7c3842` (fix: three live-judge-pass
defects in the investigation board), `856f581` (deploy trigger), `af3ad7a` (feat:
persistent per-case investigation board).

## Current live deployment
- **API**: AppSail deployment `52852000000333002` (appComputeId `52852000000204688`,
  app id `50043864344`). Carries the board feature plus all three live-found fixes
  (keyword collision, refusal-styling signal, board-refresh timing).
- **Console**: redeployed this pass (`scripts/deploy-console.sh`, three times — once
  for the initial board feature, once for the session-focus/board-refresh fixes, once
  for the refusal-signal fix). Live at
  `https://veritas-60077763394.development.catalystserverless.in/app/index.html`.

## Date/time of last verification
2026-08-27, this session ("Investigation workspace" pass). Both curl/HTTP and real
headless-Chrome CDP (over Node 22's global WebSocket, per
`[[veritas-console-verification]]`) were used against the live production deployment —
not a staging copy, not local. Full details in `docs/WORK_LOG.md`'s new entry.

## What this pass did, and why
Built `docs/INDUSTRY_GAP_ANALYSIS.md`'s top-ranked recommendation: a persistent
per-case investigation board (pin evidence, derived findings, people, leads with an
open/pursued/dismissed lifecycle, investigator notes, open questions) that survives a
page refresh, a new chat session, and a new officer's login — the concrete answer to
"is this more than a chatbot." Full design, schema, code, and endpoint list below.

**Schema**: `vx_case_board_item` (`data/data/schema.py`) — one table, `ItemType`
column discriminates six kinds. Provisioned live over the Admin API
(`python -m data.provision`, idempotent — ran clean against the other 37 live tables).

**Backend layering** (mirrors `copilot.brief`'s own pattern):
- `data/data/board.py` — raw row CRUD, no policy (like `data/sessions.py`).
- `packages/rag_agent/rag_agent/board.py` — the ONE policy-checked entry point
  (station-scoped via `policy.can_view_fir`; cross-case item tampering blocked by
  checking an item's `CaseMasterID` matches the URL's `fir_id` before any mutation).
  Both the REST router and the conversational orchestrator call this, never the raw
  `data.board` functions directly — the same discipline BUG-003 named for `/copilot`
  vs `/fir` (a rule enforced by one caller and not its neighbour is not a rule).
- `apps/api/api/routers/board.py` — four endpoints:
  - `GET /board/{fir_id}` — full board, grouped by type.
  - `POST /board/{fir_id}/items` — generic create, dispatches on `item_type` in the body
    (`evidence`/`person`/`lead`/`note`/`question`/`finding`).
  - `PATCH /board/{fir_id}/items/{item_id}` — status/reason/content update (lead
    lifecycle, question resolution, note edits).
  - `DELETE /board/{fir_id}/items/{item_id}` — hard delete; **rejects a lead with 400**
    (dismiss via PATCH instead — "a dismissed lead must remain auditable").
  - Every mutation calls `apps/api/api/audit.py:record()`, appending to the same
    tamper-evident hash chain every other endpoint uses.

**Conversational integration** (`packages/rag_agent/rag_agent/orchestrator.py`): six new
case-scoped intents (`BOARD_VIEW`, `BOARD_PIN_EVIDENCE`, `BOARD_PIN_PERSON`,
`BOARD_ADD_LEAD`, `BOARD_ADD_NOTE`, `BOARD_LEAD_STATUS`) join `intents.NEEDS_CASE` and
are handled in `node_retrieve` via `_handle_board_intent`, which short-circuits before
CRAG evaluation (the same pattern `CAPABILITY` already uses — a board action is a
mutation/read, not evidence retrieval, and has nothing for CRAG to score). "Pin this"
resolves the target evidence from the console's `active_evidence_id` (a new field on
`POST /chat`, sourced from `apps/web`'s existing `activeEvidence` client state) or falls
back to the previous turn's top citation, read via `_last_turn` (the same mechanism
`EXPLAIN_REASONING`/`EVIDENCE_FOR` already use). Lead status changes require an explicit
instruction (dismiss/pursue/mark) — never inferred from context.

**Console**: `apps/web/components/Board.tsx` is a new panel that joins
`Copilot.tsx`'s existing per-FIR overlay as a second tab ("Briefing" / "Investigation
Board") — one overlay, two views of the same case, reachable from the Evidence rail
("Pin to board" on every evidence card, "Open Case Board" on FIR-record cards), the case
index ("Investigation board" per card), and chat. Item kind gets a distinct visual
treatment (amber = pinned record, blue = derived finding, dashed neutral =
investigator note) so a note can never be mistaken for a database fact.

**Provisioning + deployment, done for real, not just described:**
```bash
CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python -m data.provision
# GET /appsail/get-signature -> write .github/relay-upload.url -> commit, push
#   -> relay-deploy.yml builds Dockerfile.overlay on the runner, uploads
# PUT /appsail/upsert (multipart: name, memory=2048, platform=custom_runtime,
#   configuration={"port":8000,"catalyst_auth":false,"disk":1024}, local_object_key)
#   -- NOTE: no "id" field. Including one returns a generic 400 INVALID_INPUT; the
#   endpoint upserts by "name". This cost real time this pass — see below.
# poll GET /appsail/{appComputeId}/deployment until deployment_status == success
```
`scripts/deploy-console.sh` for the client (needs the `catalyst` CLI shim on PATH —
`export PATH="$PATH:$(npm config get prefix 2>/dev/null || echo ~/AppData/Roaming/npm)"`
on Windows if `catalyst` isn't found directly).

## Three real defects found by a live judge pass, after the deploy already "worked"
The deploy succeeded and `/health` was green after the very first push — none of what
follows was caught by that. All three were found by actually typing the feature's own
example sentences into the live console and looking at the screen, not by re-reading
the code:

1. **Keyword collision** — "Pin this to the case board." (a literal spec example) also
   matched a bare `BOARD_VIEW` keyword ("case board"), so every pin answered with a
   board summary instead of pinning. `classify()`'s tie-break (earliest-registered
   intent wins) hid this until the exact phrasing was tried.
2. **Every citation-free success rendered as a refusal** — the console inferred
   "refusal" from `citations.length === 0`, which is also true of a successful board
   confirmation (a pin/note/lead has no record citation; it's the officer's own action).
   Now an explicit `answer_is_refusal` field, set once by the engine at the exact point
   a refusal is produced.
3. **Board panel reload timing** — keyed off `turns.length` (increments the instant a
   query is *sent*), not off turns that have actually *finished* — a lead saved via the
   panel's own form silently didn't appear until something else remounted the panel.

All three fixed, redeployed, and re-verified live (DOM class inspection for #2, not
just a screenshot judgment call). See `docs/WORK_LOG.md` for the full writeup and
`packages/rag_agent/tests/test_engine.py`'s new tests for the regression coverage.

## Verified live this pass
- **Full conversational workflow, real HTTP/SSE against production**: sign in → open
  case → "pin this" (resolves the top citation) → add a note → save a lead → `GET
  /board` shows all three, correctly typed. A **second, brand-new session** (fresh
  `session_id`) reopens the case and "What is on the board for this case?" correctly
  lists all 3 — the board survives the session. "Dismiss that lead" resolves "that
  lead" to the most recent open one; the lead stays on the board with
  `status: dismissed`, never deleted.
- **RBAC**: an IO gets 403 reading/writing another station's board (both direct REST
  and via a chat query naming that FIR), 401 with no token.
- **Audit**: `/jobs/audit-verify?sync=true` reports the hash chain intact after every
  mutation above.
- **DELETE on a lead**: 400, confirming the auditability guard holds at the API layer.
- **Console, via real CDP**: case-index board buttons render; the Evidence rail's "Pin
  to board" button pins the selected card; the Board tab's inline note/lead forms work
  and refresh correctly; a genuine refusal renders with `msg-a refusal` (red,
  left-bordered) while a board confirmation renders plain `msg-a`; two different cases'
  boards show completely different, correctly-scoped content (case-switch isolation).
  Screenshots in `docs/screenshots/2026-08-27-investigation-board/`.

## Not verified / not done this pass, stated plainly
- **The cross-entity timeline correlation view**
  (`docs/INDUSTRY_GAP_ANALYSIS.md` §7 item 3) — the analysis ranked the board first;
  this pass built that, not the timeline. Next recommended item, below.
- **A dedicated "pin" click target inside `NetworkView.tsx`/`MapView.tsx`/`SankeyView.tsx`**
  — pinning a relationship/hotspot/money-flow item currently goes through the Evidence
  rail's generic "Pin to board" (works for any evidence item, including
  `GRAPH_RELATIONSHIP`/`GEOSPATIAL_ANALYSIS`/financial ones) or the conversational path
  ("add this person to the investigation"), both tested. An in-visualization click
  target would be a small, purely additive follow-up, not a functional gap.
- **QuickML / PDF export** — unchanged, correctly BLOCKED, not re-investigated this pass
  (no new information since the prior pass's from-scratch re-check; see
  `docs/PHASE1_FAILURE_LOG.md` BUG-018/BUG-022 and `CLAUDE.md`'s changelog for the full
  history of why).
- **`dowhy`** — unchanged, deliberately excluded (image-size measurement in `CLAUDE.md`
  v12's changelog).
- Voice pipeline, case-status filter chips, map pan/drag — unchanged from all prior
  passes, same environmental constraints documented there.

## Open bugs (see `docs/PHASE1_FAILURE_LOG.md` for full detail)
BUG-015 (`dowhy`), BUG-016 (Kannada latency), BUG-018 (PDF export — HTML fallback,
honest), BUG-022 (QuickML endpoint/key — console-UI-only, no Admin API path exists),
BUG-026 (Copilot canonical/as-filed name reconciliation, P2, small and scoped) remain
open, unchanged this pass.

## Important architecture facts a new session must not re-derive
Everything in prior handoffs still holds (see `CLAUDE.md` in full). New this pass:
- **`appsail/upsert` takes no `id`/`app_id` field.** It upserts by `name`. Passing an
  `id` (either the app id `50043864344` or the appComputeId `52852000000204688`)
  returns a generic `{"error_code":"INVALID_INPUT","message":"either the request body
  or parameters is in wrong format"}` with no field-level detail — cost real time this
  pass before checking the exact documented recipe in `CONTEXT.md` and the
  `catalyst-deploy-pipeline` memory, both of which had always omitted `id`. Trust those
  recipes literally; do not add fields that seem obviously necessary.
- **The `catalyst` CLI shim is not on this shell's default `PATH`** — it lives at
  `<npm prefix>/catalyst(.cmd/.ps1)` (Windows: `%APPDATA%\npm`). `node
  scripts/catalyst-token.js` does not need it (it resolves the global install path
  itself via `npm root -g`); `scripts/deploy-console.sh`'s `catalyst deploy --only
  client` call does.
- **A citation-free `/chat` answer is not necessarily a refusal.** Any new intent that
  produces a real, successful answer with zero citations (a board confirmation, a
  capability description) must set `state.answer_is_refusal = False` explicitly (or
  simply not touch it — it defaults False) rather than relying on the frontend to infer
  correctly from citation count, which it can no longer do (and should not have been
  doing in the first place).
- **A new multi-word intent keyword must be checked against every other intent's
  keyword list for substring collisions before shipping** —
  `test_no_intents_keyword_is_a_substring_of_another_intents_keyword_unless_expected`
  in `packages/rag_agent/tests/test_engine.py` now guards this automatically; a failure
  there means a new collision was introduced, not that the test needs updating (unless
  the collision is genuinely intentional, in which case add it to the `_KNOWN` set with
  a comment explaining why, matching the four pre-existing ones already there).

## Data-generation constraints
Unchanged — do not regenerate the live 10k-case dataset casually. Nothing this pass
touched the generator. The one new table (`vx_case_board_item`) is investigator-authored
state, not generated data, and starts empty on every fresh dataset build.

## Next recommended action
1. **Cross-entity timeline correlation** (`docs/INDUSTRY_GAP_ANALYSIS.md` §7 item 3) —
   the analysis's next-ranked item, independent of the board and buildable on the
   per-case dates/districts already in the record layer. No new table needed.
2. **Lead disposition already exists** (it was §7 item 2, "almost free once the board
   schema is in place") — it shipped as part of this pass (`open`/`pursued`/`dismissed`
   with a reason field), not a separate future step.
3. If a QuickML endpoint URL/key or a working Catalyst hosted-login flow is ever
   obtained through the console UI directly, BUG-022 and BUG-018 both close for real —
   unchanged guidance from every prior pass.
4. BUG-026 (Copilot canonical/as-filed name) remains a small, well-scoped, deliberately
   deferred fix — pick it up alongside any other pass touching `copilot/brief.py`.
