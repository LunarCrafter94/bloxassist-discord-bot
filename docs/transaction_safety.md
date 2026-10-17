# Credit transaction safety

## Core rule

A balance change and its corresponding ticket/account state change and ledger record must commit in the same SQLite transaction. If a required statement fails, the operation should roll back as a whole.

## Ticket operations

- **Reservation:** a write transaction obtains a lock with `BEGIN IMMEDIATE`, initializes a missing account when needed, records starting credits, deducts the reservation, creates the ticket, allocates the server-local ticket number, and writes the reservation ledger entry.
- **Completion:** the operation transitions only an eligible open ticket, credits the active helpers, records payouts, and returns the value of any unused original helper slot when applicable. These writes commit together.
- **Refund:** the operation transitions only an eligible open ticket, returns the reserved credits, and records the refund together.
- **Manual adjustment:** additions/deductions record the amount, actor, optional reason, and idempotency key with the balance change. Invalid amounts and deductions that would create a negative balance are rejected.

## Database-level protections

Partial unique indexes and idempotency safeguards defend against duplicate reservation/refund ledger entries, multiple rewards for the same helper on a ticket, duplicate open ticket numbers within a server, and repeated idempotency keys. A repeated identical adjustment is not applied twice; reusing a key for different details is rejected.

## Per-helper service pricing

New tickets store the configured unit price and the total reservation (`unit price × selected helpers`). Editing the service catalog does not rewrite existing ticket snapshots. Each active helper receives the saved unit rate at completion; a vacant original slot is refunded if no approved replacement fills it. Cancellation refunds the full reservation. Legacy tickets without a unit price snapshot keep their older fixed-total/equal-split behavior.

## Starting credits and history

A new member account's starting-credit grant is recorded as a `starting_balance` ledger entry. The migration does not create invented starting-credit ledger records for older accounts whose original grant details are unknown.

## Operational safety

- Stop the bot and close SQLite viewers before a manual file-copy backup or restore.
- Keep the `.sqlite3` main file together with any `-wal`, `-shm`, and journal sidecars.
- Run tests in the development virtual environment and use a development Discord server before testing financial operations live.
- Never commit databases or real balance/transaction data to GitHub.
