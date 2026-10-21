# BloxAssist v0.9.0 — Full Feature Changelog

**Release focus:** owner-controlled credit debt and penalties, reliable transaction auditing, invite management, ticket workflow safeguards, and maintained backup/storage operations.

> **Verification status:** These notes describe the code currently committed on `main`. The new debt and audit paths still need live Discord acceptance testing on a test server before being treated as production-verified.

## Credit balances, adjustments, and debt

- `/balance` lets a member check their balance; `/credits` lets a member check another member's balance.
- `/add` and `/deduct` are restricted in code to the actual Discord server owner. Other Administrators and configured dashboard moderators cannot use them to alter balances.
- `/add` and `/deduct` require a reason, reject invalid amounts and bot accounts, and record the actor, target, amount, reason, and resulting balance in the transaction ledger and configured audit channel.
- Ordinary deductions cannot make a balance negative. Changes use atomic database transactions and idempotency keys to prevent duplicate application.
- `/penalty` is an owner-only path for exceptional penalties. It consumes the target member's available credits first and records any unpaid remainder as separate credit debt; the user balance itself is never set negative.
- Members with outstanding debt cannot create/request a service ticket or be selected as a helper. Debt is stored separately from ordinary credit balances.
- Debt repayment from future rewards or earnings is not automatic in this version; the debt remains recorded until a future repayment workflow is implemented.

## Invite rewards and inviter leave penalties

- `/invite-event start` and `/invite-event end` manage persisted invite-reward events, with reward and duration defaults configured in the Admin Dashboard and optional command overrides.
- Timed events expire automatically. An unlimited-duration event can remain active until staff ends it.
- Invite rewards are recorded once per invited member per event and paid to the recorded inviter when the join is eligible during an active event.
- Invite attribution depends on reading invite-use counts and requires the bot's **Manage Server** permission. Ambiguous joins, missing inviter information, or Discord API failures are skipped rather than guessed.
- The server owner can configure **Inviter Leave Penalty** in the Admin Dashboard. A value of `0` disables it. When the bot has a saved inviter attribution for a member who leaves, it applies the configured penalty only to that inviter through the same credit-debt mechanism.
- Leave penalties are audit-logged and the bot attempts to notify the affected inviter. If attribution cannot be reliably determined, no penalty is assigned to unrelated members.

## Ticket creation, service catalog, and resolution

- `/setup public_tickets` creates or refreshes the public Help Center. Members can select a service/event, choose helpers, check their balance, create a ticket, or open the scam-report form.
- Each server has its own configurable service catalog. Prices are charged per helper; the reservation is the per-helper price multiplied by the selected helper count.
- Ticket reservations, service availability checks, and credit deductions are performed with database safeguards so insufficient balances or changed prices do not silently charge members.
- The requester proposes completion or cancellation, and the requester plus every active helper must confirm. Rejection or expiry does not trigger a payout/refund. Explicit staff override commands remain separate from the normal confirmation workflow.
- `/complete_ticket` and `/cancel_ticket` expose the normal ticket actions. `/admin_complete` and `/admin_refund` are staff escalation paths and include participant guards.
- Helpers can leave an open ticket. Replacement candidates require staff approval, and replacements do not increase the already-reserved total.
- On successful completion, active helpers receive the configured per-helper payout. Unfilled original helper slots are refunded to the requester. Cancellation and eligible failure paths return the reservation through a recorded refund transaction.
- When no active helpers remain, the bot follows the automatic refund workflow.
- The Admin Dashboard can configure a plain-text welcome message for new ticket channels. `{requester}`, `{helpers}`, `{ticket}`, and `{event}` placeholders are supported. The welcome is not pinned or an embed, mentions are prevented from pinging, and edits apply to new tickets only.

## Ticket numbering, transcripts, and history

- Active ticket channel labels are allocated separately from permanent transcript identifiers. Channel labels can start again at `ticket-001` when no tickets are open, while active labels are kept collision-free.
- Permanent transcript labels do not reset: `Ticket-001` through `Ticket-999`, then `Ticket-1│000`, `Ticket-1│001`, `Ticket-2│000`, and onward.
- Resolved/refunded tickets can publish text transcripts to the configured audit channel, including message text, authors, timestamps, embed content, and attachment references/URLs. Source attachment binaries are not all re-uploaded into the text transcript.
- If transcript delivery cannot be confirmed, the bot attempts to keep the ticket channel as a restricted moderator archive rather than deleting the evidence.
- `/ticket-history` lets staff find retained ticket records and transcript links.
- The audit channel retains at most 100 tracked transcript posts. Separately, the database retains up to 500 most recent closed ticket records with confirmed transcripts, along with open tickets and closed tickets needing recovery. When eligible old ticket rows are pruned, their ticket-linked ledger rows are pruned; current balances and standalone credit-adjustment rows are preserved.

## Audit log and credit movement history

