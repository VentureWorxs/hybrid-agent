import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .hash_chain import compute_event_hash, verify_chain as _verify_chain
from .models import AuditEvent
from .storage_abstraction import AuditStorage


class SQLiteAuditStorage(AuditStorage):
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.row_factory = sqlite3.Row

    def append_event(self, event: AuditEvent) -> str:
        prev_hash = self.get_latest_hash(event.machine_id)
        prev_seq = self.get_latest_sequence(event.machine_id)
        event.previous_hash = prev_hash
        event.sequence_number = prev_seq + 1
        event.event_hash = compute_event_hash(event, prev_hash)

        self._conn.execute(
            """INSERT INTO audit_events (
                event_id, sequence_number, previous_hash, event_hash,
                tenant_id, machine_id, session_id, agent_version,
                timestamp, event_type, actor, subject_type, subject_id, action,
                scope_level, approval_status, approval_by,
                sensitivity_level, tokens_used, cost_usd, execution_time_ms,
                agent_routed_to, boundary_enforced, details, sync_disabled
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            event.to_db_row(),
        )
        return event.event_id

    def get_event(self, event_id: str) -> Optional[AuditEvent]:
        row = self._conn.execute(
            "SELECT * FROM audit_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return AuditEvent.from_db_row(dict(row)) if row else None

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

        for row in self._conn.execute(sql, params):
            yield AuditEvent.from_db_row(dict(row))

    def get_latest_hash(self, machine_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT event_hash FROM audit_events WHERE machine_id = ? ORDER BY sequence_number DESC LIMIT 1",
            (machine_id,),
        ).fetchone()
        return row["event_hash"] if row else None

    def get_latest_sequence(self, machine_id: str) -> int:
        row = self._conn.execute(
            "SELECT MAX(sequence_number) AS seq FROM audit_events WHERE machine_id = ?",
            (machine_id,),
        ).fetchone()
        return row["seq"] or 0

    def get_unsynced(self, limit: int = 100) -> list[AuditEvent]:
        rows = self._conn.execute(
            """SELECT * FROM audit_events
               WHERE synced_to_d1 = 0 AND sync_disabled = 0
               ORDER BY timestamp ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [AuditEvent.from_db_row(dict(r)) for r in rows]

    def mark_synced(self, event_ids: list[str], synced_at: str) -> None:
        placeholders = ",".join("?" * len(event_ids))
        self._conn.execute(
            f"UPDATE audit_events SET synced_to_d1 = 1, synced_at = ? WHERE event_id IN ({placeholders})",
            [synced_at, *event_ids],
        )

    def mark_sync_failed(self, event_id: str, error: str) -> None:
        self._conn.execute(
            """UPDATE audit_events
               SET sync_attempts = sync_attempts + 1, sync_error = ?
               WHERE event_id = ?""",
            (error, event_id),
        )

    def verify_chain(
        self,
        machine_id: str,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        clauses = ["machine_id = ?"]
        params: list = [machine_id]
        if start_seq is not None:
            clauses.append("sequence_number >= ?")
            params.append(start_seq)
        if end_seq is not None:
            clauses.append("sequence_number <= ?")
            params.append(end_seq)
        where = "WHERE " + " AND ".join(clauses)
        rows = self._conn.execute(
            f"SELECT * FROM audit_events {where} ORDER BY sequence_number ASC", params
        ).fetchall()
        events = [AuditEvent.from_db_row(dict(r)) for r in rows]
        return _verify_chain(events)

    def get_tenant(self, tenant_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"] or "{}")
        return d

    def update_tenant_metadata(self, tenant_id: str, updates: dict) -> None:
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Unknown tenant: {tenant_id}")
        metadata = tenant["metadata"]
        metadata.update(updates)
        self._conn.execute(
            "UPDATE tenants SET metadata = ? WHERE tenant_id = ?",
            (json.dumps(metadata), tenant_id),
        )

    def execute_fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def execute_fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.execute(sql, params)

    def close(self) -> None:
        self._conn.close()
