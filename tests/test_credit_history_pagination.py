"""Tests for interactive credit-history pagination."""

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, Mock

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from bloxfruits_helper_credit_bot.credits.credit_history_view import (
        CREDIT_HISTORY_PAGE_SIZE,
        BuildCreditHistoryEmbed,
        CreditHistoryView,
    )
except ModuleNotFoundError as error:
    if error.name != "discord":
        raise
    CREDIT_HISTORY_PAGE_SIZE = 10
    BuildCreditHistoryEmbed = None
    CreditHistoryView = None


def make_rows(count: int, target_user_id: int = 123456) -> list[dict]:
    rows = []
    for index in range(count):
        rows.append({
            "id": count - index,
            "ticket_id": None,
            "from_user": None,
            "to_user": target_user_id,
            "amount": 100,
            "type": "admin_add",
            "created_at": "2026-11-04 12:00:00+08",
            "note": f"Test transaction {count - index}",
        })
    return rows


class FakeDatabase:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.calls: list[tuple[int, int, int]] = []

    def ListCreditTransactions(self, user_id: int, *, limit: int, offset: int):
        self.calls.append((int(user_id), int(limit), int(offset)))
        return self.rows[offset:offset + limit]


def make_view(database, *, page=1, target_user_id=123456, requester_user_id=123456, staff_check=None):
    interaction = SimpleNamespace(id=999)
    return CreditHistoryView(
        database,
        targetUserId=target_user_id,
        targetLabel="Test Member",
        requesterUserId=requester_user_id,
        guildId=987654,
        page=page,
        originInteraction=interaction,
        staffAccessCheck=staff_check or (lambda _interaction: True),
    )


@unittest.skipIf(CreditHistoryView is None, "discord.py is not installed in this validation environment")
class CreditHistoryPaginationTests(unittest.TestCase):
    def test_first_page_fetches_one_extra_row_and_enables_next(self):
        database = FakeDatabase(make_rows(25))
        view = make_view(database)

        self.assertEqual(database.calls, [(123456, CREDIT_HISTORY_PAGE_SIZE + 1, 0)])
        self.assertEqual(len(view.embed.fields), 10)
        self.assertIn("Showing page 1", view.embed.description)
        self.assertTrue(view.has_navigation)
        self.assertTrue(view.previous_button.disabled)
        self.assertFalse(view.next_button.disabled)
        self.assertEqual(view.page_button.label, "Page 1")

    def test_middle_page_keeps_both_navigation_directions(self):
        database = FakeDatabase(make_rows(25))
        view = make_view(database, page=2)

        self.assertEqual(database.calls, [(123456, 11, 10)])
        self.assertEqual(len(view.embed.fields), 10)
        self.assertFalse(view.previous_button.disabled)
        self.assertFalse(view.next_button.disabled)
        self.assertEqual(view.page_button.label, "Page 2")

    def test_last_page_disables_next_but_keeps_previous(self):
        database = FakeDatabase(make_rows(21))
        view = make_view(database, page=3)

        self.assertEqual(database.calls, [(123456, 11, 20)])
        self.assertEqual(len(view.embed.fields), 1)
        self.assertFalse(view.previous_button.disabled)
        self.assertTrue(view.next_button.disabled)
        self.assertIn("Showing page 3", view.embed.description)

    def test_single_page_history_does_not_show_navigation(self):
        database = FakeDatabase(make_rows(10))
        view = make_view(database)

        self.assertEqual(len(view.embed.fields), 10)
        self.assertFalse(view.has_navigation)
        self.assertTrue(view.previous_button.disabled)
        self.assertTrue(view.next_button.disabled)

    def test_empty_manual_page_can_navigate_back(self):
        database = FakeDatabase(make_rows(10))
        view = make_view(database, page=2)

        self.assertEqual(len(view.embed.fields), 0)
        self.assertIn("No credit transactions were found", view.embed.description)
        self.assertTrue(view.has_navigation)
        self.assertFalse(view.previous_button.disabled)
        self.assertTrue(view.next_button.disabled)

    def test_embed_preserves_penalty_and_debt_repayment_labels(self):
        rows = make_rows(2)
        rows[0]["type"] = "penalty_debt"
        rows[0]["from_user"] = 123456
        rows[0]["to_user"] = 123456
        rows[1]["type"] = "debt_repayment"
        rows[1]["from_user"] = 123456
        rows[1]["to_user"] = None

        embed = BuildCreditHistoryEmbed(
            rows,
            targetUserId=123456,
            targetLabel="Test Member",
            page=1,
        )

        self.assertIn("Penalty Debt", embed.fields[0].name)
        self.assertIn("(penalty)", embed.fields[0].name)
        self.assertIn("Debt Repayment", embed.fields[1].name)
        self.assertIn("(debt repayment)", embed.fields[1].name)


class _FakeResponse:
    def __init__(self):
        self.send_message = AsyncMock()


@unittest.skipIf(CreditHistoryView is None, "discord.py is not installed in this validation environment")
class CreditHistoryPaginationPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_original_invoker_can_navigate(self):
        database = FakeDatabase(make_rows(25))
        view = make_view(database, requester_user_id=100)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=200),
            guild_id=987654,
            response=_FakeResponse(),
        )

        allowed = await view.interaction_check(interaction)

        self.assertFalse(allowed)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])

    async def test_revoked_staff_access_blocks_another_members_history(self):
        database = FakeDatabase(make_rows(25))
        view = make_view(
            database,
            target_user_id=300,
            requester_user_id=100,
            staff_check=lambda _interaction: False,
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=100),
            guild_id=987654,
            response=_FakeResponse(),
        )

        allowed = await view.interaction_check(interaction)

        self.assertFalse(allowed)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(view.is_finished())


    async def test_navigation_changes_page_without_changing_target_user(self):
        database = FakeDatabase(make_rows(25, target_user_id=300))
        view = make_view(
            database,
            target_user_id=300,
            requester_user_id=100,
        )
        response = SimpleNamespace(edit_message=AsyncMock())
        interaction = SimpleNamespace(response=response)

        await view._Navigate(interaction, 1)

        self.assertEqual(database.calls, [(300, 11, 0), (300, 11, 10)])
        self.assertIn("Member ID: 300", view.embed.description)
        self.assertIn("Showing page 2", view.embed.description)
        response.edit_message.assert_awaited_once()
        self.assertIs(response.edit_message.await_args.kwargs["view"], view)

    async def test_staff_access_is_rechecked_and_allows_navigation(self):
        database = FakeDatabase(make_rows(25))
        staff_check = Mock(return_value=True)
        view = make_view(
            database,
            target_user_id=300,
            requester_user_id=100,
            staff_check=staff_check,
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=100),
            guild_id=987654,
            response=_FakeResponse(),
        )

        allowed = await view.interaction_check(interaction)

        self.assertTrue(allowed)
        staff_check.assert_called_once_with(interaction)


if __name__ == "__main__":
    unittest.main()
