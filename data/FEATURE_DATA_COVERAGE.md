# Feature → Data Coverage Analysis

**Question**: for every planned platform feature, do the selected datasets (see
[`DATA_ACQUISITION_STRATEGY.md`](./DATA_ACQUISITION_STRATEGY.md)) provide enough real-world signal — and where
they don't, what public dataset unlocks the capability?

**Lens**: our data is generator-produced, so "sufficient" means *the generator has a realistic real-world
prior/structure to draw from, and any ML has a real corpus to train on*. A feature is a **gap** only when the
generator would have to fabricate the signal with no real anchor, or an ML model has nothing real to learn from.

Bar for recommending a **new** dataset: it must unlock capability the current 11 + generator cannot make
credible. Five clear the bar. Most features are already covered — stated plainly so this stays honest.

Legend: ✅ covered · ➕ real gap → new data recommended

---

## Features already sufficient (no new data)

| Feature | Supported by | Note |
|---|---|---|
| **Temporal forecasting** (Prophet+MinT) | D05 (24-yr series), D01+D02, D23 seasonality | ✅ real trend/seasonality backbone. (One cheap regressor add below.) |
| **Repeat offender detection** | generator + Fellegi-Sunter + D11 recidivism priors | ✅ |
| **Behavioral / offender profiling** | D11 (aggregate offender demographics), D07 (weapon/victim), generator trajectories | ✅ individual criminal histories are PII — none exist publicly for India; aggregate priors are the honest ceiling |
| **MO clustering** | D07 + D23 narratives (NLP pre-train), generator MO field | ✅ |
| **Community detection** (Louvain) | generator graph + GDS | ✅ |
| **Link prediction** (GNN) | generator graph topology | ✅ |
| **Criminal network analysis** | generator CO_ACCUSED/MEMBER_OF + GDS PageRank/Betweenness | ✅ no real co-offending network is public; a documented power-law degree prior is enough for demo |
| **Risk scoring** (XGBoost+SHAP) | D17 socioeconomic features + crime-rate priors | ✅ |
| **Explainable AI / fairness** (SHAP, Aequitas) | D17 SC/ST + geography → subgroup disparate-impact audit | ✅ geographic subgroups suffice; we exclude caste/religion as *features* by design |
| **Copilot reasoning / officer briefing** | generator case context + D07/D23 similar-case outcomes + D22 legal | ✅ |
| **Semantic search / similar FIR retrieval** | vector embeddings of generator narratives (D07/D23-styled) | ✅ |
| **Timeline reconstruction** | generator event timestamps | ✅ |
| **Relationship visualization** | generator graph | ✅ |
| **Early warning generation** | Isolation Forest on D05/D01 trend spikes | ✅ |
| **Pattern discovery** | narratives + graph | ✅ |
| **Geographic analysis** (choropleth, jurisdiction) | D18 geometry + D14 PS + D17 | ✅ at district/taluk level (micro-level gap → below) |

---

## Real gaps → new datasets to acquire

Ordered by impact.

### ➕ 1. Hotspot prediction — intra-district spatial realism  **(biggest win)**
- **Now**: generator places incidents inside GADM polygons weighted by *district* crime rate → hotspots are
  uniform-within-district. KDE/DBSCAN on that produces round, artificial blobs. Real crime clusters near
  markets, highways, bars, ATMs, transit, informal settlements.
- **Add**:
  - **WorldPop gridded population (Karnataka, 100 m)** — worldpop.org, open (CC-BY). Weight incident placement
    by real population density.
  - **OSM POI + land-use layer (Karnataka)** — Geofabrik, ODbL. Attractor points (markets, bars, ATMs, bus/rail,
    highways) to bias placement and become real geospatial ML features.
- **Unlocks**: believable micro-hotspots, near-repeat analysis, distance-to-attractor features for the risk
  model. Turns hotspot detection from "district shading" into real spatial intelligence.
- *(Distinct from rejected D16 — that was OSM* police-station *POIs, redundant with KGIS. This is OSM*
  *population/land-use, a different layer.)*

### ➕ 2. Entity resolution — realistic Indian name collisions
- **Now**: Faker is western-biased; `en_IN` is thin. Fellegi-Sunter has nothing realistic to resolve — no
  believable spelling/transliteration variants or name-frequency collisions.
- **Add**: **open Indian / Karnataka name + surname frequency corpus** (Kaggle "Indian Names", AI4Bharat name
  lists, or electoral-roll-derived first/last name frequencies). Feed IndicXlit for variants.
- **Unlocks**: the whole ER demo — "same person arrested under a different spelling" only lands if the name
  pool has real Ramesh/ರಮೇಶ್/Ramesha collision structure. Directly powers `SAME_AS` / `canonical_entity_id`.

### ➕ 3. Legal reasoning — precedent, not just statute
- **Now**: D22 gives IPC/BNS *statute text* only. RAG can cite a section but can't reason "what sentence did
  similar cases get" or retrieve precedent.
- **Add**: **Indian court judgments corpus** — **ILDC** (Indian Legal Documents Corpus, IIT Kanpur, ACL 2021,
  judgments + outcomes) or eCourts/Indian Kanoon export (mind ToS).
- **Unlocks**: precedent retrieval, charge→likely-outcome grounding, richer legal RAG. A visible depth jump
  over statute lookup — strong judge-facing differentiator.

### ➕ 4. Financial crime — labeled laundering typologies
- **Now**: D28 PaySim has fraud flags but African mobile-money context and no explicit laundering *patterns*
  (fan-in/out, cycles) — weak ground truth for the GNN we pitch as catching structuring/layering.
- **Add**: **IBM Transactions for AML** (Kaggle, synthetic, graph-shaped, with labeled laundering typologies).
  Complements or replaces PaySim.
- **Unlocks**: GNN trained on the exact pattern classes our detector claims to find; validates the rule-based
  structuring baseline against real typology labels. Keep D28 for volume, train on IBM-AML for pattern labels.

### ➕ 5. Temporal forecasting — festival/holiday regressor  *(cheap)*
- **Now**: seasonality is data-driven only; no event regressors.
- **Add**: **Indian/Karnataka gazetted holiday + festival calendar** (data.gov.in or python `holidays`).
- **Unlocks**: Prophet holiday regressors → visibly better fits around festivals/dry days. Near-zero cost,
  real accuracy uplift.

### (Optional) SNAP network topology prior
- Marginal. Stanford SNAP graphs to calibrate the generator's degree distribution toward a realistic
  co-offending topology. Nice-to-have, not required — a documented power law already suffices.

---

## Net

Of ~22 features, **17 are already covered** by the 11 selected datasets + the generator. Five have real,
public, cheap-to-acquire gaps. Adding **WorldPop + OSM land-use, an Indian name corpus, ILDC judgments,
IBM-AML, and a holiday calendar** raises the platform from "credible synthetic demo" to "genuinely
intelligent" on exactly the axes judges probe — spatial hotspots, entity resolution, legal depth, and AML —
without touching the architecture.

**Updated acquisition set**: 11 core + 5 capability-unlockers = **16 datasets**. All open-licensed
(CC-BY / ODbL / research / public domain). Same generator-centric pipeline; the five new sets slot in as
GROUND TRUTH (WorldPop, OSM, holidays), PRIOR (names), and ML/RAG CORPUS (ILDC, IBM-AML).
```
WorldPop + OSM land-use  → generator placement weights + geo features
Indian name corpus       → generator names + Fellegi-Sunter ER
ILDC judgments           → legal RAG collection (precedent)
IBM-AML                  → GNN AML training corpus (offline)
Holiday calendar         → Prophet regressor
```
