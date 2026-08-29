# Veritas — KSP Datathon 2026, Challenge 01

**The source of truth for the architecture and design rationale.** Keep this current;
append deltas to the changelog rather than rewriting history. `docs/WORK_LOG.md` and
`docs/ENGINEERING_BRIEF.md` carry the pass-by-pass operational detail (every defect
found, every live verification, every deploy) at a grain this file deliberately does
not duplicate — this file states what is true now and why; those two state how it got
that way. If a claim here and in `docs/` conflict, re-derive it from the live system
and code rather than trusting either document — both have drifted stale before.

A conversational crime-intelligence platform for the Karnataka State Police: ask a question
in English or Kannada, get an answer where every claim traces to a specific record.

- **Repo**: `github.com/baveshraam/Veritas`
- **Runs on**: Zoho Catalyst (project `Veritas`, id `52852000000013048`, org `60077763394`)
- **Schema**: the organizers' `Police_FIR_ER_Diagram.pdf`, reproduced verbatim
- **Tests**: `python -m pytest` — 602 green (`pytest --collect-only -q` for the current
  count; this line has drifted stale before and is not to be trusted over that), no
  database or Docker required

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
| Object storage | **File Store** | filesystem | Model weights (~760MB, streamed at cold start). *Stratus was the design target for the graph/vector cache, but bucket creation is scope-blocked over the Admin API (console-only); live, the graph and vector index rebuild through the sqlite mirror instead — §8 changelog v8* |
| Cache | **Cache** | none | Session focus, read on every turn |
| LLM | **QuickML LLM Serving** | Google Gemini | GLM-4.7-Flash. No API key in the image |
| Scheduling | **Cron** | none | `veritas_refresh` (6h), `veritas_audit_verify` (12h) |
| PDF export | **SmartBrowz** | headless Chrome | Local renderer demoted to offline fallback |

### The five documented exceptions
Each is permitted under the organizers' clarification. These are **absences, not
preferences** — for each, no Catalyst service exists.

| Capability | Kept on | Why no Catalyst service exists |
|---|---|---|
| Kannada ASR / TTS / translation | faster-whisper, NLLB-200 (in-container) | Zia has **no** speech-to-text, **no** text-to-speech and **no** translation service. Its catalog is Face Analytics, OCR, Identity Scanner, Image Moderation, Object Recognition, Barcode, Text Analytics. Swapping would have *deleted* working Kannada voice input |
| Vector index | numpy over a Stratus blob | QuickML's RAG is a managed upload-documents pipeline — no arbitrary-embedding store, no custom retrieval hook. HippoRAG's Personalized-PageRank seeding cannot run inside it |
| Knowledge graph | NetworkX over `vx_graph_edge` | No Catalyst service is a graph database. Every GDS algorithm was ported exactly |
| Audit-log immutability | SHA-256 hash chain | Data Store has no `RULE` and no triggers. App-layer append-only, enforced by the same code that could bypass it, is strictly weaker — so it was rebuilt in the data instead (§7) |
| Map tiles | OpenFreeMap (`tiles.openfreemap.org`, MapLibre "liberty" style) | No Catalyst service is a map tile provider — the catalog has no mapping capability at all. No API key, no registration, no per-request quota. Only a viewport tile z/x/y crosses the network, never an FIR's exact coordinates (§8) |

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

An investigative intelligence workstation (see v18): a restrained enterprise dark theme,
~90% neutral, hierarchy from layout rather than from cards. A global bar, a persistent
investigation header carrying the workspace tabs, and three hairline-divided columns:

- **Left — copilot**: streaming SSE, push-to-talk with a live waveform, EN/KN toggle. An
  answer renders as a *finding* — the claim with its clickable `[n]` citations, a
  structured module where the result has structure (the strongest connections in a
  network), and a support strip — not as a chat bubble.
- **Centre — workspace**: one primary surface, chosen by the tab in the investigation
  header (Overview · Timeline · Network · Geography · Financial · Board). A new answer
  pulls the workspace to the view it produced; an empty view hands over the exact
  question that fills it. Each carries an analysis header stating the figures the
  visualization contains — *"600 cases located · 4 hotspots · 1.00 peak density"*.
