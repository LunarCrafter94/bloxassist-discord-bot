"""Regression tests for numeric credit lookups of current and former members."""

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from bloxassist_discord_bot import bot_client
except ModuleNotFoundError as error:
    if error.name != "discord":
        raise
    bot_client = None


@unittest.skipIf(bot_client is None, "discord.py is not installed in this validation environment")
class CreditLookupTests(unittest.TestCase):
    def test_accepts_full_discord_snowflakes_above_safe_json_integer_range(self):
        userId = "1560494021573349480"
        self.assertEqual(bot_client.ParseDiscordUserId(userId), int(userId))

    def test_strips_whitespace_around_numeric_user_id(self):
        self.assertEqual(bot_client.ParseDiscordUserId("  1560494021573349480  "), 1560494021573349480)

    def test_none_means_no_explicit_user_id(self):
        self.assertIsNone(bot_client.ParseDiscordUserId(None))

    def test_rejects_usernames_mentions_and_non_ascii_digits(self):
        for value in ("clivezareth.playz2026", "<@1560494021573349480>", "１２３４"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    bot_client.ParseDiscordUserId(value)

    def test_rejects_zero_and_values_outside_unsigned_snowflake_range(self):
        for value in ("0", str((1 << 64))):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    bot_client.ParseDiscordUserId(value)

    def test_resolves_current_member_without_user_id(self):
        member = SimpleNamespace(id=1560494021573349480)
        self.assertEqual(bot_client.ResolveCreditLookupUserId(member, None), member.id)

    def test_resolves_former_member_from_user_id(self):
        self.assertEqual(
            bot_client.ResolveCreditLookupUserId(None, "1560494021573349480"),
            1560494021573349480,
        )

    def test_credit_history_defaults_to_invoking_user(self):
        self.assertEqual(
            bot_client.ResolveCreditLookupUserId(None, None, defaultUserId=123456),
            123456,
        )

    def test_rejects_ambiguous_member_and_user_id_inputs(self):
        member = SimpleNamespace(id=123456)
        with self.assertRaisesRegex(ValueError, "not both"):
            bot_client.ResolveCreditLookupUserId(member, "123456")

    def test_member_transform_errors_offer_former_member_id_lookup(self):
        class FakeTransformerError(Exception):
            pass

        with patch.object(bot_client.app_commands, "TransformerError", FakeTransformerError):
            message = bot_client.AppCommandErrorMessage("credits", FakeTransformerError())

        self.assertIn("currently in this server", message)
        self.assertIn("user_id", message)
        self.assertIn("numeric Discord User ID", message)


if __name__ == "__main__":
    unittest.main()
