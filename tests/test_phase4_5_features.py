import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES
from bloxfruits_helper_credit_bot.database import DatabaseManager


class Phase4And5DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(Path(self.tempDir.name) / "data", DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES)
        self.db = self.manager.ForServer(111111111111111111)
        self.db.CreateUser(1001, 500)
        self.ticketId = self.db.ReserveTicket(9001, 1001, "v4_trials", [2001, 2002], 200)
        self.assertIsNotNone(self.ticketId)

    def tearDown(self):
        self.manager.CloseAll()
        self.tempDir.cleanup()

    def test_completion_waits_for_every_active_helper(self):
        status, helpers = self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        self.assertEqual(status, "requested")
        self.assertEqual(helpers, [2001, 2002])
        first = self.db.ConfirmTicketResolution(self.ticketId, 2001)
        # The requester is counted as approval 1/3 because they initiated the proposal.
        self.assertEqual(first[:3], ("confirmed", 2, 3))
        self.assertEqual(self.db.GetBalance(2001), 100)
        second = self.db.ConfirmTicketResolution(self.ticketId, 2002)
        self.assertEqual(second[:3], ("ready", 3, 3))
        self.assertEqual(self.db.RejectTicketResolution(self.ticketId, 2001)[0], "already_confirmed")
        status, payouts = self.db.CompleteTicket(self.ticketId, actorUserId=2002, note="all helpers confirmed")
        self.assertEqual(status, "completed")
        self.assertEqual(payouts, [(2001, 100), (2002, 100)])
        self.assertEqual(self.db.CompleteTicket(self.ticketId)[0], "not_open")

    def test_duplicate_helper_confirmation_does_not_count_twice(self):
        self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2001)[0], "confirmed")
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2001)[0], "duplicate")

    def test_cancel_requires_all_active_helper_confirmations_before_refund(self):
        self.assertEqual(self.db.GetBalance(1001), 300)
        self.db.RequestTicketResolution(self.ticketId, "cancel", 1001)
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2001)[0], "confirmed")
        self.assertEqual(self.db.GetBalance(1001), 300)
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2002)[0], "ready")
        self.assertEqual(self.db.RefundTicket(self.ticketId), ("refunded", 200))
        self.assertEqual(self.db.GetBalance(1001), 500)

        auditRows = self.db.Execute(
            "SELECT type, actor_user_id FROM transactions WHERE ticket_id = ? AND type IN ('ticket_cancellation_requested', 'helper_confirmation') ORDER BY id",
            (self.ticketId,), fetchAll=True,
        )
        self.assertEqual(
            [(row["type"], row["actor_user_id"]) for row in auditRows],
            [("ticket_cancellation_requested", 1001), ("helper_confirmation", 2001), ("helper_confirmation", 2002)],
        )

    def test_helper_can_reject_resolution_without_changing_credits(self):
        self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        result, resolutionType = self.db.RejectTicketResolution(self.ticketId, 2001)
        self.assertEqual((result, resolutionType), ("rejected", "complete"))
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["resolution_type"], "")
        self.assertEqual(self.db.GetBalance(1001), 300)
        self.assertEqual(self.db.GetBalance(2001), 100)
        row = self.db.Execute("SELECT actor_user_id FROM transactions WHERE ticket_id = ? AND type = 'helper_rejected_resolution'", (self.ticketId,), fetchOne=True)
        self.assertEqual(row["actor_user_id"], 2001)

    def test_background_expiry_clears_stale_requests_without_moving_credits(self):
        self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        self.db.SetResolutionMessageId(self.ticketId, 123456)
        self.db.Execute("UPDATE tickets SET resolution_requested_at = datetime('now', '-20 minutes') WHERE ticket_id = ?", (self.ticketId,))
        expired = self.db.ExpireStaleResolutionRequests(15)
        self.assertEqual(expired, [(self.ticketId, 9001, "complete", 123456)])
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["resolution_type"], "")
        self.assertEqual(self.db.GetBalance(1001), 300)
        self.assertEqual(self.db.GetBalance(2001), 100)
        timeoutRow = self.db.Execute("SELECT type, actor_user_id FROM transactions WHERE ticket_id = ? AND type = 'resolution_timeout'", (self.ticketId,), fetchOne=True)
        self.assertEqual((timeoutRow["type"], timeoutRow["actor_user_id"]), ("resolution_timeout", None))

    def test_resolution_request_expires_after_fifteen_minutes(self):
        self.db.RequestTicketResolution(self.ticketId, "cancel", 1001)
        self.db.Execute("UPDATE tickets SET resolution_requested_at = datetime('now', '-20 minutes') WHERE ticket_id = ?", (self.ticketId,))
        result = self.db.ConfirmTicketResolution(self.ticketId, 2001)
        self.assertEqual(result[0], "expired")
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["resolution_type"], "")
        self.assertEqual(self.db.GetBalance(1001), 300)

    def test_helper_leaving_removes_active_roster_and_audits(self):
        result, active, originalCount = self.db.LeaveTicketHelper(self.ticketId, 2001)
        self.assertEqual((result, active, originalCount), ("left", [2002], 2))
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["helper_ids"], "2001,2002")
        self.assertEqual(ticket["active_helper_ids"], "2002")
        row = self.db.Execute("SELECT * FROM transactions WHERE ticket_id = ? AND type = 'helper_leave'", (self.ticketId,), fetchOne=True)
        self.assertIsNotNone(row)
        self.assertEqual(row["actor_user_id"], 2001)

    def test_empty_active_roster_does_not_fall_back_to_original_helpers(self):
        self.assertEqual(self.db.LeaveTicketHelper(self.ticketId, 2001)[0], "left")
        result, activeIds, originalCount = self.db.LeaveTicketHelper(self.ticketId, 2002)
        self.assertEqual((result, activeIds, originalCount), ("left", [], 2))
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["active_helper_ids"], "")
        self.assertEqual(self.db.RequestTicketResolution(self.ticketId, "complete", 1001)[0], "no_active_helpers")
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2001)[0], "no_request")

    def test_replacement_needs_request_and_staff_approval_and_keeps_price(self):
        self.db.LeaveTicketHelper(self.ticketId, 2001)
        self.assertEqual(self.db.RequestHelperReplacement(self.ticketId, 1001)[0], "requested")
        self.assertEqual(self.db.AddReplacementHelper(self.ticketId, 3001, 9001)[0], "added")
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["active_helper_ids"], "2002,3001")
        self.assertEqual(ticket["reserved_credits"], 200)
        self.assertEqual(ticket["replacement_requested"], 0)
        row = self.db.Execute("SELECT * FROM transactions WHERE ticket_id = ? AND type = 'helper_replacement'", (self.ticketId,), fetchOne=True)
        self.assertEqual(row["actor_user_id"], 9001)

    def test_replacement_can_fill_multiple_departures(self):
        self.db.LeaveTicketHelper(self.ticketId, 2001)
        # Build a three-helper ticket to prove multiple replacements can be approved.
        self.db.RefundTicket(self.ticketId)
        self.db.CreateUser(1002, 500)
        ticketId = self.db.ReserveTicket(9002, 1002, "v4_trials", [2101, 2102, 2103], 200)
        self.db.LeaveTicketHelper(ticketId, 2101)
        self.db.LeaveTicketHelper(ticketId, 2102)
        self.assertEqual(self.db.RequestHelperReplacement(ticketId, 1002)[0], "requested")
        self.assertEqual(self.db.AddReplacementHelper(ticketId, 3101, 9001)[0], "added")
        self.assertEqual(int(self.db.GetTicketById(ticketId)["replacement_requested"]), 1)
        self.assertEqual(self.db.AddReplacementHelper(ticketId, 3102, 9001)[0], "added")
        ticket = self.db.GetTicketById(ticketId)
        self.assertEqual(ticket["active_helper_ids"], "2103,3101,3102")
        self.assertEqual(int(ticket["replacement_requested"]), 0)

    def test_replacement_completion_pays_only_active_helpers_and_keeps_reserved_total(self):
        self.db.LeaveTicketHelper(self.ticketId, 2001)
        self.db.RequestHelperReplacement(self.ticketId, 1001)
        self.assertEqual(self.db.AddReplacementHelper(self.ticketId, 3001, 9001)[0], "added")
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(int(ticket["reserved_credits"]), 200)
        self.assertEqual(ticket["active_helper_ids"], "2002,3001")
        self.assertEqual(self.db.RequestTicketResolution(self.ticketId, "complete", 1001)[0], "requested")
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2002)[0], "confirmed")
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 3001)[0], "ready")
        status, payouts = self.db.CompleteTicket(self.ticketId)
        self.assertEqual(status, "completed")
        self.assertEqual(payouts, [(2002, 100), (3001, 100)])
        self.assertEqual(self.db.GetBalance(2001), 100)
        self.assertEqual(self.db.GetBalance(2002), 200)
        self.assertEqual(self.db.GetBalance(3001), 200)


    def test_new_ticket_price_scales_by_selected_helper_count_and_snapshots_unit_price(self):
        self.db.CreateUser(4101, 1000)
        unitPrice = 75
        selectedHelpers = [5101, 5102, 5103]
        ticketId = self.db.ReserveTicket(
            channelId=9410,
            creatorId=4101,
            eventKey="scaled_price_test",
            helperIds=selectedHelpers,
            requiredCredits=unitPrice * len(selectedHelpers),
            pricePerHelper=unitPrice,
        )
        self.assertIsNotNone(ticketId)
        ticket = self.db.GetTicketById(ticketId)
        self.assertEqual(int(ticket["required_credits"]), 225)
        self.assertEqual(int(ticket["reserved_credits"]), 225)
        self.assertEqual(int(ticket["price_per_helper"]), 75)
        self.assertEqual(self.db.GetBalance(4101), 775)
        # A later dashboard price edit must not alter this ticket's snapshot.
        self.db.SaveService("scaled_price_test", "Scaled Price Test", 90)
        ticketAfterPriceEdit = self.db.GetTicketById(ticketId)
        self.assertEqual(int(ticketAfterPriceEdit["reserved_credits"]), 225)
        self.assertEqual(int(ticketAfterPriceEdit["price_per_helper"]), 75)
        status, payouts = self.db.CompleteTicket(ticketId)
        self.assertEqual(status, "completed")
        self.assertEqual(payouts, [(5101, 75), (5102, 75), (5103, 75)])
        self.assertEqual(self.db.GetBalance(5101), 175)
        self.assertEqual(self.db.GetBalance(5102), 175)
        self.assertEqual(self.db.GetBalance(5103), 175)
        self.assertEqual(self.db.GetCompletionRefundAmount(ticketId), 0)

    def test_per_helper_pricing_refunds_unfilled_slots_at_completion(self):
        self.db.CreateUser(4201, 1000)
        ticketId = self.db.ReserveTicket(
            channelId=9420,
            creatorId=4201,
            eventKey="per_helper_refund_test",
            helperIds=[5201, 5202],
            requiredCredits=200,
            pricePerHelper=100,
        )
        self.assertIsNotNone(ticketId)
        self.assertEqual(self.db.GetBalance(4201), 800)
        self.assertEqual(self.db.LeaveTicketHelper(ticketId, 5201)[0], "left")
        self.assertEqual(self.db.RequestTicketResolution(ticketId, "complete", 4201)[0], "requested")
        self.assertEqual(self.db.ConfirmTicketResolution(ticketId, 5202)[0], "ready")
        status, payouts = self.db.CompleteTicket(ticketId, actorUserId=5202, note="only one active helper remained")
        self.assertEqual(status, "completed")
        self.assertEqual(payouts, [(5202, 100)])
        self.assertEqual(self.db.GetBalance(5202), 200)
        self.assertEqual(self.db.GetBalance(4201), 900)
        self.assertEqual(self.db.GetCompletionRefundAmount(ticketId), 100)
        refundRow = self.db.Execute(
            "SELECT type, to_user, amount FROM transactions WHERE ticket_id = ? AND type = 'unused_helper_refund'",
            (ticketId,), fetchOne=True,
        )
        self.assertEqual((refundRow["type"], refundRow["to_user"], refundRow["amount"]), ("unused_helper_refund", 4201, 100))

    def test_per_helper_ticket_reservation_rejects_wrong_total(self):
        self.db.CreateUser(4301, 1000)
        with self.assertRaisesRegex(ValueError, "per-helper price multiplied by the helper count"):
            self.db.ReserveTicket(
                channelId=9430,
                creatorId=4301,
                eventKey="bad_total_test",
                helperIds=[5301, 5302],
                requiredCredits=199,
                pricePerHelper=100,
            )
        self.assertEqual(self.db.GetBalance(4301), 1000)

    def test_add_and_deduct_are_audited_and_insufficient_deduction_is_rejected(self):
        self.db.CreateUser(4001, 100)
        self.assertEqual(self.db.ApplyCreditAdjustment(4001, 50, direction="add", actorUserId=5001, note="event compensation", idempotencyKey="phase5-add-1"), ("added", 150))
        self.assertEqual(self.db.ApplyCreditAdjustment(4001, 30, direction="deduct", actorUserId=5001, note="policy violation", idempotencyKey="phase5-deduct-1"), ("deducted", 120))
        self.assertEqual(self.db.ApplyCreditAdjustment(4001, 999, direction="deduct", actorUserId=5001, idempotencyKey="phase5-deduct-2"), ("insufficient", 120))
        rows = self.db.Execute("SELECT type, actor_user_id, note FROM transactions WHERE idempotency_key LIKE 'phase5-%' ORDER BY id", fetchAll=True)
        self.assertEqual([(row["type"], row["actor_user_id"]) for row in rows], [("admin_add", 5001), ("admin_deduct", 5001)])
        self.assertEqual(rows[0]["note"], "event compensation")

    def test_resolution_cannot_start_while_replacement_candidates_wait_for_staff(self):
        self.db.LeaveTicketHelper(self.ticketId, 2001)
        self.assertEqual(self.db.SubmitReplacementCandidates(self.ticketId, 1001, [3001])[0], "requested")
        status, activeHelpers = self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        self.assertEqual(status, "replacement_pending")
        self.assertEqual(activeHelpers, [2002])
        self.assertEqual(self.db.GetTicketById(self.ticketId)["resolution_type"], "")

    def test_second_resolution_request_is_not_allowed_while_one_is_pending(self):
        firstStatus, _ = self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        secondStatus, _ = self.db.RequestTicketResolution(self.ticketId, "cancel", 1001)
        self.assertEqual(firstStatus, "requested")
        self.assertEqual(secondStatus, "existing_request")
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["resolution_type"], "complete")

    def test_replacement_request_requires_exactly_one_active_helper(self):
        # Original roster contains two helpers; both are still active here.
        result, activeCount, originalCount = self.db.RequestHelperReplacement(self.ticketId, 1001)
        self.assertEqual((result, activeCount, originalCount), ("not_eligible", 2, 2))
        self.db.LeaveTicketHelper(self.ticketId, 2001)
        result, activeCount, originalCount = self.db.RequestHelperReplacement(self.ticketId, 1001)
        self.assertEqual((result, activeCount, originalCount), ("requested", 1, 2))

    def test_resolution_prompt_message_id_is_cleared_when_rejected(self):
        self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        self.assertTrue(self.db.SetResolutionMessageId(self.ticketId, 654321))
        self.assertEqual(self.db.GetTicketById(self.ticketId)["resolution_message_id"], 654321)
        self.assertEqual(self.db.RejectTicketResolution(self.ticketId, 2001)[0], "rejected")
        self.assertIsNone(self.db.GetTicketById(self.ticketId)["resolution_message_id"])

    def test_one_rejection_vetoes_even_if_that_helper_previously_confirmed(self):
        self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2001)[0], "confirmed")
        self.assertEqual(self.db.RejectTicketResolution(self.ticketId, 2001), ("rejected", "complete"))
        self.assertEqual(self.db.ConfirmTicketResolution(self.ticketId, 2002)[0], "no_request")
        self.assertEqual(self.db.GetBalance(1001), 300)
        self.assertEqual(self.db.GetBalance(2001), 100)
        self.assertEqual(self.db.GetBalance(2002), 100)

    def test_replacement_candidate_and_message_id_schema_is_available(self):
        columns = {
            str(row["name"])
            for row in self.db.Execute("PRAGMA table_info(tickets)", fetchAll=True)
        }
        self.assertTrue({
            "replacement_candidate_ids",
            "replacement_request_message_id",
            "replacement_button_message_id",
        }.issubset(columns))

    def test_requester_is_counted_in_total_resolution_approval_progress(self):
        self.db.RequestTicketResolution(self.ticketId, "complete", 1001)
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["resolution_confirmations"], "1001")
        first = self.db.ConfirmTicketResolution(self.ticketId, 2001)
        self.assertEqual(first[:3], ("confirmed", 2, 3))
        second = self.db.ConfirmTicketResolution(self.ticketId, 2002)
        self.assertEqual(second[:3], ("ready", 3, 3))

    def test_replacement_candidates_must_be_selected_and_exact_count_approved(self):
        self.assertEqual(self.db.LeaveTicketHelper(self.ticketId, 2001)[0], "left")
        status, activeCount, originalCount, missingCount = self.db.SubmitReplacementCandidates(
            self.ticketId, 1001, [3001]
        )
        self.assertEqual((status, activeCount, originalCount, missingCount), ("requested", 1, 2, 1))
        self.assertEqual(self.db.GetReplacementCandidateIds(self.ticketId), [3001])
        status, candidateIds, activeIds = self.db.ApplyReplacementCandidates(
            self.ticketId, 9001, [3001]
        )
        self.assertEqual((status, candidateIds, activeIds), ("added", [3001], [2002, 3001]))
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["active_helper_ids"], "2002,3001")
        self.assertEqual(int(ticket["reserved_credits"]), 200)
        self.assertEqual(int(ticket["replacement_requested"]), 0)

    def test_disapproving_replacement_candidates_leaves_roster_and_balance_unchanged(self):
        self.db.LeaveTicketHelper(self.ticketId, 2001)
        self.assertEqual(self.db.SubmitReplacementCandidates(self.ticketId, 1001, [3001])[0], "requested")
        status, candidates = self.db.DisapproveReplacementRequest(self.ticketId, 9001)
        self.assertEqual((status, candidates), ("disapproved", [3001]))
        ticket = self.db.GetTicketById(self.ticketId)
        self.assertEqual(ticket["active_helper_ids"], "2002")
        self.assertEqual(int(ticket["replacement_requested"]), 0)
        self.assertEqual(self.db.GetBalance(1001), 300)
        audit = self.db.Execute(
            "SELECT actor_user_id FROM transactions WHERE ticket_id = ? AND type = 'replacement_disapproved'",
            (self.ticketId,), fetchOne=True,
        )
        self.assertEqual(audit["actor_user_id"], 9001)


    def test_ticket_participant_detection_includes_original_helpers_and_candidates(self):
        self.assertTrue(self.db.IsUserTicketParticipant(self.ticketId, 1001))  # requester
        self.assertTrue(self.db.IsUserTicketParticipant(self.ticketId, 2001))
        self.assertTrue(self.db.IsUserTicketParticipant(self.ticketId, 2002))
        self.assertFalse(self.db.IsUserTicketParticipant(self.ticketId, 9001))

        self.assertEqual(self.db.LeaveTicketHelper(self.ticketId, 2001)[0], "left")
        # An original helper remains a ticket participant for override-conflict checks,
        # even after leaving the active helper roster.
        self.assertTrue(self.db.IsUserTicketParticipant(self.ticketId, 2001))
        status, activeCount, originalCount, missingCount = self.db.SubmitReplacementCandidates(
            self.ticketId, 1001, [3001]
        )
        self.assertEqual((status, activeCount, originalCount, missingCount), ("requested", 1, 2, 1))
        self.assertTrue(self.db.IsUserTicketParticipant(self.ticketId, 3001))

    def test_staff_participant_conflict_clears_after_ticket_is_resolved(self):
        self.assertTrue(self.db.IsUserParticipantInAnyOpenTicket(1001))
        self.assertTrue(self.db.IsUserParticipantInAnyOpenTicket(2001))
        self.assertTrue(self.db.IsUserParticipantInAnyOpenTicket(2002))
        self.assertFalse(self.db.IsUserParticipantInAnyOpenTicket(9001))

        self.assertEqual(self.db.RefundTicket(self.ticketId)[0], "refunded")
        self.assertFalse(self.db.IsUserParticipantInAnyOpenTicket(1001))
        self.assertFalse(self.db.IsUserParticipantInAnyOpenTicket(2001))
        self.assertFalse(self.db.IsUserParticipantInAnyOpenTicket(2002))



if __name__ == "__main__":
    unittest.main()
