# Veritas — KSP Datathon 2026, Challenge 01

**The single source of truth for this repo.** There are no other design docs. Keep this
current; append deltas to the changelog rather than rewriting history.

A conversational crime-intelligence platform for the Karnataka State Police: ask a question
in English or Kannada, get an answer where every claim traces to a specific record.

- **Repo**: `github.com/baveshraam/Veritas`
- **Runs on**: Zoho Catalyst (project `Veritas`, id `52852000000013048`, org `60077763394`)
- **Schema**: the organizers' `Police_FIR_ER_Diagram.pdf`, reproduced verbatim
- **Tests**: `python -m pytest` — 188 green, no database or Docker required

**Ground rule for this document**: choices are justified by "is this the best solution to the
actual problem", never by "what was fast to build". Where something is simple, that is
because the problem has no complexity to justify — not because the complex version was too
much work.

---

## 0. The two constraints that shaped everything

### The competition rule
Deployment on Catalyst is mandatory, and using a third-party service **where a Catalyst
equivalent exists** can invalidate the submission. The organizers further clarified: *where
no listed Catalyst service exists for a capability, an external or self-hosted alternative is
permitted.*

The rule targets **services**, not **libraries**. NetworkX, LangGraph, XGBoost, DoWhy,
faster-whisper and NLLB all run *inside our own AppSail container*, on Catalyst compute. They
are the product, not the platform. What had to go were the genuinely external *services*:
PostgreSQL, PostGIS, Neo4j, pgvector, the Gemini API, and any runtime download from
huggingface.co.

### The ER has no person
This is the single most important fact about the data, and most of the system is built around
it.

The organizers' schema has an `Accused` table. Each row belongs to **exactly one case**, and
its `PersonID` column is a *per-case sort label* — "A1", "A2" — not an identity. Nothing in
the schema says the "Ramesh Gowda" on case 412 and the "Ramesha Gouda" on case 908 are the
same man. On the raw ER:

- every offender is a first-timer, so *"does he have priors?"* has no answer;
- nobody co-offends with anybody, so there is no criminal network to analyse;
- a bank account cannot belong to a human, so the money-laundering layer is meaningless;
- a "person" endpoint could only ever show one case.

So identity has to be **inferred**, and that inference (Fellegi-Sunter, `packages/ml_models`)
is the load-bearing centrepiece of the platform rather than a nice-to-have. It runs as a
batch pass immediately after the records load, and *everything* downstream depends on it. It
is the answer to "what did you build that a team who just wrote SQL against the ER could
not?".

Measured: **F1 0.989** (precision 0.997, recall 0.981) against the generator's answer key.

---

## 1. Architecture

```
   KSP OFFICERS (browser)
            │
   COMMAND CONSOLE — glassmorphic spatial UI (chat / map+graph+Sankey / evidence rail)
   Catalyst Web Client Hosting (Slate) · Next.js `output: "export"`
            │
   FASTAPI — Catalyst AppSail, custom OCI runtime
   auth (Catalyst Authentication) · policy · SSE + WebSocket · audit hash chain
            │
   LANGGRAPH MULTI-AGENT ENGINE
   Orchestrator → HippoRAG retrieval → [Think-on-Graph deep-dive if confidence low] →
   specialist agents → CRAG-style evidence evaluator → synthesis
            │
   ┌────────┴────────┬──────────────┬─────────────┬──────────────┐
 DATA STORE      STRATUS         CACHE        QUICKML          CRON
 (37 ZCQL        (graph blob +   (session     (GLM-4.7-Flash)  (refresh 6h,
  tables)         vector index)   focus)                        audit-verify 12h)
            │
   IN-PROCESS: NetworkX graph · numpy vector search · XGBoost / LightGBM / Prophet / DoWhy
               faster-whisper + NLLB (Kannada) · Fellegi-Sunter
            │
   SYNTHETIC DATA GENERATOR — Faker + real NCRB / Census 2011 / KA-GIS ground truth
```

