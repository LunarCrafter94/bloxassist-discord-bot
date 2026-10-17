import tempfile
import unittest
from pathlib import Path
import sys
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES
from bloxfruits_helper_credit_bot.database import DatabaseManager


class PerGuildDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.databaseManager = DatabaseManager(
            Path(self.tempDir.name) / "data",
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.guildA = self.databaseManager.ForServer(111111111111111111)
        self.guildB = self.databaseManager.ForServer(222222222222222222)

    def tearDown(self):
        self.databaseManager.CloseAll()
        self.tempDir.cleanup()

    def testSameMemberHasIndependentBalances(self):
        memberId = 333333333333333333
        self.assertEqual(self.guildA.GetBalance(memberId), 100)
        self.assertEqual(self.guildB.GetBalance(memberId), 100)
        self.assertTrue(self.guildA.RemoveCredits(memberId, 40))
        self.assertEqual(self.guildA.GetBalance(memberId), 60)
        self.assertEqual(self.guildB.GetBalance(memberId), 100)
        self.assertNotEqual(self.guildA.databasePath, self.guildB.databasePath)
        self.assertEqual(self.guildA.databasePath.name, "blox_fruits_credit_system.sqlite3")
        self.assertEqual(self.guildA.databasePath.parent.name, "111111111111111111")
        self.assertEqual(self.guildB.databasePath.parent.name, "222222222222222222")

    def testServicePriceIsIndependentPerGuild(self):
        self.assertEqual(int(self.guildA.GetService("v4_trials")["price"]), 200)
        self.guildA.SaveService("v4_trials", "V4 Trials", 275)
        self.assertEqual(int(self.guildA.GetService("v4_trials")["price"]), 275)
        self.assertEqual(int(self.guildB.GetService("v4_trials")["price"]), 200)

    def testTicketReservationAndPayoutAreOnceOnly(self):
        requesterId = 4001
        helperIds = [5001, 5002]
        self.guildA.CreateUser(requesterId, 300)
        ticketId = self.guildA.ReserveTicket(
            channelId=7001,
            creatorId=requesterId,
            eventKey="v4_trials",
            helperIds=helperIds,
            requiredCredits=200,
        )
        self.assertIsNotNone(ticketId)
        self.assertEqual(self.guildA.GetBalance(requesterId), 100)
        reservationRow = self.guildA.Execute(
            "SELECT * FROM transactions WHERE ticket_id = ? AND type = 'ticket_reservation'",
            (ticketId,), fetchOne=True,
        )
        self.assertEqual(reservationRow["actor_user_id"], requesterId)

        status, payouts = self.guildA.CompleteTicket(ticketId, actorUserId=9001, note="test completion")
        self.assertEqual(status, "completed")
        self.assertEqual(payouts, [(5001, 100), (5002, 100)])
        self.assertEqual(self.guildA.GetBalance(5001), 200)
        self.assertEqual(self.guildA.GetBalance(5002), 200)
        payoutAudit = self.guildA.Execute(
            "SELECT * FROM transactions WHERE ticket_id = ? AND type = 'ticket_reward' ORDER BY id LIMIT 1",
            (ticketId,), fetchOne=True,
        )
        self.assertEqual(payoutAudit["actor_user_id"], 9001)
        self.assertEqual(payoutAudit["note"], "test completion")

        secondStatus, secondPayouts = self.guildA.CompleteTicket(ticketId)
        self.assertEqual(secondStatus, "not_open")
        self.assertEqual(secondPayouts, [])
        self.assertEqual(self.guildA.GetBalance(5001), 200)
        self.assertEqual(self.guildA.GetBalance(5002), 200)

    def testRefundIsOnceOnlyAndServerScoped(self):
        requesterId = 4002
        self.guildA.CreateUser(requesterId, 250)
        ticketId = self.guildA.ReserveTicket(
            channelId=7002,
            creatorId=requesterId,
            eventKey="leviathan",
            helperIds=[5003],
            requiredCredits=100,
        )
        self.assertIsNotNone(ticketId)
        self.assertEqual(self.guildA.GetBalance(requesterId), 150)
        self.assertEqual(self.guildB.GetBalance(requesterId), 100)

        status, amount = self.guildA.RefundTicket(
            ticketId, actorUserId=8901, note="test moderator refund"
        )
        self.assertEqual((status, amount), ("refunded", 100))
        self.assertEqual(self.guildA.GetBalance(requesterId), 250)
        refundAudit = self.guildA.Execute(
            "SELECT * FROM transactions WHERE ticket_id = ? AND type = 'refund'",
            (ticketId,), fetchOne=True,
        )
        self.assertEqual(refundAudit["actor_user_id"], 8901)
        self.assertEqual(refundAudit["note"], "test moderator refund")

        secondStatus, secondAmount = self.guildA.RefundTicket(ticketId)
        self.assertEqual(secondStatus, "not_open")
        self.assertIsNone(secondAmount)
        self.assertEqual(self.guildA.GetBalance(requesterId), 250)

    def testTicketNumbersIncreaseUntilAllTicketsCloseThenReset(self):
        def createTicket(channelId, creatorId):
            self.guildA.CreateUser(creatorId, 500)
            ticketId = self.guildA.ReserveTicket(
                channelId=channelId,
                creatorId=creatorId,
                eventKey="test_event",
                helperIds=[creatorId + 10000],
                requiredCredits=10,
            )
            self.assertIsNotNone(ticketId)
            ticket = self.guildA.GetTicketById(ticketId)
            return ticketId, int(ticket["ticket_number"])

        firstTicketId, firstNumber = createTicket(8101, 6101)
        secondTicketId, secondNumber = createTicket(8102, 6102)
        self.assertEqual((firstNumber, secondNumber), (1, 2))

        # Completing an earlier ticket must not reset the sequence while another
        # ticket remains open in this guild.
        firstStatus, firstPayouts = self.guildA.CompleteTicket(firstTicketId)
        self.assertEqual(firstStatus, "completed")
        self.assertEqual(firstPayouts, [(16101, 10)])
        thirdTicketId, thirdNumber = createTicket(8103, 6103)
        self.assertEqual(thirdNumber, 3)

        # Historical closed tickets remain in the database, but when the open
        # ticket count reaches zero, the next ticket starts over at 001.
        self.assertEqual(self.guildA.RefundTicket(secondTicketId), ("refunded", 10))
        self.assertEqual(self.guildA.RefundTicket(thirdTicketId), ("refunded", 10))
        _, resetNumber = createTicket(8104, 6104)
        self.assertEqual(resetNumber, 1)

        # The sequence is guild-local, so another server starts with 001 even while
        # this server has an open ticket numbered 001.
        self.guildB.CreateUser(6201, 500)
        otherGuildTicketId = self.guildB.ReserveTicket(
            channelId=8201,
            creatorId=6201,
            eventKey="test_event",
            helperIds=[16201],
            requiredCredits=10,
        )
        self.assertIsNotNone(otherGuildTicketId)
        otherGuildTicket = self.guildB.GetTicketById(otherGuildTicketId)
        self.assertEqual(int(otherGuildTicket["ticket_number"]), 1)

    def testCreditAdjustmentIsAtomicAndAudited(self):
        userId = 7101
        actorId = 7201
        self.guildA.CreateUser(userId, 100)
        startingRow = self.guildA.Execute(
            "SELECT * FROM transactions WHERE to_user = ? AND type = 'starting_balance'",
            (userId,), fetchOne=True,
        )
        self.assertIsNotNone(startingRow)
        self.assertEqual(startingRow["amount"], 100)

        status, balance = self.guildA.ApplyCreditAdjustment(
            userId,
            45,
            direction="add",
            actorUserId=actorId,
            note="Approved test addition",
            idempotencyKey="test-add-7101-001",
        )
        self.assertEqual((status, balance), ("added", 145))

        status, balance = self.guildA.ApplyCreditAdjustment(
            userId,
            25,
            direction="deduct",
            actorUserId=actorId,
            note="Approved test deduction",
            idempotencyKey="test-deduct-7101-001",
        )
        self.assertEqual((status, balance), ("deducted", 120))

        status, balance = self.guildA.ApplyCreditAdjustment(
            userId,
            999,
            direction="deduct",
            actorUserId=actorId,
            idempotencyKey="test-deduct-7101-insufficient",
        )
        self.assertEqual((status, balance), ("insufficient", 120))
        self.assertEqual(self.guildA.GetBalance(userId), 120)

        ledgerRows = self.guildA.Execute(
            "SELECT * FROM transactions WHERE idempotency_key IN (?, ?) ORDER BY id",
            ("test-add-7101-001", "test-deduct-7101-001"),
            fetchAll=True,
        )
        self.assertEqual(len(ledgerRows), 2)
        self.assertEqual(ledgerRows[0]["type"], "admin_add")
        self.assertEqual(ledgerRows[0]["actor_user_id"], actorId)
        self.assertEqual(ledgerRows[0]["note"], "Approved test addition")
        self.assertEqual(ledgerRows[1]["type"], "admin_deduct")
        self.assertEqual(ledgerRows[1]["actor_user_id"], actorId)

    def testAdjustmentIdempotencyPreventsDuplicateCreditChanges(self):
        userId = 7301
        actorId = 7302
        self.guildA.CreateUser(userId, 100)
        firstResult = self.guildA.ApplyCreditAdjustment(
            userId, 20, direction="add", actorUserId=actorId,
            idempotencyKey="discord-interaction-abc",
        )
        replayResult = self.guildA.ApplyCreditAdjustment(
            userId, 20, direction="add", actorUserId=actorId,
            idempotencyKey="discord-interaction-abc",
        )
        conflictResult = self.guildA.ApplyCreditAdjustment(
            userId, 50, direction="add", actorUserId=actorId,
            idempotencyKey="discord-interaction-abc",
        )

        self.assertEqual(firstResult, ("added", 120))
        self.assertEqual(replayResult, ("duplicate", 120))
        self.assertEqual(conflictResult, ("idempotency_conflict", 120))
        self.assertEqual(self.guildA.GetBalance(userId), 120)
        transactionCount = self.guildA.Execute(
            "SELECT COUNT(*) AS amount FROM transactions WHERE idempotency_key = ?",
            ("discord-interaction-abc",), fetchOne=True,
        )["amount"]
        self.assertEqual(transactionCount, 1)

    def testConcurrentAdjustmentWithSameIdempotencyKeyAppliesOnce(self):
        userId = 7351
        actorId = 7352
        self.guildA.CreateUser(userId, 100)
        secondManager = DatabaseManager(
            self.databaseManager.dataDir,
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        secondGuild = secondManager.ForServer(self.guildA.guildId)
        try:
            barrier = Barrier(2)

            def addCredits(database):
                barrier.wait()
                return database.ApplyCreditAdjustment(
                    userId,
                    35,
                    direction="add",
                    actorUserId=actorId,
                    idempotencyKey="concurrent-discord-interaction-xyz",
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(addCredits, [self.guildA, secondGuild]))

            self.assertEqual(sum(status == "added" for status, _ in results), 1)
            self.assertEqual(sum(status == "duplicate" for status, _ in results), 1)
            self.assertEqual(self.guildA.GetBalance(userId), 135)
            rowCount = self.guildA.Execute(
                "SELECT COUNT(*) AS amount FROM transactions WHERE idempotency_key = ?",
                ("concurrent-discord-interaction-xyz",), fetchOne=True,
            )["amount"]
            self.assertEqual(rowCount, 1)
        finally:
            secondManager.CloseAll()

    def testConcurrentReservationsCannotOverspendBalance(self):
        requesterId = 7401
        self.guildA.CreateUser(requesterId, 100)
        secondManager = DatabaseManager(
            self.databaseManager.dataDir,
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        secondGuild = secondManager.ForServer(self.guildA.guildId)

        try:
            barrier = Barrier(2)

            def reserve(database, channelId, helperId):
                barrier.wait()
                return database.ReserveTicket(
                    channelId=channelId,
                    creatorId=requesterId,
                    eventKey="concurrency_test",
                    helperIds=[helperId],
                    requiredCredits=80,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(
                    lambda args: reserve(*args),
                    [(self.guildA, 8401, 8402), (secondGuild, 8403, 8404)],
                ))

            self.assertEqual(sum(ticketId is not None for ticketId in results), 1)
            self.assertEqual(self.guildA.GetBalance(requesterId), 20)
            reservationCount = self.guildA.Execute(
                "SELECT COUNT(*) AS amount FROM transactions "
                "WHERE from_user = ? AND type = 'ticket_reservation'",
                (requesterId,), fetchOne=True,
            )["amount"]
            self.assertEqual(reservationCount, 1)
        finally:
            secondManager.CloseAll()

    def testConcurrentCompletionOnlyPaysHelpersOnce(self):
        requesterId = 7501
        helperIds = [7502, 7503]
        self.guildA.CreateUser(requesterId, 300)
        ticketId = self.guildA.ReserveTicket(
            channelId=8501,
            creatorId=requesterId,
            eventKey="concurrency_completion_test",
            helperIds=helperIds,
            requiredCredits=200,
        )
        self.assertIsNotNone(ticketId)

        secondManager = DatabaseManager(
            self.databaseManager.dataDir,
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        secondGuild = secondManager.ForServer(self.guildA.guildId)
        try:
            barrier = Barrier(2)

            def complete(database):
                barrier.wait()
                return database.CompleteTicket(ticketId)

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(complete, [self.guildA, secondGuild]))

            self.assertEqual(sum(result[0] == "completed" for result in results), 1)
            self.assertEqual(sum(result[0] == "not_open" for result in results), 1)
            self.assertEqual(self.guildA.GetBalance(helperIds[0]), 200)
            self.assertEqual(self.guildA.GetBalance(helperIds[1]), 200)
            rewardCount = self.guildA.Execute(
                "SELECT COUNT(*) AS amount FROM transactions WHERE ticket_id = ? AND type = 'ticket_reward'",
                (ticketId,), fetchOne=True,
            )["amount"]
            self.assertEqual(rewardCount, 2)
        finally:
            secondManager.CloseAll()

    def testFailedPayoutRollsBackStatusBalancesAndLedger(self):
        requesterId = 7601
        helperIds = [7602, 7603]
        self.guildA.CreateUser(requesterId, 300)
        ticketId = self.guildA.ReserveTicket(
            channelId=8601,
            creatorId=requesterId,
            eventKey="rollback_test",
            helperIds=helperIds,
            requiredCredits=200,
        )
        self.assertIsNotNone(ticketId)
        self.guildA.Execute(
            """CREATE TRIGGER fail_ticket_reward BEFORE INSERT ON transactions
               WHEN NEW.type = 'ticket_reward'
               BEGIN SELECT RAISE(ABORT, 'intentional test failure'); END"""
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.guildA.CompleteTicket(ticketId)

        ticket = self.guildA.GetTicketById(ticketId)
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(self.guildA.GetBalance(requesterId), 100)
        self.assertEqual(self.guildA.GetBalance(helperIds[0]), 100)
        rewardCount = self.guildA.Execute(
            "SELECT COUNT(*) AS amount FROM transactions WHERE ticket_id = ? AND type = 'ticket_reward'",
            (ticketId,), fetchOne=True,
        )["amount"]
        self.assertEqual(rewardCount, 0)
        self.guildA.Execute("DROP TRIGGER fail_ticket_reward")
        self.assertEqual(self.guildA.CompleteTicket(ticketId)[0], "completed")

    def testFailedReservationRollsBackBalanceTicketAndNumber(self):
        requesterId = 7701
        helperId = 7702
        self.guildA.CreateUser(requesterId, 300)
        self.guildA.Execute(
            """CREATE TRIGGER fail_ticket_reservation BEFORE INSERT ON transactions
               WHEN NEW.type = 'ticket_reservation'
               BEGIN SELECT RAISE(ABORT, 'intentional reservation failure'); END"""
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.guildA.ReserveTicket(
                channelId=8701,
                creatorId=requesterId,
                eventKey="reservation_rollback_test",
                helperIds=[helperId],
                requiredCredits=200,
            )

        self.assertEqual(self.guildA.GetBalance(requesterId), 300)
        ticketCount = self.guildA.Execute(
            "SELECT COUNT(*) AS amount FROM tickets WHERE channel_id = ?",
            (8701,), fetchOne=True,
        )["amount"]
        self.assertEqual(ticketCount, 0)
        self.guildA.Execute("DROP TRIGGER fail_ticket_reservation")

        validTicketId = self.guildA.ReserveTicket(
            channelId=8702,
            creatorId=requesterId,
            eventKey="reservation_rollback_test",
            helperIds=[helperId],
            requiredCredits=200,
        )
        self.assertIsNotNone(validTicketId)
        self.assertEqual(int(self.guildA.GetTicketById(validTicketId)["ticket_number"]), 1)

    def testFailedRefundRollsBackTicketAndBalance(self):
        requesterId = 7801
        self.guildA.CreateUser(requesterId, 300)
        ticketId = self.guildA.ReserveTicket(
            channelId=8801,
            creatorId=requesterId,
            eventKey="refund_rollback_test",
            helperIds=[7802],
            requiredCredits=200,
        )
        self.assertIsNotNone(ticketId)
        self.guildA.Execute(
            """CREATE TRIGGER fail_refund BEFORE INSERT ON transactions
               WHEN NEW.type = 'refund'
               BEGIN SELECT RAISE(ABORT, 'intentional refund failure'); END"""
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.guildA.RefundTicket(ticketId, actorUserId=7803, note="test refund")

        ticket = self.guildA.GetTicketById(ticketId)
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(self.guildA.GetBalance(requesterId), 100)
        refundCount = self.guildA.Execute(
            "SELECT COUNT(*) AS amount FROM transactions WHERE ticket_id = ? AND type = 'refund'",
            (ticketId,), fetchOne=True,
        )["amount"]
        self.assertEqual(refundCount, 0)
        self.guildA.Execute("DROP TRIGGER fail_refund")
        self.assertEqual(self.guildA.RefundTicket(ticketId), ("refunded", 200))
        self.assertEqual(self.guildA.GetBalance(requesterId), 300)

    def testLegacyTicketAndTransactionTablesGetPhase2Columns(self):
        legacyPath = Path(self.tempDir.name) / "legacy" / "guild.sqlite3"
        legacyPath.parent.mkdir(parents=True, exist_ok=True)
        legacyConnection = sqlite3.connect(legacyPath)
        try:
            legacyConnection.execute(
                """CREATE TABLE tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER UNIQUE,
                    guild_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    event_key TEXT NOT NULL,
                    helper_ids TEXT NOT NULL,
                    required_credits INTEGER NOT NULL,
                    reserved_credits INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                )"""
            )
            legacyConnection.execute(
                """CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER,
                    from_user INTEGER,
                    to_user INTEGER,
                    amount INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            legacyConnection.commit()
        finally:
            legacyConnection.close()

        from bloxfruits_helper_credit_bot.database.guild_database import GuildDatabase

        legacyDatabase = GuildDatabase(legacyPath, guildId=333333333333333333)
        try:
            ticketColumns = {
                row["name"] for row in legacyDatabase.Execute(
                    "PRAGMA table_info(tickets)", fetchAll=True
                )
            }
            transactionColumns = {
                row["name"] for row in legacyDatabase.Execute(
                    "PRAGMA table_info(transactions)", fetchAll=True
                )
            }
            self.assertIn("ticket_number", ticketColumns)
            self.assertIn("actor_user_id", transactionColumns)
            self.assertIn("note", transactionColumns)
            self.assertIn("idempotency_key", transactionColumns)
        finally:
            legacyDatabase.Close()


if __name__ == "__main__":
    unittest.main()
