# Veritas

### A conversational crime-intelligence platform for the Karnataka State Police

An officer asks a question — typed or spoken, in English or Kannada — and gets an answer
where **every claim traces back to a specific police record**. Not a summary that *sounds*
right: an answer whose each sentence carries a citation chip that opens the exact FIR,
person, account, or transaction it came from. And when the records don't support an answer,
Veritas says exactly that instead of inventing one.

> **KSP Datathon 2026 · Challenge 01.** Built end-to-end and running live on Zoho Catalyst.
> The full design rationale for every decision lives in [CLAUDE.md](./CLAUDE.md); this
> document is the complete tour.

| | |
|---|---|
| **Live API** | `https://veritas-api-50043864344.development.catalystappsail.in` — deployed, enabled, serving |
| **Live console** | `https://veritas-60077763394.development.catalystserverless.in/app/index.html` |
| **Identity resolution** | **F1 0.989** (precision 0.997, recall 0.981) against the generator's answer key |
| **Test suite** | **606 passing**, no database or Docker required — `python -m pytest` |
| **Live footprint** | 10,000 FIRs · ~105k rows · graph of 16,918 nodes / 87,120 edges · 13,835 indexed documents |
| **Platform** | Zoho Catalyst — one AppSail container, Data Store, File Store, Cache, QuickML LLM, Cron |

---

## The problem this exists to solve

A modern police force does not lack data. It drowns in it. Every FIR, every accused, every
seized account, every station transfer is recorded somewhere — and almost none of it is
*connected*. An investigating officer who wants to know whether the man in front of them has
a history has to remember the right case numbers, know which colleague worked them, and read
each file by hand. The knowledge exists; it is simply not reachable in the moment a decision
gets made.

Two forces make this worse. The first is language: an officer thinks and speaks in Kannada,
but the systems answer in English and the query box expects a schema, not a sentence. The
second is trust: the one thing a law-enforcement tool can never do is make something up. A
plausible-sounding wrong answer is not a small bug here — it is the difference between a lead
and a wrongful accusation.

Veritas is built for exactly that moment. Ask a plain question, get a grounded answer, see
the records it rests on, and — this is the part that matters — get told *"not found in the
available records"* when the honest answer is that nothing supports the claim.

---

## The one fact that shaped everything

The organizers gave us an entity-relationship schema — the `Police_FIR_ER_Diagram.pdf` in
this repo — and we reproduce it **verbatim**: 27 of their tables, their exact names, their
exact spelling. Conformance is a hard requirement, and a test suite fails loudly if anyone
"improves" it.

And that schema has a hole at its centre, one that quietly defeats every naive approach:

> **The ER has no concept of a person.**

There is an `Accused` table, but each row belongs to exactly one case, and its `PersonID`
column is a *per-case sort label* — "A1", "A2" — not an identity. Nothing in the data says
the "Ramesh Gowda" on case 412 and the "Ramesha Gouda" on case 908 are the same man. Read
literally, the schema claims that:

- every offender is a first-timer, so *"does he have priors?"* has no answer;
- nobody co-offends with anybody, so there is no criminal network to analyse;
- a bank account cannot belong to a human, so a money-laundering layer is meaningless;
- a "person" page could only ever show a single case.

A team that just writes SQL against this ER cannot answer the questions a detective actually
asks. So **identity has to be inferred**, and that inference is not a nice-to-have bolted on
the side — it is the load-bearing centrepiece the entire platform stands on. We reconstruct
people from `Accused` rows using **Fellegi–Sunter probabilistic record linkage** (the 1969
method that is still the statistical foundation of the field), and measure it against the
data generator's own answer key: **F1 0.989**, precision 0.997, recall 0.981.

Once people exist, everything downstream becomes possible — priors, co-offending networks,
account ownership, risk over a criminal history. That is why the pipeline runs in exactly
this order, and why identity can never move:

```
schema → real Census ground truth → generate → load records
       → RESOLVE IDENTITIES → financial layer → graph edges → graph algorithms → embeddings
```

Each step genuinely depends on the one before it. This ordering *is* the architecture.

---

## What an officer can ask

Every one of these runs today, against live data, with citations.

