import json
import re
from typing import Optional

from .models import AuditEvent

_PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),                       # phone
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                                    # SSN
]


def _redact_pii(text: str) -> str:
    for pattern in _PII_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


class SanitizationPipeline:
    """
    Sanitizes events before they leave the local machine for D1.

    Rules by sensitivity_level:
    - public:        No changes.
    - internal:      Redact PII in details field.
    - confidential:  Strip details to metadata summary only.
    - sensitive_phi: Replace with a shadow event containing no content.
    Unknown levels: drop the event (fail closed).
    """

    def sanitize(self, event: AuditEvent) -> Optional[AuditEvent]:
        level = event.sensitivity_level
        if level == "public":
            return event
        if level == "internal":
            return self._redact_pii(event)
        if level == "confidential":
            return self._strip_to_metadata(event)
        if level == "sensitive_phi":
            return self._emit_shadow_event(event)
        return None  # fail closed on unknown level

    def _redact_pii(self, event: AuditEvent) -> AuditEvent:
        if event.details:
            event = event.model_copy()
            event.details = _redact_pii(event.details)
        if event.action:
            event = event.model_copy()
            event.action = _redact_pii(event.action)
        return event

    def _strip_to_metadata(self, event: AuditEvent) -> AuditEvent:
        original_size = len(event.details or "")
        event = event.model_copy()
        event.details = json.dumps({
            "sanitized": True,
            "original_details_size_bytes": original_size,
            "summary": f"{event.event_type} event redacted at sync time",
        })
        event.subject_id = None
        return event

    def _emit_shadow_event(self, event: AuditEvent) -> AuditEvent:
        return AuditEvent(
            event_id=event.event_id,
            sequence_number=event.sequence_number,
            previous_hash=event.previous_hash,
            event_hash=event.event_hash,
            tenant_id=event.tenant_id,
            machine_id=event.machine_id,
            session_id=event.session_id,
            agent_version=event.agent_version,
            timestamp=event.timestamp,
            event_type=event.event_type,
            actor=event.actor,
            subject_type=None,
            subject_id=None,
            action="[PHI event — confined to local storage per HIPAA]",
            scope_level=event.scope_level,
            approval_status=event.approval_status,
            approval_by=event.approval_by,
            sensitivity_level="sensitive_phi",
            tokens_used=event.tokens_used,
            cost_usd=event.cost_usd,
            execution_time_ms=event.execution_time_ms,
            agent_routed_to=event.agent_routed_to,
            boundary_enforced=1,
            details=json.dumps({"phi_confinement": "enforced", "compliance_framework": "HIPAA"}),
        )
