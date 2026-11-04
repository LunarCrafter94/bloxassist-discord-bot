"""Tests for the shared ephemeral paginator used by history and report commands."""

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, Mock

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    import discord
    from bloxfruits_helper_credit_bot.pagination import EphemeralPaginator
except ModuleNotFoundError as error:
    if error.name != "discord":
        raise
    discord = None
    EphemeralPaginator = None


def make_embed(page: int):
    embed = discord.Embed(title=f"Page {page}")
    embed.description = f"Results for page {page}"
    return embed


def make_interaction(*, user_id=100, guild_id=987654):
    response = SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock())
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        guild_id=guild_id,
        response=response,
    )


@unittest.skipIf(EphemeralPaginator is None, "discord.py is not installed in this validation environment")
class EphemeralPaginatorTests(unittest.IsolatedAsyncioTestCase):
    def make_view(self, *, page=1, last_page=3, requester=100, access_check=None):
        calls = []

        def loader(requested_page):
            calls.append(requested_page)
            return make_embed(requested_page), requested_page < last_page

        view = EphemeralPaginator(
            loader,
            page=page,
            requesterUserId=requester,
            guildId=987654,
            originInteraction=SimpleNamespace(id=123),
            accessCheck=access_check,
        )
        return view, calls

    async def test_next_and_previous_update_embed_and_page_indicator(self):
        view, calls = self.make_view()
        interaction = make_interaction()

        self.assertEqual(view.page, 1)
        self.assertTrue(view.previous_button.disabled)
        self.assertFalse(view.next_button.disabled)

        await view._Navigate(interaction, 1)
        self.assertEqual(view.page, 2)
        self.assertEqual(view.page_button.label, "Page 2")
        self.assertEqual(view.embed.title, "Page 2")
        self.assertFalse(view.previous_button.disabled)
        self.assertFalse(view.next_button.disabled)

        await view._Navigate(interaction, -1)
        self.assertEqual(view.page, 1)
        self.assertEqual(view.page_button.label, "Page 1")
        self.assertEqual(view.embed.title, "Page 1")
        self.assertTrue(view.previous_button.disabled)
        self.assertEqual(calls, [1, 2, 1])

    async def test_last_page_removes_controls(self):
        view, _ = self.make_view(page=2, last_page=3)
        interaction = make_interaction()

        await view._Navigate(interaction, 1)

        self.assertEqual(view.page, 3)
        self.assertEqual(view.embed.title, "Page 3")
        interaction.response.edit_message.assert_awaited_once()
        self.assertIsNone(interaction.response.edit_message.await_args.kwargs["view"])
        self.assertTrue(view.is_finished())

    async def test_cannot_advance_past_last_page(self):
        view, calls = self.make_view(page=3, last_page=3)
        interaction = make_interaction()

        await view._Navigate(interaction, 1)

        self.assertEqual(view.page, 3)
        self.assertEqual(calls, [3])
        interaction.response.edit_message.assert_not_awaited()

    async def test_other_user_cannot_navigate(self):
        view, _ = self.make_view(requester=100)
        interaction = make_interaction(user_id=200)

        allowed = await view.interaction_check(interaction)

        self.assertFalse(allowed)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])

    async def test_access_check_is_re_evaluated(self):
        access_check = Mock(return_value=False)
        view, _ = self.make_view(access_check=access_check)
        interaction = make_interaction()

        allowed = await view.interaction_check(interaction)

        self.assertFalse(allowed)
        access_check.assert_called_once_with(interaction)
        self.assertTrue(view.is_finished())
        interaction.response.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
