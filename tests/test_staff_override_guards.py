"""Source contract tests for command/button authorization boundaries.

Database membership behavior is exercised in test_phase4_5_features.py. These checks
protect the Discord-facing call paths from accidentally reintroducing role-based bypasses.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source-files" / "bloxfruits_helper_credit_bot"


class StaffOverrideGuardTests(unittest.TestCase):
    def test_manage_server_alone_is_not_an_implicit_staff_grant(self):
        bot_text = (SOURCE / "bot_client.py").read_text(encoding="utf-8")
        ticket_text = (SOURCE / "tickets" / "ticket_views.py").read_text(encoding="utf-8")
        staff_helper = bot_text.split("def HasConfiguredStaffAccess", 1)[1].split("def CreateBot", 1)[0]
        ticket_staff_helper = ticket_text.split("def IsConfiguredTicketStaff", 1)[1].split("class MainPanelView", 1)[0]
        self.assertNotIn("manage_guild", staff_helper)
        self.assertNotIn("manage_guild", ticket_staff_helper)
        self.assertIn("GetDashboardModeratorRoleIds", staff_helper)
        self.assertIn("GetDashboardModeratorRoleIds", ticket_staff_helper)

    def test_cancel_button_path_never_calls_staff_override(self):
        ticket_text = (SOURCE / "tickets" / "ticket_views.py").read_text(encoding="utf-8")
        cancel_body = ticket_text.split("async def CancelUserTicket", 1)[1].split("async def ConfirmTicketResolutionCurrent", 1)[0]
        self.assertIn("RequestTicketResolution", cancel_body)
        self.assertNotIn("isModerator", cancel_body)
        self.assertNotIn("moderator override cancellation/refund", cancel_body)
        self.assertIn("interaction.user.id != int(ticket[\"creator_id\"])", cancel_body)

    def test_ticket_override_paths_reject_ticket_participants(self):
        ticket_text = (SOURCE / "tickets" / "ticket_views.py").read_text(encoding="utf-8")
        complete_body = ticket_text.split("async def CompleteCurrentTicket", 1)[1].split("async def CancelUserTicket", 1)[0]
        refund_body = ticket_text.split("async def RefundCurrentTicket", 1)[1].split("def BuildHelpCenterEmbed", 1)[0]
        self.assertIn("IsUserTicketParticipant", complete_body)
        self.assertIn("IsUserTicketParticipant", refund_body)


    def test_add_and_deduct_are_server_owner_only(self):
        bot_text = (SOURCE / "bot_client.py").read_text(encoding="utf-8")
        add_body = bot_text.split("async def AddCredits", 1)[1].split("@bot.tree.command(name=\"deduct\"", 1)[0]
        deduct_body = bot_text.split("async def DeductCredits", 1)[1].split("replacementAdminGroup =", 1)[0]
        for body, commandName in ((add_body, "/add"), (deduct_body, "/deduct")):
            self.assertIn("IsServerOwner(interaction)", body, commandName)
            self.assertNotIn("HasConfiguredStaffAccess(interaction", body, commandName)
        self.assertIn("def IsServerOwner", bot_text)

    def test_ticket_buttons_always_use_normal_resolution_workflow(self):
        ticket_text = (SOURCE / "tickets" / "ticket_views.py").read_text(encoding="utf-8")
        ticket_view = ticket_text.split("class TicketView", 1)[1].split("class TicketResolutionView", 1)[0]
        resolution_view = ticket_text.split("class TicketResolutionView", 1)[1].split("class ReplacementRequestView", 1)[0]
        confirm_body = ticket_text.split("async def ConfirmTicketResolutionCurrent", 1)[1].split("async def RejectTicketResolutionCurrent", 1)[0]
        reject_body = ticket_text.split("async def RejectTicketResolutionCurrent", 1)[1].split("async def EditTicketWorkflowMessage", 1)[0]
        self.assertIn("CompleteCurrentTicket(interaction, self.databaseManager)", ticket_view)
        self.assertNotIn("admin=True", ticket_view)
        self.assertIn("ConfirmTicketResolutionCurrent(interaction, self.databaseManager)", resolution_view)
        self.assertIn("RejectTicketResolutionCurrent(interaction, self.databaseManager)", resolution_view)
        self.assertIn("db.ConfirmTicketResolution", confirm_body)
        self.assertIn("db.RejectTicketResolution", reject_body)
        self.assertNotIn("admin=True", confirm_body + reject_body)

    def test_credit_commands_are_marked_admin_visible_but_runtime_owner_gated(self):
        bot_text = (SOURCE / "bot_client.py").read_text(encoding="utf-8")
        for commandName in ("add", "deduct"):
            section = bot_text.split(f'@bot.tree.command(name="{commandName}"', 1)[1]
            section = section.split("@bot.tree.command", 1)[0]
            self.assertIn("@app_commands.default_permissions(administrator=True)", section)
            self.assertIn("IsServerOwner(interaction)", section)

    def test_moderator_replacement_and_credit_commands_check_ticket_participation(self):
        bot_text = (SOURCE / "bot_client.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(bot_text.count("IsUserParticipantInAnyOpenTicket"), 2)
        self.assertGreaterEqual(bot_text.count("IsUserTicketParticipant"), 2)


if __name__ == "__main__":
    unittest.main()
