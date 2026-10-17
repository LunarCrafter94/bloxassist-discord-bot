# Blox Fruits Helper Credit Bot

A multi-server Discord ticket and credit bot. Each Discord server has its own SQLite database, credit balances, event prices, dashboard settings, tickets, and audit ledger.

## Update 0.6.3 — Staff Authorization, Owner-Only Credit Adjustments & Per-Helper Pricing

- Ticket buttons always use the ordinary workflow. Moderator/owner status never turns a button click into an admin override.
- Explicit ticket override and replacement-decision commands are denied to the requester, original/current helpers, and selected replacement candidates for that ticket.
- `/add` and `/deduct` can be executed only by the actual Discord server owner, and are blocked while the owner participates in any open ticket. Other Administrators/configured moderators cannot adjust balances. Discord may still show the commands to other Administrators due to native command visibility limits; runtime owner-ID enforcement is authoritative.
- Delegated staff command access comes from Moderator Roles configured in the Admin Dashboard; Manage Server alone does not grant access, and delegated moderators do not need Manage Server to use permitted staff commands.
- The configured event price is a fixed **price per helper**. A ticket reserves `unit price × selected helper count`; replacements fill existing slots without increasing the total. If a slot remains empty at completion, its unit price is refunded. Older tickets preserve their legacy total-price behavior.

## What is implemented through Phase 5

- Per-guild database isolation and numbered ticket channels (`ticket-001`, `ticket-002`, …).
- Atomic credit reservations, completion payouts, refunds, and transaction audit records.
- Persistent public Help Center panel with Create Ticket and Balance controls.
- Persistent admin dashboard posted in the channel where `/setup admin_dashboard` is run.
- Configurable starting credits for **new accounts only**; existing balances are never rewritten by this setting.
- Event catalog controls to add, edit, enable, disable, and set the per-helper credit price for an event. Up to 25 events fit the Discord picker.
- Per-server maximum helper count (1–25).
- Per-server invite-reward defaults (enabled flag, reward amount, default event duration). These are saved settings only; invite attribution, starting/ending events, and automatic rewards are still future work.
- Configurable dashboard moderator roles. Administrators and explicitly selected moderator roles may use dashboard controls; only Administrators may change the moderator-role allowlist.
- Configurable ticket staff access baseline. The chosen role and non-managed roles above it in the Discord role hierarchy get access to new and currently open ticket channels. The bot never grants Administrator permission.
- Saved Help Center channel/message IDs. The panel is edited in place when possible, recreated if the message was deleted, and the previous panel is marked as moved when its channel changes.
- Persistent panel messages and open-ticket workflow controls are restored during bot startup when their saved channels still exist.
- Requester-proposed completion/cancellation where the requester's click counts as approval 1/N; every active helper must also confirm. Any one helper can veto the still-pending proposal, even if that helper previously confirmed. Unconfirmed proposals expire after 15 minutes without moving credits.
- Helpers can leave. Departures update the active roster and remove ticket access; if all helpers leave, the requester is refunded automatically and the channel is scheduled for deletion after 10 seconds.
- When exactly one active helper remains, the requester selects exactly the missing number of new human members through a private selector. Staff use `/admin_helper-replace approve` or `/admin_helper-replace disapprove` to decide on the submitted list. Replacements are audited and do not change the originally reserved price. If the bot cannot update channel permissions, its active-helper roster is not changed; diagnostics log the actual Discord error code and effective channel permissions.
- Server-owner-only slash commands `/add member amount reason` and `/deduct member amount reason` make positive-amount, audited credit adjustments with actor IDs, optional notes, atomic writes, and interaction-based idempotency. Insufficient deductions are refused.

## Project layout

```text
bloxfruits-helper-credit-bot/
├── RunBot.py
├── pyproject.toml
├── requirements.txt
├── private-configs/
│   ├── tokens.env          # local secret; excluded from Phase 3 ZIP
│   └── tokens.env.example  # safe template
├── source-files/bloxfruits_helper_credit_bot/
│   ├── __main__.py
│   ├── bot_client.py
│   ├── settings.py
│   ├── database/
│   ├── credits/
│   ├── tickets/
│   ├── admin/
│   └── invites/
├── tests/
├── docs/
├── assets/branding/
├── data/servers/<server_id>/blox_fruits_credit_system.sqlite3  # auto-created; do not commit
└── _backups/              # local only; do not commit
```

## Naming convention

- Variables/parameters: `camelCase` (`guildId`, `startingCredits`).
- Application functions/methods: `PascalCase` (`LoadRuntimeSettings`, `ForServer`).
- Classes: `PascalCase` (`DatabaseManager`).
- Constants: `UPPER_SNAKE_CASE`.
- Module/package filenames: `snake_case`.
- Required framework hooks retain their framework spelling.

## How to use the dashboard

1. The bot needs **Manage Channels** to create/delete ticket channels and **Manage Roles** to edit channel permission overwrites (helper departure/replacement access and ticket staff-role access). Discord requires `MANAGE_ROLES` for channel permission overwrites; `MANAGE_CHANNELS` alone is not enough. Ensure `Manage Roles` is not denied by a ticket/category override, and place the bot role carefully in the role hierarchy. It also needs View Channel, Send Messages, Read Message History, and Embed Links wherever it posts panels. The admin dashboard itself no longer creates a channel or rewrites the dashboard channel permissions.
2. Run `/setup admin_dashboard` as a server Administrator in the channel where you want the dashboard message. The bot posts or updates the dashboard there; it does not create a new channel. Prefer a staff-only channel because the message is visible to people who can view that channel, while dashboard actions are independently permission-checked.
3. Set any moderator roles that should use dashboard controls. By default, only Administrators can use it. Only an Administrator can change this moderator-role allowlist.
4. Configure starting credits, event prices, max helper count, invite defaults, public Help Center channel, and ticket staff access using the dashboard buttons.
5. Run `/setup public_tickets` in a public text channel to post or update the Help Center panel there. Use `/setup admin_dashboard` in a staff channel to post or move the dashboard.

