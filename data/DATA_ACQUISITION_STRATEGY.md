# Data Acquisition Strategy — Veritas Crime Intelligence Platform

**Input**: `AI_Crime_Intelligence_Unified_Dataset_Catalog.md` (31 datasets, D01–D31).
**This doc**: the definitive selection, ranking, and ingestion pipeline. Supersedes the catalog's tiering.

## The governing correction (read first)

Our platform generates its record-level data (`fir`, `person`, `criminal_record`, the Neo4j
`Person/Account/Transaction` graph, the narrative/MO vector collections) — see [`CLAUDE.md`](../CLAUDE.md) §1
and [`data/README.md`](./README.md). External datasets do **not** fill those tables row-for-row. They serve
three roles:

- **PRIOR** — a distribution that weights the synthetic generator (IPC mix, district crime rate, conviction rate, victim age/gender).
- **GROUND TRUTH** — a real layer joined in verbatim (`district_socioeconomic`, GADM geometry, PS locations, legal code).
- **ML CORPUS** — real record-level data used to *pre-train/validate* a model that then runs on our synthetic KA data.

The catalog's per-dataset "Schema Mapping" column references tables that don't exist in our schema
(`incidents`, `crime_narratives`, `transaction_graph`, `network_intrusion`, …). Ignore it; the mapping below
uses our actual schema.

Two hard consequences:
- **No aggregate dataset seeds the graph.** Co-accused edges, `SAME_AS` links, money trails come from the
  generator + Fellegi-Sunter, not from any of these files. Datasets pitched as "graph seeds" (D19 POCSO
  relationships, D13/D15 hierarchy) are aggregate counts and cannot produce edges.
- **Network-intrusion data (D30/D31) has no home.** There is no IDS/packet component in the architecture.
  Pure scope creep — rejected.

---

## Tier 1 (Mandatory)

The real ground truth the generator must join against, plus the priors without which the synthetic data isn't
credible, plus the one dataset RAG needs.

| ID | Dataset | Role | Populates / Feeds | Preproc | Quality |
|----|---------|------|-------------------|---------|---------|
| **D01+D02** (merge) | Karnataka Crime 2024+2025 (KSP/SCRB) | PRIOR | Generator: IPC/BNS section mix + per-district crime-rate weights. This *is* the "real NCRB Karnataka statistics" CLAUDE.md §1 already commits to. | Low — two district×head matrices, merge on district+head | ★★★★★ official |
| **D03** | NCRB Crime in India 2024 | PRIOR | Generator: charge-sheet %, conviction %, arrest-per-case → `criminal_record.conviction`, `fir.case_status` distributions. National benchmark panel for the UI. | Low–Med — multi-volume, extract KA + national rows | ★★★★★ |
| **D17** | Census 2011 Karnataka (+ NSSO unemployment) | GROUND TRUTH | **`district_socioeconomic` directly** — the only dataset that literally fills a real table. Feeds DoWhy causal layer + XGBoost risk features. | Med — join C-08/C-13/C-14 + NSSO, map to `district_code` | ★★★★★ |
| **D18** | GADM admin boundaries (KA) | GROUND TRUTH | PostGIS district/taluk polygons → generator geo-assignment of `fir.location_geom`, `person.address_geom`; map choropleth. | Low — shapefile import | ★★★★★ |
| **D14** | KA / Bengaluru police station locations (KGIS) | GROUND TRUTH | `officer.ps_code` geo anchor, FIR→PS assignment, map PS layer. Official KGIS. | Med — KML parse, jurisdiction validation | ★★★★☆ |
| **D22** | India Code IPC / BNS | GROUND TRUTH + RAG | `fir.ipc_sections` taxonomy; **RAG legal collection** (charge recommendation, offence→punishment). Non-negotiable for the RAG pitch. | Med — parse legal text to structured sections | ★★★★★ |

**Why these six and no more at Tier 1**: they are the complete set of *real* layers our generator and RAG
cannot fabricate — socioeconomic truth, geometry, jurisdiction, legal code — plus the two crime-statistic
priors that make the synthetic distribution defensible to judges.

---

## Tier 2 (Strongly Recommended)

Materially raises realism / ML quality. Each earns its cleaning cost.

