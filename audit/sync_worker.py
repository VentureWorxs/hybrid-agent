"""
Background sync worker: reads unsynced events from local SQLite,
sanitizes them, and pushes to the Cloudflare Worker endpoint.
Run as: python -m audit.sync_worker --tenant=sam-personal
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from .d1_client import D1WorkerClient
from .sanitization import SanitizationPipeline
from .sqlite_storage import SQLiteAuditStorage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_DB = Path.home() / ".hybrid-agent" / "audit.db"
DEFAULT_BATCH = 100
DEFAULT_INTERVAL = 300


def sync_once(
    storage: SQLiteAuditStorage,
    sanitizer: SanitizationPipeline,
    d1_client: D1WorkerClient,
    batch_size: int = DEFAULT_BATCH,
) -> int:
    unsynced = storage.get_unsynced(limit=batch_size)
    if not unsynced:
        return 0

    sanitized = [sanitizer.sanitize(ev) for ev in unsynced]
    sanitized = [ev for ev in sanitized if ev is not None]

    if not sanitized:
        log.info("All %d events dropped by sanitization (likely PHI)", len(unsynced))
        return 0

    response = d1_client.push_batch(sanitized)
    now = datetime.now(timezone.utc).isoformat()

    success_ids, fail_count = [], 0
    for event_id, status in response.items():
        if status in ("success", "duplicate_skipped"):
            success_ids.append(event_id)
        else:
            storage.mark_sync_failed(event_id, status)
            fail_count += 1

    if success_ids:
        storage.mark_synced(success_ids, now)

    dropped = len(unsynced) - len(sanitized)
    log.info(
        "Sync: %d sent, %d succeeded, %d failed, %d dropped (PHI/sanitization)",
        len(sanitized), len(success_ids), fail_count, dropped,
    )
    return len(success_ids)


def sync_loop(
    storage: SQLiteAuditStorage,
    sanitizer: SanitizationPipeline,
    d1_client: D1WorkerClient,
    batch_size: int = DEFAULT_BATCH,
    interval_seconds: int = DEFAULT_INTERVAL,
) -> None:
    log.info("Sync worker started (interval=%ds, batch=%d)", interval_seconds, batch_size)
    while True:
        try:
            sync_once(storage, sanitizer, d1_client, batch_size)
        except Exception:
            log.exception("Sync loop error — will retry")
        time.sleep(interval_seconds)


def backfill_sync(
    storage: SQLiteAuditStorage,
    since: datetime,
    dry_run: bool = True,
) -> int:
    """Mark local-only events as sync-eligible (except sensitive_phi)."""
    if dry_run:
        row = storage.execute_fetchone(
            """SELECT COUNT(*) AS n FROM audit_events
               WHERE sync_disabled = 1
                 AND sensitivity_level != 'sensitive_phi'
                 AND timestamp >= ?""",
            (since.isoformat(),),
        )
        return row["n"] if row else 0

    storage.execute(
        """UPDATE audit_events
           SET sync_disabled = 0
           WHERE sync_disabled = 1
             AND sensitivity_level != 'sensitive_phi'
             AND timestamp >= ?""",
        (since.isoformat(),),
    )
    row = storage.execute_fetchone(
        """SELECT COUNT(*) AS n FROM audit_events
           WHERE sync_disabled = 0 AND synced_to_d1 = 0 AND timestamp >= ?""",
        (since.isoformat(),),
    )
    return row["n"] if row else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid-agent audit sync worker")
    parser.add_argument("--tenant", default="sam-personal")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--once", action="store_true", help="Run one sync cycle and exit")
    args = parser.parse_args()

    endpoint = os.environ.get("SYNC_ENDPOINT_URL")
    if not endpoint:
        log.error("SYNC_ENDPOINT_URL not set in environment")
        sys.exit(1)

    storage = SQLiteAuditStorage(args.db)
    sanitizer = SanitizationPipeline()
    d1_client = D1WorkerClient(endpoint_url=endpoint)

    if args.once:
        sync_once(storage, sanitizer, d1_client, args.batch)
    else:
        sync_loop(storage, sanitizer, d1_client, args.batch, args.interval)


if __name__ == "__main__":
    main()
