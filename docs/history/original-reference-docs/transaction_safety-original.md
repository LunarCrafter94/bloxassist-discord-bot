# Phase 2 — Credit transaction safety

## Main rule

Every operation that changes a balance and its corresponding financial history must commit as one SQLite transaction. If any statement fails, roll back the entire operation.

## Ticket lifecycle

- `ReserveTicket` obtains a write lock with `BEGIN IMMEDIATE` before reading balances or allocating ticket numbers. It creates any missing accounts, writes initial-balance ledger entries, deducts the price, creates the ticket, allocates its guild-local ticket number, and records `ticket_reservation` in one transaction.
- `CompleteTicket` obtains a write lock, transitions only an open ticket, credits each helper, writes each `ticket_reward` row, records any unused-helper-slot refund, and commits once. A ticket status transition, helper rewards, and any unused-slot refund cannot be partially committed.
- `RefundTicket` obtains a write lock, transitions only an open ticket, restores the reservation, writes a `refund` row, and commits once.
- A failure in any of those operations rolls back all database writes made by that operation.

## Database-level safeguards

The schema includes partial unique indexes so that:

- no two currently open tickets share the same ticket number in one guild database;
- a ticket cannot have duplicate `ticket_reservation` or `refund` entries;
- a ticket cannot have two `ticket_reward` entries for the same helper;
- one idempotency key cannot be applied more than once.

Closed ticket numbers may be reused after all tickets are closed, so the open-ticket-number index is intentionally partial.

## Auditing and idempotency

Transaction records contain amount, type, actor user ID when known, a note when supplied, and an optional idempotency key. The database-level `ApplyCreditAdjustment` method supports `direction="add"` or `direction="deduct"`. It rejects invalid amounts, refuses deductions that would create a negative balance, records the adjustment in the same transaction as the balance change, and recognizes a repeated idempotency key. A repeated identical request returns `duplicate`; the same key used for different transaction details returns `idempotency_conflict`.

The API is foundation for future `/add` and `/deduct` slash commands, but those commands are not part of Phase 2.

## Per-helper service pricing

New tickets snapshot `price_per_helper` and reserve `price_per_helper × selected helper count` in `required_credits`/`reserved_credits`. Service catalog edits do not modify an existing ticket snapshot. If helper replacements fill the original slots, each active helper receives the saved unit price. If slots remain unfilled at completion, the unused portion is returned to the requester in the same transaction as payouts. Legacy tickets with a NULL `price_per_helper` keep their prior total-price/equal-split behavior. Cancellation still refunds the full reservation.

## Starting credits

When a member account is first created, the initial balance is recorded as a `starting_balance` ledger entry in the same database transaction. Existing historical accounts are not assigned artificial starting-balance entries during migration because their true historical grant details may be unknown.

## Testing

The test suite verifies per-guild isolation, numbered ticket allocation, schema migration, once-only reservation/completion/refund, atomic and audited balance adjustments, duplicate idempotency behavior, simultaneous reservations, simultaneous completion attempts, and rollback after intentionally injected database errors.

## Operational cautions

- Stop the bot before copying SQLite databases for a manual backup. Preserve the `.sqlite3`, `-wal`, and `-shm` files together if they exist.
- Test using the development bot and controlled test accounts before using real credit balances.
- SQLite database files are private runtime data and must not be committed to GitHub.
