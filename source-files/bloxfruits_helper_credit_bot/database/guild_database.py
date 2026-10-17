"""SQLite storage belonging to one Discord server (guild)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Iterable


class GuildDatabase:
    """One isolated SQLite database, intended for exactly one Discord guild."""

    def __init__(
        self,
        path: str | Path,
        guildId: int,
        defaultJoinCredits: int = 100,
        defaultServices: Iterable[tuple[str, str, int]] = (),
    ) -> None:
        self.databasePath = Path(path)
        self.guildId = int(guildId)
        self.databasePath.parent.mkdir(parents=True, exist_ok=True)
        self.databaseLock = RLock()
        self.connection = sqlite3.connect(
            str(self.databasePath),
            timeout=15,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        with self.databaseLock:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA busy_timeout = 15000")
            self.connection.execute("PRAGMA journal_mode = WAL")
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
                completed_at TEXT
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
        )
        with self.databaseLock, self.connection:
            for statement in schema:
                self.connection.execute(statement)
            # Add the numbered-ticket column to databases created before this feature.
            ticketColumns = {
                str(row["name"])
                for row in self.connection.execute("PRAGMA table_info(tickets)").fetchall()
            }
            if "ticket_number" not in ticketColumns:
                self.connection.execute("ALTER TABLE tickets ADD COLUMN ticket_number INTEGER")

            ticketMigrations = {
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
            }
            for columnName, migrationSql in ticketMigrations.items():
                if columnName not in ticketColumns:
                    self.connection.execute(migrationSql)
            # For legacy pending proposals, requester intent is the first approval.
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
            transactionColumns = {
                str(row["name"])
                for row in self.connection.execute("PRAGMA table_info(transactions)").fetchall()
            }
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
                # A number can be reused after all tickets close, but two currently
                # open tickets in the same guild must never share a number.
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_tickets_open_number "
                "ON tickets(ticket_number) WHERE status = 'open' AND ticket_number IS NOT NULL",
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
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                created = self._EnsureUserWithinTransaction(int(userId), int(credits))
                self.connection.commit()
                return created
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
            self.connection.execute("BEGIN IMMEDIATE")
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

    def _AllocateTicketNumberWithinTransaction(self) -> int:
        """Allocate a channel number; restart at 001 only when no tickets are open.

        Caller must hold databaseLock and have an active SQLite write transaction.
        The persisted next number prevents reusing a closed number while another
        ticket in the current active batch is still open.
        """
        openCountRow = self.connection.execute(
            "SELECT COUNT(*) AS ticket_count FROM tickets WHERE status = 'open'"
        ).fetchone()
        openCount = int(openCountRow["ticket_count"])

        if openCount == 0:
            ticketNumber = 1
        else:
            nextRow = self.connection.execute(
                "SELECT setting_value FROM settings WHERE setting_key = 'next_ticket_number'"
            ).fetchone()
            try:
                configuredNext = int(nextRow["setting_value"]) if nextRow else 1
            except (TypeError, ValueError):
                configuredNext = 1

            maxRow = self.connection.execute(
                "SELECT MAX(ticket_number) AS max_number FROM tickets "
                "WHERE status = 'open'"
            ).fetchone()
            maxOpenNumber = int(maxRow["max_number"] or 0)
            # Legacy username-based tickets may have NULL ticket_number values.
            # They do not occupy a numbered channel name, so don't skip 001 solely
            # because an old, unnumbered ticket is still open.
            ticketNumber = max(configuredNext, maxOpenNumber + 1)

        self.connection.execute(
            """INSERT INTO settings(setting_key, setting_value, updated_at)
               VALUES ('next_ticket_number', ?, CURRENT_TIMESTAMP)
               ON CONFLICT(setting_key) DO UPDATE SET
                 setting_value = excluded.setting_value,
                 updated_at = CURRENT_TIMESTAMP""",
            (str(ticketNumber + 1),),
        )
        return ticketNumber

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
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                defaultCredits = self.GetDefaultJoinCredits()
                self._EnsureUserWithinTransaction(normalizedCreatorId, defaultCredits)
                for helperId in helpers:
                    self._EnsureUserWithinTransaction(helperId, defaultCredits)
                reservation = self.connection.execute(
                    "UPDATE users SET credits = credits - ? "
                    "WHERE user_id = ? AND credits >= ?",
                    (amount, normalizedCreatorId, amount),
                )
                if reservation.rowcount != 1:
                    self.connection.rollback()
                    return None

                ticketNumber = self._AllocateTicketNumberWithinTransaction()
                ticketCursor = self.connection.execute(
                    """INSERT INTO tickets
                       (ticket_number, channel_id, guild_id, creator_id, event_key, helper_ids,
                        active_helper_ids, required_credits, reserved_credits, price_per_helper, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
                    (
                        ticketNumber,
                        normalizedChannelId,
                        self.guildId,
                        normalizedCreatorId,
                        normalizedEventKey,
                        ",".join(map(str, helpers)),
                        ",".join(map(str, helpers)),
                        amount,
                        amount,
                        normalizedUnitPrice,
                    ),
                )
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

    def RequestTicketResolution(self, ticketId: int, resolutionType: str, requesterId: int) -> tuple[str, list[int]]:
        """Record a requester-proposed completion/cancellation awaiting active helper confirmations."""
        if resolutionType not in {"complete", "cancel"}:
            raise ValueError("resolutionType must be 'complete' or 'cancel'")
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                ticket = self.connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (int(ticketId),)).fetchone()
                if ticket is None:
                    self.connection.rollback()
                    return "not_found", []
                if ticket["status"] != "open":
                    self.connection.rollback()
                    return "not_open", []
                if int(ticket["creator_id"]) != int(requesterId):
                    self.connection.rollback()
                    return "not_requester", []
                if int(ticket["resolution_locked"] or 0):
                    self.connection.rollback()
                    return "processing", []
                if int(ticket["replacement_requested"] or 0):
                    self.connection.rollback()
                    return "replacement_pending", self._ParseIdCsv(str(ticket["active_helper_ids"]))
                if str(ticket["resolution_type"] or "") in {"complete", "cancel"}:
                    self.connection.rollback()
                    return "existing_request", self._ParseIdCsv(str(ticket["active_helper_ids"]))
                activeText = str(ticket["active_helper_ids"])
                activeIds = self._ParseIdCsv(activeText)
                if not activeIds:
                    self.connection.rollback()
                    return "no_active_helpers", []
                self.connection.execute(
                    "UPDATE tickets SET resolution_type = ?, resolution_requested_by = ?, resolution_confirmations = ?, resolution_requested_at = CURRENT_TIMESTAMP, resolution_message_id = NULL, resolution_locked = 0 WHERE ticket_id = ? AND status = 'open'",
                    (resolutionType, int(requesterId), str(int(requesterId)), int(ticketId)),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, ?, ?, ?)",
                    (int(ticketId), "ticket_completion_requested" if resolutionType == "complete" else "ticket_cancellation_requested", int(requesterId), f"requester proposed {resolutionType}; requester counts as first approval and all active helpers must confirm"),
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
        """Record one active helper approval; requester intent counts as the first approval."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE")
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
                if int(ticket["resolution_locked"] or 0):
                    confirmations = self._ParseIdCsv(str(ticket["resolution_confirmations"] or ""))
                    self.connection.rollback()
                    return ("duplicate" if int(helperId) in confirmations else "processing"), len(set(confirmations) & set(requiredIds)), requiredCount, resolutionType
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
                if int(helperId) not in activeIds:
                    self.connection.rollback()
                    return "not_active_helper", 0, requiredCount, resolutionType
                confirmations = self._ParseIdCsv(str(ticket["resolution_confirmations"] or ""))
                if requesterId not in confirmations:
                    confirmations.insert(0, requesterId)
                if int(helperId) in confirmations:
                    self.connection.rollback()
                    return "duplicate", len(set(confirmations) & set(requiredIds)), requiredCount, resolutionType
                confirmations.append(int(helperId))
                isReady = set(confirmations) >= set(requiredIds)
                self.connection.execute(
                    "UPDATE tickets SET resolution_confirmations = ?, resolution_locked = ? WHERE ticket_id = ? AND status = 'open'",
                    (",".join(map(str, confirmations)), 1 if isReady else 0, int(ticketId)),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, 'helper_confirmation', ?, ?)",
                    (int(ticketId), int(helperId), f"helper confirmed proposed {resolutionType}"),
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
            self.connection.execute("BEGIN IMMEDIATE")
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
        """Allow an active helper to reject a proposal; staff override remains available."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE")
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
                if int(helperId) not in activeIds:
                    self.connection.rollback()
                    return "not_active_helper", resolutionType
                self.connection.execute(
                    "UPDATE tickets SET resolution_type = '', resolution_requested_by = NULL, resolution_confirmations = '', resolution_requested_at = NULL, resolution_message_id = NULL, resolution_locked = 0 WHERE ticket_id = ? AND status = 'open'",
                    (int(ticketId),),
                )
                self.connection.execute(
                    "INSERT INTO transactions(ticket_id, from_user, to_user, amount, type, actor_user_id, note) VALUES (?, NULL, NULL, 0, 'helper_rejected_resolution', ?, ?)",
                    (int(ticketId), int(helperId), f"helper rejected proposed {resolutionType}"),
                )
                self.connection.commit()
                return "rejected", resolutionType
            except Exception:
                self.connection.rollback()
                raise

    def LeaveTicketHelper(self, ticketId: int, helperId: int) -> tuple[str, list[int], int]:
        """Remove an active helper from the roster and audit the departure."""
        with self.databaseLock:
            self.connection.execute("BEGIN IMMEDIATE")
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
            self.connection.execute("BEGIN IMMEDIATE")
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
            self.connection.execute("BEGIN IMMEDIATE")
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
            self.connection.execute("BEGIN IMMEDIATE")
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
            self.connection.execute("BEGIN IMMEDIATE")
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
            self.connection.execute("BEGIN IMMEDIATE")
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
            self.connection.execute("BEGIN IMMEDIATE")
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
                    self._EnsureUserWithinTransaction(helperId, defaultCredits)
                    self.connection.execute(
                        "UPDATE users SET credits = credits + ? WHERE user_id = ?",
                        (payoutAmount, helperId),
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
            self.connection.execute("BEGIN IMMEDIATE")
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

    def Close(self) -> None:
        with self.databaseLock:
            self.connection.close()
