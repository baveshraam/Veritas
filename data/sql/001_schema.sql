-- Veritas — relational + geospatial schema (Postgres + PostGIS + pgvector)
-- Canonical DDL for Layer 1 / schema-half of Layer 2. Owned by data/; nobody
-- else redefines a table. Verbatim from data/README.md — do not drift.
--
-- Ordering is FK-driven (officer, person before fir; session before turn), which
-- is why it differs from the README's presentation order.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Core record layer
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS officer (
    officer_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    badge_no      VARCHAR(20) UNIQUE,
    name          VARCHAR(200),
    ps_code       VARCHAR(10),
    district_code VARCHAR(5),
    role          VARCHAR(20)
    -- role in (IO, SHO, DSP, SP, IG, SCRB_Analyst) — apps/api's policy module
    -- resolves ps_code/role from this table for every JWT it verifies.
);

CREATE TABLE IF NOT EXISTS person (
    person_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scrb_id            VARCHAR(20) UNIQUE,
    name_en            VARCHAR(200),
    name_kn            VARCHAR(200),
    dob                DATE,
    gender             VARCHAR(10),
    address_geom       GEOMETRY(Point, 4326),
    aadhaar_hash       VARCHAR(64),
    criminal_history   BOOLEAN DEFAULT FALSE,
    risk_score         FLOAT,
    gang_affiliation   VARCHAR(100),
    canonical_entity_id UUID  -- Fellegi-Sunter linkage target, written by packages/ml_models
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
    location_geom   GEOMETRY(Point, 4326),
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

-- Real data, not simulated: Census/data.gov.in/NSSO
CREATE TABLE IF NOT EXISTS district_socioeconomic (
    district_code  VARCHAR(5) PRIMARY KEY,
    year           INT,
    literacy_rate  FLOAT,
    unemployment   FLOAT,
    poverty_index  FLOAT,
    population     BIGINT,
    urban_ratio    FLOAT,
    police_per_lakh FLOAT
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

CREATE INDEX IF NOT EXISTS idx_fir_location_geom  ON fir USING GIST (location_geom);     -- PostGIS/Geospatial Agent
CREATE INDEX IF NOT EXISTS idx_person_address_geom ON person USING GIST (address_geom);
CREATE INDEX IF NOT EXISTS idx_fir_ps_code        ON fir (ps_code);                       -- policy: "IO sees only their PS"
CREATE INDEX IF NOT EXISTS idx_fir_district_code  ON fir (district_code);
CREATE INDEX IF NOT EXISTS idx_fir_date_filed     ON fir (date_filed);                    -- forecasting/temporal joins
CREATE INDEX IF NOT EXISTS idx_crim_person        ON criminal_record (person_id);
CREATE INDEX IF NOT EXISTS idx_crim_fir           ON criminal_record (fir_id);
CREATE INDEX IF NOT EXISTS idx_person_canonical   ON person (canonical_entity_id);        -- SAME_AS lookups
CREATE INDEX IF NOT EXISTS idx_conv_session       ON conversation_turn (session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_audit_officer      ON audit_log (officer_id, created_at);