All settings are stored in `data/servers/<server_id>/blox_fruits_credit_system.sqlite3` and are separate for every server. Changing starting credits affects only accounts created after the change. Event price changes apply to new tickets; each new ticket snapshots the unit price and total reservation when it is created. Total reservation is the per-helper price multiplied by the selected helper count.

### Ticket staff role policy

Choose a baseline role such as `@Tickets Moderator`. That role and normal, non-managed roles above it in the server role hierarchy will receive access to new tickets. The bot also updates currently open ticket-channel permissions when this policy changes. Clearing the baseline removes the configured staff-role access; ticket participants, the bot, and Discord Administrators retain access as dictated by Discord's permissions.

### Invite reward defaults

The dashboard saves whether invite rewards should be enabled, the configured reward amount, and a default event duration. **The invite rewards are not operational yet**: tracking which invite was used, eligibility checks, starting/ending invite events, automatic expiry and reward payouts are planned for a later phase. Keep rewards disabled until that functionality is implemented and tested.

## Local setup

1. Use Python 3.13+; this project is compatible with the existing Python 3.15 environment.
2. Keep your existing `private-configs/tokens.env`. The Phase 3 ZIP intentionally excludes that secret file. If creating it for the first time, copy `private-configs/tokens.env.example` and put the bot token in `DISCORD_TOKEN`. Set `GUILD_ID` to a test server while testing, or leave it blank to sync global slash commands. Never share or commit the real token.
3. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

4. Run the bot:

   ```powershell
   .\.venv\Scripts\python.exe RunBot.py
   ```

5. In the test server, run `/setup admin_dashboard`, configure settings, then run `/setup public_tickets` in the intended public Help Center channel. Test ticket creation, completion, refund, and the moderator-role access behavior before using the settings in the production server.

Enable **Server Members Intent** in the Discord Developer Portal if you want the bot to initialize users as they join. User accounts are also initialized when they first use a credit/ticket interaction.

## Validation tests

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests use temporary directories/databases and do not touch your live `data/` directory. They verify per-server storage, configuration, atomic financial operations, helper confirmations/rejections/timeouts, active roster departures, replacement approval, audit rows, per-helper price snapshots, unused-slot refunds, owner-only credit commands, and legacy database migrations. The command-tree test checks the `/setup` subcommands and staff commands when `discord.py` is installed. Database tests do not replace live Discord permission and UI testing.

## Planned after Phase 5

- Operational invite tracking, attribution, eligibility, `/start-invite-event`, `/end-invite-event`, automatic expiry and reward payouts. Invite reward values in the dashboard are configuration only until this phase is implemented.
- Further live end-to-end tests, security review, monitoring/log-channel configuration and hosting setup.

## Security

Never commit `private-configs/tokens.env`, any database files, `data/`, `_backups/`, logs, or actual user/credit data. Rotate the Discord bot token if it has ever been exposed in a shared file or message.

## Logging note

The bot uses slash commands only and a single logging handler, so the Message Content Intent warning and duplicated Discord log lines should be gone. Optional voice dependency notices can still appear once because voice isn't used.


## Database file layout update (Phase 3.3)

The current database file is `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. On first launch, the database manager detects the earlier `data/guilds/<server_id>/guild.sqlite3` path and migrates it using SQLite's backup API. The old folder is retained under `data/legacy-database-archives/` as a timestamped archive. Existing balances, tickets, settings, and transaction history are preserved. If both old and new files already exist for the same server, startup stops rather than guessing which file is authoritative. Stop the bot before installing and keep a complete backup.

## Update 0.6.1 — contextual ticket controls and ephemeral cleanup

See `UPDATE_0.6.1_UX_EPHEMERAL_HOTFIX.md` for the latest ticket UI improvements and one-minute private-message cleanup policy. On successful ticket creation, the previous ephemeral wizard steps are deleted immediately.

Installation steps for this hotfix are in `UPDATE_0.6.1_INSTALL.md`.


## Update 0.6.2 — replacement selection and voting rules

- Requesters select their own proposed replacement members; staff approve or disapprove the exact list with `/admin_helper-replace approve` and `/admin_helper-replace disapprove`.
- A requester-proposed completion/cancellation begins at 1/N because the request itself counts as the requester’s approval. For a requester and two helpers, progress is 1/3, 2/3, 3/3.
- Any active helper rejection cancels a still-pending proposal, including when that helper previously confirmed. After all approvals are recorded and finalization locks, a late rejection is refused.
- Helper departure revokes channel access before the database removes the helper from the active roster. If Discord refuses the permission change, the roster remains unchanged and the log records the error code and effective permission state.


### Permission requirements hotfix

Discord requires the bot to have `Manage Roles` when editing channel permission overwrites. `Manage Channels` alone is not sufficient. The helper-leave and replacement approval flows preflight the effective permission; if Discord refuses an overwrite, the active helper roster and credits remain unchanged, and the diagnostic log includes the Discord error code plus effective/guild-level permission details.