| Question | What Veritas does |
|---|---|
| *"Does Ramesh Gowda have prior cases?"* | Reconstructs his identity across cases the database never linked, and answers with the specific case numbers — even when his name is spelled three different ways. |
| *"Show me crime hotspots in Kolar."* | A kernel-density heat map computed from real incident coordinates, with DBSCAN cluster cores, rendered on a real MapLibre basemap (OpenFreeMap, OSM-derived) — only a tile z/x/y for the viewport crosses the network, never an FIR's exact coordinates. |
| *"Who does he operate with?"* | A co-offending network derived from the records; community detection surfaces organised groups — labelled honestly as *derived communities*, because the records name no gangs, so neither do we. |
| *"Trace the money from this account."* | Follows transactions through the financial layer, renders the flow as a Sankey diagram, and flags laundering with both a court-auditable rule detector and a graph neural network. |
| *"Will burglaries rise next month in this district?"* | A statistical forecast with uncertainty bands, reconciled so a district's forecast always equals the sum of its stations' — optimal, not merely close. |
| *"ಕೊಲಾರದಲ್ಲಿ ನಿನ್ನೆ ಏನಾಯಿತು?"* | Kannada in, Kannada out. Speech-to-text and translation run **inside our own container**; police text never leaves the network to reach a third-party API. |
| *"Give me everything on this open case."* | The Investigation Copilot: a chronological timeline, the five most similar past cases and how they resolved, ranked investigative leads, and a paste-ready case-diary paragraph. |
| *"Pin this to the case board."* / *"What have we established so far?"* | A persistent, editable **Investigation Board** per case — pinned evidence, derived findings, leads with status, notes — that survives a refresh, a new chat session, and a new officer's login. |
| *"Show me events involving both of them."* / *"What happened before this?"* | A **cross-entity timeline**: one chronological list spanning a case's own dates, its accused's arrests, their OTHER cases, and money through any account they own — each event traced to a real record, never inferred from two events merely being close in time. |
| *"Only these?"* / *"The second one."* / *"What about her?"* | Result-set follow-ups, ordinal/positional reference, pronouns and mid-conversation corrections resolve against what the conversation already established, not a fresh unrelated search. |

Every answer carries numbered citation chips that open the underlying record in a floating
evidence drawer. An expandable **Reasoning Trace** panel shows *how* the answer was assembled,
in plain language. And every interaction lands in a tamper-evident audit log.

---

## How an answer earns trust

This is the heart of the system, because "grounded and honest" is not a slogan here — it is a
pipeline of named, published methods, each doing a specific job.

**Retrieval is two research methods, not ad-hoc embedding search.**

- **HippoRAG** (Gutiérrez et al., *NeurIPS 2024*) — extract the entities in the question, seed
  a **Personalized PageRank** walk from them over the knowledge graph, and read off the
  highest-scoring nodes. One graph pass gives genuine multi-hop retrieval without an LLM in
  the loop, which is where its 10–20× cost saving over agentic retrieval comes from.
- **Think-on-Graph** (Sun et al., *ICLR 2024*) — for deep multi-hop questions where HippoRAG's
  confidence is low, beam-search entity/relation paths across the graph. It produces a
  *traceable reasoning path*, not just an answer.

**Verification is a corrective loop, not a hope.** A **CRAG-style evaluator** (Corrective RAG,
Yan et al., 2024) scores each retrieval batch for relevance and confidence, then triggers one
of three actions: **accept**, **widen the search and retry**, or — when the evidence is empty —
**explicitly state "not found in the available records."** It never fabricates on empty
evidence. This is the single strongest trustworthiness property in the system, and it is a
published pattern, not an improvised guardrail.

**The LLM makes answers fluent; it never makes them true.** The language layer is GLM-4.7-Flash,
served through Catalyst's own QuickML — so there is no third-party API key anywhere in the
image. Every possible provider failure (quota, network, 5xx, bad credentials) collapses to a
single signal, and the **deterministic paths — intent templates plus extractive synthesis —
take over and still produce grounded, cited answers.** The model polishes the prose; the
retrieval and the citations are what make the answer correct. And the model never sees
Kannada: a Kannada query is translated to English *inside our container* before the model is
called, then the answer is translated back.

**Policy is enforced where it cannot be undone.** Role-based access is checked in two places
on purpose. In the API middleware, for structured responses whose shape is known and can be
masked after the fact. And — crucially — inside the reasoning engine at *query-construction
time*, because **you cannot un-traverse a graph and you cannot reliably redact a name out of
generated prose.** So an investigating officer's station filter becomes a `WHERE` clause
*inside* the query, and their role's traversal-depth cap bounds the graph walk *before* it
runs.

