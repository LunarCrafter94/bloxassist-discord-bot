# Phase 3 installation — Admin Dashboard and Help Center

This is the original Phase 3 installation note retained for reference. For the current named database file layout and automatic migration from the earlier `data/guilds/<server_id>/guild.sqlite3` path, follow `PHASE3.3_INSTALL.md`. The database migration preserves balances, settings, ticket records, and transaction history.

## Before installing

1. Close the bot with `Ctrl+C` and close DB Browser for SQLite.
2. From the Phase 3 package root, run the backup script below against your actual project folder. Type `YES` only after the bot and SQLite tools are closed:

   ```powershell
   .\tools\Backup-Phase3-Before-Phase3.2.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

3. Confirm that the newly dated `phase3-before-phase3.1-*` backup includes `source-code`, `database`, and `project-files`. The script deliberately excludes the real `private-configs/tokens.env`.
4. Keep your existing `private-configs/tokens.env`. This ZIP does **not** include a real token file; never replace your working token file with a blank template.

## Install

1. Extract the ZIP to a staging folder first.
2. Copy the contents of the package root into:

   `D:\Repositories\Local\bloxfruits-helper-credit-bot`

   Allow the Phase 3 versions of source files, tests, README and phase documentation to replace their older versions. Preserve `.venv`, `.venv-old`, `_backups`, `data`, and your real `private-configs/tokens.env`.
3. In VS Code, make sure the selected interpreter remains `.venv\Scripts\python.exe`.
4. Run compilation and tests:

   ```powershell
   .\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
   .\.venv\Scripts\python.exe -m unittest discover -s tests -v
   ```

   Expected: **22 tests pass** in your local virtual environment, including the slash-command registration test.

## First test in Discord

1. Start the bot with `RunBot.py` and watch for startup errors.
2. In the test server, run `/setup admin_dashboard` as a server Administrator in a staff-only text channel. Run `/setup public_tickets` in the public channel where members should open tickets. If commands do not appear immediately, use a test `GUILD_ID` during development or allow global command updates to propagate. While `GUILD_ID` is set, guild commands are synced quickly in that test server; previously registered global `/admin_dashboard` may remain visible until you later clear `GUILD_ID` and restart once to sync the updated global command list.
3. The dashboard is posted in the channel where you invoke the subcommand; it does not create a dedicated channel. Its controls check authorization in code. Use a staff-only channel so non-staff cannot read the configuration panel or see its controls. If you used an earlier Phase 3 build, the old `#bot-admin-dashboard` channel is not deleted; the new command leaves that channel intact and moves the dashboard message to the new location when you run `/setup admin_dashboard`.
4. Test starting credits by changing the value and checking that an existing balance does not change while a newly initialized test account gets the new amount.
5. Add/edit an event, change its price, disable/enable it, and confirm the public panel reflects enabled events and current prices.
6. Change the maximum helper count and confirm the helper picker offers only the configured range.
7. Choose a public Help Center channel, confirm the panel is posted there, then choose another channel and confirm the old panel is marked as moved and the new panel works.
8. Set a ticket staff baseline role. Create a new test ticket and confirm the selected role and higher normal roles can access it. Change/clear the baseline with an open ticket and confirm the current ticket's role access is updated.
9. Complete and refund tickets again. Confirm completion still pays once and deletes after 15 seconds; a requester cancellation/refund still returns credits once and deletes the channel after 10 seconds.

Invite reward settings in this phase are configuration only; don't expect `/start-invite-event`, `/end-invite-event`, or automatic invite payouts yet. Likewise, `/add` and `/deduct` are not implemented in Phase 3.

## Rollback

Stop the bot and DB Browser before restoring a backup. The backup is a copy, not a move. Restore source code and the matching database snapshot together. Do not replace the per-guild database with the old root `bot.db` unless you intentionally run a separately planned data migration.

## Phase 3.2 logging/client update

This refinement uses a slash-command-only `discord.Client` and configures one logging handler. Existing `.venv`, `data`, `_backups`, and `private-configs/tokens.env` must be preserved. After installation, run compileall and unittest as below, then start `RunBot.py` and verify each Discord log line appears once. Voice dependency warnings are optional and may remain once; this bot doesn't use voice.
