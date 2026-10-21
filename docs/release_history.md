# Release history and changelog

This page summarizes the current development release and its user-facing changes. It is the maintained release summary linked from the root [README](../README.md). Older installation and changelog notes remain archived in [`history/releases/historical-installation-and-changelogs.zip`](history/releases/historical-installation-and-changelogs.zip); use the current documentation for current setup instructions.

## v0.9.0 — Credit debt, inviter penalties, and full audit history

Full feature inventory: [`changelog-0.9.0.md`](changelog-0.9.0.md).

- Added owner-only `/penalty` with separate credit-debt tracking, debt-based service participation guards, and an owner-configurable inviter-leave penalty.
- Expanded credit movement auditing so ticket reservations, payouts, refunds, adjustments, and applicable penalties/rewards have explicit ledger/audit entries with recorded actors and reasons where available.
- Preserves the v0.8.0 ticket, transcript, Help Center, dashboard, invite reward, reporting, encrypted backup, and database migration workflows documented in the complete feature notes.

> **Acceptance status:** v0.9.0 is published as a pre-release. Live Discord testing of debt, leave-penalty, and transaction-audit workflows is still required before treating them as production-verified.

### Post-tag development changes on `main` (not included in the existing v0.9.0 tag)

- Added a **Continue** button below the multi-member helper selector during ticket creation.
- Replaced the Help Center's **Report Scam** button with **Report Issue**, including categories for scams/fraud, bugs, ticket/credit issues, member misconduct, and other concerns. Selecting a member is optional for general reports.
- Placed report controls below the category/member selectors; report selection prompts are now removed after a report is saved or after five minutes of inactivity.
- Replaced the staff commands with `/reports` and `/report-review` for general report listing and review.
- Fixed the Inviter Leave Penalty modal label to comply with Discord's 45-character limit.

These post-tag changes are committed to `main` but still require live Discord acceptance testing before a follow-up release.

## Hotfix 0.7.1 — Ticket numbering, transcript retention, and Discord interaction errors

Full user-facing notes: [`changelog-0.7.1.md`](changelog-0.7.1.md).

> **Status: local hotfix build; live Discord acceptance testing still required.** The Python source compiled and the local automated suite ran 71 tests, with 70 passing and one skipped because `discord.py` was unavailable in this validation environment.

### Fixed

- **Never-reset ticket numbering:** New tickets use `1-001` through `1-100`, then `2-101` through `2-200`, then `3-201`, etc. The suffix is global and persists through an empty queue and restarts. Existing v0.7.0 ticket labels are preserved as legacy labels rather than silently rewriting already-posted transcripts.
- **100-transcript rolling retention:** The configured log channel keeps at most 100 tracked transcript posts. After a new transcript is successfully posted and indexed, the oldest tracked transcript post is deleted. This does **not** delete its ticket or transaction history from SQL, and a failed new upload does not trigger deletion of old evidence.
- **Scam-report modal validation:** Shortened the long text-input label to meet Discord's 45-character label limit and added a safe fallback if Discord rejects the modal.
- **Expired interaction handling:** Ephemeral response/defer/edit/follow-up helpers gracefully handle Discord error `10062` (`Unknown interaction`). Once a token expires, later reply attempts for that interaction are skipped to avoid repeated exception traces. The user may need to retry an action after connectivity stabilizes.
- **Slow-connection recovery logs:** The Gateway reconnect/resume behavior remains enabled. The uploaded log shows the session resuming successfully; these network disconnect warnings are not treated as fatal and were not disabled.

### Verification performed

- `python -m compileall -q source-files tests` passed.
- `python -m unittest discover -s tests -v`: 71 tests discovered, 70 passed, one skipped because `discord.py` was not installed in this Linux validation environment.
- Added checks for sequence transition at tickets 100/101, persistence of the next sequence, the `2-101` label, and legacy-label formatting.

### Still requires live acceptance testing

- Verify ticket creation and transcript pruning in a Discord test server, including bot permission to read history and delete messages in `Text〔📜〕tickets-log`.
- Validate slow-network interaction behavior with the deployed `discord.py` version. Discord can reject any interaction whose response token has already expired; the hotfix suppresses repeated failures but cannot make an expired token valid again.
- The warning `bot needs Manage Server permission` means invite attribution will remain disabled until the bot has that permission in the affected guilds. `PyNaCl` and `davey` warnings only say voice support is unavailable; this bot's ticket/credit functions do not require voice support.

