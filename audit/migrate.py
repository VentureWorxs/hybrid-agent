"""
Database migration runner.
Usage: python -m audit.migrate --db ~/.hybrid-agent/audit.db
"""
import argparse
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "schema" / "migrations"


def apply_migrations(db_path: Path, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT)"
    )

    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] or 0

    sql_files = sorted(migrations_dir.glob("*.sql"))
    applied = 0
    for sql_file in sql_files:
        version = int(sql_file.stem.split("_")[0])
        if version <= current:
            continue
        try:
            conn.executescript(sql_file.read_text(encoding="utf-8"))
            # executescript auto-commits; also record the version if not already inserted
            exists = conn.execute(
                "SELECT 1 FROM schema_version WHERE version = ?", (version,)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO schema_version VALUES (?, datetime('now'), ?)",
                    (version, sql_file.stem),
                )
                conn.commit()
            log.info("Applied migration %s", sql_file.name)
            applied += 1
        except Exception as e:
            log.error("Migration %s failed: %s", sql_file.name, e)
            raise
    conn.close()
    if applied == 0:
        log.info("No new migrations (current version: %d)", current)
    else:
        log.info("Applied %d migration(s)", applied)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Apply database migrations")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path.home() / ".hybrid-agent" / "audit.db",
    )
    args = parser.parse_args()
    apply_migrations(args.db)


if __name__ == "__main__":
    main()
