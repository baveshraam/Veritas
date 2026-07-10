-- Append-only enforcement for audit_log (Layer 8). Separate file because it
-- must run after 001_schema.sql creates the table, and because dropping/rebuilding
-- these rules is a distinct, auditable operation.

-- CREATE RULE has no IF NOT EXISTS; drop first so init is re-runnable.
DROP RULE IF EXISTS audit_log_no_update ON audit_log;
DROP RULE IF EXISTS audit_log_no_delete ON audit_log;

CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
