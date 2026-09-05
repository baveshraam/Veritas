# CONTEXT.md — operational reference (STATE dated 2026-07-15, stale; rest re-confirmed 2026-08-28)

Read this + CLAUDE.md at the start of any new thread. The STATE block below is a dated
snapshot and has drifted — trust CLAUDE.md's changelog and `docs/WORK_LOG.md`/
`docs/ENGINEERING_BRIEF.md` for current state instead. **DEPLOY PIPELINE, MEASURED
PLATFORM CONSTRAINTS, WHAT FAILED, and STANDING USER DIRECTIVES remain accurate** —
re-confirmed verbatim during the 2026-08-28 deploy (`get-signature` → relay →
`appsail/upsert`).

## STATE

- **API**: https://veritas-api-50043864344.development.catalystappsail.in
- **Console**: https://veritas-60077763394.development.catalystserverless.in/app/index.html
- Current test count, `/health` fields and deployment status: trust `CLAUDE.md`'s header
  and changelog over anything dated in this file — this snapshot is not kept current.

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

The general shape of each of these is in `CLAUDE.md`'s "Platform gotchas" section — this
list keeps only the exact paths/ids/commands that section doesn't carry:

1. Bundle sandbox holds **4 copies** of the image simultaneously → real ceiling ≈1.3GB.
   Don't gzip the tar (staging adds a copy). Models: File Store folder `models`, id
   `52852000000195786`, 8×95MB chunks (`data/nlp/model_fetch.py`).
2. sqlite mirror lives at `/tmp/veritas_mirror.db`, hydrated atomically (`.hydrating` +
   `os.replace`).
3. Live Data Store returns every value as a string (`"4"` not `4`) — schema-typed
   coercion in the mirror, plus explicit `int()` at auth call sites.
4. `langgraph` needs `typing_extensions>=4.13` (pinned in `constraints.txt`).
5. Hybrid auth: Catalyst session first, JWT fallback; SDK throws a non-HTTP exception
   on cookie-less requests, mapped to 401 in `jwt_auth.current_officer`.

## WHAT FAILED (don't retry these)

- Building the image from Dockerfile with runtime HF downloads → 3h stall (rate limits). Convert/patch inside the existing container instead (~2 min).
- Local upload of the tar → TTL death. Always relay via GitHub Actions.
- `catalyst deploy` CLI for AppSail → silent, defaults memory=256 (doomed). Use the raw upsert.
- memory=4096 → "Invalid input value for memory". 2048 is org max.
- Deleting "duplicate" Data Store rows → they were pagination artifacts, not dups.

## CORE LIVE-FIX FILES

`data/data/ds.py` (mirror, dedupe, `_sdk_row`, `bind_catalyst_request`) is where nearly
every platform constraint above is actually worked around — read it before re-deriving
one of them elsewhere.

## STANDING USER DIRECTIVES

- Minimize Catalyst cost (~₹0 target); flag any cost-increasing change BEFORE making it.
- Never force-push / destructive git. Commit & push work as it lands.
- User works autonomously-AFK style: finish tasks end-to-end, report at the end.
