"""
Generate synthetic test events in the local audit database.
Usage: python -m audit.test_fixtures --tenant=sam-personal --count=20
"""
import argparse
import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .audit_logger import AuditLogger
from .bootstrap import get_or_create_machine_id
from .migrate import apply_migrations
from .sqlite_storage import SQLiteAuditStorage

log = logging.getLogger(__name__)
DEFAULT_DB = Path.home() / ".hybrid-agent" / "audit.db"

ROUTES = ["ollama-local", "claude-api"]
SENSITIVITIES = ["public", "public", "public", "internal", "confidential", "sensitive_phi"]
EVENT_PAIRS = [
    ("task_started", "task_completed"),
    ("task_started", "task_failed"),
]


def generate_fixtures(
    tenant_id: str,
    db_path: Path,
    count: int = 20,
    agent_version: str = "1.1.0",
) -> None:
    apply_migrations(db_path)
    storage = SQLiteAuditStorage(db_path)
    machine_id = get_or_create_machine_id()
    session_id = str(uuid.uuid4())
    audit = AuditLogger(
        storage=storage,
        tenant_id=tenant_id,
        machine_id=machine_id,
        session_id=session_id,
        agent_version=agent_version,
    )

    for i in range(count):
        sensitivity = random.choice(SENSITIVITIES)
        route = "ollama-local" if sensitivity in ("confidential", "sensitive_phi") else random.choice(ROUTES)
        input_chars = random.randint(500, 10000)
        output_chars = random.randint(100, 2000)
        tokens = random.randint(50, 500) if route == "claude-api" else 0
        cost = tokens * 3.0 / 1_000_000 if route == "claude-api" else 0.0
        latency = random.randint(200, 5000)

        audit.log("task_started", "user", f"Task {i+1}: process request", sensitivity_level=sensitivity)
        audit.log(
            "agent_invoked",
            f"agent:{route}",
            f"Invoke {route} for task {i+1}",
            sensitivity_level=sensitivity,
            agent_routed_to=route,
            tokens_used=tokens,
            cost_usd=cost,
            execution_time_ms=latency,
            boundary_enforced=1 if sensitivity == "sensitive_phi" else 0,
            details={
                "input_chars": input_chars,
                "output_chars": output_chars,
                "estimated_claude_tokens": int((input_chars + output_chars) / 4.0),
                "estimated_claude_cost_usd": round((input_chars + output_chars) / 4.0 * 3.0 / 1_000_000, 6),
                "is_shadow": False,
            },
        )
        audit.log("task_completed", "orchestrator", f"Task {i+1} complete", sensitivity_level=sensitivity)

    log.info("Generated %d task groups for tenant=%s", count, tenant_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Generate test audit fixtures")
    parser.add_argument("--tenant", default="sam-personal")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    generate_fixtures(args.tenant, args.db, args.count)


if __name__ == "__main__":
    main()
