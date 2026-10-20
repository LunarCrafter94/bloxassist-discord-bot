"""Per-server encrypted database ZIP backups delivered to one Discord DM.

SQLite snapshots use sqlite3.Connection.backup(), which accounts for WAL data.
PostgreSQL snapshots use a read-only repeatable-read transaction and export JSON
rows per server schema. Backups are separate per server, never one archive of all data/.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord

logger = logging.getLogger(__name__)


class PerServerBackupService:
    def __init__(self, databaseManager, *, recipientUserId: int | None, encryptionPassword: str):
        self.databaseManager = databaseManager
        self.recipientUserId = int(recipientUserId) if recipientUserId else None
        self.encryptionPassword = str(encryptionPassword or "")
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.recipientUserId and self.encryptionPassword)

    async def HourlyLoop(self, bot: discord.Client) -> None:
        await bot.wait_until_ready()
        # Startup snapshot, then once per hour. Do not overlap prior runs.
        while not bot.is_closed():
            try:
                await self.BackupAllServers(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Per-server backup cycle failed")
            await asyncio.sleep(3600)

    async def BackupAllServers(self, bot: discord.Client) -> int:
        if not self.enabled:
            logger.warning("Per-server backup skipped: recipient ID or encryption password is not configured")
            return 0
        try:
            import pyzipper
        except ImportError:
            logger.error("Per-server backup disabled because pyzipper is not installed")
            return 0
        async with self._lock:
            try:
                recipient = await bot.fetch_user(self.recipientUserId)
            except discord.HTTPException:
                logger.exception("Could not resolve configured Discord backup recipient")
                return 0
            # Ensure every guild is opened even if on_ready() has not yet finished
            # restoring its panels when the backup task wakes up.
            for guild in list(getattr(bot, "guilds", ())):
                try:
                    self.databaseManager.ForServer(guild.id)
                except Exception:
                    logger.exception("Could not initialize a server database before backup: guild=%s", guild.id)
            databaseItems = list(self.databaseManager._serverDatabases.items())
            successful = 0
            for serverId, database in databaseItems:
                try:
                    with tempfile.TemporaryDirectory(prefix=f"bfbackup-{serverId}-") as tempDir:
                        tempRoot = Path(tempDir)
                        zipPath = tempRoot / f"server-{serverId}-backup.zip"
                        manifest = self._BuildManifest(serverId, database)
                        payloads = await asyncio.to_thread(self._SnapshotPayloads, database, tempRoot)
                        with pyzipper.AESZipFile(
                            zipPath, "w", compression=pyzipper.ZIP_DEFLATED,
                            encryption=pyzipper.WZ_AES,
                        ) as archive:
                            archive.setpassword(self.encryptionPassword.encode("utf-8"))
                            archive.setencryption(pyzipper.WZ_AES, nbits=256)
                            archive.writestr("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
                            for archiveName, payloadPath in payloads:
                                archive.write(payloadPath, arcname=archiveName)
                        if zipPath.stat().st_size > 8_000_000:
                            raise RuntimeError(
                                f"Encrypted backup is {zipPath.stat().st_size} bytes; it exceeds the conservative 8 MB Discord upload safety threshold."
                            )
                        created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                        await recipient.send(
                            content=(
                                f"🔐 **Encrypted database backup — server `{serverId}`**\n"
                                f"Created: {created}\n"
                                "This ZIP contains only this server's database snapshot. Encryption: AES-256.\n"
                                "Keep the backup password separate from the ZIP."
                            ),
                            file=discord.File(zipPath, filename=f"server-{serverId}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        successful += 1
                        logger.info("Encrypted per-server backup DM sent: guild=%s size_bytes=%s", serverId, zipPath.stat().st_size)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Per-server backup or DM delivery failed: guild=%s", serverId)
            logger.info("Backup cycle finished: successful=%s configured_servers=%s", successful, len(databaseItems))
            return successful

    def _BuildManifest(self, serverId: int, database) -> dict[str, Any]:
        return {
            "format": "bloxfruits-helper-credit-bot-per-server-backup-v1",
            "server_id": int(serverId),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "backend": self.databaseManager.backend,
            "encryption": "WinZip AES-256",
            "contains_secrets": False,
            "current_database_file": getattr(database, "databasePath", None).name if getattr(database, "databasePath", None) else None,
            "restore_note": (
                "SQLite: stop the bot and restore the .sqlite3 file into data/servers/<server_id>/. "
                "PostgreSQL: run the included per-server JSON row export through a restore procedure after the app has created that server schema."
            ),
        }

    def _SnapshotPayloads(self, database, tempRoot: Path) -> list[tuple[str, Path]]:
        if self.databaseManager.backend == "sqlite":
            snapshotPath = tempRoot / "blox_fruits_credit_system.sqlite3"
            target = sqlite3.connect(str(snapshotPath))
            try:
                # Use the same lock as all normal DB operations. sqlite3 backup()
                # includes committed WAL state and avoids copying live sidecars.
                with database.databaseLock:
                    database.connection.backup(target)
                check = target.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise RuntimeError(f"SQLite integrity check failed: {check!r}")
            finally:
                target.close()
            return [("database/blox_fruits_credit_system.sqlite3", snapshotPath)]

        # Never run a backup transaction on the same PostgreSQL connection that the
        # live bot uses for commands: a backup must not disturb an in-flight write.
        import psycopg
        from psycopg.rows import dict_row
        connection = psycopg.connect(
            self.databaseManager.databaseUrl,
            row_factory=dict_row,
            autocommit=True,
            connect_timeout=15,
            application_name="BloxAssistBackup",
        )
        schemaName = f"server_{int(database.guildId)}"
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            tableRows = connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
                (schemaName,),
            ).fetchall()
            exported: dict[str, list[dict[str, Any]]] = {}
            tableColumns: dict[str, list[str]] = {}
            for row in tableRows:
                tableName = str(row["table_name"])
                if not tableName.replace("_", "").isalnum():
                    continue
                columns = connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                    (schemaName, tableName),
                ).fetchall()
                columnNames = [str(column["column_name"]) for column in columns]
                tableColumns[tableName] = columnNames
                quotedSchema = '"' + schemaName.replace('"', '""') + '"'
                quotedTable = '"' + tableName.replace('"', '""') + '"'
                rows = connection.execute(f"SELECT * FROM {quotedSchema}.{quotedTable}").fetchall()
                exported[tableName] = [self._JsonSafe(dict(item)) for item in rows]
            connection.commit()
            dataPath = tempRoot / "database-export.json"
            dataPath.write_text(
                json.dumps({"schema": schemaName, "columns": tableColumns, "tables": exported}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return [("database/database-export.json", dataPath)]
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _JsonSafe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): PerServerBackupService._JsonSafe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [PerServerBackupService._JsonSafe(item) for item in value]
        if isinstance(value, (datetime,)):
            return value.isoformat()
        # Most app schema values are integers/text. Convert unknown numeric/driver
        # objects to stable JSON strings rather than lose data or fail the whole job.
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
