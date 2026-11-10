"""Tests for safe cleanup of transcript-retention fixture messages."""

from pathlib import Path
import sys
import unittest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

import importlib.util

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "Seed-TranscriptRetentionTest.py"
spec = importlib.util.spec_from_file_location("seed_transcript_retention_test", TOOL_PATH)
seed_tool = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(seed_tool)


class FakeNotFound(Exception):
    pass


class StrictPartialMessage:
    """Like discord.py PartialMessage: delete() accepts no keyword arguments."""

    def __init__(self, error=None):
        self.error = error
        self.deleted = False

    async def delete(self):
        if self.error is not None:
            raise self.error
        self.deleted = True


class TranscriptRetentionCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_deletes_partial_message_without_reason_keyword(self):
        message = StrictPartialMessage()
        deleted = await seed_tool._delete_fixture_message(message, FakeNotFound)
        self.assertTrue(deleted)
        self.assertTrue(message.deleted)

    async def test_cleanup_treats_already_pruned_message_as_already_missing(self):
        message = StrictPartialMessage(FakeNotFound("already deleted"))
        deleted = await seed_tool._delete_fixture_message(message, FakeNotFound)
        self.assertFalse(deleted)
        self.assertFalse(message.deleted)


if __name__ == "__main__":
    unittest.main()
