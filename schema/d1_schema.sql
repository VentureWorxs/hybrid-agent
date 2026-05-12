-- D1 schema (Cloudflare D1 replica — sanitized subset)
-- D1 does not support WAL or most PRAGMAs; omit them here.
-- Apply via: wrangler d1 execute hybrid-agent-audit --file=schema/d1_schema.sql

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id          TEXT PRIMARY KEY,
    sequence_number   INTEGER NOT NULL,
    previous_hash     TEXT,
    event_hash        TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    machine_id        TEXT NOT NULL,
    session_id        TEXT NOT NULL,
    agent_version     TEXT NOT NULL,
    timestamp         TEXT NOT NULL,
    event_type        TEXT NOT NULL,
    actor             TEXT NOT NULL,
    subject_type      TEXT,
    subject_id        TEXT,
    action            TEXT NOT NULL,
    scope_level       INTEGER,
    approval_status   TEXT,
    approval_by       TEXT,
    sensitivity_level TEXT NOT NULL DEFAULT 'public',
    tokens_used       INTEGER DEFAULT 0,
    cost_usd          REAL DEFAULT 0.0,
    execution_time_ms INTEGER,
    agent_routed_to   TEXT,
    boundary_enforced INTEGER DEFAULT 0,
    details           TEXT
    -- Note: synced_* and sync_disabled columns are local-only; not replicated to D1
);

CREATE INDEX IF NOT EXISTS idx_events_tenant_time  ON audit_events(tenant_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type         ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_sensitivity  ON audit_events(sensitivity_level);
CREATE INDEX IF NOT EXISTS idx_events_routed_to    ON audit_events(agent_routed_to);
CREATE INDEX IF NOT EXISTS idx_events_tenant_type  ON audit_events(tenant_id, event_type, timestamp);

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id    TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    metadata     TEXT
);

CREATE TABLE IF NOT EXISTS machines (
    machine_id  TEXT PRIMARY KEY,
    hostname    TEXT,
    platform    TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    metadata    TEXT
);

CREATE TABLE IF NOT EXISTS analytics_daily_cost (
    tenant_id       TEXT NOT NULL,
    date            TEXT NOT NULL,
    agent_routed_to TEXT NOT NULL,
    task_count      INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    total_cost_usd  REAL NOT NULL DEFAULT 0.0,
    avg_latency_ms  REAL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (tenant_id, date, agent_routed_to)
);

CREATE TABLE IF NOT EXISTS analytics_ollama_savings (
    tenant_id             TEXT NOT NULL,
    date                  TEXT NOT NULL,
    ollama_task_count     INTEGER NOT NULL DEFAULT 0,
    claude_task_count     INTEGER NOT NULL DEFAULT 0,
    estimated_savings_usd REAL NOT NULL DEFAULT 0.0,
    avg_latency_local_ms  REAL,
    avg_latency_cloud_ms  REAL,
    updated_at            TEXT NOT NULL,
    PRIMARY KEY (tenant_id, date)
);

CREATE TABLE IF NOT EXISTS analytics_compliance (
    tenant_id               TEXT NOT NULL,
    date                    TEXT NOT NULL,
    phi_task_count          INTEGER NOT NULL DEFAULT 0,
    confined_local_count    INTEGER NOT NULL DEFAULT 0,
    boundary_violations     INTEGER NOT NULL DEFAULT 0,
    boundary_enforced_count INTEGER NOT NULL DEFAULT 0,
    updated_at              TEXT NOT NULL,
    PRIMARY KEY (tenant_id, date)
);

INSERT INTO schema_version (version, applied_at, description)
VALUES (5, datetime('now'), 'd1_initial_full');
