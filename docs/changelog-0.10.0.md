# BloxAssist v0.10.0 — Development Changelog

> **Status:** In development on `development/v0.10.0`. This is not a published release. Changes and tests may still be revised before a pull request or deployment.

## Credit and debt management

- Added atomic member-initiated debt repayment through `/repay-debt`.
- Supports partial and full repayment; a repayment cannot exceed either the member's available credits or outstanding debt.
- Future ticket and invite rewards automatically pay down outstanding debt before adding any remainder to the member's spendable balance. The original gross reward and the debt offset are both recorded in the ledger.
- Members with outstanding debt may still be assigned as ticket helpers; their earned ticket rewards are applied to debt first. Members with debt remain unable to create/reserve new tickets as requesters.
- Records each repayment as a distinct `debt_repayment` transaction in the existing ledger.
- Uses Discord interaction IDs as idempotency keys so retrying the same interaction cannot deduct credits twice.
- Serializes PostgreSQL repayment operations by locking the member's balance row.
- Updated `/balance` to show available credits, outstanding debt, and net position.
- Updated `/credits` to show available credits to all members, while limiting another member's debt details to that member, the server owner, Administrators, and configured dashboard moderators.

## Invite reliability and notifications

- Corrected the transcript-retention QA cleanup utility to delete `PartialMessage` objects without an unsupported `reason` argument and to tolerate fixture posts already removed by retention.
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

- `tests/test_debt_repayment.py`: partial/full repayment, invalid amounts, no debt, insufficient credits, overpayment, idempotency conflicts, ledger entries, credit-history pagination, automatic ticket-reward debt offsets for an already-indebted helper, and continued requester-debt reservation blocking.
- `tests/test_report_pagination.py`: non-overlapping pages, category filtering, and all-category pagination.
- `tests/test_credit_privacy.py`: self, owner, Administrator, configured moderator, ordinary member, Manage Server-only, and non-guild debt-visibility boundaries; verifies `/credits` only queries and displays debt after authorization.
- `tests/test_database_isolation.py`: verifies invite-attribution writes are committed before invite reward and penalty transactions begin.
- `tests/test_setup_commands.py`: verifies invite reward embeds and DMs use real line breaks.
- `tests/test_transcript_message_deletion.py`: verifies transcript-retention message deletion uses the supported Discord API call.
- `tests/test_interaction_utils.py`: verifies an already-removed ephemeral original response is non-fatal.
- `tests/test_transcript_retention_cleanup.py`: verifies fixture cleanup can delete partial messages and tolerate posts already removed by retention.

## QA status — November 4, 2026

- Rerun the full suite after pulling the latest branch; the current expected count is 114. The latest debt-helper regression test verifies that an already-indebted helper can be reserved and that completed-ticket rewards repay debt before crediting the remainder.
- Live Discord QA confirmed setup/dashboard initialization, public Help Center setup, SQLite/core-table/audit-channel diagnostics, balance and credit-history lookup, owner and Administrator `/credits` debt visibility, ordinary-member suppression of another member's debt field, manual `/penalty`, credit additions, partial/full debt repayment and overpayment rejection, invite event start/end, invite rewards with automatic debt offset, inviter leave penalties, and ticket creation/helper selection/completion/refunds.
- The non-staff `/credits` privacy path was verified live: a member without roles saw another member's available credits but no debt field. The target's debt was zero during this check; hiding a non-zero debt value has not been separately demonstrated live.
- Live Discord QA confirmed automatic ticket-reward debt offset on ticket #105: CZareth Playz received a 100-credit gross reward, 50 credits were applied to outstanding debt, and the final state was 50 available credits with zero remaining debt. This live test applied the penalty after reservation to work around the then-existing helper-debt restriction; selecting an already-indebted helper still needs live confirmation after this change.
- Live Discord QA verified non-empty `/reports` pagination with six reports: page 1 returned five reports (#6–#2), page 2 returned the remaining report (#1), and the Bug / Bot Issue category filter returned only reports #2 and #1.
- Full transcript delivery, direct history links, and 100-message rolling transcript retention passed live QA.
- Validate PostgreSQL behavior against a real PostgreSQL instance, not only the adapter unit tests.