**The order of the pipeline is the architecture:**

```
schema → real Census ground truth → generate → load records
       → RESOLVE IDENTITIES → financial layer → graph edges → graph algorithms → embeddings
```

Each step genuinely depends on the last. Identity cannot move.

---

## 2. Catalyst services in use

| Component | Catalyst service | Replaced | Notes |
|---|---|---|---|
| API runtime | **AppSail** (custom OCI) | self-hosted uvicorn | Root `Dockerfile`; FastAPI runs as-is |
| Console hosting | **Web Client Hosting** (Slate) | Next.js dev server | `output: "export"`; every component was already `"use client"` |
| Identity | **Catalyst Authentication** | self-signed JWT | Catalyst says *who*; the `Employee` record still says *what they may see* |
| Relational store | **Data Store** (ZCQL) | PostgreSQL + PostGIS | 37 tables — §3 |
| Object storage | **Stratus** | filesystem | Graph pickle + vector index |
| Cache | **Cache** | none | Session focus, read on every turn |
| LLM | **QuickML LLM Serving** | Google Gemini | GLM-4.7-Flash. No API key in the image |
| Scheduling | **Cron** | none | `veritas_refresh` (6h), `veritas_audit_verify` (12h) |
| PDF export | **SmartBrowz** | headless Chrome | Local renderer demoted to offline fallback |

### The four documented exceptions
Each is permitted under the organizers' clarification. These are **absences, not
preferences** — for each, no Catalyst service exists.

| Capability | Kept on | Why no Catalyst service exists |
|---|---|---|
| Kannada ASR / TTS / translation | faster-whisper, NLLB-200 (in-container) | Zia has **no** speech-to-text, **no** text-to-speech and **no** translation service. Its catalog is Face Analytics, OCR, Identity Scanner, Image Moderation, Object Recognition, Barcode, Text Analytics. Swapping would have *deleted* working Kannada voice input |
| Vector index | numpy over a Stratus blob | QuickML's RAG is a managed upload-documents pipeline — no arbitrary-embedding store, no custom retrieval hook. HippoRAG's Personalized-PageRank seeding cannot run inside it |
| Knowledge graph | NetworkX over `vx_graph_edge` | No Catalyst service is a graph database. Every GDS algorithm was ported exactly |
| Audit-log immutability | SHA-256 hash chain | Data Store has no `RULE` and no triggers. App-layer append-only, enforced by the same code that could bypass it, is strictly weaker — so it was rebuilt in the data instead (§7) |

**Not built** (described only — Appendix A): Kafka, Flink, Iceberg, Kubernetes, Keycloak,
OPA, Kong, MLflow, Airflow.

---

## 3. Data foundation — `data/`

### The schema — `data/data/schema.py`
One Python file defines all 37 tables and generates both backends.

**27 tables are the organizers' ER, verbatim** — their names, their columns, their spelling
(`caste_master_id`, `csdate`, `CrimeHeadName`, `inv_arrestsurrenderaccused`). Do not
"improve" them: conformance is a hard requirement, and `data/tests/test_schema.py` fails
loudly if anyone tries.

**10 tables are ours**, all prefixed `vx_` so nobody can ever mistake an addition for the
organizers' schema:

| Table | What it is |
|---|---|
| `vx_person` | The people reconstructed from `Accused` rows. The ER has none |
| `vx_accused_identity` | `AccusedMasterID` → `PersonUID`, with match confidence |
| `vx_officer_identity` | Email → `EmployeeID`. Catalyst Auth identifies by email; the ER's `Employee` has no email column, and we do not add one to it |
| `vx_account`, `vx_txn` | The financial-crime layer |
| `vx_graph_edge` | The traversal projection of the records |
| `vx_session`, `vx_conversation_turn` | Multi-turn memory and PDF export |
| `vx_audit_log` | The tamper-evident trail (§7) |
| `vx_district_socioeconomic` | Real Census 2011 ground truth |

