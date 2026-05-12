"""
Bootstrap a new machine: generate machine_id, register in DB, emit initial event.
Usage: python -m audit.bootstrap --tenant=sam-personal
"""
import argparse
import logging
import platform
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .audit_logger import AuditLogger
from .migrate import apply_migrations
from .sqlite_storage import SQLiteAuditStorage

log = logging.getLogger(__name__)

MACHINE_ID_FILE = Path.home() / ".hybrid-agent" / "machine_id"
DEFAULT_DB = Path.home() / ".hybrid-agent" / "audit.db"


def get_or_create_machine_id() -> str:
    if MACHINE_ID_FILE.exists():
        return MACHINE_ID_FILE.read_text().strip()
    machine_id = str(uuid.uuid4())
    MACHINE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    MACHINE_ID_FILE.write_text(machine_id)
    return machine_id


def bootstrap(tenant_id: str, db_path: Path, agent_version: str = "1.1.0") -> str:
    apply_migrations(db_path)
    storage = SQLiteAuditStorage(db_path)
    machine_id = get_or_create_machine_id()
    session_id = str(uuid.uuid4())
    hostname = socket.gethostname()
    plat = f"{platform.system().lower()}-{platform.machine().lower()}"
    now = datetime.now(timezone.utc).isoformat()

    # Register machine if not already present
    existing = storage.execute_fetchone(
        "SELECT 1 FROM machines WHERE machine_id = ?", (machine_id,)
    )
    if not existing:
        storage.execute(
            "INSERT INTO machines (machine_id, hostname, platform, first_seen, last_seen) VALUES (?,?,?,?,?)",
            (machine_id, hostname, plat, now, now),
        )
        log.info("Registered new machine %s (%s, %s)", machine_id, hostname, plat)
    else:
        storage.execute(
            "UPDATE machines SET last_seen = ? WHERE machine_id = ?", (now, machine_id)
        )

    audit = AuditLogger(
        storage=storage,
        tenant_id=tenant_id,
        machine_id=machine_id,
        session_id=session_id,
        agent_version=agent_version,
    )
    audit.log(
        event_type="task_started",
        actor="system",
        action=f"Bootstrap: machine {machine_id} registered for tenant {tenant_id}",
        details={"hostname": hostname, "platform": plat, "agent_version": agent_version},
    )
    log.info("Bootstrap complete. machine_id=%s", machine_id)
    return machine_id


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Bootstrap hybrid-agent on this machine")
    parser.add_argument("--tenant", default="sam-personal")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--agent-version", default="1.1.0")
    args = parser.parse_args()
    bootstrap(args.tenant, args.db, args.agent_version)


if __name__ == "__main__":
    main()
