# Update 0.6.3 — Installation

This is a hotfix for the combined Phase 4 + 5 / Update 0.6.2 package. It keeps the named-server database layout:

`data/servers/<server_id>/blox_fruits_credit_system.sqlite3`

## Install

1. Stop the bot with `Ctrl+C` and close DB Browser for SQLite.
2. Extract this ZIP into a temporary folder.
3. In PowerShell, from the extracted folder, run:

   ```powershell
   .\tools\Backup-Update-0.6.2-Before-Update-0.6.3.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

4. Verify the backup completed. Type `YES` only after confirming the bot/database tools are stopped.
5. Copy the extracted package contents into the existing project folder, allowing updated files to overwrite their earlier versions.
6. Preserve `.venv`, `.venv-old`, `_backups`, `data`, and your real `private-configs\tokens.env`.

## Validate

From the project root:

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Live test checklist

1. Make a configured moderator (and, separately, the server owner) the requester. Their Complete/Cancel button should create a normal helper-confirmation proposal, not perform an override.
2. Assign a configured moderator as a helper. Confirm/Reject buttons should register their helper vote; they must not bypass the vote requirements.
3. While that moderator remains part of an open ticket, try `/admin_complete`, `/admin_refund`, `/admin_helper-replace approve`, `/admin_helper-replace disapprove`, `/add`, and `/deduct`. The conflicted action should be denied as described in the changelog.
4. Have a configured moderator who is not a participant in that ticket use the relevant ticket escalation command. Check that the audit records the actor and reason.
5. Try `/add` and `/deduct` as a moderator or non-owner Administrator; both must be denied. Then try them as the actual server owner while the owner has no open-ticket participation; the commands should work and write audit records. If the owner participates in an open ticket, they must be denied until that ticket is resolved.

## Update 0.6.3 behavior notes

- `/add` and `/deduct` are now executable only by the actual server owner; other Administrators and configured moderators are denied. Discord may still display commands to other Administrators because native command visibility is permission-based, but the runtime owner-ID check is authoritative.
- Event catalog prices are now per helper. A 100-credit event with 3 selected helpers reserves 300 credits. Each active helper earns 100 credits on completion; any originally selected helper slot not filled by an approved replacement is refunded at completion. Cancellation refunds the complete reservation. Existing tickets without the new unit-price snapshot retain the old split behavior.
- Ticket confirmation buttons do not become admin commands for owners or moderators. Staff override commands are separate and blocked for anyone associated with the target ticket.

## Access behavior

- Owner and Administrator remain trusted staff for admin actions, except they cannot override their own ticket as a participant.
- The Dashboard's configured Moderator Roles grant delegated staff access without requiring Manage Server.
- Manage Server alone is not enough for delegated access. Dashboard role configuration itself remains Administrator-only.
- Bot-side Manage Roles/Manage Channels permissions are separate from staff command authorization.