- The configured **Audit Log Channel** receives ticket transcripts, credit-adjustment logs, ticket financial movements, invite rewards/penalties, scam reports/reviews, and startup/graceful-shutdown status messages.
- Manual additions/deductions include actor, affected member, signed change, new balance, and reason. Penalties include the target, penalty amount, reason, current debt, and resulting balance information.
- Ticket reservations, helper payouts, unused-slot refunds, and ticket refunds are written as individual movement entries with transaction IDs, amount, source/recipient, actor when available, ledger note, and timestamp.
- Ticket movement audit delivery is tracked so failed sends are eligible for retry during ticket finalization. Failure to write to Discord's audit channel does not roll back a credit transaction already committed to the database.
- Audit delivery requires the bot to access the selected channel with at least Send Messages and Embed Links. Transcript posting additionally needs the relevant file/message-history permissions.

## Scam reports and staff review

- The Help Center includes **Report Scam** for members to submit a report against another member.
- `/scam-reports` lists open scam reports for authorized staff. `/scam-review` records a confirmed/dismissed decision and review note.
- Reports are stored in the server database and routed to the Audit Log Channel, with supporting retained ticket-history references where available.

## Admin Dashboard and per-server controls

- `/setup admin_dashboard` posts or refreshes the private Admin Dashboard.
- Controls cover starting credits for new accounts, the event/service catalog, maximum helpers per ticket, invite-reward defaults, the inviter leave penalty, Help Center channel, dashboard moderator roles, ticket-staff role baseline, audit channel, ticket welcome message preview/reset, and dashboard refresh.
- Settings and service catalog entries are stored per Discord server. Changing starting credits affects newly created accounts only; it does not rewrite existing balances.
- Dashboard controls authorize each interaction in code. Only a Discord server Administrator can edit the dashboard moderator-role allowlist; inviter leave penalty is restricted further to the actual server owner.
- Persistent views can be restored when the saved Discord messages/channels remain accessible after a restart.

## Storage, encrypted backups, and migration

- SQLite is the default backend, with a separate database per server at `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`.
- PostgreSQL mode uses an isolated `server_<server_id>` schema per Discord server and is experimental until verified against the chosen live provider.
- `tools/Migrate-SQLite-To-Postgres.py` supports a guarded migration from local SQLite databases to fresh PostgreSQL server schemas. `tools/Restore-Postgres-Server-Backup.py` supports dry-run inspection and a confirmed restore of one server's PostgreSQL export.
- Optional per-server encrypted ZIP backups are delivered to a configured Discord DM using WinZip AES-256. SQLite snapshots use the SQLite backup API; PostgreSQL backups use a read-only repeatable-read snapshot/export.
- In the current backup loop, a snapshot is attempted after startup and then every **five hours**, plus a best-effort attempt at graceful shutdown. Archives over the conservative 8 MB Discord upload threshold are skipped and logged.
- Backups are best-effort: forced process kills, Discord DM settings, upload-size restrictions, API/provider failures, or an unavailable recipient may prevent delivery. Keep the password separate from the ZIP and maintain an independent recovery copy for critical production data.

## Runtime, reliability, and security

- Supports Python 3.13+ with `discord.py`, `python-dotenv`, `psycopg`, and `pyzipper` dependencies.
- `private-configs/credentials.env` or host-managed environment variables configure the Discord token, optional command-sync server, database backend/URL, and backup recipient/password. Legacy `runtime.env` and `tokens.env` paths remain compatibility fallbacks.
- `app.py` is a compatibility launcher; `RunBot.py` is the main entry point.
- Server-specific data isolation, database transactions, uniqueness/idempotency protections, conservative migrations, persistent component views, guarded Discord interaction responses, and structured logging support safe operation.
- Real tokens, database files, backups, logs, and member credit data should not be committed to Git or shared publicly.

## Known limitations and release checks

- Live Discord acceptance testing is still required for the recently added debt/leave-penalty behavior and detailed credit movement audit delivery.
- PostgreSQL is not considered production-verified solely by local tests or schema compatibility.
- Invite rewards and leave penalties are intentionally skipped when invite attribution is unavailable or ambiguous.
- Debt is tracked separately; automatic repayment from later income is not included.
- Transcript attachment references are URLs rather than a guarantee that all source attachment files are copied into the transcript.
- Encrypted DM backup delivery is best-effort and, according to the current implementation, runs after startup and every five hours rather than every hour.

## Primary commands

- Setup: `/setup admin_dashboard`, `/setup public_tickets`
- Credit lookup: `/balance`, `/credits`
- Owner credit management: `/add`, `/deduct`, `/penalty`
- Ticket workflow: `/complete_ticket`, `/cancel_ticket`, `/admin_complete`, `/admin_refund`
- Ticket history: `/ticket-history`
- Invite rewards: `/invite-event start`, `/invite-event end`
- Scam reporting/review: Help Center **Report Scam**, `/scam-reports`, `/scam-review`
