# Phase 2 — Atomic credit transactions and audit records

This package builds on the Phase 1 implementation that you confirmed in Discord: per-guild database folders and numbered ticket channels.

## What changed

- Explicit `BEGIN IMMEDIATE` transactions protect reservation, completion, refund, account initialization, and manual/system balance adjustments.
- Ticket status, the account balance updates, and ledger records commit or roll back together.
- Unique SQLite indexes provide a second layer of protection against duplicate financial ledger entries, duplicate active ticket numbers, and repeated idempotency keys.
- The transaction ledger now has `actor_user_id`, `note`, and `idempotency_key` fields. Existing databases are migrated at startup when the missing columns are detected.
- Newly created user accounts record their starting credit grant as a ledger entry.
- The `ApplyCreditAdjustment` database method establishes an audited, idempotent foundation for future `/add` and `/deduct` commands; these commands are not added in this phase.
- The ticket workflow passes actor IDs and notes to completion/cancellation/refund records when available.

## Before installation

1. Stop the bot with `Ctrl+C` and close DB Browser for SQLite.
2. Extract this ZIP to a staging folder. Do not install directly over the working project until the backup is confirmed.
3. From the extracted staging folder, run the backup script and explicitly target the live project folder:

   ```powershell
   .\tools\Backup-Phase1-Before-Phase2.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

   Type `YES` only after the bot and DB Browser are closed. The script copies source files and the full `data/` directory into `_backups`; it deliberately excludes the actual `private-configs/tokens.env`.
4. Leave the completed Phase 0 backup untouched.

## Install

Copy the contents of this package's project root into:

`D:\Repositories\Local\bloxfruits-helper-credit-bot`

Preserve your existing `.venv`, `.venv-old`, `_backups`, and actual `private-configs/tokens.env`. Never replace the actual token file with the blank `tokens.env` placeholder in a ZIP.

## Validate

From the project root, run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: 14 tests pass. These tests create temporary databases and do not use live guild databases.

## After tests pass

1. Start the bot using the development token.
2. In your development Discord server, create and complete a ticket, then confirm its helper payout occurs once.
3. Create and refund a ticket, then confirm the requester receives the reservation back once.
4. If testing an injected database failure, do that only in the automated test suite; don't manually add triggers to the live guild database.
5. Stop and close SQLite tools before making a fresh checkpoint.

## Scope boundary

Phase 2 does not implement the dashboard, role-based access policy, helper confirmations, helper leave/replacement workflow, invite events, or `/add` and `/deduct` commands. Those remain future phases.