### Provisioning — `data/data/provision.py`
Data Store has no `CREATE TABLE` in any documented route: the console is the only way in, and
IaC import *forks a new project*, which would have orphaned the AppSail and QuickML
deployments already living in this one. But the Admin API the console itself calls is
reachable:

```
POST /baas/v1/project/{id}/table               {"table_name": "X"}   -> table_id
POST /baas/v1/project/{id}/table/{tid}/column  [ {column spec}, … ]
```

So the 37 tables are created from `schema.py` in one idempotent command, with no clicking:

```bash
CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python -m data.provision
```

`scripts/catalyst-token.js` mints a token from the `catalyst login` the CLI already stores,
so provisioning needs no OAuth client of its own.

### The client — `data/data/ds.py`
`query()` / `insert()` / `update()` / `execute()` are the only ways into the database. Two
backends, one query language:

- **catalyst** — the real Data Store, via the SDK. Inside AppSail the SDK authenticates as
  the app itself: no keys, no secrets, nothing to leak.
- **sqlite** — the *same ZCQL strings* against a local file. Used by the tests, the
  generator, and offline development.

**The second backend is not a mock.** ZCQL is a subset of SQL, so SQLite executes exactly the
query strings the deployed service sends to Data Store. A query that passes the test suite is
a query Data Store will accept. This is why the RBAC rules — the part a government panel will
actually poke at — now run on every commit instead of being skipped for want of a database.

Three Data Store facts every caller is protected from:

- **A SELECT returns at most 300 rows.** `query()` pages transparently.
- **There are no bind parameters.** A query is a string, so `_lit()` is the single injection
  boundary in the system — and it is tested as one.
- **ZCQL rejects double-quoted identifiers**, which SQLite requires (the ER has tables named
  `Rank` and `Section` — both SQL keywords). Callers write the portable quoted form and
  `unquote_identifiers()` strips them on the way out to Catalyst. This is the *only* genuine
  dialect difference between the two backends, and it is worth naming because it was invisible
  from the test suite: SQLite accepted every quoted query, so the whole suite passed while the
  live service would have answered `No such Table with the given name exists` to every single
  request. It was caught by driving the real Data Store, which is the argument for doing that
  before the demo rather than during it.
- **No `UPSERT`, no `date_trunc`, no CTE, no correlated subquery, at most 4 JOINs.**
  Aggregation that cannot be expressed server-side happens in Python
  (`data/data/queries.py`). At tens of thousands of rows, that is the same answer.

### The generator — `data/data/generator/`
Crime records are synthetic (no real FIR data exists for us) but they sit on **real ground
truth**: IPC-section distributions weighted by published NCRB Karnataka statistics, real
Census 2011 district socioeconomics, real KA-GIS boundaries.

Four properties are load-bearing. Each was a real bug, and in each case a model found it by
correctly learning that there was no signal to find:

1. **Incidents cluster around activity centres**, not uniformly within a district. Uniform
   placement leaves KDE/DBSCAN no hotspot to find, and the model honestly reports none.
2. **Accused are drawn by preferential attachment on priors, in chronological order.**
   Uniform sampling means a prior record predicts nothing, and the recidivism model correctly
   learns there is no signal.
3. **Offenders form crews.** Drawing each co-accused independently makes co-offending a
   *random graph*, and a random graph has no community structure — Louvain duly put 254 of
   255 people into one community. Real offenders reoffend with the people they already
   offended with, so each additional accused is weighted towards the lead's known associates.
   This is precisely what Louvain exists to recover, and it now finds 12 communities of
   realistic size.
4. **Names drift.** 35% of accused rows are recorded under a romanisation variant. Not
   decoration — it is the problem entity resolution exists to solve.

```bash
python -m data.generator.run --cases 10000
```

---

