# Phase 4 + Phase 5 — Installation

This package is built from the **Phase 3.3 named-server database layout**: `data/servers/<server_id>/blox_fruits_credit_system.sqlite3`. It does not revert to the old `data/guilds/<server_id>/guild.sqlite3` layout and does not include a new Phase 3.3-only install cycle.

## Before installing

1. Stop the running bot with `Ctrl+C`.
2. Close DB Browser for SQLite and any other program using the databases.
3. Extract this ZIP to a temporary/staging folder.
4. Open PowerShell in that extracted package folder and run the backup script against the existing project:

   ```powershell
   .\tools\Backup-Phase3.3-Before-Phase4-5.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

5. Type `YES` only after confirming the bot and database tools are stopped. Check that the dated backup exists. The script copies the current source, tests, project files, and all of `data/`; it does not move or delete working files and deliberately excludes the real `private-configs\tokens.env`.

## Install

Copy the package contents into:

`D:\Repositories\Local\bloxfruits-helper-credit-bot`

Allow the updated source, tests, documentation, and tools to overwrite earlier versions. Preserve `.venv`, `.venv-old`, `_backups`, `data`, and the actual `private-configs\tokens.env`. Do not replace your real token file with `tokens.env.example`.

## Validate locally

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected packaging result: compilation succeeds and the database/configuration tests pass. The command-registration test will run only if `discord.py` is installed in this environment; in this packaging environment that test was skipped because the library was unavailable. These tests use temporary databases and do not touch your live server databases.

## Phase 4 live test checklist

Use the development server and test accounts with small balances:

1. Create a ticket with two helpers.
2. Request completion. Verify the requester receives a private acknowledgement, the ticket channel shows a proposal, and neither helper is paid after only one confirmation.
3. Have the first helper confirm; verify the second helper is still required. Have the second helper confirm; verify the payout happens once and the channel is deleted after 15 seconds.
4. Create another ticket and propose cancellation. Verify no refund after only one helper confirmation; the final active helper confirmation should refund the reservation once and delete the channel after 10 seconds.
5. Test rejection and a 15-minute timeout path. Neither action should move credits.
6. Have a helper leave. Verify their ticket access is denied. If all helpers leave, verify the requester is refunded once, a DM is attempted, staff are notified when staff roles are configured, and the channel is deleted after 10 seconds.
7. For a ticket that originally had multiple helpers, request replacements. Verify a non-staff user cannot add anyone; staff can use `/admin_helper-replace approve` or `/admin_helper-replace disapprove` only after the requester submits a selection. Check the reserved price did not change and any remaining vacancies can be filled through the same approved request.
8. Restart the bot with an open ticket and verify the new persistent controls are attached to existing ticket panel messages.

## Phase 5 live test checklist

1. As the actual Discord server owner, while not participating in any open ticket, run `/add member amount reason`. Confirm the target balance increases and the reply is private.
2. Run `/deduct member amount reason`. Confirm the balance decreases and a reason/actor is recorded.
3. Attempt to deduct more than the target's balance. Confirm it is refused and the balance remains unchanged.
4. Try `/add` and `/deduct` as a configured moderator and as another Administrator. Both must be denied, even though Discord may display the commands to Administrators.
5. Try the commands as the server owner while involved in any open ticket. They must be denied until that participation is resolved.
6. Check the transaction ledger for `admin_add` and `admin_deduct` rows with the server-owner actor ID and supplied reason.

## Behavior and cautions

- The requester’s proposal counts as approval 1/N; normal completion/cancellation then requires every **currently active** helper to confirm. Any one active helper can reject a pending proposal, even after accepting, until finalization locks. A helper can reject a pending request. Pending requests expire after 15 minutes; expiration does not move credits.
- `/admin_complete` and `/admin_refund` are explicit staff overrides. Use them only after reviewing the ticket. They are blocked when the acting staff member is the requester, an original/active helper (including a departed original helper), or a pending replacement candidate in that ticket. Normal ticket buttons always use the helper-confirmation workflow.
- Requesting a replacement does not change the ticket price. Configured service prices are per helper. The total reservation is the per-helper price multiplied by the helper count selected at ticket creation. At completion, active helpers each receive one unit price; any original slot left unfilled is refunded to the requester. Approved replacements fill existing slots without increasing the reservation.
- Never test real credit deductions on live balances until the development tests are complete. Preserve backups and inspect balances/ledger before retrying any interaction after an error.

## Update 0.6.1 UX hotfix

For the contextual ticket controls and ephemeral cleanup update, follow `UPDATE_0.6.1_UX_EPHEMERAL_HOTFIX.md`. Back up with `tools/Backup-Phase4-5-Before-Update-0.6.1.ps1`, then run compilation and the full test suite inside the project's `.venv` before live testing.
