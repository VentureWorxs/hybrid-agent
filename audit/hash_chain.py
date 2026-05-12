import hashlib
import json
from typing import Optional

HASH_FIELDS = [
    "event_id", "sequence_number", "previous_hash",
    "tenant_id", "machine_id", "session_id", "agent_version",
    "timestamp", "event_type", "actor",
    "subject_type", "subject_id", "action",
    "scope_level", "approval_status", "approval_by",
    "sensitivity_level",
    "tokens_used", "cost_usd", "execution_time_ms",
    "agent_routed_to", "boundary_enforced",
    "details",
]


def compute_event_hash(event, previous_hash: Optional[str] = None) -> str:
    canonical = {f: getattr(event, f, None) for f in HASH_FIELDS}
    canonical["previous_hash"] = previous_hash or ""
    serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def verify_chain(events: list) -> tuple[bool, Optional[str]]:
    """Walk the hash chain in sequence order. Returns (is_valid, error_message)."""
    expected_prev: Optional[str] = None
    expected_seq: int = 0

    for ev in events:
        if ev.sequence_number != expected_seq + 1:
            return False, (
                f"Sequence gap at {ev.event_id}: "
                f"expected {expected_seq + 1}, got {ev.sequence_number}"
            )
        if ev.previous_hash != expected_prev:
            return False, f"Chain break at {ev.event_id}: previous_hash mismatch"

        recomputed = compute_event_hash(ev, ev.previous_hash)
        if recomputed != ev.event_hash:
            return False, f"Hash mismatch at {ev.event_id}: stored != recomputed"

        expected_prev = ev.event_hash
        expected_seq = ev.sequence_number

    return True, None
