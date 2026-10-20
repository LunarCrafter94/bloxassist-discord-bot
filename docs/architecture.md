# Architecture and server identity

## Server ID and database routing

Discord interactions provide the current server ID. The database manager uses that ID to resolve the server's state; `GUILD_ID` in `private-configs/credentials.env` only scopes slash-command synchronization and never routes business data.

SQLite path:

```text
data/servers/<server_id>/blox_fruits_credit_system.sqlite3
```

PostgreSQL path: one schema per Discord server, named `server_<server_id>`, inside the database URL configured through `DATABASE_URL`. The remote backend is newly introduced and remains experimental until tested against the chosen live provider.

The database tables hold accounts/balances (`users`), tickets and transcript references (`tickets`), balance/audit ledger rows (`transactions`), per-server configuration (`settings`), service/event catalog (`services`), timed invite events (`invite_events`), unique invite rewards (`invite_rewards`), and scam reports/reviews (`scam_reports`).

## Initialization and settings

- `/setup public_tickets` resolves and initializes the server's database before posting/updating the public Help Center.
- `/setup admin_dashboard` posts/updates the dashboard in the command's channel and saves its channel/message IDs.
- Dashboard values are stored per server in the `settings` key-value table and `services` catalog table, never in the environment file. The environment file contains only runtime credentials/connection settings.
- On startup, persistent dashboard/help/ticket views are restored when their saved Discord message/channel remains accessible.
- New servers have their own database/schema and defaults; starting-credit changes apply only to accounts created later.

## Ticket numbering and history

Each server maintains a permanent `settings.next_ticket_sequence` for transcript identifiers and a separate `settings.next_ticket_channel_number` for reusable ticket channel labels. A transcript identifier uses `Ticket-001` through `Ticket-999`, then `Ticket-1│000`, `Ticket-1│001`, `Ticket-2│000`, and so on; it never resets, preventing duplicate transcript names. Channel numbers are allocated separately, avoid collisions with active tickets, and restart at `001` when no tickets are open. Existing v0.7.1-and-earlier channel labels remain readable through a legacy-label fallback. The database `ticket_id` remains the internal primary key.

Every successful ticket completion/refund attempts to publish a text transcript into the configured Audit Log Channel and stores that Discord message/channel reference in the ticket row. The transcript contains message content, author IDs/names, timestamp, embed text/fields, and references to attached files. If the bot can't confirm successful transcript delivery, it attempts to hide the source channel from participants and move it into a moderator-review archive instead of deleting the evidence.

Only the 100 most recent tracked transcript posts are retained in the configured server log channel. When the 101st tracked transcript is successfully posted and indexed, the oldest tracked transcript message is deleted. Separately, the database retains the 500 most recent closed ticket rows with confirmed transcripts, plus active tickets and closed tickets still needing transcript recovery. When such an old ticket row is pruned, its ticket-linked transaction rows are deleted first; current balances, settings, services, scam reports, and standalone credit-adjustment rows remain. A failed new transcript upload or uncertain Discord cleanup skips database-history pruning so the bot does not discard references to possibly retained evidence.

## Audit, reports, invite events

`transactions.actor_user_id` and notes record the actor/reason for moderator/ticket actions when applicable; automated changes have a system/automatic actor label. The Admin Dashboard's `audit_log_channel_id` routes human-readable audit logs, scam reports, invite event activity, rewards, and transcripts to one selected channel.

Invite rewards are event-scoped and unique per invited member per event. The bot compares invite use counts before/after a member joins; if attribution isn't unique or required Discord invite information isn't available, it skips the reward rather than guessing. The bot needs `Manage Server` to read invite uses. Event expiry is checked by the periodic runtime loop.

## Credentials and database migration

New installations use `private-configs/credentials.env` or equivalent host secret settings. `DISCORD_TOKEN`, `DATABASE_URL`, and backup encryption passwords must not be committed. Legacy `tokens.env` and `runtime.env` paths are still read as compatibility fallbacks.

`tools/Migrate-SQLite-To-Postgres.py` imports each local server DB into an empty target schema and refuses to overwrite non-empty or customized targets. Always stop the bot, keep a recoverable SQLite copy, inspect the migration's row counts, and verify balances/tickets/ledger before switching production.
