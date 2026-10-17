# Architecture and server identity

## Server ID and database routing

Discord interactions carry the server (guild) ID. The bot uses the ID from the current interaction or event to select the matching server database; `GUILD_ID` in `private-configs/tokens.env` controls slash-command synchronization scope only and must not be used to route database operations.

The current database path is:

```text
data/servers/<server_id>/blox_fruits_credit_system.sqlite3
```

Each database stores that server's accounts, balances, ticket records, services, settings, ticket number sequence, and transaction ledger. SQLite WAL/SHM sidecars, when present, sit alongside the main database file.

## Initialization points

- `/setup public_tickets` initializes or resolves the current server database before posting/updating the public Help Center panel.
- `/setup admin_dashboard` resolves the same server database, then posts or updates the dashboard in the channel where the command is invoked; it does not create a separate dashboard channel.
- Dashboard controls write to the current server's settings and service catalog.
- Guild-join and member-join events initialize server/account data as implemented by the current source.
- Balance and ticket callbacks resolve the database from the interaction's actual server ID.

## Ticket numbering

The next ticket number is allocated inside the ticket reservation write transaction. Numbers are isolated per server and cannot duplicate among currently open tickets in the same server. When a server has no open tickets, the next ticket starts again at `ticket-001`; closed records remain available for history, so a reused number may appear in a later record cycle.

## Dashboard and ticket permissions

Dashboard callback authorization is checked in code. Administrators and configured moderator roles may use permitted dashboard controls; only Administrators can edit the moderator-role allowlist. The dashboard does not change its host channel's visibility, so it should be posted in a staff-only channel when its settings must remain private.

The configured ticket staff baseline role and normal, non-managed roles above it in the role hierarchy receive ticket access according to the bot's permission logic. The bot does not grant Administrator. Discord's channel permission overwrite endpoint requires `Manage Roles`; `Manage Channels` alone is insufficient.

## Database migration

When the older `data/guilds/<server_id>/guild.sqlite3` exists and the current path does not, the application copies the old database through SQLite's backup API, verifies integrity, and retains the legacy copy under `data/legacy-database-archives/`. If both old and current files exist, startup stops rather than picking one. Always make a full backup before migrations and verify balances, tickets, settings, and ledger history afterward.
