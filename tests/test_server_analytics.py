"""Tests for the read-only server statistics and member activity summaries."""

import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.database import DatabaseManager
from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES


class ServerAnalyticsTests(unittest.TestCase):
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

    def test_server_statistics_aggregate_balances_debt_tickets_and_reports(self):
        firstMember = 810001
        secondMember = 810002
        self.db.CreateUser(firstMember, credits=200)
        self.db.CreateUser(secondMember, credits=75)

        status, balance = self.db.ApplyCreditAdjustment(
            firstMember,
            25,
            direction="add",
            actorUserId=900001,
            note="Statistics test",
        )
        self.assertEqual(status, "added")
        self.assertEqual(balance, 225)

        penaltyStatus, _, debt = self.db.ApplyPenaltyDebt(
            secondMember,
            100,
            actorUserId=900001,
            reason="Statistics test penalty",
        )
        self.assertEqual(penaltyStatus, "penalized")
        self.assertEqual(debt, 25)

        ticketId = self.db.ReserveTicket(
            channelId=820001,
            creatorId=firstMember,
            eventKey="statistics_test",
            helperIds=[secondMember],
            requiredCredits=0,
        )
        self.assertIsNotNone(ticketId)

        openReportId = self.db.CreateScamReport(
            reporterUserId=firstMember,
            reportedUserId=secondMember,
            details="Open report for statistics test",
            reportType="bug",
        )
        confirmedReportId = self.db.CreateScamReport(
            reporterUserId=firstMember,
            reportedUserId=secondMember,
            details="Confirmed report for statistics test",
            reportType="scam",
        )
        self.assertTrue(
            self.db.ResolveScamReport(confirmedReportId, 900001, "confirmed", "Reviewed")
        )

        stats = self.db.GetServerStatistics()

        self.assertEqual(stats["tracked_members"], 2)
        self.assertEqual(stats["available_credits"], 225)
        self.assertEqual(stats["debtors"], 1)
        self.assertEqual(stats["outstanding_debt"], 25)
        self.assertEqual(stats["ticket_statuses"].get("open"), 1)
        self.assertEqual(stats["report_statuses"].get("open"), 1)
        self.assertEqual(stats["report_statuses"].get("confirmed"), 1)
        self.assertGreater(stats["ledger_entries"], 0)
        self.assertEqual(stats["enabled_services"], len(DEFAULT_SERVICES))
        self.assertEqual(stats["invite_reward_count"], 0)
        self.assertEqual(stats["invite_reward_credits"], 0)
        self.assertFalse(stats["active_invite_event"])

        # Both report states remain independently queryable by the report browser.
        self.assertEqual(
            [int(row["report_id"]) for row in self.db.ListScamReports(status="open")],
            [openReportId],
        )
        self.assertEqual(
            [int(row["report_id"]) for row in self.db.ListScamReports(status="confirmed")],
            [confirmedReportId],
        )

    def test_member_activity_summary_combines_balance_transactions_and_ticket_history(self):
        targetMember = 830001
        helperMember = 830002
        self.db.CreateUser(targetMember, credits=150)

        status, balance = self.db.ApplyCreditAdjustment(
            targetMember,
            20,
            direction="add",
            actorUserId=900001,
            note="Member activity test",
        )
        self.assertEqual(status, "added")
        self.assertEqual(balance, 170)

        ticketId = self.db.ReserveTicket(
            channelId=830003,
            creatorId=targetMember,
            eventKey="member_activity_test",
            helperIds=[helperMember],
            requiredCredits=0,
        )
        self.assertIsNotNone(ticketId)

        summary = self.db.GetMemberActivitySummary(targetMember)

        self.assertEqual(summary["user_id"], targetMember)
        self.assertEqual(summary["available_credits"], 170)
        self.assertEqual(summary["outstanding_debt"], 0)
        self.assertGreaterEqual(summary["transaction_count"], 2)
        self.assertEqual(summary["ticket_count"], 1)
        self.assertEqual(summary["open_ticket_count"], 1)
        self.assertEqual(
            [int(row["ticket_id"]) for row in summary["recent_tickets"]],
            [int(ticketId)],
        )
        self.assertTrue(summary["recent_transactions"])

    def test_unknown_member_summary_does_not_create_a_credit_account(self):
        unknownMember = 840001

        summary = self.db.GetMemberActivitySummary(unknownMember)

        self.assertIsNone(summary["account"])
        self.assertIsNone(summary["available_credits"])
        self.assertEqual(summary["outstanding_debt"], 0)
        self.assertEqual(summary["transaction_count"], 0)
        self.assertEqual(summary["ticket_count"], 0)
        self.assertEqual(summary["recent_transactions"], [])
        self.assertEqual(summary["recent_tickets"], [])
        self.assertIsNone(self.db.GetUser(unknownMember))


if __name__ == "__main__":
    unittest.main()
