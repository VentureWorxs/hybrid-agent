"""
Root CLI entry point for hybrid-agent.

Usage:
  python cli.py scorecard --tenant sam-personal
  python cli.py config show --tenant sam-personal
  python cli.py config set --scope global --field operating_mode --value baseline
  python cli.py audit backfill --since 2026-01-01T00:00:00Z
  python cli.py audit verify --machine-id <uuid>
"""
import argparse
import sys
from pathlib import Path

DEFAULT_DB = Path.home() / ".hybrid-agent" / "audit.db"


def _scorecard_cmd(args) -> int:
    from scorecard.cli import run
    return run(args)


def _config_show(args) -> int:
    from modes.config import load_global_config
    from audit.sqlite_storage import SQLiteAuditStorage
    from audit.migrate import apply_migrations
    import json

    cfg = load_global_config()
    print("\n[global config]")
    ha = cfg.get("hybrid_agent", {})
    print(f"  operating_mode:     {ha.get('operating_mode')}")
    print(f"  audit_sync_enabled: {ha.get('audit_sync_enabled')}")
    print(f"  agent_version:      {ha.get('agent_version')}")

    if args.tenant:
        apply_migrations(args.db)
        storage = SQLiteAuditStorage(args.db)
        tenant = storage.get_tenant(args.tenant)
        if tenant:
            print(f"\n[tenant: {args.tenant}]")
            meta = tenant.get("metadata", {})
            for k, v in meta.items():
                print(f"  {k}: {v}")
        else:
            print(f"\n[tenant: {args.tenant}] — not found in DB")
    return 0


def _config_set(args) -> int:
    from audit.sqlite_storage import SQLiteAuditStorage
    from audit.audit_logger import AuditLogger
    from audit.migrate import apply_migrations
    from audit.bootstrap import get_or_create_machine_id
    from modes.controller import ModeController
    import uuid

    apply_migrations(args.db)
    storage = SQLiteAuditStorage(args.db)
    machine_id = get_or_create_machine_id()
    session_id = str(uuid.uuid4())
    agent_version = "1.1.0"
    audit = AuditLogger(storage, args.tenant or "sam-personal", machine_id, session_id, agent_version)
    controller = ModeController(storage, audit)

    if args.field == "operating_mode":
        controller.set_mode(args.value, scope=args.scope, tenant_id=args.tenant)
        print(f"operating_mode → {args.value} (scope={args.scope})")
    elif args.field == "audit_sync_enabled":
        val = args.value.lower() in ("true", "1", "yes")
        controller.set_sync_enabled(val, scope=args.scope, tenant_id=args.tenant)
        print(f"audit_sync_enabled → {val} (scope={args.scope})")
    else:
        print(f"Unknown field: {args.field}", file=sys.stderr)
        return 1
    return 0


def _audit_backfill(args) -> int:
    from audit.sqlite_storage import SQLiteAuditStorage
    from audit.sync_worker import backfill_sync
    from audit.migrate import apply_migrations
    from datetime import datetime, timezone

    apply_migrations(args.db)
    storage = SQLiteAuditStorage(args.db)
    since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))

    count = backfill_sync(storage, since, dry_run=args.dry_run)
    if args.dry_run:
        print(f"Dry run: {count} events would be marked for sync (since {args.since})")
    else:
        print(f"Marked {count} events for sync (since {args.since})")
    return 0


def _audit_verify(args) -> int:
    from audit.sqlite_storage import SQLiteAuditStorage
    from audit.migrate import apply_migrations

    apply_migrations(args.db)
    storage = SQLiteAuditStorage(args.db)
    valid, error = storage.verify_chain(args.machine_id)
    if valid:
        print(f"✓ Hash chain valid for machine {args.machine_id}")
    else:
        print(f"✗ Hash chain INVALID: {error}", file=sys.stderr)
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="hybrid-agent", description="Hybrid Claude/Ollama agent CLI")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    # scorecard sub-command
    from scorecard.cli import build_parser as _sc_build
    _sc_build(sub)

    # config sub-command
    cfg_p = sub.add_parser("config", help="View or change configuration")
    cfg_sub = cfg_p.add_subparsers(dest="config_action", required=True)

    show_p = cfg_sub.add_parser("show")
    show_p.add_argument("--tenant")

    set_p = cfg_sub.add_parser("set")
    set_p.add_argument("--scope", choices=["global", "tenant", "session"], required=True)
    set_p.add_argument("--field", required=True)
    set_p.add_argument("--value", required=True)
    set_p.add_argument("--tenant")

    # audit sub-command
    audit_p = sub.add_parser("audit", help="Audit log utilities")
    audit_sub = audit_p.add_subparsers(dest="audit_action", required=True)

    bf_p = audit_sub.add_parser("backfill")
    bf_p.add_argument("--since", required=True, help="ISO8601 timestamp")
    bf_p.add_argument("--dry-run", action="store_true")
    bf_p.add_argument("--tenant")

    ver_p = audit_sub.add_parser("verify")
    ver_p.add_argument("--machine-id", required=True)

    args = parser.parse_args()

    if args.command == "scorecard":
        return _scorecard_cmd(args)
    elif args.command == "config":
        if args.config_action == "show":
            return _config_show(args)
        elif args.config_action == "set":
            return _config_set(args)
    elif args.command == "audit":
        if args.audit_action == "backfill":
            return _audit_backfill(args)
        elif args.audit_action == "verify":
            return _audit_verify(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
