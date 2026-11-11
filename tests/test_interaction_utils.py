"""Tests for stale ephemeral interaction response handling."""

from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

from bloxassist_discord_bot.interaction_utils import (
    EditEphemeralOriginalResponse,
    SendEphemeralResponse,
)


class InteractionResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_view_is_omitted_from_send_message(self):
        interaction = Mock()
        interaction.id = 123456788
        interaction.response.send_message = AsyncMock()

        with patch(
            "bloxassist_discord_bot.interaction_utils.ScheduleEphemeralOriginalDeletion"
        ):
            await SendEphemeralResponse(interaction, "No pagination needed.", view=None)

        interaction.response.send_message.assert_awaited_once()
        self.assertNotIn("view", interaction.response.send_message.await_args.kwargs)
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])

    async def test_missing_auto_deleted_ephemeral_response_is_non_fatal(self):
        response = Mock()
        response.status = 404
        missing_message = discord.NotFound(
            response,
            {"message": "Unknown Message", "code": 10008},
        )
        interaction = Mock()
        interaction.id = 123456789
        interaction.edit_original_response = AsyncMock(side_effect=missing_message)

        with patch(
            "bloxassist_discord_bot.interaction_utils.ScheduleEphemeralOriginalDeletion"
        ) as schedule:
            result = await EditEphemeralOriginalResponse(interaction, content="finished")

        self.assertIsNone(result)
        schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
