![BloxAssist banner](assets/branding/bot-client_banner.png)

# BloxAssist Discord Bot
### Helper & Credit System for Blox Fruits Players

![BloxAssist icon](assets/branding/bot-client_icon.png)

A slash-command Discord bot for multi-server Blox Fruits service tickets, helper coordination, and credit management. Each Discord server has isolated data, ticket numbering, service catalog, settings, audit records, and invite-reward history.

> **🧪 Beta status and deployment scope (as of November 11, 2026):** BloxAssist is still in beta. It has only been deployed in one small real Discord server and one separate testing server. This is a very limited deployment, not broad production testing across multiple communities or at scale. Automated tests have passed, but they do not replace extensive live testing with different users, permissions, and server configurations. Bugs and edge cases may remain. Test new or changed workflows in a separate server first, keep independent backups, and verify important credit and ticket records rather than relying on the bot as the sole source of truth.

> **Latest release:** BloxAssist `v0.10.0` was published as a GitHub pre-release on November 10, 2026 and announced in the real server on November 11, 2026. It passed 173 automated tests and extensive live acceptance testing in a separate Discord test server on November 10, 2026. BloxAssist remains in beta; its deployment scope is still limited to one small real Discord server and one separate testing server. See [`docs/release_history.md`](docs/release_history.md), [`docs/changelog-0.9.0.md`](docs/changelog-0.9.0.md), and [`docs/changelog-0.10.0.md`](docs/changelog-0.10.0.md) for release history and changes. See [`docs/project_timeline.md`](docs/project_timeline.md) for dated development and hosting milestones.

## AI-assisted development disclosure

BloxAssist is a heavily AI-assisted project and can fairly be described as “vibe-coded.” AI tools have been used extensively to help develop, revise, debug, and document parts of the project. The maintainer directs the project and is responsible for its maintenance, but AI-generated suggestions can still contain mistakes, bugs, or security issues. Review and test the code in a safe development environment before deploying it, especially when handling real users, credits, or server data.

## Features

- Public Help Center panel with ticket creation, balances, and a **Report Issue** form for scams, bugs, ticket/credit issues, member misconduct, and general concerns. A reported member is optional.
- Persistent ticket workflow: requester proposes completion/cancellation, active helpers confirm, helpers may leave, and replacement helpers require staff approval.
- Configurable per-server Admin Dashboard, event catalog, starting credits for new accounts, helper limits, moderator roles, ticket staff policy, Help Center placement, and audit/transcript channel.
- `/add` and `/deduct` are restricted to the actual server owner and write actor/reason details to the transaction ledger and configured audit channel.
- `/add` and `/deduct` require a reason. Owner-only `/penalty` can consume available credits and create separate debt for unpaid penalties. Members with debt cannot create/reserve tickets as requesters, but they may still be assigned as helpers; their completed-ticket rewards repay debt first.
- **v0.10.0:** `/balance` and `/credits` show outstanding debt; `/repay-debt` supports partial/full repayment with atomic balance/debt updates and an idempotent ledger record; future ticket and invite rewards automatically pay down debt first; `/credit-history`, `/ticket-history`, and `/reports` use consistent private Previous/Next pagination controls while retaining their `page` options for direct page jumps (ticket history also retains its configurable per-page limit); `/credits` and `/credit-history` accept numeric `user_id` lookups for former members (credit-history remains staff-restricted for other users); owner-only `/diagnostics` checks database tables and audit-channel permissions; `/reports` adds category filters and pagination. A global slash-command error handler gives users actionable private responses when option conversion fails.
- Staff history and reporting: `/ticket-history` accepts a numeric `user_id` for former members; `/reports` can filter Open, Confirmed, Dismissed, or All while keeping the selected category/status across pages and showing saved reviewer notes for resolved cases.
- Staff analytics: the Admin Dashboard's **Server Statistics** button opens a private snapshot of tracked accounts, available credits, outstanding debt, ticket/report counts, ledger records, enabled services, and invite rewards. `/member-activity` combines a member's account/debt totals with recent transactions and retained tickets; it accepts numeric IDs for former members and does not create missing accounts.
- The server owner can configure the **Inviter Leave Penalty** in the Admin Dashboard, including whether the recorded inviter is penalized once per invited member or again for each distinct attributed rejoin/leave cycle. Repeat-per-rejoin is disabled by default for backward compatibility; `0` disables the penalty. Duplicate join/leave event handling is protected per join cycle.
- Ticket reservations, payouts, unused-slot refunds, refunds, invite rewards, and penalties have individual audit entries where implemented, with actor/reason/ledger details when available.
- Completed/refunded tickets create text transcripts in the configured audit channel. If the transcript cannot be safely stored, the bot attempts to archive the original channel for moderator-only review rather than deleting the evidence.
- Active ticket channel numbers are allocated separately and restart at `ticket-001` when no tickets remain open; active ticket channels are never assigned the same label. Permanent transcript identifiers never reset: `Ticket-001` through `Ticket-999`, then `Ticket-1│000`, `Ticket-1│001`, `Ticket-2│000`, and so on. At most **100 tracked transcript posts** remain in the configured audit channel. The database retains the **500 most recent closed tickets with confirmed transcripts**, plus open tickets and closed tickets that still need transcript recovery. Older eligible ticket rows and their per-ticket ledger rows are pruned; current balances, settings, services, and standalone credit-adjustment ledger entries are retained.
- `/ticket-history` links to retained transcripts. `/reports` lists open reports across all categories, and `/report-review` lets authorized staff confirm or dismiss a report with an audit note.
- Timed invite reward events use `/invite-event start` and `/invite-event end`. The command uses reward/duration defaults configured in the Admin Dashboard unless explicit values are provided; `run_forever:true` keeps an event open until staff ends it manually. Finite events show a Discord relative-time countdown in the start confirmation, audit log, and Admin Dashboard, while automatic expiry remains restart-safe. Invite attribution requires the bot to have **Manage Server** permission to inspect invite use counts; ambiguous attribution is skipped rather than guessed.
- Optional encrypted ZIP backups, one ZIP per server, sent to a configured Discord DM after startup and then every five hours, plus a best-effort graceful-shutdown attempt. The configured Audit Log Channel also receives one startup notice per process and a graceful-shutdown notice. A forced kill cannot send a shutdown notice or guarantee the final backup.

