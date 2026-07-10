# Data Engineering (`data/`)

**What this is**: every schema in the system, the synthetic data pipeline that populates them, the vector index, and the Kannada NLP/ASR/TTS wrappers. Every other folder reads/writes through what's exposed here — nobody else opens their own DB connection or redefines a table/node shape.

Owns Layer 1, the schema half of Layer 2, and Layer 6 of root [`CLAUDE.md`](../../CLAUDE.md).

## Relational + geospatial schema (Postgres + PostGIS)

```sql
CREATE TABLE officer (
    officer_id UUID PRIMARY KEY, badge_no VARCHAR(20) UNIQUE, name VARCHAR(200),
    ps_code VARCHAR(10), district_code VARCHAR(5), role VARCHAR(20)
    -- role in (IO, SHO, DSP, SP, IG, SCRB_Analyst) — apps/api's policy module
    -- resolves ps_code/role from this table for every JWT it verifies.
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

## Session, conversation & audit schema

`apps/api` is stateless between requests — this is the only persistence for multi-turn conversation. Three distinct tables, three distinct purposes; don't collapse them:

```sql
-- One row per chat session. Only the SessionFocus fields are rehydrated into a
-- fresh InvestigationState on each turn — evidence_items/query_results are NOT
-- carried forward, they're per-turn artifacts (see packages/rag_agent/README.md).
-- Column ↔ SessionFocus mapping (get/upsert_session_focus do exactly this, nothing else):
--   active_person  <-> SessionFocus.active_person  (person_id UUID, NOT scrb_id)
--   active_fir     <-> SessionFocus.active_fir      (fir_id UUID, NOT fir_number)
--   active_location<-> SessionFocus.active_location (district/taluk name)
--   active_date_from, active_date_to <-> SessionFocus.active_date_range tuple (from, to)
CREATE TABLE session (
    session_id UUID PRIMARY KEY, officer_id UUID REFERENCES officer(officer_id),
    active_person UUID, active_fir UUID, active_location VARCHAR(100),
    active_date_from DATE, active_date_to DATE,
    started_at TIMESTAMPTZ DEFAULT NOW(), last_turn_at TIMESTAMPTZ DEFAULT NOW()
);

-- One row per turn. Plaintext — this is what powers chat re-render on reload,
-- session resumption, and PDF export. (audit_log below is NOT a substitute:
-- it stores a hash, not the content.)
CREATE TABLE conversation_turn (
    turn_id UUID PRIMARY KEY, session_id UUID REFERENCES session(session_id),
    turn_index INT, query TEXT, language VARCHAR(2), final_answer TEXT,
    citations JSONB, evidence_items JSONB, visualization JSONB, agent_trace JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tamper-evident log, not a content store. Append-only by design (see rules below).
CREATE TABLE audit_log (
    log_id UUID PRIMARY KEY,
    officer_id UUID REFERENCES officer(officer_id), session_id UUID, endpoint VARCHAR(100),
    request_hash VARCHAR(64), response_hash VARCHAR(64),   -- SHA-256, not plaintext
    agent_trace JSONB, created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
```

Owned here, not in `apps/api` — every schema in the system lives in `data/`, full stop; `apps/api` only calls the write/read helpers below.

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
3. Runs `packages/ml_models.resolve_entities()` once over all generated `person` rows as a batch dedup pass, writing `canonical_entity_id` and `SAME_AS` edges. **This is the only caller of `resolve_entities`** — it is a batch/offline operation (pairwise candidate scoring), not something `packages/rag_agent` invokes per query. At query time, "has this person been arrested under another name" is answered by reading the already-resolved `SAME_AS` edges via a normal Cypher query, not by recomputing linkage live.
4. (Re)builds Postgres, syncs the Neo4j graph, re-embeds narratives into the vector store.

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

All self-hosted — FIR/person data never leaves the network. `transliterate()` output feeds `packages/ml_models.resolve_entities()` (called from `generator/`, see above — not called live).

```python
class Entity(BaseModel):                # ner_extract() return element
    text: str
    label: Literal["PERSON", "LOCATION", "GANG", "VEHICLE", "IPC_SECTION"]
    start: int; end: int                # char offsets into the input text
```

## Return shapes owned here (crossing into other folders)

```python
class SessionFocus(BaseModel):          # data/data/models.py — used by the session write helpers.
    active_person: Optional[str]        # Lives here (not rag_agent) because data can't import upward
    active_fir: Optional[str]           # without a cycle, and it maps 1:1 to session.active_* columns.
    active_location: Optional[str]      # rag_agent imports it: `from data import SessionFocus`.
    active_date_range: Optional[tuple[date, date]]

class ConversationTurn(BaseModel):      # get_conversation_history() return element; one row of conversation_turn
    turn_index: int
    query: str; language: Literal["en", "kn"]
    final_answer: str
    citations: list[dict]; evidence_items: list[dict]   # stored/returned as JSON — Citation/EvidenceItem shapes owned by packages/rag_agent
    visualization: dict; agent_trace: list[dict]
    created_at: datetime
```

## Write helpers (the only sanctioned way any other folder mutates data)

```python
def write_audit(officer_id, session_id, endpoint, request_hash, response_hash, agent_trace) -> None: ...   # apps/api, every request
def upsert_session_focus(session_id, officer_id, focus: SessionFocus) -> None: ...                          # apps/api, every turn
def get_session_focus(session_id) -> Optional[SessionFocus]: ...                                            # apps/api, every turn
def write_conversation_turn(session_id, turn_index, query, language, final_answer,
                             citations, evidence_items, visualization, agent_trace) -> None: ...             # apps/api, every turn
def get_conversation_history(session_id) -> list[ConversationTurn]: ...                                     # apps/api, for /export/pdf
def set_canonical_entity(person_id, canonical_id, confidence) -> None: ...                                   # ml_models, batch entity resolution
def write_same_as_edge(person_id_a, person_id_b, confidence) -> None: ...                                   # ml_models, batch entity resolution
def flag_transaction(txn_id, flag_type, detector, confidence) -> None: ...                                   # ml_models, AML detectors
```

## Suggested structure
```
data/
  sql/                 # Postgres/PostGIS DDL + migrations
  graph/               # Neo4j schema, constraint/index setup, GDS job scripts
  generator/           # Faker/Mimesis synthetic FIR/person pipeline + real ground-truth joins + entity-resolution batch pass
  embeddings/          # vector store indexing job
  nlp/                 # AI4Bharat/Vakyansh wrappers (functions above)
  seed/                # real NCRB/Census/NSSO/KA-GIS reference datasets
  data/                # the importable `data` package — the only way in:
    config.py          #   env-driven DSNs (get_settings)
    db.py              #   data.db.get_session(), init_db()
    graph.py           #   data.graph.get_driver(), init_graph()
    vectors.py         #   vector store client (pgvector)
    audit.py, sessions.py, transactions.py   # the write helpers above
```

## Provides / Consumes
- **Provides to everyone**: `connections.py` helpers, the write helpers above, the NLP wrapper functions, the schemas above.
- **Consumes**: nothing from other folders — this is the foundation layer.

## Non-goals
- No business logic, no ML scoring, no orchestration. If a function does more than fetch/write data or wrap an NLP call, it belongs in `packages/ml_models` or `packages/rag_agent` instead.
