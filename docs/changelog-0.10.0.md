# BloxAssist v0.10.0 — Development Changelog

> **Status:** In development on `development/v0.10.0`. This is not a published release. Changes and tests may still be revised before a pull request or deployment.

## Credit and debt management

- Added atomic member-initiated debt repayment through `/repay-debt`.
- Supports partial and full repayment; a repayment cannot exceed either the member's available credits or outstanding debt.
- Records each repayment as a distinct `debt_repayment` transaction in the existing ledger.
- Uses Discord interaction IDs as idempotency keys so retrying the same interaction cannot deduct credits twice.
- Serializes PostgreSQL repayment operations by locking the member's balance row.
- Updated `/balance` and `/credits` to show available credits and outstanding debt. The personal balance view also shows the net position.

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

- `tests/test_debt_repayment.py`: partial/full repayment, invalid amounts, no debt, insufficient credits, overpayment, idempotency conflicts, ledger entries, and credit-history pagination.
- `tests/test_report_pagination.py`: non-overlapping pages, category filtering, and all-category pagination.

## Verification still required

- Run the complete unittest suite against the branch.
- Validate PostgreSQL behavior against a real PostgreSQL instance, not only SQLite.
- Test Discord command registration and owner/staff permission boundaries in a separate test server.
- Verify audit-log delivery and report navigation in Discord before deployment.
