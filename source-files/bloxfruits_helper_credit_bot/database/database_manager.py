"""Resolve and cache one persistent SQLite database per Discord server."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Iterable

from .guild_database import GuildDatabase

DATABASE_DIRECTORY_NAME = "servers"
DATABASE_FILE_NAME = "blox_fruits_credit_system.sqlite3"
LEGACY_DIRECTORY_NAME = "guilds"
LEGACY_DATABASE_FILE_NAME = "guild.sqlite3"


class DatabaseManager:
    """Lazily open one isolated database per Discord server.

    ``dataDir`` is the project-level ``data`` directory. The current layout is
    ``data/servers/<server_id>/blox_fruits_credit_system.sqlite3``.
    Previous ``data/guilds/<server_id>/guild.sqlite3`` databases are migrated
    with SQLite's backup API on first access. The old directory is retained as
    a dated archive; it is never silently deleted.
    """

    def __init__(
        self,
        dataDir: str | Path,
        defaultJoinCredits: int = 100,
        defaultServices: Iterable[tuple[str, str, int]] = (),
    ) -> None:
        self.dataDir = Path(dataDir)
        self.defaultJoinCredits = max(0, int(defaultJoinCredits))
        self.defaultServices = tuple(defaultServices)
        self._serverDatabases: dict[int, GuildDatabase] = {}
        self._databaseLock = RLock()

    def GetServerDatabasePath(self, serverId: int) -> Path:
        """Return the current database file path for a server ID."""
        normalizedId = int(serverId)
        if normalizedId <= 0:
            raise ValueError("Server ID must be a positive integer.")
        return (
            self.dataDir
            / DATABASE_DIRECTORY_NAME
            / str(normalizedId)
            / DATABASE_FILE_NAME
        )

    def _MigrateLegacyDatabase(self, serverId: int, destinationPath: Path) -> None:
        legacyDirectory = self.dataDir / LEGACY_DIRECTORY_NAME / str(serverId)
        legacyPath = legacyDirectory / LEGACY_DATABASE_FILE_NAME
        if not legacyPath.is_file():
            return

        if destinationPath.exists():
            raise RuntimeError(
                "Both the new server database and the old guild database exist for "
                f"server {serverId}. Nothing was overwritten. Stop the bot and compare "
                f"'{destinationPath}' with '{legacyPath}' before continuing."
            )

        archiveRoot = self.dataDir / "legacy-database-archives"
        archiveRoot.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        archiveDirectory = archiveRoot / f"server-{serverId}-{timestamp}"
        destinationPath.parent.mkdir(parents=True, exist_ok=True)

        # Move the whole legacy folder first so any SQLite WAL/SHM files travel
        # with the main database. If archive preparation fails, the original path
        # remains intact and bot startup stops rather than creating empty data.
        legacyDirectory.rename(archiveDirectory)
        archivedDatabasePath = archiveDirectory / LEGACY_DATABASE_FILE_NAME
        sourceConnection = None
        destinationConnection = None
        try:
            sourceConnection = sqlite3.connect(str(archivedDatabasePath), timeout=15)
            destinationConnection = sqlite3.connect(str(destinationPath), timeout=15)
            sourceConnection.backup(destinationConnection)
            integrity = destinationConnection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise sqlite3.DatabaseError(
                    f"Migrated database failed integrity_check: {integrity!r}"
                )
        except Exception:
            # Remove any incomplete destination, then restore the old folder to
            # its expected legacy location so a future launch cannot seed an
            # empty database after a failed migration.
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(str(destinationPath) + suffix)
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass
            if legacyDirectory.exists():
                # Keep both copies safe if an unexpected path collision occurred.
                raise RuntimeError(
                    f"Migration failed for server {serverId}; original remains archived at "
                    f"{archiveDirectory}. Inspect it before restarting."
                )
            archiveDirectory.rename(legacyDirectory)
            raise
        finally:
            if destinationConnection is not None:
                destinationConnection.close()
            if sourceConnection is not None:
                sourceConnection.close()

        print(
            f"[Database] Migrated existing data for server {serverId} to "
            f"{destinationPath}. Original preserved at {archiveDirectory}"
        )

    def ForServer(self, serverId: int | None) -> GuildDatabase:
        """Return the isolated database for a Discord server."""
        if serverId is None:
            raise ValueError("A Discord server ID is required for database access.")
        normalizedId = int(serverId)
        if normalizedId <= 0:
            raise ValueError("Server ID must be a positive integer.")

        with self._databaseLock:
            database = self._serverDatabases.get(normalizedId)
            if database is None:
                databasePath = self.GetServerDatabasePath(normalizedId)
                self._MigrateLegacyDatabase(normalizedId, databasePath)
                database = GuildDatabase(
                    path=databasePath,
                    guildId=normalizedId,
                    defaultJoinCredits=self.defaultJoinCredits,
                    defaultServices=self.defaultServices,
                )
                self._serverDatabases[normalizedId] = database
                print(f"[Database] Ready for server {normalizedId}: {databasePath}")
            return database

    def ForGuild(self, guildId: int | None) -> GuildDatabase:
        """Compatibility alias for older modules; prefer ``ForServer``."""
        return self.ForServer(guildId)

    def CloseAll(self) -> None:
        """Close all open SQLite connections cleanly."""
        with self._databaseLock:
            for database in self._serverDatabases.values():
                database.Close()
            self._serverDatabases.clear()
