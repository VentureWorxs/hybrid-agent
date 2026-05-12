"""
CLI entry point for `hybrid-agent scorecard`.
Called from the root cli.py dispatcher.
"""
import argparse
import sys
from pathlib import Path

from audit.sqlite_storage import SQLiteAuditStorage
from audit.migrate import apply_migrations
from .generator import generate_scorecard
from .formatters.cli import render_cli
from .formatters.markdown import render_markdown
from .formatters.json import render_json

DEFAULT_DB = Path.home() / ".hybrid-agent" / "audit.db"


def build_parser(subparsers=None):
    if subparsers:
        p = subparsers.add_parser("scorecard", help="Generate KPI scorecard")
    else:
        p = argparse.ArgumentParser(description="Hybrid-agent KPI scorecard")

    p.add_argument("--tenant", required=True, help="Tenant ID")
    p.add_argument("--epoch", default="CURRENT", help="CURRENT, PREV, GENESIS, or sequence number")
    p.add_argument("--period", help="Alternative to --epoch: 24h, 7d, 30d, all")
    p.add_argument("--compare", dest="compare_to", help="Compare to epoch (CURRENT, PREV, or number)")
    p.add_argument("--output", choices=["cli", "md", "json"], default="cli")
    p.add_argument("--output-file", type=Path, help="Write output to file instead of stdout")
    p.add_argument("--include-shadow", action="store_true", help="Include shadow events in KPIs")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p


def run(args) -> int:
    apply_migrations(args.db)
    storage = SQLiteAuditStorage(args.db)

    try:
        data = generate_scorecard(
            storage=storage,
            tenant_id=args.tenant,
            epoch_selector=args.epoch,
            period=args.period,
            compare_to=args.compare_to,
            include_shadow=args.include_shadow,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.output == "json":
        text = render_json(data)
    elif args.output == "md":
        text = render_markdown(data)
    else:
        text = render_cli(data, verbose=args.verbose)

    if args.output_file:
        args.output_file.write_text(text, encoding="utf-8")
        print(f"Written to {args.output_file}")
    else:
        print(text)
    return 0


def main():
    p = build_parser()
    args = p.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
