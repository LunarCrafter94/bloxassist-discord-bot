# Changelog

This file consolidates the user-facing changes from the project's phase and hotfix notes. Older install guides are historical; use [`INSTALL.md`](INSTALL.md) for current local setup and maintenance instructions.

## Update 0.6.3 — Owner-only credit adjustments and per-helper pricing

- `/add` and `/deduct` are executable only by the actual Discord server owner. They are blocked while the owner is involved in any open ticket. Other Administrators and configured moderators are denied even if Discord displays the commands to them.
- Ticket buttons continue to use the normal requester/helper confirmation workflow; they never silently become staff overrides.
- Ticket-specific staff override and replacement-decision commands are blocked when the acting staff member is a participant or proposed replacement in that ticket.
- The configured service price is a per-helper rate. A ticket reserves the unit price multiplied by the selected helper count, snapshots both values, pays each active helper the stored unit rate, and returns the value of any unfilled slot. Cancellation refunds the full reservation. Legacy tickets retain their previous fixed-total behavior.
- Automated tests cover the added guards, pricing math, snapshots, unused-slot refunds, and legacy migrations. Live Discord validation remains required.

## Update 0.6.2 — Replacement selection and resolution voting

- Requesters select replacement candidates privately; authorized staff approve or disapprove the submitted list with `/admin_helper-replace approve` or `/admin_helper-replace disapprove`.
- The requester's completion/cancellation proposal counts as the first approval. Every active helper must confirm before finalization; any active helper can reject while the proposal is pending.
- Helper access changes are checked against Discord's actual permission behavior. If an overwrite change fails, the bot should not commit the corresponding roster change, and diagnostics record Discord permission/error details.
- Database migration adds the replacement-selection fields without rewriting balances or financial history.

## Update 0.6.1 — Ticket interface cleanup

- Completion/cancellation confirmations appear in a separate, contextual message instead of occupying the permanent ticket card.
- Ticket creation wizard messages are removed after successful creation, and private follow-up messages are scheduled to disappear after about 60 seconds.
- Persistent controls are refreshed on startup where the saved message still exists.

## Phase 5 — Staff credit moderation

- Added `/add` and `/deduct` with positive whole-number amounts, optional reasons, ephemeral responses, and transaction-ledger audit records.
- A deduction that would make a balance negative is refused. Adjustment operations are atomic and idempotent.
- Update 0.6.3 supersedes the original Phase 5 authorization rule: only the actual server owner can execute these two commands, subject to the open-ticket participation guard.

## Phase 4 — Helper confirmation and roster workflow

- Completion and cancellation require the requester's proposal and confirmation from every active helper. Rejection and timeout do not move credits.
- Helpers can leave open tickets. If no active helpers remain, the requester is refunded and the ticket is scheduled for deletion.
- Requester-selected replacement helpers require an authorized staff decision. Replacement changes do not increase the already-reserved ticket total.
- Staff override commands remain separate from the normal ticket buttons and are restricted for ticket participants.

## Phase 3.3 — Named server database files

- Standardized each server's database path to `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`.
- Legacy `data/guilds/<server_id>/guild.sqlite3` databases are copied through SQLite's backup API and integrity-checked when migrating to the new path. The legacy archive is retained. If both old and new files exist, the application stops instead of guessing which is authoritative.

## Phase 3 — Admin Dashboard and Help Center

- Added an in-channel Admin Dashboard and public Help Center panel, configurable starting credits for new accounts, event/service catalog settings, maximum helper count, Help Center placement, moderator roles, and ticket staff baseline access.
- Starting-credit changes apply to new accounts only; they do not rewrite existing balances.
- Invite reward values are configurable only; operational invite tracking and payouts are not implemented.

## Phase 2 — Atomic credit transactions

- Made reservations, payouts, refunds, account initialization, and adjustments transactional.
- Added a transaction ledger, audit fields, idempotency keys, and database-level duplicate protections.
- Added tests for server isolation, concurrency, duplicate operations, schema migration, and rollback after failures.

## Phase 1 — Per-server storage and numbered tickets

- Organized the Python package, introduced per-server SQLite databases, added setup-based public ticket initialization, and added ticket numbering that resets when the server has no open tickets.
