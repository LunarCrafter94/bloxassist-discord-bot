# Phase 4 — Helper confirmation and ticket roster workflow

## Included

- Ticket completion is requester-proposed. Every currently active helper must confirm before normal completion pays credits.
- Ticket cancellation is requester-proposed. Every currently active helper must confirm before normal cancellation refunds the reserved credits.
- Helpers can reject a pending resolution request. Rejection cancels the proposal without moving credits.
- Confirmation requests expire after 15 minutes. A background loop clears expired requests and posts a notice; no payout or refund occurs on timeout.
- `/admin_complete` and `/admin_refund` remain staff override paths and now accept Administrators, Manage Server staff, or configured dashboard moderator roles. Overrides are recorded in the transaction ledger.
- Helpers can leave an open ticket. Their active status is removed, their channel access is denied, and the departure is audited.
- If every helper leaves, the requester is automatically refunded and the ticket channel is scheduled for deletion after 10 seconds. The bot notifies the requester by DM when possible and posts a staff review notice.
- When the original helper roster has gaps and exactly one active helper remains, the requester selects replacement members privately. Authorized staff use `/admin_helper-replace approve` or `/admin_helper-replace disapprove` to approve/disapprove the submitted list.
- Replacement changes are recorded in the ledger; the originally reserved ticket price does not change. Completion splits that fixed amount among the final active helpers.
- Open ticket messages are refreshed with the new persistent controls when the bot starts.
- New database columns are migrated in place; existing open tickets retain their original helpers as the active roster.

## Safety rules

- A user cannot confirm or reject unless they are a currently active helper for that ticket.
- Duplicate confirmation clicks never count twice.
- Helper departures and replacement changes clear old resolution votes so a changed roster cannot inherit prior approvals.
- Completion/refund continue using the atomic Phase 2 database transactions.

## Permission note

Discord requires `Manage Roles` to edit channel permission overwrites. `Manage Channels` alone is not sufficient for helper departure and replacement permission edits.

## Validation

Compilation passed. Automated database/configuration tests pass, including new checks for helper confirmation, rejection, timeout, departures, replacement approval, and unchanged reservation prices. The Discord command-tree test requires `discord.py` and was skipped in this packaging environment.
