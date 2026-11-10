"""Restore one encrypted per-server PostgreSQL backup ZIP into a PostgreSQL schema.

Dry-run is the default. Actual replacement requires --apply and typing the exact
Discord server ID. Stop the bot before applying a restore.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

import pyzipper

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.database import DatabaseManager  # noqa: E402
from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES, LoadRuntimeSettings  # noqa: E402

TABLES = (
    "users",
    "services",
    "settings",
    "invite_events",
    "tickets",
    "transactions",
    "transaction_audit_deliveries",
    "invite_rewards",
    "credit_debts",
    "invite_attributions",
    "scam_reports",
)
DELETE_ORDER = (
    "transaction_audit_deliveries",
    "invite_rewards",
    "transactions",
    "tickets",
    "invite_events",
    "invite_attributions",
    "credit_debts",
    "scam_reports",
    "users",
    "services",
    "settings",
)
SERIALS = (("tickets", "ticket_id"), ("transactions", "id"), ("invite_events", "event_id"), ("scam_reports", "report_id"))


def quote(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unexpected SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_zip", type=Path)
    parser.add_argument("--server-id", type=int, required=True, help="Expected Discord server ID inside the archive")
    parser.add_argument("--apply", action="store_true", help="Replace this server schema after a confirmation prompt")
    args = parser.parse_args()

    settings = LoadRuntimeSettings()
    if settings.databaseBackend != "postgresql" or not settings.databaseUrl:
        parser.error("Set DATABASE_BACKEND=postgresql and DATABASE_URL in private-configs/credentials.env first")
    if not args.backup_zip.is_file():
        parser.error(f"Backup ZIP not found: {args.backup_zip}")
    password = getpass.getpass("Backup AES-256 password: ")
    try:
        with pyzipper.AESZipFile(args.backup_zip, "r") as archive:
            archive.pwd = password.encode("utf-8")
            names = set(archive.namelist())
            if "manifest.json" not in names or "database/database-export.json" not in names:
                raise RuntimeError("This is not a PostgreSQL per-server backup ZIP recognized by this tool.")
            manifest = json.loads(archive.read("manifest.json"))
            payload = json.loads(archive.read("database/database-export.json"))
    except Exception as exc:
        print(f"Could not read or decrypt the backup: {exc}", file=sys.stderr)
        return 2

    if manifest.get("format") != "bloxfruits-helper-credit-bot-per-server-backup-v1":
        print("Unrecognized backup format; nothing changed.", file=sys.stderr)
        return 2
    if int(manifest.get("server_id", -1)) != args.server_id or payload.get("schema") != f"server_{args.server_id}":
        print("Server ID does not match the backup manifest/schema; refusing to restore.", file=sys.stderr)
        return 2
    tables = payload.get("tables")
    columns = payload.get("columns")
    if not isinstance(tables, dict) or not isinstance(columns, dict) or set(tables) != set(TABLES):
        print("Backup table set doesn't match the current bot schema; nothing changed.", file=sys.stderr)
        return 2
    for table in TABLES:
        if not isinstance(tables[table], list) or not isinstance(columns.get(table), list):
            print(f"Invalid table payload: {table}", file=sys.stderr)
            return 2
        expected_columns = set(columns[table])
        if any(not isinstance(row, dict) or set(row) != expected_columns for row in tables[table]):
            print(f"Invalid row shape in table: {table}", file=sys.stderr)
            return 2

    print(f"Backup timestamp: {manifest.get('created_at_utc', 'unknown')}")
    print(f"Target schema: server_{args.server_id}")
    for table in TABLES:
        print(f"  {table}: {len(tables[table])} rows in backup")
    if not args.apply:
        print("DRY RUN ONLY: no rows changed. Add --apply to restore after stopping the bot.")
        return 0

    confirmation = input(f"This replaces ALL application tables in server_{args.server_id}. Type the exact server ID to continue: ").strip()
    if confirmation != str(args.server_id):
        print("Cancelled; no rows changed.")
        return 1

    manager = DatabaseManager(ROOT / "data", DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES, backend="postgresql", databaseUrl=settings.databaseUrl)
    try:
        database = manager.ForServer(args.server_id)
        raw = database.connection.raw
        schema = f"server_{args.server_id}"
        inserted: dict[str, int] = {}
        raw.execute("BEGIN")
        try:
            for table in DELETE_ORDER:
                raw.execute(f"DELETE FROM {quote(table)}")
            for table in TABLES:
                row_columns = [str(name) for name in columns[table]]
                db_columns = raw.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
                    (schema, table),
                ).fetchall()
                if set(row_columns) != {str(row["column_name"]) for row in db_columns}:
                    raise RuntimeError(f"Target columns differ for {schema}.{table}; schema upgrade is required before restore.")
                if not tables[table]:
                    inserted[table] = 0
                    continue
                sql = f"INSERT INTO {quote(table)} ({', '.join(quote(name) for name in row_columns)}) VALUES ({', '.join(['%s'] * len(row_columns))})"
                for row in tables[table]:
                    raw.execute(sql, tuple(row[name] for name in row_columns))
                inserted[table] = len(tables[table])
            for table, column in SERIALS:
                seqRow = raw.execute("SELECT pg_get_serial_sequence(%s, %s) AS seq", (f"{schema}.{table}", column)).fetchone()
                sequence = seqRow["seq"] if seqRow else None
                if not sequence:
                    continue
                maximum = raw.execute(f"SELECT MAX({quote(column)}) AS max_id FROM {quote(table)}").fetchone()["max_id"]
                if maximum is None:
                    raw.execute("SELECT setval(%s::regclass, 1, false)", (sequence,))
                else:
                    raw.execute("SELECT setval(%s::regclass, %s, true)", (sequence, int(maximum)))
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        for table, expected in inserted.items():
            actual = int(raw.execute(f"SELECT COUNT(*) AS n FROM {quote(table)}").fetchone()["n"])
            if actual != expected:
                raise RuntimeError(f"Post-restore count mismatch for {table}: expected {expected}, found {actual}")
        print("Restore completed and row counts verified. Start the bot only after checking balances and ticket history.")
        for table, count in inserted.items():
            print(f"  {table}: {count}")
        return 0
    except Exception as exc:
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 2
    finally:
        manager.CloseAll()


if __name__ == "__main__":
    raise SystemExit(main())
