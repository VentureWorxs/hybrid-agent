"""
D1AuditStorage — HTTP client for Cloudflare D1 REST API.

Used primarily by the dashboard for read queries.
The local agent always writes to SQLiteAuditStorage first;
the sync worker pushes batches here.
"""
import json
from typing import Iterator, Optional

import httpx

from .models import AuditEvent
from .storage_abstraction import AuditStorage


class D1AuditStorage(AuditStorage):
    def __init__(self, account_id: str, database_id: str, api_token: str):
        self.base_url = (
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
            f"/d1/database/{database_id}"
        )
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    def _query(self, sql: str, params: list | None = None) -> dict:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{self.base_url}/query",
                headers=self.headers,
                json={"sql": sql, "params": params or []},
            )
            resp.raise_for_status()
            return resp.json()

    def append_event(self, event: AuditEvent) -> str:
        """Used only by the sync worker, not by the local agent directly."""
        row = event.to_db_row()
        sql = """INSERT OR IGNORE INTO audit_events (
            event_id, sequence_number, previous_hash, event_hash,
            tenant_id, machine_id, session_id, agent_version, timestamp,
            event_type, actor, subject_type, subject_id, action,
            scope_level, approval_status, approval_by,
            sensitivity_level, tokens_used, cost_usd, execution_time_ms,
            agent_routed_to, boundary_enforced, details
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        # D1 REST API requires the row without sync_disabled (local-only column)
        self._query(sql, list(row[:24]))
        return event.event_id

    def get_event(self, event_id: str) -> Optional[AuditEvent]:
        result = self._query(
            "SELECT * FROM audit_events WHERE event_id = ?", [event_id]
        )
        rows = result.get("result", [{}])[0].get("results", [])
        return AuditEvent.from_db_row(rows[0]) if rows else None

    def iter_events(
        self,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        order: str = "asc",
        limit: Optional[int] = None,
    ) -> Iterator[AuditEvent]:
        clauses, params = [], []
        if tenant_id:
            clauses.append("tenant_id = ?")
            params.append(tenant_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp < ?")
            params.append(until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        direction = "ASC" if order == "asc" else "DESC"
        lim = f"LIMIT {limit}" if limit else ""
        sql = f"SELECT * FROM audit_events {where} ORDER BY sequence_number {direction} {lim}"
        result = self._query(sql, params)
        for row in result.get("result", [{}])[0].get("results", []):
            yield AuditEvent.from_db_row(row)

    def get_latest_hash(self, machine_id: str) -> Optional[str]:
        result = self._query(
            "SELECT event_hash FROM audit_events WHERE machine_id = ? ORDER BY sequence_number DESC LIMIT 1",
            [machine_id],
        )
        rows = result.get("result", [{}])[0].get("results", [])
        return rows[0]["event_hash"] if rows else None

    def get_latest_sequence(self, machine_id: str) -> int:
        result = self._query(
            "SELECT MAX(sequence_number) AS seq FROM audit_events WHERE machine_id = ?",
            [machine_id],
        )
        rows = result.get("result", [{}])[0].get("results", [])
        return rows[0]["seq"] or 0 if rows else 0

    def get_unsynced(self, limit: int = 100) -> list[AuditEvent]:
        return []  # D1 is the sync destination; no unsynced concept here

    def mark_synced(self, event_ids: list[str], synced_at: str) -> None:
        pass  # No-op for D1

    def mark_sync_failed(self, event_id: str, error: str) -> None:
        pass  # No-op for D1

    def verify_chain(
        self,
        machine_id: str,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        raise NotImplementedError("Hash chain verification must be done against local SQLite")

    def get_tenant(self, tenant_id: str) -> Optional[dict]:
        result = self._query(
            "SELECT * FROM tenants WHERE tenant_id = ?", [tenant_id]
        )
        rows = result.get("result", [{}])[0].get("results", [])
        if not rows:
            return None
        d = dict(rows[0])
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return d

    def update_tenant_metadata(self, tenant_id: str, updates: dict) -> None:
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Unknown tenant: {tenant_id}")
        metadata = tenant["metadata"]
        metadata.update(updates)
        self._query(
            "UPDATE tenants SET metadata = ? WHERE tenant_id = ?",
            [json.dumps(metadata), tenant_id],
        )

    def execute_fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        result = self._query(sql, list(params))
        rows = result.get("result", [{}])[0].get("results", [])
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._query(sql, list(params))
