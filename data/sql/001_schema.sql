-- Veritas — relational schema (Postgres + pgvector)
-- Canonical DDL for Layer 1 / schema-half of Layer 2. Owned by data/; nobody
-- else redefines a table. Verbatim from data/README.md — do not drift.
--
-- Ordering is FK-driven (officer, person before fir; session before turn), which
-- is why it differs from the README's presentation order.
--
-- NO POSTGIS. Coordinates are plain DECIMAL lat/lng columns, matching the KSP
-- reference ER diagram (CaseMaster.latitude / CaseMaster.longitude) and Catalyst
-- Data Store, which has no geometry type. Nothing was lost: KDE/DBSCAN and the
-- Deck.gl layer always consumed lat/lng arrays — PostGIS only ever stored them.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Core record layer
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS officer (
    officer_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    badge_no      VARCHAR(20) UNIQUE,
    email         VARCHAR(200) UNIQUE,   -- the key Catalyst Authentication identifies a user by
    name          VARCHAR(200),
    ps_code       VARCHAR(10),
    district_code VARCHAR(5),
    role          VARCHAR(20)
    -- role in (IO, SHO, DSP, SP, IG, SCRB_Analyst) — apps/api's policy module
    -- resolves ps_code/role from this table for every caller it authenticates.
);

CREATE TABLE IF NOT EXISTS person (
    person_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scrb_id            VARCHAR(20) UNIQUE,
    name_en            VARCHAR(200),
    name_kn            VARCHAR(200),
    dob                DATE,
    gender             VARCHAR(10),
    address_lat        DECIMAL(9,6),
    address_lng        DECIMAL(9,6),
    aadhaar_hash       VARCHAR(64),
    criminal_history   BOOLEAN DEFAULT FALSE,
    risk_score         FLOAT,
    gang_affiliation   VARCHAR(100),
    canonical_entity_id UUID,  -- Fellegi-Sunter linkage target, written by packages/ml_models
    -- Graph metrics, written back by the NetworkX job (data.gds). These were Neo4j
    -- node properties; with no graph DB they live on the record they describe.
    pagerank           FLOAT,
    community          INT,
    betweenness        FLOAT
);

