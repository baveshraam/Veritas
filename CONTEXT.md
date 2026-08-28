# CONTEXT.md — session state snapshot (2026-07-15, STATE below superseded 2026-08-28)

Read this + CLAUDE.md at the start of any new thread. **This file's own "if they
conflict, this is newer" claim stopped being true long ago** — it is dated 2026-07-15
and was never updated while ~236 commits and roughly a dozen real passes landed on
`main`. For current state, trust CLAUDE.md's changelog (newest entry wins) and
`docs/WORK_LOG.md`/`docs/ENGINEERING_BRIEF.md` for pass-by-pass detail, not the STATE
block below. The **DEPLOY PIPELINE, MEASURED PLATFORM CONSTRAINTS, WHAT FAILED, and
STANDING USER DIRECTIVES sections below remain accurate** — re-confirmed working
verbatim during the 2026-08-28 pass (a full `get-signature` → relay → `appsail/upsert`
deploy cycle) — and are kept for that reason; only the dated STATE snapshot is stale.

## STATE (2026-07-15 snapshot — stale; see note above)

- **API**: https://veritas-api-50043864344.development.catalystappsail.in
- **Console**: https://veritas-60077763394.development.catalystserverless.in/app/index.html
- `/health` (2026-08-28, current): firs=10000 · graph 16,918n/87,120e · vectors 13,835 docs
  · llm=quickml(glm-4.7-flash) configured · datastore=catalyst · cache=catalyst
- Verified live, 2026-08-28: `scripts/verify_live_deployment.py` 36/36,
  `scripts/judge_flows.py` 26/26, both fresh against production.
- **602 tests green locally** (this file's "190" was the 2026-07-15 count; see
  CLAUDE.md for the current number, since this line will drift stale again).
  All work committed & pushed to `main`.

## WHAT'S USABLE (features, live)

- Chat (EN, SSE streaming): HippoRAG retrieval → ToG deep-dive on low confidence → CRAG evaluator → cited answers. No LLM = deterministic fallback still answers.
- Investigation Copilot: timeline, 5 similar cases, direct-co-accused leads, diary paragraph.
- Records: /cases /fir /person (person = Fellegi-Sunter resolved identities, F1 0.989).
- Risk scoring (XGBoost + exact TreeSHAP via `pred_contribs`), Prophet+MinT forecasts, KDE/DBSCAN hotspots, Isolation Forest alerts, rule-based AML, Louvain communities.
- Kannada translation (NLLB int8 CTranslate2) + ASR (whisper) — models stream from File Store at cold start.
- Audit hash chain + Cron verify (12h) + refresh (6h). RBAC enforced in API middleware AND query construction.

## DEPLOYED-CONTAINER TRADE-OFFS (local dev keeps full quality)

- whisper **tiny** (code default `small`) · **no torch** → GNN AML raises `GNNUnavailable` · **no dowhy** → causal layer `SocioeconomicDataUnavailable` · no shap lib (xgboost native = same math). Rule-based AML (the court-auditable one) unaffected. Demo the GNN/causal on the laptop.

## COST POSTURE (standing directive: ~₹0/month, limited credits)

- One AppSail instance, **memory 2048MB = FLOOR not ceiling** (int8 models OOM at 1024; org max is also 2048). Disk 1024 max.
- What consumes credits: AppSail compute (the big one), Data Store rows (~105k seeded), File Store (761MB models), QuickML per-call, Cron (2 jobs), Cache.
- Mirror architecture means runtime Data Store reads ≈ 0 after hydration (one full read per cold container). QuickML called only per chat turn; deterministic path costs nothing.
- Check usage: Catalyst console → project → **Usage** tab; billing under profile → Billing. Per-component views under each service.
- **Never** add always-on workers, raise memory, or add services without flagging cost first.

## DEPLOY PIPELINE (the only way that works)

1. Patch inside docker container `veritas-flatten` (`docker cp`), `docker export | docker import`
   with full `-c` set — **`USER root` mandatory**, plus PATH/LANG/PYTHON*/VERITAS_* envs, EXPOSE 8000, shell-form uvicorn CMD (exact command in git history / memory file `catalyst-deploy-pipeline`).
