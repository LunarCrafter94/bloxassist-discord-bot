# Backup and restore

Use the one current backup script, `tools/Backup-Project.ps1`, for routine pre-update checkpoints. The old phase-specific backup scripts are historical copies of similar procedures and should not all be used interchangeably.

## Create a checkpoint

1. Stop the bot using `Ctrl+C`.
2. Close DB Browser for SQLite and any other process using the databases.
3. From the project root, run:

   ```powershell
   .\tools\Backup-Project.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

4. Type `YES` only when the bot and database tools are closed.
5. Review the printed `_backups` path. Confirm the source, tests, tools, docs, and `data` folders were included as applicable. The script's SHA-256 manifest inventories copied files; it does not validate business rules or replace a restore test.

The backup script must exclude the real `private-configs/tokens.env` and other secret environment files. Backups include the SQLite data and may contain member balances and ticket history; keep them local and private, and don't upload them to GitHub.

## Restore

Stop the bot and close all database viewers first. Restore source and the matching data snapshot together. Keep the real token file separate. After restoring, run `tools/Test-Project.ps1`, start the bot in the development server, and verify balances, ticket state, and transaction history before returning to production.

Do not delete a legacy database archive just because the new path exists. Confirm the current database has the expected records and make a fresh backup first.
