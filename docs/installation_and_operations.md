# Installation and operations

This is the maintained setup document for the current local development package. Do not use archived phase installation notes unless you are investigating a historical release.

## 0. Upgrade an existing v0.7.0 project to hotfix v0.7.1

1. Stop the currently running bot process first. Do not run two copies using the same Discord token.
2. Keep a recoverable backup of the project and its `data/` directory.
3. Extract the v0.7.1 package somewhere outside the existing project, then run its updater in PowerShell:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   & "D:\Path\To\Extracted\tools\Apply-Local-Update-0.7.1.ps1" -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

4. From the existing project folder, run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`, then run `.\tools\Test-Project.ps1` directly in PowerShell.
5. Start the bot with `.\.venv\Scripts\python.exe RunBot.py` and verify the server-specific databases are ready.

The updater does not copy package-side credentials, `.git`, `.venv`, `data/`, or private backup folders into the project. On startup, the database adds the separate channel-number column and setting automatically. Historical ticket numbers and transcript references are preserved through a legacy-label fallback. New transcript identifiers use `Ticket-001` through `Ticket-999`, then `Ticket-1│000` onward; active ticket channel labels use a separate reusable counter.

## 1. Install and configure

Python 3.13 or newer is required. From the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item private-configs\credentials.env.example private-configs\credentials.env
```

Edit `private-configs/credentials.env` privately:

```dotenv
DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN
GUILD_ID=
DATABASE_BACKEND=sqlite
DATABASE_URL=
BACKUP_DISCORD_USER_ID=
BACKUP_ENCRYPTION_PASSWORD=
```

- `DISCORD_TOKEN` is required.
- `GUILD_ID` is optional and controls development slash-command synchronization only.
- `DATABASE_BACKEND` is `sqlite` by default or `postgresql` when using a configured remote PostgreSQL database.
- `DATABASE_URL` contains a database password and must not be committed.
- `BACKUP_DISCORD_USER_ID` and `BACKUP_ENCRYPTION_PASSWORD` are both required to enable the five-hourly encrypted per-server ZIP backups.

The loader prefers `private-configs/credentials.env`. `runtime.env` and the old `tokens.env` path remain as compatibility fallbacks for existing installations, but new installs should use `credentials.env`. On a managed host such as Nylix, configure secrets through its environment/secret settings when possible instead of storing a real secret file in a code deployment.

Start locally:

```powershell
.\.venv\Scripts\python.exe RunBot.py
```

For Falix, choose Python 3.13 and install dependencies from `requirements.txt`. The Python template often starts `app.py`; this package includes `app.py` as a compatibility launcher that calls the existing `RunBot.py` entry point. If the panel exposes a Main file selector, use `app.py`. The process logs whether SQLite or PostgreSQL mode is selected; it never prints the database URL or password.

## 2. Discord first-time setup

1. In a private staff channel, run `/setup admin_dashboard`.
2. Configure the **Audit Log Channel** in the Admin Dashboard. It needs `Send Messages`, `Embed Links`, `Attach Files`, and `Read Message History`. Store transcripts in a channel visible only to trusted moderators/admins.
3. In a public text channel, run `/setup public_tickets`.
4. Set dashboard moderator roles and ticket-staff baseline access. Only a Discord server Administrator can change the dashboard moderator-role allowlist.
5. If invite events will be used, enable invite rewards in the dashboard, set default reward/duration, and ensure the bot has `Manage Server`. Test `/invite-event start` and `/invite-event end` in a test server.
6. Test `/reports` and `/report-review` from a configured staff account. General reports are delivered to the Audit Log Channel and remain in the database even if Discord cannot deliver the audit message.

## 3. Database modes and migration

### SQLite

