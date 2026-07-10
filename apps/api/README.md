# Backend Platform (`apps/api/`)

**What this is**: the one deployable backend service. Terminates auth, enforces who-sees-what, streams the chat/reasoning-trace to the frontend, writes the audit trail, and hosts (imports) `packages/rag_agent` and `packages/ml_models` — it contains no reasoning or ML logic itself.

Single FastAPI service (Layer 7 of root [`CLAUDE.md`](../../CLAUDE.md)) — async, Pydantic v2.

## Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/chat` | `POST`, SSE response | Body: `{session_id, officer_id, officer_role, language, query}` **or** `{..., audio: <base64>}` instead of `query`. Streams trace + final events (exact envelope below). |
| `/fir/{fir_id}` | `GET` | Full FIR record, policy-filtered by role. |
| `/person/{person_id}` | `GET` | Person record; victim identity masked below DSP rank. |
| `/copilot/{fir_id}` | `GET` | Investigation Copilot brief (timeline, similar cases, leads, draft summary). |
| `/export/pdf` | `POST` | Body: `{session_id}`. Returns a PDF (Puppeteer render of the full conversation history + charts, KSP letterhead). |
| `/alerts` | `WebSocket` | Pushes Isolation Forest anomaly alerts live. |

Every route calls into `packages/rag_agent` (`run_investigation` for `/chat`, `generate_copilot_brief` for `/copilot`) or `packages/ml_models` (`check_anomalies` for `/alerts` only) — this file does auth, policy filtering, response shaping, and persistence. It contains no reasoning, retrieval, or ML logic.

### `/chat` SSE envelope (canonical — `apps/web` and `packages/rag_agent` both build against this exact shape)

```
{ type: "trace",  step, detail, duration_ms, confidence }              # one per AgentTraceEntry, as it's appended
{ type: "final",  final_answer, citations, evidence_items, visualization }
  # citations: Citation[] (1-based index — matches the [1] FIR/... render convention)
  # evidence_items: EvidenceItem[]           — full content, powers the evidence-rail drawer
  # visualization: VisualizationPayload      — { kind, data }, drives the center context-view
{ type: "audio",  data: <base64> }           # only sent if the request had respond_with_voice=true
```

Field-level shapes (`Citation`, `EvidenceItem`, `VisualizationPayload`) are defined once, canonically, in `packages/rag_agent/README.md` — don't redefine them here or in `apps/web`.

### How a turn is built (request → response)

1. Verify JWT, extract `officer_id`/`officer_role`.
2. If `audio` present: decode, pass as `input_audio` bytes; else pass `query` as `original_query`.
3. `focus = data.get_session_focus(session_id)` — rehydrate **only** `SessionFocus`; every other `InvestigationState` field starts fresh this turn (evidence/results are per-turn, not session-level — see `packages/rag_agent/README.md`).
4. Call `run_investigation(state)`, streaming `agent_trace` entries out as `type: "trace"` as soon as each is appended.
5. On completion: stream the `type: "final"` event (and `type: "audio"` if requested), then `data.write_conversation_turn(...)` and `data.write_audit(...)` — both, for their distinct purposes (see `data/README.md`).

## Auth
JWT with a `role` claim: `IO, SHO, DSP, SP, IG, SCRB_Analyst`. Verified in middleware before any handler runs.

## Policy — lives in `packages/policy`, not here (see below)
- IO sees only FIRs filed at their own PS.
- Victim identity is masked below DSP rank.
- Graph traversal depth is capped by role (e.g. IO can't run unbounded multi-hop financial traversals; DSP+ can).

**Two enforcement points, one rule set.** Field-masking on *structured* responses (`/fir/{id}`, `/person/{id}`) can be applied post-hoc, so it runs here, as FastAPI middleware, on every response before it leaves the handler. But depth-capping and content-masking on the free-text `/chat` answer **cannot** be enforced after the fact — you can't un-traverse a graph or reliably redact a name out of generated prose. So the same rules also run *inside* `packages/rag_agent`'s Cypher/SQL Agents, at query-construction time, before anything is retrieved.

To avoid duplicating (and inevitably drifting) the rule definitions, they live in a small shared package, **`packages/policy`** — imported by both `apps/api` (middleware + this package owns/versions the rules) and `packages/rag_agent` (query-time enforcement). This is the one deliberate exception to "no shared files between tracks" (see root `CLAUDE.md` Repository Structure): RBAC is inherently cross-cutting and can't be owned by a single track without either duplicating logic or creating a masking gap.

## Audit log
Schema owned by `data/` (see `data/README.md`'s Session, conversation & audit schema) — this folder only calls `data.write_audit(officer_id, session_id, endpoint, request_hash, response_hash, agent_trace)` after every request. SHA-256 hashes only, tamper-evident, not a content store — full conversation text lives in `data.conversation_turn`, written via `data.write_conversation_turn(...)` (see the "How a turn is built" steps above).

## Suggested structure
```
apps/api/
  main.py              # FastAPI app, router mounts
  auth/                # JWT verification, role claims
  routers/             # chat.py, fir.py, person.py, copilot.py, export.py, alerts.py
```
(`packages/policy` and `data/`'s connection/write helpers are imported, not duplicated here — see below.)

## Provides / Consumes
- **Provides to `apps/web`**: the endpoints above, matching the SSE envelope defined here and the `Citation`/`EvidenceItem`/`AgentTraceEntry`/`VisualizationPayload` shapes canonically defined in `packages/rag_agent/README.md` — treat those as an append-only contract (add fields freely, never rename/remove without telling the frontend).
- **Consumes from `packages/rag_agent`**: `run_investigation(state) -> InvestigationState`, `generate_copilot_brief(fir_id) -> CopilotBrief`.
- **Consumes from `packages/ml_models`**: `check_anomalies` only, for `/alerts`; everything else goes through `rag_agent`.
- **Consumes from `packages/policy`**: the RBAC rule definitions (owns/versions them; also the runtime dependency `packages/rag_agent` uses for query-time enforcement).
- **Consumes from `data/`**: `get_session_focus`/`upsert_session_focus`, `write_conversation_turn`, `get_conversation_history` (for `/export/pdf`), `write_audit`, and the `officer` table lookup for policy-relevant fields (PS code, role).

## Non-goals
- No Cypher/SQL generation, no retrieval logic, no ML inference, no RBAC *rule definitions* (those live in `packages/policy`) — all of that lives elsewhere. This folder is auth + policy *enforcement on structured responses* + transport + persistence orchestration, nothing else.
