# Update 0.6.2 — Install Instructions

This hotfix builds directly on the combined Phase 4 + 5 package and the 0.6.1 UX/ephemeral cleanup update. It retains the Phase 3.3 named-server database layout. You do not need to install Phase 3.1, 3.2, or 3.3 separately.

## 1. Back up the current project

1. Stop the bot with `Ctrl+C` and close DB Browser for SQLite.
2. Extract this ZIP to a temporary staging folder.
3. Open PowerShell in that staging folder and run:

   ```powershell
   .\tools\Backup-Phase4-5-Before-Update-0.6.2.ps1 -ProjectRoot "D:\Repositories\Local\bloxfruits-helper-credit-bot"
   ```

4. Type `YES` only after confirming the bot and database tools are stopped. Verify the backup location. The script copies project files and all `data/` files; it excludes the real `private-configs\tokens.env`.

## 2. Install

Copy the extracted package contents into:

`D:\Repositories\Local\bloxfruits-helper-credit-bot`

Allow source files to overwrite the previous version. Preserve `.venv`, `.venv-old`, `_backups`, `data`, and the actual `private-configs\tokens.env`. This update does not rename or relocate the current named-server SQLite databases. On startup, SQLite adds the replacement candidate/message ID columns, and clears old replacement-request flags that do not have a saved candidate list.

## 3. Run local checks

```powershell
.\.venv\Scripts\python.exe -m compileall -q RunBot.py source-files tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The packaging environment passed 44 database/configuration/workflow tests. The command registration test is skipped in the packaging environment because `discord.py` is unavailable there; your project virtual environment should run it. Verify it shows `/admin_helper-replace approve` and `/admin_helper-replace disapprove`, and that the old `/admin_replace_helper` command is absent.

## Required bot permissions

- **Manage Channels**: create and delete ticket channels.
- **Manage Roles**: edit permission overwrites to revoke a departing helper's access, grant access to approved replacements, and update staff-role access on tickets. Discord's channel permission endpoint requires `MANAGE_ROLES`; `MANAGE_CHANNELS` alone is not sufficient. Ensure the bot's `Manage Roles` permission is not denied by ticket/category overrides. Place the bot role carefully and grant only the permissions needed.
- View Channel, Send Messages, Read Message History, and Embed Links in channels where the bot posts or updates messages.

If a permission operation fails, the bot should leave the helper roster unchanged and log the HTTP status, Discord error code, and effective permissions. Do not manually edit balances to compensate.

## 4. Live test checklist

- **Helper departure:** click Leave as Helper on an open ticket. If Discord refuses the permission update, the helper must remain active in the roster, and the terminal must show the actual error code plus effective Manage Roles and Manage Channels states. `TextChannel.set_permissions` requires Manage Roles; Manage Channels alone is insufficient.
- **Replacement selection:** on a ticket with original helpers > 1 and exactly one active helper remaining, the requester clicks **Choose Replacement Helpers** and selects exactly the missing number of new, non-bot members. Staff see the chosen candidate list in the ticket.
- **Approve:** in that ticket, an authorized staff member runs `/admin_helper-replace approve`. All selected candidates are added, access is updated, and the reserved price stays unchanged.
- **Disapprove:** in that ticket, staff runs `/admin_helper-replace disapprove`. No helper or credit state changes; requester can select a new list.
- **Resolution voting:** a requester plus two helpers starts at 1/3; one helper approval makes it 2/3; the second makes it 3/3 and finalizes. Any one helper can reject the still-pending proposal, even if they previously approved. A click on an old prompt after rejection must not change credits.
- **Cleanup:** confirm the 60-second ephemeral deletion and the existing 15-second completion / 10-second refund channel deletion still work.

The database/unit tests cannot verify Discord permission state or real component delivery, so run the live checklist in the development server before using this update on the public server.
