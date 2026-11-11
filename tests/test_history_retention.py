"""Tests for bounded retained ticket history while preserving active work."""

import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxassist_discord_bot.database import DatabaseManager
from bloxassist_discord_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES


class TicketHistoryRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tempDirectory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.tempDirectory.name) / "data",
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.db = self.manager.ForServer(777777777777777777)

    def tearDown(self):
        self.manager.CloseAll()
        self.tempDirectory.cleanup()

    def _create_closed_saved_ticket(self, index: int) -> tuple[int, int]:
        requester = 800000 + index
        helper = 900000 + index
        ticket_id = self.db.ReserveTicket(
            channelId=1000000 + index,
            creatorId=requester,
            eventKey="history_retention_test",
            helperIds=[helper],
            requiredCredits=0,
        )
        self.assertIsNotNone(ticket_id)
        self.assertEqual(self.db.RefundTicket(ticket_id)[0], "refunded")
        self.db.SetTicketTranscriptMessage(ticket_id, 123456789, 2000000 + index)
        return int(ticket_id), requester

    def test_retention_keeps_500_latest_saved_closed_tickets_and_all_open_tickets(self):
        closed_ids = []
        first_requester = None
        for index in range(501):
            ticket_id, requester_id = self._create_closed_saved_ticket(index)
            closed_ids.append(ticket_id)
            if index == 0:
                first_requester = requester_id

        # A closed ticket without a confirmed transcript must stay available for recovery.
        unsaved_id = self.db.ReserveTicket(
            channelId=3000001,
            creatorId=880001,
            eventKey="history_retention_unsaved",
            helperIds=[880002],
            requiredCredits=0,
        )
        self.assertIsNotNone(unsaved_id)
        self.assertEqual(self.db.RefundTicket(unsaved_id)[0], "refunded")

        # Open tickets are never pruned, even when their IDs are older/newer than the history window.
        open_id = self.db.ReserveTicket(
            channelId=3000002,
            creatorId=880003,
            eventKey="history_retention_open",
            helperIds=[880004],
            requiredCredits=0,
        )
        self.assertIsNotNone(open_id)

        original_balance = self.db.GetBalance(first_requester)
        removed = self.db.PruneTicketHistory(500)
        self.assertEqual(removed, 1)
        self.assertIsNone(self.db.GetTicketById(closed_ids[0]))
        self.assertIsNotNone(self.db.GetTicketById(closed_ids[1]))
        self.assertIsNotNone(self.db.GetTicketById(closed_ids[-1]))
        self.assertIsNotNone(self.db.GetTicketById(int(unsaved_id)))
        self.assertEqual(self.db.GetTicketById(int(open_id))["status"], "open")

        saved_closed_count = self.db.Execute(
            "SELECT COUNT(*) AS amount FROM tickets WHERE status <> 'open' AND transcript_saved = 1",
            fetchOne=True,
        )["amount"]
        self.assertEqual(int(saved_closed_count), 500)

        # Delete the pruned ticket's associated ledger rows to preserve FK integrity,
        # but keep the materialized balance and standalone adjustment ledger.
        old_transactions = self.db.Execute(
            "SELECT COUNT(*) AS amount FROM transactions WHERE ticket_id = ?",
            (closed_ids[0],), fetchOne=True,
        )["amount"]
        self.assertEqual(int(old_transactions), 0)
        self.assertEqual(self.db.GetBalance(first_requester), original_balance)

    def test_member_ticket_history_pages_do_not_overlap(self):
        requester = 880010
        helper = 880011
        createdIds = []
        for index in range(12):
            ticketId = self.db.ReserveTicket(
                channelId=4000000 + index,
                creatorId=requester,
                eventKey="ticket_history_pagination_test",
                helperIds=[helper],
                requiredCredits=0,
            )
            self.assertIsNotNone(ticketId)
            createdIds.append(int(ticketId))
            self.assertEqual(self.db.RefundTicket(ticketId)[0], "refunded")

        first = self.db.ListTicketHistoryForMember(requester, limit=6, offset=0)
        second = self.db.ListTicketHistoryForMember(requester, limit=6, offset=6)
        firstIds = [int(row["ticket_id"]) for row in first]
        secondIds = [int(row["ticket_id"]) for row in second]

        self.assertEqual(len(firstIds), 6)
        self.assertEqual(len(secondIds), 6)
        self.assertFalse(set(firstIds).intersection(secondIds))
        self.assertEqual(firstIds, list(reversed(createdIds[-6:])))
        self.assertEqual(secondIds, list(reversed(createdIds[:6])))

    def test_clearing_a_pruned_discord_message_does_not_erase_transcript_saved_marker(self):
        ticket_id, _ = self._create_closed_saved_ticket(999)
        self.db.ClearTicketTranscriptMessage(ticket_id)
        row = self.db.GetTicketById(ticket_id)
        self.assertEqual(int(row["transcript_saved"]), 1)
        self.assertIsNone(row["transcript_message_id"])


if __name__ == "__main__":
    unittest.main()
