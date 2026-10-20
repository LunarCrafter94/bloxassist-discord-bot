# BF World Credit Test Bot — Hotfix 0.7.1

## The Hotfix: Persistent Ticket Labels, Transcript Limits, and Interaction Error Fixes

This hotfix addresses the ticket-number behavior requested by the owner and the errors shown in the October 19, 2026 console log. It builds on Update 0.7.0 without changing successful Gateway reconnection behavior.

### 1. Persistent Ticket Counting

- New ticket labels now use a global number rather than wrapping back to `001`.
- The first sequence is `1-001` through `1-100`.
- Ticket 101 is labeled `2-101`; ticket 200 is `2-200`; ticket 201 is `3-201`.
- The sequence remains saved after all tickets close and after the bot restarts.
- Existing 0.7.0 tickets keep their legacy labels so already-posted transcript names are not silently rewritten.
- The unique database `ticket_id` is unchanged and continues to identify a ticket internally.

### 2. Maximum of 100 Transcript Posts

- The configured `Text〔📜〕tickets-log`/Audit Log Channel keeps at most 100 tracked ticket transcript posts per server.
- When transcript 101 is successfully uploaded and indexed, the bot removes the oldest tracked transcript post so the channel returns to 100 retained transcripts.
- Only the Discord transcript message is pruned. The ticket row, credit transactions, and SQL history are preserved.
- If the new transcript cannot be uploaded or indexed, the bot does not delete an older transcript to make room.
- Unrelated audit entries and scam reports are not included in the ticket-transcript count and are not deleted by this retention rule.

### 3. Scam-Report Modal Fix

- Shortened the “What happened?” text-input label to fit Discord’s 45-character limit.
- Added a guarded fallback if Discord rejects a future modal, instead of allowing the button callback to crash noisily.

### 4. Expired Discord Interaction Handling

- The `/setup admin_dashboard` `Unknown interaction` (`10062`) trace came from attempting to respond after Discord had expired the interaction token, which can happen when connectivity is unstable or a response is delayed.
- Ephemeral response, defer, edit, and follow-up helpers now handle expired interaction tokens and skip subsequent reply attempts for that same expired interaction.
- The bot cannot revive an interaction whose token has expired. The user may need to run the command or press the button again once the connection is stable.

### 5. Slow Internet and Gateway Reconnection

- Automatic reconnect/resume behavior remains unchanged.
- The supplied console log repeatedly shows the Gateway session successfully resuming after disconnects. Those warnings are not by themselves fatal errors, so the hotfix does not suppress them or disable reconnection.
- The `PyNaCl` and `davey` messages only indicate that optional voice support is unavailable; ticket and credit workflows do not require voice support.

### 6. Permission Note

- Invite reward tracking still requires the bot to have **Manage Server** permission to inspect invite-use counts. The log reports that this permission is currently missing in two servers, so invite attribution will not work there until permissions are corrected.

### 7. Verification

- Python compilation passed.
- 71 automated tests were discovered: 70 passed and one was skipped because `discord.py` was not installed in this validation environment.
- Tests cover per-server database isolation, credit transactions, legacy database migration, monotonic ticket sequence allocation, the `2-101` boundary label, legacy-label compatibility, and existing PostgreSQL adapter logic.
- Actual Discord transcript deletion, modal presentation, interaction expiry under a slow live network, hosting, and database provider behavior still require acceptance testing in the test server.

### Update 0.7.0 — Previous Release

- Added timed invite-reward events, audit-channel records, ticket transcripts/history, scam reports, configurable storage backend groundwork, encrypted backup delivery, and hosting documentation.
- The previous 0.7.0 ticket labels wrapped from 100 back to 001; this behavior is replaced for new tickets in hotfix 0.7.1.
