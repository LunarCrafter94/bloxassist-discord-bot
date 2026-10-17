# Phase 3.3 — Named server database layout

## What changed

- Current path: `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. The file name describes that it contains the bot's credits, tickets, server settings, event catalog, and transaction ledger.
- The app now uses `DatabaseManager.ForServer` and calls the directory `servers` in current logs and docs. `ForGuild` remains as a small compatibility alias for older external scripts. Discord-required terms such as `guild_id` inside Discord interactions and existing SQL columns are intentionally retained.
- Existing `data/guilds/<server_id>/guild.sqlite3` files are migrated on first access using SQLite's backup API and checked with `PRAGMA integrity_check`. The old folder is kept under `data/legacy-database-archives/` for rollback/reference.
- If the new and old database both exist for a server, startup stops instead of guessing which one is authoritative.
- Added tests to prove balances and settings survive the migration and that collisions never get silently overwritten.

## Safety

Stop the bot and close DB Browser for SQLite before installing. Make a full backup including all of `data/`. Never delete the old database archive until you have verified balances, tickets, and history in the new database after live testing. The root-level Phase 0 `bot.db` is still not automatically imported.