## Storage options

### Local SQLite (default and safest starting point)

Each server uses:

```text
data/servers/<server_id>/blox_fruits_credit_system.sqlite3
```

The database stores `users`, `tickets`, `transactions`, `settings`, `services`, `invite_events`, `invite_rewards`, and `scam_reports`. SQLite WAL sidecars may be present while the bot is running. Do not delete or replace those files by hand.

### PostgreSQL (live-tested with Supabase)

Set `DATABASE_BACKEND=postgresql` and `DATABASE_URL` in `private-configs/credentials.env` or your bot hosting service's secret/environment settings. The bot creates a separate PostgreSQL schema named `server_<Discord server ID>` for each guild, preserving server-level isolation inside the hosted PostgreSQL database.

**Live deployment status:** The announcement history records the Supabase deployment by October 20, 2026 and Bot-Hosting.net with Supabase by October 21, 2026—approximately three weeks before November 11, 2026. PostgreSQL connectivity, application workflows, per-server data isolation, and backup/restore behavior have been exercised in the deployed bot. BloxAssist remains in beta, and this does not establish readiness at broad multi-community scale or validate every PostgreSQL provider.

The one-time `tools/Migrate-SQLite-To-Postgres.py` utility is only for deployments that are moving existing SQLite databases to PostgreSQL. It requires recoverable SQLite source files, checks that target schemas contain only known default seeds, imports each server's records, resets serial sequences, and checks row counts. It intentionally refuses to overwrite populated or customized target schemas. Do not run this migration against an already-populated live PostgreSQL deployment.
## Setup

1. Install Python 3.13 or newer, then run `python -m pip install -r requirements.txt`.
2. For local use, copy `private-configs/credentials.env.example` to `private-configs/credentials.env` and fill in `DISCORD_TOKEN`. For bot hosting services, configure secrets/environment variables through the host's supported settings instead of uploading real credentials. SQLite remains the default for a first local test. To use PostgreSQL, set `DATABASE_BACKEND=postgresql` and provide the matching `DATABASE_URL` securely.
3. Start locally with `python RunBot.py`. For a hosted deployment, configure the Python runtime and startup command to run `python RunBot.py`. Consult your hosting service's documentation for its panel-specific settings.
4. In a staff-only channel, run `/setup admin_dashboard`. Set an **Audit Log Channel** where the bot can send messages, embed links, attach files, and read message history. This channel receives ticket transcripts, credit movement audit entries, invite reward logs, and general moderation reports.
5. Run `/setup public_tickets` in the public Help Center channel. Test in a development Discord server before using real balances.

For full environment, permissions, migration, backup, and verification steps, see [`docs/installation_and_operations.md`](docs/installation_and_operations.md). See [`docs/backup_and_restore.md`](docs/backup_and_restore.md) for backup/restore details, [`docs/release_history.md`](docs/release_history.md) for release history, and [`docs/changelog-0.10.0.md`](docs/changelog-0.10.0.md) for the v0.10.0 release changelog.

Historical install/changelog files are archived in [`docs/history/releases/historical-installation-and-changelogs.zip`](docs/history/releases/historical-installation-and-changelogs.zip). They are reference material only; use the maintained docs linked above for current instructions.

## Backup settings

Set the following environment variables in `credentials.env` or your bot hosting service's secret/environment settings to enable encrypted per-server ZIP backups:

```dotenv
BACKUP_DISCORD_USER_ID=your_numeric_discord_user_id
BACKUP_ENCRYPTION_PASSWORD=a_long_random_password
```

The bot needs to be able to DM the selected user. The ZIP is encrypted with WinZip AES-256; store the password separately from the backup. The backup service intentionally skips sending oversized archives rather than silently treating a failed send as success. It records success/failure in the host logs. A graceful shutdown backup is best-effort, not guaranteed after a forced process kill.

## Permissions and safety

- Required ticket capabilities include `View Channel`, `Send Messages`, `Read Message History`, `Embed Links`, `Manage Channels`, and `Manage Roles` where the workflow applies channel permission overwrites. Grant only the permissions your configuration needs.
- Invite tracking needs `Manage Server` to inspect invite uses. If the invite-use change cannot be uniquely attributed, no reward is issued.
- Do not commit `private-configs/credentials.env`, real tokens, database files, backups, logs, or real member/credit data. `.gitignore` excludes these by design.
- The Admin Dashboard can edit the ordinary plain-text welcome message sent to new ticket channels. It is not pinned and is not an embed. Supported placeholders: `{requester}`, `{helpers}`, `{ticket}`, and `{event}`. Existing ticket conversations are not rewritten.

## License

BloxAssist source code is licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE).

You may use, study, modify, and distribute this software
for noncommercial purposes under the terms of the license.

Commercial use requires separate permission from the
copyright holder.

BloxAssist branding, name, and logos are not included
in the software license and remain reserved.
