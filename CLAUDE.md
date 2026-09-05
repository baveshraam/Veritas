# Veritas — KSP Datathon 2026, Challenge 01

**The source of truth for the architecture and design rationale.** Keep this current.
`docs/WORK_LOG.md` and `docs/ENGINEERING_BRIEF.md` carry the pass-by-pass operational
detail (every defect found, every live verification, every deploy) at a grain this file
deliberately does not duplicate — this file states what is true now and why; those two
state how it got that way. If a claim here and in `docs/` conflict, re-derive it from
the live system and code rather than trusting either document — both have drifted stale
before. The Changelog below is a condensed index, one entry per pass: log full detail
in `docs/WORK_LOG.md` and add only a one- or two-line summary here, so this file stays
readable instead of re-growing into the narrative `docs/` already owns.

A conversational crime-intelligence platform for the Karnataka State Police: ask a question
in English or Kannada, get an answer where every claim traces to a specific record.

- **Repo**: `github.com/baveshraam/Veritas`
- **Runs on**: Zoho Catalyst (project `Veritas`, id `52852000000013048`, org `60077763394`)
- **Schema**: the organizers' `Police_FIR_ER_Diagram.pdf`, reproduced verbatim
- **Tests**: `python -m pytest` — 868 green, 2 skipped (`python -m pytest` prints the current
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
- **A `double` column is a hard, non-configurable DECIMAL(15,4), and accepts a
  scientific-notation value silently corrupted no matter how it arrives.** Confirmed
  the precision cap by asking Data Store's own column-update endpoint for
  `max_length: 25, decimal_digits: 12` on an already-provisioned column and getting
  the request accepted (`status: success`) with the returned spec unchanged at 15/4 —
  no provisioning or update choice widens it. Confirmed the corruption by round-
  tripping the exact row-write endpoint the SDK calls, directly, with three inputs: a
  bare JSON number below the precision (`0.0009`) was *rejected outright* (`400
  INVALID_INPUT`); a plain fixed-point string (`"0.000851196807533056"`) round-tripped
  *correctly* (`8.0E-4`); a string that still contained an exponent
  (`"7.817113529341168e-05"`) came back with it silently dropped (`7.8171`) — a
  10,000x-100,000x inflation (changelog v22 — a real co-offender's PageRank came back
  live as `8.5119`, tripping the graph view's `pagerank >= 1` root-node sentinel and
  rendering that associate as a duplicate of the query's own subject). `data.ds._sdk_row`
  now formats every float as `f"{v:.4f}"` — a string, always plain decimal, never
  `e`/`E` — before it reaches the SDK, so this is handled once, for every `double`
  column, not per caller.

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

### Provenance — `provenance.py`
Every result a specialist produces can be asked **"why is this here?"**, and the answer is
about the claim, not the pipeline: the records underneath it, how they were combined, why
this one qualified, and what it does not establish (§8). Dispatch is on the `evidence_id`
prefix each producing branch already writes, so a new retriever gets an explanation by
following the same convention it already follows to be citable. Two rules: the chain is
derived from the record layer on demand, so it can never go stale against it; and where it
cannot be reconstructed it says so — a fabricated chain would defeat everything the CRAG
evaluator above is for.

**Two agreement checks run before an answer ships.** A structured field beats a generated
sentence: prose that describes a case's status differently from its `CaseStatusName` carries
a correction naming the recorded status, and a district the prose names that neither a cited
record nor the question mentions is flagged as unsupported. Both are narrow on purpose — an
officer told "the record says otherwise" about a correct sentence learns to ignore the
warning, so anything not decidable from a column the cited records actually carry is left
alone.

**A bounded result says it is bounded.** `describe_result_set` states what KIND of set is on
screen — sampled, filtered, ranked, exhaustive, modelled — from the same `result_context` the
producing branch already records. Five cases listed under a question that asked for "the
cases" reads as all of them, and that is the quiet failure, not a loud one.

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

**Six further conversational operations (v24)** extend the same case/person-scoped
pattern, each built entirely on data already in the record layer: **interrogation
prep** (priors, structural case gaps, direct associates, assembled before an officer
questions someone), **case-similarity watch** (`SIMILAR_CASES` narrowed to an
officer's own backlog and the unsolved pool), **case handoff** (the Copilot brief
fused with the investigation board's own state into one "catch me up" narrative),
**challenge a finding** (a new meta-turn, alongside "why is this here"/"what supports
this", that actively looks for what would WEAKEN the previous answer rather than
explaining how it was reached), **pre-filing check** (the same structural-gap check,
run proactively before a case is sent up), and **cross-station linkage** (reports when
a case's accused is also named at a different station, under the same partial-
visibility rule associate explanations already use — the link is always reported, the
other case named only where the officer's access allows it).

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

An investigative intelligence workstation (v18, productized in v19). **Light is the
default**: a warm off-white ground, white work surfaces, cool slate rules and deep
navy text — the register of an institutional record system, read for hours next to
paper. Dark remains available as one token block (`data-theme="dark"`), offered in
System status; there is no second design. IBM Plex in three roles, Noto Sans Kannada
for Kannada, mono reserved for record identifiers.

A global bar, a persistent investigation header carrying the workspace tabs, and
three hairline-divided columns:

- **Left — copilot**: streaming SSE, push-to-talk with a live waveform, EN/KN toggle.
  An answer renders as a **finding**, not a paragraph: the engine's own "Based on N
  records" line becomes a caption, each `[n]` claim becomes a row anchored on its
  clickable citation chip, and "no inference has been added" becomes a footnote.
  Where the answer produced a network, a module states the two populations apart —
  who the records NAME versus who was reached through shared cases.
- **Centre — workspace**: one primary surface, chosen by the tab in the investigation
  header (Overview · Timeline · Network · Geography · Financial · Board). With a case
  open, **Overview is that case's overview** — narrative, facts, the people (each
  as-filed name linked to the identity resolution matched it to), what is still open,
  the most recent developments, and the questions to ask next; the register is one
  click away. A new answer pulls the workspace to the view it produced, including
  when the answer is a *negative* finding ("no outbound trail"), which lands in
  Financial rather than leaving the register on screen.
- **Right — evidence**: the sources as a SET first ("Moderate · 5 authoritative
  records · 4 model outputs"), then compact rows. With nothing cited the column
  narrows to a strip rather than spending a fifth of the workstation saying so. A row
  opens the **inspector** — the full record, its provenance, **why it is here**, what
  its confidence number actually measures, and the query that retrieved it.

**Any result can be asked WHY** (v20 — `packages/rag_agent/rag_agent/provenance.py`,
`GET /explain`, `apps/web/components/WhyChain.tsx`). Point at an associate, a case, a
hotspot, a timeline event, a transfer, a lead, a forecast — by clicking it or by
typing *"why is this person connected?"* — and the answer is the same five things in
the same order: **CLAIM · BASIS · RECORDS · DERIVATION · WHY IT QUALIFIES**, plus what
it does NOT mean and the questions the engine can actually answer next about it. It
names the actual records ("both named as accused on FIR 100303002202400003, Theft,
Yadgir, 13 Jul 2024"), never the pipeline; where a chain cannot be reconstructed it
says so rather than inventing one. A selected node or map case is an investigation
entry point, offering only actions the backend supports.

**Provenance is a visual primitive**, and it is the same one on every surface —
evidence, board, timeline, overview, briefing, chart legends: ■ RECORD (stated in the
file) · ◆ DERIVED (inferred by Veritas) · ▲ MODEL (computed). A model estimate must
never be able to look like a record, so it gets its own channel rather than a word
inside body text. The three things `confidence` can mean are named apart for the same
reason: **evidence support** ≠ **text match** ≠ **model output**.

**The finding leads; the measurement follows** (`apps/web/lib/metrics.ts`). A
headline is what the number MEANS — "Severe concentration", "≈74 cases projected",
"Central to this network" — with the figure printed underneath it ("Relative density
· 1.00", "Expected daily range · 2.1–2.9", "Network influence · 0.010"). Nothing is
hidden; a band is a reading of a number still on screen.

**Reasoning Trace panel** (expandable, off by default) renders the agent trace in
plain language. While a turn runs, a four-stage progress readout names what is
happening — understanding → retrieving → verifying → preparing — and deliberately
does NOT print the trace's raw `detail`, which is written for an engineer ("Semantic
model (QuickML) — no familiar phrasing matched…") and reads to an officer as *the
system did not understand you* while the system is in fact understanding them. That
text is one click away in the trace, where opening it is a deliberate act.

**Refusal is a designed state**, not an error: a calm amber-ruled panel saying what
could not be established and what that does and does not mean. A transport or engine
*failure* is a separate, genuinely red state — the two must never look alike.

The basemap is a real MapLibre style served by **OpenFreeMap** (`tiles.openfreemap.org`,
OSM-derived, no API key or registration — the fifth documented exception, §2). What
crosses the network is a tile z/x/y for the current viewport, never an FIR's exact
coordinates or any investigative text; a viewport request reveals district-level
location at most, which is already non-sensitive metadata (every FIR's District is a
plain ER column). Veritas's own overlays — FIR points, clusters, hotspot density
polygons, district reference labels, legend, scale — render on top.

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

Condensed index — full pass-by-pass detail (every defect, every live verification,
every deploy ID) lives in `docs/WORK_LOG.md` and `docs/ENGINEERING_BRIEF.md`.

- **v1–v4**: Postgres + PostGIS + Neo4j + pgvector + Gemini, on a self-designed schema.
  Built and integrated end-to-end.
- **v5 (Catalyst migration)**: infrastructure replaced, features preserved. FastAPI →
  AppSail; Next.js → Slate; JWT → Catalyst Auth; headless Chrome → SmartBrowz; PostGIS
  and Neo4j+GDS dropped for NetworkX (ported every algorithm exactly).
- **v6 (organizers' ER)**: reshaped the whole schema to the organizers' ER verbatim (27
  of their tables + 10 `vx_`-prefixed additions); built Fellegi-Sunter identity
  resolution (F1 0.989) as the load-bearing centrepiece (§0); PostgreSQL → Data
  Store/ZCQL; pgvector → Stratus + numpy; Gemini → QuickML; added Cache + Cron; baked
  model weights into the image; fixed the co-offending generator (crews, not a random
  graph — Louvain now finds 12 communities, not 1); deleted the fabricated gang layer.
  189 tests.
- **v7 (deployment)**: fit the image through AppSail's bundle-sandbox ceiling
  (empirically ~2.2GB then) — NLLB → CTranslate2 int8, whisper `base`, `xgboost-cpu`,
  no generator-only deps; `torch` dropped from the deployed image (AML GNN degrades
  gracefully); SHAP via xgboost's own `pred_contribs`; deploys relay through GitHub
  Actions to beat the signed-upload-URL TTL on a residential uplink.
- **v8 (going live)**: first live deploy. Learned the real bundle-sandbox ceiling is
  ~1.3GB, not 2.2GB — moved model weights out of the image entirely into File Store
  (image now 0.88GB); ZCQL refuses JOINs between value-related tables live, so reads
  run off a local sqlite mirror hydrated from Data Store; Data Store pagination can
  duplicate a row at a page boundary; the SDK JSON-serializes writes (datetimes need
  display strings); Stratus bucket creation is scope-blocked (`OAUTH_SCOPE_MISMATCH`) —
  dead code with a mirror fallback. See "Platform gotchas" below. 189 tests, all live.
- **v9**: the hosted console was blank in production from two build-time bugs — Catalyst
  serves the client from `/app/`, not the domain root, and `NEXT_PUBLIC_API_URL`
  defaulted to `localhost` at build time and got baked into the static export. Both are
  now guarded by `scripts/deploy-console.sh`.
- **v10**: 18-digit FIR numbers weren't recognised by the FIR-lookup regex (fell through
  to semantic search on the wrong case, cited and confident); a named-but-nonexistent
  FIR now refuses instead of returning nearest-neighbour narratives; console redesign
  ("Registry"); fixed three colour bugs running confidence/status through the severity
  ramp. 200 tests.
- **v11**: a hotspot/forecast question naming no district crashed outright — exactly the
  laziest, most natural phrasing of the question. Fixed at the one producer of the
  malformed district code. 201 tests.
- **v12**: `/alerts` moved WebSocket → SSE (the AppSail gateway 404s on a WS upgrade);
  `/health` now reports actual model-weight provenance instead of letting a wrong claim
  go unchecked; warm-up thread for NLLB/whisper (cold load ≈20s); measured DoWhy's
  dependency footprint and declined it (fits on paper, no margin); root-caused QuickML's
  failure to a missing per-endpoint key header; both Cron jobs had never once succeeded
  since creation — fixed a wrong app id in the job URL and a stale job token.
- **v13 (hardening pass)**: Cron's own audit-verify job was still failing unattended
  because it ran synchronously past Cron's timeout — same background-thread fix
  `/jobs/refresh` already used, plus a `sync=true` escape hatch for manual checks (why
  the bug stayed invisible: manual curls always hit an already-warm container). "Does X
  have priors?" was silently answering with the wrong case data because a second query
  exceeded ZCQL's 4-JOIN cap (P0). Created `docs/WORK_LOG.md`. 317 tests (correcting a
  long-stale "189" in this file's own header).
- **v14**: the map's `maxZoom` fix only held for spread-out queries, not a tight
  single-taluk cluster — capped lower, added a legend. Pronoun follow-ups ("does he have
  priors") after a multi-accused answer now resolve against the previous turn's named
  candidates instead of refusing outright. 354 tests.
- **v15**: replaced the self-drawn canvas basemap with a real MapLibre style (OpenFreeMap
  `liberty`, OSM-derived, no key/quota — the fifth documented Catalyst exception, §2).
- **v16**: built the persistent per-case investigation board (`vx_case_board_item`, 6 new
  intents, `Board.tsx`) — pinned evidence/findings/people/leads/notes that survive a
  session. Found and fixed a keyword collision (a pin phrase matched a `BOARD_VIEW`
  keyword) and a UI bug rendering every citation-free answer as a refusal. 403 tests.
- **v17**: caught this file up to ~10 undocumented sessions of real work (cross-entity
  timeline, protected-span Kannada translation, a semantic-interpreter layer, QuickML
  activation, an N-step planner). Found both English and Kannada answers leaking a
  literal `(s)` plural marker into prose — resolved generally, not just for Kannada.
  Noted the `appsail/upsert` deploy response echoes secrets in plaintext (operational
  finding; not rotated unilaterally). 602 tests.
- **v18 (console redesign)**: an investigative workstation shell (copilot / workspace /
  evidence columns) replacing three floating glass panes. Made provenance
  (RECORD/DERIVED/MODEL) a visual primitive on every surface. Found the network view was
  painting ordinary co-accused on the *severity* ramp, and that the root node's
  `pagerank: 1.0` display sentinel was collapsing every real associate's centrality to
  the bottom of the scale.
- **v19 (productization)**: light theme became the default (dark is one token block,
  still available); "the finding leads, the measurement follows" framing
  (`lib/metrics.ts`); fixed a numeric/string id mismatch that silently misattributed
  named-in-file people as merely graph-adjacent; four natural phrasings of "who's
  involved" were each routing to a different, wrong intent — fixed as a question-shape
  pattern, not per-phrase keywords. 631 tests.
- **v20 (explainability)**: any derived result can be asked "why is this here?" —
  `provenance.py` returns CLAIM/BASIS/RECORDS/DERIVATION/WHY-IT-QUALIFIES for 22 evidence
  kinds, shared by `GET /explain` and typed questions (§5, §8). Added result-set
  truthfulness labelling (sample vs. exhaustive) and a structured-field-vs-prose
  contradiction check. Found and fixed 9 defects by actually driving the flows the
  feature was built for. 670 tests.
- **v21**: built two 1,000+ line test corpora from the dataset's own vocabulary (officer
  and judge phrasings) and found ~430 misroutes. Fixed: `CRIME_SEARCH` silently ignored
  every filter but crime-type/district (returned everything, cited and confident); added
  `OFFENDER_RANKING` and `CASE_STATS` intents — questions the raw ER literally cannot
  answer without identity resolution; rebuilt push-to-talk as a real recording control;
  fixed the multi-word search box. 740 tests.
- **v22**: a live network view was rendering distant associates as duplicates of the
  query subject. Root cause: Data Store's `double` columns are a hard, non-configurable
  DECIMAL(15,4) that silently corrupts a scientific-notation value by 10,000–100,000×
  on ingest. Fixed by formatting every float written through `data.ds._sdk_row` as an
  always-plain-decimal string, never `e`/`E` (§3). Live data self-healed on the next
  refresh. 741 tests.
- **v23**: the workspace's analytical tabs stopped firing a canned English question at
  the orchestrator just to fill themselves (destroyed the prior turn's evidence, did
  real intent/CRAG work for what is just a table scan) — new `GET /analytics/*`
  endpoints call the same policy-scoped query functions directly. Statistics became a
  real KPI+chart dashboard off one grouped scan. Found `/jobs/refresh`'s four
  independent derived-layer rebuilds shared one try/except, so one blocked step
  (Stratus, scope-blocked) silently cancelled the others. 802 tests.
- **v24**: added the six conversational Copilot operations named in §5 (interrogation
  prep, similarity watch, handoff, challenge-a-finding, pre-filing check, cross-station
  linkage) — researched against real deployed products and the West Midlands Police
  Copilot hallucination incident. Reverse-engineered and documented the actual
  `appsail/upsert` deploy contract (multipart form, not JSON) into
  `scripts/deploy-api.py`. 830 tests.
- **v25**: interrogation prep was briefing the officer on their own paperwork gaps
  instead of questions a suspect could actually answer — rebuilt around the subject's
  own cases/associates/record. Challenge-a-finding printed an empty quotation and could
  flag a 100%-confidence point as "least supported" — fixed, plus added structural
  checks specific to derived network answers.
- **v26 (strategic reset)**: a ground-up audit (`docs/STRATEGIC_RESET_2026-09-04.md`)
  found the challenge's own named capabilities — pattern discovery, behavioral
  profiling — were reactive-only or a bare risk score. Added unprompted cross-station
  series discovery (linkage-blindness / ViCAP-style, pushed through `/alerts`) and an
  evidence-backed behavioral profile (recurring MO, timing, geographic range,
  escalation — never demographic, by construction). Backfilled real BNS section
  citations onto the live dataset. Added a hard QuickML spend cap + call-count circuit
  breaker. **868 tests, 2 skipped.**
- **v27 (Part 9, Items 1-3)**: closed the three unblocked items from
  `STRATEGIC_RESET`'s remaining-work plan. **Aequitas wiring** — the bias audit was a
  real, working script nobody scheduled; it is now its own isolated `/jobs/refresh`
  step (cached, so a fresh Cron cycle can't silently skip it the way a blocked Stratus
  publish once cancelled the AML sweep), surfaced as a real `/health` status line and
  in the console's System panel. **Fused prevention advisory** — hotspot detection,
  trend forecasting, and cross-station series linkage existed as three outputs an
  officer combined mentally; `prediction_agent.advisory_for` fuses them into one
  proactive read per district (only when a real hotspot AND a rising forecast agree —
  a hotspot with a flat/falling forecast isn't news), cached by the same refresh step
  and pushed through the existing `/alerts` SSE feed as a new `advisory` event, with
  the confounder disclosure and any Aequitas flag shown as separate caveats, never
  folded into the headline number. **Graph-edge annotation** — `NetworkView.tsx`'s
  edge click now opens the same pin-a-note flow a node already had; the backend
  reconstructs the edge directly from the graph (the same "not part of any chat
  turn's evidence pool" situation the Timeline tab's own pin already handled), tagged
  `ref_type="graph_edge"`. Item 4 (LLM-authored MO narrative) stays deliberately
  deferred — QuickML has no real billing history yet, unchanged from Part 9's own
  recommendation. **874 tests, 2 skipped.**

---

## Platform gotchas learned the hard way

Non-obvious Catalyst/Data Store facts, consolidated here because they recur across
versions above and are easy to re-discover the expensive way otherwise.

- **AppSail's bundle-creator sandbox is the real deploy ceiling**, and it is smaller
  than the app-level `disk` config suggests: empirically ~1.3GB, not the ~2.2GB implied
  by scratch-space math, because staging adds a fourth copy of the image. Model weights
  (~760MB) live in File Store, streamed and spliced at cold start
  (`data/nlp/model_fetch.py`) — never baked into the image or written to disk as one tar.
- **The Catalyst SDK's context is per-request headers (`X-ZC-*`), not environment
  variables.** A bare `zcatalyst_sdk.initialize()` raises "Catalyst headers are empty" in
  AppSail; the API middleware captures each request into the SDK
  (`ds.bind_catalyst_request`), and background jobs reuse the captured app.
- **Live ZCQL refuses JOINs between value-related tables** (every JOIN in this codebase,
  since the ER relates by business key). Reads run off a **local sqlite mirror**
  hydrated from Data Store once per container; writes go to Data Store first, mirror
  second.
- **Data Store pagination can duplicate one row at a page boundary, even under ORDER
  BY.** Paged reads dedupe on ROWID; hydration `INSERT OR IGNORE`s.
- **The SDK JSON-serializes writes**, so datetimes must be passed as Data Store display
  strings (`data.ds._sdk_row`), never raw datetimes.
- **A `double` column is a hard, non-configurable DECIMAL(15,4)** — a column-update
  request asking for more precision is accepted (`status: success`) but silently
  ignored. A value containing scientific notation is silently corrupted 10,000–100,000×
  on ingest. `_sdk_row` formats every float as `f"{v:.4f}"` (always plain decimal) before
  it reaches the SDK — the fix for every `double` column, not just the one that broke
  (§3, changelog v22).
- **No bind parameters, no UPSERT, no `date_trunc`, no CTE, no correlated subquery, at
  most 4 JOINs.** `_lit()` is the single injection boundary; aggregation past that
  happens in Python (`data/data/queries.py`).
- **ZCQL rejects double-quoted identifiers**, which SQLite requires for ER tables named
  after SQL keywords (`Rank`, `Section`). Callers write the portable quoted form;
  `unquote_identifiers()` strips them on the way to Catalyst.
- **A SELECT returns at most 300 rows**; `query()` pages transparently.
- **Catalyst serves the static console from `/app/`, not the domain root**
  (`assetPrefix: "/app"` in `next.config.mjs`), and a Next static export resolves
  `NEXT_PUBLIC_API_URL` at *build* time with no runtime left to correct it — a developer
  machine's `.env.local` can silently ship `localhost` to every officer's browser.
  `scripts/deploy-console.sh` guards both.
- **The `appsail/upsert` deploy call is `multipart/form-data`, not JSON** — `name`,
  `memory`, `platform: "custom_runtime"`, `configuration` as a JSON *string*, and
  `local_object_key` (never `image`/`object_key`, which 400 with an opaque
  `INVALID_INPUT`). Full contract in `scripts/deploy-api.py`. Its response echoes the
  app's full environment configuration — including secrets — in plaintext; rotate via
  `scripts/rotate_secrets.py` if that ever needs acting on.
- **The Admin API is on the India DC** (`api.catalyst.zoho.in`, not `.com`), and its
  `ENVIRONMENT` header must be exactly `Development` — `DEVELOPMENT`/`development` are
  both rejected.
- **A background job (Cron-triggered) that touches the data layer before responding
  will fail every unattended fire**, because Cron abandons the request before a cold
  mirror-hydration (~20s+) completes. Run the real work on a background thread and
  return immediately; keep a `sync=true` escape hatch for manual verification (which is
  exactly why this class of bug hides from manual testing — a curl always hits an
  already-warm container).
- **Independent derived-data rebuild steps must not share one try/except.** A single
  blocked step (e.g. Stratus, permanently scope-blocked here) will silently cancel every
  step after it in `/jobs/refresh` unless each is isolated.
- **QuickML LLM Serving needs a per-endpoint `X-QUICKML-ENDPOINT-KEY` header**, obtained
  from that model's own Catalyst console popup — not documented anywhere in the general
  QuickML API docs.
- **PDF export (SmartBrowz) remains blocked** — `INVALID_ID`/"No such User" persists
  even after the `_switch_user("admin")` fix that resolved the identical class of error
  for QuickML; no Chromium-family fallback exists on the deployed host either. The
  console downloads a printable HTML copy instead and says so.
