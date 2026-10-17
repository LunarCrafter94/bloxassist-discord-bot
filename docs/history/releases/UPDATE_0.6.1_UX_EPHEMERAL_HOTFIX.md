# BF World Credit Test Bot — Update 0.6.1

## Contextual ticket controls and one-minute ephemeral cleanup

This hotfix builds on the combined Phase 4 + Phase 5 package and keeps the Phase 3.3 named-server database layout. It does not implement invite rewards or helper invite acceptance.

### Ticket UI changes

- The Confirm/Reject buttons are for a pending completion or cancellation proposal, not for accepting a ticket invitation. In this version, selected helpers are added to the ticket when the ticket is created; a separate invite-acceptance workflow is not included.
- The ticket message now shows only the always-relevant controls: **Complete**, **Cancel**, and **Leave as Helper**.
- Resolution controls now appear on a separate message only after the requester submits a completion or cancellation proposal. Their labels are specific to the action: **Confirm Completion / Reject Completion** or **Confirm Cancellation / Reject Cancellation**, so they are not confused with accepting a ticket invitation.
- The bot stores the resolution prompt's message ID so it can restore the pending prompt after restart and remove its controls after rejection, expiry, helper departure, or resolution.
- A replacement request button is posted only after the system detects exactly one active helper remains and the original ticket had multiple helpers. The requester must still press the button, and staff must approve any replacement.
- A replacement request removes its button after it is submitted; stale prompts are disabled if the request is no longer eligible.

### Ephemeral cleanup

- Private responses and ephemeral follow-up messages are scheduled for deletion after 60 seconds.
- Editing an ephemeral original response restarts the one-minute countdown from its latest update.
- When ticket creation succeeds, prior ephemeral ticket-wizard responses are deleted immediately. The final private ticket-created confirmation remains briefly, then deletes after 60 seconds.
- Ticket-wizard views now expire after 60 seconds to match their ephemeral message lifetime.

### Database migration

A nullable `resolution_message_id` column is added automatically to each server database. Existing balances, ticket reservations, transaction history, and active ticket records are preserved. Stop the bot and back up the project before installing.

### Validation

- Python source compilation passed.
- 38 database/configuration tests passed in the packaging environment.
- The Discord command-registration test could not be run in the packaging environment because `discord.py` could not be installed there. Run the complete test suite in the project's `.venv` before live verification.
- Live Discord behavior is not verified by these local tests; confirm the UI and ephemeral cleanup in the test server.