## 4. Knowledge graph — `data/data/graph.py`, `data/data/gds.py`

Neo4j is gone; no Catalyst service is a graph database. The graph is `vx_graph_edge`, a flat
edge table, materialised into NetworkX on demand.

Node ids carry their own type: `person:412`, `case:1043`, `acct:77`, `txn:9001`, `loc:Kolar`
— one varchar column instead of an id plus a label column.

**Person nodes are resolved `PersonUID`s, not `Accused` rows.** That is what makes a
co-offending graph exist at all.

| Edge | Direction |
|---|---|
| `ACCUSED_IN` (person → case) | symmetric |
| `CO_ACCUSED_WITH` (person ↔ person, weight = shared cases) | symmetric |
| `OCCURRED_AT` (case → location) | symmetric |
| `OWNS_ACCOUNT` (person → account) | symmetric |
| `INVOLVED_IN`, `LINKED_TO` | symmetric |
| `TRANSFERRED_TO` (account → account) | **directed** |

`TRANSFERRED_TO` is deliberately *not* symmetric. Money moves one way, and reversing it would
invent a payment that never happened.

### Algorithms — every GDS procedure ported exactly
| Neo4j GDS | NetworkX |
|---|---|
| `gds.pageRank.write` | `nx.pagerank` |
| `gds.louvain.write` | `nx.community.louvain_communities` |
| `gds.betweenness.write` | `nx.betweenness_centrality` (pivot-sampled — Brandes & Pich) |
| `gds.pageRank(sourceNodes=…)` | `nx.pagerank(personalization=…)` ← this *is* HippoRAG |

**They run on the co-offending projection, not the whole graph.** Over the whole graph every
case joins to its district, so `loc:Bengaluru Urban` is a hub that transitively connects every
offender in the state — and Louvain correctly puts them all in one community. That is a true
statement about the graph and a useless one about crime. GDS called this a graph projection;
same thing, same reason.

### There are no gangs
The ER records no gang, so we do not invent one. Organised-crime grouping is *derived*, by
Louvain over co-offending, and labelled honestly as what it is — `"Community 47"`, not
`"the Chaddi Gang"`. That is also the stronger claim: the grouping is evidence *from* the
record layer, not an input to it. (The NER has no `GANG` label, for the same reason.)

### Honest ceiling
`load_graph()` pulls the whole graph into memory — ~24k nodes / 136k edges, tens of MB, well
under a second. That is the right trade: Neo4j's real advantage is traversal at a scale this
dataset does not have. On Catalyst the generator pickles the built graph into **Stratus**, so
a cold container reads one object instead of paginating 136k edges through ZCQL's 300-row
cap. `vx_graph_edge` stays the record of truth; Stratus is a cache, and a miss costs latency,
never correctness.

---

## 5. Reasoning engine — `packages/rag_agent/`

LangGraph. Decompose → plan → retrieve across graph / vector / relational → synthesise →
verify → answer with a citation chain.

### Retrieval — two published methods, not ad-hoc embedding search
- **HippoRAG** (Gutiérrez et al., NeurIPS 2024): extract the query's entities, seed
  **Personalized PageRank** from them, read off the highest-scoring nodes. One graph pass
  gives multi-hop retrieval — no iterative LLM-in-the-loop, which is where the 10–20× cost
  saving over agentic retrieval comes from.
- **Think-on-Graph** (Sun et al., ICLR 2024): for deep multi-hop questions, beam-search
  entity/relation paths over the graph. Produces a *traceable reasoning path*, not just an
  answer. Used when HippoRAG's confidence is low.

### Verification — CRAG-style evaluator
A relevance/confidence evaluator scores each retrieval batch (Corrective-RAG, Yan et al.
2024) and triggers one of: **accept** → **widen and retry** → **explicitly state "not found in
the available records"**. It never fabricates on empty evidence. This is the strongest
trustworthy-for-law-enforcement property in the system, and it is a named, published pattern
rather than an improvised safeguard.

