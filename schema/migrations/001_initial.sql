-- Migration 001: Initial schema — audit_events, tenants, machines
-- Applies to: local SQLite and Cloudflare D1

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

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
    details           TEXT,
    synced_to_d1      INTEGER DEFAULT 0,
    synced_at         TEXT,
    sync_attempts     INTEGER DEFAULT 0,
    sync_error        TEXT,
    UNIQUE(machine_id, sequence_number)
);

CREATE INDEX IF NOT EXISTS idx_events_tenant_time  ON audit_events(tenant_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type         ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_subject      ON audit_events(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_events_sync         ON audit_events(synced_to_d1, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_sensitivity  ON audit_events(sensitivity_level);
CREATE INDEX IF NOT EXISTS idx_events_session      ON audit_events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_machine_seq  ON audit_events(machine_id, sequence_number);

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id    TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    metadata     TEXT
);

INSERT OR IGNORE INTO tenants (tenant_id, display_name, created_at, metadata) VALUES
    ('sam-personal', 'Sam (Personal)',  datetime('now'), '{"phi_allowed": false}'),
    ('nicheworxs',   'NicheWorxs',      datetime('now'), '{"phi_allowed": false}'),
    ('propel',       'Propel (HIPAA)',  datetime('now'), '{"phi_allowed": true, "retention_days": 2555}');

CREATE TABLE IF NOT EXISTS machines (
    machine_id  TEXT PRIMARY KEY,
    hostname    TEXT,
    platform    TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    metadata    TEXT
);

INSERT INTO schema_version (version, applied_at, description)
VALUES (1, datetime('now'), '001_initial');
