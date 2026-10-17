# Feature scope and implementation status

This document summarizes the feature behavior supported by the current Update 0.6.3 documentation. A feature described here should still be verified against the working source and tested in a development Discord server before being treated as production-ready.

## Implemented through Update 0.6.3

### Per-server storage and transactions

- Each server has an independent SQLite database and local ticket-number sequence.
- Ticket reservations, completion payouts, refunds, and balance adjustments use atomic transactions and audited ledger entries.
- Database safeguards help prevent duplicated reservations, payouts, refunds, ticket numbers among open tickets, and repeated idempotent adjustments.
- Initial starting credits are ledgered for newly initialized accounts; migrations do not fabricate historical starting-balance entries.

### Admin Dashboard and Help Center

- `/setup admin_dashboard` posts or updates a dashboard in the invoking text channel.
- `/setup public_tickets` posts or updates the public Help Center panel.
- Per-server settings include new-account starting credits, service catalog/prices, maximum helper count, Help Center placement, dashboard moderator roles, and a ticket staff baseline role.
- Updating starting credits does not rewrite existing balances.

### Ticket lifecycle and roster

- Requester-proposed completion/cancellation requires all active helpers to confirm. A helper may reject a pending proposal; timeout/rejection moves no credits.
- Helpers can leave and have access revoked. If every helper leaves, the requester is refunded and the ticket is scheduled for deletion.
- The requester selects proposed replacement helpers privately, then authorized staff approve or disapprove the submitted list.
- Staff escalation commands are distinct from the normal ticket buttons and are restricted for participants in the ticket they are trying to override.

### Credit moderation and pricing

- `/add` and `/deduct` can be executed only by the actual Discord server owner, and are blocked while the owner participates in any open ticket.
- Adjustments are atomic, audited, idempotent, and cannot deduct a balance below zero.
- Service price is stored as a per-helper unit rate for new tickets. Reserved total is unit rate multiplied by selected helper count. Old tickets without the unit-price snapshot preserve legacy payout behavior.

## Not implemented yet

Dashboard invite-reward settings can be saved, but invite usage attribution, eligibility checks, event start/end commands, automatic event expiry, and automatic reward payouts are not operational. Hosting, production monitoring, and full live acceptance testing are still follow-up work according to the current project notes.

## Acceptance rule

Do not promote a planned feature to “implemented” based solely on saved settings, a command being visible, or a passing database test. Confirm that the current code implements the complete flow and that the flow has been tested in a development server.