### Agents
Orchestrator · HippoRAG/ToG retrieval · SQL Agent (templates) · Graph Agent · Vector Agent
(hybrid dense + lexical) · Prediction Agent · Evidence Synthesis · Translation · Voice.

**There is no LLM text-to-SQL or text-to-Cypher fallback, and that is not a gap left by the
migration.** With Neo4j gone there is no Cypher to generate. And ZCQL has no bind parameters,
so a model-authored query against an evidence store would be the one place in the system where
user text reaches the database uninterpolated. The long tail those generators served is now
served by Think-on-Graph, which *reasons over* the graph instead of writing code against it.

### The LLM is not what makes an answer true
`rag_agent/llm.py` — QuickML LLM Serving, GLM-4.7-Flash. Inside AppSail the SDK authenticates
as the app, so **there is no API key in the image**.

Every provider failure — quota, network, 5xx, bad credentials — degrades into one signal:
`generate()` raises `LLMUnavailable`, `generate_json()` returns `{}`, and the deterministic
paths (intent templates + extractive synthesis) take over. Those paths produce grounded, cited
answers on their own. **The LLM makes them fluent; it never makes them true.** It also never
sees Kannada: a Kannada query is translated to English *inside our own container* before the
model is called, and the answer is translated back.

### Investigation Copilot
Given an open case: a chronological timeline, the top-5 similar past cases with their
outcomes, ranked investigative leads, and a paste-ready case-diary paragraph.

Leads are **direct co-accused only**. At the 4-hop policy cap this would name most of the
connected component ("857 associates") — true, and useless. A lead has to be actionable this
week.

---

## 6. Predictive analytics — `packages/ml_models/`

