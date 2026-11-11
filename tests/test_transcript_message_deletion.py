"""Regression test for Discord transcript-message deletion calls."""

from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import unittest

from bloxassist_discord_bot.tickets.ticket_views import _DeleteTranscriptMessage


class StrictPartialMessage:
    """Match discord.py PartialMessage.delete(), which accepts no reason keyword."""

    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class TranscriptMessageDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcript_message_deletion_uses_no_reason_keyword(self):
        message = StrictPartialMessage()
        await _DeleteTranscriptMessage(message)
        self.assertTrue(message.deleted)


if __name__ == "__main__":
    unittest.main()
