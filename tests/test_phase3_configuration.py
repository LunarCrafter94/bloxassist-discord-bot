"""Tests for guild-specific Phase 3 configuration persistence."""

import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxassist_discord_bot.database import DatabaseManager
from bloxassist_discord_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES


class Phase3ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.tempDir.name) / "data",
            defaultJoinCredits=DEFAULT_JOIN_CREDITS,
            defaultServices=DEFAULT_SERVICES,
        )
        self.guildA = self.manager.ForServer(111111111111111111)
        self.guildB = self.manager.ForServer(222222222222222222)

    def tearDown(self):
        self.manager.CloseAll()
        self.tempDir.cleanup()

    def test_starting_credit_setting_changes_only_new_accounts(self):
        self.guildA.CreateUser(3001, 100)
        self.guildA.SetDefaultJoinCredits(250)
        self.assertEqual(self.guildA.GetBalance(3001), 100)
        self.assertEqual(self.guildA.GetBalance(3002), 250)
        self.assertEqual(self.guildB.GetBalance(3002), 100)

    def test_starting_credits_allow_zero_and_reject_negative(self):
        self.guildA.SetDefaultJoinCredits(0)
        self.assertEqual(self.guildA.GetDefaultJoinCredits(), 0)
        with self.assertRaises(ValueError):
            self.guildA.SetDefaultJoinCredits(-1)

    def test_maximum_helper_count_is_guild_specific_and_bounded(self):
        self.guildA.SetMaxHelpers(12)
        self.assertEqual(self.guildA.GetMaxHelpers(), 12)
        self.assertEqual(self.guildB.GetMaxHelpers(), 5)
        with self.assertRaises(ValueError):
            self.guildA.SetMaxHelpers(26)
        with self.assertRaises(ValueError):
            self.guildA.SetMaxHelpers(0)

    def test_invite_defaults_are_seeded_per_guild(self):
        self.assertEqual(self.guildA.GetSetting("invite_rewards_enabled"), "false")
        self.assertEqual(self.guildA.GetSetting("invite_reward_credits"), "50")
        self.assertEqual(self.guildA.GetSetting("invite_duration_minutes"), "60")
        self.guildA.SetSetting("invite_rewards_enabled", "true")
        self.guildA.SetSetting("invite_reward_credits", 125)
        self.assertEqual(self.guildA.GetSetting("invite_rewards_enabled"), "true")
        self.assertEqual(self.guildA.GetSetting("invite_reward_credits"), "125")
        self.assertEqual(self.guildB.GetSetting("invite_rewards_enabled"), "false")
        self.assertEqual(self.guildB.GetSetting("invite_reward_credits"), "50")

    def test_inviter_leave_penalty_repeat_setting_is_guild_specific_and_disabled_by_default(self):
        setting = "invite_leave_penalty_repeat_on_rejoin"
        self.assertEqual(self.guildA.GetSetting(setting), "false")
        self.assertEqual(self.guildB.GetSetting(setting), "false")

        self.guildA.SetSetting(setting, "true")
        self.assertEqual(self.guildA.GetSetting(setting), "true")
        self.assertEqual(self.guildB.GetSetting(setting), "false")

    def test_event_catalog_change_is_guild_specific(self):
        self.guildA.SaveService("test_event", "Test Event", 325, active=False)
        inactive = self.guildA.GetService("test_event", activeOnly=False)
        self.assertEqual(int(inactive["price"]), 325)
        self.assertEqual(int(inactive["active"]), 0)
        self.assertIsNone(self.guildA.GetService("test_event", activeOnly=True))
        self.assertIsNone(self.guildB.GetService("test_event", activeOnly=False))

    def test_ticket_keeps_the_price_reserved_at_creation(self):
        requesterId = 5101
        self.guildA.CreateUser(requesterId, 500)
        ticketId = self.guildA.ReserveTicket(
            channelId=9101,
            creatorId=requesterId,
            eventKey="v4_trials",
            helperIds=[6101],
            requiredCredits=int(self.guildA.GetService("v4_trials")["price"]),
            pricePerHelper=int(self.guildA.GetService("v4_trials")["price"]),
        )
        self.assertIsNotNone(ticketId)
        self.guildA.SaveService("v4_trials", "V4 Trials", 300, active=True)
        ticket = self.guildA.GetTicketById(ticketId)
        self.assertEqual(int(ticket["required_credits"]), 200)
        self.assertEqual(int(ticket["reserved_credits"]), 200)
        self.assertEqual(int(ticket["price_per_helper"]), 200)
        self.assertEqual(int(self.guildA.GetService("v4_trials")["price"]), 300)

    def test_dashboard_and_help_center_ids_are_separate_per_guild(self):
        self.guildA.SetSetting("dashboard_channel_id", 7001)
        self.guildA.SetSetting("dashboard_message_id", 7002)
        self.guildA.SetSetting("help_center_channel_id", 8001)
        self.guildA.SetSetting("help_center_message_id", 8002)
        self.assertEqual(self.guildA.GetSetting("dashboard_channel_id"), "7001")
        self.assertEqual(self.guildA.GetSetting("dashboard_message_id"), "7002")
        self.assertEqual(self.guildA.GetSetting("help_center_channel_id"), "8001")
        self.assertEqual(self.guildA.GetSetting("help_center_message_id"), "8002")
        self.assertEqual(self.guildB.GetSetting("dashboard_channel_id"), "")
        self.assertEqual(self.guildB.GetSetting("help_center_channel_id"), "")

    def test_default_services_exclude_redundant_race_awakening(self):
        service_keys = {service[0] for service in DEFAULT_SERVICES}

        self.assertIn("v4_trials", service_keys)
        self.assertNotIn("race_awakening", service_keys)


if __name__ == "__main__":
    unittest.main()
