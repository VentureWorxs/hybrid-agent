-- Migration 003: Analytics aggregation tables

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

CREATE TABLE IF NOT EXISTS analytics_task_frequency (
    tenant_id    TEXT NOT NULL,
    task_pattern TEXT NOT NULL,
    week_start   TEXT NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0,
    total_cost   REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (tenant_id, task_pattern, week_start)
);

INSERT INTO schema_version (version, applied_at, description)
VALUES (3, datetime('now'), '003_analytics_views');
