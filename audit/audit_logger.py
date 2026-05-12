import json
from datetime import datetime, timezone
from typing import Optional

from ulid import ULID

from .models import AuditEvent
from .sqlite_storage import SQLiteAuditStorage


class AuditLogger:
    def __init__(
        self,
        storage: SQLiteAuditStorage,
        tenant_id: str,
        machine_id: str,
        session_id: str,
        agent_version: str,
        sync_disabled: bool = False,
    ):
        self.storage = storage
        self.tenant_id = tenant_id
        self.machine_id = machine_id
        self.session_id = session_id
        self.agent_version = agent_version
        self.sync_disabled = sync_disabled

    def log(
        self,
        event_type: str,
        actor: str,
        action: str,
        sensitivity_level: str = "public",
        details: Optional[dict] = None,
        **kwargs,
    ) -> str:
        event = AuditEvent(
            event_id=str(ULID()),
            tenant_id=self.tenant_id,
            machine_id=self.machine_id,
            session_id=self.session_id,
            agent_version=self.agent_version,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            actor=actor,
            action=action,
            sensitivity_level=sensitivity_level,
            details=json.dumps(details) if details else None,
            sync_disabled=1 if self.sync_disabled else 0,
            **kwargs,
        )
        return self.storage.append_event(event)
