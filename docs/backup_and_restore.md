# Backup and restore

## Automated per-server ZIP-to-DM backups

The optional `PerServerBackupService` uses these environment variables:

- `BACKUP_DISCORD_USER_ID`: numeric Discord ID to receive backups.
- `BACKUP_ENCRYPTION_PASSWORD`: long random password used for WinZip AES-256 encryption.

When both are configured, the service snapshots each connected Discord server separately after the bot becomes ready and repeats every five hours. It also attempts one final backup during graceful shutdown. It intentionally does **not** ZIP all of `data/` into one archive: each DM contains one server only, named with that server's ID.

SQLite backups use `sqlite3.Connection.backup()` under the database lock (including committed WAL state), then run `PRAGMA integrity_check`. PostgreSQL backups use a separate read-only repeatable-read connection and export the isolated `server_<server_id>` schema tables/columns/rows. The raw connection URL, bot token, and backup password are not written into the ZIP.

The service uses a conservative 8 MB Discord attachment threshold. Larger archives are skipped and logged; the bot doesn't claim success. DMs must be available to the bot. Scheduled backup delivery and graceful-shutdown delivery are best-effort: a hard kill, host deadline, API outage, inaccessible DM, or upload-size limit may prevent delivery. The configured Audit Log Channel also receives startup and graceful-shutdown status notices; it cannot report a forced kill that prevents the bot from running its shutdown handler. Keep the archive password separate from the ZIP, because a lost password makes AES-protected backups unreadable.

## Restore a SQLite backup

1. Stop the bot.
2. Download the server-specific ZIP and extract it with the backup password. Check `manifest.json` and `server_id` before using it.
3. Keep a separate copy of the current database directory in case the wrong archive was selected.
4. Restore `database/blox_fruits_credit_system.sqlite3` to `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`.
5. If there are multiple sidecar files in a separate source snapshot, keep them with the corresponding database or use the consistent SQLite backup from the ZIP as the replacement.
6. Start in a test deployment first; verify member balances, service settings, tickets, and transaction rows.

## Inspect or restore a PostgreSQL ZIP backup

A PostgreSQL ZIP contains `database/database-export.json` and `manifest.json`. First run the restore utility in dry-run mode:

```powershell
.\.venv\Scripts\python.exe tools\Restore-Postgres-Server-Backup.py path\to\server-<ID>-backup.zip --server-id <ID>
```

To apply, stop the bot and run the same command with `--apply`. The script requires typing the exact server ID because it replaces the eight application tables for that server. It checks the backup format/server ID, checks schema column compatibility, imports rows transactionally, resets serial sequences, and verifies row counts. Confirm balances, tickets, service settings, event history and ledger before starting the bot again.

## One-time SQLite-to-PostgreSQL migration

With the bot stopped and local SQLite source databases at `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`, configure `DATABASE_BACKEND=postgresql` and `DATABASE_URL`, then run:

```powershell
.\.venv\Scripts\python.exe tools\Migrate-SQLite-To-Postgres.py
```

It discovers server IDs in current or legacy local paths, updates legacy SQLite schemas using the project's migrator, confirms the target PostgreSQL schema contains only the known default seeds, and refuses to overwrite any populated/modified target. Type `MIGRATE` only after confirming the source files are recoverable. Inspect row counts and balances after migration.

## Local pre-update backup

Use `tools/Backup-Project.ps1` for a private source snapshot before code changes. It excludes actual credential files and generated caches but includes current project code/docs/tools. Runtime database backups should remain outside the GitHub repository. Historical phase-specific scripts in `tools/history/legacy-release-scripts/` are retained for reference only.


## Hosting-specific note: Falix Free

Falix Free advertises weekly manual renewal and crash notifications; automatic crash restarts are listed as Premium. A final application shutdown backup is best-effort only. Keep the configured per-server ZIP backup task enabled and check logs for failures. See [Falix test setup](falix_free_test.md).
