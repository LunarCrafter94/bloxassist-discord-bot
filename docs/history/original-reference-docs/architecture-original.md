# Architecture and server identity

## Guild ID source

Discord supplies `interaction.guild_id` for interactions in a server. Guild events expose `guild.id`; member events expose `member.guild.id`. The bot does not need the invoking user to have permission to copy the ID in Discord's UI.

## Database initialization points

- `/setup public_tickets`: call `DatabaseManager.ForServer(interaction.guild_id)` before creating/updating the public Help Center panel; save its channel and message IDs.
- `/setup admin_dashboard`: resolves the current guild database, posts/updates the dashboard in the invoking text channel, and saves dashboard channel/message IDs. It does not create a channel.
- Dashboard forms write configurable values into that guild's `settings` and `services` tables; missing Phase 3 keys are seeded with `INSERT OR IGNORE` so existing saved values are preserved.
- `on_guild_join`: initializes a guild database when the bot joins a server.
- `on_member_join`: resolves the member's server database and uses that database's configured starting credits.
- Balance and ticket interactions: resolve storage using the actual interaction guild ID.

## Isolation boundary

Each `GuildDatabase` represents one Discord server and is backed by `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. The class keeps its internal Discord API terminology, while the on-disk layout uses the clearer server-based name. SQLite's WAL/SHM sidecars remain beside that main file. Persistent views retain the `DatabaseManager`, not a database connection for one server, then route each callback through the current interaction's guild ID.

## Ticket numbering

Each guild's database stores `ticket_number` and the next number in its own `settings` table. Allocation occurs inside the ticket reservation write transaction, so requests handled by the same guild database cannot receive the same number. The number advances while at least one ticket has `status = 'open'`. When the open-ticket count becomes zero, the next reservation starts at 1 again, formatted in channel names with a minimum width of three digits (`ticket-001`). Closed ticket records remain in the database for history; their old numbers may therefore appear on historical records after the channel name is reused in a later cycle.

## Slash-command sync

`GUILD_ID` in `private-configs/tokens.env` controls command synchronization scope only. It does not determine database routing.


## Dashboard security and channel permissions

Dashboard callbacks verify that the user is a server Administrator or holds a configured moderator role; the Moderator Roles setting itself is Administrator-only. The dashboard does not rewrite channel visibility. Use a staff-only channel for confidentiality; configured roles and Administrators are authorized to operate dashboard controls by callback checks. A configured ticket staff baseline role applies `View Channel`, `Send Messages`, and `Read Message History` to that role and higher, non-managed roles. No permission overwrite grants Administrator.

## Database file migration

The database manager now treats the project-level `data/` as its root. Current storage uses `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. If the older `data/guilds/<server_id>/guild.sqlite3` is found and the new path is absent, it archives the legacy directory and copies the database through SQLite's backup API into the new file. It validates the copy with `PRAGMA integrity_check`. If the new file already exists alongside the legacy file, it stops instead of choosing a potentially stale database.
