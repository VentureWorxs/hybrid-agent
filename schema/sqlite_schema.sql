-- Full SQLite schema (convenience file — migrations are authoritative)
-- Run migrations individually in order rather than this file in production.
-- This file is useful for standing up a fresh dev/test database.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Run all migrations in order
.read schema/migrations/001_initial.sql
.read schema/migrations/002_decision_cache.sql
.read schema/migrations/003_analytics_views.sql
.read schema/migrations/004_indexes_phase2.sql
.read schema/migrations/005_add_sync_disabled.sql
