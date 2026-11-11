# BloxAssist v0.10.0 — Release Changelog

> **Status:** Published as the `v0.10.0` GitHub pre-release on November 10, 2026. This document records the released feature set and its verification.

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
- Added a numeric `user_id` lookup option to `/credits` and `/credit-history`, allowing staff to inspect retained accounts and transaction history for former server members without requiring a live Discord Member object. IDs are accepted as text to preserve the full 64-bit Discord snowflake range; missing former-member accounts are not silently created.
- Added a global application-command error handler that responds privately to invalid member selections and other command failures instead of leaving users with an unhandled interaction.

## Invite reliability and notifications

- Corrected the transcript-retention QA cleanup utility to delete `PartialMessage` objects without an unsupported `reason` argument and to tolerate fixture posts already removed by retention.
- Fixed transcript retention to delete Discord message objects without an unsupported audit-reason argument, allowing the 100-message rolling window to prune old posts.
- Treat an already auto-deleted ephemeral completion response as non-fatal, so a slow transcript-retention pass cannot make a completed ticket appear to have failed.
- Committed successful invite-attribution inserts and leave-penalty attribution updates before later explicit SQLite transactions begin, preventing nested-transaction failures on the shared per-server connection.
- Corrected invite reward audit-embed and inviter-DM line breaks so automatic debt-offset details render on separate lines.
- Added an owner-configurable Admin Dashboard option for inviter leave penalties: one penalty per invited member (default) or one penalty for each distinct attributed rejoin/leave cycle. Cycle tracking uses the Discord member join timestamp, stores a per-member cycle counter, and uses a cycle-specific idempotency key after the first cycle so duplicate events cannot charge twice. The first-cycle key remains backward-compatible with earlier builds. Leave handling matches the departing member timestamp to the stored cycle, preventing a delayed leave event from penalizing a newer rejoin. Existing SQLite and PostgreSQL databases add the new attribution columns automatically.
- Replaced raw UTC end-time displays for invite reward events with Discord relative-time countdowns in the start confirmation, audit embed, and Admin Dashboard. Discord renders the countdown in each viewer's locale; `run_forever` events display as Forever. Persisted end instants remain the source of truth for automatic expiry across restarts, and starting/ending/automatic expiry now refreshes the Admin Dashboard.

## Credit history

- Added a shared ephemeral Previous/Next paginator for `/credit-history`, `/ticket-history`, and `/reports`. Existing `page` options remain available for direct page jumps; ticket history retains its configurable 1–10 ticket page size and reports retain their category filter while navigating.
- Credit and ticket history pages are bound to the command invoker. Staff access is rechecked on every page interaction for another member's history and for staff-only ticket-history/report views. Controls are disabled after their short interaction session expires.
- Added offset pagination to retained ticket history queries so pages do not overlap.
- Members can view their own history. Viewing another member's history requires Administrator or configured moderator access.
- Reuses the existing transaction ledger; no parallel history table is introduced.

## Diagnostics

- Added owner-only `/diagnostics`.
- Checks database connectivity, core tables, audit-channel availability, and the bot's audit-channel permissions.
- Does not display connection strings, credentials, or secret values.

## Staff history and analytics

- Extended staff-only `/ticket-history` to accept either a current server member or a numeric `user_id`, so retained tickets can be reviewed for former members. Existing page-size and Previous/Next controls are preserved.
- Added a status filter to `/reports` for Open, Confirmed, Dismissed, and All reports. Category and status filters persist while navigating pages; reviewed reports show the recorded reviewer and review note where available.
- Added a private **Server Statistics** panel to the persistent Admin Dashboard. It summarizes tracked accounts, available credits, outstanding debt, tickets and reports by status, ledger entries, enabled services, and invite reward totals.
- Added staff-only `/member-activity`, combining a member's available balance, outstanding debt, transaction/ticket counts, recent credit transactions, and recent retained tickets. It accepts numeric IDs for former members and never creates an account during lookup.
- Added read-only database aggregate methods and regression coverage for statistics, member activity, former-member lookup wiring, report filters, and dashboard access.

## Report navigation

- Added page navigation and optional category filtering to `/reports`.
- Database report queries now support bounded limits, offsets, status filters, and category filters.

## PostgreSQL backup restore

- Updated `tools/Restore-Postgres-Server-Backup.py` to recognize and restore all 11 current v0.10.0 application tables, including `transaction_audit_deliveries`, `credit_debts`, and `invite_attributions`. The deletion order removes dependent rows before parent rows, and serial sequences are reset after import.
- Added regression coverage ensuring the PostgreSQL restore table list matches the full application schema and that foreign-key-dependent rows are deleted in a safe order.

- Live PostgreSQL restore QA passed on November 4, 2026: the encrypted 12:39:20 UTC backup for server `1560356320954294313` was decrypted, validated, and applied to schema `server_1560356320954294313`. All 11 tables were restored and row counts verified (165 rows total); serial sequences were reset by the restore utility. A subsequent live `/diagnostics` confirmed PostgreSQL connectivity, queryable core tables, and the configured `#ticket-audit` channel. The 128-test suite also passed locally (9.303 seconds) after the restore utility update.
- **Live Supabase PostgreSQL deployment:** As of November 11, 2026, the deployed BloxAssist bot has been operating on Supabase PostgreSQL for approximately three weeks. The application uses a separate schema for each Discord server. This supplements the restore QA above with live operation of the actual bot workload; it does not claim broad validation across multiple providers or large-scale deployments.

## Service catalog cleanup

- Removed Race Awakening from the default service catalog because it duplicates V4 Trials.
- Existing guild databases retain their previously configured services. This cleanup does not automatically remove Race Awakening from existing servers.

## Live acceptance testing — November 10, 2026

The v0.10.0 candidate underwent extensive live testing in a separate Discord test server.

### Verified

- Owner-only `/diagnostics` access and database connectivity checks.
- Dashboard access for Administrators and configured moderators, including restrictions on moderator-role management.
- Event Catalog viewing, selection, editing-modal prefill, and refresh behavior.
- `/member-activity`, `/credit-history`, and `/ticket-history` access controls, pagination, and former-member lookups.
- `/reports` status and category filters, pagination, and saved review information.
- Credit privacy: ordinary members can view another member's available credits but cannot view that member's debt.
- Transcript publication and content, including ticket metadata and conversation history.
- Audit-channel notifications and credit/invite-related audit entries.
- Graceful shutdown and startup behavior, including backup delivery.
- Restart persistence of balances, debts, tickets, reports, transactions, services, and invite-event data.
- Encrypted per-server backup decryption, manifest validation, and SQLite integrity check.

### Automated validation

- Python compilation completed successfully using `compileall`.
- The automated unittest suite passed: **173 tests, 0 failures**.

> **Deployment note:** BloxAssist remains in beta. Passing automated tests and acceptance testing in a dedicated Discord test server does not establish broad production readiness across multiple communities or at scale.
