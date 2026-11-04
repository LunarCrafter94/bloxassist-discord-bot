"""Regression tests for member-credit debt visibility boundaries."""

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from bloxfruits_helper_credit_bot import bot_client
except ModuleNotFoundError as error:
    if error.name != "discord":
        raise
    bot_client = None


class _DatabaseManager:
    def ForServer(self, _guild_id):
        return object()


@unittest.skipIf(bot_client is None, "discord.py is not installed in this validation environment")
class CreditPrivacyTests(unittest.TestCase):
    def makeInteraction(
        self,
        *,
        userId=100,
        ownerId=999,
        administrator=False,
        roleIds=(),
        inGuild=True,
    ):
        user = SimpleNamespace(
            id=userId,
            guild_permissions=SimpleNamespace(administrator=administrator),
            roles=[SimpleNamespace(id=roleId) for roleId in roleIds],
        )
        guild = SimpleNamespace(owner_id=ownerId) if inGuild else None
        return SimpleNamespace(
            user=user,
            guild=guild,
            guild_id=123 if inGuild else None,
        )

    def test_member_can_view_their_own_debt_without_staff_access(self):
        interaction = self.makeInteraction(userId=100, ownerId=999)

        with patch.object(bot_client, "HasConfiguredStaffAccess") as staffCheck:
            self.assertTrue(
                bot_client.CanViewMemberCreditDebt(interaction, 100, _DatabaseManager())
            )

        staffCheck.assert_not_called()

    def test_server_owner_can_view_another_members_debt(self):
        interaction = self.makeInteraction(userId=999, ownerId=999)
        self.assertTrue(
            bot_client.CanViewMemberCreditDebt(interaction, 100, _DatabaseManager())
        )

    def test_administrator_can_view_another_members_debt(self):
        interaction = self.makeInteraction(userId=200, administrator=True)
        self.assertTrue(
            bot_client.CanViewMemberCreditDebt(interaction, 100, _DatabaseManager())
        )

    def test_configured_dashboard_moderator_can_view_another_members_debt(self):
        interaction = self.makeInteraction(userId=200, roleIds=(500,))

        with patch.object(bot_client, "GetDashboardModeratorRoleIds", return_value={500}):
            self.assertTrue(
                bot_client.CanViewMemberCreditDebt(interaction, 100, _DatabaseManager())
            )

    def test_ordinary_member_cannot_view_another_members_debt(self):
        interaction = self.makeInteraction(userId=200, roleIds=(600,))

        with patch.object(bot_client, "GetDashboardModeratorRoleIds", return_value={500}):
            self.assertFalse(
                bot_client.CanViewMemberCreditDebt(interaction, 100, _DatabaseManager())
            )

    def test_manage_server_permission_alone_does_not_grant_debt_visibility(self):
        interaction = self.makeInteraction(userId=200)
        interaction.user.guild_permissions.manage_guild = True

        with patch.object(bot_client, "GetDashboardModeratorRoleIds", return_value=set()):
            self.assertFalse(
                bot_client.CanViewMemberCreditDebt(interaction, 100, _DatabaseManager())
            )

    def test_direct_message_context_never_grants_member_debt_visibility(self):
        interaction = self.makeInteraction(userId=100, inGuild=False)
        self.assertFalse(
            bot_client.CanViewMemberCreditDebt(interaction, 100, _DatabaseManager())
        )

    def test_credits_command_only_queries_and_displays_debt_after_authorization(self):
        sourceRoot = Path(__file__).resolve().parents[1] / "source-files" / "bloxfruits_helper_credit_bot"
        botText = (sourceRoot / "bot_client.py").read_text(encoding="utf-8")
        creditsBody = botText.split("async def Credits(", 1)[1].split(
            '@bot.tree.command(name="repay-debt"', 1
        )[0]

        self.assertIn(
            "CanViewMemberCreditDebt(interaction, targetUserId, databaseManager)",
            creditsBody,
        )
        self.assertIn(
            'embed.add_field(name="Available credits", value=f"**{amount:,}**", inline=True)',
            creditsBody,
        )
        self.assertIn(
            'if CanViewMemberCreditDebt(interaction, targetUserId, databaseManager):\n'
            '            debt = db.GetCreditDebt(member.id)\n'
            '            embed.add_field(name="Outstanding debt"',
            creditsBody,
        )
        self.assertIn(
            "await SendEphemeralResponse(interaction, embed=embed, ephemeral=True)",
            creditsBody,
        )


if __name__ == "__main__":
    unittest.main()
