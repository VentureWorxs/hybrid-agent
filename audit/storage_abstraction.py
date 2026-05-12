from abc import ABC, abstractmethod
from typing import Iterator, Optional
from .models import AuditEvent


class AuditStorage(ABC):
    """Backend-agnostic interface for audit event storage."""

    @abstractmethod
    def append_event(self, event: AuditEvent) -> str:
        """Append a new event to the log. Returns the event_id."""
        ...

    @abstractmethod
    def get_event(self, event_id: str) -> Optional[AuditEvent]:
        ...

    @abstractmethod
    def iter_events(
        self,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        order: str = "asc",
        limit: Optional[int] = None,
    ) -> Iterator[AuditEvent]:
        ...

    @abstractmethod
    def get_latest_hash(self, machine_id: str) -> Optional[str]:
        """Return event_hash of most recent event for this machine."""
        ...

    @abstractmethod
    def get_latest_sequence(self, machine_id: str) -> int:
        """Return highest sequence_number for this machine, or 0 if none."""
        ...

    @abstractmethod
    def get_unsynced(self, limit: int = 100) -> list[AuditEvent]:
        """Return events not yet synced to D1 and not sync_disabled."""
        ...

    @abstractmethod
    def mark_synced(self, event_ids: list[str], synced_at: str) -> None:
        ...

    @abstractmethod
    def mark_sync_failed(self, event_id: str, error: str) -> None:
        ...

    @abstractmethod
    def verify_chain(
        self,
        machine_id: str,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        ...

    @abstractmethod
    def get_tenant(self, tenant_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def update_tenant_metadata(self, tenant_id: str, updates: dict) -> None:
        ...

    @abstractmethod
    def execute_fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        ...

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> None:
        ...
