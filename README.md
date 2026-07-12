# Veritas — KSP Crime Intelligence Platform

Evidence-grounded investigative AI for the Karnataka State Police. Every answer
traces to a record; where the records don't support one, the system says so rather
than guessing.

Architecture: [`CLAUDE.md`](./CLAUDE.md). Each track's contract is its own README.

## Run it

```bash
# 1. Database (Postgres + pgvector). The knowledge graph is an edge-list table in
#    the same database, traversed with NetworkX — there is no graph server.
docker compose up -d

# 2. Python packages (editable, in dependency order)
pip install -e data -e packages/policy -e packages/ml_models -e packages/rag_agent -e apps/api

# 3. Build the dataset: schema -> generate -> Postgres -> graph edges -> graph
#    algorithms -> entity resolution -> vector index. Idempotent; rerun to refresh.
cd data && python -m data.generator.run --firs 3000 && cd ..

# 4. Backend
cd apps/api && VERITAS_DEV_MODE=1 uvicorn api.main:app --port 8000

# 5. Console
cd apps/web && npm install && npm run dev     # http://localhost:3000
```

Sign in as any role — an IO and a DSP genuinely see different data.

```bash
pytest                                        # 80 tests, all packages
python packages/ml_models/fairness_run_audit.py   # pre-demo bias audit
```

## Deploy it (Zoho Catalyst)

The competition requires deployment on Catalyst. The backend runs as an **AppSail**
custom (OCI) service, the Console as **Web Client Hosting**.

```bash
docker build --platform linux/amd64 -t baveshraam/veritas-api:latest .
docker push baveshraam/veritas-api:latest

cd apps/web && npm run build:catalyst && cd ..    # static export -> client/
catalyst deploy
```

Set `GEMINI_API_KEY` and `VERITAS_POSTGRES_DSN` in the AppSail environment (console →
AppSail → Configuration). See [`CLAUDE.md`](./CLAUDE.md) for which Catalyst services
back which layer, and for the three capabilities with no Catalyst equivalent.

## What's real vs. what's gated

Everything below runs today against the live stack:

| | |
|---|---|
| Knowledge graph | NetworkX over a `graph_edge` table — PageRank, Louvain communities, betweenness |
| Retrieval | HippoRAG (personalized PageRank) + Think-on-Graph beam search |
| Verification | CRAG evaluator — refuses to answer on weak/empty evidence |
| Entity resolution | Fellegi-Sunter — 100% precision/recall on injected duplicates |
| Forecasting | Prophet + MinT (coherence verified to 1e-9) |
| Hotspots | KDE + DBSCAN over plain lat/lng columns |
| Risk / recidivism | XGBoost+SHAP, calibrated LightGBM, temporal split |
| Financial crime | Rule-based structuring detector + GraphSAGE GNN |
| Causal inference | DoWhy on **real Census 2011** ground truth — identified, estimated, *and refuted* |
| Fairness | Aequitas-style audit, 80% rule, gender + district subgroups |
| RBAC | Enforced at query-construction time *and* on structured responses |
| Audit | Append-only, SHA-256, DB-level immutability (UPDATE/DELETE no-op) |
| LLM synthesis | Gemini (`gemini-flash-lite-latest`), degrading to deterministic templates on any failure |

Implementation record — what's built, verified, and why: [`docs/implementation/`](./docs/implementation/).

**Gated on things we don't have** — each fails loudly with the exact remedy rather
than degrading silently:

- **Kannada TTS** (voice *output*) needs the self-hosted IndicTTS/Kokoro weights. Voice
  *input* (faster-whisper ASR) and translation (NLLB-200) run today. Catalyst Zia has no
  speech or translation service at all, so these stay self-hosted — permitted by the
  organizers' ruling that an external alternative is allowed where no Catalyst service exists.
- **District-level police strength** is not published in India (BPR&D/KSP report it
  state-wide only). It is therefore an *unmeasured confounder*, named as such with
  every causal estimate rather than adjusted for with an invented number.
- **Micro-geography** — incidents cluster around synthetic activity centres until the
  WorldPop/OSM attractor layer lands. The hotspot *method* is production-grade; the
  synthetic geography under it is not yet.

## Layout

| Folder | Track |
|---|---|
| [`apps/web`](./apps/web) | Command Console — glassmorphic three-pane UI |
| [`apps/api`](./apps/api) | FastAPI — auth, policy, SSE, audit |
| [`packages/rag_agent`](./packages/rag_agent) | LangGraph engine, HippoRAG/ToG, evidence chain, Copilot |
| [`packages/ml_models`](./packages/ml_models) | Predictive analytics, AML, entity resolution, fairness |
| [`packages/policy`](./packages/policy) | RBAC rules — the one deliberately shared package |
| [`data`](./data) | Schemas, generator, graph sync, vector index, Kannada NLP |