## Development 0.7.0 — Phase 6, auditing, transcripts, and hosting preparation

> **Status: development build; not production-verified.** Python compilation and the local automated test suite passed, but real Discord workflows, PostgreSQL against a live provider, hosting behavior, and backup delivery still require acceptance testing.

### Added

- **Timed invite-reward events:** Added `/invite-event start` and `/invite-event end`, configurable reward and duration defaults, persisted event state, and automatic expiration checks. Invite attribution uses observed invite-use changes and skips ambiguous attribution instead of guessing. The bot needs the appropriate Discord permission to inspect invite usage.
- **Configurable audit log channel:** Added an Admin Dashboard setting for the audit/logging channel. Credit adjustments, financial ticket outcomes, invite events/rewards, scam reports, startup notices, and graceful-shutdown notices can be written there.
- **Ticket transcripts and history:** Resolved/refunded tickets can publish text transcripts to the configured audit channel. Added `/ticket-history` to locate available ticket history and transcript records.
- **Scam reporting and review:** Added the Help Center's Report Scam flow, `/scam-reports` for authorized staff to review open reports, and `/scam-review` to record a confirmed/dismissed decision and audit note.
- **Bounded transcript retention:** Keeps at most 100 tracked transcript posts per server. When a new transcript would exceed the limit, the oldest tracked transcript message is removed after the new transcript is successfully posted and indexed. If transcript publication fails, the bot attempts to preserve the ticket channel for moderator-only review rather than discarding the evidence.
- **Ticket-number cycling:** Ticket labels progress through `ticket-001` to `ticket-100` and cycle after the 100th ticket; numbering no longer resets just because a server has no open tickets. The database's internal ticket ID remains unique, and historical ticket/transaction rows are retained independently of transcript-message pruning.
- **Configurable database backend:** Added `DATABASE_BACKEND` and `DATABASE_URL` configuration for the experimental PostgreSQL backend, with per-server schemas to preserve data isolation. Local SQLite remains the default.
- **SQLite-to-PostgreSQL migration utility:** Added a safety-first migration tool that checks target schemas, refuses to overwrite non-empty targets, imports per-server data, resets serial sequences, and compares row counts. It requires explicit confirmation and manual validation before production cutover.
- **Per-server encrypted backup ZIPs:** Added separate ZIP archives for each server's database, encrypted with WinZip AES-256 and delivered to the configured Discord DM on an hourly schedule. A graceful-shutdown backup is also attempted; a forced process kill cannot guarantee that final backup. Oversized or failed sends must not be treated as successful.
- **Runtime credential-file convention:** Added `private-configs/credentials.env.example` for the broader set of authentication/configuration settings, with legacy token-file fallback retained. Real credentials remain excluded from source control.
- **Hosting-test launcher and update tooling:** Added `app.py` for hosts that expect a single Python entry file, plus `tools/Apply-Local-Update-0.7.0.ps1` for applying the update to a local worktree while preserving credentials and private backup folders.
- **Documentation cleanup:** Updated the root README to display `assets/branding/bot-client_banner.png` and `assets/branding/bot-client_icon.png`, link to maintained documentation, and point historical phase install/changelog notes to the ZIP archive under `docs/history/releases/`.

### Changed

- Credit changes have both a database ledger record and a configurable audit-channel entry where the operation's audit event applies; DM notifications alone are not the audit record.
- The Admin Dashboard now exposes the audit channel and invite-event defaults alongside the existing per-server settings and event catalog.
- Event removal is implemented as disabling an event rather than hard-deleting it, which avoids breaking historical ticket references.
- New-install configuration uses `private-configs/credentials.env`; local SQLite remains the default unless PostgreSQL is explicitly configured.
- Historical root-level installation/changelog material is consolidated in an archive. The maintained documentation index and release-history page remain in `docs/`, without adding another root README.

### Fixed and hardened

