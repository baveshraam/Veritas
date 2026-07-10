# KSP Datathon 2026 — Crime Intelligence Platform (Challenge 01)

**Status**: v3.1 — architecture finalized, repo scaffolded into 5 tracks. This file is the single current-state record of the project — keep it current; append deltas to the changelog instead of rewriting history; do not let stale backlog/todo/open-question items accumulate here — that's what git issues are for.
**Scope**: Challenge 01 (Conversational AI), architected to also cover Challenge 02's analytics.
**Ground rule for this doc**: choices are justified by "is this the best solution to the actual problem," never by "what's fast to build." Where something is simple (e.g. batch pipeline, single API service), that's because the problem has no real-time/multi-tenant nature to justify otherwise — not because building the complex version would take too long.

## Changelog
- **v1**: LLM-generated "enterprise fantasy" stack (Kafka/Flink/Iceberg/K8s/Keycloak/OPA/Kong/MLflow/Airflow). Wrong optimization target — infra with no demo-visible payoff.
- **v2**: Cut infra cosplay, kept reasoning/UX substance. Added financial-crime graph, session entity memory, Investigation Copilot, Command Console UI, requirement traceability matrix, responsible-AI section. Grounded in CrimeKGQA, COPLINK/CrimeNet Explorer, Palantir Gotham, LangGraph citation-grounding pattern.
- **v3 (this pass)**: Reframed design philosophy to be effort-agnostic (best solution, not least effort). Upgraded graph reasoning with HippoRAG + Think-on-Graph. Upgraded evidence verification with a CRAG-style evaluator. Added MinT hierarchical forecast reconciliation. Added GNN-based AML detection alongside the rule-based structuring detector. Added Fellegi-Sunter probabilistic entity resolution (real fix for Indian-name/alias duplication). Added Aequitas as the named bias-audit methodology. Replaced the "dense command-console" UI direction with a futuristic glassmorphic/spatial design language per explicit direction.
- **v3.1**: Scaffolded the repo into 5 parallel-work folders (`apps/web`, `apps/api`, `packages/rag_agent`, `packages/ml_models`, `data/`), each with its own README mapping to the layers below — see Repository Structure. Dropped the Open Questions/backlog section: this file tracks current architecture only, not todos.
- **v3.2**: Cross-README integration audit. Closed real gaps found by treating the 5 READMEs as one system: added `officer`/`session`/`conversation_turn` tables (audit_log was hash-only and had no plaintext conversation store — broke PDF export and multi-turn resumption); added the missing `visualization` + full `evidence_items` fields to the chat response (the "context view swaps by query type" and citation-drawer features had no wire contract); defined all 9 previously-untyped `ml_models` return types; fixed `resolve_entities` (was documented as a live per-query call, corrected to the batch job it actually is, run from `data/`'s generator); wired the previously-orphaned `estimate_causal_effect` and Investigation Copilot (`generate_copilot_brief`) to actual callers; extracted `packages/policy` as the one deliberate shared module, since depth-capping/masking can't be enforced post-hoc alone. Full findings in the audit that produced this pass.

---

## Design Philosophy

- **Graph-native.** Crime data is relational at its core (people↔events↔locations↔money↔behavior). Property graph (Neo4j) is the primary model, not a relational afterthought. Validated by COPLINK/CrimeNet Explorer (NIJ/Univ. of Arizona) and Palantir Gotham.
- **Agentic reasoning, not retrieval.** Decompose → plan multi-step investigation across graph/vector/geospatial/relational stores → synthesize → verify → answer with a citation chain. Mirrors the LangGraph citation-grounding pattern (structured output + deterministic verification loop).
- **Evidence-grounded.** Every claim traces to an exact FIR record, graph query, or model run. No answer without evidence; no evidence without a source. Academic precedent: CrimeKGQA (2025, Neo4j+Cypher-gen RAG for crime investigation).
- **Best available method, not least effort.** Where the literature has a better-validated technique than a naive approach, use it (HippoRAG over ad hoc embedding search, MinT over independent per-level forecasts, Fellegi-Sunter over fuzzy string matching). Complexity is justified by the problem, never rationed by team size.
- **Responsible by design.** Predictive policing has a documented history of laundering historical bias into "objective" scores. Every prediction is decision-support, audited (Aequitas), never an automated trigger.

---

## System Overview

```
   KSP OFFICERS (web + mobile)
            │
   COMMAND CONSOLE — glassmorphic spatial UI (chat / map+graph+Sankey / case rail)
            │
   FASTAPI (async, JWT + in-process policy)
            │
   LANGGRAPH MULTI-AGENT ENGINE
   Orchestrator → HippoRAG retrieval → [ToG deep-dive if confidence low] →
   specialist agents → CRAG-style evidence evaluator → synthesis
            │
   ┌────────┼──────────┬─────────────┬───────────┬──────────┐
 NEO4J    QDRANT/    POSTGRES+    ML MODELS   AUDIT LOG (append-only,
 (graph + PGVECTOR   POSTGIS      (KDE,DBSCAN, SHA-256, JSONB agent trace)
 GNN-AML) (HippoRAG  (FIR/person/ Prophet+MinT,
          index)     socioecon)   XGB+SHAP,GNN)
            │
   SYNTHETIC DATA GENERATOR — Faker + real NCRB/Census/NSSO/KA-GIS ground truth
```

No Kafka/Flink/Iceberg/K8s/Keycloak/OPA/Kong/MLflow/Airflow in the build — there is no real-time source or multi-tenant deployment to justify them here. Described as the production path in **Appendix A**.

---

## Requirement Traceability Matrix

| Brief requirement | Section | Status |
|---|---|---|
| NL chatbot, EN + Kannada | §6 NLP | Core |
| Retrieve FIR/accused/victim/location/status/history | §2 Graph, §3 agents | Core |
| Context-aware conversation | §3.2 Session Entity Memory | Fixed in v2 |
| Save conversation as PDF | §9 UI | Core |
| Multi-language | §6 NLP | Core |
| Voice interaction | §3.4 Voice Agent | Core |
| Crime pattern discovery | §4 Predictive Models | Core |
| Criminal network analysis | §2 Graph + GDS | Core |
| Organized-crime/repeat-offender detection | §2.2 Louvain+PageRank | Core |
| Socio-demographic insights | §4 Risk model + district data | Core |
| Causal social risk correlation | §4 DoWhy | Differentiator |
| Behavioral/offender profiling | §4 Risk+recidivism | Core |
| Financial crime & transaction link analysis | §2.4 Financial graph + GNN-AML | New in v2, upgraded v3 |
| Investigator decision support | §3.3 Investigation Copilot | Fleshed out v2 |
| Crime forecasting & early warning | §4 Prophet+MinT, Isolation Forest | Core, upgraded v3 |
| Explainable AI, audit trail | §5 Evidence Chain, §9 Reasoning Trace | Core |
| Secure RBAC | §8 Security | Core |

---

## Layer 1: Data Foundation

```sql
CREATE TABLE officer (
    officer_id UUID PRIMARY KEY, badge_no VARCHAR(20) UNIQUE, name VARCHAR(200),
    ps_code VARCHAR(10), district_code VARCHAR(5), role VARCHAR(20)
);

CREATE TABLE fir (
    fir_id UUID PRIMARY KEY, ps_code VARCHAR(10), district_code VARCHAR(5),
    fir_number VARCHAR(20), date_filed TIMESTAMPTZ, ipc_sections TEXT[],
    crime_type VARCHAR(100), occurrence_from TIMESTAMPTZ, occurrence_to TIMESTAMPTZ,
    location_geom GEOMETRY(Point,4326), district VARCHAR(50), taluk VARCHAR(50),
    complainant_id UUID REFERENCES person(person_id), io_id UUID REFERENCES officer(officer_id),
    case_status VARCHAR(30), modus_operandi TEXT, narrative TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE person (
    person_id UUID PRIMARY KEY, scrb_id VARCHAR(20) UNIQUE,
    name_en VARCHAR(200), name_kn VARCHAR(200), dob DATE, gender VARCHAR(10),
    address_geom GEOMETRY(Point,4326), aadhaar_hash VARCHAR(64),
    criminal_history BOOLEAN DEFAULT FALSE, risk_score FLOAT, gang_affiliation VARCHAR(100),
    canonical_entity_id UUID  -- NEW: Fellegi-Sunter linkage target, see §6.2
);

CREATE TABLE criminal_record (
    record_id UUID PRIMARY KEY, person_id UUID REFERENCES person(person_id),
    fir_id UUID REFERENCES fir(fir_id), role VARCHAR(50),
    arrest_date DATE, bail_status VARCHAR(30), conviction BOOLEAN
);

-- Real data, not simulated: Census/data.gov.in/NSSO
CREATE TABLE district_socioeconomic (
    district_code VARCHAR(5) PRIMARY KEY, year INT, literacy_rate FLOAT,
    unemployment FLOAT, poverty_index FLOAT, population BIGINT,
    urban_ratio FLOAT, police_per_lakh FLOAT
);
```

**Grounding**: crime records are synthetic (no real FIR data available to us) but IPC-section distributions are weighted by real published NCRB Karnataka statistics, joined to real district socioeconomic data and real KA-GIS district/taluk boundaries. Pitch: "synthetic crime layer on real socio-demographic ground truth." 10-50K FIR records is enough for every demo scenario.

**Pipeline**: one Python job (re)builds Postgres, syncs Neo4j, re-embeds narratives. Functionally identical to a streaming pipeline here because there is no real-time source — not a shortcut, a correct read of the problem.

**Session/conversation/audit schema** (`session`, `conversation_turn`, `audit_log` — full DDL in `data/README.md`): `apps/api` is stateless between requests, so multi-turn conversation, PDF export, and the tamper-evident trail each need their own table — `audit_log` stores only a SHA-256 hash (tamper-evidence), not plaintext, so it cannot double as the conversation store.

---

## Layer 2: Knowledge Graph

**Nodes**: `Person, CrimeEvent, Location, Gang, MethodOfOperation, Vehicle, Account, Transaction`

```cypher
(:Person {person_id, scrb_id, name_en, name_kn, dob, gender, risk_score,
          gang_affiliation, is_habitual_offender, canonical_entity_id})
(:CrimeEvent {fir_id, crime_type, ipc_sections, date_occurred, location, district,
              modus_operandi, case_status})
(:Account {account_id, bank, account_type, opened_date})
(:Transaction {txn_id, amount, date, channel, flagged_suspicious: Boolean})
```

**Edges**:

```cypher
(:Person)-[:ACCUSED_IN {role, arrest_date}]->(:CrimeEvent)
(:Person)-[:VICTIM_IN]->(:CrimeEvent)
(:Person)-[:CO_ACCUSED_WITH {fir_ids, strength}]->(:Person)
(:Person)-[:MEMBER_OF {since, role}]->(:Gang)
(:CrimeEvent)-[:OCCURRED_AT]->(:Location)
(:Person)-[:USES_METHOD]->(:MethodOfOperation)
(:Person)-[:OWNS_ACCOUNT]->(:Account)
(:Account)-[:TRANSFERRED_TO {amount, date}]->(:Account)
(:Transaction)-[:LINKED_TO]->(:CrimeEvent)
(:Account)-[:INVOLVED_IN]->(:Transaction)
(:Person)-[:SAME_AS {confidence}]->(:Person)   -- NEW: Fellegi-Sunter linkage edge
```

### 2.2 Graph Algorithms (Neo4j GDS, on-demand)
PageRank (influence), Betweenness (brokers between gangs), Louvain (communities/gangs), Node Similarity (shared MO).

### 2.3 GraphRAG Retrieval — HippoRAG + Think-on-Graph

Two published, complementary methods replace ad hoc "embed and cosine-search":

- **HippoRAG** (Gutiérrez et al., NeurIPS 2024): extract query entities → seed **Personalized PageRank** over the KG → single-step multi-hop retrieval. 10-20x cheaper than iterative retrieval, and it's literally what our GDS PageRank layer is for — this names and formalizes what was previously an ad hoc heuristic.
- **Think-on-Graph / ToG** (Sun et al., ICLR 2024): for deep multi-hop investigative questions ("how are these three gangs financially connected over the last year"), the LLM agent iteratively beam-searches entity/relation paths on the graph instead of trusting one generated Cypher query. Used when HippoRAG's confidence is low or the question is explicitly relational/multi-hop; produces a traceable reasoning path, not just an answer.
- Louvain community summaries (CrimeKGQA pattern) remain the global-context layer underneath both.

### 2.4 Financial Crime Graph

- Bounded-depth traversal for money trails: `(:Account)-[:TRANSFERRED_TO*1..4]->(:Account)`
- **Rule-based structuring detector** (many sub-threshold transactions) — kept as the explainable first line judges and courts can audit line-by-line.
- **GNN suspicious-subgraph classifier** (heterogeneous/temporal graph neural network, per current AML literature — e.g. group-aware deep graph learning, temporal motif detection over transaction graphs) trained on the synthetic graph with injected structuring/layering patterns as ground truth. Catches coordinated multi-account laundering patterns the rule-based detector structurally cannot see. Explained per-flag via attention-weight/subgraph highlighting, not a bare score.
- Visualized as a Sankey money-flow diagram, distinct from the criminal-network view.

---

## Layer 3: Multi-Agent Orchestration (LangGraph)

```python
class InvestigationState(BaseModel):
    session_id: str; officer_id: str; officer_role: str
    original_query: str; language: Literal["en", "kn"]
    active_entities: SessionFocus
    decomposed_subqueries: List[str]
    evidence_items: List[EvidenceItem]
    graph_query_results: List[dict]; sql_query_results: List[dict]
    vector_search_results: List[dict]; prediction_results: Optional[dict]
    final_answer: Optional[str]; citations: List[Citation]
    confidence_score: float; requires_escalation: bool
    agent_trace: List[AgentTraceEntry]   # rendered in UI, not just logged
```
(Sketch only — the canonical, complete version, including `visualization`/voice fields and exactly what's session-persistent vs per-turn, lives in `packages/rag_agent/README.md`. Edit that one; this block is illustrative.)

### 3.2 Session Entity Memory
```python
class SessionFocus(BaseModel):
    active_person: Optional[str]; active_fir: Optional[str]
    active_location: Optional[str]; active_date_range: Optional[tuple]
```
Orchestrator resolves pronouns/references ("does **he** have priors") against this focus stack before routing, updating it every turn. Strong, honest live-demo moment: ask a deliberately ambiguous follow-up on stage.

### 3.3 Investigation Copilot
Given an open FIR, auto-generate: (1) chronological timeline, (2) top-5 MO-similar past cases with outcomes, (3) ranked investigative leads (e.g. "matches Community 47; 3 associates in adjoining districts"), (4) draft case-summary paragraph for the case diary. This is the "I'd use this Monday morning" feature.

### 3.4 Agent Roster
Orchestrator · HippoRAG/ToG Retrieval Agent · SQL Agent (text-to-SQL) · Vector Search Agent (hybrid dense+BM25, RRF) · Geospatial Agent (PostGIS) · Prediction Agent (calls model endpoints, never predicts inline) · Evidence Synthesis Agent · Translation Agent (IndicTrans2) · Voice Agent (ASR/TTS).

---

## Layer 4: Predictive Analytics

- **KDE** (Gaussian, Scott's rule) — continuous hotspot density
- **DBSCAN** (`eps=500m, min_samples=10`) — discrete hotspot polygons; **ST-DBSCAN** for spatio-temporal series linking
- **Prophet + MinT reconciliation**: forecast independently at PS / taluk / district / state level, then reconcile with **Minimum Trace (MinT)** (Wickramasuriya, Athanasopoulos & Hyndman, 2019, *JASA*) so a district's forecast always equals the coherent sum of its taluks — statistically optimal, not just "close enough." Formal upgrade over unreconciled independent forecasts.
- **XGBoost + SHAP** risk scoring; **LightGBM** recidivism (180-day re-offense, calibrated probabilities); **Isolation Forest** district-level spike anomaly alerts
- **DoWhy** causal layer for socioeconomic claims — causal effect estimate with confounding adjustment, not bare correlation

Return-type shapes for every model above (`RiskResult`, `ForecastResult`, `HotspotPolygon`, etc.) and exactly who calls each: `packages/ml_models/README.md`.

---

## Layer 5: Retrieval & Evidence Chain

```python
class EvidenceItem(BaseModel):
    evidence_id: str
    source_type: Literal["FIR_RECORD","CRIMINAL_RECORD","GRAPH_RELATIONSHIP",
                          "COMMUNITY_SUMMARY","ML_PREDICTION","GEOSPATIAL_ANALYSIS"]
    source_id: str; source_query: Optional[str]
    content: str; confidence: float; timestamp: datetime
```

Citations render as `[1] FIR/BLR/2024/KGF/001234 — Filed 12 Mar 2024, Kolar PS, IPC 302` (1-based index). Full `EvidenceItem`/`Citation`/`VisualizationPayload` shapes and the exact SSE wire contract: `packages/rag_agent/README.md` and `apps/api/README.md`.

**Verification loop — CRAG-style evaluator**: a lightweight relevance/confidence evaluator scores each retrieval batch (per Corrective-RAG, Yan et al. 2024) and triggers one of: accept → widen query/retry → explicitly state "not found in available records." Never fabricates on empty evidence. This is the strongest "trustworthy for law enforcement" beat in a live demo — it's a named, published pattern, not an improvised safeguard.

---

## Layer 6: NLP, Language & Entity Resolution

- **NER**: AI4Bharat IndicNER — native Kannada entity extraction (PERSON, LOCATION, GANG, VEHICLE, IPC_SECTION)
- **Transliteration**: AI4Bharat IndicXlit — merges "Ramesh"/"ರಮೇಶ್" as candidate variants
- **Translation**: AI4Bharat IndicTrans2, self-hosted (FIR data never leaves the network)
- **ASR**: Vakyansh (Kannada) / Whisper (English fallback), self-hosted
- **TTS**: AI4Bharat IndicTTS (Kannada) / Kokoro-TTS (English), self-hosted

### 6.2 Entity Resolution — Fellegi-Sunter probabilistic linkage
Real crime databases accumulate duplicate person records under name/spelling/transliteration variants — a genuine data-quality problem no other team will address. Formalize it: the **Fellegi-Sunter model** (1969; foundational, unsupervised, still the basis of modern record linkage) scores candidate pairs by weighted field agreement (name similarity post-IndicXlit, DOB, address proximity, phone) into link / possible-link / non-link decisions with explicit error-rate thresholds. Matches feed the `SAME_AS {confidence}` graph edge and `canonical_entity_id` column — so "has this person been arrested before under a different name spelling" gets a real, statistically grounded answer instead of silent duplication.

---

## Layer 7: API Layer

Single **FastAPI** service — async, Pydantic v2, SSE/WebSocket for streaming chat and live alerts. No separate gateway or graph microservice: one well-bounded service is functionally indistinguishable from a decomposed one at this scale and has no split-brain failure modes. Service decomposition path described in Appendix A.

---

## Layer 8: Security

- **Auth**: JWT with `role` claim (`IO, SHO, DSP, SP, IG, SCRB_Analyst`)
- **Policy**: versioned, unit-tested Python policy module (`packages/policy`, functionally what OPA/Rego expresses) — e.g. "IO sees only their PS's FIRs," "victim identity masked below DSP rank," "graph traversal depth capped by role." Enforced in two places, not one: `apps/api` middleware for structured responses (post-hoc masking is fine there); `packages/rag_agent`'s Cypher/SQL Agents at query-construction time for depth-capping and anything feeding a free-text answer (post-hoc is not fine there — you can't un-traverse a graph or reliably redact generated prose)
- **Audit**: append-only Postgres table, SHA-256 response hash, full agent trace as JSONB, `RULE ... DO INSTEAD NOTHING` on UPDATE/DELETE for immutability

---

## Layer 9: UI/UX — Command Console (glassmorphic spatial design)

**Direction**: futuristic minimalist, glassmorphism with subtle acrylic blur layers, soft elevation shadows, floating components, smooth natural-easing microinteractions. Clean spatial layout, generous spacing, light depth layering, restrained gradient-mesh background. Modern crisp legible typography. Soft neon/pastel accents used sparingly for emphasis only. Calm, premium, spatial — next-gen Apple-style with a subtle sci-fi undertone, rendered in **dark glass** (frosted dark-acrylic panels over a deep gradient-mesh background) so it stays legible for dense command-console work while keeping the calm/premium feel — light-glass-on-white would wash out map/graph density.

**Layout — three floating panes, not hard-edged panels:**
- **Left — Chat**: streaming SSE conversation, voice push-to-talk with a live waveform, EN/KN toggle. Frosted glass card floating over the background, soft shadow, rounded generously.
- **Center — Context view**: swaps automatically by query type — map (Deck.gl/MapLibre, KDE heatmap + FIR points) for geospatial, force-directed network graph (Sigma.js/Cytoscape) for relationships, Sankey for financial trails, ECharts trend lines with confidence bands for forecasts. Each transition uses a soft cross-fade/morph, not a hard cut.
- **Right — Case/evidence rail**: current FIR/person always visible; every citation chip (`[FIR-1234]`, `[Community 47]`) opens here as a floating glass drawer.

**Reasoning Trace panel** (expandable, off by default): renders the LangGraph agent trace in plain language — *"Orchestrator → HippoRAG retrieval (0.4s) → ToG deep-dive (low confidence) → Evidence Evaluator: 3 corroborating records → Synthesis."* Makes explainability visible, not just logged. Likely the strongest 30-second differentiation moment.

**Color language**: one consistent severity/threat palette (soft neon amber/rose accents on dark glass, used sparingly) across map, graph nodes, citation chips, and Sankey flows — reads as one coherent instrument, not stitched-together widgets.

**Investigation Copilot workspace**: separate view — case file panel, drag-and-drop evidence board, auto-generated timeline, "these cases may be linked" suggestions, one-click charge-sheet-support report generation. Same glass-panel language, denser information layout for working investigators.

**PDF export**: headless-Chrome render of conversation + charts, KSP letterhead.

---

## Layer 10: Responsible AI & Fairness

Predictive policing has a documented history of laundering historical policing bias (over-policing → more recorded crime → "predicted" crime in the same area) into an apparently-objective score. A government panel evaluating a system meant to influence real policing will expect this addressed.

- **No protected/proxy attributes** (caste, religion, or direct proxies) as model features
- **Aequitas bias audit** (Saleiro et al. 2018, Univ. of Chicago Center for Data Science & Public Policy — the standard toolkit for auditing criminal-justice risk tools, applied publicly to COMPAS): run disparate-impact, FPR/FNR-parity, and other Aequitas metrics across demographic/geographic subgroups on the risk and recidivism models, and show the audit report in the pitch. Naming a specific, real, criminal-justice-purpose-built audit methodology is far more credible than a generic "we care about fairness" slide.
- **Human-in-the-loop by design** — every prediction is decision-support only, never an automated trigger
- **Explicit uncertainty communication** — confidence intervals, SHAP explanations, UI distinguishes "the model suggests" from "the record shows"

---

## Technology Reference

| Component | Technology | Notes |
|---|---|---|
| Knowledge Graph | Neo4j Community + GDS | Single instance sufficient |
| Relational + Geospatial | PostgreSQL + PostGIS | FIR/person/socioeconomic + spatial |
| Vector Store | Qdrant or pgvector | HippoRAG index lives here |
| Agent Orchestration | LangGraph | Stateful graph, conditional edges, verification loop |
| LLM | Claude / GPT-4o | Structured outputs, evidence synthesis |
| Graph Reasoning | HippoRAG (personalized PageRank) + Think-on-Graph (beam search) | Published methods, not ad hoc RAG |
| Kannada NLP | AI4Bharat (IndicNER, IndicTrans2, IndicXlit, IndicTTS) | Self-hosted |
| Kannada ASR | Vakyansh | Self-hosted |
| Entity Resolution | Fellegi-Sunter probabilistic linkage | Solves real name/alias duplication |
| Forecasting | Prophet + MinT reconciliation | Coherent multi-level forecasts |
| Risk/Recidivism | XGBoost+SHAP, LightGBM, Isolation Forest | Explainable per-prediction |
| Causal Inference | DoWhy | Confounder-adjusted socioeconomic claims |
| Financial Crime | Rule-based structuring detector + heterogeneous/temporal GNN | Explainable baseline + SOTA pattern catch |
| Fairness Audit | Aequitas | Criminal-justice-purpose-built toolkit |
| Spatial Viz | Deck.gl + MapLibre | Self-hosted OSM tiles |
| Network Viz | Sigma.js / Cytoscape.js | Force-directed |
| Charts | Apache ECharts | Trend lines, Sankey |
| API | FastAPI, single service | Async, SSE/WebSocket |
| Auth | JWT + in-process policy module | Same guarantees as Keycloak+OPA, no extra infra |
| PDF Export | Puppeteer | Headless Chrome |
| Data Generation | Faker/Mimesis + real NCRB/Census/NSSO/KA-GIS | Synthetic crime on real ground truth |

**Not built** (described only, Appendix A): Kafka, Flink, Iceberg/MinIO, Kubernetes/Helm/ArgoCD, Keycloak, OPA, Kong, MLflow, Airflow, separate TimescaleDB, Trino/DuckDB.

---

## Appendix A: Production Scaling Path (describe, don't build)

- Real-time CCTNS ingestion → Kafka topics per event type → Flink for enrichment/entity-resolution/graph-edge-extraction
- Iceberg/MinIO lakehouse once volume and audit/time-travel needs exceed Postgres
- Keycloak for HR-federated identity, OPA/Rego once the policy set outgrows a Python module, Kong once there are multiple client apps
- Kubernetes + GitOps once there's a real multi-environment deployment lifecycle
- MLflow registry once model/version count outgrows ad hoc FastAPI endpoints
- Spatio-temporal GNN forecasting (ST-GNN / mixture-of-graph-experts literature) as a research-grade upgrade path beyond Prophet+MinT, once historical volume justifies the training cost

---

## Repository Structure

Repo: `github.com/baveshraam/Veritas` (Vercel project `veritas` — deploy target for `apps/web`).

Monorepo, 5 folders, one per concurrent work track. Each folder has its own dependency manifest and its own `README.md` with the full spec for that folder — cross-folder coordination happens through documented contracts (schemas, typed function signatures), never through shared files, so parallel pushes don't collide.

| Folder | Track | Root doc layers owned |
|---|---|---|
| `apps/web/` | Frontend — Command Console UI | §9 |
| `apps/api/` | Backend platform — FastAPI, auth, policy, audit, session transport | §7, §8 |
| `packages/rag_agent/` | RAG / graph reasoning — LangGraph, HippoRAG, ToG, evidence chain, Investigation Copilot | §2 (reasoning), §3, §5 |
| `packages/ml_models/` | ML — predictive analytics, financial-crime GNN, entity resolution, fairness audit | §4, §2.4 (models), §6.2, §10 |
| `data/` | Data engineering — schemas, synthetic data pipeline, vector index, Kannada NLP/ASR/TTS | §1, §2 (schema), §6 |

`apps/api` is still the one deployable service (Layer 7) — `packages/rag_agent` and `packages/ml_models` are Python packages it imports, not separately deployed microservices. The folder split is for parallel *development*, not a change to the runtime architecture.

**One deliberate exception**: `packages/policy` is a 6th, small shared package (RBAC rule definitions) imported by both `apps/api` and `packages/rag_agent` — not a 6th track, and not owned by one person. RBAC is cross-cutting by nature: duplicating the rules risks drift, and it can't be enforced entirely post-hoc (see Layer 8), so it can't be cleanly isolated inside a single folder the way everything else is. Whoever touches auth/RBAC on either side edits it.

---

