"""One-time, safety-first per-server SQLite -> PostgreSQL migration.

Run with the bot stopped and current SQLite databases present in data/servers/.
DATABASE_BACKEND=postgresql and DATABASE_URL must be configured in
private-configs/credentials.env or the process environment. This tool refuses to
replace any non-empty target and imports every current v0.10.0 application table.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

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
CORE_TABLES = (
    "users",
    "tickets",
    "transactions",
    "transaction_audit_deliveries",
    "invite_events",
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


def locate_existing_servers(data_dir: Path) -> list[int]:
    found: set[int] = set()
    for directory_name, filename in (("servers", "blox_fruits_credit_system.sqlite3"), ("guilds", "guild.sqlite3")):
        base = data_dir / directory_name
        if not base.is_dir():
            continue
        for candidate in base.iterdir():
            if candidate.is_dir() and candidate.name.isdecimal() and (candidate / filename).is_file():
                found.add(int(candidate.name))
    return sorted(found)


def assert_target_is_fresh(database) -> None:
    conn = database.connection.raw
    for table in CORE_TABLES:
        count = conn.execute(f"SELECT COUNT(*) AS n FROM {quote(table)}").fetchone()["n"]
        if int(count):
            raise RuntimeError(
                f"Target schema server_{database.guildId} is not empty: {table} has {count} rows. "
                "Migration is refusing to overwrite it."
            )
    # Fresh target schemas are seeded with defaults. If somebody already changed
    # settings/services there, stop rather than quietly overwriting those changes.
    settings = {
        str(row["setting_key"]): str(row["setting_value"])
        for row in conn.execute("SELECT setting_key, setting_value FROM settings").fetchall()
    }
    expected_settings = {
        "default_join_credits": str(DEFAULT_JOIN_CREDITS),
        "max_helpers": "5",
        "invite_rewards_enabled": "false",
        "invite_reward_credits": "50",
        "invite_duration_minutes": "60",
        "dashboard_moderator_role_ids": "",
        "ticket_staff_role_baseline_id": "",
        "ticket_staff_role_ids_effective": "",
        "help_center_channel_id": "",
        "help_center_message_id": "",
        "dashboard_channel_id": "",
        "dashboard_message_id": "",
        "audit_log_channel_id": "",
    }
    if settings != expected_settings:
        raise RuntimeError(
            f"Target schema server_{database.guildId} contains customized or unexpected settings. "
            "Review it manually before migration."
        )
    services = conn.execute("SELECT service_key, name, price, active, sort_order FROM services ORDER BY sort_order, name").fetchall()
    actual_services = [(str(row["service_key"]), str(row["name"]), int(row["price"]), int(row["active"]), int(row["sort_order"])) for row in services]
    expected_services = [(str(key), str(name), max(0, int(price)), 1, i) for i, (key, name, price) in enumerate(DEFAULT_SERVICES)]
    if actual_services != expected_services:
        raise RuntimeError(
            f"Target schema server_{database.guildId} has a modified event catalog. "
            "Migration is refusing to overwrite it."
        )


def migrate_server(server_id: int, sqlite_path: Path, postgres_manager: DatabaseManager) -> None:
    print(f"\nServer {server_id}: reading {sqlite_path}")
    with sqlite3.connect(sqlite_path) as source:
        source.row_factory = sqlite3.Row
        source_tables = {str(row["name"]) for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        missing = set(TABLES) - source_tables
        if missing:
            raise RuntimeError(f"Source database is missing expected tables: {', '.join(sorted(missing))}")
        source_rows = {table: source.execute(f"SELECT * FROM {quote(table)}").fetchall() for table in TABLES}

    target = postgres_manager.ForServer(server_id)
    assert_target_is_fresh(target)
    raw = target.connection.raw
    schema = f"server_{server_id}"
    inserted_counts: dict[str, int] = {}
    raw.execute("BEGIN")
    try:
        # Replace only the seed defaults after confirming there is no live target data.
        for table in DELETE_ORDER:
            raw.execute(f"DELETE FROM {quote(table)}")
        for table in TABLES:
            rows = source_rows[table]
            if not rows:
                inserted_counts[table] = 0
                continue
            source_columns = [str(name) for name in rows[0].keys()]
            target_column_rows = raw.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (schema, table),
            ).fetchall()
            target_columns = {str(row["column_name"]) for row in target_column_rows}
            if set(source_columns) != target_columns:
                raise RuntimeError(
                    f"Column mismatch in server {server_id}, table {table}. "
                    f"Source={sorted(source_columns)} target={sorted(target_columns)}. No partial migration will be committed."
                )
            cols = ", ".join(quote(name) for name in source_columns)
            placeholders = ", ".join(["%s"] * len(source_columns))
            sql = f"INSERT INTO {quote(schema)}.{quote(table)} ({cols}) VALUES ({placeholders})"
            for row in rows:
                raw.execute(sql, tuple(row[name] for name in source_columns))
            inserted_counts[table] = len(rows)

        # Explicitly inserted primary-key values must advance their serial sequences.
        for table, column in SERIALS:
            seq_row = raw.execute("SELECT pg_get_serial_sequence(%s, %s) AS seq", (f"{schema}.{table}", column)).fetchone()
            sequence = seq_row["seq"] if seq_row else None
            if not sequence:
                continue
            max_row = raw.execute(f"SELECT MAX({quote(column)}) AS max_id FROM {quote(schema)}.{quote(table)}").fetchone()
            maximum = max_row["max_id"] if max_row else None
            if maximum is None:
                raw.execute("SELECT setval(%s::regclass, 1, false)", (sequence,))
            else:
                raw.execute("SELECT setval(%s::regclass, %s, true)", (sequence, int(maximum)))
        raw.commit()
    except Exception:
        raw.rollback()
        raise

    for table, expected in inserted_counts.items():
        actual = int(raw.execute(f"SELECT COUNT(*) AS n FROM {quote(schema)}.{quote(table)}").fetchone()["n"])
        if actual != expected:
            raise RuntimeError(f"Post-migration row-count mismatch in {schema}.{table}: expected {expected}, found {actual}")
    print("Imported and verified row counts:")
    for table, count in inserted_counts.items():
        print(f"  {table}: {count}")


def main() -> int:
    settings = LoadRuntimeSettings()
    if settings.databaseBackend != "postgresql" or not settings.databaseUrl:
        print("Set DATABASE_BACKEND=postgresql and DATABASE_URL in private-configs/credentials.env before migration.", file=sys.stderr)
        return 2
    data_dir = ROOT / "data"
    server_ids = locate_existing_servers(data_dir)
    if not server_ids:
        print("No SQLite server databases found under data/servers/ or data/guilds/. Get the actual database files before migrating.", file=sys.stderr)
        return 2
    print("IMPORTANT: stop the running bot first. This utility refuses to overwrite non-empty PostgreSQL schemas.")
    print(f"Found {len(server_ids)} local SQLite server database(s): {', '.join(map(str, server_ids))}")
    answer = input("Type MIGRATE only after confirming you have a recoverable copy of every source database: ").strip()
    if answer != "MIGRATE":
        print("Cancelled; no remote rows changed.")
        return 1

    # Run current schema migrations on each SQLite source first; this preserves legacy
    # database upgrade behavior and makes sure source table shapes are current.
    sqlite_manager = DatabaseManager(data_dir, DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES, backend="sqlite")
    try:
        source_paths = {}
        for server_id in server_ids:
            source_paths[server_id] = sqlite_manager.GetServerDatabasePath(server_id)
            sqlite_manager.ForServer(server_id)
    finally:
        sqlite_manager.CloseAll()

    postgres_manager = DatabaseManager(data_dir, DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES, backend="postgresql", databaseUrl=settings.databaseUrl)
    try:
        for server_id in server_ids:
            migrate_server(server_id, source_paths[server_id], postgres_manager)
    finally:
        postgres_manager.CloseAll()
    print("\nMigration finished. Compare settings, balances, tickets, and transaction totals in the SQL provider dashboard before switching production hosting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
