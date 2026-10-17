# Phase 3.2 changelog — Clean logging and slash-command-only client

## Changes in this refinement

- Switched from `commands.Bot` to `discord.Client` with an explicit application-command tree. The bot does not use prefix commands, so it no longer requests the privileged Message Content Intent just to support unused prefix commands.
- Registered gateway handlers as client methods rather than attaching them through `@bot.event`, reducing deprecation warnings caused by discord.py calling `asyncio.iscoroutinefunction()` under Python 3.15.
- Disabled discord.py's extra logging handler (`log_handler=None`) because the project configures the root logger itself. This prevents Discord INFO/WARNING/ERROR log entries from appearing twice.
- No voice features were added. Missing PyNaCl/davey notices may still appear once because voice dependencies are optional and this bot does not use voice.

## Validation

Run compilation and the full suite in the project's virtual environment. Python 3.15 may still surface `asyncio.iscoroutinefunction()` deprecation notices from third-party discord.py internals that this app doesn't call directly; those should not be hidden globally. If any remain, retain their exact file/line in the report and either use a discord.py release that fixes them or run on Python 3.14 until upstream compatibility is updated.

The refactor keeps the existing slash-command tree, persistent views, guild-specific databases, and ticket workflow. Live Discord testing is still required after installation.

# Phase 3.1 changelog — Setup subcommands and in-channel admin dashboard

## Changes in this refinement

- Moved both setup actions into a single `/setup` command group: `/setup public_tickets` and `/setup admin_dashboard`.
- `/setup admin_dashboard` now posts or updates the panel in the current text channel instead of creating a separate dashboard channel. If moved, the old bot dashboard message is removed when possible; the old channel itself is left untouched.
- Moderator role selections control which users may operate dashboard controls, but the bot no longer rewrites channel visibility for the dashboard. Use a staff-only channel to keep settings private.

## Phase 3 features retained

- Reorganized setup commands under `/setup`: `/setup public_tickets` posts or updates the public Help Center panel, and `/setup admin_dashboard` posts or updates the admin dashboard in the channel where the command is run.
- The dashboard no longer creates or manages a separate channel. Use a staff-only text channel for privacy; dashboard controls independently check Administrator/configured-moderator authorization on each action.
- Added configurable starting credits for new accounts; existing balances are not changed.
- Added event catalog add/edit/enable/disable controls with a total event price and a 25-event picker limit.
- Added per-server maximum helper setting (1–25), which changes helper count choices for new ticket requests.
- Added saved invite reward enabled/amount/default-duration settings. The UI explicitly notes that actual invite tracking and rewards are not implemented yet.
- Added Help Center text-channel selection. The bot stores channel/message IDs, updates the existing panel when possible, recreates a deleted panel, and retires the previous panel when moved.
- Added configured dashboard moderator roles and per-callback access checks; only Administrators can edit this allowlist.
- Added configurable ticket staff baseline role; the selected role and non-managed roles above it in the hierarchy are granted access to new tickets. Updating the baseline also updates open ticket channels. No Administrator permissions are granted.
- Added startup restoration for configured dashboard/Help Center messages.
- Added Phase 3 persistence/isolation tests. Phase 2 atomic transaction code, numbered tickets, 15-second completion deletion, and 10-second cancellation/refund deletion are preserved.

## Data and migration

No new database tables are required. The existing `settings` table is seeded with missing Phase 3 settings using `INSERT OR IGNORE`, which preserves settings already stored in each per-guild database. Existing user balances and ticket/transaction history are retained. No old root-level `bot.db` is imported.

## Validation

- Python compilation passed in the packaging environment.
- The 21 existing transaction/configuration tests passed. A new command-tree test verifies the two `/setup` subcommands when `discord.py` is available; it was skipped in this packaging environment because that dependency could not be installed here.
- Live Discord testing is still required for dashboard posting/moving, component interactions, Help Center movement/recreation, and ticket staff-role access. These cannot be proven by the database-only test suite.

## Not included in Phase 3

- Operational invite events/reward distribution and expiry.
- `/add` or `/deduct` slash commands.
- Helper approval, leave, or replacement workflows.
