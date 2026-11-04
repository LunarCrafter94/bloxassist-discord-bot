# BloxAssist v0.10.0 — Development Changelog

> **Status:** In development on `development/v0.10.0`. This is not a published release. Changes and tests may still be revised before a pull request or deployment.

## Credit and debt management

- Added atomic member-initiated debt repayment through `/repay-debt`.
- Supports partial and full repayment; a repayment cannot exceed either the member's available credits or outstanding debt.
- Future ticket and invite rewards automatically pay down outstanding debt before adding any remainder to the member's spendable balance. The original gross reward and the debt offset are both recorded in the ledger.
- Records each repayment as a distinct `debt_repayment` transaction in the existing ledger.
- Uses Discord interaction IDs as idempotency keys so retrying the same interaction cannot deduct credits twice.
- Serializes PostgreSQL repayment operations by locking the member's balance row.
- Updated `/balance` to show available credits, outstanding debt, and net position.
- Updated `/credits` to show available credits to all members, while limiting another member's debt details to that member, the server owner, Administrators, and configured dashboard moderators.

## Invite reliability and notifications

- Fixed transcript retention to delete Discord message objects without an unsupported audit-reason argument, allowing the 100-message rolling window to prune old posts.
- Treat an already auto-deleted ephemeral completion response as non-fatal, so a slow transcript-retention pass cannot make a completed ticket appear to have failed.

- Committed successful invite-attribution inserts and leave-penalty attribution updates before later explicit SQLite transactions begin, preventing nested-transaction failures on the shared per-server connection.
- Corrected invite reward audit-embed and inviter-DM line breaks so automatic debt-offset details render on separate lines.

## Credit history

- Added `/credit-history` with 10 entries per page, newest first.
- Members can view their own history. Viewing another member's history requires Administrator or configured moderator access.
- Reuses the existing transaction ledger; no parallel history table is introduced.

## Diagnostics

- Added owner-only `/diagnostics`.
- Checks database connectivity, core tables, audit-channel availability, and the bot's audit-channel permissions.
- Does not display connection strings, credentials, or secret values.

## Report navigation

- Added page navigation and optional category filtering to `/reports`.
- Database report queries now support bounded limits, offsets, status filters, and category filters.

## Tests added

- `tests/test_debt_repayment.py`: partial/full repayment, invalid amounts, no debt, insufficient credits, overpayment, idempotency conflicts, ledger entries, credit-history pagination, and automatic ticket-reward debt offsets.
- `tests/test_report_pagination.py`: non-overlapping pages, category filtering, and all-category pagination.
- `tests/test_credit_privacy.py`: self, owner, Administrator, configured moderator, ordinary member, Manage Server-only, and non-guild debt-visibility boundaries; verifies `/credits` only queries and displays debt after authorization.
- `tests/test_database_isolation.py`: verifies invite-attribution writes are committed before invite reward and penalty transactions begin.
- `tests/test_setup_commands.py`: verifies invite reward embeds and DMs use real line breaks.

## QA status — November 4, 2026

- Local unit suite previously passed 106 tests before the latest three regression tests were added. Rerun the full suite after pulling the latest branch; the current expected count is 111.
- Live Discord QA confirmed setup/dashboard initialization, public Help Center setup, SQLite/core-table/audit-channel diagnostics, balance and credit-history lookup, owner `/credits` lookup, manual `/penalty`, credit additions, partial/full debt repayment and overpayment rejection, invite event start/end, invite rewards with automatic debt offset, inviter leave penalties, and ticket creation/helper selection/completion/refunds.
- Ordinary non-staff `/credits` debt hiding is covered by unit tests but has not yet been independently verified with a non-staff Discord account.
- Automatic ticket-reward debt offset is unit-tested but has not been independently verified live.
- Non-empty report filtering/pagination and full transcript delivery/retention still need live Discord acceptance testing.
- Validate PostgreSQL behavior against a real PostgreSQL instance, not only the adapter unit tests.