2. `docker push baveshraam/veritas-api:latest` (image **0.88GB** — hard ceiling ~1.3GB, see constraints).
3. Fresh signed URL: `GET /baas/v1/project/52852000000013048/appsail/get-signature?name=veritas-api` (30-min TTL, single-use). Write to `.github/relay-upload.url`, commit, push → `relay-deploy.yml` uploads from GitHub runner (home uplink ~7Mbps can't beat TTL).
4. Callback: `PUT .../appsail/upsert` multipart — name, memory=2048, platform=custom_runtime, configuration={"port":8000,"catalyst_auth":false,"disk":1024}, local_object_key.
5. Bundle logs: `GET .../appsail/{id}/deployment/{depid}/logs`. Env/restart: `POST /appsail/{id}/configuration` (works only after 1 successful deploy).
- Console deploy: `catalyst deploy --only client`.
- Admin token: `node scripts/catalyst-token.js` — **throttles if looped**; cache ~1h (was cached at /tmp/cached_token.txt).
- Secrets set on app: VERITAS_JWT_SECRET, VERITAS_JOB_TOKEN (values were in /tmp/jwt_secret.txt, /tmp/job_token.txt — regenerate if lost).

## MEASURED PLATFORM CONSTRAINTS (undocumented; cost days)

1. **Bundle sandbox ~5GB holds 4 copies** (tar+blobs+staged+rootfs) → image ≤ ~1.3GB. 9.31GB & 4.66GB & 1.61GB all died. Don't gzip the tar (staging adds a copy). Models live OUTSIDE the image: File Store folder `models` id `52852000000195786`, 8×95MB chunks, streamed+spliced at cold start (`data/nlp/model_fetch.py`), never on disk as one tar.
2. **SDK context = per-request X-ZC-\* headers**; bare `initialize()` → "Catalyst headers are empty". Middleware `ds.bind_catalyst_request(request)` captures it; background work reuses via `ds.catalyst_app()`.
3. **Live ZCQL refuses ALL our JOINs** ("No relationship between tables" — ER relates by value). Reads run on a **sqlite mirror** (`/tmp/veritas_mirror.db`) hydrated once per container, atomic (`.hydrating` + os.replace). Writes: Data Store first, mirror second.
4. **Pagination duplicates one row at page boundaries even under ORDER BY** → `_catalyst_select` dedupes on ROWID; hydration INSERT OR IGNOREs. (13 "phantom dups" once deleted by mistake were this artifact — restored from local sqlite.)
5. **Live Data Store returns every value as a string** ("4" not 4) → schema-typed coercion in mirror + `int()` at auth call sites.
6. **SDK JSON-serializes writes** → datetimes must be `"%Y-%m-%d %H:%M:%S"` strings (`ds._sdk_row`); raw datetime 500'd every audited endpoint.
7. langgraph needs `typing_extensions>=4.13` (pinned in constraints.txt).
8. Stratus bucket creation is scope-blocked over API (OAUTH_SCOPE_MISMATCH) — console-only. **Not needed**: File Store replaced it for models, mirror serves the graph.
9. Hybrid auth: Catalyst session first, JWT fallback; SDK throws non-HTTP exception on cookie-less requests → mapped to 401 (`jwt_auth.current_officer`).

## WHAT FAILED (don't retry these)

- Building the image from Dockerfile with runtime HF downloads → 3h stall (rate limits). Convert/patch inside the existing container instead (~2 min).
- Local upload of the tar → TTL death. Always relay via GitHub Actions.
- `catalyst deploy` CLI for AppSail → silent, defaults memory=256 (doomed). Use the raw upsert.
- memory=4096 → "Invalid input value for memory". 2048 is org max.
- Deleting "duplicate" Data Store rows → they were pagination artifacts, not dups.

## KEY FILES TOUCHED THIS SESSION

- `data/data/ds.py` — mirror, dedupe, `_sdk_row`, `bind_catalyst_request` (the core live-fix file)
- `data/data/nlp/model_fetch.py` — File Store chunk streaming
- `apps/api/api/main.py` — context middleware + warm thread · `apps/api/api/auth/jwt_auth.py` — hybrid auth
- `packages/ml_models/.../risk/scoring.py` — `_XGBShap` · `financial/gnn.py`, `causal/effects.py` — graceful degradation
- `.github/workflows/relay-deploy.yml` · `constraints.txt` · README.md (layman rewrite) · CLAUDE.md v7+v8 changelogs

## STANDING USER DIRECTIVES

- Minimize Catalyst cost (~₹0 target); flag any cost-increasing change BEFORE making it.
- Never force-push / destructive git. Commit & push work as it lands.
- User works autonomously-AFK style: finish tasks end-to-end, report at the end.
