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

## PostgreSQL migration safety

- Updated the SQLite-to-PostgreSQL migration utility to include the v0.10.0 `transaction_audit_deliveries`, `credit_debts`, and `invite_attributions` tables. Fresh-target checks and deletion ordering cover these tables as well.
- Corrected the PostgreSQL migration fresh-target check to recognize the current seeded `ticket_welcome_message` setting, avoiding a false customized-settings rejection on a newly initialized schema.
- Corrected the PostgreSQL migration fresh-target check to recognize the current `next_ticket_channel_number` and `next_ticket_sequence` allocator settings as well.
- Added `tests/test_postgres_migration_coverage.py` to prevent application-table coverage from drifting behind the current schema.

## Tests added

- `tests/test_debt_repayment.py`: partial/full repayment, invalid amounts, no debt, insufficient credits, overpayment, idempotency conflicts, ledger entries, credit-history pagination, automatic ticket-reward debt offsets for an already-indebted helper, and continued requester-debt reservation blocking.
- `tests/test_report_pagination.py`: non-overlapping pages, category filtering, and all-category pagination.
- `tests/test_credit_privacy.py`: self, owner, Administrator, configured moderator, ordinary member, Manage Server-only, and non-guild debt-visibility boundaries; verifies `/credits` only queries and displays debt after authorization.
- `tests/test_database_isolation.py`: verifies invite-attribution writes are committed before invite reward and penalty transactions begin.
- `tests/test_setup_commands.py`: verifies invite reward embeds and DMs use real line breaks.
- `tests/test_transcript_message_deletion.py`: verifies transcript-retention message deletion uses the supported Discord API call.
- `tests/test_interaction_utils.py`: verifies an already-removed ephemeral original response is non-fatal.
- `tests/test_transcript_retention_cleanup.py`: verifies fixture cleanup can delete partial messages and tolerate posts already removed by retention.

## PostgreSQL live integration QA — November 4, 2026

- Installed and started local PostgreSQL 18.6 on Windows with a dedicated `bloxassist_qa` database and least-privilege login role; production Supabase was not modified.
- Migrated the QA SQLite database for server `1560356320954294313` into schema `server_1560356320954294313`. The migration imported and verified 11 application tables: users (4), services (7), settings (17), invite_events (5), tickets (6), transactions (49), transaction_audit_deliveries (14), invite_rewards (3), credit_debts (4), invite_attributions (1), and scam_reports (6), for 116 rows total.
- A read-only comparison confirmed SQLite integrity and exact column and row-content matches for all 11 source/target tables.
- Started the bot successfully in PostgreSQL mode; startup logs confirmed the server-specific PostgreSQL schema, Discord gateway connection, and synchronization of 18 slash commands.
- Live `/diagnostics` confirmed PostgreSQL reachable, core tables queryable, and the configured audit channel available.
- Live balance and credit-history reads succeeded. CZareth Playz's ticket #106 reward and automatic debt-repayment transactions (#449 and #448) were present after migration; the account showed 50 available credits and zero debt. Hollow Saviour showed zero available credits and zero debt.
- Live PostgreSQL credit-write QA passed: owner-authorized `/add` added 1 credit to Hollow Saviour and produced an audit entry; `/deduct` removed that credit and produced a separate audit entry. The subsequent balance check returned to zero available credits and zero debt.
- Additional live PostgreSQL ticket QA passed: ticket #107 automatically refunded its 100-credit reservation when all helpers left; ticket #108 completed through the normal requester/helper approval workflow and recorded a 100-credit helper reward; ticket #109 completed through the moderator-override path with the helper-confirmation bypass explicitly recorded in the transaction note; ticket #110 was refunded through the moderator refund path. Each ticket produced its corresponding transcript and ledger entry, including refund/reward transaction records.
- Live PostgreSQL invite attribution/reward QA passed for invite event #6: Hollow Saviour invited CZareth Playz using invite code `S66TuDwbr`; BloxAssist attributed the join to Hollow and awarded 100 credits. The event notification reported Hollow's new balance as 200 credits and remaining debt as zero.
- Live PostgreSQL invite-reward debt-offset QA passed in two additional cases. After a 250-credit manual penalty left Hollow with 50 debt, CZareth's departure triggered the configured 50-credit inviter leave penalty against Hollow, bringing debt to 100. During invite event #7, a 100-credit reward was fully applied to that 100-credit debt, leaving balance 0 and debt 0. After a further 50-credit penalty created 50 debt, event #8 awarded another 100-credit reward: 50 paid the debt and the remaining 50 was added to available credits, leaving balance 50 and debt 0. This verifies both full and partial automatic debt offsets for invite rewards on PostgreSQL.
- Live PostgreSQL member-initiated debt repayment QA passed: after Hollow Saviour incurred 50 credits of debt, an additional 100-credit owner adjustment gave sufficient available funds; `/repay-debt` repaid the full 50-credit debt and left 50 available credits. The debt-repayment notification confirmed zero remaining debt. This verifies full repayment on PostgreSQL; a distinct partial repayment that leaves some debt outstanding remains to be tested.

- The automated DM backup warning appeared because backup recipient/password settings were not configured; this did not prevent startup or PostgreSQL operation. Backup delivery/restore has not yet been live-verified against PostgreSQL.
- The 119-test unit suite passed before migration. These tests supplement, but do not replace, live verification of the complete PostgreSQL ticket and invite workflows.

## QA status — November 4, 2026

- Pulled the latest `development/v0.10.0` branch and ran the full suite: **114 tests passed in 14.295 seconds** (`OK`). This includes the regression tests proving that an already-indebted helper can be reserved and that a requester with debt remains blocked.
- Live Discord QA confirmed setup/dashboard initialization, public Help Center setup, SQLite/core-table/audit-channel diagnostics, balance and credit-history lookup, owner and Administrator `/credits` debt visibility, ordinary-member suppression of another member's debt field, manual `/penalty`, credit additions, partial/full debt repayment and overpayment rejection, invite event start/end, invite rewards with automatic debt offset, inviter leave penalties, and ticket creation/helper selection/completion/refunds.
- The non-staff `/credits` privacy path was verified live with a target member who had non-zero outstanding debt: an ordinary member without authorized roles could see the target's available credits but was not shown the debt field.
- Live Discord QA confirmed automatic ticket-reward debt offset on ticket #105: CZareth Playz received a 100-credit gross reward, 50 credits were applied to outstanding debt, and the final state was 50 available credits with zero remaining debt. On ticket #106, CZareth already had 50 debt and zero available credits **before reservation**; Hollow Saviour successfully reserved 100 credits and CZareth was assigned as the helper. After completion and participant approvals, ledger transaction #448 recorded the 50-credit automatic debt repayment and transaction #449 recorded the separate 100-credit gross ticket reward. The subsequent `/balance` check confirmed 50 available credits and zero debt. This verifies the previously failing indebted-helper assignment flow end to end.
- Ticket #106's persistent database/transcript/ledger ID appeared in a Discord channel named `ticket-001`. The channel name is reused when no other tickets occupy that slot; this is expected channel naming, not an ID mismatch.
- Live Discord QA verified non-empty `/reports` pagination with six reports: page 1 returned five reports (#6–#2), page 2 returned the remaining report (#1), and the Bug / Bot Issue category filter returned only reports #2 and #1.
- Full transcript delivery, direct history links, and 100-message rolling transcript retention passed live QA.
- Validate PostgreSQL behavior against a real PostgreSQL instance, not only the adapter unit tests.
