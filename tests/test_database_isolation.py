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

    def testTicketNumbersIncreaseAcrossEmptyQueueWithoutReset(self):
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

        # Ticket numbering must not reset merely because every open ticket closes.
        self.assertEqual(self.guildA.RefundTicket(secondTicketId), ("refunded", 10))
        self.assertEqual(self.guildA.RefundTicket(thirdTicketId), ("refunded", 10))
        _, nextNumber = createTicket(8104, 6104)
        self.assertEqual(nextNumber, 4)

        # The sequence is guild-local, so another server starts at 1-001 even while
        # this server has a newer ticket number.
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

    def testChannelNumbersResetWhenNoTicketsRemainButTranscriptSequenceContinues(self):
        def createTicket(channelId, creatorId):
            ticketId = self.guildA.ReserveTicket(
                channelId=channelId, creatorId=creatorId, eventKey="channel_cycle_test",
                helperIds=[creatorId + 10000], requiredCredits=0,
            )
            self.assertIsNotNone(ticketId)
            return ticketId, self.guildA.GetTicketById(ticketId)

        firstId, first = createTicket(8301, 6301)
        self.assertEqual(int(first["channel_ticket_number"]), 1)
        self.assertEqual(int(first["ticket_sequence"]), 1)

        # With an open ticket still present, labels move forward and do not collide.
        secondId, second = createTicket(8302, 6302)
        self.assertEqual(int(second["channel_ticket_number"]), 2)
        self.assertEqual(int(second["ticket_sequence"]), 2)

        self.assertEqual(self.guildA.RefundTicket(firstId), ("refunded", 0))
        thirdId, third = createTicket(8303, 6303)
        self.assertEqual(int(third["channel_ticket_number"]), 3)
        self.assertEqual(int(third["ticket_sequence"]), 3)

        # Once every active ticket is closed, the channel number can return to 001,
        # but the permanent transcript sequence continues and stays unique.
        self.assertEqual(self.guildA.RefundTicket(secondId), ("refunded", 0))
        self.assertEqual(self.guildA.RefundTicket(thirdId), ("refunded", 0))
        fourthId, fourth = createTicket(8304, 6304)
        self.assertEqual(int(fourth["channel_ticket_number"]), 1)
        self.assertEqual(int(fourth["ticket_number"]), 4)
        self.assertEqual(int(fourth["ticket_sequence"]), 4)

        from bloxfruits_helper_credit_bot.ticket_numbers import TicketChannelLabelFromRow, TicketLabelFromRow
        self.assertEqual(TicketChannelLabelFromRow(fourth), "001")
        self.assertEqual(TicketLabelFromRow(fourth), "004")

    def testActiveChannelNumbersCannotBeReused(self):
        ids = []
        channelNumbers = []
        for index in range(3):
            ticketId = self.guildA.ReserveTicket(
                channelId=8401 + index, creatorId=6401 + index, eventKey="active_channel_test",
                helperIds=[16401 + index], requiredCredits=0,
            )
            self.assertIsNotNone(ticketId)
            ticket = self.guildA.GetTicketById(ticketId)
            ids.append(ticketId)
            channelNumbers.append(int(ticket["channel_ticket_number"]))
        self.assertEqual(channelNumbers, [1, 2, 3])
        self.assertEqual(len(set(channelNumbers)), 3)
        for ticketId in ids:
            self.assertEqual(self.guildA.RefundTicket(ticketId)[0], "refunded")

    def testTicketNumberDoesNotWrapAfter100EvenWithNoOpenTickets(self):
        numbers = []
        for index in range(101):
            requesterId = 930000 + index
            ticketId = self.guildA.ReserveTicket(
                channelId=940000 + index, creatorId=requesterId, eventKey="cycle_test",
                helperIds=[950000 + index], requiredCredits=0,
            )
            self.assertIsNotNone(ticketId)
            ticket = self.guildA.GetTicketById(ticketId)
            numbers.append(int(ticket["ticket_number"]))
            self.assertEqual(int(ticket["ticket_sequence"]), index + 1)
            status, amount = self.guildA.RefundTicket(ticketId)
            self.assertEqual((status, amount), ("refunded", 0))
        self.assertEqual(numbers[:3], [1, 2, 3])
        self.assertEqual(numbers[98:101], [99, 100, 101])
        from bloxfruits_helper_credit_bot.ticket_numbers import TicketLabelFromRow
        firstHundredth = self.guildA.GetTicketById(100)
        hundredFirst = self.guildA.GetTicketById(101)
        self.assertEqual(TicketLabelFromRow(firstHundredth), "100")
        self.assertEqual(TicketLabelFromRow(hundredFirst), "101")
        self.assertEqual(self.guildA.GetSetting("next_ticket_sequence"), "102")

        # A process restart must not reset the counter.
        dataDir = self.databaseManager.dataDir
        self.databaseManager.CloseAll()
        self.databaseManager = DatabaseManager(
            dataDir,
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.guildA = self.databaseManager.ForServer(111111111111111111)
        nextTicketId = self.guildA.ReserveTicket(
            channelId=990999,
            creatorId=990998,
            eventKey="cycle_test",
            helperIds=[990997],
            requiredCredits=0,
        )
        self.assertIsNotNone(nextTicketId)
        nextTicket = self.guildA.GetTicketById(nextTicketId)
        self.assertEqual(int(nextTicket["ticket_number"]), 102)
        self.assertEqual(TicketLabelFromRow(nextTicket), "102")

    def testLegacyCycledTicketLabelsArePreservedAndCounterContinuesAfterUpgrade(self):
        # Build a small data set, then emulate v0.7.0's wrapped labels and settings.
        legacyTicketIds = []
        for index in range(3):
            ticketId = self.guildA.ReserveTicket(
                channelId=970001 + index,
                creatorId=970101 + index,
                eventKey="legacy_cycle",
                helperIds=[970201 + index],
                requiredCredits=0,
            )
            self.assertIsNotNone(ticketId)
            legacyTicketIds.append(ticketId)
            self.assertEqual(self.guildA.RefundTicket(ticketId), ("refunded", 0))

        for ticketId, oldNumber in zip(legacyTicketIds, (1, 2, 1)):
            self.guildA.Execute(
                "UPDATE tickets SET ticket_number = ?, ticket_sequence = NULL WHERE ticket_id = ?",
                (oldNumber, ticketId),
            )
        self.guildA.Execute("DELETE FROM settings WHERE setting_key = 'next_ticket_sequence'")
        self.guildA.Execute(
            "INSERT INTO settings(setting_key, setting_value) VALUES ('next_ticket_number', '2')"
        )

        dataDir = self.databaseManager.dataDir
        self.databaseManager.CloseAll()
        self.databaseManager = DatabaseManager(
            dataDir,
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.guildA = self.databaseManager.ForServer(111111111111111111)

        from bloxfruits_helper_credit_bot.ticket_numbers import TicketLabelFromRow
        legacyLabels = [TicketLabelFromRow(self.guildA.GetTicketById(ticketId)) for ticketId in legacyTicketIds]
        self.assertEqual(legacyLabels, ["001", "002", "001"])
        self.assertEqual(self.guildA.GetSetting("next_ticket_sequence"), "4")
        ticketColumns = {
            str(row["name"])
            for row in self.guildA.Execute("PRAGMA table_info(tickets)", fetchAll=True)
        }
        self.assertIn("transcript_saved", ticketColumns)

        newTicketId = self.guildA.ReserveTicket(
            channelId=970009,
            creatorId=970109,
            eventKey="after_upgrade",
            helperIds=[970209],
            requiredCredits=0,
        )
        self.assertIsNotNone(newTicketId)
        newTicket = self.guildA.GetTicketById(newTicketId)
        self.assertEqual(TicketLabelFromRow(newTicket), "004")

    def testRecordInviteAttributionCommitsBeforeInviteRewardTransaction(self):
        status, eventId, _ = self.guildA.StartInviteEvent(75, 60, startedBy=1234)
        self.assertEqual(status, "started")
        self.assertTrue(self.guildA.RecordInviteAttribution(22011, 22012, "invite-code"))
        self.assertFalse(self.guildA.connection.in_transaction)

        result = self.guildA.AwardInviteReward(
            eventId, invitedUserId=22011, inviterUserId=22012, inviteCode="invite-code"
        )
        self.assertEqual(result[0], "awarded")
        self.assertEqual(result[1], 175)
        self.assertFalse(self.guildA.connection.in_transaction)

    def testMarkInviteLeavePenaltyAppliedCommitsBeforeNextTransaction(self):
        self.guildA.Execute(
            "INSERT INTO invite_attributions(invited_user_id, inviter_user_id, invite_code) VALUES (?, ?, ?)",
            (22111, 22112, "leave-code"),
        )
        self.assertTrue(self.guildA.MarkInviteLeavePenaltyApplied(22111))
        self.assertFalse(self.guildA.connection.in_transaction)

        status, balance, debt = self.guildA.ApplyPenaltyDebt(
            22112, 125, actorUserId=1234, reason="leave penalty QA"
        )
        self.assertEqual((status, balance, debt), ("penalized", 0, 25))
        self.assertFalse(self.guildA.connection.in_transaction)

    def testInviteLeavePenaltyCanRepeatOncePerDistinctRejoinCycle(self):
        invitedId, inviterId = 22121, 22122
        self.guildA.CreateUser(inviterId, credits=0)
        firstJoin = "2026-11-04T10:00:00+00:00"
        secondJoin = "2026-11-04T11:00:00+00:00"

        self.assertTrue(self.guildA.RecordInviteAttribution(
            invitedId, inviterId, "repeat-code",
            repeatOnRejoin=True, joinedAt=firstJoin,
        ))
        firstAttribution = self.guildA.GetInviteAttribution(invitedId)
        self.assertEqual(int(firstAttribution["join_cycle"]), 1)

        firstKey = f"invite-leave-penalty:111111111111111111:{invitedId}"
        firstPenalty = self.guildA.ApplyPenaltyDebt(
            inviterId, 50, actorUserId=1234, reason="first leave",
            idempotencyKey=firstKey,
        )
        self.assertEqual(firstPenalty, ("penalized", 0, 50))
        self.assertTrue(self.guildA.MarkInviteLeavePenaltyApplied(invitedId, joinCycle=1))

        # Duplicate delivery of the same Discord join timestamp cannot re-arm
        # the penalty, and replaying the same leave-cycle key cannot charge twice.
        self.assertFalse(self.guildA.RecordInviteAttribution(
            invitedId, inviterId, "repeat-code",
            repeatOnRejoin=True, joinedAt=firstJoin,
        ))
        self.assertIsNone(self.guildA.GetInviteAttribution(invitedId))
        duplicatePenalty = self.guildA.ApplyPenaltyDebt(
            inviterId, 50, actorUserId=1234, reason="duplicate first leave",
            idempotencyKey=firstKey,
        )
        self.assertEqual(duplicatePenalty, ("duplicate", 0, 50))
        self.assertEqual(self.guildA.GetCreditDebt(inviterId), 50)

        # A distinct rejoin starts cycle 2 and re-arms exactly one new penalty.
        self.assertTrue(self.guildA.RecordInviteAttribution(
            invitedId, inviterId, "repeat-code",
            repeatOnRejoin=True, joinedAt=secondJoin,
        ))
        secondAttribution = self.guildA.GetInviteAttribution(invitedId)
        self.assertEqual(int(secondAttribution["join_cycle"]), 2)
        self.assertEqual(int(secondAttribution["penalty_applied"]), 0)

        secondKey = f"invite-leave-penalty:111111111111111111:{invitedId}:2"
        secondPenalty = self.guildA.ApplyPenaltyDebt(
            inviterId, 50, actorUserId=1234, reason="second leave",
            idempotencyKey=secondKey,
        )
        self.assertEqual(secondPenalty, ("penalized", 0, 100))
        self.assertTrue(self.guildA.MarkInviteLeavePenaltyApplied(invitedId, joinCycle=2))
        self.assertEqual(self.guildA.GetCreditDebt(inviterId), 100)

        penaltyRows = self.guildA.Execute(
            "SELECT idempotency_key FROM transactions WHERE type = 'penalty_debt' AND to_user = ? ORDER BY id",
            (inviterId,), fetchAll=True,
        )
        self.assertEqual([row["idempotency_key"] for row in penaltyRows], [firstKey, secondKey])

    def testInviteLeavePenaltyDoesNotRearmWhenRepeatSettingIsDisabled(self):
        invitedId, inviterId = 22131, 22132
        firstJoin = "2026-11-04T10:00:00+00:00"
        secondJoin = "2026-11-04T11:00:00+00:00"
        self.assertTrue(self.guildA.RecordInviteAttribution(
            invitedId, inviterId, "once-code",
            repeatOnRejoin=False, joinedAt=firstJoin,
        ))
        self.assertTrue(self.guildA.MarkInviteLeavePenaltyApplied(invitedId, joinCycle=1))

        self.assertFalse(self.guildA.RecordInviteAttribution(
            invitedId, inviterId, "once-code",
            repeatOnRejoin=False, joinedAt=secondJoin,
        ))
        self.assertIsNone(self.guildA.GetInviteAttribution(invitedId))
        stored = self.guildA.Execute(
            "SELECT join_cycle, joined_at, penalty_applied FROM invite_attributions WHERE invited_user_id = ?",
            (invitedId,), fetchOne=True,
        )
        self.assertEqual(
            (int(stored["join_cycle"]), str(stored["joined_at"]), int(stored["penalty_applied"])),
            (1, secondJoin, 1),
        )

    def testLateLeaveHandlerCannotMarkANewerJoinCycleAsPenalized(self):
        invitedId, inviterId = 22141, 22142
        self.guildA.RecordInviteAttribution(
            invitedId, inviterId, "cycle-code",
            repeatOnRejoin=True, joinedAt="2026-11-04T10:00:00+00:00",
        )
        self.guildA.RecordInviteAttribution(
            invitedId, inviterId, "cycle-code",
            repeatOnRejoin=True, joinedAt="2026-11-04T11:00:00+00:00",
        )
        self.assertIsNone(
            self.guildA.GetInviteAttribution(
                invitedId, joinedAt="2026-11-04T10:00:00+00:00"
            )
        )
        self.assertFalse(self.guildA.MarkInviteLeavePenaltyApplied(invitedId, joinCycle=1))
        current = self.guildA.GetInviteAttribution(
            invitedId, joinedAt="2026-11-04T11:00:00+00:00"
        )
        self.assertEqual(int(current["join_cycle"]), 2)
        self.assertEqual(int(current["penalty_applied"]), 0)

    def testLegacyInviteAttributionTableGainsJoinCycleColumnsOnUpgrade(self):
        dataDir = self.databaseManager.dataDir
        databasePath = self.guildA.databasePath
        self.databaseManager.CloseAll()

        with sqlite3.connect(databasePath) as connection:
            connection.execute("ALTER TABLE invite_attributions DROP COLUMN joined_at")
            connection.execute("ALTER TABLE invite_attributions DROP COLUMN join_cycle")

        self.databaseManager = DatabaseManager(
            dataDir,
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.guildA = self.databaseManager.ForServer(111111111111111111)
        columns = {
            str(row["name"])
            for row in self.guildA.Execute("PRAGMA table_info(invite_attributions)", fetchAll=True)
        }
        self.assertIn("join_cycle", columns)
        self.assertIn("joined_at", columns)

    def testInviteRewardEventsAreTimedAndAwardInviterOnce(self):
        status, eventId, endsAt = self.guildA.StartInviteEvent(75, 60, startedBy=1234)
        self.assertEqual(status, "started")
        self.assertIsNotNone(eventId)
        self.assertTrue(endsAt)
        self.assertEqual(self.guildA.StartInviteEvent(50, 60, startedBy=5678)[0], "already_active")

        first = self.guildA.AwardInviteReward(eventId, invitedUserId=22001, inviterUserId=22002, inviteCode="abc123")
        self.assertEqual(first[0], "awarded")
        self.assertEqual(first[1], 175)
        self.assertEqual(first[2], 75)
        second = self.guildA.AwardInviteReward(eventId, invitedUserId=22001, inviterUserId=22002, inviteCode="abc123")
        self.assertEqual(second[0], "duplicate")
        self.assertEqual(self.guildA.GetBalance(22002), 175)

        endedStatus, event = self.guildA.EndInviteEvent(endedBy=1234)
        self.assertEqual(endedStatus, "ended")
        self.assertEqual(int(event["event_id"]), eventId)
        self.assertIsNone(self.guildA.GetActiveInviteEvent())

    def testScamReportsAndTicketHistoryAreStoredPerServer(self):
        ticketId = self.guildA.ReserveTicket(
            channelId=960001, creatorId=960002, eventKey="history_event",
            helperIds=[960003], requiredCredits=0,
        )
        self.assertIsNotNone(ticketId)
        rows = self.guildA.ListTicketHistoryForMember(960003, limit=5)
        self.assertEqual([int(row["ticket_id"]) for row in rows], [ticketId])
        reportId = self.guildA.CreateScamReport(960002, 960003, "The helper did not provide the promised service.")
        report = self.guildA.Execute("SELECT * FROM scam_reports WHERE report_id = ?", (reportId,), fetchOne=True)
        self.assertEqual(report["reporter_user_id"], 960002)
        self.assertEqual(report["reported_user_id"], 960003)
        openReports = self.guildA.ListScamReports(status="open", limit=5)
        self.assertEqual([int(row["report_id"]) for row in openReports], [reportId])
        self.assertTrue(self.guildA.ResolveScamReport(reportId, reviewedBy=960004, decision="confirmed", note="Transcript reviewed"))
        self.assertFalse(self.guildA.ResolveScamReport(reportId, reviewedBy=960004, decision="dismissed", note="duplicate review"))
        reviewed = self.guildA.Execute("SELECT status, reviewed_by, review_note FROM scam_reports WHERE report_id = ?", (reportId,), fetchOne=True)
        self.assertEqual((reviewed["status"], reviewed["reviewed_by"], reviewed["review_note"]), ("confirmed", 960004, "Transcript reviewed"))

        # General reports may be submitted without targeting a specific member.
        bugReportId = self.guildA.CreateScamReport(
            960005,
            None,
            "The Continue button is not visible on mobile.",
            reportType="bug",
        )
        bugReport = self.guildA.Execute(
            "SELECT reporter_user_id, reported_user_id, report_type, details FROM scam_reports WHERE report_id = ?",
            (bugReportId,), fetchOne=True,
        )
        self.assertEqual(bugReport["reporter_user_id"], 960005)
        self.assertEqual(bugReport["reported_user_id"], 0)
        self.assertEqual(bugReport["report_type"], "bug")
        self.assertEqual(bugReport["details"], "The Continue button is not visible on mobile.")
        self.assertTrue(self.guildA.ResolveScamReport(
            bugReportId, reviewedBy=960004, decision="dismissed", note="Fixed in latest update"
        ))

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
            self.assertIn("ticket_sequence", ticketColumns)
            self.assertIn("channel_ticket_number", ticketColumns)
            self.assertIn("transcript_saved", ticketColumns)
            self.assertIn("actor_user_id", transactionColumns)
            self.assertIn("note", transactionColumns)
            self.assertIn("idempotency_key", transactionColumns)
        finally:
            legacyDatabase.Close()


if __name__ == "__main__":
    unittest.main()
