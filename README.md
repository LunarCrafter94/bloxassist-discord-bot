# Blox Fruits Helper Credit Bot

A slash-command Discord bot for managing helper tickets and credit balances in Blox Fruits community servers. Each server keeps its own SQLite database, so balances, tickets, service settings, and transaction history remain separate between servers.

> **Current documented release: Update 0.6.3.** Run the automated checks and test the live Discord workflows in a development server before relying on the bot with real credit balances. Passing unit tests does not prove that every Discord interaction or permission overwrite works in a live server.

## What it does

- Creates a public Help Center panel where members can check their balance and open tickets.
- Creates numbered ticket channels independently per server (`ticket-001`, `ticket-002`, and so on). Ticket numbers can restart after that server has no open tickets; closed ticket records remain in the database.
- Reserves credits atomically when a ticket is created and records balance changes in a transaction ledger.
- Requires the requester to propose completion or cancellation and every active helper to confirm. A helper can reject a pending proposal. A pending proposal expires after 15 minutes without moving credits.
- Supports helper departure and requester-selected replacement helpers, with staff approval of the submitted replacement list.
- Provides a configurable Admin Dashboard for starting credits for new accounts, the event/service catalog, per-helper prices, helper limits, ticket staff access, Help Center placement, and moderator roles.
- Provides `/add` and `/deduct` for the actual Discord server owner only, with audit records and safeguards against negative balances and duplicate adjustments.

## Important current limitations

Invite-reward settings can be saved in the dashboard, but invite attribution, operational invite events, automatic expiry, and reward payouts are **not implemented**. Do not advertise invite rewards as an available feature or enable them expecting automatic payouts.

Hosting, production monitoring, and a full live end-to-end acceptance run remain follow-up work. The database tests do not replace testing commands, message components, role permissions, and channel changes in Discord.

## Requirements

- Python 3.13 or newer; the project has been run in the existing Python 3.15 environment.
- A Discord application and bot token.
- The Python packages listed in `requirements.txt`.
- A development Discord server for initial setup and acceptance testing.

## Run locally

1. Clone or extract the project, then open a terminal in the project root.
2. Create and activate a virtual environment if you do not already have one:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Copy `private-configs/tokens.env.example` to `private-configs/tokens.env` and set `DISCORD_TOKEN` to the bot token. Set `GUILD_ID` to your development server ID for quicker test-server command synchronization; leave it blank when you intentionally want global command synchronization.
4. Start the bot:

   ```powershell
   .\.venv\Scripts\python.exe RunBot.py
   ```

5. In the development server, run `/setup admin_dashboard` in a staff-only channel and `/setup public_tickets` in the public Help Center channel. Configure the event catalog and permissions, then test the ticket lifecycle before using the bot in a public server.

For the complete setup, backup, update, and validation procedure, see [`INSTALL.md`](INSTALL.md). To reorganize existing documentation and archive the old phase-specific scripts safely, extract the cleanup bundle elsewhere and run `tools/Organize-Documentation.ps1` from the extracted package; see the package instructions first.

## Discord permissions and intents

The bot needs `Manage Channels` to create/delete ticket channels and `Manage Roles` to edit ticket-channel permission overwrites for staff access, helper departure, and approved replacements. It also needs `View Channel`, `Send Messages`, `Read Message History`, and `Embed Links` where it operates. Configure the bot role hierarchy and channel/category overwrites so the required permissions are effective. Do not grant `Administrator` solely to avoid permission troubleshooting.

Enable **Server Members Intent** in the Discord Developer Portal if you want the bot to initialize users when they join. Accounts are also initialized when users first use supported credit/ticket interactions. The bot is slash-command-only and does not require Message Content Intent for prefix commands.

## Data and safety

Each server's database is stored at:

```text
data/servers/<server_id>/blox_fruits_credit_system.sqlite3
```

The database holds balances, tickets, ledger entries, and per-server settings. Keep the main SQLite file and any `-wal`, `-shm`, or journal sidecars together when making a file-level backup. Stop the bot and close database viewers before backing up or restoring.

Never commit or share `private-configs/tokens.env`, SQLite databases, runtime data, backup archives, logs, or real member/credit data. The `.gitignore` is intended to exclude these local files; confirm `git status` before every push. If a bot token has been exposed, rotate it in the Discord Developer Portal.

## Project map

```text
RunBot.py                         # launcher
source-files/bloxfruits_helper_credit_bot/  # application package
private-configs/tokens.env.example          # safe configuration template
requirements.txt                  # Python dependencies
tests/                            # automated tests
tools/                            # maintenance and verification scripts
docs/                             # maintained references and docs/history/ archive
data/                             # local runtime databases; do not commit
_backups/                         # local backup snapshots; do not commit
```

The project uses its established naming conventions documented in [`docs/naming_convention.md`](docs/naming_convention.md). SQL transactions and audit safeguards are summarized in [`docs/transaction_safety.md`](docs/transaction_safety.md). See [`CHANGELOG.md`](CHANGELOG.md) for consolidated release history.
