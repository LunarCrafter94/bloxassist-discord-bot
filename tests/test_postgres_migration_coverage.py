"""Regression tests for SQLite-to-PostgreSQL migration coverage."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_SCRIPT = ROOT / "tools" / "Migrate-SQLite-To-Postgres.py"

EXPECTED_TABLES = {
    "users",
    "services",
    "settings",
    "invite_events",
    "tickets",
    "transactions",
    "transaction_audit_deliveries",
    "invite_rewards",
    "credit_debts",
    "invite_attributions",
    "scam_reports",
}

EXPECTED_CORE_TABLES = EXPECTED_TABLES - {"services", "settings"}


def read_module_constant(name: str):
    tree = ast.parse(MIGRATION_SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Could not find constant {name!r} in migration script")


class PostgresMigrationCoverageTests(unittest.TestCase):
    def test_migration_includes_every_current_application_table(self):
        tables = read_module_constant("TABLES")
        self.assertEqual(set(tables), EXPECTED_TABLES)
        self.assertEqual(len(tables), len(EXPECTED_TABLES))

    def test_fresh_target_check_covers_every_user_data_table(self):
        core_tables = read_module_constant("CORE_TABLES")
        self.assertEqual(set(core_tables), EXPECTED_CORE_TABLES)


    def test_fresh_target_check_includes_ticket_welcome_default(self):
        source = MIGRATION_SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            '"ticket_welcome_message": DEFAULT_TICKET_WELCOME_MESSAGE',
            source,
        )
        self.assertIn(
            "from bloxfruits_helper_credit_bot.ticket_messages import DEFAULT_TICKET_WELCOME_MESSAGE",
            source,
        )

    def test_insert_and_delete_orders_respect_foreign_keys(self):
        tables = read_module_constant("TABLES")
        delete_order = read_module_constant("DELETE_ORDER")

        self.assertLess(tables.index("invite_events"), tables.index("invite_rewards"))
        self.assertLess(tables.index("tickets"), tables.index("transactions"))
        self.assertLess(
            delete_order.index("transaction_audit_deliveries"),
            delete_order.index("transactions"),
        )
        self.assertLess(delete_order.index("invite_rewards"), delete_order.index("invite_events"))
        self.assertLess(delete_order.index("transactions"), delete_order.index("tickets"))


if __name__ == "__main__":
    unittest.main()
