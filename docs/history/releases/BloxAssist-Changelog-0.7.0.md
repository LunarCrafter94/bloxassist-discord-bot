# BF World Credit Test Bot — Update 0.7.0

## The Big Update: Invite Events, Auditing, Ticket History, and Hosting Preparation

This release combines the Phase 6 invite-reward work, auditing and transcript features, ticket-number rules, and the first configurable remote-database/backup groundwork into one development update. It builds on the safeguards and ticket workflow from Update 0.6.3.

### 1. Invite Reward Events

- Added `/invite-event start` and `/invite-event end` so authorized staff can start and end an invite-reward event.
- Added per-server settings for invite reward credits and default event duration.
- Added persisted event state and automatic expiration checks so an event can end when its configured duration expires.
- Invite attribution uses observed Discord invite-use changes. If the inviter cannot be identified unambiguously, the bot skips the reward rather than guessing.
- The bot needs the appropriate Discord permissions to inspect invite usage. Live testing is still required to confirm attribution and event behavior in the target server.

### 2. Credit Auditing and the Configurable Audit Channel

- Added an Admin Dashboard setting for the server's audit/logging channel.
- Credit adjustments record the acting user and reason in the database transaction ledger; applicable financial and administrative events are also sent to the configured audit channel.
- Added audit-channel entries for ticket outcomes, invite events/rewards, scam-report decisions, and bot startup/graceful-shutdown notices.
- Audit logs are separate from requester DMs: a private message is not treated as the canonical audit record.

### 3. Ticket History, Transcripts, and Scam Reporting

- Added text transcript generation for resolved/refunded tickets and posting to the configured audit channel.
- Added `/ticket-history` to locate saved ticket history and transcript records.
- Added a Report Scam flow to the Help Center, `/scam-reports` for authorized staff to review open reports, and `/scam-review` to record a confirmed/dismissed decision with an audit note.
- If transcript publication fails, the bot attempts to preserve the ticket channel for moderator-only review rather than discarding the evidence.
- Transcript delivery, channel permission changes, and report review still need live Discord acceptance testing.

### 4. Transcript Retention and Ticket Numbering

- The transcript log keeps a maximum of **100 tracked transcript posts per server**. When a new transcript is successfully posted and indexed beyond that limit, the oldest tracked transcript post is removed.
- The bot prunes the oldest transcript only after publishing and indexing the new one successfully. The database ticket and transaction history are retained independently of transcript-message pruning.
- Ticket labels progress from `ticket-001` through `ticket-100` and then cycle; numbering no longer resets merely because no tickets are currently open.
- Internal database ticket IDs remain unique even when the displayed ticket-number cycle repeats.

### 5. Event Catalog and Admin Dashboard Changes

- Added a **Remove Event** capability using disable/deactivate behavior rather than hard-deleting the event. This preserves references from historical tickets.
- The Admin Dashboard exposes audit-channel configuration and invite-event defaults alongside existing starting-credit, helper-limit, event-price, Help Center, moderator-role, and ticket-staff settings.
- The owner's request for an editable pinned message remains deferred because its exact content, placement, and expected behavior have not yet been clarified.

### 6. Configurable Database Backend and Migration Preparation

- Added `DATABASE_BACKEND` and `DATABASE_URL` configuration for the experimental PostgreSQL backend; SQLite remains the default.
- Kept each Discord server's data isolated through server-specific database handling rather than combining every server's balances and ticket records.
- Added a safety-first SQLite-to-PostgreSQL migration utility that checks target schemas, refuses to overwrite non-empty targets, imports per-server data, resets serial sequences, and compares row counts.
- Migration requires explicit confirmation and manual validation. PostgreSQL has not yet been accepted against a live provider, so do not switch a production deployment to it yet.
- Added `private-configs/credentials.env.example` as the template for the broader runtime credentials/configuration file. Legacy `tokens.env` fallback remains available, and real secrets are excluded from source control.

### 7. Per-Server Encrypted ZIP Backups and Runtime Notices

- Added an encrypted ZIP backup for **each server's database**, rather than archiving the whole `data/` directory as one undifferentiated backup.
- ZIP contents use WinZip AES-256 encryption and are intended for delivery to the configured Discord DM on an hourly schedule.
- Added a graceful-shutdown backup attempt. A forced termination, host outage, Discord DM restriction, attachment-size limit, or delayed scheduled run can prevent a backup from arriving on time.
- Backup errors must be reported as failures; an attempted send is not counted as success unless Discord accepts the upload.
- Added startup and graceful-shutdown status notices to the configured audit channel. A forced process kill cannot reliably run the bot's shutdown handler.

### 8. Hosting, Credentials, and Documentation

- Added `app.py` for hosting platforms that expect a single Python entry file.
- Added `tools/Apply-Local-Update-0.7.0.ps1` to apply the local update while preserving Git metadata, credentials, and private backup folders.
- Updated the root README to display `assets/branding/bot-client_banner.png` and `assets/branding/bot-client_icon.png`, and to link to maintained documentation.
- Consolidated historical installation/changelog notes into `docs/history/releases/historical-installation-and-changelogs.zip` rather than adding another root-level README or changelog.

### 9. Verification Performed

- Python compilation completed successfully.
- `tools/Test-Project.ps1` completed in the local Windows/Python environment: **66 tests ran, 0 failures**.
- Automated tests cover per-server SQLite isolation, atomic/idempotent credit operations, timed invite events/reward behavior, scam-report storage, ticket-number cycling, legacy database migration, PostgreSQL adapter behavior, and Discord command-registration/staff-guard checks.
- This test run did not start the bot or prove live provider integration. One test may be skipped in environments where `discord.py` is unavailable.

### 10. Not Yet Verified / Known Limitations

- PostgreSQL support has not been accepted against a live SQL provider. Verify balances, ticket history, settings, transaction ledgers, and restoration before production cutover.
- Real Discord acceptance testing remains necessary for invite attribution and permissions, dashboard interactions, transcript delivery and retention, scam review, audit-channel notices, and DM backup delivery.
- Hourly scheduling and graceful-shutdown backups are best-effort, not guarantees against data loss. Keep an independent recovery option and test restoration.
- Hosting deployment and provider-specific automatic crash recovery have not been verified. Keep the currently working deployment until a replacement passes live tests.

## Update 0.6.3 — Owner-Only Credit Adjustments and Per-Helper Pricing

- Restricted `/add` and `/deduct` to the actual server owner, with a participation guard and audit reasons.
- Stored event prices as per-helper rates; reservations, payouts, and unused-slot refunds use the ticket's saved price and transactional safeguards.
- Retained ticket lifecycle, replacement approval, and credit consistency protections.
