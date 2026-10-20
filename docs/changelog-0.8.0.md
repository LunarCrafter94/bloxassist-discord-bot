# BF World Credit Test Bot — Update 0.8.0

## The Big Update: Separate Ticket and Transcript Numbering, Custom Welcome Messages, and Cleaner Shutdown

This development release separates reusable ticket-channel numbering from permanent transcript identifiers, adds an Admin Dashboard editor for the plain-text welcome sent into new tickets, and improves Ctrl+C shutdown output. It builds on the v0.7.1 hotfix work.

### 1. Separate Ticket Channel Numbers from Transcript Identifiers

- Active ticket channel numbers are now stored separately from the permanent transcript sequence.
- New ticket channels use labels such as `ticket-001`, `ticket-002`, and so on.
- If no tickets are open when the next ticket is created, the channel-number sequence starts again at `ticket-001`.
- If tickets remain open, the allocator continues forward and skips every number currently used by an active ticket.
- The internal database `ticket_id` remains the stable primary key; old ticket records are not deleted or renumbered.

### 2. Permanent Transcript Labels and the Vertical Divider

- Transcript identifiers never reset, even after all ticket channels have closed or the bot restarts.
- Labels run from `Ticket-001` through `Ticket-999`.
- At ticket/transcript sequence 1,000, the display becomes `Ticket-1│000`, then `Ticket-1│001`; sequence 2,000 becomes `Ticket-2│000`.
- The same permanent label is used for transcript filenames, transcript posts, ticket history, and references to retained transcript posts.
- The `│` character is the Unicode vertical box-drawing divider. Channel names using this character still need to be tested against Discord's live channel-name validation before production use.
- Pre-v0.8.0 database rows retain a legacy-label fallback so existing channels and their posted transcript titles remain recognizable.

### 3. Keep Only the 100 Most Recent Transcript Posts

- The configured Audit Log Channel retains at most 100 tracked ticket transcript posts. When the 101st transcript is successfully posted and indexed, the oldest tracked transcript message is removed, leaving transcripts 002–101 in the simple first-100 example.
- Separately, the database retains the 500 most recent closed ticket-history rows whose transcripts were confirmed as saved, plus all open tickets and closed tickets that still need transcript recovery.
- When old ticket-history rows are pruned, transaction rows attached to those removed tickets are deleted first to preserve referential integrity. Current user balances, settings, services, and standalone credit-adjustment records are preserved.
- If the new transcript upload/indexing fails, or if Discord cannot verify or delete an old post, the bot skips database-history pruning for that run so it does not lose references to potentially retained transcript messages.
- Pruning is best-effort; missing permissions or Discord API failures are logged and may require manual cleanup.

### 4. Editable Plain-Text Ticket Welcome Message

- Added a **Ticket Welcome Message** control to the Admin Dashboard.
- The bot sends the configured content as an ordinary message inside each newly created ticket channel. It is not pinned and is not an embed.
- Supported placeholders are `{requester}`, `{helpers}`, `{ticket}`, and `{event}`.
- The setting is stored per server. Leaving the editor blank disables the extra welcome message for future tickets.
- Editing the template does not rewrite messages in existing ticket channels. Mentions in the custom text are not allowed to trigger pings.
- The existing ticket information embed and workflow buttons remain in place.

### 5. Cleaner Ctrl+C Shutdown

- The launcher catches the final `KeyboardInterrupt` raised by `asyncio.run()` when Ctrl+C is used, suppressing the traceback for a normal manual stop.
- The existing async-client shutdown path remains responsible for closing the Discord client, database resources, and attempting the configured final backup/status notice.
- A shutdown backup is still best-effort; check the logs to confirm whether it succeeded. A forced process termination can bypass cleanup.

### 6. Database Migration and Compatibility

- Added `tickets.channel_ticket_number` and the per-server `next_ticket_channel_number` setting.
- Existing SQLite and PostgreSQL schema setup adds the new nullable channel-number column and `transcript_saved` marker when absent. Existing ticket rows are not renumbered.
- History pruning is conservative: only closed tickets with a confirmed transcript are eligible. All open tickets and closed tickets without a confirmed transcript are preserved even if that means the database contains more than 500 total ticket rows.
- SQLite may reuse pages freed by deletes without immediately shrinking the database file on disk; a VACUUM operation is a separate maintenance action and should only be run after a backup.
- Added a database uniqueness guard for channel numbers assigned to open tickets.
- Kept the monotonic `ticket_sequence` and existing internal `ticket_id` semantics for transcript references and financial audit history.

### 7. Verification

- Added tests for permanent labels through 10,000, including `1│000`, `2│000`, and `10│000`.
- Added tests for channel-number reuse after all tickets close, collision avoidance while tickets remain open, and separation of the channel number from the permanent transcript sequence.
- Added tests for legacy-label compatibility and plain-text welcome placeholder replacement.
- Current local validation: **79 tests ran: 78 passed and 1 skipped** because `discord.py` is not installed in this build environment. Python source compilation passed.

### Important Testing Notes

This is a development build, not yet a live-verified release. Before deploying it, test the Admin Dashboard modal, create a real test ticket, verify plain-text welcome delivery, test a channel name containing `│`, complete/cancel tickets, and confirm transcript 101 removes only the oldest tracked transcript post. Also verify Ctrl+C shutdown logs and backup outcome. PostgreSQL operation and remote-host behavior have not been live-tested here.

### Follow-up patch — Helper-proposed completion and cancellation

- Active assigned helpers may propose ticket completion or cancellation through the normal ticket workflow.
- These proposals do not bypass approval: the proposer counts as the first approval, and the requester plus every other active helper must approve.
- The requester and active helpers can confirm or reject a pending proposal; rejection cancels the proposal without moving credits.
- Nonparticipants remain blocked, and configured staff override paths remain separate and auditable.
