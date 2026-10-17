"""Tests for the named per-server database layout and safe legacy migration."""

import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxfruits_helper_credit_bot.database import DatabaseManager
from bloxfruits_helper_credit_bot.database.guild_database import GuildDatabase
from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES


class DatabaseLayoutMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempDirectory = tempfile.TemporaryDirectory()
        self.dataRoot = Path(self.tempDirectory.name) / "data"
        self.serverId = 987654321012345678

    def tearDown(self):
        self.tempDirectory.cleanup()

    def test_legacy_database_migrates_and_preserves_data(self):
        legacyPath = self.dataRoot / "guilds" / str(self.serverId) / "guild.sqlite3"
        legacyDatabase = GuildDatabase(legacyPath, self.serverId, 100, DEFAULT_SERVICES)
        legacyDatabase.CreateUser(555001, 425)
        legacyDatabase.SetDefaultJoinCredits(99)
        legacyDatabase.SaveService("v4_trials", "V4 Trials", 275)
        reservedTicketId = legacyDatabase.ReserveTicket(
            channelId=990001,
            creatorId=555001,
            eventKey="v4_trials",
            helperIds=[555002],
            requiredCredits=200,
        )
        self.assertIsNotNone(reservedTicketId)
        legacyDatabase.Close()

        manager = DatabaseManager(self.dataRoot, DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES)
        try:
            database = manager.ForServer(self.serverId)
            expectedPath = self.dataRoot / "servers" / str(self.serverId) / "blox_fruits_credit_system.sqlite3"
            self.assertEqual(database.databasePath, expectedPath)
            self.assertEqual(database.GetBalance(555001), 225)
            self.assertEqual(database.GetDefaultJoinCredits(), 99)
            self.assertEqual(int(database.GetService("v4_trials")["price"]), 275)
            preservedTicket = database.GetOpenTicketForUser(555001)
            self.assertIsNotNone(preservedTicket)
            self.assertEqual(int(preservedTicket["channel_id"]), 990001)
            ledgerCount = database.Execute(
                "SELECT COUNT(*) AS amount FROM transactions WHERE ticket_id = ?",
                (int(preservedTicket["ticket_id"]),), fetchOne=True,
            )["amount"]
            self.assertGreaterEqual(int(ledgerCount), 1)
            archives = list((self.dataRoot / "legacy-database-archives").glob(f"server-{self.serverId}-*"))
            self.assertEqual(len(archives), 1)
            self.assertTrue((archives[0] / "guild.sqlite3").exists())
        finally:
            manager.CloseAll()

    def test_existing_new_and_legacy_databases_are_never_guessed_between(self):
        legacyPath = self.dataRoot / "guilds" / str(self.serverId) / "guild.sqlite3"
        legacyDatabase = GuildDatabase(legacyPath, self.serverId, 100, DEFAULT_SERVICES)
        legacyDatabase.CreateUser(555002, 100)
        legacyDatabase.Close()

        newPath = self.dataRoot / "servers" / str(self.serverId) / "blox_fruits_credit_system.sqlite3"
        newDatabase = GuildDatabase(newPath, self.serverId, 100, DEFAULT_SERVICES)
        newDatabase.CreateUser(555003, 200)
        newDatabase.Close()

        manager = DatabaseManager(self.dataRoot, DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES)
        try:
            with self.assertRaisesRegex(RuntimeError, "Both the new server database and the old guild database exist"):
                manager.ForServer(self.serverId)
            self.assertTrue(legacyPath.exists())
            self.assertTrue(newPath.exists())
        finally:
            manager.CloseAll()


if __name__ == "__main__":
    unittest.main()
