# BF World Credit Test Bot — Update 0.6.3

## Staff Authorization, Owner-Only Credit Adjustments, and Per-Helper Pricing

### Normal ticket buttons never become admin overrides

- Ticket **Complete** and **Cancel** buttons always use the normal requester-proposed workflow, regardless of whether the requester or helper is the server owner, an Administrator, or a configured moderator.
- Confirm/Reject Resolution buttons only record the active helper's vote. They never call the staff override route.
- Every active helper must accept completion or cancellation before the normal payout/refund is finalized. One helper rejection vetoes a still-pending proposal, even if that helper previously accepted. Once finalization is locked after all required confirmations, a late rejection is too late.
- Explicit `/admin_complete`, `/admin_refund`, and `/admin_helper-replace approve/disapprove` commands remain separate escalation operations. They are denied to the requester, original helpers (including departed helpers), active helpers, and pending replacement candidates for the target ticket.
- Staff authorization uses server owner, Administrator, and moderator roles configured in the Admin Dashboard. Delegated moderators do not need Manage Server or Manage Channels permissions to use staff commands, provided they are configured and can access the relevant channel. Manage Server alone is not an automatic grant.

### Credit adjustments are server-owner-only

- `/add` and `/deduct` now require the actual Discord server owner ID. Other Administrators and configured moderator roles are denied even if they can see the commands.
- These commands are also blocked while the owner participates in any open ticket, reducing conflicts of interest.
- Adjustments remain atomic, audited, idempotent, and refuse negative balances or invalid amounts.
- Discord's native command visibility can be limited to Administrator-level users; the server-owner ID check is the authoritative security boundary, so other Administrators who can see a command still cannot execute it.

### Service price is per helper

- The price configured in the dashboard is now the fixed price **per helper**.
- Total reserved at ticket creation is `price per helper × number of selected helpers`. The ticket stores the unit-price snapshot and total reservation, so later service price edits don't affect open tickets.
- At completion, every active helper earns the stored per-helper amount. If an original helper slot remains empty, its unit price is refunded to the requester. Staff-approved replacements fill existing slots and do not increase the original reserved total.
- Cancellation/refund still returns the full reserved amount. Older tickets without a per-helper price snapshot retain the legacy equal-split payout behavior; migration does not rewrite their financial history.

### Validation

- Python source compilation passed.
- Automated tests cover owner-only credit command source guards, normal button routing, ticket participant override guards, per-helper total calculations, unit-price snapshots, unused-slot refunds, and legacy database migrations.
- Live Discord verification is still required for slash-command behavior and channel permission changes.
