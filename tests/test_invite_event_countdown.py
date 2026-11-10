"""Tests for viewer-local invite reward event countdown formatting."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from bloxfruits_helper_credit_bot.invites.invite_events import FormatInviteEventCountdown
except ModuleNotFoundError as error:
    if error.name != "discord":
        raise
    FormatInviteEventCountdown = None


@unittest.skipIf(FormatInviteEventCountdown is None, "discord.py is not installed in this validation environment")
class InviteEventCountdownTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def test_finite_event_uses_relative_discord_timestamp_not_utc_text(self):
        endsAt = self.now + timedelta(hours=2, minutes=15)
        result = FormatInviteEventCountdown({"ends_at": endsAt.isoformat()}, now=self.now)
        self.assertEqual(result, f"<t:{int(endsAt.timestamp())}:R>")
        self.assertNotIn("UTC", result)

    def test_finite_event_accepts_zulu_timestamp(self):
        endsAt = self.now + timedelta(minutes=30)
        result = FormatInviteEventCountdown({"ends_at": endsAt.isoformat().replace("+00:00", "Z")}, now=self.now)
        self.assertEqual(result, f"<t:{int(endsAt.timestamp())}:R>")

    def test_infinite_event_displays_forever(self):
        result = FormatInviteEventCountdown({"ends_at": "9999-12-31T23:59:59+00:00"}, now=self.now)
        self.assertIn("Forever", result)

    def test_expired_event_is_marked_as_ending_now(self):
        endsAt = self.now - timedelta(minutes=1)
        result = FormatInviteEventCountdown({"ends_at": endsAt.isoformat()}, now=self.now)
        self.assertIn("ending now", result)

    def test_invalid_or_missing_end_time_is_safe(self):
        self.assertEqual(FormatInviteEventCountdown({"ends_at": "not-a-date"}, now=self.now), "Unavailable")
        self.assertEqual(FormatInviteEventCountdown({}, now=self.now), "Unavailable")


if __name__ == "__main__":
    unittest.main()
