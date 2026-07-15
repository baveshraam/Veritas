# Veritas — KSP Datathon 2026, Challenge 01

**A conversational crime-intelligence platform for the Karnataka State Police.** An officer
asks a question in English or Kannada — typed or spoken — and gets an answer where **every
claim traces back to a specific police record**. No hallucinated facts: if the records don't
support an answer, the system says so.

> Deep technical detail and every design decision live in [CLAUDE.md](./CLAUDE.md) — the
> single source of truth for this repo. This README is the plain-language tour.

---

## What it does

Ask things like:

- *"Does Ramesh Gowda have prior cases?"* — even though the police database never says two
  records are the same person, Veritas reconstructs identities across cases
  (record linkage, measured **F1 0.989**) and answers with the linked case numbers.
- *"Show me crime hotspots in Kolar"* — a heat map computed from real incident coordinates.
- *"Trace the money trail from this account"* — follows transactions through the financial
  layer and renders the flow as a Sankey diagram; a GNN and a court-auditable rule detector
  flag laundering patterns.
- *"Who does he operate with?"* — a co-offending network is derived from the records, and
  community detection surfaces organised groups (labelled honestly as derived communities —
  the records name no gangs, so neither do we).
- *"Will burglaries rise next month in this district?"* — statistical forecasts with
  uncertainty bands, where a district's forecast always equals the sum of its stations'.
- *"ಕೊಲಾರದಲ್ಲಿ ನಿನ್ನೆ ಏನಾಯಿತು?"* — Kannada in, Kannada out. Translation and speech-to-text
  run **inside our own container**; police text never leaves the network.

Every answer carries citation chips that open the underlying record. A Reasoning Trace panel
shows *how* the answer was assembled. Every interaction lands in a tamper-evident audit log
(a SHA-256 hash chain — editing any row breaks every hash after it).

The data is **synthetic** (no real FIR data is available to us) but sits on real ground
truth: NCRB crime statistics, Census 2011 district socioeconomics, and real Karnataka GIS
boundaries. The database schema is the organizers' ER diagram, reproduced verbatim.

## How it's put together

```
Browser (Command Console — chat / map / network graph / Sankey / forecasts)
   │            Next.js, hosted on Catalyst Web Client Hosting
   ▼
FastAPI backend — one container on Catalyst AppSail
   │            auth · role-based policy · audit hash chain · SSE streaming
   ▼
LangGraph reasoning engine
   │            HippoRAG graph retrieval → Think-on-Graph deep dives →
   │            evidence evaluator (never fabricates on empty evidence) → synthesis
   ▼
Catalyst services                      In-process ML
   Data Store   37 tables               NetworkX graph algorithms (PageRank, Louvain)
   File Store   model weights           XGBoost + native TreeSHAP risk scoring
   Cache        session focus           LightGBM recidivism · Prophet forecasts
   QuickML      GLM-4.7-Flash LLM       Fellegi-Sunter identity resolution
   Cron         refresh + audit check   NLLB translation · Whisper speech (CTranslate2 int8)
```

The LLM only makes answers fluent — it never makes them true. If it's unreachable, the
deterministic retrieval + template paths still produce grounded, cited answers.

## What's built and working right now

- **All 188 tests green**, no database or Docker needed (`python -m pytest`).
- **The full data foundation**: the organizers' 27-table ER verbatim + 10 `vx_` tables of
  ours; a synthetic-data generator with realistic hotspots, repeat offenders, co-offending
  crews and name-spelling drift; ~105k rows seeded into the live Catalyst Data Store.
- **Identity resolution** (the centrepiece — the ER has no "person", so we build one),
  the knowledge graph, financial/AML layer, all predictive models, the fairness audit,
  RBAC policy enforced at query-construction time, and the audit hash chain.
- **The API is live on Catalyst AppSail** at
  `https://veritas-api-50043864344.development.catalystappsail.in` — deployed, enabled,
  serving. The web console deploys to Catalyst Web Client Hosting.
- **Kannada + English answers**, voice input, PDF export, live alerts over WebSocket.

## How deployment works (and why it's unusual)

Catalyst runs the backend as a container image. Its deploy pipeline unpacks an image in a
**~5GB scratch space that must hold roughly four copies at once** — measured empirically from
its own logs — which caps a deployable image at about **1.3GB**. Our ML weights alone are
760MB, so:

- The image was cut **9.31GB → 0.88GB**: NLLB translation converted to int8 (600MB instead
  of a 2.4GB checkpoint accidentally baked in twice), CPU-only builds of the ML libraries,
  torch removed (one detector degrades gracefully; SHAP values now come from XGBoost's own
  exact TreeSHAP), and no build tooling or caches in the image.
- The **model weights live in Catalyst File Store** (the project's own storage — nothing is
  downloaded from the public internet at runtime) and stream into the container once at
  cold start.
- A home uplink can't finish the upload inside Catalyst's 30-minute signed-URL window, so
  **deploys relay through GitHub Actions** (`.github/workflows/relay-deploy.yml`): the
  runner pulls the image from Docker Hub and uploads it datacenter-to-datacenter in minutes,
  then a small authenticated callback turns the upload into a deployment.

## Run it locally

```bash
python -m pytest                                      # 188 tests, no stack needed
cd data && python -m data.generator.run --cases 10000 # generate a synthetic dataset
cd apps/api && uvicorn api.main:app --reload          # the API (sqlite backend locally)
cd apps/web && npm run dev                            # the Command Console
```

Locally everything runs against SQLite using the *same query strings* the deployed service
sends to the Data Store — the test suite exercises the real queries, not mocks.

## What's deliberately not built

Kafka, Flink, Kubernetes, Keycloak and friends are **described, not built** (CLAUDE.md,
Appendix A): at this dataset's scale they'd be architecture theatre. The causal-inference
layer and the GNN detector run anywhere their libraries are installed (local dev, demo
laptop) and report themselves unavailable in the size-capped deployed container rather than
pretending.
