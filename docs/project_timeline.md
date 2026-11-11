# BloxAssist project timeline

This timeline records milestones from the `#〔📢〕bot-announcements` channel export and the GitHub release record. Times are Philippine Time (PHT, UTC+8) unless stated otherwise.

The early BF World Credit Test Bot update numbers are historical announcement labels. They are not presented here as GitHub tags or formal published releases.

## October 2026 — Early development

- **October 17, 2026, 4:58 PM — Updates 0.4, 0.4.1, and 0.5 announced.** Per-server credit isolation, per-guild database directories, and numbered ticket channels were introduced in the announcements.
- **October 17, 2026, 10:36 PM — Update 0.6 announced.** The announcement described the combined Phase 4 and Phase 5 work: helper confirmations, safer ticket handling, replacement-helper requests, and staff-managed credit adjustments.
- **October 18, 2026, 1:49 AM — Update 0.6.3 announced.** The cumulative hotfix covered ticket UI cleanup, replacement-helper selection and approval, resolution voting, permission safeguards, and per-helper service pricing.
- **October 19, 2026, 9:55 AM — Update 0.7.0 announced.** The announcement covered invite reward events, audit logging, ticket history and transcripts, scam reporting, transcript retention, ticket numbering, and initial hosting/database/backup preparation.
- **October 19, 2026, 10:31 AM — Hotfix 0.7.1 announced.** Persistent ticket numbering, the 100-transcript limit, and a scam-report modal fix were highlighted.
- **October 20, 2026, 7:15 AM — Update 0.8.0 announced.** Ticket-channel numbering was separated from permanent transcript identifiers; the update also included the editable plain-text ticket welcome message and cleaner shutdown behavior.
- **October 20, 2026, 10:42 AM — Update 0.8.1 announced.** Helpers could propose ticket completion or cancellation.
- **October 20, 2026, 8:47 PM — Semi-permanent bot hosting announced.** The channel post named control.heavencloud.in as the host and Supabase as the data store.
- **October 20, 2026, 9:56 PM — BloxAssist v0.8.0 tester reports opened.** A testing form and instructions were shared with testers.
- **October 21, 2026, 1:15 PM — Bot-Hosting.net deployment announced.** The post stated that the bot was hosted on Bot-Hosting.net and its data was stored in Supabase. It also noted the free-host renewal requirement as understood at that time.
- **October 21, 2026, 7:59:19 PM — GitHub v0.9.0 pre-release published.** This timestamp comes from the GitHub release record (14:59:19 UTC). The real-server channel then posted the v0.9.0 development update at 9:57 PM, highlighting credit debt, inviter leave penalties, expanded audit logs, and stronger owner-only credit-management permissions.

## November 2026 — v0.10.0

- **November 4, 2026 — PostgreSQL backup-restore QA.** The v0.10.0 changelog records a successful encrypted backup restore into the server-specific PostgreSQL schema, followed by live diagnostics and a 128-test run.
- **November 10, 2026 — v0.10.0 acceptance testing and release.** The release candidate passed 173 automated tests and compilation, and underwent live testing in a separate Discord test server. GitHub published `v0.10.0` as a pre-release at **10:22:29 PM PHT**.
- **November 11, 2026, 8:13 AM — v0.10.0 announcement in the real server.** The channel export shows the announcement timestamp as 8:13 AM without repeating the calendar date; November 11 is assigned from the current-day context of the export shared for this timeline.

## Hosting and database duration note

The announcement history records Supabase use by **October 20, 2026**, and specifically records Bot-Hosting.net with Supabase on **October 21, 2026**. By November 11, those dated milestones are approximately three weeks earlier. This is an announcement-based timeline, not a claim that the exact database provisioning or first successful production write happened at those precise times.

The current live deployment uses Supabase PostgreSQL with separate schemas per Discord server. Its five-hourly encrypted per-server backup behavior is documented in [Backup and restore](backup_and_restore.md) and [Installation and operations](installation_and_operations.md).
