"""Command registration checks for the nested /setup commands."""

import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from bloxfruits_helper_credit_bot.bot_client import CreateBot
    from bloxfruits_helper_credit_bot.settings import RuntimeSettings
except ModuleNotFoundError as error:
    if error.name != "discord":
        raise
    CreateBot = None
    RuntimeSettings = None


class SetupCommandTests(unittest.TestCase):
    @unittest.skipIf(CreateBot is None, "discord.py is not installed in this validation environment")
    def test_setup_has_public_tickets_and_admin_dashboard_subcommands(self):
        with tempfile.TemporaryDirectory() as tempDir:
            root = Path(tempDir)
            settings = RuntimeSettings(
                projectRoot=root,
                envFile=root / "private-configs" / "tokens.env",
                discordToken="not-used-by-this-test",
                commandGuildId=None,
            )
            bot = CreateBot(settings)
            try:
                import discord
                self.assertIsInstance(bot, discord.Client)
                self.assertFalse(hasattr(bot, "command_prefix"))
                setupGroup = bot.tree.get_command("setup")
                self.assertIsNotNone(setupGroup)
                subcommandNames = {command.name for command in setupGroup.commands}
                self.assertEqual(subcommandNames, {"public_tickets", "admin_dashboard"})
                self.assertIsNone(bot.tree.get_command("admin_dashboard"))
                commandNames = {command.name for command in bot.tree.get_commands()}
                self.assertTrue({"add", "deduct", "admin_helper-replace"}.issubset(commandNames))
                replacementGroup = bot.tree.get_command("admin_helper-replace")
                self.assertIsNotNone(replacementGroup)
                self.assertEqual({command.name for command in replacementGroup.commands}, {"approve", "disapprove"})
                self.assertIsNone(bot.tree.get_command("admin_replace_helper"))
            finally:
                # No database has been opened because no event callbacks were invoked.
                pass


if __name__ == "__main__":
    unittest.main()
