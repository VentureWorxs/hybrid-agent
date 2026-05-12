-- Migration 004: Additional performance indexes

CREATE INDEX IF NOT EXISTS idx_events_routed_to   ON audit_events(agent_routed_to);
CREATE INDEX IF NOT EXISTS idx_events_boundary    ON audit_events(boundary_enforced);
CREATE INDEX IF NOT EXISTS idx_events_approval    ON audit_events(approval_status);
CREATE INDEX IF NOT EXISTS idx_events_tenant_type ON audit_events(tenant_id, event_type, timestamp);

INSERT INTO schema_version (version, applied_at, description)
VALUES (4, datetime('now'), '004_indexes_phase2');