- Invite attribution does not award credits when invite usage cannot be attributed unambiguously.
- Transcript retention prunes only after the new transcript has been successfully posted/indexed, reducing the risk of deleting the previous record when a new upload fails.
- The v0.7.0 sequence advanced independently of the number of currently open tickets; v0.7.1 replaces the wraparound labels with a never-reset global sequence.
- PostgreSQL adapter transaction/context handling and SQL compatibility are covered by unit tests.
- The local update script was corrected to use actual PowerShell line breaks rather than literal escaped newline text.

### Verification performed

- Python compilation completed successfully.
- `tools/Test-Project.ps1` completed successfully in the user's local Windows/Python environment: **66 tests ran, 0 failures**.
- Automated tests cover per-server SQLite isolation, atomic/idempotent credit operations, invite-event timing and reward behavior, scam-report storage, ticket-number cycling, legacy database migration, PostgreSQL adapter behavior, and command-registration guards.

### Not yet verified / known limitations

- PostgreSQL support has not yet been accepted against a live SQL provider; do not switch a production bot to PostgreSQL until migration, balances, tickets, settings, transactions, and restore are verified.
- Real Discord acceptance testing is still needed for invite attribution and required permissions, dashboard interaction, transcript delivery/retention, scam review, startup/clean-shutdown notices, and DM backup delivery.
- Hourly scheduling and a graceful-shutdown backup are best-effort. A forced kill, host outage, Discord DM restrictions, upload-size limit, or scheduled-job delay can prevent a backup from arriving on time.
- The earlier pinned-message request has been clarified and implemented in the v0.8.0 development draft as an ordinary editable plain-text ticket welcome message; see [`changelog-0.8.0.md`](changelog-0.8.0.md).
- Hosting deployment and provider-specific automatic crash recovery have not been verified. Keep the currently working deployment until a replacement passes live acceptance testing.

## Update 0.6.3 — Owner-only credit adjustments and per-helper pricing

- `/add` and `/deduct` restricted to the actual server owner, with a participation guard and ledger reasons.
- Ticket prices are stored as per-helper rates; reservations and unused-slot refunds are atomic.
- Ticket lifecycle and replacement-approval safeguards retained.

## Earlier releases

The previous phase and hotfix installation/changelog notes are stored in [`history/releases/historical-installation-and-changelogs.zip`](history/releases/historical-installation-and-changelogs.zip). They describe historical behavior and should not be used as current setup instructions. See [`history/README.md`](history/README.md) for archive context.


## Update 0.8.0 — Development draft

This draft replaces the v0.7.1 shared counter behavior with separate channel labels and permanent transcript identifiers. Do not treat it as a published release until live Discord acceptance tests pass.

- **Separate ticket counters:** active ticket channel labels can restart at `ticket-001` when no tickets are open, while permanent transcript labels always advance and do not repeat. Active labels cannot conflict with existing open-ticket labels.
- **Large transcript identifiers:** `Ticket-001` through `Ticket-999`, then `Ticket-1│000`, `Ticket-1│001`, `Ticket-2│000`, and so on.
- **Admin-editable welcome:** added an Admin Dashboard modal for an ordinary plain-text ticket welcome message. It is not pinned or an embed, supports `{requester}`, `{helpers}`, `{ticket}`, and `{event}`, and affects new tickets only.
- **Bounded retention:** retain the 100 most recent tracked Discord transcript posts and separately the 500 most recent closed ticket records with confirmed transcripts. Open tickets and closed tickets needing transcript recovery are preserved. Ticket-linked ledger rows are deleted only when the corresponding old ticket-history rows are pruned; current balances and standalone credit-adjustment ledger entries remain.
- **Graceful Ctrl+C:** catch the final terminal interrupt after the client's async context shutdown, avoiding a normal-stop traceback while preserving best-effort backup/status handling.
- **Tests:** added channel-counter reuse tests, transcript number formatting through 10,000, legacy channel-label fallback, welcome placeholder rendering, and bounded database-history pruning tests.

**Validation status:** Python compileall passed. The local suite ran 79 tests: 78 passed and one Discord command-registration test was skipped because `discord.py` is unavailable in this environment. Live channel naming with `│`, Admin Dashboard modal behavior, transcript 101 retention, database history 501st-record pruning in a live workflow, shutdown backup delivery, and PostgreSQL migration still require live verification.
