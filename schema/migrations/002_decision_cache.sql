-- Migration 002: Decision cache materialized view

CREATE TABLE IF NOT EXISTS decision_cache (
    decision_id    TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    context_hash   TEXT NOT NULL,
    decision_type  TEXT NOT NULL,
    decision_value TEXT NOT NULL,
    routed_to      TEXT,
    scope_level    INTEGER NOT NULL,
    trust_score    REAL NOT NULL DEFAULT 0.5,
    reuse_count    INTEGER NOT NULL DEFAULT 0,
    tokens_saved   INTEGER DEFAULT 0,
    cost_saved     REAL DEFAULT 0.0,
    created_at     TEXT NOT NULL,
    last_reused_at TEXT,
    expires_at     TEXT,
    metadata       TEXT,
    UNIQUE(tenant_id, context_hash, decision_type)
);

CREATE INDEX IF NOT EXISTS idx_cache_tenant_context ON decision_cache(tenant_id, context_hash);
CREATE INDEX IF NOT EXISTS idx_cache_expires        ON decision_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_cache_trust          ON decision_cache(trust_score);

INSERT INTO schema_version (version, applied_at, description)
VALUES (2, datetime('now'), '002_decision_cache');
