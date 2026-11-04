"""Regression checks that history/list commands share interactive pagination."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOT_CLIENT = ROOT / "source-files" / "bloxfruits_helper_credit_bot" / "bot_client.py"
CREDIT_HISTORY_VIEW = ROOT / "source-files" / "bloxfruits_helper_credit_bot" / "credits" / "credit_history_view.py"


class HistoryCommandPaginationWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.botText = BOT_CLIENT.read_text(encoding="utf-8")

    def _command_body(self, command_name: str, next_command_name: str) -> str:
        start = self.botText.index(f'@bot.tree.command(name="{command_name}"')
        end = self.botText.index(f'@bot.tree.command(name="{next_command_name}"', start)
        return self.botText[start:end]

    def test_all_page_and_history_commands_use_shared_paginator(self):
        credit_history = self._command_body("credit-history", "diagnostics")
        ticket_history = self._command_body("ticket-history", "reports")
        reports = self._command_body("reports", "report-review")

        self.assertIn("CreditHistoryView(", credit_history)
        self.assertIn("class CreditHistoryView(EphemeralPaginator)", CREDIT_HISTORY_VIEW.read_text(encoding="utf-8"))
        for body in (ticket_history, reports):
            with self.subTest(command=body[:100]):
                self.assertIn("EphemeralPaginator(", body)
                self.assertIn("page=int(page)", body)
                self.assertIn("accessCheck=", body)

    def test_ticket_history_passes_offset_for_disjoint_pages(self):
        ticket_history = self._command_body("ticket-history", "reports")
        self.assertIn("pageSize + 1", ticket_history)
        self.assertIn("offset=(pageNumber - 1) * pageSize", ticket_history)
        self.assertIn("len(rows) > pageSize", ticket_history)

    def test_reports_preserve_category_filter_while_navigating(self):
        reports = self._command_body("reports", "report-review")
        self.assertIn("categoryValue = category.value if category else None", reports)
        self.assertIn("reportType=categoryValue", reports)
        self.assertIn("offset=(pageNumber - 1) * 5", reports)
        self.assertIn("len(rows) > 5", reports)

    def test_existing_direct_page_options_are_preserved(self):
        ticket_history = self._command_body("ticket-history", "reports")
        reports = self._command_body("reports", "report-review")
        credit_history = self._command_body("credit-history", "diagnostics")

        for body in (ticket_history, reports, credit_history):
            self.assertIn("page: app_commands.Range[int, 1, 1000] = 1", body)


if __name__ == "__main__":
    unittest.main()
