"""
Verify that sanitization pipeline correctly handles each sensitivity level.
Usage: python -m audit.test_sanitization
"""
import json
import logging
from datetime import datetime, timezone

from .models import AuditEvent
from .sanitization import SanitizationPipeline

log = logging.getLogger(__name__)


def _make_event(sensitivity: str, details: dict | None = None) -> AuditEvent:
    return AuditEvent(
        event_id="test-01",
        sequence_number=1,
        previous_hash=None,
        event_hash="abc",
        tenant_id="propel",
        machine_id="machine-01",
        session_id="session-01",
        agent_version="1.1.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type="agent_invoked",
        actor="orchestrator",
        subject_type="task",
        subject_id="task-99",
        action="Processed patient record for john.doe@hospital.com",
        sensitivity_level=sensitivity,
        agent_routed_to="ollama-local",
        tokens_used=0,
        cost_usd=0.0,
        details=json.dumps(details or {"raw": "sensitive data", "phi": True}),
    )


def test_sanitization() -> None:
    pipeline = SanitizationPipeline()
    results: dict[str, str] = {}

    public_ev = _make_event("public")
    out = pipeline.sanitize(public_ev)
    assert out is not None, "public events must pass through"
    assert out.subject_id == "task-99", "public events must not be modified"
    results["public"] = "pass"

    internal_ev = _make_event("internal")
    out = pipeline.sanitize(internal_ev)
    assert out is not None
    assert "john.doe@hospital.com" not in (out.action or ""), "email must be redacted"
    results["internal"] = "pass (email redacted)"

    confidential_ev = _make_event("confidential")
    out = pipeline.sanitize(confidential_ev)
    assert out is not None
    details = json.loads(out.details or "{}")
    assert details.get("sanitized") is True, "confidential details must be stripped"
    assert out.subject_id is None, "subject_id must be cleared"
    results["confidential"] = "pass (details stripped)"

    phi_ev = _make_event("sensitive_phi")
    out = pipeline.sanitize(phi_ev)
    assert out is not None, "PHI events produce a shadow — not dropped"
    assert out.subject_id is None, "PHI shadow must not contain subject_id"
    assert out.subject_type is None, "PHI shadow must not contain subject_type"
    assert "PHI" in out.action, "PHI shadow action must indicate confinement"
    details = json.loads(out.details or "{}")
    assert details.get("phi_confinement") == "enforced"
    results["sensitive_phi"] = "pass (shadow event emitted, no content)"

    unknown_ev = _make_event("unknown_level")
    out = pipeline.sanitize(unknown_ev)
    assert out is None, "Unknown sensitivity must be dropped"
    results["unknown"] = "pass (dropped)"

    print("\nSanitization test results:")
    for level, verdict in results.items():
        print(f"  {level}: {verdict}")
    print("\nAll sanitization tests passed.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_sanitization()
