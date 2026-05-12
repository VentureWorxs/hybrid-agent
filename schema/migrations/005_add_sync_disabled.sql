-- Migration 005: Local-only audit mode (ADR-002.0 Section 6)
-- sync_disabled = 1 means this event will never be synced to D1,
-- regardless of audit_sync_enabled setting.

ALTER TABLE audit_events ADD COLUMN sync_disabled INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_events_sync_disabled
    ON audit_events(sync_disabled, synced_to_d1, timestamp);

INSERT INTO schema_version (version, applied_at, description)
VALUES (5, datetime('now'), '005_add_sync_disabled');
