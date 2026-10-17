# Installation, updates, and recovery

This guide is for the current documented code line, Update 0.6.3. Earlier `PHASE*_INSTALL.md` and `UPDATE_*_INSTALL.md` files describe historical packages and should not be used as the current install procedure.

## 1. Before first run

1. Install Python 3.13 or newer and open PowerShell in the project root.
2. Create a virtual environment and install dependencies:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   If `.venv` already exists and is working, do not recreate it just for an application update.
3. Copy `private-configs/tokens.env.example` to `private-configs/tokens.env`. Set `DISCORD_TOKEN` to the development bot token. Use `GUILD_ID` for test-server command synchronization, or leave it blank for global synchronization. Never commit the real token file.
4. Review bot permissions and role hierarchy in the README. In particular, `Manage Roles` is required for channel permission overwrites; `Manage Channels` alone is insufficient.

## 2. Back up before changing code or databases

Stop the bot with `Ctrl+C` and close DB Browser for SQLite or any other process that may have the database open. Run the consolidated backup script from the project root:

```powershell
.\tools\Backup-Project.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
```

Type `YES` only after the bot and database tools are closed. Check the printed destination under `_backups` and confirm that the backup contains source, tests, project documentation, and the full `data/` directory if it exists. The script should copy—not move or delete—working files and should omit the real token file. Keep backups private because they include live databases and member credit records.

A file-copy backup is only as good as its contents. Do not proceed with an update if a live database exists but the backup reports that no database files were copied. Keep the main `.sqlite3` file and any `-wal`, `-shm`, and journal sidecars together.

## 3. Install or update

- **New checkout:** open the cloned repository, create the virtual environment, install requirements, configure the local token file, then run the verification commands below.
- **Existing project:** back up first, then copy or pull the updated source/docs/tools. Preserve `.venv`, `private-configs/tokens.env`, `data/`, and `_backups/`. Never replace the real token file with the example template.
- Do not manually delete the older database archive at `data/legacy-database-archives/` until the migrated database has been checked and a fresh backup has been made.
- If both `data/guilds/<server_id>/guild.sqlite3` and `data/servers/<server_id>/blox_fruits_credit_system.sqlite3` exist for the same server, stop and review them; the application intentionally refuses to guess which is authoritative.

## 4. Run automated checks

```powershell
.\tools\Test-Project.ps1
```

Or run the commands directly:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The automated suite uses temporary databases. It does not prove that live Discord commands, UI components, channel permissions, or event delivery work in your server. Review the complete test output and address failures before proceeding.

## 5. First live test

Use a development Discord server and controlled test accounts:

1. Start the bot and check the console for startup errors.
2. Run `/setup admin_dashboard` in a staff-only channel and `/setup public_tickets` in the intended public Help Center channel.
3. Check starting-credit behavior on both a new account and an existing account.
4. Create tickets at different helper counts. Verify the reservation is `price per helper × selected helpers`.
5. Test normal completion and cancellation with all required helper confirmations, helper rejection, the 15-minute timeout behavior where practical, and the scheduled channel cleanup.
6. Test helper departure, the all-helpers-left refund, requester replacement selection, staff approval/disapproval, and role-overwrite behavior.
7. Test `/add` and `/deduct` only in the development server. Confirm only the actual server owner can use them, that owner participation in an open ticket blocks the commands, and that every change appears in the ledger.
8. Restart the bot with open tickets and check persistent panels and workflow controls.

Do not test deductions or replacement operations against important production balances until the development checks have passed.

## 6. Restore a backup

1. Stop the bot and close database viewers.
2. Identify the matching pre-update snapshot under `_backups`.
3. Restore the matching source and database copies together. Do not restore an old database against unrelated newer source code unless you are deliberately rolling back to that version.
4. Preserve the real token file separately. Start the bot only after the restored code and databases are in place, then check balances, ticket states, and transaction history.

A backup script creates a local copy and checksum manifest; it does not validate the business correctness of every database row. Inspect the restored bot and data before returning to production.