**The audit trail is tamper-evident by construction.** Every log row carries the hash of the
row before it — `ChainHash = sha256(PrevHash ‖ ResponseHash)`. Editing or deleting any row
breaks every hash after it, and repairing that means rewriting the entire tail of the log. The
database cannot make tampering *impossible*, but the chain makes it **undeniable** — and a
Catalyst Cron job re-verifies the whole chain every twelve hours, because a tamper check that
nobody runs is not a tamper check.

---

## The intelligence layer

Underneath the conversation sits a genuine analytics stack. Each component was chosen because
it is the right method for the problem, and each reports its own uncertainty.

**Identity resolution — the centrepiece.** Fellegi–Sunter probabilistic record linkage
reconstructs people from `Accused` rows (F1 0.989). Everything else depends on it existing.

**The knowledge graph.** A flat `vx_graph_edge` table materialises into an in-memory NetworkX
graph on demand. Node ids carry their own type — `person:412`, `case:1043`, `acct:77`,
`loc:Kolar`. Every Neo4j GDS procedure we would have used is ported exactly: `gds.pageRank`
→ `nx.pagerank`, `gds.louvain` → `nx.community.louvain_communities`, `gds.betweenness` →
pivot-sampled Brandes–Pich. Money edges (`TRANSFERRED_TO`) are deliberately *directed* —
reversing them would invent a payment that never happened. The graph algorithms run on the
**co-offending projection**, not the whole graph, because over the whole graph every case
joins to its district and the whole state collapses into one useless "community." On the right
projection, Louvain recovers **12 organised groups of realistic size**.

**Forecasting.** Prophet models each station, then **MinT reconciliation** (Wickramasuriya,
Athanasopoulos & Hyndman, 2019, *JASA*) guarantees a district's forecast equals the coherent
sum of its stations' — statistically optimal, not eyeballed.