- **Fellegi-Sunter** probabilistic record linkage (1969) — §0. The centrepiece.
- **KDE** (Gaussian, Scott's rule) + **DBSCAN** (`eps=500m, min_samples=10`) — hotspots.
  These never used PostGIS *functions*, only its storage, so dropping PostGIS changed no
  method.
- **Prophet + MinT reconciliation** (Wickramasuriya, Athanasopoulos & Hyndman, 2019, *JASA*) —
  a district's forecast always equals the coherent sum of its stations. Statistically optimal,
  not merely "close enough".
- **XGBoost + SHAP** risk scoring; **LightGBM** 180-day recidivism, calibrated.
- **Isolation Forest** district spike alerts → the `/alerts` WebSocket.
- **DoWhy** causal layer over real Census 2011 data.
- **GNN** suspicious-subgraph AML classifier, alongside the explainable rule-based structuring
  detector — the GNN catches coordinated multi-account layering the rule structurally cannot
  see; the rule is what a court can audit line by line.
- **Aequitas** bias audit (Saleiro et al. 2018) — the toolkit built for criminal-justice risk
  tools and applied publicly to COMPAS.

### Two rules that are enforced, not merely stated
**Detector output is never the generator's input.** `vx_txn.FlaggedSuspicious` is written by
the models. The injected laundering patterns — the training ground truth — are written to a
*file*, never to the table the detectors read. A classifier trained on a label sitting in the
column it scores is measuring nothing.

**No protected attribute reaches a model.** The ER declares `CasteID` and `ReligionID`, so
they are stored — conformance is a hard requirement. **No model reads them.** Storing is not
scoring. Gender is kept only as a *subgroup label*, so the Aequitas audit has an axis to test
disparate impact against. Both rules have tests.

---

## 7. Security & audit — `apps/api/`, `packages/policy/`

**Auth.** Catalyst Authentication in every deployed environment; a self-signed JWT is the
local path, and it refuses to run on a default secret outside dev mode. Catalyst says *who
signed in*; the ER's `Employee` row stays authoritative for **role and station**, which is
what policy reads. A Catalyst account with no `Employee` row is not an officer.

**Policy** (`packages/policy`) is enforced in **two places, not one**:

- `apps/api` middleware, for structured responses — post-hoc masking is fine when the shape is
  known.
- `packages/rag_agent`, at *query-construction time*, for depth-capping and anything feeding a
  free-text answer. **You cannot un-traverse a graph, and you cannot reliably redact a name
  out of generated prose.** So an IO's station filter is a `WHERE` clause *inside* the query,
  and the role's traversal depth cap bounds the walk *before* it runs.

**The audit chain.** Postgres made the log physically immutable with
`RULE … DO INSTEAD NOTHING`. Data Store has **no rules and no triggers**, and app-layer
"append-only" enforced by the same code that could bypass it is not a guarantee at all.

So immutability moved into the data. Every row carries the hash of the row before it:

```
ChainHash = sha256(PrevHash ‖ ResponseHash)
```

Editing or deleting any row breaks every hash after it, and repairing that means rewriting the
entire tail of the log. The database cannot make tampering *impossible*; the chain makes it
**undeniable**. `verify_chain()` is what an auditor runs — and a Catalyst Cron job runs it
every 12 hours, because a tamper check nobody runs is not a tamper check.

---

## 8. Console — `apps/web/`

Futuristic minimalist: glassmorphism over a deep gradient mesh, rendered in **dark glass** so
it stays legible for dense command-console work. Three floating panes:

- **Left — chat**: streaming SSE, push-to-talk with a live waveform, EN/KN toggle.
- **Centre — context view**: swaps by query type — map (MapLibre, KDE heatmap + case points),
  force-directed network graph, Sankey money flow, ECharts forecast bands. Soft cross-fade
  between them, never a hard cut.
- **Right — evidence rail**: every citation chip renders as its 1-based `[index]` and opens
  the matching evidence item as a floating glass drawer.

**Reasoning Trace panel** (expandable, off by default) renders the agent trace in plain
language — *"Orchestrator → HippoRAG retrieval (0.4s) → ToG deep-dive (low confidence) →
Evidence Evaluator: 3 corroborating records → Synthesis."* Explainability made visible rather
than merely logged.

The basemap is a self-drawn dark canvas, **not a tile service** — FIR coordinates must never
leave the network inside a third-party tile request URL.

---

## 9. Responsible AI

Predictive policing has a documented history of laundering historical bias (over-policing →
more recorded crime → "predicted" crime in the same area) into an apparently-objective score.
A panel evaluating a system meant to influence real policing will expect this addressed.

- **No protected or proxy attributes as model features** (§6).
- **Aequitas** disparate-impact and FPR/FNR-parity metrics across demographic **and
  geographic** subgroups. Geography is the axis that catches the over-policing feedback loop,
  and it is the one a naive audit omits.
- **Human-in-the-loop by design.** Every prediction is decision-support. Nothing is an
  automated trigger.
- **Explicit uncertainty.** Confidence intervals, SHAP explanations, and a UI that
  distinguishes *"the model suggests"* from *"the record shows"*.
- The causal layer **names its unmeasured confounder** — police strength is not published per
  district in India — rather than adjusting for a fabricated column.

---

## 10. Repository

| Folder | Owns |
|---|---|
| `apps/web/` | Command Console UI (§8) |
| `apps/api/` | FastAPI, auth, policy enforcement, transport, audit (§7) |
| `packages/rag_agent/` | LangGraph, HippoRAG, ToG, evidence chain, Copilot (§5) |
| `packages/ml_models/` | Predictive analytics, AML, entity resolution, fairness (§6) |
| `packages/policy/` | RBAC rules. Shared, because they are enforced in two places (§7) |
| `data/` | Schema, Data Store client, generator, graph, vectors, Kannada NLP (§3, §4) |

`apps/api` is the one deployable service; the packages are imports it makes, not
microservices.

### Run it
```bash
python -m pytest                                     # 184 tests, no stack needed
cd data && python -m data.generator.run --cases 10000
cd apps/api && uvicorn api.main:app --reload
cd apps/web && npm run dev
```

### Deploy it
```bash
CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python -m data.provision
docker build --platform linux/amd64 -t baveshraam/veritas-api:latest . && docker push baveshraam/veritas-api:latest
catalyst deploy
```

---

## Appendix A: production scaling path (describe, don't build)

Real-time CCTNS ingestion → Kafka topics per event type → Flink for enrichment and
entity-resolution. Iceberg/MinIO once volume and time-travel needs exceed the Data Store.
Keycloak for HR-federated identity; OPA/Rego once the policy set outgrows a Python module.
Kubernetes + GitOps once there is a real multi-environment lifecycle. MLflow once model count
outgrows ad-hoc endpoints. Spatio-temporal GNN forecasting beyond Prophet+MinT once historical
volume justifies the training cost.

---

## Changelog

- **v1–v4**: Postgres + PostGIS + Neo4j + pgvector + Gemini, on a schema of our own design.
  Built and integrated end-to-end.
- **v5 (Catalyst migration)**: infrastructure replaced, features and algorithms preserved.
  FastAPI → AppSail; Next.js → Slate; JWT → Catalyst Auth; headless Chrome → SmartBrowz;
  PostGIS deleted (KDE/DBSCAN never used its functions, only its storage); Neo4j + GDS deleted
  → NetworkX over an edge table, every algorithm ported exactly.
- **v6 (this pass) — the organizers' ER, and the last of the third-party services.**
  - **Reshaped the entire schema to the organizers' ER**, verbatim: 27 of their tables plus 10
    `vx_`-prefixed additions. The old self-designed schema is gone.
  - **The ER has no person** (§0). Rebuilt Fellegi-Sunter to *reconstruct* people from
    `Accused` rows — F1 0.989 — and made it a hard dependency of the graph, the financial
    layer, the risk features, and every "does he have priors" answer.
  - **PostgreSQL → Data Store.** Provisioned the 37 tables over the Admin API (IaC forks a new
    project, so it was the wrong tool); ported all ~30 SQL call sites to ZCQL. SQLAlchemy is
    gone from the repo.
  - **pgvector → Stratus + numpy.** Exact brute-force cosine over one blob, with an
    IDF-weighted lexical half so an officer can still find "IPC 457" — which is exactly what
    an investigator types and exactly what a dense model cannot represent.
  - **Gemini → QuickML (GLM-4.7-Flash).** No API key in the image.
  - **Added Cache** (session focus — read on every turn, before the orchestrator can route
    anything) and **Cron** (`veritas_refresh` 6h; `veritas_audit_verify` 12h).
  - **Baked the model weights into the image.** A container that reaches huggingface.co at
    request time is a third-party runtime dependency — and a cold container downloading 2.4GB
    of NLLB is not a slow answer, it is a timeout.
  - **Fixed the co-offending generator.** Accused were drawn independently, making the network
    a random graph with no community structure; Louvain found one community holding 254 of 255
    people. Offenders now form crews, and Louvain finds 12 of realistic size.
  - **Deleted the fabricated gang layer.** The ER records no gang; the community *is* the
    gang, derived and labelled as such.
  - **Rewrote the test suites against the ER + Data Store.** 188 green — and the RBAC rules,
    previously skipped for want of a Postgres stack, now run on every commit.
  - **Seeded the live Data Store** (105k rows) over the Admin API, and found the one thing the
    SQLite backend could not have told us: ZCQL rejects quoted identifiers (§3).
  - **Consolidated every design doc into this file.** `docs/`, the per-folder READMEs, the
    dataset catalog, `docker-compose.yml` and `data/sql/` are deleted.
- **v7 (deployment) — fitting the image through AppSail's bundle sandbox.**
  - **The constraint, measured empirically**: AppSail's bundle creator unpacks the image
    in a ~4.5GB scratch space that must hold the tar *and* its extraction simultaneously,
    so the deployable image ceiling is ~2.2GB. (The app-level `disk` config caps at 1024MB
    and governs runtime writes, not the unpack.) The 9.31GB first image died downloading;
    a 4.66GB rebuild died extracting. Bundle-creator logs via
    `GET .../appsail/{id}/deployment/{depid}/logs`.
  - **The image is 2.23GB** and every subsystem still passes its checks in-container:
    NLLB -> CTranslate2 int8 (600MB replaces a 2.4GB fp32 checkpoint that had been baked in
    *twice*), whisper `base` multilingual for Kannada ASR (via `VERITAS_WHISPER_KN_MODEL`;
    `small` is better and stays the code default for local dev), `xgboost-cpu` instead of
    the CUDA-bundled wheel, and no generator-only deps (geopandas/pyogrio/faker).
  - **torch is not in the deployed image** (800MB serving one detector). The AML GNN
    degrades to `GNNUnavailable` exactly as it does on a too-small graph; the rule-based
    structuring detector - the court-auditable one - is unaffected. The GNN runs anywhere
    torch is installed, including local dev and the demo laptop.
  - **SHAP values now come from xgboost's own `pred_contribs`** (identical TreeSHAP math,
    minus the shap -> numba -> llvmlite chain, ~240MB). `_XGBShap` in `risk/scoring.py`.
  - **Deploys relay through GitHub Actions** (`.github/workflows/relay-deploy.yml`): the
    CLI uploads the image tar from the developer's machine, which cannot beat the signed
    URL's 30-minute TTL on a residential uplink. The runner pulls from Docker Hub and
    uploads datacenter-to-datacenter; the `upsert` callback (with `memory: 2048`, the max
    this org accepts) is then made locally.
