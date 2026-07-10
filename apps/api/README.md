# Backend Platform (`apps/api/`)

**What this is**: the one deployable backend service. Terminates auth, enforces who-sees-what, streams the chat/reasoning-trace to the frontend, writes the audit trail, and hosts (imports) `packages/rag_agent` and `packages/ml_models` — it contains no reasoning or ML logic itself.

Single FastAPI service (Layer 7 of root [`CLAUDE.md`](../../CLAUDE.md)) — async, Pydantic v2.

## Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/chat` | `POST`, SSE response | Body: `{session_id, officer_id, officer_role, query, language}`. Streams `AgentTraceEntry` events as the investigation runs, then a final event with `final_answer` + `citations`. |
| `/fir/{fir_id}` | `GET` | Full FIR record, policy-filtered by role. |
| `/person/{person_id}` | `GET` | Person record; victim identity masked below DSP rank. |
| `/export/pdf` | `POST` | Body: `{session_id}`. Returns a PDF (Puppeteer render of conversation + charts, KSP letterhead). |
| `/alerts` | `WebSocket` | Pushes Isolation Forest anomaly alerts live. |

Every route calls into `packages/rag_agent.run_investigation(...)` or `packages/ml_models` — this file only does auth, policy filtering, and shaping the response.

## Auth
JWT with a `role` claim: `IO, SHO, DSP, SP, IG, SCRB_Analyst`. Verified in middleware before any handler runs.

## Policy (in-process, versioned, unit-tested — functionally what OPA/Rego expresses)
- IO sees only FIRs filed at their own PS.
- Victim identity is masked below DSP rank.
- Graph traversal depth is capped by role (e.g. IO can't run unbounded multi-hop financial traversals; DSP+ can).
Policy checks run as FastAPI middleware, applied to every response before it leaves the handler — not bolted on per-route.

## Audit log
Append-only Postgres table:
```sql
CREATE TABLE audit_log (
    log_id UUID PRIMARY KEY,
    officer_id UUID, session_id UUID, endpoint VARCHAR(100),
    request_hash VARCHAR(64), response_hash VARCHAR(64),   -- SHA-256
    agent_trace JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- immutability: no UPDATE/DELETE, ever
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
```

## Suggested structure
```
apps/api/
  main.py              # FastAPI app, router mounts
  auth/                # JWT verification, role claims
  policy/              # in-process RBAC policy module + its unit tests
  audit/               # append-only log writer
  routers/             # chat.py, fir.py, person.py, export.py, alerts.py
  db/                  # Postgres/PostGIS connection handling
```

## Provides / Consumes
- **Provides to `apps/web`**: the endpoints above, and the `EvidenceItem` / `Citation` / `AgentTraceEntry` shapes defined in `packages/rag_agent/README.md` — treat those as an append-only contract (add fields freely, never rename/remove without telling the frontend).
- **Consumes from `packages/rag_agent`**: `run_investigation(state) -> InvestigationState`.
- **Consumes from `packages/ml_models`**: direct calls only for anomaly-alert polling (`/alerts`); everything else goes through `rag_agent`.
- **Consumes from `data/`**: connection helpers only, for the audit log and any policy-relevant lookups (e.g. officer's PS code).

## Non-goals
- No Cypher/SQL generation, no retrieval logic, no ML inference — all of that lives in `packages/rag_agent` and `packages/ml_models`. This folder is auth + policy + transport + audit, nothing else.