Each server uses `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. The DB manager maintains one connection per server. SQLite WAL and SHM sidecar files can appear while the bot is running. Do not copy only the main file from a live database using an ordinary file-copy tool; use the app's SQLite backup API (the automated DM backup does that) or stop the bot before copying.

### PostgreSQL

BloxAssist's PostgreSQL backend has been live-tested with Supabase. The deployed bot has been operating against Supabase PostgreSQL for approximately two weeks as of November 11, 2026. The application creates an isolated schema named `server_<server_id>` for each Discord server. This validates the current Supabase deployment and exercised application workload; it does not establish broad production readiness at scale or automatically validate other PostgreSQL providers.

Put the connection URL in `DATABASE_URL` using the hosting provider's secret/environment settings or a private local `credentials.env` file. Never commit the URL or its password.

#### One-time migration from SQLite

The migration utility is only for an existing SQLite deployment that is intentionally moving to PostgreSQL. It is not needed by an installation that already uses PostgreSQL. With the bot stopped and the current SQLite files available under `data/servers/`, run:

```powershell
.\.venv\Scripts\python.exe tools\Migrate-SQLite-To-Postgres.py
```

The script prompts for `MIGRATE`, checks that each target schema contains only the known default seed settings/service catalog, preserves source SQLite files, imports server tables in dependency order, resets serial sequences, and checks row counts. It refuses to merge into non-empty or customized target schemas. Do not run it against an already-populated live PostgreSQL deployment.

For a SQLite-to-PostgreSQL cutover, compare user counts, total credits, ticket counts by status, transaction counts/totals, service catalog, settings keys, and transcript/report rows. Test with a development Discord server before switching the production token. Do not run SQLite and PostgreSQL instances simultaneously with the same Discord bot token against production: simultaneous writes could diverge their data.

## 4. Five-hourly per-server encrypted DM backups

Configure `BACKUP_DISCORD_USER_ID` to the numeric Discord user ID of the recipient and `BACKUP_ENCRYPTION_PASSWORD` to a strong password. The service starts a backup cycle after the client is ready, then repeats every five hours. It sends a different ZIP for each server:

- SQLite mode: a transaction-safe SQLite snapshot created using `sqlite3.Connection.backup()` and checked with `PRAGMA integrity_check`.
- PostgreSQL mode: a repeatable-read, read-only export of that server's schema as JSON rows/columns inside the encrypted ZIP.

Both formats are encrypted with WinZip AES-256. Store the ZIP password separately from the backup. The bot tries a final backup during graceful shutdown; abrupt termination, host power loss, unavailable DMs, upload-size limits, or a network outage can prevent a backup from being delivered. The service uses a conservative 8 MB attachment cutoff, logging failed delivery instead of claiming success. The configured Audit Log Channel receives one startup notice per process and a graceful-shutdown notice. A hard kill, power loss or host termination that skips graceful shutdown cannot send a final status message or guarantee the last backup.

For PostgreSQL backups, perform a dry-run restore inspection:

```powershell
.\.venv\Scripts\python.exe tools\Restore-Postgres-Server-Backup.py path\to\server-<ID>-backup.zip --server-id <ID>
```

To apply a restore, stop the bot and rerun with `--apply`; the tool asks you to type the exact server ID and replaces all application tables in that server's schema. Use this only when you intend to replace those records. After a restore, compare counts and balances before restarting the bot.

For SQLite backups, stop the bot, extract the ZIP, verify `manifest.json`, and restore `database/blox_fruits_credit_system.sqlite3` to `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. Keep a separate copy of the current destination before replacing it.

## 5. Ticket transcript retention and recovery

Transcripts are posted to the configured Audit Log Channel as text attachments. The bot tracks transcript message/channel IDs in the same server database. When a new transcript is saved, it removes the oldest tracked transcript message if 100 are already retained, leaving the 100 most recent. Ordinary audit entries/reports are not pruned by this transcript-retention rule.

Separately, after transcript retention completes safely, the database keeps the 500 most recent closed ticket records whose transcript was confirmed as saved. All open tickets and closed tickets without a confirmed transcript are preserved for recovery, so the total row count can exceed 500. Ticket-linked transaction rows are removed when their old ticket-history row is pruned; the account's current balance and standalone credit-adjustment records are preserved. This means old per-ticket financial detail may no longer be available in `/ticket-history`; keep a separate backup if you need a complete long-term ledger. SQLite commonly reuses pages freed by deletion rather than immediately shrinking the database file. Run `VACUUM` only with the bot stopped and a verified backup if reducing physical file size is necessary.

Active ticket channel labels use a separate counter and restart at `ticket-001` when no tickets are open; while tickets remain active, new labels skip every active number. Permanent transcript labels advance independently as `Ticket-001`–`Ticket-999`, `Ticket-1│000`, `Ticket-1│001`, `Ticket-2│000`, etc. Transcript identifiers never reset, including after restarts. `ticket_id` remains an independent internal identifier. If transcript posting fails, the bot attempts to archive the source ticket channel with participant access removed and effective ticket staff roles granted. Keep role policy configured so moderators can see the fallback archive.

## 6. Verification

Compile and run tests:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests tools
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Use `tools/Test-Project.ps1` if the local `.venv` exists. Tests with a skipped Discord registration check mean `discord.py` was not available in that validation environment; they do not validate live command registration. Live acceptance testing is still necessary for Discord permissions, transcript attachments, invite attribution, and the actual deployment environment. The current Supabase PostgreSQL deployment has been live-tested; validate any different PostgreSQL provider separately.
