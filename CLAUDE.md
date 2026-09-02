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
- **Tests**: `python -m pytest` — 802 green, 2 skipped (`python -m pytest` prints the current
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
- **v19 (productization) — the console stops looking like a data-science demo, and
  four defects the pass surfaced by driving it rather than reading it.** Frontend,
  plus three small, narrowly-scoped backend text/routing fixes named below. No RBAC,
  evidence-semantics or orchestration change; no new endpoint.
  - **Light is the default.** The whole theme is one `:root` token block — a warm
    off-white ground, white work surfaces, cool slate rules, deep navy text, ochre
    for identity and a restrained blue for action. Dark is the same block redefined
    under `[data-theme="dark"]` and offered in System status, so there is one design,
    not two. Every hardcoded colour left in the stylesheet was tokenised on the way
    (scrims, shadows, the map's floating plates, the MapLibre control icons), and
    `viz/palette.ts` now READS those tokens at render time instead of carrying a
    second copy of the palette — which is what makes the charts follow the theme.
    **Noto Sans Kannada** joins IBM Plex, with the extra line-height Kannada needs;
    `:lang(kn)` applies it wherever a Kannada answer renders.
  - **The finding leads; the measurement follows** (`apps/web/lib/metrics.ts`, one
    module every surface reads). "0.010" became "Central to this network · Network
    influence · 0.010"; "1.00 peak density" became "Severe concentration · Relative
    density · 1.00"; "2.5 mean FIRs/day" became "≈74 cases projected · Expected daily
    range · 2.1–2.9" — which is the figure an officer actually plans against. Nothing
    is hidden: a band is a reading of a number still printed beside it.
  - **The graph and the answer stopped disagreeing** (`apps/web/lib/network.ts`). An
    answer would say "two people are accused in this FIR" while the graph beside it
    drew forty, with nothing on screen reconciling them — an officer reads that as
    forty accused, which is an accusation this platform has no basis for. The two
    populations are now counted and captioned apart, from data the payload already
    carried: `accused:<PersonUID>` evidence ids are the people the FILE names (a
    record fact, drawn as the console's square RECORD glyph), and everyone else was
    reached through shared cases (derived, drawn as a circle). Where the question was
    about a person rather than a case the file names nobody, so the front group is
    one-hop co-offenders — captioned "offended alongside X", never "named in the
    records", because those are different claims.
  - **Overview is the case's overview once a case is open** (`CaseOverview.tsx`) —
    narrative, facts, the people, what is still open, the most recent developments,
    and the questions to ask next, all from `/fir`, `/board` and `/timeline/case`. It
    also closes **BUG-026**, open since v13: the file records "Suma Nadkarni D/o
    Eshwar" while every derived surface calls the same PersonUID "Soom Nadkarni", and
    nothing linked them. The two names now sit together, the second labelled Derived
    and explained. The register is one click away, not replaced.
  - **Progress stopped exposing the engine room.** The trace's raw `detail` is
    written for an engineer — "Semantic model (QuickML) — no familiar phrasing
    matched, asking the model to interpret this question" — and printing it mid-answer
    reads as *the system did not understand you* while the system is understanding
    them. The four progress stages now carry their own plain-language notes; the
    detail is unchanged and one click away in the reasoning trace.
  - **Four defects found by driving the console, not by reading the diff:**
    1. **`record(s)`, `hop(s)`, `case(s)` reached English readers.** v17 fixed this
       for Kannada only, by resolving the markers on the way INTO the translation
       model. English answers shipped the marker itself — a form field in the middle
       of a finding. `resolve_plural_markers` is now applied in `node_synthesize` to
       the answer and to the evidence lines beside it, for every language.
    2. **The network join silently matched nothing.** Node ids arrive as numbers
       (`{"id": 803}`) while an evidence id is the string `"accused:803"`, so the two
       people a case file actually named rendered as "reached through shared cases" —
       the exact misattribution the module exists to prevent. Ids are normalised to
       strings once, at the top of the component.
    3. **A negative finding left the register on screen.** "Where did her money go?"
       correctly answers "no outbound trail was found", produces no visualization, and
       so left the workspace showing ten thousand unrelated cases. A no-visualization
       answer now routes by its evidence ids (`flow:` → Financial, `hotspot:` →
       Geography, …) and the Financial view renders the negative finding AS a finding,
       distinct from "nothing has been asked yet".
    4. **Four natural phrasings of one question went to four different operations** —
       measured against the LIVE deployment, so the semantic interpreter was not
       rescuing them either: `"show everyone involved"` → CRIME_SEARCH, `"Who is
       connected?"` and `"Anyone connected to this case?"` → CASE_CONTEXT, `"Who does
       she run with?"` → NEXT_STEPS. Fixed as a question SHAPE (a who-word plus an
       involvement word), alongside `intents.py`'s existing shape patterns, rather
       than by adding one keyword per phrasing forever — and the same shape with a
       NAMED subject ("who is connected to Usha Naika") routes to PERSON_NETWORK,
       because that is a different population. 26 new tests, including the boundaries
       it must not cross.
  - **Also**: the case register and ⌘K lead with crime and place, identifier second;
    sign-in states what each rank can see, because rank is the scope of every answer
    that follows; the evidence column narrows to a strip when nothing is cited rather
    than spending a fifth of the workstation on "no sources yet"; charts animate in
    260ms instead of a second; `sourceLabel` stopped rendering "Fir record".
  - **One foot-gun closed on the way out**: `apps/web/.env.local` is the right way to
    point `next dev` at a local API (this pass needed one), and Next reads it during
    `next build` too — so on a developer machine that has one, a console deploy would
    have quietly shipped `http://localhost:8000` to every officer's browser. v9's
    guard in `scripts/deploy-console.sh` catches it; the script now also pins
    `NEXT_PUBLIC_API_URL` so it cannot happen at all.
  - **Verified by driving the real console over CDP at 1600×1000**, against a local
    API on the same 10,000-case dataset (16,918 graph nodes, 13,835 indexed docs): 19
    states in `docs/screenshots/2026-08-29-productization/`, zero console errors.
    `npx tsc --noEmit` clean; the static export re-verified against both v9
    invariants (`/app`-prefixed assets, no `localhost` in the bundle). Both automated
    live-behaviour gates re-run against the changed backend: `judge_flows.py` 26/26
    turns, `verify_live_deployment.py` 36/36 adversarial scenarios. Test suite: **631
    passed, 2 skipped** (27 new this pass).
  - **Not done this pass, named rather than silently skipped**: not deployed — the
    console needs `scripts/deploy-console.sh` and the three backend fixes need the
    relay pipeline; both are the operator's call. `apps/web` still has no test suite
    of its own and this pass did not add one — the frontend logic that broke
    (`lib/network.ts`'s id join) was caught by driving the console, which is the
    check this repo actually runs. QuickML's endpoint key, PDF export's SmartBrowz
    identity block and the `dowhy` exclusion are unchanged and were not re-
    investigated: no new information surfaced that would change any of them.

- **v20 (every important result becomes questionable) — an investigator can point at
  any derived result and ask WHY, and get an answer about the CLAIM rather than about
  the software.** The console could already show what was found and which records were
  cited. What it could not do was let an officer point at one line — one associate, one
  similar case, one hotspot, one timeline event — and ask *"why is this one here?"*
  - **The one place that question was already answered was answering the wrong
    question.** `EXPLAIN_REASONING` restated the agent trace: *"HippoRAG retrieval:
    Personalized PageRank from 15 seeded nodes; Cypher Agent: 12 associate(s) within
    policy depth"*. Every word true, none of it what was asked. An officer asking why
    two people are connected wants the FIRs they are both named on.
  - **`packages/rag_agent/rag_agent/provenance.py`** is the one mechanism. Given any
    evidence item it returns the same five things in the same order — CLAIM · BASIS
    (record / derived / model / prediction) · RECORDS · DERIVATION · WHY IT QUALIFIES —
    plus what the result does NOT mean, and the questions the engine can actually answer
    next about it. Dispatch is on the `evidence_id` prefix, a convention three other
    functions in `orchestrator.py` already parse, so this reads what is already there
    rather than adding a channel that can drift out of step with it. Twenty-two kinds
    have handlers, and a test enumerates the prefixes out of the source, so a new
    producer cannot add one without noticing. Explanations are derived on demand, never
    stored: the Data Store's text column is already tight, and an explanation computed
    from the record layer cannot go stale against it. Where a chain genuinely cannot be
    reconstructed it says so (`incomplete`) — a plausible-sounding fabricated chain is
    the exact failure this platform exists to prevent.
  - **The flagship is the co-offending chain.** "Why is this person connected?" now
    answers with the actual path — *"Usha Naika and Soom Nadkarni are both named as
    accused on FIR 100303002202400003 (Theft, Yadgir, filed 13 Jul 2024 — status
    Acquitted); FIR 100242402202400033 …"* — recomputed from the graph already in
    memory, policy-filtered per hop (a path may legitimately run through another
    station's case; the hop is still reported, the case is named only where the officer
    may see it). This is the claim the organizers' ER cannot make at all (§0), and the
    one an officer is most entitled to interrogate before acting on it.
  - **One explanation, two ways in.** `GET /explain` (new router) and the typed question
    call the same function, so a result explained by clicking and the same result
    explained by asking cannot give two different accounts. The console renders it
    through one component (`WhyChain.tsx`) in the evidence inspector, on a selected
    graph node, and on a selected case on the map.
  - **Click → investigate**: a selected map case and a selected graph node became
    investigation entry points — what this is, why it appears, the chain behind it, and
    only actions the backend actually supports (priors · timeline · trace money ·
    related cases · who was involved · add to board).
  - **Result truth**: every bounded, ranked or modelled answer now states what KIND of
    set it is — *"Result set: SAMPLE — 5 of 73 shown, filtered: every case matching the
    filters in your question, within your access scope"*. The quiet failure is the
    dangerous one: five cases under a question that asked for "the cases" reads as all
    of them.
  - **Contradiction checking**: the structured field beats the generated sentence. A
    case whose status is `Convicted` under prose saying "the investigation is being
    carried out" now carries a correction naming the recorded status, and a district the
    prose names that neither a cited record nor the question mentions is flagged. The
    prose is never rewritten — string surgery on a generated sentence produces a
    sentence nobody wrote and nobody can audit; naming the record's own value beside it
    leaves both on screen.
  - **Question shapes, not one keyword at a time**: "why is this person connected", "why
    is that a hotspot", "why is this case in the timeline", "how are you deriving all
    these", "show me the chain", a bare "why these?" — each used to score somewhere
    plausible and wrong ("connected" on PERSON_NETWORK, "hotspot" on HOTSPOT), running a
    FRESH search for the thing already on screen. `TIMELINE_CONNECTION` is now checked
    BEFORE the explanation branch, because "how are these connected" asks about the
    entities and is a real retrieval.
  - **Nine defects found by driving it, not by reading the diff** — each by typing the
    brief's own flows against a live API and clicking the console over CDP:
    1. **A false contradiction flag on a correct answer.** The district check read
       `sql_query_results`, which the timeline, graph and financial branches never
       populate — so a timeline citing five real FIRs in five real districts was told
       those districts appear "in none of the records cited here", with them printed in
       the citations directly above. A false positive here is expensive: an officer told
       the record says otherwise about a correct sentence learns to ignore the warning.
    2. **Citation chips disagreed with the answer beside them.** `resolve_plural_markers`
       ran AFTER citations were built from the same evidence content, so the answer read
       "1 hop away" while its own chip read "1 hop(s) away". Resolved before synthesis.
    3. **A truncated turn silently downgraded a RECORD to DERIVED.** `sessions._pack`
       dropped `evidence_items` wholesale over the text-column budget, and the timeline
       explanation read a missing `authoritative` as False — so a recorded transfer
       explained itself as a probabilistic identity inference. `_pack` now sheds BODIES
       and keeps IDENTITY (a middle tier: ids, source type/id, authoritative,
       confidence), and the event TYPE decides where the flag is genuinely absent.
    4. **"Where are the related cases?" refused with the cases on screen.** It scored
       HOTSPOT on the bare word "where" and ran cluster detection over a defaulted
       district; and once routed correctly, it read only the immediately previous turn —
       which was a meta-turn re-showing the same result. It now reads the last answer
       that actually SHOWED cases, and reads a case out of a timeline event's `ref_id`
       as well as out of a `fir:` citation.
    5. **"Why is that a hotspot?" reported the previous answer as having nothing to
       explain.** Two causes at once: "that A hotspot" matched no demonstrative noun, and
       the whole-answer branch read `evidence_items` with no citation fallback.
    6. **A two-person answer was explained one person at a time.** Grouping by kind is
       right for nine near-identical hotspots and wrong for two named people; three or
       fewer items are now each explained.
    7. **The chain printed "1 step(s) of co-accusation away"** — the marker convention is
       resolved on the synthesis path, and a chain reached by clicking never goes through
       it.
    8. **A multi-hop record list over-claimed.** Nine FIRs printed flat under a two-hop
       path read as "these nine connect you to this person"; the far person appears on
       only the last hop's cases. Each row now says which pair it links.
    9. **Selecting a cited case lit up no point on the map.** The same FIR arrives as
       `fir:1194` from the structured layer and `vec:fir_narrative:1194` from semantic
       search; the map read only the first, so on a hotspot answer — where every cited
       case comes from semantic search — the console behaved as though the case it had
       just cited were not on the map in front of it. One shared `caseIdOf()` reads both.
  - **Verified by driving the real thing.** The brief's nine flows run against a local
    API on the full 10,000-case dataset (16,918 graph nodes, 13,835 indexed docs), and
    the console driven over CDP at 1600×1000 with real `Input.dispatchMouseEvent`
    clicks — including a genuine force-layout graph-node click, which opened the card and
    traced the chain through named FIRs. Zero console errors. `npx tsc --noEmit` clean.
    Screenshots: `docs/screenshots/2026-08-29-explainability/`. Test suite: **670 passed,
    2 skipped** (39 new).
  - **Not done this pass, named rather than silently skipped**: not deployed — the
    console and the API each need their own pipeline, and that is the operator's call.
    The financial (Sankey) and trend views did not get a click-to-investigate panel of
    their own; the evidence inspector covers the same need for every evidence type they
    produce, and a view-native click target would be purely additive. `apps/web` still
    has no test suite of its own — the frontend logic that broke this pass (the
    `vec:`/`fir:` id join) was caught by driving the console, which remains the check
    this repo actually runs.

- **v21 (the questions nobody had typed) — a 1,701-input corpus of what an officer and
  a judge actually ask, and the ~430 of them the system was answering wrongly.**
  This pass started by conversing with the engine instead of reading it. Six questions
  in, an entire class of ordinary request turned out to be answered with a count of
  every case in the state plus five arbitrary FIRs — cited, confident, and about
  something else.
  - **CRIME_SEARCH was a black hole.** It read two qualifiers (crime type, district)
    and dropped every other word WITHOUT SAYING SO. Measured live: *"How many cases
    are pending in Mandya?"* → 263 (every Mandya case, of every status); *"Show me
    cases under section 379"* → 10,000 (every case in the state); *"Show me all cases
    from PS 2201"*, *"cases filed in June 2026"* → the same 10,000. Answering a
    different question than the one asked, in silence, is the worst thing this layer
    can do short of inventing a record. `sql_agent` now filters on **case status,
    police station, IPC section and date window** through ONE shared clause builder
    (`_filters`) that both the count and the sample list use — two copies of the same
    WHERE clause is how a count stops describing the list printed under it — and every
    answer states the filters it applied. A section filter selects the offence GROUP
    that carries the section (the ER attaches sections to a crime head, not to a case)
    and says so, rather than letting an officer discover it by noticing a burglary in
    a list of thefts.
  - **Two whole question classes had no home at all**, and both are the first things
    an officer asks. `OFFENDER_RANKING` — *"who is the most active offender in
    Mandya"*, *"top 5 habitual offenders"* — ranks people by how many cases NAME them,
    a recorded fact, never by PageRank or risk score, which are derived and modelled
    and do not mean "most active". This is the identity layer's payoff stated plainly:
    on the organizers' ER the question cannot be asked at all. `CASE_STATS` —
    *"conviction rate"*, *"which station has the most pending"*, *"most common
    offence"* — computes the rate over cases that actually reached a verdict, prints
    the denominator, and declines to rank IPC sections because the schema attaches
    them to offence types rather than to cases.
  - **"Does she have priors?" opened with a cheating case in Davanagere.** Twelve FIRs,
    no name, no count, no answer to the yes/no question actually asked. It now opens
    *"Yes — Usha Naika is named as accused on 19 cases on record within your access
    scope, of which 6 ended in conviction"*, with the cases as the working beneath it.
  - **The search box could not do two words.** `/cases?q=` tested whether the WHOLE
    query appeared inside ONE field, so *"theft mandya"* matched nothing while the
    register held sixty-one of them; a person could not be found at all, and neither
    could a section or a station. New `rag_agent/search.py` + `GET /search`: tokenised,
    every word must match SOMETHING across fields, ranked by WHERE it matched (exact
    FIR number ≫ structured field ≫ narrative/MO), people included and scoped so a
    name cannot be confirmed by an officer who may read none of their cases. Every hit
    carries **why** it matched, because a ranked list whose order cannot be explained
    is one an officer scrolls past. The register's own `q` uses the same tokenizer.
  - **Push-to-talk was a text button that said "Speak" and then "Stop".** Recording
    REPLACED the question field, so anything typed vanished; "Stop" SENT, so a
    recording that had gone wrong could not be abandoned; nothing said how long it had
    been listening; a denied microphone left the button reading "Stop" over a
    recording that did not exist; and nothing announced any of it. `VoiceRecorder.tsx`
    is a mic button that becomes a recording BAR — live level meter, elapsed timer,
    **Discard** and **Send**, a 60-second cap, real permission handling, an aria-live
    status — and the question field stays where it is.
  - **The corpora.** `tests/officer_inputs.py` (1,115 lines, generated from the
    dataset's own districts, offences, sections and stations, plus a curated awkward
    half) and `tests/judge_inputs.py` (586 lines of what a magistrate, defence counsel
    or supervising officer asks: *how did you decide*, *on what basis*, *could this be
    wrong*, *is your output evidence*, *do you decide guilt*). Checked as PROPERTIES —
    each line must reach an operation that would be a DEFENSIBLE reading of it, never
    a confidently wrong one. **88 of the officer corpus and 338 of the judge corpus
    misrouted on first run.** Both are 0 now.
  - **What those 426 misroutes actually were**, by class: "convicted" was a
    PERSON_HISTORY keyword and is a case STATUS, so *"show me convicted theft cases in
    Bagalkot"* returned somebody's criminal record; word-bounded keywords never matched
    their own plurals, so "area"/"transfer"/"trend" missed *"areas"*, *"transfers"*,
    *"what are the crime trends"*; `criminals?` matched the first word of *"Criminal
    Breach of Trust"*, turning a district ranking into a leaderboard of people; a bare
    *"Hurt in Ballari"* matched nothing at all, because CRIME_SEARCH's keyword list
    carries three offence names out of twenty; and the whole explanation surface was a
    list of phrasings, so *"How did you determine this?"*, *"On what basis?"*, *"Where
    does this come from?"* (a hotspot map, on the word "where") and a bare *"why?"*
    each ran a FRESH search for the thing already on screen.
  - **`_EXPLAIN_REASONING` and `_EVIDENCE_FOR` are shapes now, not phrase lists** —
    built from a named derivation-verb class and a demonstrative class, with a
    `_WORLD_QUESTION` guard so *"why is crime higher in this district"* stays causal
    analysis rather than becoming provenance.
  - **A question about this system's STANDING gets its own answer.** *"Do you decide
    guilt?"*, *"Is your output evidence?"*, *"Can this be used in court?"*, *"Is this
    biased?"*, *"Do you ever guess?"*, *"Is there an audit trail?"* all reached UNKNOWN
    or, worse, a retrieval — *"Is this biased?"* was answered with a person's priors.
    They now route to CAPABILITY **and** each gets a specific paragraph
    (`_STANDING_ANSWERS`), because a judge handed a feature list in reply to "do you
    decide guilt" has been answered in form and not in substance.
  - **"Who would you arrest?" was answered, not refused** — the suspect-nomination
    guard needed the word "guilty" or a completed verb of commission, and missed every
    imperative form.
  - **A chain of audit questions walked backwards one turn at a time.** *"How did you
    decide this?"* then *"Could this be wrong?"* explained the EXPLANATION, not the
    result both were about. `_last_substantive_turn` skips meta-turns, re-classifying
    each stored turn from its OWN query — a meta-turn deliberately carries the prior
    substantive request forward under `last_request`, so reading `result_context`
    reports it as substantive.
  - **Also fixed by driving it**: a statistics answer captioned an unfiltered 263 as
    "in Mandya · status Convicted" because "conviction rate" was read as a status
    FILTER rather than as the metric's name; the sections-unavailable note promised an
    offence-type breakdown and then printed the status one; `crime_count:any:any` was
    the evidence id for two unrelated searches; rankings and statistics were padded
    with five irrelevant semantic hits, burying "conviction rate 59%" at citation [2]
    of 7; the recording bar overflowed a 390px column and pushed the Ask button off
    the panel; and the palette rows crammed six fields onto one line, truncating the
    location an officer scans for.
  - **Provenance handlers added** for every new evidence kind — `offender:`,
    `ranking:`, `stats:`, `priors:` — so the enumerate-the-prefixes test still passes
    and *"why is this person top of the list?"* answers with the count and what it is
    a count OF, never with the model's opinion.
  - **Verified by conversing, not by reading**: multi-turn sessions driven against a
    local API on the full 10,000-case dataset, and the console driven over CDP for the
    voice control (typed text survives a recording; Discard sends nothing) and the
    search palette (*"theft mandya"* → eight real Mandya thefts, each captioned
    "matched crime, district"). Zero console errors; `npx tsc --noEmit` clean.
    Screenshots: `docs/screenshots/2026-08-30-voice-and-search/`.
  - **Test suite: 740 passed, 2 skipped** (70 new).
  - **DEPLOYED and live-verified.** Console via `scripts/deploy-console.sh`; API via
    the relay pipeline (`get-signature?name=veritas-api` → `.github/relay-upload.url`
    → `relay-deploy.yml` → local `appsail/upsert` with the BARE base64 object key —
    the `CLI/Orphan/` prefix is rejected as `INVALID_INPUT`, which cost a cycle to
    find). Both live gates re-run against production: `judge_flows.py` 26/26,
    `verify_live_deployment.py` 36/36. The new operations verified by hand on the live
    URL — *"how many cases are pending in Mandya"* → 85 (not 263), the offender
    ranking, the 59% conviction rate with its denominator, *"do you decide guilt"* →
    the standing answer, *"who would you arrest"* → refused. Live console driven over
    CDP: mic control present, ⌘K search returns real Mandya thefts captioned "matched
    crime, district", zero console errors.
  - **One regression the live gate caught that the corpus did not**: tightening
    CAPABILITY to require an object verb turned *"What all can you actually answer for
    me?"* into UNKNOWN — an adverb sits between the pronoun and the verb. Fixed,
    added to the corpus, redeployed.

- **v22 (a `double` column corrupting its own values) — found by driving the console,
  not by reading a stack trace, and traced all the way into a Data Store platform
  constraint neither this file nor `data/data/provision.py`'s own reasoning had named
  correctly until this pass.
  - **"Who are the associates of Usha Naika?" rendered most of the network as copies
    of Usha Naika.** The five real direct co-offenders showed correctly; every more
    distant associate — reached the same query, same graph, same code path — rendered
    with the subject's own name over and over. Confirmed against the deployed
    `NetworkView.tsx` bundle first (pulled and diffed the live JS against this repo's
    source, module-for-module identical) to rule out a stale build before looking
    anywhere else.
  - **The graph view's own root-node sentinel was firing on real associates.** The
    engine flags the query's subject with `pagerank: 1.0` (`synthesis_agent.py` says so
    in its own comment) so the console can size it as the root; `isRoot()`
    (`apps/web/lib/network.ts`) reads `pagerank >= 1` as "this is the subject," and
    every associate whose *real* PageRank had come back corrupted above 1 tripped that
    same check — rendering as a second copy of Usha Naika rather than themselves.
  - **The corruption was in the live Data Store, not in this codebase's query or graph
    logic.** Queried the deployed API directly and diffed against a clean, freshly
    generated copy of the same dataset: `vx_person.PageRank` for every co-offender whose
    true centrality sits below roughly 0.0001 came back 10,000-100,000x too large —
    `0.000851196807533056` (Nithin Madar) stored and returned as `8.5119`;
    `0.0000781711...` (Suma Nadkarni) as `7.8171`. Every case checked fit the same
    shape: strip the value's scientific-notation exponent and what's left is exactly
    the corrupted number.
  - **The wrong lever, corrected.** `data/data/schema.py`'s `_MAX_LEN["double"]` (17)
    looked like the obvious knob — Data Store's column API does accept a `max_length`
    for a `double` — and the first fix widened it. Checked live before trusting that
    fix: a column-update request explicitly asking for `max_length: 25,
    decimal_digits: 12` on the live `PageRank` column came back `status: success` with
    the returned spec *unchanged* at `max_length: 15, decimal_digits: 4`. Data Store
    silently clamps every `double` column to that precision — a hard DECIMAL(15,4) —
    regardless of what a provisioning or update request asks for. No number in
    `schema.py` was ever the real constraint; left at 17, with a comment saying why,
    rather than claiming a control that does not exist.
  - **The second wrong fix, caught by not trusting a deploy that "finished" without
    visibly changing anything.** `data.ds._sdk_row` — the one place every Catalyst
    write already gets normalized before the SDK JSON-serializes it — first shipped
    `round(v, 4)`: a plain Python float, never in scientific notation by Python's own
    rules. Deployed, triggered `POST /jobs/refresh` to rewrite `PageRank`/`Betweenness`
    through it, and the associates query came back exactly as corrupted as before.
    Repeated triggers all returned `{"status": "started"}` — meaning each run's lock
    was already free, i.e. finishing fast, not hanging — with nothing fixed. Rather
    than assume the fix just needed more time, round-tripped the *exact* row-write
    REST endpoint the SDK's `update_rows()` calls, directly, with the admin token: a
    bare JSON *number* `0.0009` came back `400 INVALID_INPUT ("Please give a correct
    double value")` — rejected outright, which is almost certainly why a batch write
    containing any such value fails silently inside the refresh job's caught
    exception. A plain fixed-point *string* `"0.000851196807533056"` round-tripped
    correctly (`8.0E-4`) at every magnitude tried, including `"123.4567"` back exactly.
    But a string that still *contained* scientific notation —
    `"7.817113529341168e-05"` — came back `7.8171`, reproducing the exact original
    corruption: this really is a text-level `E`-notation defect on Data Store's
    ingest, independent of JSON type, and no `float`-side rounding fixes it unless the
    string sent is also guaranteed exponent-free.
  - **The fix that actually held**: every `float` through `_sdk_row` is now formatted
    `f"{v:.4f}"` — a string, always plain decimal, never `e`/`E`, at the same precision
    the column already enforces. Redeployed, triggered `/jobs/refresh` again, and the
    associates query came back correct within a minute: all 41 nodes distinct names,
    real magnitudes (`0.0101` down to `0.0001`), zero nodes at or above `1`. This
    protects every `double` column in the schema — `RiskScore`, `Betweenness`,
    `MatchConfidence`, `FlagConfidence`, `Weight`, `Confidence`, financial `Amount` —
    not just `PageRank`, since they all share the one write path. Test:
    `test_sdk_row_formats_floats_as_exponent_free_decimal_strings`, `data/tests/test_ds.py`.
  - **Deployed twice, and the already-corrupted values repaired live**, not just the
    code: relayed to AppSail (`get-signature` → `.github/relay-upload.url` →
    `relay-deploy.yml` → local `appsail/upsert`) to deployment `52852000000355160`
    (the `round(v,4)` attempt, later proven wrong) and then `52852000000356181` (the
    `.4f`-string fix, confirmed live). `POST /jobs/refresh` on the second deployment
    ran `data.gds.run_all()` through the now-genuinely-fixed write path, rewriting
    `PageRank`/`Betweenness` for every person — self-healing the two columns this pass
    actually proved broken, rather than a schema change alone that would have left
    every existing row corrupted. Console redeployed too (`scripts/deploy-console.sh`)
    carrying an unrelated fix from earlier in this session: the sign-in screen's roles
    reordered by operational hierarchy (IG → SCRB Analyst → SP → DSP → SHO → IO) and
    its em dashes removed.
  - **Test suite: 741 passed, 2 skipped** (1 new).
  - **Audited every other `double` column against live, exhaustively rather than by
    sample, and found nothing else to repair.** `RiskScore` (`vx_person`) and
    `FlagConfidence` (`vx_txn`) are never actually written in this codebase — the
    former is scored on demand per query and never persisted, the latter would be set
    by an AML detector job that has never run against this live dataset (0 flagged
    transactions in all 2,354 rows) — so there was nothing to corrupt.
    `MatchConfidence` (`vx_accused_identity`, all 17,315 rows): `[0.90, 1.0]`, matching
    the code's own `LINK_THRESHOLD` floor exactly. `Weight` (`vx_graph_edge`, 20,000+
    rows sampled): `1.0`-`26.0`. `Amount` (`vx_txn`, all 2,354 rows): `₹501.81`-
    `₹1,426,326.50`. `Confidence` (`vx_case_board_item`, all 11 rows, 3 non-null):
    `0.6`-`0.97`. The five socioeconomic columns (`vx_district_socioeconomic`, all 30
    districts): real Census 2011 ratios and percentages, all plausible.
    `CaseMaster.latitude`/`longitude` (all 10,000 rows): within Karnataka's real
    bounds. None needed repair, and the reason is structural, not luck: corruption
    only strikes a magnitude below ~0.0001, and every column here is either never
    actually populated or has a domain floor well above that (confidence scores
    bounded at 0.90+, rupee amounts in the hundreds, edge weights ≥1, real-world
    ratios, real coordinates). Only `PageRank`/`Betweenness` — raw graph centrality
    over a 17k-node graph — legitimately produce values that small, which is why they
    were the only ones that actually broke.
  - The exact internal mechanism on Data Store's side that rejects a bare
    small JSON number yet corrupts a scientific-notation string was established with
    high confidence from the pattern across every case checked, not from Zoho's own
    source or documentation.

- **v23 (the analytical tabs stop asking a question to fill themselves) — every
  workspace tab preloads from the records, Statistics becomes a real dashboard, and
  three defects the pass found by driving it rather than reading it.**
  - **A tab was filling itself by firing a canned English question at the
    orchestrator.** `Workspace.tsx` held an `AUTO_ASK` table — "Show me crime
    hotspots", "What is the conviction rate?" — pushed through `/chat` as a silent
    turn. That is the right mechanism for a QUESTION and the wrong one for a TAB,
    and it was wrong three ways at once: a turn's evidence is the LAST turn's
    evidence, so opening a second tab destroyed the first one's contents, and the
    `autoFired` guard that stopped the preload re-firing then left the revisited tab
    loading forever; the preload appeared in the officer's own transcript and
    evidence column, so the console showed questions nobody had asked and citations
    for them; and an intent classification, a retrieval pass and a CRAG evaluation
    are real work, none of which is needed to answer "count these rows".
  - **`GET /analytics/*`** (new router, 8 endpoints) calls exactly the same
    policy-scoped functions the corresponding orchestrator handlers call —
    `ranked_offenders`, `status_breakdown`, `counts_by`, `district_socioeconomic`,
    `flagged_transactions`, `station_workload`, `community_case_profile`,
    `fir_points`, `gds.community_members`, `prediction_agent.hotspots/forecast` — and
    returns the STRUCTURED rows instead of sentences built from them. No new query
    logic and no widened scope: RBAC is the officer's own role and station passed
    into those same functions, so the filter stays inside the query exactly as it is
    for `/chat`. Verified live at IO rank (81 cases, 1 district, 1 station, masked
    names) and 401 unauthenticated on all eight.
  - **The conversational path is untouched and still WINS.** Where a chat answer has
    produced a view's result — with its own scope, citations and refusals — that is
    what renders; the fetched data is only the default the tab opens on. On
    Statistics the two are shown APART ("From your last question" above the
    dashboard) rather than merged, because the answer is usually district-scoped and
    the dashboard is statewide, and silently combining them would caption one scope's
    number with another's.
  - **Statistics is an actual analytics dashboard** (`viz/StatsDashboard.tsx`): five
    KPI tiles, 36 months of case volume, a status donut, and ranked offence /
    district / station bars — all from ONE scan (`sql_agent.dashboard`, five
    groupings of the same rows rather than five scans of them, 0.28s over 10,000
    cases). Every figure is a count of records; the conviction rate prints its own
    denominator beside it. Colour is the neutral analytical blue, not the severity
    ramp — a tall bar means "more cases recorded", which is not the claim "more
    dangerous". Area Profile, Community, Watchlist and Workload get structured
    renderings for the same reason a ranked list read out one sentence at a time is
    a list an officer scrolls past.
  - **`/jobs/refresh` rebuilt four INDEPENDENT derived layers inside ONE try/except**,
    so the first raise silently skipped everything after it. `publish_graph()` is step
    two and writes to Stratus, whose bucket creation is scope-blocked on this org (§2,
    `OAUTH_SCOPE_MISMATCH`) — so a blocked CACHE publish was able to cancel the AML
    detector sweep, a RECORD-layer rebuild. Each step now runs in its own try and
    names itself when it fails. Found live; the failing test was confirmed to fail
    against the pre-fix code first.
  - **`sync=true` added to `/jobs/refresh`**, the same escape hatch
    `/jobs/audit-verify` already carries (BUG-027). Not a convenience: AppSail exposes
    bundle-creator logs and **no runtime logs**, so a step failing inside a background
    thread is invisible from outside and `{"status":"started"}` is all a caller ever
    learns. Diagnosing a background job through a log nobody can read is not
    diagnosis. Cron must never use it — the recompute takes minutes and the gateway
    kills the request long before that, which this pass also confirmed live.
  - **`useAnalytics` reintroduced the exact bug it was written to remove, and a live
    session caught it.** The obvious `let live = true; return () => { live = false }`
    cleanup is wrong here: `enabled` flips false the moment the officer clicks another
    tab, which re-runs the effect and fires that cleanup — so the response is thrown
    away while the "already started" marker stays set and blocks any re-fetch. The tab
    then spins forever on every later visit. Reproduced deterministically (open
    Forecast, leave after 500ms, return) and A/B'd: old hook still spinning after 50s,
    new hook "≈74 cases projected" with a rendered chart. A result is now accepted
    whenever it still matches the key that asked for it — a stale ANSWER is one for a
    scope nobody is looking at, not one that arrived while the officer glanced away.
  - **Also fixed**: an influence/caseload meter's fill had `flex: 1 1 auto`, which
    silently won over its own percentage width, so every row rendered the same length
    and the ranking the column exists to show disappeared; "1 police stations"; and a
    "top 10" caption on a chart with one row in it — both visible on an IO's own
    dashboard.
  - **The live Financial Watchlist is empty, and that is correct.** The detectors run
    and are reachable live (`AML Detectors (structuring + GNN): 0 flag(s)` in a real
    trace, beside `Graph Agent (money trail): 60 transfer path(s)` — so the financial
    layer is populated); the live transaction set simply contains none of the
    structuring patterns the local dataset has. The UI states it as a checked absence,
    not a failed search. Not regenerated: manufacturing flags on a live dataset to
    make a tab look busier is exactly the casual regeneration this project's rules
    exclude.
  - **One operational rule learned the hard way**: the console and the API are ONE
    deploy when a new endpoint is involved. The console is a static export that calls
    the live API by absolute URL, so shipping it first put 8 of 15 tabs into a 404
    state on production until it was rebuilt from the previous commit and redeployed.
    API first, confirm the route answers, then console.
  - **Deployed and live-verified**: API deployments `52852000000392006` /
    `52852000000390017`, console via `scripts/deploy-console.sh`. All eight routes
    answer live; all nine tabs preload with **zero turns in the copilot transcript**;
    a typed question still overrides (`hotspots in Mandya` → 263 cases, 4 hotspots,
    real citations) and `Who are the associates of Usha Naika?` renders the 40-node
    graph with distinct names and 12 citations.
  - **Test suite: 802 passed, 2 skipped** (32 new — 6 pinning that the dashboard's
    five breakdowns all sum to the same total it reports, 20 pinning that every
    analytics endpoint is authenticated and rank-scoped, 6 on refresh-step isolation).
    `npx tsc --noEmit` clean. Screenshots:
    `docs/screenshots/2026-09-02-preloaded-analytics/`.
