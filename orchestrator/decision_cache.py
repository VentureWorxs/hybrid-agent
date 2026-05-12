import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ulid import ULID

from audit.sqlite_storage import SQLiteAuditStorage

log = logging.getLogger(__name__)


class DecisionCache:
    def __init__(self, storage: SQLiteAuditStorage, audit_logger):
        self.storage = storage
        self.audit = audit_logger

    @staticmethod
    def compute_context_hash(context: dict) -> str:
        canonical = json.dumps(context, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def lookup(
        self, tenant_id: str, context: dict, decision_type: str
    ) -> Optional[dict]:
        h = self.compute_context_hash(context)
        row = self.storage.execute_fetchone(
            """SELECT * FROM decision_cache
               WHERE tenant_id = ? AND context_hash = ? AND decision_type = ?
                 AND (expires_at IS NULL OR expires_at > datetime('now'))""",
            (tenant_id, h, decision_type),
        )
        if not row:
            return None

        self.audit.log(
            event_type="decision_reused",
            actor="orchestrator",
            action=f"Reused cached decision: {decision_type}",
            details={"decision_id": row["decision_id"], "context_hash": h},
        )
        self.storage.execute(
            """UPDATE decision_cache
               SET reuse_count = reuse_count + 1, last_reused_at = datetime('now')
               WHERE decision_id = ?""",
            (row["decision_id"],),
        )
        return dict(row)

    def store(
        self,
        tenant_id: str,
        context: dict,
        decision_type: str,
        decision_value: dict,
        scope_level: int,
        ttl_hours: Optional[int] = 24,
        **metadata,
    ) -> str:
        h = self.compute_context_hash(context)
        decision_id = str(ULID())
        expires_at = None
        if ttl_hours:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            ).isoformat()

        self.audit.log(
            event_type="decision_made",
            actor="orchestrator",
            action=f"Cached decision: {decision_type}",
            scope_level=scope_level,
            details={
                "decision_id": decision_id,
                "context_hash": h,
                "decision_type": decision_type,
                "decision_value": decision_value,
                "expires_at": expires_at,
                **metadata,
            },
        )

        self.storage.execute(
            """INSERT OR REPLACE INTO decision_cache (
                decision_id, tenant_id, context_hash, decision_type, decision_value,
                scope_level, trust_score, created_at, expires_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, 0.5, datetime('now'), ?, ?)""",
            (
                decision_id,
                tenant_id,
                h,
                decision_type,
                json.dumps(decision_value),
                scope_level,
                expires_at,
                json.dumps(metadata),
            ),
        )
        return decision_id

    def expire_stale(self) -> int:
        """Remove expired entries. Returns count deleted."""
        row = self.storage.execute_fetchone(
            "SELECT COUNT(*) AS n FROM decision_cache WHERE expires_at <= datetime('now')"
        )
        n = row["n"] if row else 0
        self.storage.execute(
            "DELETE FROM decision_cache WHERE expires_at <= datetime('now')"
        )
        return n