- **Right — evidence**: the sources as a SET first ("Moderate · 5 authoritative records ·
  4 model outputs"), then compact rows. A row opens the **inspector** — the full record,
  its provenance, what its confidence number actually measures, and the query that
  retrieved it — over the workbench, never navigating away from the investigation.

**Provenance is a visual primitive**, and it is the same one on every surface — evidence,
board, timeline, briefing, chart legends: ■ RECORD (stated in the file) · ◆ DERIVED
(inferred by Veritas) · ▲ MODEL (computed). A model estimate must never be able to look
like a record, so it gets its own channel rather than a word inside body text. The three
things `confidence` can mean are named apart for the same reason: **evidence support** ≠
**text match** ≠ **model output**.

**Reasoning Trace panel** (expandable, off by default) renders the agent trace in plain
language — *"Orchestrator → HippoRAG retrieval (0.4s) → ToG deep-dive (low confidence) →
Evidence Evaluator: 3 corroborating records → Synthesis."* Explainability made visible rather
than merely logged. While a turn runs, the same trace drives a four-stage progress readout
(understanding → retrieving → verifying → preparing) instead of a bare spinner.

**Refusal is a designed state**, not an error: a calm amber-ruled panel saying what could
not be established and what that does and does not mean. A transport or engine *failure*
is a separate, genuinely red state — the two must never look alike.

The basemap is a real MapLibre style served by **OpenFreeMap** (`tiles.openfreemap.org`,
OSM-derived, no API key or registration — the fifth documented exception, §2). What crosses
the network is a tile z/x/y for the current viewport, never an FIR's exact coordinates or any
investigative text; a viewport request reveals district-level location at most, which is
already non-sensitive metadata (every FIR's District is a plain ER column). Veritas's own
overlays — FIR points, hotspot density polygons, district reference labels, legend, scale —
render on top, unchanged by the swap.

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
python -m pytest                                     # 189 tests, no stack needed
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
  - **Rewrote the test suites against the ER + Data Store.** 189 green — and the RBAC rules,
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
  - **Weights left the image entirely; the image is now 0.88GB.** The v7 image (2.23GB, weights
    baked in) still died in the bundle sandbox on a bad day — the *real* ceiling is ~1.3GB, not
    2.2GB, because staging adds a fourth copy. So the ~760MB of NLLB + whisper weights moved
    **out of the image into Catalyst File Store** (folder `models`, 8×95MB chunks), streamed and
    spliced into CTranslate2/whisper at cold start (`data/nlp/model_fetch.py`) — never written to
    disk as one tar. The image now carries only code and CPU wheels.
  - **Stratus was the design target for the graph/vector cache but its bucket creation is
    scope-blocked over the Admin API** (`OAUTH_SCOPE_MISMATCH`, console-only). Not needed: File
    Store holds the models and the sqlite mirror serves the graph and vector index (rebuilt from
    `vx_graph_edge` / the embeddings on first read). The Stratus fast path in `graph.py` /
    `vectors.py` stays as code — it simply always misses live and falls back to the mirror.
  - **Live health, verified**: `llm=quickml(glm-4.7-flash) · datastore=catalyst · firs=10000 ·
    graph 16,918n/87,120e · vectors 13,835 docs · cache=catalyst`. All 6 roles resolve; `/chat`
    streams the LangGraph trace; 189 tests green.
- **v9 (the console actually loads) — two build-time bugs that made a healthy stack look dead.**
  The API was live and correct the whole time; the *hosted console* was blank, and both causes
  were baked into the static export rather than being runtime faults.
  - **Catalyst serves the client from `/app/`, not the domain root.** Next's default
    root-relative `/_next/...` asset URLs therefore 404'd — every chunk and the stylesheet. With
    no JS there is no hydration, so the page froze on its prerendered "Loading officers…" shell.
    Fixed with `assetPrefix: "/app"` in `next.config.mjs`. This is invisible locally, where
    `next dev` and `next start` both serve from `/`.
  - **`NEXT_PUBLIC_API_URL` was unset at build time**, so the export fell back to the
    `http://localhost:8000` default and shipped it to users — each visitor's browser called its
    own machine. **The committed default in `next.config.mjs` is now the deployed API URL**, and
    localhost is the opt-in (`.env.local`). A static export resolves env vars at build time with
    no runtime left to correct them, and `.env.*` is gitignored — so a default that is only right
    when someone remembers to set a variable is a bug waiting to recur on the next clean clone.
    A wrong default is invisible in dev and fatal in production; production wins the default.
  - **CORS was already correct** and needed no change; the API had been returning 200 on
    `/health`, `/auth/officers`, `/auth/token`, `/cases` and `/chat` throughout.
  - **Verified live, not assumed**: all 7 referenced assets return 200, and the full console
    flow — officers → token → `/cases` → `/chat` with cited evidence — was driven end to end
    against the deployed URLs.
- **v10 — the console people actually see, and the bug the demo would have hit first.**
  - **The 18-digit FIR number was never recognised.** `sql_agent.fir_by_number()` has always
    taken the 18-digit `CrimeNo` — its docstring says so, it is what the generator writes and
    the case index renders — but the `FIR_LOOKUP` branch only matched the short `0112/2026`
    form. Every query carrying a real FIR number skipped the exact lookup and was answered by
    semantic search. Measured live: *"What is the status of FIR 100222201202600022?"* — a Hurt
    case in Mandya — returned five **cyber-crime cases in Shivamogga**, cited and confident.
    That is precisely what the console's own *Ask about this case* button sends. `FIR_NUMBER_RE`
    now matches both forms, floored at 12 digits so "the last 30 days" and "2026" can never be
    read as a record identifier.
  - **A named FIR that does not exist is now refused.** A record identifier is a yes/no claim
    about one row, and retrieval will always return *something* — the nearest narratives it can
    find, which are records about a different crime. Confidence cannot rescue that case, so the
    evaluator REJECTs on a missed exact lookup (`exact_lookup_missed`). The refusal path was
    working as documented; it simply had no way to know a lookup had missed. **189 → 196 tests.**
  - **Console redesign — "Registry".** Ink ground, brass accent taken from the KSP uniform, IBM
    Plex in three roles (condensed for official labels, sans for prose, mono for record
    identifiers). Fonts resolve at build time into the export, so the page still makes no
    third-party request. Signature element: the **evidence thread** — selecting a citation draws
    a line from the claim to the record it rests on, which is the one argument the console had
    only ever asserted in prose.
  - **Three colour bugs, one category error**: a non-severity dimension borrowing the severity
    ramp. Evidence *confidence* ran through `severityOf()`, so a 100%-confidence record rendered
    in the crimson of a high-risk hotspot — the strongest evidence looked the most alarming.
    Case *status* did the same, making "Under Investigation" read as an alarm. Both now have
    their own scales. The map basemap, network labels, chart axes and the MapLibre zoom control
    were still light-theme; the network labels were near-black on near-black.
  - **Sign-in cannot hang.** The roster request is bounded and every outcome renders something
    actionable; on failure the gate falls back to unverified rank buttons so the console still
    opens. `?as=DSP` signs straight in at a rank, making the RBAC contrast a link.
  - **`scripts/deploy-console.sh`** replaces the copy-paste deploy and asserts the two
    build-time invariants that shipped a blank page in v9: `/app`-prefixed assets, non-localhost
    API URL.
  - **The FIR branch had never executed, so its bugs had never been wrong out loud.** Making it
    reachable immediately raised `KeyError: 'ipc_sections'`: it built its evidence string from
    keys `sql_agent._case()` has never returned (`ipc_sections`, `modus_operandi`) and formatted
    `date_filed` with a date spec, which also breaks because live Data Store returns every
    column as a string. `_fir_content()` now builds from the real keys and routes the date
    through `ds.to_dt()`. Worth recording that the engine behaved correctly while broken — the
    failure surfaced as *"Nothing was answered — no partial or unsourced result is being
    shown"*, not as a half-built citation. **196 → 200 tests.**
  - **Deploys no longer need a `docker push` from a developer machine.** `Dockerfile.overlay` is
    the published base plus the current source tree, and `relay-deploy.yml` builds it *on the
    runner* (the base is public, so the pull needs no credentials), smoke-tests that the app
    imports, and uploads that. This also documents what the root `Dockerfile` no longer does:
    the running image was never built from it — weights moved to File Store and the build was
    patched inside the container to fit the ~1.3GB sandbox. When a `pyproject` changes, the base
    must be rebuilt properly; the overlay is not enough.
  - **Re-confirmed from `CONTEXT.md`, the hard way**: `catalyst deploy --only appsail` hangs
    silently (and defaults to memory=256) — use the raw `upsert`; and a local upload of the tar
    still loses to the signed URL's 30-minute TTL, even at 898MB on this uplink.
  - **Known issue — a clean `docker build -f Dockerfile .` fails** in pip's resolver
    (`ResolutionTooDeep: 200000`) after ~25 minutes. The dependency set has not changed and the
    same Dockerfile built 10 days earlier, so a newly published release widened the search
    space. The fix belongs in `constraints.txt` and is not yet done.
  - **Verified live end to end**: *"What is the status of FIR 100222201202600022?"* now returns
    that FIR (Mandya, PS 2201, Hurt, filed 30 Jun 2026) at confidence 0.97; a nonexistent FIR
    number refuses; RBAC holds (IO 81 cases / 1 station, DSP+ 500 / 76); Kannada round-trips
    (`ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?` → CRIME_SEARCH, 5 citations); map and forecast
    both render.
- **v11 — the map and the forecast died on the shortest question anyone would ask.**
  - **A hotspot or forecast question that names no district raised, and the turn was lost.**
    `_district_code()` falls back to the busiest district when the question names none;
    `crime_counts_by_district()` returned `district_code = str(DistrictID)` — `"5"` — while
    every consumer beneath it parses a code as `int(code[2:])`. So `int('')`, and *"The
    investigation engine failed on this query"*. Measured live: `Show me crime hotspots`,
    `Show hotspots`, `Show me the hotspot map`, `Where are the crime hotspots?`,
    `Forecast crime` and `What are the crime trends?` **all** raised, while *"theft hotspots
    in Bengaluru Urban"* worked — the named path goes through `canonical_code()` and never
    touches the fallback. A demo script written from working examples cannot find this; only
    typing the *lazier* question does. Fixed at the producer — it is the sole caller of that
    field, and everything below it already agreed on `KAnn`. **200 → 201 tests.**
  - **The console was discarding the diagnosis.** The API has always sent `detail` (exception
    type and message) on an `error` frame; `lib/api.ts` threw away everything but `message`,
    so the console reported that something had failed and nothing about what — the one fact
    the officer could already see.
  - **Not a bug, worth knowing before a demo**: `Show me the co-offender network` and
    `Show me the money trail` return zero citations and no visualization. That is the CRAG
    evaluator refusing correctly — neither question names a subject to traverse from, and
    picking one would be invention. Name the person (`Who are the associates of Usha Naika?`
    → 41 nodes, 12 citations) and the graph renders.
  - **Deploy notes that cost time**: the admin API is on the **India** DC
    (`api.catalyst.zoho.in`, not `.com`) and the header is `ENVIRONMENT: Development` —
    `DEVELOPMENT` and `development` are both rejected with `Invalid input value for Env Name`.
  - **Verified live after deploy**, all nine: bare hotspot → map/600 points/9 citations, bare
    forecast → trend/30 points/6 citations, named hotspot, network, refusal, real FIR, Kannada.
    Console redeployed; all 7 assets 200 and the new error handling is in the served bundle.
- **v12 — an overnight pass closing platform-limitation bugs, and correcting a claim v8 got
  wrong about its own image.**
  - **`/alerts` moved off WebSocket to SSE, and now works live.** Prior sessions had verified
    the WebSocket auth fix correct in-process but never live — a real `websocket-client` and
    curl with explicit `Connection: Upgrade`/`Sec-WebSocket-*` headers both got Starlette's own
    404 against the deployed AppSail gateway, while an ordinary REST route on the identical
    domain returned 401 as expected. Rather than keep chasing an unconfirmed gateway question,
    `/alerts` now uses `sse_starlette.EventSourceResponse` over `GET`, the transport `/chat`
    already proves works live on this deployment, authenticated with the same
    `Depends(current_officer)` every other route uses. **Verified live post-deploy**:
    unauthenticated → 401; authenticated → real streaming district anomaly alerts.
  - **v8's "the image now carries only code and CPU wheels" was wrong, and still is.**
    `/health` now reports `model_weights` and `nllb_backend` — not inferred from response
    latency (which is what let this claim go unchecked in the first place), but observed
    directly. Live, post-deploy: `model_weights: "fetched from Catalyst File Store this cold
    start"` (the File Store streaming path genuinely works — it had simply never been wired:
    the AppSail app had no `VERITAS_MODELS_FOLDER_ID`/`_FILE_IDS`/`HF_HOME`, set this pass via
    the configuration API) **and** `nllb_backend: "ctranslate2 (...local/baked directory)"` —
    the image still bakes in a converted NLLB CTranslate2 directory at
    `/opt/models/nllb-ct2`. The File Store copy (a raw Hugging Face hub cache, confirmed by
    downloading and inspecting a chunk directly) is real and now fetched successfully, but
    currently redundant for translation, since `translate.py` prefers the baked CTranslate2
    directory when present. Left as-is rather than rebuilding the base image to remove it: the
    baked path is faster (CTranslate2 vs. a raw transformers load) and working well — a round
    trip that measured 13.4s in the v11-era audit measured 4.3s after this pass, partly from
    this fast backend and partly from the warm-up fix below. Correcting the record, not the
    architecture.
  - **A cold NLLB/whisper load is ~20s of weight loading — profiled directly, not guessed.**
    Two warm calls on the same process, immediately after, were 0.8-1.4s each. Nothing paid
    that cost proactively, so it landed on whichever officer's Kannada query happened to be
    first after a container start — indistinguishable from a hang at 20s.
    `translate.warm()`/`speech.warm()` now run from the same background thread that already
    fetches the Data Store mirror and File Store weights on startup. A separate, larger cost —
    CPU-bound autoregressive generation time scaling with output length, measured at 10.7s for
    translating one multi-sentence answer even on an already-warm model — is an inherent
    property of running NLLB on CPU, not a bug this fix (or any code change short of a
    smaller/faster model) touches.
  - **DoWhy's deployability was measured, not re-asserted.** Installed `dowhy==0.14` into an
    isolated venv and sized its dependency closure directly: genuinely new weight (excluding
    numpy/scipy/pandas/sklearn/networkx, already present) is ≈405MB — dominated by
    `llvmlite`+`numba` (≈149MB, the same dependency class the v7 changelog already removed
    once, when SHAP's numba chain cost ≈240MB and was replaced with xgboost's own
    `pred_contribs`), plus `cvxpy`, `statsmodels`, `sympy`, and (surprisingly, with no
    "plotting" extra requested) `matplotlib`. Against the current 0.88GB image and the
    empirically measured ~1.3GB bundle-sandbox ceiling, that lands at ≈1.28GB — inside the
    ceiling on paper, with essentially no margin against a limit that has already killed two
    prior deploys outright. Not attempted live: gambling a working, verified deployment to "see
    if it fits" is exactly the trial-and-error this project's own rules exclude. `dowhy` stays
    out of the image; the honest decline (v6's evaluator fix) remains correct.
  - **QuickML's request failure narrowed to a named, documented-elsewhere requirement.**
    Checked current Zoho documentation directly: QuickML's sibling "pipeline endpoints" REST
    surface documents a required per-endpoint `X-QUICKML-ENDPOINT-KEY` header, obtained only
    from that model's own console popup — the LLM Serving invoke contract itself is not
    published anywhere reachable from here (checked the dedicated docs pages and the
    machine-readable `llms-full.md` dump). `QUICKML_ENDPOINT` has no recorded provenance as
    having been copied from that popup, and the live `PATTERN_NOT_MATCHED`/"zoho-inputstream"
    gateway error is consistent with an unrecognised route, which is what a guessed URL with no
    key produces. `llm.py` now sends the header when `QUICKML_ENDPOINT_KEY` is configured —
    nothing fabricated, effective the moment someone copies the real key from the console.
  - **PDF export's remaining identity question was tested, not left presumed.** Added
    `_switch_user("admin")` before `smart_browz()` — the exact fix that resolved the identical
    `INVALID_ID`/"No such User" failure class for QuickML (v11's BUG-021). Live-tested
    post-deploy: the identical error persists byte-for-byte. This rules the hypothesis out
    rather than leaving it assumed correct — Data Store/Cache/Graph calls already succeed under
    that same admin scope, so the token itself is accepted; SmartBrowz's API layer appears to
    need a genuine Catalyst User Management identity distinct from any service-token scope,
    reachable only through an interactive Catalyst Authentication sign-in this environment has
    no browser to drive.
  - **BUG-019 fixed**: keyword intent matching used a bare substring check, so `"fir" in
    "firs"` routed `"show me murder firs"` to `FIR_LOOKUP`. Word-boundary matching now, per
    keyword, compiled once.
  - **Both Catalyst Cron jobs had never once succeeded since being created (Jul 13, 2026) —
    `success_count: 0`, `failure_count: 20`, and both disabled.** Listed them directly over the
    Admin API rather than continuing to leave "does Cron actually fire on schedule" unobserved
    (flagged as DEP-12 in the QA matrix since BUG-024). Two stacked causes: the configured
    `job_meta.url` used the **org id** (`60077763394`) instead of the AppSail app's own id
    (`50043864344`) — likely never resolved to the deployed app at all — and, after fixing
    that, the configured `X-Veritas-Job-Token` header turned out to predate the current
    `VERITAS_JOB_TOKEN` and no longer matched (401 "Bad job token"). Both jobs corrected via
    `PUT /project/{id}/cron/{jobId}` and re-enabled; both endpoints then called directly with
    the corrected URL+token and returned real success (`audit-verify`: chain intact;
    `refresh`: started). `veritas_audit_verify` is the tamper-evidence claim's own enforcement
    — "a tamper check nobody runs is not a tamper check" — and had been running zero times in
    production.
- **v13 (North Star hardening pass) — a 23-section re-audit, and the one place v12's own
  "fixed" claim hadn't actually held.**
  - **`veritas_audit_verify`'s Cron job was still failing every unattended fire after
    v12's fix.** Listing the live job directly (rather than trusting the prior pass's own
    "FIXED, verified live") showed `success_count: 0, failure_count: 21` — one MORE
    failure than v12 had already logged — while `veritas_refresh`'s sibling job had a
    real unattended success (`0→1`). Root cause: `/jobs/audit-verify` ran
    `verify_chain()` — a `ds.query()` — synchronously, which is exactly the call that
    pays the ~23s cold-container mirror-hydration cost (BUG-001), inside a request Cron
    abandons long before that; `/jobs/refresh` never touches the data layer before
    responding, which is why it alone survived a cold fire. Fixed with the identical
    background-thread pattern `/jobs/refresh` already uses, plus a `sync=true` escape
    hatch that keeps the original inline `{"intact": ...}` response for a human running
    the check by hand — the mode every prior live-verification pass in this document
    used, which is exactly why this had stayed invisible: manual curls always hit an
    already-warm container. 5 new tests. Deployed (`52852000000316042`) and
    live-verified: default call returns in 0.2s against a freshly-deployed container;
    `sync=true` still returns the real result. Logged as BUG-027.
  - **A real headless-Chrome/CDP session** (the console-verification technique from
    2026-07-26, not used with actual browser tooling in several intervening sessions)
    moved 10 UI rows from PARTIAL/UNKNOWN to VERIFIED: the EN/KN toggle, citation-chip
    click, the evidence-thread line draw, reasoning-trace expand, the full Copilot
    overlay (timeline/leads/similar-cases/diary), Copy-to-clipboard, case-explorer
    search, "Ask about this case" per card, and Export PDF's *enabled* state (previously
    only its disabled state had been driven).
  - **Found live, during that same session: Copilot leads name a person by
    `vx_person.CanonicalName` ("Soom Nadkarni") while the same case's own accused list
    shows the as-filed `Accused.AccusedName` ("Suma Nadkarni") for the identical
    `PersonUID`, with nothing on screen linking the two.** Confirmed via `/fir/9992` and
    `/person/877` that this is entity resolution working *correctly* — a genuine
    romanisation-variant case, exactly what §3's 35%-drift feature exists to produce —
    the UI simply never cross-references the two names it already has in scope. Logged
    as BUG-026, documented, deliberately left open (small, well-scoped, but out of this
    pass's "one clear fix per change" discipline for a live-system edit).
  - **Export PDF stopped lying by omission.** `exportPdf()` returned `void`, so a 200
    response carrying BUG-018's HTML fallback downloaded silently with zero indication
    that "Export PDF" hadn't produced a PDF. It now reports whether the blob was a real
    PDF; the console shows *"PDF renderer unavailable on this deployment — downloaded a
    printable HTML copy instead"* when it wasn't. Verified live by grepping the deployed
    bundle for the string.
  - **The identity-resolution answer key is now persisted**, closing
    `docs/DATA_GENERATION_AUDIT.md` §19's minor gap the same way the AML labels already
    close its equivalent: `run.py` writes `IDENTITY_ANSWER_KEY` to `.veritas/`, and new
    `data/generator/score_identity.py` recomputes precision/recall/F1 against whatever
    `vx_accused_identity` is currently bound — out-of-band, like `fairness_run_audit.py`,
    not wired to any route. Deliberately **not** exercised against the live 10k-case
    dataset, which predates this fix — regenerating it just to backfill a P2
    auditability gap would be exactly the casual regeneration this project's rules
    exclude.
  - **Re-confirmed, unchanged, correctly still blocked**: QuickML
    (`QUICKML_ENDPOINT_KEY` checked directly against the live AppSail config — still
    unset), PDF export (SmartBrowz still `INVALID_ID`; the in-container local-renderer
    fallback confirmed absent too — "no Chromium-family browser found on this host",
    stated explicitly for the first time rather than left implicit), Aequitas
    (still out-of-band by design), `dowhy` (still a measured, deliberate exclusion).
  - **"Does X have priors?" — the flagship reason identity resolution exists at all
    (§0) — had been silently answering with "crime type not recorded, status not
    recorded" for every case, in production, since this code path shipped.** Found live
    while testing multi-turn pronoun resolution with a fresh pronoun ("her," not "he").
    `sql_agent.person_record()` ran `_case()` over `queries.cases_for_person()`'s rows,
    which carry only raw `CrimeMinorHeadID`/`CaseStatusID` — that query's own join
    (`vx_accused_identity`→`Accused`→`CaseMaster`→`Unit`) already spends 3 of ZCQL's
    4-JOIN cap, with no room left for the `District`/`CrimeSubHead`/`CaseStatusMaster`
    joins `_case()` reads names from. No prior test caught this because every
    `PERSON_HISTORY` test asserted intent *routing*, never answer *content*. Fixed by
    chaining a second, separately-budgeted query (`cases_by_ids`, reusing the
    already-correct `_CASE_SELECT` from `fir_by_id`/`fir_by_number`) instead of asking
    one query to exceed the cap. 2 regression tests, confirmed to fail against the
    pre-fix code first. Deployed and live-verified: the same "Does Usha Naika have
    priors?" query now returns full crime type, district, status and narrative for all
    12 of her cases. Logged as BUG-028 (P0).
  - **The "189 green" test count in this document's own header had been stale for a
    long time** — the real count, gotten via `pytest --collect-only -q` rather than
    trusted from a changelog entry, is 317. Corrected at the top of this document.
  - Created `docs/VERITAS_HANDOFF.md` and `docs/WORK_LOG.md` (neither existed before this
    pass) so a future session has an operational pointer instead of needing to
    reconstruct state from this changelog in full.
- **v14 (map made investigator-grade + a real conversational gap found and closed) —
  a "final product pass" prompt named the map a launch-blocking defect; verified that
  by inspection first, then fixed the actual root cause rather than the symptom.**
  - **The map's Phase-4 "district labels + scale" fix (v13-era, §QA UI-24) only held
    for a broad, spread-out query.** `MapView.tsx`'s `fitBounds({maxZoom: 11})` zoomed
    a TIGHT cluster (a handful of FIRs in one taluk — exactly what a case-scoped
    `CASE_LOCATIONS` follow-up produces) in so far that every neighbouring district
    dot/label fell outside the viewport, leaving one label floating in an otherwise
    blank dark canvas — confirmed against the already-committed
    `docs/screenshots/2026-08-26-conversational-architecture/06-case-locations-map.png`
    before touching any code, per this pass's own instruction not to fix what wasn't
    first inspected. No legend existed anywhere, so an officer had no way to tell an
    exact FIR point from a modeled hotspot-density region either.
  - **Fixed**: `maxZoom` capped at 9 (a tight cluster now keeps a ~150-250km window,
    several neighbouring districts stay in frame regardless of how tight the points
    are); a legend added (amber dot = individual cited FIR, green→amber→red ramp =
    hotspot density); hotspot fill/line opacity raised (0.26→0.4) so the aggregate
    region reads as distinct from the points inside it where large enough to render.
    No district boundary polygons were added — none exist in this dataset, and
    fabricating one would violate this pass's own explicit instruction. Live-verified
    via CDP against the deployed console, both regimes (tight single-district cluster,
    broad statewide) — screenshots in
    `docs/screenshots/2026-08-26-map-investigator-grade/`.
  - **A live conversational sanity pass (9 curl/SSE turns + a 2-turn RBAC check,
    against production, not a mock) found a real, previously-unnoticed gap the prior
    pass's own handoff had predicted but left unbuilt**: `CASE_PEOPLE` correctly
    leaves `active_person` unset when a case has several accused (naming one would be
    a guess), but a pronoun follow-up ("Does he have priors?") fell straight to a bare
    `no_subject` refusal, discarding the names the previous turn had just listed on
    screen. Fixed by checking the previous turn's own stored citations for named
    `accused:` candidates and, with two or more, asking which one — reusing the exact
    ambiguous-name clarification path (`ambiguous_person`) a tied name search already
    uses, sourced from `vx_conversation_turn` rather than a fresh query or any new
    persisted state. 2 new regression tests, the positive one confirmed to fail
    against pre-fix code first.
  - **A second, smaller bug found in the same live session**: `CASE_LOCATIONS`'s
    "nothing to map" refusal reused `EXPLAIN_REASONING`'s "this is the first answer"
    message verbatim — false on any turn but the actual first one (caught live on
    turn 7 of the same session). Given its own accurate message
    (`nothing_prior_locations`).
  - **QuickML re-checked directly against the live AppSail `configuration` object**
    (not re-guessed from a prior pass's note): `QUICKML_ENDPOINT_KEY` remains absent.
    No code change; still correctly BLOCKED with an honest fallback.
  - **Deployed and live-verified**: console (`catalyst deploy --only client`) and API
    (relay-deploy → `appsail/upsert`, deployment `52852000000325027`) both redeployed
    and independently re-tested post-deploy against the live URLs — the map fix via a
    fresh CDP screenshot of the exact previously-broken query, the conversational fix
    via the exact reproduction turn sequence that found it.
  - **Test suite**: 354 collected, all green (2 new this pass).
  - **Not done this pass, named rather than silently skipped**: the full 19-turn
    golden conversation (including an explicit case-switch-and-back and a genuine
    ambiguous-name tie) a "final product pass" mega-prompt specified was not driven
    end to end through the live console — a shorter, targeted live check was, and it
    found and fixed a real bug rather than merely confirming what already worked. A
    full UI judge-review click-through (login → every panel → export → failure states)
    was likewise not repeated in full; the prior pass's own CDP verification of most
    of §1's UI rows stands, re-confirmed only where this pass's own fixes touched them.
- **v15 (real geographic basemap) — the map stopped being a plain dark canvas.**
  - **The self-drawn canvas basemap is gone.** `MapView.tsx` now loads a real MapLibre
    style, OpenFreeMap's `liberty` (`tiles.openfreemap.org`, OSM-derived) — real roads,
    water, terrain and place names, with no API key, no registration and no per-request
    quota. This is the **fifth documented Catalyst exception** (§2): no service in Zia's
    catalog is a map tile provider, so nothing was displaced. What crosses the network is
    a tile z/x/y for the current viewport, never an FIR's exact coordinates or any
    investigative text — the same non-leak guarantee the old architecture note asserted,
    now satisfied by a real basemap instead of by having no basemap at all.
  - **Every Veritas overlay is unchanged**: FIR points, hotspot density polygons, the
    legend, the scale control, the `maxZoom: 9` fix from v14. The district reference
    dots/labels were re-styled only for contrast (a two-tone dot, a dark chip behind each
    name) since liberty's terrain ranges from pale cropland to saturated green forest to
    blue water — the old low-opacity-white styling was tuned for a near-black background
    and would have nearly vanished on a light one.
  - **Attribution restored, correctly this time.** The old CSS force-hid
    `.maplibregl-ctrl-attrib` — harmless when there was no third-party data source to
    credit, wrong now that the tiles are OSM data under ODbL. A compact
    `AttributionControl` renders bottom-right, styled to match the console's glass
    chrome instead of MapLibre's default light skin.
  - **Dead code removed**: `palette.ts`'s `MAP_BG` constant (the flat background colour
    the self-drawn canvas used) had no remaining callers once the style object was
    replaced with a URL; deleted rather than left stale.
  - **`NEXT_PUBLIC_MAP_STYLE` still works as an escape hatch** — it now overrides the
    OpenFreeMap default instead of the flat-background default, so pointing at a
    self-hosted tile server (the honest upgrade path once one has somewhere to run)
    remains a zero-code-change operation.
  - **Verified locally first**: API on `localhost:8000` against the existing sqlite
    mirror (`data/.veritas/ds.sqlite3`, the same 10,000-case dataset), console on
    `localhost:3000`, driven headlessly over CDP. Four queries — a tight single-district
    cluster (Mandya), a bare statewide-phrased query (falls back to the true busiest
    district, Bengaluru Urban), a distant district (Bidar, on the Telangana border, to
    confirm re-centering works anywhere in the state) and a district with no hotspot
    evidence (Kodagu, honest refusal + graceful fallback to the case index) — all judged
    against the same checklist a competition judge would use: real geography recognizable
    within seconds, overlays obvious, legend/scale/zoom all present, not cluttered.
  - **Deployed** (`scripts/deploy-console.sh`, console-only — nothing in `apps/api` or the
    packages changed) and **re-verified live** against
    `https://veritas-60077763394.development.catalystserverless.in/app/index.html`, same
    four queries plus one explicit no-subject refusal. One real platform fact surfaced:
    the first live attempt hit a cold AppSail container (the sign-in gate's own "still
    loading the duty roster — the service is warming up" message, not a map bug) — waiting
    for warm-up and retrying confirmed identical rendering to local. The live dataset
    turned out to have hotspot evidence for Kodagu where the local mirror didn't — not a
    bug, just a different data state between the two backends — and produced the most
    visually striking shot of the pass (dense Western Ghats forest around Madikeri).
  - **`docs/screenshots/2026-08-26-real-basemap/`** holds both sets (4 local + 5 live), and
    supersedes `docs/screenshots/2026-08-26-map-investigator-grade/` (kept for history,
    marked superseded — the zoom-cap and legend fixes it documents are still in effect,
    just now drawn over real geography).
  - **Test suite**: unchanged at 354 (frontend-only change; `npx tsc --noEmit` clean).
  - **Not done this pass**: true district *boundary* polygons — still not part of this
    dataset, still correctly not fabricated. Pan/drag interaction was not driven live
    (screenshots prove render correctness, not gesture handling) — unchanged from v14's
    own note on this.
- **v16 (the persistent per-case investigation board) — the first genuine
  product-level differentiation past the North Star baseline, and the answer to the
  industry gap analysis's own top-ranked finding.**
  - **Built `docs/INDUSTRY_GAP_ANALYSIS.md`'s #1 recommendation whole**: a
    persistent, editable case artifact — pinned evidence, derived findings, people,
    leads (`open`/`pursued`/`dismissed`, with a `reason` field), investigator notes,
    open questions — that survives a page refresh, a new chat session, and a new
    officer's login. One new table, `vx_case_board_item`
    (`data/data/schema.py`), `ItemType`-discriminated so a note can never render as
    a database fact and a derived finding can never be mistaken for an authoritative
    record. References the record layer (`RefType`/`RefID`) plus a content
    *snapshot* at pin time; never a second copy of FIR/person/financial/graph facts.
  - **Layered exactly like `copilot.brief`**: `data/data/board.py` (raw CRUD, no
    policy) → `rag_agent/board.py` (the ONE policy-checked entry point,
    station-scoped via `policy.can_view_fir`, cross-case item tampering blocked) →
    both `apps/api/api/routers/board.py` (4 REST endpoints) and the conversational
    orchestrator call *that same function* — the BUG-003 discipline ("a rule
    enforced by one caller and not its neighbour is not a rule") applied from the
    start rather than retrofitted. Deleting a lead is rejected (400); the API for
    retiring one is a status change (`dismissed`), so "a dismissed lead must remain
    auditable" is structurally enforced, not merely documented.
  - **Six new case-scoped intents** (`BOARD_VIEW`, `BOARD_PIN_EVIDENCE`,
    `BOARD_PIN_PERSON`, `BOARD_ADD_LEAD`, `BOARD_ADD_NOTE`, `BOARD_LEAD_STATUS`)
    extend `intents.NEEDS_CASE` and short-circuit before CRAG evaluation in
    `node_retrieve` — the same pattern `CAPABILITY` already uses, since a board
    mutation/read is not a retrieval and has nothing for CRAG to score. "Pin this"
    resolves against the console's selected evidence card (new `active_evidence_id`
    on `/chat`) or the previous turn's top citation. A lead's status never changes
    without an explicit instruction — never inferred from context.
  - **Console**: `Board.tsx` joins `Copilot.tsx`'s existing per-FIR overlay as a
    second tab ("Briefing" / "Investigation Board") — one overlay, two views of one
    case, not a new destination — reachable from the Evidence rail (new "Pin to
    board" / "Open Case Board"), the case index (new "Investigation board" button),
    and chat. Distinct visual treatment per item kind so provenance stays visible,
    not just stored correctly.
  - **Provisioned live**: `python -m data.provision` created the one new table over
    the Admin API, idempotently, alongside the 37 already-live tables. Deployed via
    the existing relay pipeline (API) and `scripts/deploy-console.sh` (console) —
    both redeployed twice more this pass for the fixes below.
  - **A real live-judge pass — driving the deployed console with the feature's own
    example phrasing, not re-reading the code — found and fixed two genuine defects
    a green `/health` and passing tests did not catch:**
    1. **Keyword collision.** "Pin this to the case board." and "Add that to the
       case board." (the feature spec's own literal examples) both contained "case
       board," which was also a bare `BOARD_VIEW` keyword — `classify()`'s
       score-tie rule (earliest-registered intent wins) routed every successful pin
       to a board *summary* instead. Fixed by removing the bare "case
       board"/"investigation board" fragments from `BOARD_VIEW`'s keyword list.
       Added a systematic substring-collision test across every intent's keyword
       list (`test_no_intents_keyword_is_a_substring_of_another_intents_keyword_unless_expected`)
       so this class of bug can't recur silently.
    2. **Every citation-free answer rendered as a refusal.** The console inferred
       "refusal" from `citations.length === 0`, which a successful `CAPABILITY`
       answer and a successful board confirmation both satisfy without being one —
       "Pinned this evidence…" rendered in the same red, left-bordered styling as
       "I could not find this in the records." Replaced the inference with an
       explicit `answer_is_refusal` field, set by `node_synthesize` at the exact
       point a refusal-shaped answer is produced — deliberately *not* derived from
       `requires_escalation`, which is set generically before synthesis runs and
       does not track whether synthesis went on to answer successfully (a found
       `EXPLAIN_REASONING`/`EVIDENCE_FOR` prior turn re-shows real citations despite
       `requires_escalation` having been `True` on the way in).
    - Also fixed: the board panel reloaded on `turns.length` (increments the
      instant a query is *sent*), not on turns that had actually *finished* — a
      lead saved via the panel's own inline form read stale, pre-mutation state.
      And opening the board directly from the case index (no prior chat turn) left
      the session with no active case, so the panel's own note/lead forms refused
      with "no case is open" — the board button now also asks about the case first.
  - **Live-verified end to end, real HTTP/SSE against production**: sign in → open
    case → "pin this" → note → lead → `GET /board` shows all three, correctly
    typed. A **second, brand-new session** (fresh `session_id`) reopens the case and
    "What is on the board for this case?" correctly lists all 3 — the board
    survives the session, not just the turn. "Dismiss that lead" resolves "that
    lead" to the most recent open one; the lead stays, `status: dismissed`, never
    deleted. An IO gets 403 on another station's board (REST and via chat), 401
    with no token. Audit chain confirmed intact after every mutation. Console
    re-verified via real CDP after each fix: the spec's own example phrases now
    classify correctly, a genuine refusal renders `msg-a refusal` while a board
    confirmation renders plain `msg-a` (read from the live DOM's actual CSS class),
    and two different cases' boards show completely different, correctly-scoped
    content. Screenshots: `docs/screenshots/2026-08-27-investigation-board/`.
  - **Test suite**: 403 collected (25 new for the feature, 4 more for the two live-
    found defects), all green.
  - **Not done this pass, named rather than silently skipped**: the cross-entity
    timeline correlation view (`docs/INDUSTRY_GAP_ANALYSIS.md` §7 item 3) — ranked
    below the board, not part of this pass's scope. A dedicated in-visualization
    pin button (`NetworkView.tsx`/`MapView.tsx`/`SankeyView.tsx`) — the Evidence
    rail's generic "Pin to board" and the conversational path already cover the
    same need for every evidence type, tested; a graph-native click target would be
    a small, purely additive follow-up. QuickML and PDF export remain correctly
    BLOCKED, not re-investigated (no new information since the prior pass's
    from-scratch re-check).
- **v17 (final completion pass) — closing the gap between this file and ~10 sessions'
  worth of real work `docs/WORK_LOG.md`/`docs/ENGINEERING_BRIEF.md` had already done
  and verified live, plus one genuine defect a fresh live audit found.**
  - **This file had gone stale against reality**, not against intent: the last
    changelog entry above is v16, but 236 commits and roughly ten further passes had
    landed on `main` since — cross-entity investigation timeline, protected-span
    Kannada translation (FIR/IPC/plate identifiers immune to the MT model), a
    structured semantic-interpreter layer replacing the flat 30-intent classifier, a
    compositional semantic layer (result-set follow-ups — "only these?" — ordinal/
    positional reference, bounded two-entity comparison, a Kannada-district-name
    gazetteer fix in both translation directions), QuickML activation (root-caused
    down to a platform org-id gap, then a working per-endpoint key, with
    deterministic-confident queries deliberately routed around it to avoid an
    unneeded model call), a general N-step investigation planner with semantic
    correction handling, and a cold-start fix so a cold container answers sign-in
    with a real 503-and-reason instead of a bare 500. Full detail — findings, live
    reproductions, exact deploy IDs — lives in `docs/WORK_LOG.md` and
    `docs/ENGINEERING_BRIEF.md`, not reproduced here; this file's job is to state
    that it happened and that it is live, not to re-narrate it. The false "no other
    design docs" claim at the top of this file is corrected to name that split.
  - **Verified before touching anything**, per this pass's own instruction not to
    change what wasn't first inspected: full local suite (602 collected, all
    green — the "403" this file quoted was itself the stale artifact), live
    `/health` (10,000 FIRs, graph 16,918n/87,120e, 13,835 indexed vectors, QuickML
    configured), and the repo's own automated live-behavior gates —
    `scripts/verify_live_deployment.py` (36/36 adversarial conversational
    scenarios) and `scripts/judge_flows.py` (26/26 realistic officer sessions) —
    both run fresh against production, not re-quoted from a prior pass's log.
  - **One real defect found by that audit, not by re-reading old bug reports**:
    the live Kannada battery's own output showed `"73 ಪ್ರಕರಣಗಳು(s)"` — synthesis
    writes count-agnostic `case(s)`/`record(s)` markers throughout
    `orchestrator.py` (a deliberate convention for English readers), and NLLB
    translates the noun but copies the literal `"(s)"` through untouched. Fixed
    structurally, the same discipline `_protect_spans` already uses for
    identifiers and district names: a new `_resolve_plural_markers()`
    (`data/data/nlp/translate.py`) resolves every such marker to real English
    singular/plural — reading the actual count already sitting next to it — before
    the text ever reaches the translation model, so the ambiguity never reaches
    NLLB rather than being hoped away. One test
    (`test_resolve_plural_markers_picks_singular_or_plural_from_the_real_count`,
    `data/tests/test_nlp.py`) — the one that took the real count from 601 to 602.
  - **Deployed and live-verified**: commit `ddbc4f1` relayed
    (`get-signature` → `.github/relay-upload.url` → `relay-deploy.yml` → local
    `appsail/upsert`) to deployment `52852000000346070`. Both automated live
    gates re-run clean against the fresh container (36/36, 26/26), and the exact
    live query that surfaced the bug (`"ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು
    ಪ್ರಕರಣಗಳಿವೆ?"`) now renders `"73 ಪ್ರಕರಣಗಳು"` with no residual `"(s)"` and the
    correct canonical district spelling, confirmed by parsing the raw SSE
    response, not by re-reading the automated battery's summary line alone.
  - **One operational finding, not a code defect**: the AppSail `appsail/upsert`
    callback's own JSON response echoes the app's full environment configuration —
    including `VERITAS_JWT_SECRET`, `VERITAS_JOB_TOKEN`, and the QuickML OAuth
    client secret/refresh token — in plaintext. This is the platform API's
    behavior on every deploy through this pipeline, not something this pass
    introduced, and `scripts/rotate_secrets.py` already exists for the case
    where that needs acting on. Left for the operator to decide whether rotation
    is warranted; not rotated unilaterally, since doing so would invalidate
    live JWT sessions and the Cron job token without coordination.
  - **Test suite**: 602 collected, all green.
  - **Not re-done this pass, named rather than silently skipped**: no dataset
    regeneration — the live audit found no data-quality defect, and regenerating
    10,000 seeded cases on spec-compliance grounds alone would be exactly the
    unrequested rebuild this project's own freeze discipline argues against. No
    UI zoom-level/browser click-through — the last CDP-verified pass
    (`docs/screenshots/2026-08-27-investigation-board/` and earlier) stands,
    unchanged by a backend-and-one-translation-file pass; not re-driven from
    scratch for lack of a found regression to chase. QuickML endpoint-key
    status, PDF export's SmartBrowz identity block, and the "priorities"
    Kannada residual (`\bpriors?\b` vs. "priorities") are unchanged from the
    prior passes' own from-scratch re-checks — no new information surfaced this
    pass that would change any of those three findings.
- **v18 (console redesign) — an investigative workstation instead of three panes of
  cards.** Frontend only: no backend, RBAC, evidence-semantics or orchestration change,
  and no new endpoint. `apps/web` was the part of this platform that still looked like a
  data-science demo, and the gap between what the engine does and what the screen claims
  was itself a defect.
  - **The shell.** Three co-equal floating glass panes became a top bar, a persistent
    **investigation header**, and three full-bleed hairline-divided columns (copilot /
    workspace / evidence). Nothing floats except the two things that genuinely do — the
    evidence inspector and the case overlay. The gradient mesh, the glass blur and the
    glow are gone; hierarchy comes from layout, and the palette is ~90% neutral.
  - **The top bar stopped advertising the deployment.** `10,000 FIRs · 16,918 nodes ·
    13,835 indexed` is a true fact about the *stack*, not investigator context, and it
    was holding the best strip on the screen. It moved behind the system indicator, one
    click away (`19-system-status.png`). Its place went to ⌘K search and the officer.
  - **Provenance became a visual primitive** (`apps/web/lib/evidence.ts`, `.prov-*` /
    `.rail-*`). Every surface that shows a fact — an evidence row, a board item, a
    timeline event, a briefing section, a chart legend — carries the same rail and glyph:
    ■ RECORD (blue, stated in the file) · ◆ DERIVED (amber, inferred by Veritas) ·
    ▲ MODEL (violet, computed). The platform's strongest claim is that a model's estimate
    can never look like a record; that is now a dedicated visual channel rather than a
    word inside body text. `confidence_kind` is likewise split by name: **evidence
    support** ≠ **text match** ≠ **model output**, so a 66% wording similarity can no
    longer read as authoritative as 100% corroboration.
  - **Evidence stopped being nine identical cards.** The column leads with the evidence
    AS A SET — "Moderate · 5 authoritative records · 4 model outputs" — and the sources
    are compact rows; the full record, its provenance, its retrieval query and its
    actions live in an **inspector** drawer (Esc / ↑↓ navigable) that never leaves the
    investigation. Support counts SOURCES, never an average over scores measuring
    different things, and only `support`-kind confidences can move the verdict.
  - **The workspace has tabs**, and they are views of the investigation, not
    destinations: Overview · Timeline · Network · Geography · Financial · Board. A new
    answer pulls the workspace to the view it produced; a view with nothing loaded states
    what it is for and hands over the exact question that fills it. Each carries an
    **analysis header** naming the figures the visualization contains but never stated
    ("600 cases located · 4 hotspots · 1.00 peak density").
  - **Two real defects the redesign surfaced and fixed**, both category errors of the
    kind §12 exists to prevent:
    1. **The network painted PageRank on the SEVERITY ramp**, so every ordinary
       co-accused rendered somewhere on the crimson end — the graph asserted a threat
       score this platform does not compute for those nodes. Influence now has its own
       steel→blue scale (`palette.ts`), labelled *"connectedness within this graph — not
       a risk score"*.
    2. **The root node's `pagerank: 1.0` is a display sentinel** (`synthesis_agent.py`
       says so), and it was inside the max-normalisation — so every genuinely measured
       centrality (0.003–0.01 in a real co-offending network) collapsed to the bottom of
       the ramp and twenty distinguishable associates rendered as twenty identical dots.
       Scaled on the real values now, with the subject sized and coloured explicitly and
       **named** (it used to render as the literal string "subject").
  - **The evidence thread survived a shell rename it would have died silently in.**
    `EvidenceThread` anchors on `chip.closest(".pane")`; `.pane` no longer exists, and
    `closest()` returning null draws nothing at all — indistinguishable from the feature
    having been removed. Caught in a screenshot, not by a test or the type checker;
    now anchored on `.col` with a comment saying why the selector is load-bearing.
  - **Refusal is a designed state**, not a red error box: calm amber-ruled panel, "No
    supporting records", plus what that does and does not mean. A transport/engine
    failure is a *separate*, genuinely red state — `Turn.failed` is new, because the old
    code set `refused: true` on a caught exception and made the system working correctly
    look identical to the system breaking.
  - **Loading names its stages** (`Progress.tsx`) — understanding → retrieving →
    verifying → preparing — derived from the trace the engine already emits, so it
    reports what is actually happening and exposes nothing the trace panel didn't.
  - **Also**: ⌘K command palette over the rank-scoped case register plus real actions;
    the case register is rows, not cards (three buttons per card became row actions on
    hover); alerts moved out of the evidence column into a counter that can never cover a
    record; the board is a first-class workspace with a compose rail; forecast intervals
    read as intervals (dashed bounds) instead of a slab; the map gained a density
    layer toggle and provenance labels in its legend.
  - **Verified by driving the real console over CDP**, not by reading the diff: 19 states
    captured in `docs/screenshots/2026-08-29-workstation-redesign/`, and the interactions
    a screenshot cannot prove — graph node click, inspector ↑↓/Esc, ⌘K, alerts, system
    popover, Kannada round trip (`73 ಪ್ರಕರಣಗಳು`, no residual `(s)`) — all driven with real
    input events and asserted on live DOM. Zero console errors. `npx tsc --noEmit` clean;
    static export re-verified against both v9 invariants (`/app`-prefixed assets, no
    `localhost` in the bundle).
  - **Not done this pass, named rather than silently skipped**: not deployed — this is a
    console-only change and `scripts/deploy-console.sh` is the one command it needs, but
    pushing to the live URL is the operator's call. The backend is untouched, so the 602
    Python tests are unaffected and were not re-run against a change that cannot reach
    them. `apps/web` has no test suite of its own and this pass did not add one.
