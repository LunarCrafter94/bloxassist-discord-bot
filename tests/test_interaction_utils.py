"""Tests for stale ephemeral interaction response handling."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

from bloxfruits_helper_credit_bot.interaction_utils import EditEphemeralOriginalResponse


class InteractionResponseTests(unittest.IsolatedAsyncioTestCase):
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
            "bloxfruits_helper_credit_bot.interaction_utils.ScheduleEphemeralOriginalDeletion"
        ) as schedule:
            result = await EditEphemeralOriginalResponse(interaction, content="finished")

        self.assertIsNone(result)
        schedule.assert_not_called()


if __name__ == "__main__":
    unittest.main()
