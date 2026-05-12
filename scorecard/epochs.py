from __future__ import annotations
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class Epoch:
    epoch_id: str           # event_id of config_changed, or 'genesis'
    sequence: int           # 1-based order from start of log
    started_at: str         # ISO8601
    ended_at: Optional[str] # None if current epoch
    operating_mode: str
    audit_sync_enabled: bool
    tenant_id: str
    config_snapshot: dict = field(default_factory=dict)

    def duration_hours(self) -> float:
        end = self.ended_at or datetime.now(timezone.utc).isoformat()
        start_dt = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (end_dt - start_dt).total_seconds() / 3600

    def to_dict(self) -> dict:
        return {
            "epoch_id": self.epoch_id,
            "sequence": self.sequence,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "operating_mode": self.operating_mode,
            "audit_sync_enabled": self.audit_sync_enabled,
            "tenant_id": self.tenant_id,
            "config_snapshot": self.config_snapshot,
        }


def get_epochs(storage, tenant_id: str) -> list[Epoch]:
    """
    Return epochs for a tenant, newest first.
    Epochs are defined by config_changed events.
    The period before any config_changed is epoch 'genesis'.
    """
    rows = list(storage.iter_events(
        tenant_id=tenant_id,
        event_type="config_changed",
        order="asc",
    ))

    # Seed config state
    config_state = {"operating_mode": "hybrid", "audit_sync_enabled": True}
    boundaries: list[tuple[str, str, dict]] = []  # (event_id, timestamp, snapshot_after_change)

    for row in rows:
        details = json.loads(row.details or "{}")
        field_name = details.get("field", "")
        new_val = details.get("new_value")
        if field_name == "operating_mode":
            config_state["operating_mode"] = new_val
        elif field_name == "audit_sync_enabled":
            config_state["audit_sync_enabled"] = bool(new_val)
        boundaries.append((row.event_id, row.timestamp, dict(config_state)))

    if not boundaries:
        # Only genesis epoch
        first = storage.execute_fetchone(
            "SELECT MIN(timestamp) AS t FROM audit_events WHERE tenant_id = ?",
            (tenant_id,),
        )
        start = (first or {}).get("t") or datetime.now(timezone.utc).isoformat()
        return [Epoch(
            epoch_id="genesis",
            sequence=1,
            started_at=start,
            ended_at=None,
            operating_mode="hybrid",
            audit_sync_enabled=True,
            tenant_id=tenant_id,
        )]

    epochs: list[Epoch] = []
    first_ts_row = storage.execute_fetchone(
        "SELECT MIN(timestamp) AS t FROM audit_events WHERE tenant_id = ?",
        (tenant_id,),
    )
    first_ts = (first_ts_row or {}).get("t") or boundaries[0][1]

    # Genesis epoch: before first config_changed
    genesis_snapshot = {"operating_mode": "hybrid", "audit_sync_enabled": True}
    epochs.append(Epoch(
        epoch_id="genesis",
        sequence=1,
        started_at=first_ts,
        ended_at=boundaries[0][1],
        operating_mode=genesis_snapshot["operating_mode"],
        audit_sync_enabled=genesis_snapshot["audit_sync_enabled"],
        tenant_id=tenant_id,
        config_snapshot=genesis_snapshot,
    ))

    for i, (event_id, timestamp, snapshot) in enumerate(boundaries):
        next_ts = boundaries[i + 1][1] if i + 1 < len(boundaries) else None
        epochs.append(Epoch(
            epoch_id=event_id,
            sequence=i + 2,
            started_at=timestamp,
            ended_at=next_ts,
            operating_mode=snapshot["operating_mode"],
            audit_sync_enabled=snapshot["audit_sync_enabled"],
            tenant_id=tenant_id,
            config_snapshot=snapshot,
        ))

    epochs.reverse()  # newest first
    return epochs


def get_current_epoch(storage, tenant_id: str) -> Epoch:
    return get_epochs(storage, tenant_id)[0]


def resolve_epoch(storage, tenant_id: str, selector: str, period: Optional[str] = None) -> Epoch:
    """
    Resolve a CLI epoch selector to an Epoch object.
    Selectors: CURRENT, PREV, GENESIS, or a numeric sequence number.
    period overrides: 24h, 7d, 30d, all → returns a synthetic epoch covering that window.
    """
    if period:
        return _period_to_epoch(storage, tenant_id, period)

    epochs = get_epochs(storage, tenant_id)
    if selector.upper() == "CURRENT":
        return epochs[0]
    if selector.upper() == "PREV" and len(epochs) > 1:
        return epochs[1]
    if selector.upper() == "GENESIS":
        return epochs[-1]

    try:
        seq = int(selector)
        for ep in epochs:
            if ep.sequence == seq:
                return ep
        raise ValueError(f"Epoch #{seq} not found for tenant {tenant_id}")
    except ValueError:
        pass

    raise ValueError(f"Unknown epoch selector: {selector!r}")


def _period_to_epoch(storage, tenant_id: str, period: str) -> Epoch:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    if period == "24h":
        start = now - timedelta(hours=24)
    elif period == "7d":
        start = now - timedelta(days=7)
    elif period == "30d":
        start = now - timedelta(days=30)
    elif period == "all":
        row = storage.execute_fetchone(
            "SELECT MIN(timestamp) AS t FROM audit_events WHERE tenant_id = ?",
            (tenant_id,),
        )
        start = datetime.fromisoformat((row or {}).get("t", now.isoformat()).replace("Z", "+00:00"))
    else:
        raise ValueError(f"Unknown period: {period!r}")

    return Epoch(
        epoch_id=f"period-{period}",
        sequence=0,
        started_at=start.isoformat(),
        ended_at=now.isoformat(),
        operating_mode="mixed",
        audit_sync_enabled=True,
        tenant_id=tenant_id,
    )
