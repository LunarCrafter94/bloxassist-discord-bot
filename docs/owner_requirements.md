# Owner requirements and implementation status

## Phase 1 — Completed and live-tested

- `/setup public_tickets` initializes the current server's database before posting the public panel.
- Each guild has its own SQLite database and settings/service catalog.
- Member balances, ticket records, transactions, service prices, and ticket numbers are isolated per guild.
- Ticket channels use sequential names (`ticket-001`, `ticket-002`, etc.) and the sequence resets only when that guild has no open tickets. Ticket-number workflow verified in Discord.
- Persistent panel/ticket callbacks resolve storage from the current interaction's guild ID.
- A guild-join event initializes a database when the bot joins a server.

## Phase 2 — Atomic credit transactions and ledger safeguards

- Ticket reservations atomically deduct requester credits, create the ticket row, allocate the ticket number, and write the reservation ledger row.
- Ticket completion atomically marks the ticket complete, pays all registered helpers, and records payouts. Repeated or concurrent completion attempts cannot pay a ticket twice.
- Ticket refunds atomically mark a ticket refunded, restore the reserved credits, and record the refund. Repeated or concurrent refunds cannot refund a ticket twice.
- SQL `BEGIN IMMEDIATE` serializes competing write operations, including separate database connections.
- Unique database indexes defend against duplicate reservation/refund/reward ledger entries, duplicate active ticket numbers, and reused idempotency keys.
- Balance additions/deductions have an atomic audited database method with actor, note, and optional idempotency key; `/add` and `/deduct` commands are not yet implemented.
- New member-account starting credits are recorded as a `starting_balance` ledger entry. Legacy historical accounts are not retroactively assigned fabricated ledger entries.
- Failed reservation, payout, or refund writes roll back balances, ticket status, ticket-number allocation, and ledger writes together.

## Phase 3 — Admin Dashboard and Help Center configuration

- `/setup admin_dashboard` posts/updates the dashboard in the current text channel without creating another channel. Each dashboard action checks Administrator/configured-moderator authorization in code. Owners should invoke it in a staff-only channel for privacy.
- Starting credits for newly created accounts, event catalog name/price/enabled state, and maximum helpers can be configured separately per guild. Existing account balances are not overwritten by starting-credit changes.
- Invite reward enabled/amount/default duration values are saved, but they do not issue rewards yet.
- The public Help Center channel/message IDs are saved. The panel can be updated, moved, and recreated if its message was deleted.
- Dashboard moderator role IDs are configured by an Administrator. A ticket staff baseline role grants channel access to itself and non-managed roles above it in the role hierarchy; open ticket overwrites are updated when the baseline changes. The bot does not grant Administrator.

Validation status: database configuration tests and the Phase 2 financial tests pass. Live Discord validation of channel creation, role overwrites and every dashboard component remains required.

## Phase 4 — Helper confirmation and roster workflow

- The requester proposes completion or cancellation; every currently active helper must confirm before the normal payout/refund runs.
- An active helper can reject a proposal. Requests expire after 15 minutes; timeout/rejection does not move credits.
- Helpers may leave. Their active status is removed and the bot denies their direct ticket access. If all helpers leave, the requester is automatically refunded, notified by DM when possible, and the ticket channel is scheduled for deletion after 10 seconds. Staff are notified when staff roles are configured.
- Requesters can ask for replacement helpers when an original multi-helper roster is short. Requesters select replacements privately, then staff use `/admin_helper-replace approve` or `/admin_helper-replace disapprove`; replacements are audited and do not alter the ticket's already-reserved total price.
- `/admin_complete` and `/admin_refund` provide explicit staff override paths only for authorized staff who are not participants in the target ticket. Ticket buttons always use normal helper confirmations, regardless of staff rank. Ticket payouts/refunds continue to use atomic transactions.

## Phase 5 — Staff credit moderation

- `/add member amount reason` and `/deduct member amount reason` are executable only by the actual Discord server owner. They are blocked while the owner participates in any open ticket; Administrators and configured moderator roles cannot use them.
- Every adjustment is atomic and records the acting user, optional reason, and idempotency key. A deduction exceeding the balance is rejected. Admin command authorization is independent of Manage Server/Manage Channels permissions and uses dashboard-configured moderator roles for delegated staff actions.
- `/admin_helper-replace approve` and `/admin_helper-replace disapprove` use the configured staff authorization policy and do not change credit balances.

## Per-helper service pricing (Update 0.6.3)

- The dashboard price is a fixed credits-per-helper rate. New tickets reserve the configured rate multiplied by the number of selected helpers.
- The ticket snapshots both the per-helper rate and total reservation. Changes to event prices do not change already-open tickets.
- At completion, each active helper receives one unit price. If no replacement fills a departed helper slot, that slot's unit price is returned to the requester. Existing tickets without a unit-price snapshot keep the legacy fixed-total/equal-split behavior.

## Future phases

- Operational invite tracking, attribution, eligibility, `/start-invite-event`, `/end-invite-event`, persisted automatic expiry and rewards. Dashboard invite reward settings still do not issue rewards at this stage.
- End-to-end launch checks, production hosting and monitoring/log-channel configuration.

Do not describe future-phase features as implemented until their code and acceptance tests exist.
