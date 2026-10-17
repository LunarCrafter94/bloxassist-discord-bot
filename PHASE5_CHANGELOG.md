# Phase 5 — Staff credit moderation commands

## Included

- `/add member amount reason` adds credits to a member.
- `/deduct member amount reason` deducts credits only when the target has sufficient credits.
- Amount must be a positive whole number from 1 to 1,000,000,000. Bot accounts cannot be targets.
- `reason` is optional, but staff are encouraged to provide it for audit clarity.
- Responses are ephemeral and show the amount changed and new balance.
- Initial Phase 5 used a general staff authorization check. **Superseded by Update 0.6.3:** only the actual Discord server owner may execute `/add` or `/deduct`. Other Administrators and configured moderator roles are denied even if Discord displays the commands to them. The owner is also blocked while participating in any open ticket.
- Each adjustment and ledger entry are committed atomically with actor ID, optional reason, and interaction-based idempotency key. Replaying an interaction key cannot apply the same adjustment twice.
- Replacement helper approval is handled separately by `/admin_helper-replace approve` and `/admin_helper-replace disapprove`; requesters choose the candidate(s) before staff approval.

## Current security rule (Update 0.6.3)

- `/add` and `/deduct` are executable only by the actual server owner, and only while the owner is not a participant in any open ticket.
- Staff dashboard roles apply to ticket escalation and other configured staff actions, not credit adjustments.

## Validation

Automated tests cover audited additions/deductions, refusal of insufficient deductions, and transaction idempotency. Live Discord permission and command synchronization still require testing in the development server.