**Hotspots.** Gaussian KDE (Scott's rule) plus DBSCAN (`eps=500m`) — methods that never
depended on PostGIS *functions*, only its storage, so dropping PostGIS changed nothing.

**Risk and recidivism.** XGBoost risk scoring with **exact TreeSHAP** explanations (taken from
XGBoost's own `pred_contribs` — identical math, without dragging in a 240MB dependency chain);
a calibrated LightGBM 180-day recidivism model; Isolation Forest district-spike alerts pushed
live over a WebSocket.

**Financial crime.** Two detectors, on purpose. A **rule-based structuring detector** a court
can audit line by line, alongside a **graph neural network** that catches coordinated
multi-account layering the rule structurally cannot see. The rule is the one that testifies;
the GNN is the one that catches the clever launderer.

**Causality.** A DoWhy layer over real Census 2011 data — and it **names its unmeasured
confounder** (police strength is not published per district in India) rather than adjusting for
a column it fabricated.

Two rules here are enforced by tests, not merely stated. **A detector's output is never the
generator's input** — the injected laundering ground truth is written to a file, never to the
column the detectors score, so no classifier is quietly measuring its own label. And **no
protected attribute ever reaches a model** — `CasteID` and `ReligionID` are stored because the
ER declares them, but no model reads them. Storing is not scoring.

---

## Responsible AI, taken seriously

Predictive policing has a documented history of laundering historical bias into an
apparently-objective score: over-policing produces more recorded crime, which "predicts" more
crime in the same place, which justifies more policing. Any serious evaluation of a tool meant
to influence real policing will expect this addressed head-on. Veritas does:

- **No protected or proxy attribute is ever a model feature.** Gender is kept only as a
  *subgroup label* so the fairness audit has an axis to test against — never as an input.
- **Aequitas** (Saleiro et al., 2018 — the toolkit built for criminal-justice risk tools and
  applied publicly to COMPAS) audits disparate impact and false-positive/false-negative parity
  across demographic *and geographic* subgroups. Geography is the axis that catches the
  over-policing feedback loop, and it is the one a naive audit leaves out.
- **Human-in-the-loop by design.** Every prediction is decision-support. Nothing in the system
  is an automated trigger.
- **Explicit uncertainty.** Confidence intervals, SHAP explanations, and a UI that visibly
  distinguishes *"the model suggests"* from *"the record shows."*

---

## Built entirely on Zoho Catalyst

The competition rule is strict: deployment on Catalyst is mandatory, and using a third-party
service *where a Catalyst equivalent exists* can invalidate the submission. The organizers
clarified that where **no** Catalyst service exists for a capability, a self-hosted alternative
is permitted.

The distinction the rule draws is between **services** and **libraries**. NetworkX, LangGraph,
XGBoost, DoWhy, Whisper and NLLB are not external services — they are libraries running *inside
our own container, on Catalyst compute*. They are the product. What genuinely had to go were
the external *services*, and every one was replaced by its Catalyst equivalent:

| Capability | Now runs on | Replaced |
|---|---|---|
| API runtime | **AppSail** (custom OCI container) | self-hosted uvicorn |
| Console hosting | **Web Client Hosting** | Next.js dev server |
| Identity | **Catalyst Authentication** | self-signed JWT |
| Relational store | **Data Store** (ZCQL), 37 tables | PostgreSQL + PostGIS |
| Object storage | **File Store** (model weights) | filesystem |
| Session cache | **Cache** | none |
| Language model | **QuickML LLM Serving** (GLM-4.7-Flash) | Google Gemini |
| Scheduling | **Cron** (refresh 6h, audit-verify 12h) | none |
| PDF export | **SmartBrowz** | headless Chrome |

Four capabilities stay self-hosted — and each is an **absence, not a preference**, because
Catalyst genuinely offers no service for it:

- **Kannada speech and translation.** Zia has Face Analytics, OCR, Object Recognition, Text
  Analytics — but *no* speech-to-text, *no* text-to-speech, *no* translation. Swapping would
  have deleted working Kannada voice input. So Whisper and NLLB-200 run in-container.
- **The vector index.** QuickML's RAG is a managed upload-documents pipeline with no
  arbitrary-embedding store and no custom retrieval hook — HippoRAG's Personalized-PageRank
  seeding cannot run inside it. So it is numpy over our own embeddings.
- **The knowledge graph.** No Catalyst service is a graph database. NetworkX over an edge
  table, every algorithm ported exactly.
- **Audit-log immutability.** Data Store has no rules and no triggers, and app-layer
  "append-only" enforced by the same code that could bypass it is strictly weaker — so
  immutability was rebuilt *in the data* as the hash chain.

---

## The engineering that makes it real

A design that runs on the demo laptop is a prototype. Getting Veritas live on Catalyst meant
solving a set of constraints the platform does not document — each cost real time, and each is
worth naming because it is the difference between "should work" and "is serving traffic right
now."

**Fitting the image through the bundle sandbox.** AppSail unpacks a deployed image in a ~5GB
scratch space that must hold roughly four copies at once (the tar, its blobs, the staged
layers, the extracted rootfs). That caps a deployable image at about **1.3GB** — images of
9.31GB, 4.66GB and 1.61GB all died there. So the image was cut to **0.88GB**: the ~760MB of
NLLB and Whisper weights moved *out* of the image entirely into **Catalyst File Store** (eight
95MB chunks, streamed and spliced straight into CTranslate2 and Whisper at cold start, never
written to disk as one file); NLLB converted to int8 (600MB, replacing a 2.4GB checkpoint that
had been accidentally baked in *twice*); CPU-only ML wheels; TreeSHAP from XGBoost's own code
instead of a 240MB dependency chain.

**Deploying from a home connection.** A residential uplink can't finish the image upload inside
Catalyst's 30-minute signed-URL window, so **deploys relay through GitHub Actions**: the runner
pulls the image from Docker Hub and uploads it datacenter-to-datacenter in minutes, then a
small authenticated callback turns the upload into a running deployment.

**Live Data Store behaves differently from any SQL you'd test against.** These were found by
driving the *real* service, and each has a fix baked in:

- **ZCQL refuses every JOIN in the codebase** — the ER relates by business key, not by foreign
  key, so the live store answers "no relationship between tables." Reads therefore run against a
  **local SQLite mirror** hydrated from the Data Store once per container; writes go to the Data
  Store first, the mirror second. A bonus fell out of this: schema-typed hydration killed a
  whole class of bug where the live store returns every value as a string (`"4"`, not `4`).
- **Pagination duplicates one row at each page boundary, even under `ORDER BY`.** Paged reads
  dedupe on row id; hydration inserts-or-ignores. (Thirteen "phantom duplicates" once deleted by
  hand turned out to be this artifact, not real duplicates — and were restored.)
- **The SDK JSON-serializes writes**, so datetimes have to be Data Store display strings — a raw
  datetime 500'd every audited endpoint while SQLite silently accepted it.
- **The SDK's context is per-request headers, not environment** — a bare `initialize()` raises
  "Catalyst headers are empty" inside AppSail, so middleware captures each request's context and
  background work reuses it.

The through-line: the local SQLite backend is **not a mock**. ZCQL is a subset of SQL, so
SQLite executes the *exact query strings* the deployed service sends to the Data Store. A query
that passes the test suite is a query the Data Store will accept — which is why the RBAC rules,
the part a government panel will actually poke at, run on every single commit.

---

## What's live and verified right now

- **The API is deployed, enabled, and serving** on Catalyst AppSail. Health reports
  `llm=quickml(glm-4.7-flash)` · `datastore=catalyst` · `firs=10000` · graph
  `16,918 nodes / 87,120 edges` · `13,835` indexed documents · `cache=catalyst`.
- **Verified end-to-end on the live deployment**: token auth, `/cases`, `/fir`, `/person`
  (Fellegi–Sunter resolved identities), the Investigation Copilot, and `/chat` streaming the
  full LangGraph reasoning trace over SSE — plus a clean 401 with no auth. All **six officer
  roles** resolve to their correct permissions.
- **The full data foundation is seeded**: the organizers' 27-table ER verbatim plus 10 `vx_`
  tables of ours, ~105k rows, on real ground truth (NCRB Karnataka crime statistics, Census
  2011 district socioeconomics, real Karnataka GIS boundaries).
- **Kannada and English**, voice input, and live district-anomaly alerts over SSE.
- **PDF export is BLOCKED, honestly, not silently**: SmartBrowz's API layer requires a genuine
  Catalyst User Management identity this environment cannot drive interactively; the console
  says so and falls back to a printable HTML copy rather than pretending to produce a PDF.
- **606 tests green** locally, with no stack required.

---

## Run it locally

```bash
python -m pytest                                      # 606 tests, no stack needed
cd data && python -m data.generator.run --cases 10000 # generate a synthetic dataset
cd apps/api && uvicorn api.main:app --reload          # the API (SQLite backend locally)
cd apps/web && npm run dev                            # the Command Console
```

Locally, everything below the API runs against SQLite using the *same query strings* the
deployed service sends to the Data Store — the suite exercises the real queries, not mocks.
The DoWhy causal layer and the GNN detector run wherever their libraries are installed (local
dev, demo laptop) and report themselves unavailable in the size-capped deployed container
rather than pretending.

## Deploy it

```bash
CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python -m data.provision   # 37 tables, idempotent

# API: source-only change needs no local Docker. A signed upload URL relayed through
# GitHub Actions (.github/workflows/relay-deploy.yml) builds Dockerfile.overlay on the
# runner — the published base plus this commit's source — and uploads it datacenter-
# to-datacenter, since a residential uplink can't beat the URL's 30-minute TTL.
#   1. GET .../appsail/get-signature -> write the signed URL to .github/relay-upload.url,
#      commit, push (triggers the relay-deploy workflow)
#   2. PUT .../appsail/upsert with the uploaded object's key (the local callback that
#      turns the upload into a running deployment)

bash scripts/deploy-console.sh                                                      # the console
```

---

## Repository map

| Folder | Owns |
|---|---|
| `apps/web/` | The Command Console — glassmorphic UI: chat, map, network graph, Sankey, forecasts, evidence rail, Reasoning Trace |
| `apps/api/` | FastAPI — auth, two-place policy enforcement, SSE + WebSocket transport, the audit hash chain |
| `packages/rag_agent/` | LangGraph engine — HippoRAG, Think-on-Graph, the CRAG evaluator, the evidence chain, the Investigation Copilot |
| `packages/ml_models/` | Fellegi–Sunter identity resolution, forecasting, hotspots, risk, AML, the fairness audit |
| `packages/policy/` | RBAC rules — shared, because they are enforced in two places |
| `data/` | The 37-table schema, the Data Store client, the synthetic generator, the graph, the vector index, the Kannada NLP |

`apps/api` is the one deployable service; the packages are the imports it makes, not
microservices.

---

## Where it goes next

The production scaling path is deliberately **described, not built** — at this dataset's scale,
building it now would be architecture theatre. Real-time CCTNS ingestion through Kafka topics
and Flink enrichment; Iceberg once volume and time-travel needs exceed the Data Store; Keycloak
for HR-federated identity and OPA/Rego once the policy set outgrows a Python module; a
spatio-temporal GNN forecaster once historical volume justifies the training cost. The design
that gets there is the one already in place — identity first, evidence always cited, and never
an answer the records don't support.
