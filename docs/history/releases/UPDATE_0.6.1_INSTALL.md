> **Historical guide:** This file describes Update 0.6.1. In Update 0.6.2, replacement selection changed: requesters choose candidates, and staff use `/admin_helper-replace approve` or `/admin_helper-replace disapprove`. The old `/admin_replace_helper member` command is no longer available.

# Update 0.6.1 — Installation

This hotfix is for the combined Phase 4 + Phase 5 package already installed. It does not require installing Phase 3.1, 3.2, or 3.3 separately, and it keeps the named-server database path introduced by the combined package.

## 1. Back up first

1. Stop the bot with `Ctrl+C`.
2. Close DB Browser for SQLite and any other database viewer.
3. Extract this ZIP to a temporary staging folder.
4. In PowerShell opened in that staging folder, run:

   ```powershell
   .\tools\Backup-Phase4-5-Before-Update-0.6.1.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

5. Type `YES` only after confirming the bot and SQLite tools are closed. Verify that the script printed the backup location.

The script copies `source-files`, tests, tools, documentation, and the full `data` folder into `_backups`. It deliberately excludes the actual `private-configs\tokens.env`.

## 2. Install

Copy the extracted package contents into:

`D:\Repositories\Local\bloxfruits-helper-credit-bot`

Allow updated source files to overwrite their previous versions. Preserve `.venv`, `.venv-old`, `_backups`, `data`, and the actual `private-configs\tokens.env`.

The database automatically adds a nullable `resolution_message_id` column on startup. Existing balances, ticket records, and transaction history are preserved. No database filename or directory rename is performed by this hotfix.

## 3. Validate

From the project root, run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The packaging environment ran 38 database/configuration tests successfully. One Discord command-registration test was skipped there because `discord.py` was not installed in that environment. In the project's `.venv`, that test should run too.

## 4. Live checks

- Open a new ticket: the private helper-count, helper selection, and event-selection messages should disappear immediately after the ticket is successfully created. The final private confirmation should disappear within one minute.
- Check a balance or trigger an authorization error: the private response should disappear after about 60 seconds.
- Run `/complete_ticket`: the main ticket card should stay unchanged, and a separate confirmation message with Confirm/Reject buttons should appear.
- Reject or finish the proposal: the separate prompt's buttons should be removed.
- On a multi-helper ticket, let helpers leave until exactly one remains: a replacement-request message should appear. It should not appear while two or more active helpers remain or after all helpers leave.
- In Update 0.6.1, staff used `/admin_replace_helper member`. This command was superseded by Update 0.6.2, where the requester selects candidates and staff use `/admin_helper-replace approve` or `/admin_helper-replace disapprove`.
- Confirm the usual 15-second completion deletion and 10-second refund deletion still work.

Run these checks in the development server before using the workflows on the public server.