CREATE TABLE IF NOT EXISTS fir (
    fir_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ps_code         VARCHAR(10),
    district_code   VARCHAR(5),
    fir_number      VARCHAR(20),
    date_filed      TIMESTAMPTZ,
    ipc_sections    TEXT[],
    crime_type      VARCHAR(100),
    occurrence_from TIMESTAMPTZ,
    occurrence_to   TIMESTAMPTZ,
    latitude        DECIMAL(9,6),   -- CaseMaster.latitude  in the KSP reference ER diagram
    longitude       DECIMAL(9,6),   -- CaseMaster.longitude
    district        VARCHAR(50),
    taluk           VARCHAR(50),
    complainant_id  UUID REFERENCES person(person_id),
    io_id           UUID REFERENCES officer(officer_id),
    case_status     VARCHAR(30),
    modus_operandi  TEXT,
    narrative       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS criminal_record (
    record_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id   UUID REFERENCES person(person_id),
    fir_id      UUID REFERENCES fir(fir_id),
    role        VARCHAR(50),
    arrest_date DATE,
    bail_status VARCHAR(30),
    conviction  BOOLEAN
);

-- ---------------------------------------------------------------------------
-- Financial-crime layer. These two lived only in Neo4j before; with the graph
-- gone they need a real home, and the AML detectors read them from here.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS account (
    account_id       VARCHAR(64) PRIMARY KEY,
    owner_person_id  UUID REFERENCES person(person_id),
    bank             VARCHAR(60),
    account_type     VARCHAR(30),
    opened_date      DATE
);

CREATE TABLE IF NOT EXISTS txn (
    txn_id             VARCHAR(64) PRIMARY KEY,
    src_account_id     VARCHAR(64) REFERENCES account(account_id),
    dst_account_id     VARCHAR(64) REFERENCES account(account_id),
    amount             DECIMAL(14,2),
    txn_date           DATE,
    channel            VARCHAR(30),
    linked_fir_id      UUID REFERENCES fir(fir_id),
    injected_pattern   VARCHAR(30),   -- generator ground truth; NOT a detector output
    flagged_suspicious BOOLEAN DEFAULT FALSE,
    flag_type          VARCHAR(30),
    detector           VARCHAR(30),
    flag_confidence    FLOAT
);

-- ---------------------------------------------------------------------------
-- Knowledge graph, as an edge list.
--
-- Replaces Neo4j: no Catalyst service corresponds to a graph database, so the
-- graph is stored as ordinary rows and the algorithms (PageRank, Louvain,
-- betweenness, personalized PageRank, bounded traversal) run in NetworkX over
-- them. Nodes are the records themselves (person/fir/account/txn) plus the two
-- name-only kinds (Gang, Location) — only the EDGES need a table of their own.
--
-- Deliberately flat: every column is a scalar, so this table maps 1:1 onto a
-- Catalyst Data Store table with no JSON/array column to flatten later.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS graph_edge (
    edge_id    BIGSERIAL PRIMARY KEY,
    edge_type  VARCHAR(24) NOT NULL,   -- ACCUSED_IN, CO_ACCUSED_WITH, TRANSFERRED_TO, ...
    src_id     VARCHAR(64) NOT NULL,
    src_label  VARCHAR(16) NOT NULL,   -- Person, CrimeEvent, Account, Transaction, Gang, Location
    dst_id     VARCHAR(64) NOT NULL,
    dst_label  VARCHAR(16) NOT NULL,
    -- edge properties, one column each (no property bag: Data Store has no JSON)
    role       VARCHAR(50),
    edge_date  DATE,
    amount     DECIMAL(14,2),
    strength   INT,                    -- CO_ACCUSED_WITH: number of shared FIRs
    confidence FLOAT                   -- SAME_AS: Fellegi-Sunter linkage confidence
);

CREATE INDEX IF NOT EXISTS idx_edge_src  ON graph_edge (src_id);
CREATE INDEX IF NOT EXISTS idx_edge_dst  ON graph_edge (dst_id);
CREATE INDEX IF NOT EXISTS idx_edge_type ON graph_edge (edge_type);

-- Real data, not simulated: Census/data.gov.in/NSSO
-- The one REAL table: Census of India 2011 Primary Census Abstract, joined in
-- verbatim (data.socioeconomic). Every column is a ratio of two published Census
-- counts. `unemployment` and `police_per_lakh` are absent by design -- neither is
-- published at district level in India, and the causal layer must not adjust for,
-- or estimate the effect of, a number we made up. See data/data/socioeconomic.py.
CREATE TABLE IF NOT EXISTS district_socioeconomic (
    district_code        VARCHAR(5) PRIMARY KEY,
    year                 INT,
    population           BIGINT,
    literacy_rate        FLOAT,   -- crude: literates / total population
    urban_ratio          FLOAT,   -- urban households / all households
    poverty_index        FLOAT,   -- households under Rs 45,000 PPP income / all
    marginal_worker_rate FLOAT,   -- workers employed < 6 months / all workers
    youth_ratio          FLOAT    -- population aged 0-29 / total population
);

-- ---------------------------------------------------------------------------
-- Session, conversation & audit (only persistence for a stateless apps/api)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS session (
    session_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    officer_id      UUID REFERENCES officer(officer_id),
    active_person   UUID,
    active_fir      UUID,
    active_location VARCHAR(100),
    active_date_from DATE,
    active_date_to   DATE,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    last_turn_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_turn (
    turn_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id     UUID REFERENCES session(session_id),
    turn_index     INT,
    query          TEXT,
    language       VARCHAR(2),
    final_answer   TEXT,
    citations      JSONB,
    evidence_items JSONB,
    visualization  JSONB,
    agent_trace    JSONB,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Tamper-evident log, not a content store. Append-only (rules below).
CREATE TABLE IF NOT EXISTS audit_log (
    log_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    officer_id    UUID REFERENCES officer(officer_id),
    session_id    UUID,
    endpoint      VARCHAR(100),
    request_hash  VARCHAR(64),   -- SHA-256, not plaintext
    response_hash VARCHAR(64),
    agent_trace   JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes — only where a documented query path needs one.
-- ---------------------------------------------------------------------------

-- Hotspot/geo queries filter by district first and then scan that district's points
-- in Python (KDE/DBSCAN), so a plain btree on the coordinate pair is all the
-- Geospatial Agent needs — there is no bounding-box or radius predicate left in SQL.
CREATE INDEX IF NOT EXISTS idx_fir_latlng         ON fir (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_fir_ps_code        ON fir (ps_code);                       -- policy: "IO sees only their PS"
CREATE INDEX IF NOT EXISTS idx_fir_district_code  ON fir (district_code);
CREATE INDEX IF NOT EXISTS idx_fir_date_filed     ON fir (date_filed);                    -- forecasting/temporal joins
CREATE INDEX IF NOT EXISTS idx_crim_person        ON criminal_record (person_id);
CREATE INDEX IF NOT EXISTS idx_crim_fir           ON criminal_record (fir_id);
CREATE INDEX IF NOT EXISTS idx_person_canonical   ON person (canonical_entity_id);        -- SAME_AS lookups
CREATE INDEX IF NOT EXISTS idx_conv_session       ON conversation_turn (session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_audit_officer      ON audit_log (officer_id, created_at);
