from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    event_id: str
    sequence_number: int = 0
    previous_hash: Optional[str] = None
    event_hash: Optional[str] = None

    tenant_id: str
    machine_id: str
    session_id: str
    agent_version: str

    timestamp: str
    event_type: str
    actor: str
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    action: str

    scope_level: Optional[int] = None
    approval_status: Optional[str] = None
    approval_by: Optional[str] = None

    sensitivity_level: str = "public"
    tokens_used: int = 0
    cost_usd: float = 0.0
    execution_time_ms: Optional[int] = None
    agent_routed_to: Optional[str] = None
    boundary_enforced: int = 0

    details: Optional[str] = None  # JSON string

    # Local-only sync state (not written to D1)
    synced_to_d1: int = 0
    synced_at: Optional[str] = None
    sync_attempts: int = 0
    sync_error: Optional[str] = None
    sync_disabled: int = 0

    def to_db_row(self) -> tuple:
        return (
            self.event_id, self.sequence_number, self.previous_hash, self.event_hash,
            self.tenant_id, self.machine_id, self.session_id, self.agent_version,
            self.timestamp, self.event_type, self.actor,
            self.subject_type, self.subject_id, self.action,
            self.scope_level, self.approval_status, self.approval_by,
            self.sensitivity_level, self.tokens_used, self.cost_usd,
            self.execution_time_ms, self.agent_routed_to, self.boundary_enforced,
            self.details, self.sync_disabled,
        )

    @classmethod
    def from_db_row(cls, row: dict) -> AuditEvent:
        return cls(**{k: row[k] for k in row.keys() if k in cls.model_fields})
