"""SQLite storage belonging to one Discord server (guild)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Iterable

from ..ticket_messages import DEFAULT_TICKET_WELCOME_MESSAGE


class _PostgresDialectConnection:
    """Translate the small SQLite SQL dialect differences used by this project."""

    def __init__(self, connection):
        self.raw = connection

    def execute(self, sql: str, params=()):
        query = str(sql)
        stripped = query.lstrip().upper()
        if stripped.startswith("PRAGMA"):
            return _NoopCursor()
        nullableExpiredExpression = "CASE WHEN ? IS NULL OR datetime(?) <= datetime('now', '-15 minutes')"
        if nullableExpiredExpression in query:
            # Cast both placeholders; PostgreSQL cannot infer the type of a
            # bare `%s IS NULL` parameter when the caller passes None.
            query = query.replace(
                nullableExpiredExpression,
                "CASE WHEN (%s)::timestamptz IS NULL OR (%s)::timestamptz <= (now() - interval '15 minutes')",
            )
        elif "datetime(?) <= datetime('now', '-15 minutes')" in query:
            query = query.replace(
                "datetime(?) <= datetime('now', '-15 minutes')",
                "(%s)::timestamptz <= (now() - interval '15 minutes')",
            )
        if "datetime(resolution_requested_at) <= datetime('now', ?)" in query:
            query = query.replace(
                "datetime(resolution_requested_at) <= datetime('now', ?)",
                "resolution_requested_at::timestamptz <= (now() + (%s)::interval)",
            )
        ignoredInsert = "INSERT OR IGNORE INTO" in query.upper()
        if ignoredInsert:
            query = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", query, flags=re.IGNORECASE)
            query = query.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        # All parameterized application queries use qmark placeholders and no SQL
        # string literal containing a question mark. Convert them for psycopg.
        query = query.replace("?", "%s")
        if stripped.startswith("BEGIN IMMEDIATE"):
            query = re.sub(r"^\s*BEGIN\s+IMMEDIATE", "BEGIN", query, flags=re.IGNORECASE)
        if stripped.startswith("CREATE TABLE"):
            query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            query = re.sub(r"\bINTEGER\b", "BIGINT", query)
        elif stripped.startswith("ALTER TABLE"):
            query = re.sub(r"\bINTEGER\b", "BIGINT", query)
        query = re.sub(r"\bCURRENT_TIMESTAMP\b", "CURRENT_TIMESTAMP::text", query, flags=re.IGNORECASE)
        return self.raw.execute(query, params)

    def commit(self):
        return self.raw.commit()

    def rollback(self):
        return self.raw.rollback()

    def close(self):
        return self.raw.close()

    def __enter__(self):
        # The pooled/lifecycle connection belongs to DatabaseManager and must
        # remain open after schema initialization. psycopg.Connection's own
        # context manager closes the connection on exit, unlike sqlite3's.
        # Open a transaction for the SQLite-style `with self.connection:` scopes
        # and commit/roll back without delegating connection ownership to psycopg.
        self.raw.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        return False


class _NoopCursor:
    rowcount = 0
    def fetchone(self):
        return None
    def fetchall(self):
        return []


class GuildDatabase:
    """One isolated SQLite database, intended for exactly one Discord guild."""

    def __init__(
        self,
        path: str | Path,
        guildId: int,
        defaultJoinCredits: int = 100,
        defaultServices: Iterable[tuple[str, str, int]] = (),
        *,
        backend: str = "sqlite",
        connection=None,
    ) -> None:
        self.databasePath = Path(path)
        self.guildId = int(guildId)
        self.backend = str(backend).lower()
        self.databaseLock = RLock()
        if self.backend == "sqlite":
            self.databasePath.parent.mkdir(parents=True, exist_ok=True)
            self.connection = connection or sqlite3.connect(
                str(self.databasePath), timeout=15, check_same_thread=False
            )
            self.connection.row_factory = sqlite3.Row
            with self.databaseLock:
                self.connection.execute("PRAGMA foreign_keys = ON")
                self.connection.execute("PRAGMA busy_timeout = 15000")
                self.connection.execute("PRAGMA journal_mode = WAL")
        elif self.backend == "postgresql":
            if connection is None:
                raise ValueError("A PostgreSQL connection is required.")
            self.connection = _PostgresDialectConnection(connection)
        else:
            raise ValueError("backend must be sqlite or postgresql")
        self.CreateTables()
        self.SeedDefaults(defaultJoinCredits, defaultServices)

    def CreateTables(self) -> None:
        schema = (
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                credits INTEGER NOT NULL DEFAULT 100 CHECK (credits >= 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_number INTEGER,
                ticket_sequence INTEGER,
                channel_ticket_number INTEGER,
                channel_id INTEGER UNIQUE,
                guild_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                event_key TEXT NOT NULL,
                helper_ids TEXT NOT NULL,
                active_helper_ids TEXT NOT NULL DEFAULT '',
                resolution_type TEXT NOT NULL DEFAULT '',
                resolution_requested_by INTEGER,
                resolution_confirmations TEXT NOT NULL DEFAULT '',
                resolution_requested_at TEXT,
                resolution_message_id INTEGER,
                resolution_locked INTEGER NOT NULL DEFAULT 0 CHECK (resolution_locked IN (0, 1)),
                replacement_requested INTEGER NOT NULL DEFAULT 0 CHECK (replacement_requested IN (0, 1)),
                replacement_candidate_ids TEXT NOT NULL DEFAULT '',
                replacement_request_message_id INTEGER,
                replacement_button_message_id INTEGER,
                required_credits INTEGER NOT NULL CHECK (required_credits >= 0),
                reserved_credits INTEGER NOT NULL DEFAULT 0 CHECK (reserved_credits >= 0),
                price_per_helper INTEGER CHECK (price_per_helper IS NULL OR price_per_helper >= 0),
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                transcript_channel_id INTEGER,
                transcript_message_id INTEGER,
                transcript_saved INTEGER NOT NULL DEFAULT 0 CHECK (transcript_saved IN (0, 1))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                from_user INTEGER,
                to_user INTEGER,
                amount INTEGER NOT NULL CHECK (amount >= 0),
                type TEXT NOT NULL,
                actor_user_id INTEGER,
                note TEXT,
                idempotency_key TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS transaction_audit_deliveries (
                transaction_id INTEGER PRIMARY KEY,
                delivered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS services (
                service_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price INTEGER NOT NULL CHECK (price >= 0),
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS invite_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reward_credits INTEGER NOT NULL CHECK (reward_credits >= 0),
                duration_minutes INTEGER NOT NULL CHECK (duration_minutes BETWEEN 1 AND 10080),
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended', 'expired')),
                started_by INTEGER NOT NULL,
                ended_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS invite_rewards (
                event_id INTEGER NOT NULL,
                invited_user_id INTEGER NOT NULL,
                inviter_user_id INTEGER NOT NULL,
                invite_code TEXT NOT NULL DEFAULT '',
                reward_credits INTEGER NOT NULL CHECK (reward_credits >= 0),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_id, invited_user_id),
                FOREIGN KEY (event_id) REFERENCES invite_events(event_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS credit_debts (
                user_id INTEGER PRIMARY KEY,
                amount INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS invite_attributions (
                invited_user_id INTEGER PRIMARY KEY,
                inviter_user_id INTEGER NOT NULL,
                invite_code TEXT NOT NULL DEFAULT '',
                penalty_applied INTEGER NOT NULL DEFAULT 0 CHECK (penalty_applied IN (0, 1)),
                join_cycle INTEGER NOT NULL DEFAULT 1,
                joined_at TEXT NOT NULL DEFAULT '',
                invite_event_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS scam_reports (
                report_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_user_id INTEGER NOT NULL,
                reported_user_id INTEGER NOT NULL,
                report_type TEXT NOT NULL DEFAULT 'scam',
                details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_by INTEGER,
                review_note TEXT
            )
            """,
        )
        with self.databaseLock, self.connection:
            for statement in schema:
                if self.backend == "postgresql" and statement.lstrip().upper().startswith("CREATE TABLE"):
                    statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
                    statement = re.sub(r"\bINTEGER\b", "BIGINT", statement)
                self.connection.execute(statement)
            # Preserve legacy scam reports while adding a category for generalized reports.
            if self.backend == "sqlite":
                reportColumnRows = self.connection.execute("PRAGMA table_info(scam_reports)").fetchall()
                reportColumns = {str(row["name"]) for row in reportColumnRows}
            else:
                reportColumnRows = self.connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
                    ("scam_reports",),
                ).fetchall()
                reportColumns = {str(row["column_name"]) for row in reportColumnRows}
            if "report_type" not in reportColumns:
                self.connection.execute(
                    "ALTER TABLE scam_reports ADD COLUMN report_type TEXT NOT NULL DEFAULT 'scam'"
                )

            # Track attributed invite join cycles so optional repeat leave penalties
            # can re-arm once per distinct Discord join timestamp.
            if self.backend == "sqlite":
                attributionColumnRows = self.connection.execute("PRAGMA table_info(invite_attributions)").fetchall()
                attributionColumns = {str(row["name"]) for row in attributionColumnRows}
            else:
                attributionColumnRows = self.connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
                    ("invite_attributions",),
                ).fetchall()
                attributionColumns = {str(row["column_name"]) for row in attributionColumnRows}
            attributionMigrations = {
                "join_cycle": "ALTER TABLE invite_attributions ADD COLUMN join_cycle INTEGER NOT NULL DEFAULT 1",
                "joined_at": "ALTER TABLE invite_attributions ADD COLUMN joined_at TEXT NOT NULL DEFAULT ''",
                "invite_event_id": "ALTER TABLE invite_attributions ADD COLUMN invite_event_id INTEGER",
            }
            for columnName, migrationSql in attributionMigrations.items():
                if columnName not in attributionColumns:
                    self.connection.execute(migrationSql)

            # Add the numbered-ticket column to databases created before this feature.
            if self.backend == "sqlite":
                ticketColumnRows = self.connection.execute("PRAGMA table_info(tickets)").fetchall()
                ticketColumns = {str(row["name"]) for row in ticketColumnRows}
            else:
                ticketColumnRows = self.connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
                    ("tickets",),
                ).fetchall()
                ticketColumns = {str(row["column_name"]) for row in ticketColumnRows}
            if "ticket_number" not in ticketColumns:
                self.connection.execute("ALTER TABLE tickets ADD COLUMN ticket_number INTEGER")

            ticketMigrations = {
                # NULL marks historical tickets from v0.7.0 and earlier. Their
                # published transcript labels remain unchanged; new tickets use a
                # global sequence from v0.7.1 onward.
                "ticket_sequence": "ALTER TABLE tickets ADD COLUMN ticket_sequence INTEGER",
                "channel_ticket_number": "ALTER TABLE tickets ADD COLUMN channel_ticket_number INTEGER",
                "active_helper_ids": "ALTER TABLE tickets ADD COLUMN active_helper_ids TEXT NOT NULL DEFAULT ''",
                "resolution_type": "ALTER TABLE tickets ADD COLUMN resolution_type TEXT NOT NULL DEFAULT ''",
                "resolution_requested_by": "ALTER TABLE tickets ADD COLUMN resolution_requested_by INTEGER",
                "resolution_confirmations": "ALTER TABLE tickets ADD COLUMN resolution_confirmations TEXT NOT NULL DEFAULT ''",
                "resolution_requested_at": "ALTER TABLE tickets ADD COLUMN resolution_requested_at TEXT",
                "resolution_message_id": "ALTER TABLE tickets ADD COLUMN resolution_message_id INTEGER",
                "resolution_locked": "ALTER TABLE tickets ADD COLUMN resolution_locked INTEGER NOT NULL DEFAULT 0",
                "replacement_requested": "ALTER TABLE tickets ADD COLUMN replacement_requested INTEGER NOT NULL DEFAULT 0",
                "replacement_candidate_ids": "ALTER TABLE tickets ADD COLUMN replacement_candidate_ids TEXT NOT NULL DEFAULT ''",
                "replacement_request_message_id": "ALTER TABLE tickets ADD COLUMN replacement_request_message_id INTEGER",
                "replacement_button_message_id": "ALTER TABLE tickets ADD COLUMN replacement_button_message_id INTEGER",
                # NULL preserves the legacy total-price / equal-split payout policy for old tickets.
                "price_per_helper": "ALTER TABLE tickets ADD COLUMN price_per_helper INTEGER",
                "transcript_channel_id": "ALTER TABLE tickets ADD COLUMN transcript_channel_id INTEGER",
                "transcript_message_id": "ALTER TABLE tickets ADD COLUMN transcript_message_id INTEGER",
                "transcript_saved": "ALTER TABLE tickets ADD COLUMN transcript_saved INTEGER NOT NULL DEFAULT 0",
            }
            for columnName, migrationSql in ticketMigrations.items():
                if columnName not in ticketColumns:
                    self.connection.execute(migrationSql)

            # Preserve evidence that a transcript was successfully published even
            # after its Discord message falls outside the 100-message retention
            # window and its message pointer is cleared.
            self.connection.execute(
                "UPDATE tickets SET transcript_saved = 1 "
                "WHERE transcript_message_id IS NOT NULL AND transcript_saved = 0"
            )

            # Seed a persistent, never-wrapping ticket counter. Use the largest
            # historical identifier/number so old cycling labels can coexist with
            # new globally unique suffixes while their already-posted transcripts
            # retain their original labels.
            highWaterRow = self.connection.execute(
                "SELECT COUNT(*) AS row_count, COALESCE(MAX(ticket_id), 0) AS max_ticket_id, "
                "COALESCE(MAX(ticket_number), 0) AS max_ticket_number, "
                "COALESCE(MAX(ticket_sequence), 0) AS max_ticket_sequence FROM tickets"
            ).fetchone()
            highWater = max(
                int(highWaterRow["row_count"] or 0),
                int(highWaterRow["max_ticket_id"] or 0),
                int(highWaterRow["max_ticket_number"] or 0),
                int(highWaterRow["max_ticket_sequence"] or 0),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES ('next_ticket_sequence', ?)",
                (str(highWater + 1),),
            )
            currentSequenceRow = self.connection.execute(
                "SELECT setting_value FROM settings WHERE setting_key = 'next_ticket_sequence'"
            ).fetchone()
            try:
                currentSequence = int(currentSequenceRow["setting_value"])
            except (TypeError, ValueError, KeyError):
                currentSequence = highWater + 1
            if currentSequence <= highWater or currentSequence < 1:
                self.connection.execute(
                    "UPDATE settings SET setting_value = ?, updated_at = CURRENT_TIMESTAMP WHERE setting_key = 'next_ticket_sequence'",
                    (str(highWater + 1),),
                )

            # Channel numbers are reusable after the server has no open tickets.
            # Seed above historical numbers on upgrade so old active channel labels
            # cannot collide with new labels during the transition. The allocator
            # resets to 1 once it observes that no ticket is open.
            self.connection.execute(
                "INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES ('next_ticket_channel_number', ?)",
                (str(highWater + 1),),
            )

            # For legacy pending proposals, preserve the recorded proposer as the first approval.
            self.connection.execute(
                "UPDATE tickets SET resolution_confirmations = CAST(resolution_requested_by AS TEXT) "
                "WHERE resolution_type IN ('complete', 'cancel') "
                "AND resolution_requested_by IS NOT NULL AND resolution_confirmations = ''"
            )

            # Old versions marked replacement_requested before storing selected candidates.
            # Clear these stale requests during migration so the new selection/approval flow
            # never mistakes them for a complete requester-submitted proposal.
            self.connection.execute(
                "UPDATE tickets SET replacement_requested = 0, replacement_candidate_ids = '', replacement_request_message_id = NULL "
                "WHERE replacement_requested = 1 AND replacement_candidate_ids = ''"
            )

            # Existing tickets keep their original helper roster as their active roster.
            self.connection.execute(
                "UPDATE tickets SET active_helper_ids = helper_ids "
                "WHERE active_helper_ids = '' AND status = 'open'"
            )

            # Migrate existing transaction tables safely to include adjustment auditing
            # and interaction-level idempotency. Existing rows receive NULL defaults.
            if self.backend == "sqlite":
                transactionColumnRows = self.connection.execute("PRAGMA table_info(transactions)").fetchall()
                transactionColumns = {str(row["name"]) for row in transactionColumnRows}
            else:
                transactionColumnRows = self.connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
                    ("transactions",),
                ).fetchall()
                transactionColumns = {str(row["column_name"]) for row in transactionColumnRows}
            transactionMigrations = {
                "actor_user_id": "ALTER TABLE transactions ADD COLUMN actor_user_id INTEGER",
                "note": "ALTER TABLE transactions ADD COLUMN note TEXT",
                "idempotency_key": "ALTER TABLE transactions ADD COLUMN idempotency_key TEXT",
            }
            for columnName, migrationSql in transactionMigrations.items():
                if columnName not in transactionColumns:
                    self.connection.execute(migrationSql)

            indexes = (
                "CREATE INDEX IF NOT EXISTS idx_tickets_creator_status "
                "ON tickets(creator_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_ticket ON transactions(ticket_id)",
                "CREATE INDEX IF NOT EXISTS idx_tickets_status_number ON tickets(status, ticket_number)",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_tickets_sequence "
                "ON tickets(ticket_sequence) WHERE ticket_sequence IS NOT NULL",
                # Legacy wrapped numbers may repeat among closed records. New v0.7.1
                # ticket_number values are global, never-wrapping sequence numbers.
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_tickets_open_number "
                "ON tickets(ticket_number) WHERE status = 'open' AND ticket_number IS NOT NULL",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_tickets_open_channel_number "
                "ON tickets(channel_ticket_number) WHERE status = 'open' AND channel_ticket_number IS NOT NULL",
                # Defensive database-level guards in addition to ticket status checks.
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_ticket_reservation "
                "ON transactions(ticket_id) WHERE ticket_id IS NOT NULL AND type = 'ticket_reservation'",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_ticket_refund "
                "ON transactions(ticket_id) WHERE ticket_id IS NOT NULL AND type = 'refund'",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_ticket_reward "
                "ON transactions(ticket_id, to_user) WHERE ticket_id IS NOT NULL AND type = 'ticket_reward'",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_starting_balance "
                "ON transactions(to_user) WHERE ticket_id IS NULL AND type = 'starting_balance' AND to_user IS NOT NULL",
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_transactions_idempotency_key "
                "ON transactions(idempotency_key) WHERE idempotency_key IS NOT NULL",
            )
            for indexSql in indexes:
                self.connection.execute(indexSql)

    def SeedDefaults(
        self,
        defaultJoinCredits: int,
        defaultServices: Iterable[tuple[str, str, int]],
    ) -> None:
        joinCredits = max(0, int(defaultJoinCredits))
        with self.databaseLock, self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO settings(setting_key, setting_value) "
                "VALUES('default_join_credits', ?)",
                (str(joinCredits),),
            )
            # New configurable values are seeded per guild. INSERT OR IGNORE keeps
            # existing server-specific settings unchanged across upgrades.
            settingDefaults = {
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
                "ticket_welcome_message": DEFAULT_TICKET_WELCOME_MESSAGE,
                "invite_leave_penalty_repeat_on_rejoin": "false",
            }
            for settingKey, settingValue in settingDefaults.items():
                self.connection.execute(
                    "INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES (?, ?)",
                    (settingKey, settingValue),
                )
            for index, (key, name, price) in enumerate(defaultServices):
                self.connection.execute(
                    """INSERT OR IGNORE INTO services
                       (service_key, name, price, active, sort_order)
                       VALUES (?, ?, ?, 1, ?)""",
                    (str(key), str(name), max(0, int(price)), index),
                )

    def Execute(self, sql: str, params: tuple = (), *, fetchOne=False, fetchAll=False):
        with self.databaseLock:
            cursor = self.connection.execute(sql, params)
            if fetchOne:
                return cursor.fetchone()
            if fetchAll:
                return cursor.fetchall()
            self.connection.commit()
            return cursor

    # ----- Per-guild settings and service catalog -----

    def GetSetting(self, key: str, default: str | None = None) -> str | None:
        row = self.Execute(
            "SELECT setting_value FROM settings WHERE setting_key = ?",
            (key,), fetchOne=True,
        )
        return row["setting_value"] if row else default

    def SetSetting(self, key: str, value: str | int | bool) -> None:
        self.Execute(
            """INSERT INTO settings(setting_key, setting_value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(setting_key) DO UPDATE SET
                 setting_value = excluded.setting_value,
                 updated_at = CURRENT_TIMESTAMP""",
            (str(key), str(value)),
        )

    def GetDefaultJoinCredits(self) -> int:
        try:
            value = self.GetSetting("default_join_credits", "100")
            return max(0, int(value if value is not None else "100"))
        except (TypeError, ValueError):
            return 100

    def SetDefaultJoinCredits(self, credits: int) -> None:
        if isinstance(credits, bool):
            raise ValueError("Starting credits must be a non-negative integer")
        try:
            normalizedCredits = int(credits)
        except (TypeError, ValueError) as error:
            raise ValueError("Starting credits must be a non-negative integer") from error
        if normalizedCredits < 0:
            raise ValueError("Starting credits must be a non-negative integer")
        self.SetSetting("default_join_credits", normalizedCredits)

    def GetMaxHelpers(self) -> int:
        try:
            value = int(self.GetSetting("max_helpers", "5") or "5")
            return min(25, max(1, value))
        except (TypeError, ValueError):
            return 5

    def SetMaxHelpers(self, maxHelpers: int) -> None:
        if isinstance(maxHelpers, bool):
            raise ValueError("Maximum helpers must be an integer from 1 to 25")
        try:
            normalizedCount = int(maxHelpers)
        except (TypeError, ValueError) as error:
            raise ValueError("Maximum helpers must be an integer from 1 to 25") from error
        if not 1 <= normalizedCount <= 25:
            raise ValueError("Maximum helpers must be an integer from 1 to 25")
        self.SetSetting("max_helpers", normalizedCount)

    def ListServices(self, activeOnly: bool = True) -> list[sqlite3.Row]:
        if activeOnly:
            return self.Execute(
                "SELECT * FROM services WHERE active = 1 ORDER BY sort_order, name",
                fetchAll=True,
            )
        return self.Execute(
            "SELECT * FROM services ORDER BY sort_order, name", fetchAll=True
        )

    def GetService(self, serviceKey: str, *, activeOnly: bool = True):
        sql = "SELECT * FROM services WHERE service_key = ?"
        if activeOnly:
            sql += " AND active = 1"
        return self.Execute(sql, (serviceKey,), fetchOne=True)

    def SaveService(self, serviceKey: str, name: str, price: int, active: bool = True) -> None:
        if not serviceKey.strip():
            raise ValueError("service_key cannot be empty")
        if not name.strip():
            raise ValueError("Service name cannot be empty")
        if isinstance(price, bool) or int(price) < 0:
            raise ValueError("Service price must be a non-negative integer")
        self.Execute(
            """INSERT INTO services(service_key, name, price, active, sort_order)
               VALUES (?, ?, ?, ?, COALESCE((SELECT MAX(sort_order) + 1 FROM services), 0))
               ON CONFLICT(service_key) DO UPDATE SET
                 name = excluded.name,
                 price = excluded.price,
                 active = excluded.active,
                 updated_at = CURRENT_TIMESTAMP""",
            (serviceKey.strip(), name.strip(), int(price), 1 if active else 0),
        )

    # ----- User balances -----

    def GetUser(self, userId: int):
        return self.Execute(
            "SELECT * FROM users WHERE user_id = ?", (int(userId),), fetchOne=True
        )

    def _EnsureUserWithinTransaction(
        self,
        userId: int,
        startingCredits: int,
        *,
        note: str = "initial server credit balance",
    ) -> bool:
        """Insert a missing user and audit the initial credit grant in the active transaction."""
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO users(user_id, credits) VALUES (?, ?)",
            (int(userId), int(startingCredits)),
        )
        if cursor.rowcount != 1:
            return False
        self.connection.execute(
            """INSERT INTO transactions
               (ticket_id, from_user, to_user, amount, type, note)
               VALUES (NULL, NULL, ?, ?, 'starting_balance', ?)""",
            (int(userId), int(startingCredits), str(note)[:500]),
        )
        return True

    def CreateUser(self, userId: int, credits: int | None = None) -> bool:
        if credits is None:
            credits = self.GetDefaultJoinCredits()
        if isinstance(credits, bool) or int(credits) < 0:
            raise ValueError("Starting credits must be a non-negative integer")
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                created = self._EnsureUserWithinTransaction(int(userId), int(credits))
                self.connection.commit()
                return created
            except Exception:
                self.connection.rollback()
                raise

    def RecordInviteAttribution(
        self,
        invitedUserId: int,
        inviterUserId: int,
        inviteCode: str,
        *,
        repeatOnRejoin: bool = False,
        joinedAt: str | None = None,
        inviteEventId: int | None = None,
    ) -> bool:
        """Remember the inviter, event provenance, and optional per-join-cycle penalty eligibility.

        The Discord member's joined_at timestamp identifies a join cycle. Repeated
        delivery of the same join event therefore cannot re-arm an already-used
        penalty. The default mode preserves the historical one-penalty-per-member
        behavior for existing servers.
        """
        invitedId, inviterId = int(invitedUserId), int(inviterUserId)
        if invitedId <= 0 or inviterId <= 0 or invitedId == inviterId:
            return False
        joinedAtText = str(joinedAt or "").strip()[:80]
        eventId = int(inviteEventId) if inviteEventId is not None else None
        if eventId is not None and eventId <= 0:
            eventId = None
        with self.databaseLock:
            try:
                self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
                cursor = self.connection.execute(
                    """INSERT INTO invite_attributions
                       (invited_user_id, inviter_user_id, invite_code, join_cycle, joined_at, invite_event_id)
                       VALUES (?, ?, ?, 1, ?, ?)
                       ON CONFLICT(invited_user_id) DO NOTHING""",
                    (invitedId, inviterId, str(inviteCode)[:100], joinedAtText, eventId),
                )
                inserted = cursor.rowcount == 1

                lockSql = "SELECT join_cycle, joined_at, invite_event_id FROM invite_attributions WHERE invited_user_id = ?"
                if self.backend == "postgresql":
                    lockSql += " FOR UPDATE"
                current = self.connection.execute(lockSql, (invitedId,)).fetchone()
                if current is not None and str(current["joined_at"] or "") != joinedAtText:
                    if repeatOnRejoin:
                        self.connection.execute(
                            """UPDATE invite_attributions
                               SET inviter_user_id = ?, invite_code = ?, penalty_applied = 0,
                                   join_cycle = join_cycle + 1, joined_at = ?, invite_event_id = ?
                               WHERE invited_user_id = ?""",
                            (inviterId, str(inviteCode)[:100], joinedAtText, eventId, invitedId),
                        )
                        inserted = True
                    else:
                        # Even in once-per-member mode, track the current join timestamp
                        # without resetting penalty_applied or changing the original inviter.
                        self.connection.execute(
                            "UPDATE invite_attributions SET joined_at = ? WHERE invited_user_id = ?",
                            (joinedAtText, invitedId),
                        )

                self.connection.commit()
                return inserted
            except Exception:
                self.connection.rollback()
                raise

    def GetInviteAttribution(self, invitedUserId: int, *, joinedAt: str | None = None):
        if joinedAt is None:
            return self.Execute(
                "SELECT * FROM invite_attributions WHERE invited_user_id = ? AND penalty_applied = 0",
                (int(invitedUserId),), fetchOne=True,
            )
        # Empty timestamps belong to legacy rows created before join-cycle tracking.
        # They remain eligible for their one outstanding legacy penalty. A timestamped
        # row must match the member object from this exact Discord leave event, so a
        # delayed old leave event cannot penalize a newer rejoin cycle.
        return self.Execute(
            "SELECT * FROM invite_attributions "
            "WHERE invited_user_id = ? AND penalty_applied = 0 AND (joined_at = ? OR joined_at = '')",
            (int(invitedUserId), str(joinedAt)[:80]), fetchOne=True,
        )

    def MarkInviteLeavePenaltyApplied(self, invitedUserId: int, joinCycle: int | None = None) -> bool:
        with self.databaseLock:
            try:
                if joinCycle is None:
                    cursor = self.connection.execute(
                        "UPDATE invite_attributions SET penalty_applied = 1 WHERE invited_user_id = ? AND penalty_applied = 0",
                        (int(invitedUserId),),
                    )
                else:
                    cursor = self.connection.execute(
                        "UPDATE invite_attributions SET penalty_applied = 1 "
                        "WHERE invited_user_id = ? AND join_cycle = ? AND penalty_applied = 0",
                        (int(invitedUserId), int(joinCycle)),
                    )
                self.connection.commit()
                return cursor.rowcount == 1
            except Exception:
                self.connection.rollback()
                raise

    def GetCreditDebt(self, userId: int) -> int:
        row = self.Execute("SELECT amount FROM credit_debts WHERE user_id = ?", (int(userId),), fetchOne=True)
        return int(row["amount"] or 0) if row else 0

    def ListCreditTransactions(self, userId: int, *, limit: int = 10, offset: int = 0):
        """Return recent ledger entries involving one member, newest first."""
        normalizedLimit = max(1, min(int(limit), 100))
        normalizedOffset = max(0, int(offset))
        return self.Execute(
            """SELECT id, ticket_id, from_user, to_user, amount, type,
                      actor_user_id, note, created_at
               FROM transactions
               WHERE from_user = ? OR to_user = ?
               ORDER BY id DESC LIMIT ? OFFSET ?""",
            (int(userId), int(userId), normalizedLimit, normalizedOffset),
            fetchAll=True,
        )

    def _ApplyRewardAgainstDebtWithinTransaction(
        self,
        userId: int,
        amount: int,
        *,
        actorUserId: int | None = None,
        sourceNote: str,
        ticketId: int | None = None,
    ) -> tuple[int, int]:
        """Apply earned credits to debt first; caller owns the active transaction."""
        normalizedUserId = int(userId)
        normalizedAmount = int(amount)
        if normalizedAmount < 0:
            raise ValueError("Reward amount cannot be negative.")
        self._EnsureUserWithinTransaction(normalizedUserId, self.GetDefaultJoinCredits())
        userLockSql = "SELECT credits FROM users WHERE user_id = ?"
        if self.backend == "postgresql":
            userLockSql += " FOR UPDATE"
        self.connection.execute(userLockSql, (normalizedUserId,)).fetchone()
        debtRow = self.connection.execute(
            "SELECT amount FROM credit_debts WHERE user_id = ?", (normalizedUserId,)
        ).fetchone()
        currentDebt = int(debtRow["amount"]) if debtRow else 0
        repayment = min(currentDebt, normalizedAmount)
        remainingDebt = currentDebt - repayment
        availableCredit = normalizedAmount - repayment
        if repayment:
            self.connection.execute(
                "UPDATE credit_debts SET amount = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (remainingDebt, normalizedUserId),
            )
            self.connection.execute(
                """INSERT INTO transactions
                   (ticket_id, from_user, to_user, amount, type, actor_user_id, note)
                   VALUES (?, ?, NULL, ?, 'debt_repayment', ?, ?)""",
                (int(ticketId) if ticketId is not None else None, normalizedUserId,
                 repayment, int(actorUserId) if actorUserId is not None else None,
                 ("Automatic debt offset: " + str(sourceNote).strip())[:500]),
            )
        self.connection.execute(
            "UPDATE users SET credits = credits + ? WHERE user_id = ?",
            (availableCredit, normalizedUserId),
        )
        balanceRow = self.connection.execute(
            "SELECT credits FROM users WHERE user_id = ?", (normalizedUserId,)
        ).fetchone()
        return int(balanceRow["credits"]), remainingDebt

    def ApplyPenaltyDebt(self, userId: int, amount: int, *, actorUserId: int, reason: str, idempotencyKey: str | None = None) -> tuple[str, int | None, int]:
        """Apply an audited penalty, using available credits before recording unpaid debt."""
        penalty = int(amount)
        note = str(reason).strip()[:500]
        if penalty <= 0 or penalty > 1_000_000_000 or not note:
            raise ValueError("A positive penalty up to 1,000,000,000 and a reason are required.")
        targetId, actorId = int(userId), int(actorUserId)
        key = str(idempotencyKey).strip() if idempotencyKey else None
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                if key:
                    prior = self.connection.execute("SELECT * FROM transactions WHERE idempotency_key = ?", (key,)).fetchone()
                    if prior is not None:
                        same = str(prior["type"]) == "penalty_debt" and int(prior["amount"]) == penalty and prior["to_user"] == targetId and prior["actor_user_id"] == actorId
                        debtRow = self.connection.execute('SELECT amount FROM credit_debts WHERE user_id = ?', (targetId,)).fetchone()
                        debt = int(debtRow["amount"]) if debtRow else 0
                        balanceRow = self.connection.execute('SELECT credits FROM users WHERE user_id = ?', (targetId,)).fetchone()
                        balance = int(balanceRow["credits"]) if balanceRow else None
                        self.connection.rollback()
                        return ("duplicate" if same else "idempotency_conflict"), balance, debt
                self._EnsureUserWithinTransaction(targetId, self.GetDefaultJoinCredits())
                userLockSql = "SELECT credits FROM users WHERE user_id = ?"
                if self.backend == "postgresql":
                    userLockSql += " FOR UPDATE"
                userRow = self.connection.execute(userLockSql, (targetId,)).fetchone()
                if key:
                    prior = self.connection.execute(
                        "SELECT * FROM transactions WHERE idempotency_key = ?", (key,)
                    ).fetchone()
                    if prior is not None:
                        same = str(prior["type"]) == "penalty_debt" and int(prior["amount"]) == penalty and prior["to_user"] == targetId and prior["actor_user_id"] == actorId
                        debtRow = self.connection.execute(
                            "SELECT amount FROM credit_debts WHERE user_id = ?", (targetId,)
                        ).fetchone()
                        debt = int(debtRow["amount"]) if debtRow else 0
                        balance = int(userRow["credits"])
                        self.connection.rollback()
                        return ("duplicate" if same else "idempotency_conflict"), balance, debt
                credits = int(userRow["credits"])
                debtRow = self.connection.execute("SELECT amount FROM credit_debts WHERE user_id = ?", (targetId,)).fetchone()
                oldDebt = int(debtRow["amount"]) if debtRow else 0
                consumed = min(credits, penalty)
                newCredits = credits - consumed
                newDebt = oldDebt + penalty - consumed
                self.connection.execute("UPDATE users SET credits = ? WHERE user_id = ?", (newCredits, targetId))
                self.connection.execute("""INSERT INTO credit_debts(user_id, amount, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id) DO UPDATE SET amount = excluded.amount, updated_at = CURRENT_TIMESTAMP""",
                    (targetId, newDebt),
                )
                self.connection.execute("""INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note, idempotency_key)
                    VALUES (NULL, ?, ?, ?, 'penalty_debt', ?, ?, ?)""",
                    (targetId, targetId, penalty, actorId, note, key),
                )
                self.connection.commit()
                return "penalized", newCredits, newDebt
            except Exception:
                self.connection.rollback()
                raise

    def RepayCreditDebt(
        self,
        userId: int,
        amount: int,
        *,
        idempotencyKey: str | None = None,
    ) -> tuple[str, int | None, int]:
        """Use a member's available credits to repay outstanding debt atomically.

        The repayment is recorded as its own immutable transaction row. A
        repeated interaction ID cannot deduct credits or reduce debt twice.
        Returns (status, current_balance, remaining_debt).
        """
        if isinstance(amount, bool):
            raise ValueError("Repayment amount must be a positive integer.")
        try:
            normalizedAmount = int(amount)
        except (TypeError, ValueError) as error:
            raise ValueError("Repayment amount must be a positive integer.") from error
        if normalizedAmount <= 0 or normalizedAmount > 1_000_000_000:
            raise ValueError("Repayment amount must be between 1 and 1,000,000,000 credits.")

        normalizedUserId = int(userId)
        normalizedKey = str(idempotencyKey).strip() if idempotencyKey is not None else None
        if normalizedKey == "":
            normalizedKey = None
        if normalizedKey is not None and len(normalizedKey) > 200:
            raise ValueError("idempotencyKey must be 200 characters or fewer.")

        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                self._EnsureUserWithinTransaction(normalizedUserId, self.GetDefaultJoinCredits())
                balanceSql = "SELECT credits FROM users WHERE user_id = ?"
                if self.backend == "postgresql":
                    balanceSql += " FOR UPDATE"
                balanceRow = self.connection.execute(balanceSql, (normalizedUserId,)).fetchone()
                if normalizedKey is not None:
                    existing = self.connection.execute(
                        "SELECT * FROM transactions WHERE idempotency_key = ?",
                        (normalizedKey,),
                    ).fetchone()
                    if existing is not None:
                        sameOperation = (
                            str(existing["type"]) == "debt_repayment"
                            and int(existing["amount"]) == normalizedAmount
                            and existing["from_user"] == normalizedUserId
                            and existing["to_user"] is None
                            and existing["actor_user_id"] == normalizedUserId
                        )
                        debtRow = self.connection.execute(
                            "SELECT amount FROM credit_debts WHERE user_id = ?", (normalizedUserId,)
                        ).fetchone()
                        balance = int(balanceRow["credits"]) if balanceRow else None
                        debt = int(debtRow["amount"]) if debtRow else 0
                        self.connection.rollback()
                        return ("duplicate" if sameOperation else "idempotency_conflict"), balance, debt
                debtRow = self.connection.execute(
                    "SELECT amount FROM credit_debts WHERE user_id = ?", (normalizedUserId,)
                ).fetchone()
                balance = int(balanceRow["credits"])
                debt = int(debtRow["amount"]) if debtRow else 0

                if debt <= 0:
                    self.connection.rollback()
                    return "no_debt", balance, 0
                if balance < normalizedAmount:
                    self.connection.rollback()
                    return "insufficient_credits", balance, debt
                if normalizedAmount > debt:
                    self.connection.rollback()
                    return "exceeds_debt", balance, debt

                cursor = self.connection.execute(
                    "UPDATE users SET credits = credits - ? WHERE user_id = ? AND credits >= ?",
                    (normalizedAmount, normalizedUserId, normalizedAmount),
                )
                if cursor.rowcount != 1:
                    self.connection.rollback()
                    return "insufficient_credits", balance, debt

                remainingDebt = debt - normalizedAmount
                self.connection.execute(
                    "UPDATE credit_debts SET amount = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (remainingDebt, normalizedUserId),
                )
                self.connection.execute(
                    """INSERT INTO transactions
                       (ticket_id, from_user, to_user, amount, type, actor_user_id, note, idempotency_key)
                       VALUES (NULL, ?, NULL, ?, 'debt_repayment', ?, ?, ?)""",
                    (normalizedUserId, normalizedAmount, normalizedUserId,
                     "Member-initiated debt repayment", normalizedKey),
                )
                newBalanceRow = self.connection.execute(
                    "SELECT credits FROM users WHERE user_id = ?", (normalizedUserId,)
                ).fetchone()
                newBalance = int(newBalanceRow["credits"])
                self.connection.commit()
                return "repaid", newBalance, remainingDebt
            except Exception:
                self.connection.rollback()
                raise

    def GetBalance(self, userId: int) -> int:
        row = self.GetUser(userId)
        if row is None:
            self.CreateUser(userId)
            row = self.GetUser(userId)
        return int(row["credits"])

    def ApplyCreditAdjustment(
        self,
        userId: int,
        amount: int,
        *,
        direction: str,
        actorUserId: int | None = None,
        note: str | None = None,
        idempotencyKey: str | None = None,
    ) -> tuple[str, int | None]:
        """Atomically adjust a balance and record an auditable ledger row.

        direction is "add" or "deduct". When an idempotency key is supplied,
        replaying the same operation returns "duplicate" without applying it again.
        Reusing that key for a different operation returns "idempotency_conflict".
        """
        if direction not in {"add", "deduct"}:
            raise ValueError("direction must be 'add' or 'deduct'")
        if isinstance(amount, bool):
            raise ValueError("Credit amount must be a positive integer")
        try:
            normalizedAmount = int(amount)
        except (TypeError, ValueError) as error:
            raise ValueError("Credit amount must be a positive integer") from error
        if normalizedAmount <= 0:
            raise ValueError("Credit amount must be a positive integer")

        normalizedUserId = int(userId)
        normalizedActorId = int(actorUserId) if actorUserId is not None else None
        normalizedNote = str(note).strip()[:500] if note and str(note).strip() else None
        normalizedKey = str(idempotencyKey).strip() if idempotencyKey is not None else None
        if normalizedKey == "":
            normalizedKey = None
        if normalizedKey is not None and len(normalizedKey) > 200:
            raise ValueError("idempotencyKey must be 200 characters or fewer")

        if normalizedActorId is None:
            transactionType = f"system_{direction}"
        else:
            transactionType = f"admin_{direction}"

        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                if normalizedKey is not None:
                    existing = self.connection.execute(
                        "SELECT * FROM transactions WHERE idempotency_key = ?",
                        (normalizedKey,),
                    ).fetchone()
                    if existing is not None:
                        expectedFromUser = normalizedUserId if direction == "deduct" else None
                        expectedToUser = normalizedUserId if direction == "add" else None
                        sameOperation = (
                            str(existing["type"]) == transactionType
                            and int(existing["amount"]) == normalizedAmount
                            and existing["from_user"] == expectedFromUser
                            and existing["to_user"] == expectedToUser
                            and existing["actor_user_id"] == normalizedActorId
                        )
                        balanceRow = self.connection.execute(
                            "SELECT credits FROM users WHERE user_id = ?",
                            (normalizedUserId,),
                        ).fetchone()
                        currentBalance = int(balanceRow["credits"]) if balanceRow else None
                        self.connection.rollback()
                        if sameOperation:
                            return "duplicate", currentBalance
                        return "idempotency_conflict", currentBalance

                defaultCredits = self.GetDefaultJoinCredits()
                self._EnsureUserWithinTransaction(normalizedUserId, defaultCredits)
                balanceRow = self.connection.execute(
                    "SELECT credits FROM users WHERE user_id = ?",
                    (normalizedUserId,),
                ).fetchone()
                currentBalance = int(balanceRow["credits"])

                if direction == "deduct" and currentBalance < normalizedAmount:
                    self.connection.rollback()
                    return "insufficient", currentBalance

                if direction == "add":
                    self.connection.execute(
                        "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                        (normalizedAmount, normalizedUserId),
                    )
                    fromUser = None
                    toUser = normalizedUserId
                else:
                    cursor = self.connection.execute(
                        "UPDATE users SET credits = credits - ? "
                        "WHERE user_id = ? AND credits >= ?",
                        (normalizedAmount, normalizedUserId, normalizedAmount),
                    )
                    if cursor.rowcount != 1:
                        self.connection.rollback()
                        return "insufficient", currentBalance
                    fromUser = normalizedUserId
                    toUser = None

                self.connection.execute(
                    """INSERT INTO transactions
                       (ticket_id, from_user, to_user, amount, type, actor_user_id, note, idempotency_key)
                       VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fromUser, toUser, normalizedAmount, transactionType,
                        normalizedActorId, normalizedNote, normalizedKey,
                    ),
                )
                balanceRow = self.connection.execute(
                    "SELECT credits FROM users WHERE user_id = ?",
                    (normalizedUserId,),
                ).fetchone()
                newBalance = int(balanceRow["credits"])
                self.connection.commit()
                return ("added" if direction == "add" else "deducted"), newBalance
            except Exception:
                self.connection.rollback()
                raise

    def AddCredits(
        self,
        userId: int,
        amount: int,
        *,
        actorUserId: int | None = None,
        note: str | None = None,
        idempotencyKey: str | None = None,
    ) -> tuple[str, int | None]:
        """Audited convenience wrapper for a positive credit addition."""
        return self.ApplyCreditAdjustment(
            userId,
            amount,
            direction="add",
            actorUserId=actorUserId,
            note=note,
            idempotencyKey=idempotencyKey,
        )

    def RemoveCredits(
        self,
        userId: int,
        amount: int,
        *,
        actorUserId: int | None = None,
        note: str | None = None,
        idempotencyKey: str | None = None,
    ) -> bool:
        """Audited deduction helper; returns False if the balance is insufficient."""
        status, _ = self.ApplyCreditAdjustment(
            userId,
            amount,
            direction="deduct",
            actorUserId=actorUserId,
            note=note,
            idempotencyKey=idempotencyKey,
        )
        return status == "deducted"

    # ----- Ticket lifecycle: each financial transition is atomic -----

    def _AllocateTranscriptSequenceWithinTransaction(self) -> int:
        """Allocate a never-reused per-server sequence for transcript identifiers.

        Caller must hold databaseLock and an active write transaction.
        """
        self.connection.execute(
            "INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES ('next_ticket_sequence', '1')"
        )
        nextSequenceSql = "SELECT setting_value FROM settings WHERE setting_key = 'next_ticket_sequence'"
        if self.backend == "postgresql":
            nextSequenceSql += " FOR UPDATE"
        nextRow = self.connection.execute(nextSequenceSql).fetchone()
        try:
            configuredNext = int(nextRow["setting_value"]) if nextRow else 1
        except (TypeError, ValueError):
            configuredNext = 1

        highWaterRow = self.connection.execute(
            "SELECT COALESCE(MAX(ticket_number), 0) AS max_ticket_number, "
            "COALESCE(MAX(ticket_sequence), 0) AS max_ticket_sequence FROM tickets"
        ).fetchone()
        highWater = max(
            int(highWaterRow["max_ticket_number"] or 0),
            int(highWaterRow["max_ticket_sequence"] or 0),
        )
        sequence = max(1, configuredNext, highWater + 1)
        self.connection.execute(
            """INSERT INTO settings(setting_key, setting_value, updated_at)
               VALUES ('next_ticket_sequence', ?, CURRENT_TIMESTAMP)
               ON CONFLICT(setting_key) DO UPDATE SET
                 setting_value = excluded.setting_value,
                 updated_at = CURRENT_TIMESTAMP""",
            (str(sequence + 1),),
        )
        return sequence

    def _AllocateTicketChannelNumberWithinTransaction(self) -> int:
        """Choose a channel label that is unused by active tickets in this guild.

        Ticket channel numbers restart at 1 whenever no tickets are open. When
        other tickets remain open, allocation continues forward and skips any
        number already used by an open ticket. Caller holds the write transaction.
        """
        self.connection.execute(
            "INSERT OR IGNORE INTO settings(setting_key, setting_value) VALUES ('next_ticket_channel_number', '1')"
        )
        nextNumberSql = "SELECT setting_value FROM settings WHERE setting_key = 'next_ticket_channel_number'"
        if self.backend == "postgresql":
            nextNumberSql += " FOR UPDATE"
        nextRow = self.connection.execute(nextNumberSql).fetchone()
        try:
            candidate = max(1, int(nextRow["setting_value"]) if nextRow else 1)
        except (TypeError, ValueError):
            candidate = 1

        openRows = self.connection.execute(
            "SELECT COALESCE(channel_ticket_number, ticket_number) AS active_number "
            "FROM tickets WHERE status = 'open'"
        ).fetchall()
        openNumbers = {
            int(row["active_number"])
            for row in openRows
            if row["active_number"] is not None and int(row["active_number"]) > 0
        }
        if not openNumbers:
            candidate = 1
        while candidate in openNumbers:
            candidate += 1

        self.connection.execute(
            """INSERT INTO settings(setting_key, setting_value, updated_at)
               VALUES ('next_ticket_channel_number', ?, CURRENT_TIMESTAMP)
               ON CONFLICT(setting_key) DO UPDATE SET
                 setting_value = excluded.setting_value,
                 updated_at = CURRENT_TIMESTAMP""",
            (str(candidate + 1),),
        )
        return candidate

    def ReserveTicket(
        self,
        channelId: int,
        creatorId: int,
        eventKey: str,
        helperIds: list[int],
        requiredCredits: int,
        pricePerHelper: int | None = None,
    ) -> int | None:
        """Atomically reserve the total, allocate a number, and log the reservation.

        New tickets pass ``pricePerHelper`` and reserve exactly that unit price multiplied
        by the number of selected helpers. Omitting it retains the legacy fixed-total
        policy for direct integrations and historic data.
        Returns the ticket ID, or None if the requester has insufficient credits.
        """
        if isinstance(requiredCredits, bool):
            raise ValueError("Ticket price must be a non-negative integer")
        try:
            amount = int(requiredCredits)
        except (TypeError, ValueError) as error:
            raise ValueError("Ticket price must be a non-negative integer") from error
        if amount < 0:
            raise ValueError("Ticket price must be a non-negative integer")
        normalizedUnitPrice: int | None = None
        if pricePerHelper is not None:
            if isinstance(pricePerHelper, bool):
                raise ValueError("Price per helper must be a non-negative integer")
            try:
                normalizedUnitPrice = int(pricePerHelper)
            except (TypeError, ValueError) as error:
                raise ValueError("Price per helper must be a non-negative integer") from error
            if normalizedUnitPrice < 0:
                raise ValueError("Price per helper must be a non-negative integer")

        normalizedChannelId = int(channelId)
        normalizedCreatorId = int(creatorId)
        normalizedEventKey = str(eventKey).strip()
        helpers = [int(helperId) for helperId in helperIds]
        if not normalizedEventKey:
            raise ValueError("eventKey cannot be empty")
        if not helpers:
            raise ValueError("A ticket must have at least one helper")
        if normalizedCreatorId in helpers:
            raise ValueError("The requester cannot be listed as a helper")
        if len(set(helpers)) != len(helpers):
            raise ValueError("A helper can only be listed once per ticket")
        if normalizedUnitPrice is not None and amount != normalizedUnitPrice * len(helpers):
            raise ValueError(
                "Total ticket price must equal the per-helper price multiplied by the helper count"
            )

        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                defaultCredits = self.GetDefaultJoinCredits()
                self._EnsureUserWithinTransaction(normalizedCreatorId, defaultCredits)
                for helperId in helpers:
                    self._EnsureUserWithinTransaction(helperId, defaultCredits)
                # Requesters must clear debt before reserving a new ticket.
                # Indebted members may still help; their earned reward is applied
                # to outstanding debt first by _ApplyRewardAgainstDebtWithinTransaction.
                debtRow = self.connection.execute("SELECT amount FROM credit_debts WHERE user_id = ?", (normalizedCreatorId,)).fetchone()
                if debtRow is not None and int(debtRow["amount"] or 0) > 0:
                    self.connection.rollback()
                    return None
                reservation = self.connection.execute(
                    "UPDATE users SET credits = credits - ? "
                    "WHERE user_id = ? AND credits >= ?",
                    (amount, normalizedCreatorId, amount),
                )
                if reservation.rowcount != 1:
                    self.connection.rollback()
                    return None

                ticketSequence = self._AllocateTranscriptSequenceWithinTransaction()
                ticketNumber = ticketSequence  # Retained as the historical/global numeric identifier.
                channelTicketNumber = self._AllocateTicketChannelNumberWithinTransaction()
                ticketInsertSql = """INSERT INTO tickets
                       (ticket_number, ticket_sequence, channel_ticket_number, channel_id, guild_id, creator_id, event_key, helper_ids,
                        active_helper_ids, required_credits, reserved_credits, price_per_helper, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')"""
                if self.backend == "postgresql":
                    ticketInsertSql += " RETURNING ticket_id"
                ticketCursor = self.connection.execute(
                    ticketInsertSql,
                    (
                        ticketNumber, ticketSequence, channelTicketNumber, normalizedChannelId, self.guildId,
                        normalizedCreatorId, normalizedEventKey, ",".join(map(str, helpers)),
                        ",".join(map(str, helpers)), amount, amount, normalizedUnitPrice,
                    ),
                )
                if self.backend == "postgresql":
                    ticketId = int(ticketCursor.fetchone()["ticket_id"])
                else:
                    ticketId = int(ticketCursor.lastrowid)
                self.connection.execute(
                    """INSERT INTO transactions
                       (ticket_id, from_user, to_user, amount, type, actor_user_id, note)
                       VALUES (?, ?, NULL, ?, 'ticket_reservation', ?, ?)""",
                    (ticketId, normalizedCreatorId, amount, normalizedCreatorId, "ticket reservation"),
                )
                self.connection.commit()
                return ticketId
            except Exception:
                self.connection.rollback()
                raise

    def GetUnauditedTicketTransactions(self, ticketId: int):
        """Return positive credit movements for a ticket that have not yet reached the audit channel."""
        return self.Execute(
            """SELECT t.id, t.ticket_id, t.type, t.amount, t.from_user, t.to_user,
                      t.actor_user_id, t.note, t.created_at
               FROM transactions t
               LEFT JOIN transaction_audit_deliveries a ON a.transaction_id = t.id
               WHERE t.ticket_id = ? AND t.amount > 0 AND a.transaction_id IS NULL
               ORDER BY t.id""",
            (int(ticketId),), fetchAll=True,
        )

    def MarkTransactionAuditDelivered(self, transactionId: int) -> None:
        """Mark a transaction only after its audit embed was successfully sent."""
        with self.databaseLock:
            self.connection.execute(
                """INSERT INTO transaction_audit_deliveries(transaction_id)
                   VALUES (?) ON CONFLICT(transaction_id) DO NOTHING""",
                (int(transactionId),),
            )
            self.connection.commit()

    def GetTicketById(self, ticketId: int):
        return self.Execute(
            "SELECT * FROM tickets WHERE ticket_id = ?",
            (int(ticketId),), fetchOne=True,
        )

    def GetTicketByChannel(self, channelId: int):
        return self.Execute(
            "SELECT * FROM tickets WHERE channel_id = ?",
            (int(channelId),), fetchOne=True,
        )

    def GetOpenTicketForUser(self, userId: int):
        return self.Execute(
            "SELECT * FROM tickets WHERE creator_id = ? AND status = 'open' "
            "ORDER BY ticket_id DESC LIMIT 1",
            (int(userId),), fetchOne=True,
        )

    @staticmethod
    def _ParseIdCsv(value: str | None) -> list[int]:
        result: list[int] = []
        for item in (value or "").split(","):
            try:
                itemId = int(item.strip())
            except (TypeError, ValueError):
                continue
            if itemId > 0 and itemId not in result:
                result.append(itemId)
        return result

    def GetTicketParticipantIds(self, ticketId: int) -> set[int]:
        """Return everyone associated with an open ticket, including original/departed helpers.

        Original helpers remain participants for administrative-conflict checks after leaving,
        preventing someone from leaving and then using a staff override on their own ticket.
        Pending replacement candidates are included so they cannot approve their own selection.
        """
        ticket = self.GetTicketById(int(ticketId))
        if ticket is None:
            return set()
        participantIds = {int(ticket["creator_id"])}
        for fieldName in ("helper_ids", "active_helper_ids", "replacement_candidate_ids"):
            participantIds.update(self._ParseIdCsv(str(ticket[fieldName] or "")))
        return participantIds

    def IsUserTicketParticipant(self, ticketId: int, userId: int) -> bool:
        """Whether userId is requester, original/current helper, or pending candidate."""
        return int(userId) in self.GetTicketParticipantIds(int(ticketId))

    def IsUserParticipantInAnyOpenTicket(self, userId: int) -> bool:
        """Whether userId is involved in any open ticket in this server."""
        normalizedUserId = int(userId)
        return any(
            normalizedUserId in self.GetTicketParticipantIds(int(ticket["ticket_id"]))
            for ticket in self.ListOpenTickets()
        )

    def RequestTicketResolution(self, ticketId: int, resolutionType: str, proposerId: int) -> tuple[str, list[int]]:
        """Record a requester- or active-helper-proposed resolution awaiting every participant's approval."""
        if resolutionType not in {"complete", "cancel"}:
            raise ValueError("resolutionType must be 'complete' or 'cancel'")
        normalizedProposerId = int(proposerId)
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", []
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", []

                requesterId = int(ticket["creator_id"])
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if normalizedProposerId != requesterId and normalizedProposerId not in activeIds:
                    self.connection.rollback()
                    return "not_authorized", []
                if int(ticket["resolution_locked"] or 0):
                    self.connection.rollback()
                    return "processing", []
                if int(ticket["replacement_requested"] or 0):
                    self.connection.rollback()
                    return "replacement_pending", activeIds
                if str(ticket["resolution_type"] or "") in {"complete", "cancel"}:
                    self.connection.rollback()
                    return "existing_request", activeIds
                if not activeIds:
                    self.connection.rollback()
                    return "no_active_helpers", []

                proposerRole = "requester" if normalizedProposerId == requesterId else "active helper"
                self.connection.execute(
                    "UPDATE tickets SET resolution_type = ?, resolution_requested_by = ?, resolution_confirmations = ?, resolution_requested_at = CURRENT_TIMESTAMP, resolution_message_id = NULL, resolution_locked = 0 WHERE ticket_id = ? AND status = 'open'",
                    (resolutionType, normalizedProposerId, str(normalizedProposerId), int(ticketId)),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, ?, ?, ?)",
                    (
                        int(ticketId),
                        "ticket_completion_requested" if resolutionType == "complete" else "ticket_cancellation_requested",
                        normalizedProposerId,
                        f"{proposerRole} proposed {resolutionType}; proposer counts as the first approval and the requester plus all active helpers must approve",
                    ),
                )
                self.connection.commit()
                return "requested", activeIds
            except Exception:
                self.connection.rollback()
                raise


    def SetResolutionMessageId(self, ticketId: int, messageId: int) -> bool:
        """Store the visible proposal message while the ticket awaits helper votes."""
        cursor = self.Execute(
            "UPDATE tickets SET resolution_message_id = ? "
            "WHERE ticket_id = ? AND status = 'open' AND resolution_type IN ('complete', 'cancel')",
            (int(messageId), int(ticketId)),
        )
        return cursor.rowcount == 1

    def ClearTicketResolutionRequest(self, ticketId: int) -> None:
        """Clear an unfinalized proposal when its visible prompt could not be posted."""
        self.Execute(
            "UPDATE tickets SET resolution_type = '', resolution_requested_by = NULL, "
            "resolution_confirmations = '', resolution_requested_at = NULL, "
            "resolution_message_id = NULL, resolution_locked = 0 "
            "WHERE ticket_id = ? AND status = 'open' AND resolution_locked = 0",
            (int(ticketId),),
        )

    def ConfirmTicketResolution(self, ticketId: int, helperId: int) -> tuple[str, int, int, str | None]:
        """Record approval from the requester or an active helper for a pending resolution."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", 0, 0, None
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", 0, 0, None
                resolutionType = str(ticket["resolution_type"] or "")
                if resolutionType not in {"complete", "cancel"}:
                    self.connection.rollback()
                    return "no_request", 0, 0, None
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                requesterId = int(ticket["creator_id"])
                requiredIds = list(dict.fromkeys([requesterId, *activeIds]))
                requiredCount = len(requiredIds)
                normalizedActorId = int(helperId)
                if normalizedActorId not in requiredIds:
                    self.connection.rollback()
                    return "not_participant", 0, requiredCount, resolutionType
                if int(ticket["resolution_locked"] or 0):
                    confirmations = self._ParseIdCsv(str(ticket["resolution_confirmations"] or ""))
                    self.connection.rollback()
                    return ("duplicate" if normalizedActorId in confirmations else "processing"), len(set(confirmations) & set(requiredIds)), requiredCount, resolutionType
                requestedAt = ticket["resolution_requested_at"]
                expiredRow = self.connection.execute(
                    "SELECT CASE WHEN ? IS NULL OR datetime(?) <= datetime('now', '-15 minutes') THEN 1 ELSE 0 END AS expired",
                    (requestedAt, requestedAt),
                ).fetchone()
                if expiredRow and int(expiredRow["expired"]):
                    self.connection.execute(
                        "UPDATE tickets SET resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0 WHERE ticket_id = ? AND status = 'open'",
                        (int(ticketId),),
                    )
                    self.connection.commit()
                    return "expired", 0, 0, resolutionType
                confirmations = self._ParseIdCsv(str(ticket["resolution_confirmations"] or ""))
                proposerId = int(ticket["resolution_requested_by"] or requesterId)
                if proposerId not in confirmations:
                    confirmations.insert(0, proposerId)
                if normalizedActorId in confirmations:
                    self.connection.rollback()
                    return "duplicate", len(set(confirmations) & set(requiredIds)), requiredCount, resolutionType
                confirmations.append(normalizedActorId)
                isReady = set(confirmations) >= set(requiredIds)
                self.connection.execute(
                    "UPDATE tickets SET resolution_confirmations = ?, resolution_locked = ? WHERE ticket_id = ? AND status = 'open'",
                    (",".join(map(str, confirmations)), 1 if isReady else 0, int(ticketId)),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, ?, ?, ?)",
                    (
                        int(ticketId),
                        "helper_confirmation" if int(helperId) in activeIds else "requester_confirmation",
                        int(helperId),
                        f"{'helper' if int(helperId) in activeIds else 'requester'} confirmed proposed {resolutionType}",
                    ),
                )
                self.connection.commit()
                result = "ready" if isReady else "confirmed"
                return result, len(set(confirmations) & set(requiredIds)), requiredCount, resolutionType
            except Exception:
                self.connection.rollback()
                raise

    def ExpireStaleResolutionRequests(self, ageMinutes: int = 15) -> list[tuple[int, int, str, int | None]]:
        """Expire stale helper-confirmation proposals atomically and return ticket locations."""
        ageMinutes = max(1, min(int(ageMinutes), 1440))
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                rows = self.connection.execute(
                    "SELECT ticket_id, channel_id, resolution_type, resolution_message_id FROM tickets "
                    "WHERE status = 'open' AND resolution_type IN ('complete', 'cancel') "
                    "AND resolution_requested_at IS NOT NULL "
                    "AND datetime(resolution_requested_at) <= datetime('now', ?)",
                    (f"-{ageMinutes} minutes",),
                ).fetchall()
                if rows:
                    ticketIds = [int(row["ticket_id"]) for row in rows]
                    placeholders = ",".join("?" for _ in ticketIds)
                    self.connection.execute(
                        f"UPDATE tickets SET resolution_type = '', resolution_requested_by = NULL, "
                        f"resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0 "
                        f"WHERE ticket_id IN ({placeholders}) AND status = 'open'",
                        tuple(ticketIds),
                    )
                    for row in rows:
                        self.connection.execute(
                            "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, 'resolution_timeout', NULL, ?)",
                            (int(row["ticket_id"]), f"proposed {row['resolution_type']} expired after {ageMinutes} minutes; no credits moved"),
                        )
                self.connection.commit()
                return [
                    (
                        int(row["ticket_id"]),
                        int(row["channel_id"] or 0),
                        str(row["resolution_type"]),
                        int(row["resolution_message_id"]) if row["resolution_message_id"] is not None else None,
                    )
                    for row in rows
                ]
            except Exception:
                self.connection.rollback()
                raise

    def RejectTicketResolution(self, ticketId: int, helperId: int) -> tuple[str, str | None]:
        """Allow the requester or an active helper to veto a proposal; staff override remains available."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", None
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", None
                resolutionType = str(ticket["resolution_type"] or "")
                if resolutionType not in {"complete", "cancel"}:
                    self.connection.rollback()
                    return "no_request", None
                if int(ticket["resolution_locked"] or 0):
                    self.connection.rollback()
                    return "already_confirmed", resolutionType
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                requesterId = int(ticket["creator_id"])
                normalizedActorId = int(helperId)
                if normalizedActorId != requesterId and normalizedActorId not in activeIds:
                    self.connection.rollback()
                    return "not_participant", resolutionType
                self.connection.execute(
                    "UPDATE tickets SET resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0 WHERE ticket_id = ? AND status = 'open'",
                    (int(ticketId),),
                )
                actorRole = "helper" if normalizedActorId in activeIds else "requester"
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, ?, ?, ?)",
                    (
                        int(ticketId),
                        "helper_rejected_resolution" if actorRole == "helper" else "requester_rejected_resolution",
                        normalizedActorId,
                        f"{actorRole} rejected proposed {resolutionType}",
                    ),
                )
                self.connection.commit()
                return "rejected", resolutionType
            except Exception:
                self.connection.rollback()
                raise

    def LeaveTicketHelper(self, ticketId: int, helperId: int) -> tuple[str, list[int], int]:
        """Remove an active helper from the roster and audit the departure."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", [], 0
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", [], 0
                if int(ticket["resolution_locked"] or 0):
                    self.connection.rollback()
                    return "processing", self._ParseIdCsv(str(ticket["active_helper_ids"])), len(self._ParseIdCsv(str(ticket["helper_ids"])))
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if int(helperId) not in activeIds:
                    self.connection.rollback()
                    return "not_active_helper", activeIds, len(self._ParseIdCsv(str(ticket["helper_ids"])))
                activeIds.remove(int(helperId))
                self.connection.execute(
                    "UPDATE tickets SET active_helper_ids = ?, resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0, replacement_requested = 0, replacement_candidate_ids = '', replacement_request_message_id = NULL, replacement_button_message_id = NULL WHERE ticket_id = ? AND status = 'open'",
                    (",".join(map(str, activeIds)), int(ticketId)),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, 'helper_leave', ?, ?)",
                    (int(ticketId), int(helperId), "helper left ticket"),
                )
                originalCount = len(self._ParseIdCsv(str(ticket["helper_ids"])))
                self.connection.commit()
                return "left", activeIds, originalCount
            except Exception:
                self.connection.rollback()
                raise

    def RequestHelperReplacement(self, ticketId: int, requesterId: int) -> tuple[str, int, int]:
        """Legacy DB API retained for older tests; current Discord UI uses candidate selection."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", 0, 0
                if ticket["status"] != "open" or int(ticket["creator_id"]) != int(requesterId):
                    self.connection.rollback()
                    return "not_authorized", 0, 0
                if int(ticket["resolution_locked"] or 0) or str(ticket["resolution_type"] or "") in {"complete", "cancel"}:
                    self.connection.rollback()
                    return "processing", 0, 0
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                originalCount = len(self._ParseIdCsv(str(ticket["helper_ids"])))
                if originalCount <= 1 or len(activeIds) != 1 or len(activeIds) >= originalCount:
                    self.connection.rollback()
                    return "not_eligible", len(activeIds), originalCount
                if int(ticket["replacement_requested"] or 0):
                    self.connection.rollback()
                    return "already_requested", len(activeIds), originalCount
                self.connection.execute("UPDATE tickets SET replacement_requested = 1 WHERE ticket_id = ? AND status = 'open'", (int(ticketId),))
                self.connection.commit()
                return "requested", len(activeIds), originalCount
            except Exception:
                self.connection.rollback()
                raise

    def CheckReplacementEligibility(self, ticketId: int, requesterId: int) -> tuple[str, int, int]:
        """Check whether the requester may select replacements without changing state."""
        with self.databaseLock:
            ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
            if ticket is None:
                return "not_found", 0, 0
            if ticket["status"] != "open" or int(ticket["creator_id"]) != int(requesterId):
                return "not_authorized", 0, 0
            if int(ticket["resolution_locked"] or 0) or str(ticket["resolution_type"] or "") in {"complete", "cancel"}:
                return "processing", 0, 0
            if int(ticket["replacement_requested"] or 0):
                return "already_requested", len(self._ParseIdCsv(str(ticket["active_helper_ids"]))), len(self._ParseIdCsv(str(ticket["helper_ids"])))
            activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
            originalCount = len(self._ParseIdCsv(str(ticket["helper_ids"])))
            if originalCount <= 1 or len(activeIds) != 1 or len(activeIds) >= originalCount:
                return "not_eligible", len(activeIds), originalCount
            return "eligible", len(activeIds), originalCount

    def SubmitReplacementCandidates(
        self, ticketId: int, requesterId: int, candidateIds: Iterable[int]
    ) -> tuple[str, int, int, int]:
        """Persist requester-selected replacement candidates for staff review."""
        rawIds = list(candidateIds)
        normalizedIds: list[int] = []
        for candidate in rawIds:
            candidateId = int(candidate)
            if candidateId <= 0 or candidateId in normalizedIds:
                return "invalid_candidates", 0, 0, 0
            normalizedIds.append(candidateId)
        if not normalizedIds:
            return "invalid_candidates", 0, 0, 0

        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", 0, 0, 0
                if ticket["status"] != "open" or int(ticket["creator_id"]) != int(requesterId):
                    self.connection.rollback()
                    return "not_authorized", 0, 0, 0
                if int(ticket["resolution_locked"] or 0) or str(ticket["resolution_type"] or "") in {"complete", "cancel"}:
                    self.connection.rollback()
                    return "processing", 0, 0, 0
                if int(ticket["replacement_requested"] or 0):
                    self.connection.rollback()
                    return "already_requested", 0, 0, 0
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                originalIds = self._ParseIdCsv(str(ticket["helper_ids"]))
                originalCount = len(originalIds)
                activeCount = len(activeIds)
                missingCount = originalCount - activeCount
                if originalCount <= 1 or activeCount != 1 or missingCount < 1:
                    self.connection.rollback()
                    return "not_eligible", activeCount, originalCount, max(0, missingCount)
                if len(normalizedIds) != missingCount:
                    self.connection.rollback()
                    return "wrong_candidate_count", activeCount, originalCount, missingCount
                if int(requesterId) in normalizedIds or set(normalizedIds).intersection(activeIds) or set(normalizedIds).intersection(originalIds):
                    self.connection.rollback()
                    return "invalid_candidates", activeCount, originalCount, missingCount
                self.connection.execute(
                    "UPDATE tickets SET replacement_requested = 1, replacement_candidate_ids = ?, "
                    "replacement_request_message_id = NULL, replacement_button_message_id = NULL "
                    "WHERE ticket_id = ? AND status = 'open'",
                    (",".join(map(str, normalizedIds)), int(ticketId)),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) "
                    "VALUES (?, NULL, NULL, 0, 'replacement_request', ?, ?)",
                    (int(ticketId), int(requesterId), "requester selected replacement candidates: " + ",".join(map(str, normalizedIds))),
                )
                self.connection.commit()
                return "requested", activeCount, originalCount, missingCount
            except Exception:
                self.connection.rollback()
                raise

    def GetReplacementCandidateIds(self, ticketId: int) -> list[int]:
        row = self.Execute(
            "SELECT replacement_candidate_ids FROM tickets WHERE ticket_id = ?",
            (int(ticketId),), fetchOne=True,
        )
        return self._ParseIdCsv(str(row["replacement_candidate_ids"] or "")) if row else []

    def SetReplacementRequestMessageId(self, ticketId: int, messageId: int) -> bool:
        cursor = self.Execute(
            "UPDATE tickets SET replacement_request_message_id = ? "
            "WHERE ticket_id = ? AND status = 'open' AND replacement_requested = 1",
            (int(messageId), int(ticketId)),
        )
        return cursor.rowcount == 1

    def SetReplacementButtonMessageId(self, ticketId: int, messageId: int) -> bool:
        cursor = self.Execute(
            "UPDATE tickets SET replacement_button_message_id = ? "
            "WHERE ticket_id = ? AND status = 'open' AND replacement_requested = 0",
            (int(messageId), int(ticketId)),
        )
        return cursor.rowcount == 1

    def ApplyReplacementCandidates(self, ticketId: int, actorUserId: int, expectedCandidateIds: Iterable[int] | None = None) -> tuple[str, list[int], list[int]]:
        """Atomically apply exactly the candidates previously selected by the requester."""
        expected = list(dict.fromkeys(int(item) for item in expectedCandidateIds)) if expectedCandidateIds is not None else None
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", [], []
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", [], []
                if int(ticket["resolution_locked"] or 0) or str(ticket["resolution_type"] or "") in {"complete", "cancel"}:
                    self.connection.rollback()
                    return "processing", [], self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if int(ticket["replacement_requested"] or 0) != 1:
                    self.connection.rollback()
                    return "no_replacement_request", [], self._ParseIdCsv(str(ticket["active_helper_ids"]))
                candidates = self._ParseIdCsv(str(ticket["replacement_candidate_ids"] or ""))
                if not candidates:
                    self.connection.rollback()
                    return "no_candidates", [], self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if expected is not None and candidates != expected:
                    self.connection.rollback()
                    return "request_changed", candidates, self._ParseIdCsv(str(ticket["active_helper_ids"]))
                requesterId = int(ticket["creator_id"])
                originalIds = self._ParseIdCsv(str(ticket["helper_ids"]))
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if len(activeIds) != 1 or len(activeIds) + len(candidates) != len(originalIds):
                    self.connection.rollback()
                    return "not_eligible", candidates, activeIds
                if requesterId in candidates or set(candidates).intersection(activeIds) or set(candidates).intersection(originalIds):
                    self.connection.rollback()
                    return "invalid_candidates", candidates, activeIds
                newActiveIds = activeIds + candidates
                self.connection.execute(
                    "UPDATE tickets SET active_helper_ids = ?, replacement_requested = 0, replacement_candidate_ids = '', "
                    "replacement_request_message_id = NULL, replacement_button_message_id = NULL, "
                    "resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', "
                    "resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0 "
                    "WHERE ticket_id = ? AND status = 'open'",
                    (",".join(map(str, newActiveIds)), int(ticketId)),
                )
                for candidateId in candidates:
                    self._EnsureUserWithinTransaction(candidateId, self.GetDefaultJoinCredits())
                    self.connection.execute(
                        "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) "
                        "VALUES (?, NULL, ?, 0, 'helper_replacement', ?, ?)",
                        (int(ticketId), candidateId, int(actorUserId), "staff approved requester-selected replacement; reserved price unchanged"),
                    )
                self.connection.commit()
                return "added", candidates, newActiveIds
            except Exception:
                self.connection.rollback()
                raise

    def DisapproveReplacementRequest(self, ticketId: int, actorUserId: int) -> tuple[str, list[int]]:
        """Reject the selected replacement candidates without changing the active roster."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", []
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", []
                if int(ticket["replacement_requested"] or 0) != 1:
                    self.connection.rollback()
                    return "no_replacement_request", []
                candidates = self._ParseIdCsv(str(ticket["replacement_candidate_ids"] or ""))
                self.connection.execute(
                    "UPDATE tickets SET replacement_requested = 0, replacement_candidate_ids = '', "
                    "replacement_request_message_id = NULL, replacement_button_message_id = NULL "
                    "WHERE ticket_id = ? AND status = 'open'",
                    (int(ticketId),),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) "
                    "VALUES (?, NULL, NULL, 0, 'replacement_disapproved', ?, ?)",
                    (int(ticketId), int(actorUserId), "staff disapproved requester-selected replacement candidates: " + ",".join(map(str, candidates))),
                )
                self.connection.commit()
                return "disapproved", candidates
            except Exception:
                self.connection.rollback()
                raise

    # Legacy single-helper operation retained for earlier database tests and migration compatibility.
    def AddReplacementHelper(self, ticketId: int, helperId: int, actorUserId: int) -> tuple[str, list[int]]:
        """Add one staff-approved replacement using the pre-0.6.2 internal API."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", []
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", []
                if int(ticket["resolution_locked"] or 0):
                    self.connection.rollback()
                    return "processing", self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if int(ticket["replacement_requested"] or 0) != 1:
                    self.connection.rollback()
                    return "no_replacement_request", []
                creatorId = int(ticket["creator_id"])
                helperId = int(helperId)
                if helperId == creatorId:
                    self.connection.rollback()
                    return "requester_cannot_be_helper", []
                originalIds = self._ParseIdCsv(str(ticket["helper_ids"]))
                activeIds = self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if helperId in activeIds or helperId in originalIds:
                    self.connection.rollback()
                    return "already_active", activeIds
                if len(activeIds) >= len(originalIds):
                    self.connection.rollback()
                    return "roster_full", activeIds
                activeIds.append(helperId)
                replacementStillNeeded = int(len(activeIds) < len(originalIds))
                self.connection.execute(
                    "UPDATE tickets SET active_helper_ids = ?, replacement_requested = ?, replacement_candidate_ids = '', "
                    "replacement_request_message_id = NULL, replacement_button_message_id = NULL, "
                    "resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0 "
                    "WHERE ticket_id = ? AND status = 'open'",
                    (",".join(map(str, activeIds)), replacementStillNeeded, int(ticketId)),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, ?, 0, 'helper_replacement', ?, ?)",
                    (int(ticketId), helperId, int(actorUserId), "staff approved replacement helper; reserved price unchanged"),
                )
                self.connection.commit()
                return "added", activeIds
            except Exception:
                self.connection.rollback()
                raise

    def ListOpenTickets(self) -> list[sqlite3.Row]:
        return self.Execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY ticket_id", fetchAll=True)

    def CompleteTicket(
        self,
        ticketId: int,
        *,
        actorUserId: int | None = None,
        note: str | None = None,
    ) -> tuple[str, list[tuple[int, int]]]:
        """Complete an open ticket and pay helpers exactly once, atomically."""
        normalizedTicketId = int(ticketId)
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute(
                    "SELECT * FROM tickets WHERE ticket_id = ?", (normalizedTicketId,)
                ).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", []
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", []

                amount = int(ticket["reserved_credits"])
                activeHelperText = str(ticket["active_helper_ids"])
                helperIds = [
                    int(value) for value in activeHelperText.split(",") if value.strip()
                ]
                if (
                    amount < 0
                    or not helperIds
                    or int(ticket["creator_id"]) in helperIds
                    or len(set(helperIds)) != len(helperIds)
                ):
                    self.connection.rollback()
                    return "invalid_ticket", []

                stateUpdate = self.connection.execute(
                    """UPDATE tickets SET status = 'completed', completed_at = CURRENT_TIMESTAMP, resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0
                       WHERE ticket_id = ? AND status = 'open'""",
                    (normalizedTicketId,),
                )
                if stateUpdate.rowcount != 1:
                    self.connection.rollback()
                    return "not_open", []

                pricePerHelperValue = ticket["price_per_helper"] if "price_per_helper" in ticket.keys() else None
                defaultCredits = self.GetDefaultJoinCredits()
                payouts: list[tuple[int, int]] = []
                unusedHelperRefund = 0
                if pricePerHelperValue is not None:
                    pricePerHelper = int(pricePerHelperValue)
                    originalHelperIds = self._ParseIdCsv(str(ticket["helper_ids"] or ""))
                    # New tickets reserve a fixed per-helper unit price for each originally
                    # selected slot. Replacements fill slots without increasing the total.
                    # An unfilled slot is not paid out; its unit price is returned to requester.
                    if (
                        pricePerHelper < 0
                        or len(helperIds) > len(originalHelperIds)
                        or amount != pricePerHelper * len(originalHelperIds)
                    ):
                        self.connection.rollback()
                        return "invalid_ticket", []
                    totalPayout = pricePerHelper * len(helperIds)
                    unusedHelperRefund = amount - totalPayout
                    if unusedHelperRefund < 0:
                        self.connection.rollback()
                        return "invalid_ticket", []
                    payouts = [(helperId, pricePerHelper) for helperId in helperIds]
                else:
                    # Existing tickets are kept on the legacy fixed-total split policy.
                    payoutBase, payoutRemainder = divmod(amount, len(helperIds))
                    payouts = [
                        (helperId, payoutBase + (payoutRemainder if helperIndex == 0 else 0))
                        for helperIndex, helperId in enumerate(helperIds)
                    ]

                for helperId, payoutAmount in payouts:
                    self._ApplyRewardAgainstDebtWithinTransaction(
                        helperId, payoutAmount, actorUserId=actorUserId,
                        sourceNote=f"ticket reward for ticket {normalizedTicketId}",
                        ticketId=normalizedTicketId,
                    )
                    self.connection.execute(
                        """INSERT INTO transactions
                           (ticket_id, from_user, to_user, amount, type, actor_user_id, note)
                           VALUES (?, ?, ?, ?, 'ticket_reward', ?, ?)""",
                        (
                            normalizedTicketId,
                            int(ticket["creator_id"]),
                            helperId,
                            payoutAmount,
                            int(actorUserId) if actorUserId is not None else None,
                            (str(note).strip()[:500] if note and str(note).strip() else None),
                        ),
                    )

                if unusedHelperRefund:
                    creatorId = int(ticket["creator_id"])
                    self._EnsureUserWithinTransaction(creatorId, defaultCredits)
                    self.connection.execute(
                        "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                        (unusedHelperRefund, creatorId),
                    )
                    filledSlots = len(helperIds)
                    originalSlots = len(self._ParseIdCsv(str(ticket["helper_ids"] or "")))
                    self.connection.execute(
                        """INSERT INTO transactions
                           (ticket_id, from_user, to_user, amount, type, actor_user_id, note)
                           VALUES (?, NULL, ?, ?, 'unused_helper_refund', ?, ?)""",
                        (
                            normalizedTicketId,
                            creatorId,
                            unusedHelperRefund,
                            int(actorUserId) if actorUserId is not None else None,
                            f"refund for {originalSlots - filledSlots} unfilled helper slot(s) at completion",
                        ),
                    )

                self.connection.commit()
                return "completed", payouts
            except Exception:
                self.connection.rollback()
                raise

    def RefundTicket(
        self,
        ticketId: int,
        *,
        actorUserId: int | None = None,
        note: str | None = None,
    ) -> tuple[str, int | None]:
        """Refund the requester's reservation exactly once, atomically."""
        normalizedTicketId = int(ticketId)
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                ticket = self.connection.execute(
                    "SELECT * FROM tickets WHERE ticket_id = ?", (normalizedTicketId,)
                ).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", None
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", None

                amount = int(ticket["reserved_credits"])
                if amount < 0:
                    self.connection.rollback()
                    return "invalid_ticket", None

                stateUpdate = self.connection.execute(
                    """UPDATE tickets SET status = 'refunded', completed_at = CURRENT_TIMESTAMP, resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0
                       WHERE ticket_id = ? AND status = 'open'""",
                    (normalizedTicketId,),
                )
                if stateUpdate.rowcount != 1:
                    self.connection.rollback()
                    return "not_open", None

                creatorId = int(ticket["creator_id"])
                self._EnsureUserWithinTransaction(creatorId, self.GetDefaultJoinCredits())
                self.connection.execute(
                    "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                    (amount, creatorId),
                )
                self.connection.execute(
                    """INSERT INTO transactions
                       (ticket_id, from_user, to_user, amount, type, actor_user_id, note)
                       VALUES (?, NULL, ?, ?, 'refund', ?, ?)""",
                    (
                        normalizedTicketId,
                        creatorId,
                        amount,
                        int(actorUserId) if actorUserId is not None else None,
                        (str(note).strip()[:500] if note and str(note).strip() else None),
                    ),
                )
                self.connection.commit()
                return "refunded", amount
            except Exception:
                self.connection.rollback()
                raise

    def GetCompletionRefundAmount(self, ticketId: int) -> int:
        """Return any unused-helper-slot refund generated during completion."""
        row = self.Execute(
            "SELECT COALESCE(SUM(amount), 0) AS refund_amount FROM transactions "
            "WHERE ticket_id = ? AND type = 'unused_helper_refund'",
            (int(ticketId),),
            fetchOne=True,
        )
        return int(row["refund_amount"] or 0) if row else 0

    # ----- Audit routing, ticket history, reports, and invite reward events -----

    def SetTicketTranscriptMessage(self, ticketId: int, channelId: int, messageId: int) -> None:
        self.Execute(
            "UPDATE tickets SET transcript_channel_id = ?, transcript_message_id = ?, transcript_saved = 1 WHERE ticket_id = ?",
            (int(channelId), int(messageId), int(ticketId)),
        )

    def ClearTicketTranscriptMessage(self, ticketId: int) -> None:
        # Clear only the live Discord message pointer. transcript_saved records
        # that this ticket once had a successfully stored transcript and remains
        # true when the Discord post is pruned by retention.
        self.Execute(
            "UPDATE tickets SET transcript_channel_id = NULL, transcript_message_id = NULL WHERE ticket_id = ?",
            (int(ticketId),),
        )

    def PruneTicketHistory(self, maxRecords: int = 500) -> int:
        """Keep only the newest ``maxRecords`` closed tickets with saved transcripts.

        Open tickets are never pruned. Closed records whose transcript was never
        confirmed are also retained for recovery. Transactions associated with
        removed ticket-history rows are deleted first to satisfy the database
        foreign key; user balances and standalone credit adjustments are kept.
        Returns the number of ticket rows removed.
        """
        safeLimit = max(1, min(5000, int(maxRecords)))
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                if self.backend == "sqlite":
                    candidateSql = (
                        "SELECT ticket_id FROM tickets "
                        "WHERE status <> 'open' AND transcript_saved = 1 "
                        "ORDER BY ticket_id DESC LIMIT -1 OFFSET ?"
                    )
                else:
                    candidateSql = (
                        "SELECT ticket_id FROM tickets "
                        "WHERE status <> 'open' AND transcript_saved = 1 "
                        "ORDER BY ticket_id DESC OFFSET ?"
                    )
                rows = self.connection.execute(candidateSql, (safeLimit,)).fetchall()
                ticketIds = [int(row["ticket_id"]) for row in rows]
                for start in range(0, len(ticketIds), 400):
                    batch = ticketIds[start:start + 400]
                    placeholders = ",".join("?" for _ in batch)
                    params = tuple(batch)
                    self.connection.execute(
                        f"DELETE FROM transactions WHERE ticket_id IN ({placeholders})", params
                    )
                    self.connection.execute(
                        f"DELETE FROM tickets WHERE ticket_id IN ({placeholders}) "
                        "AND status <> 'open' AND transcript_saved = 1", params
                    )
                self.connection.commit()
                return len(ticketIds)
            except Exception:
                self.connection.rollback()
                raise

    def GetServerStatistics(self) -> dict[str, Any]:
        """Return read-only aggregate metrics for the current server."""
        memberRow = self.Execute(
            """SELECT COUNT(*) AS tracked_members,
                      COALESCE(SUM(credits), 0) AS available_credits
               FROM users""",
            fetchOne=True,
        )
        debtRow = self.Execute(
            """SELECT COUNT(*) AS debtors,
                      COALESCE(SUM(amount), 0) AS outstanding_debt
               FROM credit_debts
               WHERE amount > 0""",
            fetchOne=True,
        )
        ticketRows = self.Execute(
            "SELECT status, COUNT(*) AS amount FROM tickets GROUP BY status",
            fetchAll=True,
        )
        reportRows = self.Execute(
            "SELECT status, COUNT(*) AS amount FROM scam_reports GROUP BY status",
            fetchAll=True,
        )
        ledgerRow = self.Execute(
            "SELECT COUNT(*) AS amount FROM transactions",
            fetchOne=True,
        )
        inviteRewardRow = self.Execute(
            """SELECT COUNT(*) AS amount,
                      COALESCE(SUM(reward_credits), 0) AS credits
               FROM invite_rewards""",
            fetchOne=True,
        )
        serviceRow = self.Execute(
            "SELECT COUNT(*) AS amount FROM services WHERE active = 1",
            fetchOne=True,
        )
        return {
            "tracked_members": int(memberRow["tracked_members"] or 0),
            "available_credits": int(memberRow["available_credits"] or 0),
            "debtors": int(debtRow["debtors"] or 0),
            "outstanding_debt": int(debtRow["outstanding_debt"] or 0),
            "ticket_statuses": {
                str(row["status"]): int(row["amount"]) for row in ticketRows
            },
            "report_statuses": {
                str(row["status"]): int(row["amount"]) for row in reportRows
            },
            "ledger_entries": int(ledgerRow["amount"] or 0),
            "invite_reward_count": int(inviteRewardRow["amount"] or 0),
            "invite_reward_credits": int(inviteRewardRow["credits"] or 0),
            "enabled_services": int(serviceRow["amount"] or 0),
            "active_invite_event": self.GetActiveInviteEvent() is not None,
        }

    def GetMemberActivitySummary(
        self,
        userId: int,
        *,
        recentTransactionLimit: int = 5,
        recentTicketLimit: int = 3,
    ) -> dict[str, Any]:
        """Return read-only member balances and retained activity without creating an account."""
        normalizedId = int(userId)
        token = str(normalizedId)
        ticketConditions = """creator_id = ?
            OR (',' || helper_ids || ',') LIKE ('%%,' || ? || ',%%')
            OR (',' || active_helper_ids || ',') LIKE ('%%,' || ? || ',%%')
            OR (',' || replacement_candidate_ids || ',') LIKE ('%%,' || ? || ',%%')"""
        ticketCounts = self.Execute(
            f"""SELECT COUNT(*) AS total_tickets,
                       COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0) AS open_tickets
                FROM tickets
                WHERE {ticketConditions}""",
            (normalizedId, token, token, token),
            fetchOne=True,
        )
        transactionCount = self.Execute(
            "SELECT COUNT(*) AS amount FROM transactions WHERE from_user = ? OR to_user = ?",
            (normalizedId, normalizedId),
            fetchOne=True,
        )
        account = self.GetUser(normalizedId)
        return {
            "user_id": normalizedId,
            "account": account,
            "available_credits": int(account["credits"]) if account is not None else None,
            "outstanding_debt": self.GetCreditDebt(normalizedId),
            "transaction_count": int(transactionCount["amount"] or 0),
            "ticket_count": int(ticketCounts["total_tickets"] or 0),
            "open_ticket_count": int(ticketCounts["open_tickets"] or 0),
            "recent_transactions": self.ListCreditTransactions(
                normalizedId, limit=max(1, min(10, int(recentTransactionLimit)))
            ),
            "recent_tickets": self.ListTicketHistoryForMember(
                normalizedId, limit=max(1, min(10, int(recentTicketLimit)))
            ),
        }

    def ListTicketHistoryForMember(
        self, userId: int, limit: int = 10, *, offset: int = 0
    ) -> list[sqlite3.Row]:
        """Return newest-first retained ticket history with bounded pagination."""
        normalizedId = int(userId)
        safeLimit = max(1, min(25, int(limit)))
        safeOffset = max(0, int(offset))
        token = str(normalizedId)
        return self.Execute(
            """SELECT * FROM tickets
               WHERE creator_id = ?
                  OR (',' || helper_ids || ',') LIKE ('%%,' || ? || ',%%')
                  OR (',' || active_helper_ids || ',') LIKE ('%%,' || ? || ',%%')
                  OR (',' || replacement_candidate_ids || ',') LIKE ('%%,' || ? || ',%%')
               ORDER BY ticket_id DESC LIMIT ? OFFSET ?""",
            (normalizedId, token, token, token, safeLimit, safeOffset), fetchAll=True,
        )

    def CreateScamReport(
        self,
        reporterUserId: int,
        reportedUserId: int | None,
        details: str,
        *,
        reportType: str = "scam",
    ) -> int:
        """Store a general moderation report; 0 as reported_user_id means no specific member."""
        details = str(details).strip()[:3000]
        if not details:
            raise ValueError("Report details cannot be empty.")
        normalizedReporterId = int(reporterUserId)
        normalizedReportedId = int(reportedUserId or 0)
        normalizedType = str(reportType).strip().lower()
        validTypes = {"scam", "bug", "ticket_credit", "member_behavior", "other"}
        if normalizedType not in validTypes:
            raise ValueError("Choose a valid report category.")
        if normalizedReportedId < 0:
            raise ValueError("Reported member ID cannot be negative.")
        if normalizedReportedId and normalizedReporterId == normalizedReportedId:
            raise ValueError("You cannot report yourself.")
        with self.databaseLock:
            reportSql = (
                "INSERT INTO scam_reports(reporter_user_id, reported_user_id, report_type, details) "
                "VALUES (?, ?, ?, ?)"
            )
            if self.backend == "postgresql":
                reportSql += " RETURNING report_id"
            cursor = self.connection.execute(
                reportSql,
                (normalizedReporterId, normalizedReportedId, normalizedType, details),
            )
            reportId = int(cursor.fetchone()["report_id"]) if self.backend == "postgresql" else int(cursor.lastrowid)
            self.connection.commit()
            return reportId

    def ListScamReports(
        self, *, status: str | None = "open", limit: int = 10,
        reportType: str | None = None, offset: int = 0,
    ):
        """List reports with bounded pagination and an optional category filter."""
        safeLimit = max(1, min(25, int(limit)))
        safeOffset = max(0, int(offset))
        conditions = []
        parameters = []
        if status is not None and status != "all":
            conditions.append("status = ?")
            parameters.append(str(status))
        if reportType is not None and reportType != "all":
            conditions.append("report_type = ?")
            parameters.append(str(reportType))
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        parameters.extend((safeLimit, safeOffset))
        return self.Execute(
            f"SELECT * FROM scam_reports{where} ORDER BY report_id DESC LIMIT ? OFFSET ?",
            tuple(parameters), fetchAll=True,
        )

    def ResolveScamReport(self, reportId: int, reviewedBy: int, decision: str, note: str = "") -> bool:
        normalizedDecision = str(decision).strip().lower()
        if normalizedDecision not in {"confirmed", "dismissed"}:
            raise ValueError("decision must be 'confirmed' or 'dismissed'.")
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                cursor = self.connection.execute(
                    "UPDATE scam_reports SET status = ?, reviewed_by = ?, review_note = ? "
                    "WHERE report_id = ? AND status = 'open'",
                    (normalizedDecision, int(reviewedBy), str(note).strip()[:1000] or None, int(reportId)),
                )
                self.connection.commit()
                return cursor.rowcount == 1
            except Exception:
                self.connection.rollback()
                raise

    def StartInviteEvent(self, rewardCredits: int, durationMinutes: int | None, startedBy: int) -> tuple[str, int | None, str | None]:
        import datetime as _datetime
        reward = int(rewardCredits)
        infinite = durationMinutes is None
        duration = 10_080 if infinite else int(durationMinutes)
        if reward < 0 or reward > 1_000_000_000:
            raise ValueError("Reward must be between 0 and 1,000,000,000 credits.")
        if not infinite and not 1 <= duration <= 10_080:
            raise ValueError("Duration must be between 1 minute and 7 days.")
        now = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0)
        startsAt = now.isoformat()
        # Keep the existing non-null schema compatible across SQLite and PostgreSQL.
        # Infinite events use a far-future end marker and are still manually endable.
        endsAt = "9999-12-31T23:59:59+00:00" if infinite else (now + _datetime.timedelta(minutes=duration)).isoformat()
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                active = self.connection.execute(
                    "SELECT event_id FROM invite_events WHERE status = 'active' LIMIT 1"
                ).fetchone()
                if active is not None:
                    self.connection.rollback()
                    return "already_active", int(active["event_id"]), None
                eventSql = "INSERT INTO invite_events(reward_credits, duration_minutes, starts_at, ends_at, status, started_by) VALUES (?, ?, ?, ?, 'active', ?)"
                if self.backend == "postgresql":
                    eventSql += " RETURNING event_id"
                cursor = self.connection.execute(eventSql, (reward, duration, startsAt, endsAt, int(startedBy)))
                eventId = int(cursor.fetchone()["event_id"]) if self.backend == "postgresql" else int(cursor.lastrowid)
                for settingKey, settingValue in (
                    ("invite_reward_credits", str(reward)),
                    ("invite_duration_minutes", str(duration)),
                ):
                    self.connection.execute(
                        """INSERT INTO settings(setting_key, setting_value, updated_at)
                           VALUES (?, ?, CURRENT_TIMESTAMP)
                           ON CONFLICT(setting_key) DO UPDATE SET
                             setting_value = excluded.setting_value,
                             updated_at = CURRENT_TIMESTAMP""",
                        (settingKey, settingValue),
                    )
                self.connection.commit()
                return "started", eventId, None if infinite else endsAt
            except Exception:
                self.connection.rollback()
                raise

    def GetActiveInviteEvent(self):
        return self.Execute(
            "SELECT * FROM invite_events WHERE status = 'active' ORDER BY event_id DESC LIMIT 1",
            fetchOne=True,
        )

    def EndInviteEvent(self, endedBy: int | None = None, *, expired: bool = False) -> tuple[str, object | None]:
        import datetime as _datetime
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                event = self.connection.execute(
                    "SELECT * FROM invite_events WHERE status = 'active' ORDER BY event_id DESC LIMIT 1"
                ).fetchone()
                if event is None:
                    self.connection.rollback()
                    return "none_active", None
                status = "expired" if expired else "ended"
                endedAt = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat()
                self.connection.execute(
                    "UPDATE invite_events SET status = ?, ended_by = ?, ended_at = ? WHERE event_id = ? AND status = 'active'",
                    (status, int(endedBy) if endedBy is not None else None, endedAt, int(event["event_id"])),
                )
                self.connection.commit()
                # Return an immutable-friendly copy for callers after the commit.
                return status, dict(event)
            except Exception:
                self.connection.rollback()
                raise

    def ExpireInviteEventIfDue(self) -> object | None:
        import datetime as _datetime
        nowText = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat()
        event = self.GetActiveInviteEvent()
        if event is None or str(event["ends_at"]) > nowText:
            return None
        status, ended = self.EndInviteEvent(expired=True)
        return ended if status == "expired" else None

    def AwardInviteReward(self, eventId: int, invitedUserId: int, inviterUserId: int, inviteCode: str) -> tuple[str, int | None, int]:
        """Atomically award an inviter once per invite event / joining member."""
        import datetime as _datetime
        nowText = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat()
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE" if self.backend == "sqlite" else "BEGIN")
            try:
                event = self.connection.execute(
                    "SELECT * FROM invite_events WHERE event_id = ? AND status = 'active'",
                    (int(eventId),),
                ).fetchone()
                if event is None or str(event["ends_at"]) <= nowText:
                    self.connection.rollback()
                    return "inactive", None, 0
                if int(invitedUserId) == int(inviterUserId):
                    self.connection.rollback()
                    return "self_invite", None, 0
                reward = int(event["reward_credits"])
                self._EnsureUserWithinTransaction(int(inviterUserId), self.GetDefaultJoinCredits())
                self._EnsureUserWithinTransaction(int(invitedUserId), self.GetDefaultJoinCredits())
                cursor = self.connection.execute(
                    """INSERT INTO invite_rewards(event_id, invited_user_id, inviter_user_id, invite_code, reward_credits)
                       VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_id, invited_user_id) DO NOTHING""",
                    (int(eventId), int(invitedUserId), int(inviterUserId), str(inviteCode)[:100], reward),
                )
                if cursor.rowcount != 1:
                    self.connection.rollback()
                    return "duplicate", None, reward
                self._ApplyRewardAgainstDebtWithinTransaction(
                    int(inviterUserId), reward,
                    sourceNote=f"invite event #{int(eventId)} reward",
                )
                self.connection.execute(
                    """INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note)
                       VALUES (NULL, NULL, ?, ?, 'invite_reward', NULL, ?)""",
                    (int(inviterUserId), reward, f"Invite event #{int(eventId)}: invited member {int(invitedUserId)} via {str(inviteCode)[:80]}"),
                )
                row = self.connection.execute(
                    "SELECT credits FROM users WHERE user_id = ?", (int(inviterUserId),)
                ).fetchone()
                balance = int(row["credits"])
                self.connection.commit()
                return "awarded", balance, reward
            except Exception:
                self.connection.rollback()
                raise

    def Close(self) -> None:
        with self.databaseLock:
            self.connection.close()