- **v8 (going live) — everything empirical about running on Catalyst, learned the hard way.**
  - **LIVE**: API `https://veritas-api-50043864344.development.catalystappsail.in` (health,
    auth, cases, fir, person, copilot, chat all verified); console
    `https://veritas-60077763394.development.catalystserverless.in/app/index.html`.
  - **The SDK's context is per-request headers, not env** (`X-ZC-*`): a bare
    `zcatalyst_sdk.initialize()` raises "Catalyst headers are empty" in AppSail. The API
    middleware captures each request into the SDK (`ds.bind_catalyst_request`); background
    work reuses the captured app.
  - **Live ZCQL refuses JOINs between value-related tables** — every JOIN in the codebase,
    since the ER relates by business key. Reads therefore run on a **local sqlite mirror**
    hydrated from the Data Store once per container (writes: Data Store first, mirror
    second). Bonus: schema-typed hydration killed the whole "live returns '4', sqlite
    returns 4" bug class.
  - **Data Store pagination duplicates one row at a page boundary, even under ORDER BY**
    (measured repeatedly). Paged reads dedupe on ROWID; hydration INSERT OR IGNOREs; and
    this artifact — via the original seeding — is what the 13 phantom "duplicate" rows were.
  - **The SDK JSON-serializes writes**, so datetimes must be Data Store display strings
    (`_sdk_row`); a raw datetime 500'd every audited endpoint while sqlite hid it.
  - **Hybrid deployed auth**: Catalyst session first, signed JWT (VERITAS_JWT_SECRET, set
    via the configuration API) as fallback; SDK exceptions on cookie-less requests now 401.
  - **AppSail env vars, memory (2048 max here) and disk (1024 max) are all settable over
    `POST /appsail/{id}/configuration`** once one deployment has succeeded — nothing was
    console-only in the end, including the VERITAS_JOB_TOKEN cron secret.
  - langgraph needs typing_extensions>=4.13 (`TypedDict(extra_items=...)`) — constraints.txt
    now pins the floor; the old torch resolve had dragged it to 4.12.2, killing /chat.