| ID | Dataset | Role | Populates / Feeds | Preproc | Quality |
|----|---------|------|-------------------|---------|---------|
| **D07** | Indian Crimes Dataset (Kaggle, ~40K, incl. Bangalore, CC0) | ML CORPUS + PRIOR | Seed/style corpus for generated `fir.narrative` + `modus_operandi`; pre-train MO-clustering & crime-type NLP; victim age/gender + weapon priors. Best *India-flavoured* narrative source. | Med — clean, de-dupe, map free-text→IPC | ★★★★☆ |
| **D05** | NCRB Summary 2001–2024 (clean CSV) | PRIOR | 24-yr state time series → realistic seasonality/trend backbone for **Prophet + MinT** so forecasts aren't toy. | Low — tidy CSV | ★★★★★ |
| **D04** | Bengaluru Crime 2023 (detection rates) | PRIOR | Detection/closure-rate priors for `fir.case_status`; city granularity for the flagship Bengaluru demo. | Low | ★★★★★ |
| **D23** | Chicago Crime (geocoded + narrative + arrest) | ML CORPUS | Pre-train/validate **KDE, DBSCAN/ST-DBSCAN hotspots, spatio-temporal forecasting, narrative embeddings** on real case-level geo data before applying to synthetic KA. **The single international benchmark we keep.** | Med — large; subset & schema-align | ★★★★★ |
| **D28** | PaySim (6M txns, fraud labels) | ML CORPUS | Train the **GNN AML classifier** + validate the rule-based structuring detector on realistic transaction-graph/layering patterns; shape our injected `Transaction`/`Account` ground truth. | Med | ★★★★☆ |

**Merge/complement notes**: D01+D02 are one prior (merge). D03 (cross-section) and D05 (longitudinal)
complement — keep both. D14 is primary geo; everything else geocodes off it.

---

## Tier 3 (Optional Enhancements)

Add only if the matching demo module is on the storyboard. Each is an aggregate prior for one vertical.

| ID | Dataset | Add when you demo… |
|----|---------|--------------------|
| D09 | NCRB Crimes Against Women (age-group) | victim-demographic priors / women-safety analytics |
| D10 | NCRB Missing Persons | a missing-persons module (else no home in schema) |
| D11 | NCRB Prison Statistics | recidivism-model priors (LightGBM re-offense) |
| D12 | NCRB Cyber Crime (IT Act) | cybercrime trend panel |
| D20 | NCRB Economic Offences | financial-crime aggregate context beside the GNN |
| D08 | District Crimes 2001–2012 | deeper historical trend (overlaps D05) |
| D13 / D15 | DoPO / PS hierarchy | `officer` org-hierarchy enrichment, coverage analytics |
| D21 | NDPS Drug Seizures | a narcotics module |
| D29 | Elliptic Bitcoin | a crypto-AML module (academic license friction) |

---

## Tier 4 (Reject)

| ID | Dataset | Why rejected |
|----|---------|--------------|
| **D24, D25, D26** | UK Police / LA / Philadelphia crime | Redundant with **D23 Chicago**. One international geo-benchmark is enough; three more = cleaning effort + legal-context mismatch for zero marginal ML signal. |
| **D16** | OSM police POIs | Redundant with official **D14 (KGIS)**; crowdsourced, incomplete. Keep only as a geocode fallback, not a source. |
| **D27** | IEEE-CIS Fraud | Redundant with **D28 PaySim** for the AML demo; tabular/wide, less graph-shaped, heavier. PaySim fits the `Account→Transaction` graph better. |
| **D30, D31** | CICIDS2017 / UNSW-NB15 | **No network-intrusion component exists in the architecture.** Packet/flow data maps to nothing. Pure scope creep. |
| **D06** | NCRB Road Accidents | No accident/vehicle-safety model is core to our schema. Out of scope. |
| **D19** | POCSO offender relationships | ~200 aggregate rows — cannot seed graph edges (our co-accused/SAME_AS edges come from the generator + Fellegi-Sunter). Its only value is a POCSO relationship-mix prior; not worth a pipeline stage. |

---

## Final selection at a glance

