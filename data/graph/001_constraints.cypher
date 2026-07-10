// Veritas knowledge-graph constraints & indexes (Neo4j).
// Node/edge shapes are documented in data/README.md; this file makes the
// identity keys unique and indexes the properties GDS/retrieval traverse on.
// Idempotent — IF NOT EXISTS on every statement.

CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.person_id IS UNIQUE;
CREATE CONSTRAINT crimeevent_id IF NOT EXISTS FOR (c:CrimeEvent) REQUIRE c.fir_id IS UNIQUE;
CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.account_id IS UNIQUE;
CREATE CONSTRAINT transaction_id IF NOT EXISTS FOR (t:Transaction) REQUIRE t.txn_id IS UNIQUE;
CREATE CONSTRAINT gang_name IF NOT EXISTS FOR (g:Gang) REQUIRE g.name IS UNIQUE;
CREATE CONSTRAINT location_name IF NOT EXISTS FOR (l:Location) REQUIRE l.name IS UNIQUE;
CREATE CONSTRAINT method_name IF NOT EXISTS FOR (m:MethodOfOperation) REQUIRE m.name IS UNIQUE;

// Traversal/filter indexes
CREATE INDEX person_scrb IF NOT EXISTS FOR (p:Person) ON (p.scrb_id);
CREATE INDEX person_canonical IF NOT EXISTS FOR (p:Person) ON (p.canonical_entity_id);
CREATE INDEX person_risk IF NOT EXISTS FOR (p:Person) ON (p.risk_score);
CREATE INDEX crimeevent_district IF NOT EXISTS FOR (c:CrimeEvent) ON (c.district);
CREATE INDEX crimeevent_type IF NOT EXISTS FOR (c:CrimeEvent) ON (c.crime_type);
CREATE INDEX txn_flagged IF NOT EXISTS FOR (t:Transaction) ON (t.flagged_suspicious);
