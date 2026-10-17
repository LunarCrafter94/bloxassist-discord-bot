# BF World Credit Test Bot — Update 0.6.2

## Replacement Selection, Resolution Voting, and Permission Safety

### Replacement helper workflow

- The requester—not staff—selects the proposed replacement member(s) from a private user selector. The selector requires exactly enough new human members to restore the original helper count. The requester, current helpers, and members from the original roster cannot be selected as replacements.
- Staff approve the saved selection with `/admin_helper-replace approve` or reject it with `/admin_helper-replace disapprove`, from the affected ticket channel. The previous `/admin_replace_helper member` command is removed.
- Approval applies all selected member permissions before committing the roster update. If a permission update fails, already-attempted overwrites are rolled back where possible, no roster changes are committed, and the detailed Discord error is logged.
- Disapproval leaves the active roster, channel access, and credits unchanged, and lets the requester submit a new selection. The original reserved price remains unchanged.

### Resolution vote rules

- The requester’s click to propose completion/cancellation counts as the first approval. A requester plus two helpers therefore shows 1/3, then 2/3 and 3/3 as helpers approve.
- Every active helper must confirm before normal payout/refund finalizes. Any one active helper may reject while the proposal is pending, including a helper who previously confirmed; rejection clears the pending proposal and moves no credits.
- Once all participants have approved and finalization locks, later rejection is refused. Clicking a stale old prompt after a rejection does not restore the proposal.

### Permission-failure hotfix

- **Required bot permission:** `Manage Roles` is required by Discord to edit channel permission overwrites; `Manage Channels` alone is not sufficient. `Manage Channels` remains necessary for creating/deleting ticket channels.
- The bot checks its effective `Manage Roles` permission in the specific ticket channel before processing a helper departure or replacement approval. Discord requires `MANAGE_ROLES` to edit channel permission overwrites; `MANAGE_CHANNELS` alone is not sufficient. Channel/category overrides may also deny the effective permission.
- Ticket access is revoked before removing the helper from the database roster. If Discord rejects the permission update, the helper remains active in the database rather than being removed while still able to access the channel. The log now includes the HTTP status, Discord error code, effective `Manage Roles` and `Manage Channels` permissions, guild-level permission bits, and category ID.
- If roster mutation fails after access was changed, the bot attempts to restore the previous channel overwrite.

### Database and compatibility

- Adds/migrates candidate IDs and replacement request/button message IDs to the existing named-server SQLite databases.
- Stale pre-0.6.2 replacement requests without a selected candidate list are cleared during migration. No balances, reservations, ticket prices, or historical transaction rows are rewritten by this change.
- One-minute ephemeral cleanup from Update 0.6.1 remains in place.

### Validation

- Python compilation passed.
- 44 database/configuration/workflow tests passed.
- One Discord command-registration test was skipped because `discord.py` is not installed in the packaging environment; run it inside the project's `.venv`.
- Live Discord interactions and permission edits still need to be verified in the development server.
