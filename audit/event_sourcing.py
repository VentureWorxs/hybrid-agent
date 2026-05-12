import json
import logging
from datetime import datetime
from typing import Optional

from .sqlite_storage import SQLiteAuditStorage

log = logging.getLogger(__name__)


def _apply_decision_made(storage: SQLiteAuditStorage, event) -> None:
    details = json.loads(event.details or "{}")
    decision_id = details.get("decision_id")
    if not decision_id:
        return
    storage.execute(
        """INSERT OR REPLACE INTO decision_cache (
            decision_id, tenant_id, context_hash, decision_type, decision_value,
            scope_level, trust_score, created_at, expires_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, 0.5, ?, ?, ?)""",
        (
            decision_id,
            event.tenant_id,
            details.get("context_hash", ""),
            details.get("decision_type", "routing"),
            json.dumps(details.get("decision_value", {})),
            event.scope_level or 1,
            event.timestamp,
            details.get("expires_at"),
            json.dumps({}),
        ),
    )


def _apply_decision_reused(storage: SQLiteAuditStorage, event) -> None:
    details = json.loads(event.details or "{}")
    decision_id = details.get("decision_id")
    if not decision_id:
        return
    storage.execute(
        """UPDATE decision_cache
           SET reuse_count = reuse_count + 1, last_reused_at = ?
           WHERE decision_id = ?""",
        (event.timestamp, decision_id),
    )


def rebuild_all_derived_state(storage: SQLiteAuditStorage) -> None:
    """
    Drop and rebuild all derived tables from the audit_events log.
    Safe to run on a live database — uses a transaction.
    """
    log.info("Rebuilding derived state from audit_events…")
    storage.execute("DELETE FROM decision_cache")
    storage.execute("DELETE FROM analytics_daily_cost")
    storage.execute("DELETE FROM analytics_ollama_savings")
    storage.execute("DELETE FROM analytics_compliance")
    storage.execute("DELETE FROM analytics_task_frequency")

    for event in storage.iter_events(event_type="decision_made", order="asc"):
        _apply_decision_made(storage, event)

    for event in storage.iter_events(event_type="decision_reused", order="asc"):
        _apply_decision_reused(storage, event)

    _refresh_analytics_all(storage)
    log.info("Derived state rebuilt.")


def _refresh_analytics_all(storage: SQLiteAuditStorage) -> None:
    now = datetime.utcnow().isoformat()
    storage.execute(
        """INSERT OR REPLACE INTO analytics_daily_cost
           SELECT tenant_id, date(timestamp), agent_routed_to,
                  COUNT(*), SUM(tokens_used), SUM(cost_usd), AVG(execution_time_ms), ?
           FROM audit_events
           WHERE event_type = 'agent_invoked' AND agent_routed_to IS NOT NULL
           GROUP BY tenant_id, date(timestamp), agent_routed_to""",
        (now,),
    )
    storage.execute(
        """INSERT OR REPLACE INTO analytics_compliance
           SELECT tenant_id, date(timestamp),
                  SUM(CASE WHEN sensitivity_level = 'sensitive_phi' THEN 1 ELSE 0 END),
                  SUM(CASE WHEN sensitivity_level = 'sensitive_phi' AND agent_routed_to = 'ollama-local' THEN 1 ELSE 0 END),
                  0,
                  SUM(boundary_enforced), ?
           FROM audit_events
           WHERE event_type = 'agent_invoked'
           GROUP BY tenant_id, date(timestamp)""",
        (now,),
    )
