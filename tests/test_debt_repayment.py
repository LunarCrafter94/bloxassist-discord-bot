import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.database import DatabaseManager
from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES


class DebtRepaymentTests(unittest.TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.tempDir.name) / "data",
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.db = self.manager.ForServer(111111111111111111)
        self.userId = 333333333333333333
        self.db.CreateUser(self.userId, credits=0)
        status, balance, debt = self.db.ApplyPenaltyDebt(
            self.userId, 150, actorUserId=9001, reason="test penalty",
            idempotencyKey="test-penalty-1",
        )
        self.assertEqual((status, balance, debt), ("penalized", 0, 150))

    def tearDown(self):
        self.manager.CloseAll()
        self.tempDir.cleanup()

    def addCredits(self, amount=200):
        return self.db.ApplyCreditAdjustment(
            self.userId, amount, direction="add", actorUserId=9001,
            note="test funding", idempotencyKey=f"funding-{amount}",
        )

    def testPartialRepaymentUpdatesBalanceDebtAndLedger(self):
        self.addCredits()
        result = self.db.RepayCreditDebt(self.userId, 50, idempotencyKey="repay-partial")
        self.assertEqual(result, ("repaid", 150, 100))
        row = self.db.Execute(
            "SELECT * FROM transactions WHERE idempotency_key = ?",
            ("repay-partial",), fetchOne=True,
        )
        self.assertEqual(row["type"], "debt_repayment")
        self.assertEqual(row["from_user"], self.userId)
        self.assertIsNone(row["to_user"])
        self.assertEqual(int(row["amount"]), 50)
        self.assertEqual(int(row["actor_user_id"]), self.userId)

    def testFullRepaymentClearsDebtButKeepsUnusedCredits(self):
        self.addCredits()
        self.assertEqual(self.db.RepayCreditDebt(self.userId, 150), ("repaid", 50, 0))
        self.assertEqual(self.db.GetCreditDebt(self.userId), 0)
        self.assertEqual(self.db.GetBalance(self.userId), 50)

    def testRepaymentCannotExceedOutstandingDebt(self):
        self.addCredits()
        self.assertEqual(self.db.RepayCreditDebt(self.userId, 151), ("exceeds_debt", 200, 150))
        self.assertEqual(self.db.GetBalance(self.userId), 200)
        self.assertEqual(self.db.GetCreditDebt(self.userId), 150)

    def testRepaymentCannotExceedAvailableCredits(self):
        self.assertEqual(
            self.db.RepayCreditDebt(self.userId, 1),
            ("insufficient_credits", 0, 150),
        )
        self.assertEqual(self.db.GetCreditDebt(self.userId), 150)

    def testDuplicateRepaymentIsIdempotent(self):
        self.addCredits()
        first = self.db.RepayCreditDebt(self.userId, 50, idempotencyKey="same-repayment")
        second = self.db.RepayCreditDebt(self.userId, 50, idempotencyKey="same-repayment")
        self.assertEqual(first, ("repaid", 150, 100))
        self.assertEqual(second, ("duplicate", 150, 100))
        count = self.db.Execute(
            "SELECT COUNT(*) AS count FROM transactions WHERE idempotency_key = ?",
            ("same-repayment",), fetchOne=True,
        )
        self.assertEqual(int(count["count"]), 1)

    def testReusingIdempotencyKeyForDifferentRepaymentIsRejected(self):
        self.addCredits()
        self.db.RepayCreditDebt(self.userId, 50, idempotencyKey="repayment-key")
        self.assertEqual(
            self.db.RepayCreditDebt(self.userId, 40, idempotencyKey="repayment-key"),
            ("idempotency_conflict", 150, 100),
        )
        self.assertEqual(self.db.GetBalance(self.userId), 150)
        self.assertEqual(self.db.GetCreditDebt(self.userId), 100)

    def testNoDebtDoesNotConsumeCredits(self):
        self.db.Execute("DELETE FROM credit_debts WHERE user_id = ?", (self.userId,))
        self.addCredits()
        self.assertEqual(self.db.RepayCreditDebt(self.userId, 50), ("no_debt", 200, 0))
        self.assertEqual(self.db.GetBalance(self.userId), 200)

    def testFutureTicketRewardAutomaticallyPaysDownDebtFirst(self):
        requesterId = 444444444444444444
        helperId = 555555555555555555
        self.db.CreateUser(requesterId, credits=200)
        self.db.CreateUser(helperId, credits=0)
        self.assertEqual(
            self.db.ApplyPenaltyDebt(
                helperId, 50, actorUserId=9001, reason="debt before ticket assignment",
                idempotencyKey="debt-before-ticket-assignment",
            ),
            ("penalized", 0, 50),
        )

        # An indebted helper must be accepted at reservation time. Their reward
        # will clear the debt first and credit only the remainder to their balance.
        ticketId = self.db.ReserveTicket(
            channelId=777777777777777777,
            creatorId=requesterId,
            eventKey="debt_reward_test",
            helperIds=[helperId],
            requiredCredits=100,
            pricePerHelper=100,
        )
        self.assertIsNotNone(ticketId)

        status, payouts = self.db.CompleteTicket(ticketId, actorUserId=9001, note="test payout")
        self.assertEqual(status, "completed")
        self.assertEqual(payouts, [(helperId, 100)])
        self.assertEqual(self.db.GetBalance(helperId), 50)
        self.assertEqual(self.db.GetCreditDebt(helperId), 0)

        offset = self.db.Execute(
            "SELECT * FROM transactions WHERE ticket_id = ? AND type = 'debt_repayment'",
            (ticketId,), fetchOne=True,
        )
        self.assertIsNotNone(offset)
        self.assertEqual(int(offset["amount"]), 50)
        self.assertIn("Automatic debt offset", str(offset["note"]))

        reward = self.db.Execute(
            "SELECT * FROM transactions WHERE ticket_id = ? AND type = 'ticket_reward'",
            (ticketId,), fetchOne=True,
        )
        self.assertIsNotNone(reward)
        self.assertEqual(int(reward["amount"]), 100)
        self.assertEqual(int(reward["from_user"]), requesterId)
        self.assertEqual(int(reward["to_user"]), helperId)

    def testRequesterWithOutstandingDebtCannotReserveTicket(self):
        helperId = 555555555555555555
        self.db.CreateUser(helperId, credits=0)

        ticketId = self.db.ReserveTicket(
            channelId=777777777777777778,
            creatorId=self.userId,
            eventKey="requester_debt_test",
            helperIds=[helperId],
            requiredCredits=100,
            pricePerHelper=100,
        )

        self.assertIsNone(ticketId)
        self.assertEqual(self.db.GetBalance(self.userId), 0)
        self.assertEqual(self.db.GetCreditDebt(self.userId), 150)
        ticketCount = self.db.Execute(
            "SELECT COUNT(*) AS count FROM tickets WHERE creator_id = ?",
            (self.userId,), fetchOne=True,
        )
        self.assertEqual(int(ticketCount["count"]), 0)

    def testCreditHistoryIncludesRepaymentsAndSupportsPagination(self):
        self.addCredits()
        self.db.RepayCreditDebt(self.userId, 50, idempotencyKey="history-repayment-1")
        self.db.RepayCreditDebt(self.userId, 25, idempotencyKey="history-repayment-2")
        firstPage = self.db.ListCreditTransactions(self.userId, limit=2, offset=0)
        secondPage = self.db.ListCreditTransactions(self.userId, limit=2, offset=2)
        thirdPage = self.db.ListCreditTransactions(self.userId, limit=2, offset=4)
        self.assertEqual(len(firstPage), 2)
        self.assertEqual(len(secondPage), 2)
        self.assertEqual(len(thirdPage), 1)
        self.assertEqual(firstPage[0]["type"], "debt_repayment")
        self.assertEqual(firstPage[1]["type"], "debt_repayment")
        self.assertEqual(secondPage[0]["type"], "admin_add")
        self.assertEqual(secondPage[1]["type"], "penalty_debt")
        self.assertEqual(thirdPage[0]["type"], "starting_balance")

    def testInvalidAmountsAreRejected(self):
        for amount in (0, -1, True, 1_000_000_001):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.db.RepayCreditDebt(self.userId, amount)


if __name__ == "__main__":
    unittest.main()
