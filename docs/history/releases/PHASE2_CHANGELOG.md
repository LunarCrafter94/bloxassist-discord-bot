# Phase 2 changelog — Atomic Credit Transactions

## Included

- `BEGIN IMMEDIATE` write transactions around ticket reservations, completion payouts, refunds, account initialization, and balance adjustments.
- A balance change and its matching transaction ledger record are committed or rolled back together.
- Initial account credits are now recorded as `starting_balance` ledger entries for newly created users.
- Transaction records support `actor_user_id`, `note`, and `idempotency_key`.
- `ApplyCreditAdjustment` safely supports audited `add`/`deduct` operations for future admin commands. It is not exposed as `/add` or `/deduct` yet.
- Replaying the same idempotency key and operation does not apply the adjustment twice; reusing the key for different details is rejected.
- SQL partial unique indexes guard duplicate ticket reservations/refunds, duplicate per-helper rewards, duplicate initial balance grants, duplicate idempotency keys, and duplicate ticket numbers among currently open tickets.
- Ticket completion/cancellation/refund callbacks record the actor and a descriptive note when known.
- The test suite covers simultaneous reservations, simultaneous ticket completions, simultaneous idempotent adjustments, injected transaction failures/rollback, schema migration, guild isolation, and ticket numbering.

## Database migration

On opening a guild database, the application adds missing transaction audit columns and creates the new indexes. Existing balances and ticket records are retained. The old root-level Phase 0 `bot.db` is not imported into the per-guild data folder. Create a Phase 1 backup before installing this package.

Existing historic transactions are not retroactively assigned invented actor IDs or initial-balance entries. Starting-balance ledger rows are written for user accounts created after this update.

## Still future work

- `/add` and `/deduct` slash commands and staff permission configuration.
- Admin dashboard, configurable services/prices, starting-credit setting UI, ticket-access role policy, and Help Center channel selection.
- Helper confirmations/departure/replacement workflow and invite event rewards.

## Validation

Python compilation and 14 automated tests passed in the packaging environment. This is not a live Discord integration test; verify startup and ticket actions in the configured development server after installing.
