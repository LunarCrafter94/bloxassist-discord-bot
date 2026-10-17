# Phase 3.3 installation — Named server database files

## Before installing

1. Stop the bot with `Ctrl+C` and close DB Browser for SQLite.
2. Run the included backup script against your project folder. Type `YES` only after everything that may have the SQLite files open is stopped.
3. Confirm the backup includes the complete `data/` directory, source code, tests, and project files. Do not replace `private-configs/tokens.env`.

   ```powershell
   .\tools\Backup-Phase3-Before-Phase3.3.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

## Install

Copy this package's project contents to `D:\Repositories\Local\bloxfruits-helper-credit-bot`, allowing updated source, tests, and documentation to replace prior versions. Preserve `.venv`, `.venv-old`, `_backups`, `data`, and your real `private-configs/tokens.env`.

Run checks:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: **24 tests pass** in your project environment with `discord.py` installed. In a validation environment without that dependency, the command-registration test is skipped.

## New data location and automatic migration

Current storage is `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. Existing databases at `data/guilds/<server_id>/guild.sqlite3` are migrated automatically on first access. The old folder is archived under `data/legacy-database-archives/`; it is not deleted. The migration uses SQLite's backup API, verifies database integrity, and keeps balances, ticket records, settings, and transactions.

If both old and new files are present for the same server, the bot will raise an error and refuse to pick one automatically. Do not delete either file; stop the bot and ask for help reviewing the two copies.

After installing, start the bot and check the startup log for a path like `data\servers\967934723760468018\blox_fruits_credit_system.sqlite3`. Check balances in both test servers, create a test ticket, and verify that ticket history remains available. Do not manually delete `data/legacy-database-archives/` until you have confirmed the migration and made a fresh backup.