- **Build on**: D01+D02, D03, D17, D18, D14, D22 (mandatory) · D07, D05, D04, D23, D28 (strong).
- **Optional per module**: D08–D13, D15, D20, D21, D29.
- **Drop**: D06, D16, D19, D24, D25, D26, D27, D30, D31.

Net: **11 core datasets** carry the whole platform; ~9 optional module boosters; **9 rejected**. Down from 31.

---

## Recommended pipeline (corrected for a generator-centric architecture)

The catalog's linear "ingest real records → normalize → load" pipeline assumes record-level real data we don't
have. Ours pivots on the synthetic generator. This is the actual order:

```
REAL SOURCES
  ├─ Priors:        D01+D02, D03, D05, D04, D07(dist.)      → distribution tables
  ├─ Ground truth:  D17 (socioecon), D18 (geometry),
  │                 D14 (PS geo), D22 (legal code)
  └─ ML corpora:    D07 (narratives), D23 (geo/narrative),  → offline, never in prod DB
                    D28 (transactions)
        │
        ▼
VALIDATION        schema/type checks, district-code reconciliation (D01/D03/D17/D18/D14
                  all use different district spellings → canonical district_code map is step 0)
        │
        ▼
CLEANING          dedupe D07, tidy NCRB CSVs, parse D22 legal text, subset D23
        │
        ▼
CANONICAL MAPPING D17→district_socioeconomic (verbatim); D18→PostGIS geom;
                  D14→PS anchors; D22→ipc_sections + RAG docs;
                  D01/D02/D03/D04/D05/D07→PRIOR tables (not fact tables)
        │
        ▼
┌──────────────────────────────────────────────────────────────┐
│ SYNTHETIC GENERATOR (data/generator/)                        │
│  draws from PRIORS, places entities inside GROUND-TRUTH geom, │
│  emits record-level fir / person / criminal_record /          │
│  Account / Transaction / narratives                           │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
ENTITY RESOLUTION      Fellegi-Sunter batch (packages/ml_models.resolve_entities)
                       → canonical_entity_id + SAME_AS edges  [only caller, offline]
        │
        ▼
RELATIONSHIP GEN       co-accused, MEMBER_OF, money trails, LINKED_TO  (from generator)
        │
        ▼
KNOWLEDGE GRAPH        sync Postgres → Neo4j nodes/edges; GDS PageRank/Louvain/Betweenness
        │
        ▼
VECTOR EMBEDDING       narratives, community summaries, criminal profiles, MO,
                       + D22 legal docs + (optional) D23 narratives for retrieval robustness
        │
        ▼
   ┌────────────┬────────────┬──────────────────────┐
 PostgreSQL   Neo4j       pgvector / Qdrant       RAG KB (D22 legal + summaries)
```

**Step 0 that the catalog misses**: a canonical `district_code` reconciliation map. D01, D03, D17, D18, D14
each spell/segment Karnataka districts differently — every downstream join breaks without it. This is the
single highest-leverage preprocessing task and belongs before everything else.

**ML corpora (D07/D23/D28) never enter the production DB.** They live in `data/seed/` and train models
offline; only fitted model artifacts ship. This keeps the "synthetic crime on real socio-demographic ground
truth" claim clean — no foreign real crime records leak into the demo dataset.

---

## Coverage check against our real schema

| Table / store | Filled by |
|---|---|
| `district_socioeconomic` | D17 (real, verbatim) |
| `fir` / `person` / `criminal_record` | generator, weighted by D01+D02/D03/D04/D07 priors, placed in D18/D14 geometry |
| `officer` | generator + optional D13/D15 hierarchy |
| Neo4j Person/CrimeEvent/Location | generator + GDS |
| Neo4j Account/Transaction (+GNN) | generator, patterns validated on D28 |
| `SAME_AS` / `canonical_entity_id` | Fellegi-Sunter batch |
| Vector: FIR narrative / MO | generator narratives, NLP pre-trained on D07 (+D23) |
| Vector / RAG: legal | D22 |
| Forecast/hotspot models | trained/validated on D05 + D23, run on synthetic KA |

Everything the schema needs is covered by 11 datasets. The other 20 are redundant, out-of-scope, or aggregate
priors for modules that may not ship.
