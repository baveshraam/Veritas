# Data Engineering (`data/`)

**What this is**: every schema in the system, the synthetic data pipeline that populates them, the vector index, and the Kannada NLP/ASR/TTS wrappers. Every other folder reads/writes through what's exposed here — nobody else opens their own DB connection or redefines a table/node shape.

Owns Layer 1, the schema half of Layer 2, and Layer 6 of root [`CLAUDE.md`](../../CLAUDE.md).

## Relational + geospatial schema (Postgres + PostGIS)

```sql
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
    canonical_entity_id UUID  -- Fellegi-Sunter linkage target, written by packages/ml_models
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

## Knowledge graph schema (Neo4j)

```cypher
(:Person {person_id, scrb_id, name_en, name_kn, dob, gender, risk_score,
          gang_affiliation, is_habitual_offender, canonical_entity_id})
(:CrimeEvent {fir_id, crime_type, ipc_sections, date_occurred, location, district,
              modus_operandi, case_status})
(:Account {account_id, bank, account_type, opened_date})
(:Transaction {txn_id, amount, date, channel, flagged_suspicious: Boolean})

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
(:Person)-[:SAME_AS {confidence}]->(:Person)   -- Fellegi-Sunter linkage edge
```

GDS algorithm setup (PageRank, Betweenness, Louvain, Node Similarity) lives here as on-demand job scripts, not a scheduled service — `packages/rag_agent` calls into these results, doesn't run the algorithms itself.

## Synthetic data generator
One Python job:
1. Faker/Mimesis generates FIR/person/criminal-record rows, IPC-section distribution weighted by real published NCRB Karnataka statistics.
2. Joined against real district socioeconomic data (Census/data.gov.in/NSSO) and real KA-GIS district/taluk boundary shapefiles.
3. (Re)builds Postgres, syncs the Neo4j graph, re-embeds narratives into the vector store.

Target: 10-50K FIR records — sufficient for every demo scenario. Rerunning this job is how the whole dataset gets refreshed; there is no streaming ingestion to build.

## Vector store
Qdrant or pgvector. Collections: FIR narratives, GraphRAG community summaries, criminal profiles, MO descriptions. Indexing/embedding job lives here; `packages/rag_agent` only queries it (hybrid dense + BM25).

## Kannada NLP/ASR/TTS wrappers

```python
def ner_extract(text: str, lang: Literal["en", "kn"]) -> list[Entity]: ...      # AI4Bharat IndicNER
def transliterate(name: str) -> list[str]: ...                                  # AI4Bharat IndicXlit — candidate variants
def translate(text: str, src: str, tgt: str) -> str: ...                        # AI4Bharat IndicTrans2, self-hosted
def speech_to_text(audio: bytes, lang: Literal["en", "kn"]) -> str: ...          # Vakyansh (kn) / Whisper (en)
def text_to_speech(text: str, lang: Literal["en", "kn"]) -> bytes: ...           # AI4Bharat IndicTTS (kn) / Kokoro-TTS (en)
```

All self-hosted — FIR/person data never leaves the network. `transliterate()` output feeds `packages/ml_models.resolve_entities()`.

## Suggested structure
```
data/
  sql/                 # Postgres/PostGIS DDL + migrations
  graph/               # Neo4j schema, constraint/index setup, GDS job scripts
  generator/           # Faker/Mimesis synthetic FIR/person pipeline + real ground-truth joins
  embeddings/          # vector store indexing job
  nlp/                 # AI4Bharat/Vakyansh wrappers (functions above)
  seed/                # real NCRB/Census/NSSO/KA-GIS reference datasets
  connections.py       # data.db.get_session(), data.graph.get_driver(), vector client — the only way in
```

## Provides / Consumes
- **Provides to everyone**: `connections.py` helpers, the NLP wrapper functions, the schemas above.
- **Consumes**: nothing from other folders — this is the foundation layer.

## Non-goals
- No business logic, no ML scoring, no orchestration. If a function does more than fetch/write data or wrap an NLP call, it belongs in `packages/ml_models` or `packages/rag_agent` instead.
