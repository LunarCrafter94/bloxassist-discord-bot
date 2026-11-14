"""Regression tests for invite attribution and join-time penalty eligibility."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxassist_discord_bot.database.guild_database import GuildDatabase
from bloxassist_discord_bot.invites.invite_events import (
    IsInviteEventInProgress,
    IsInviteLeavePenaltyEligible,
)
from bloxassist_discord_bot.settings import DEFAULT_SERVICES


class InviteEventEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

    def test_event_with_future_end_is_in_progress(self):
        self.assertTrue(
            IsInviteEventInProgress(
                {"ends_at": "2026-11-14T13:00:00+00:00"},
                now=self.now,
            )
        )

    def test_event_at_exact_end_time_is_not_in_progress(self):
        self.assertFalse(
            IsInviteEventInProgress(
                {"ends_at": "2026-11-14T12:00:00+00:00"},
                now=self.now,
            )
        )

    def test_event_with_different_timezone_offset_is_compared_as_an_instant(self):
        # 13:30 at UTC+02:00 is 11:30 UTC, so this event has already ended.
        self.assertFalse(
            IsInviteEventInProgress(
                {"ends_at": "2026-11-14T13:30:00+02:00"},
                now=self.now,
            )
        )

    def test_naive_event_timestamp_is_interpreted_as_utc(self):
        self.assertTrue(
            IsInviteEventInProgress(
                {"ends_at": "2026-11-14T12:30:00"},
                now=self.now,
            )
        )

    def test_manual_only_event_marker_remains_in_progress(self):
        self.assertTrue(
            IsInviteEventInProgress(
                {"ends_at": "9999-12-31T23:59:59+00:00"},
                now=self.now,
            )
        )

    def test_missing_or_invalid_event_end_is_not_eligible(self):
        self.assertFalse(IsInviteEventInProgress(None, now=self.now))
        self.assertFalse(IsInviteEventInProgress({}, now=self.now))
        self.assertFalse(
            IsInviteEventInProgress({"ends_at": "not-a-timestamp"}, now=self.now)
        )

    def test_all_invites_scope_accepts_attributed_members_outside_events(self):
        attribution = {"invite_event_id": None}
        self.assertTrue(IsInviteLeavePenaltyEligible(attribution, "all_invites"))
        self.assertTrue(IsInviteLeavePenaltyEligible(attribution, "unknown-value"))

    def test_active_event_only_scope_requires_saved_event_provenance(self):
        self.assertTrue(
            IsInviteLeavePenaltyEligible(
                {"invite_event_id": 42}, "active_event_only"
            )
        )
        self.assertFalse(
            IsInviteLeavePenaltyEligible(
                {"invite_event_id": None}, "active_event_only"
            )
        )
        self.assertFalse(
            IsInviteLeavePenaltyEligible({}, "active_event_only")
        )
        self.assertFalse(IsInviteLeavePenaltyEligible(None, "all_invites"))


class InviteAttributionDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempDirectory = tempfile.TemporaryDirectory()
        self.databasePath = Path(self.tempDirectory.name) / "server.sqlite3"
        self.database = GuildDatabase(
            self.databasePath,
            123456789012345678,
            100,
            DEFAULT_SERVICES,
        )

    def tearDown(self):
        self.database.Close()
        self.tempDirectory.cleanup()

    def getAttribution(self, invitedUserId: int):
        return self.database.Execute(
            "SELECT * FROM invite_attributions WHERE invited_user_id = ?",
            (invitedUserId,),
            fetchOne=True,
        )

    def test_new_attribution_persists_event_provenance(self):
        joinedAt = "2026-11-14T10:00:00+00:00"
        self.assertTrue(
            self.database.RecordInviteAttribution(
                1001, 2001, "invite-event", joinedAt=joinedAt, inviteEventId=42
            )
        )
        row = self.getAttribution(1001)
        self.assertEqual(int(row["inviter_user_id"]), 2001)
        self.assertEqual(row["joined_at"], joinedAt)
        self.assertEqual(int(row["invite_event_id"]), 42)
        self.assertEqual(int(row["join_cycle"]), 1)

    def test_attribution_outside_an_event_stores_no_event_id(self):
        self.database.RecordInviteAttribution(
            1002,
            2002,
            "ordinary-invite",
            joinedAt="2026-11-14T10:00:00+00:00",
        )
        row = self.getAttribution(1002)
        self.assertIsNone(row["invite_event_id"])
        self.assertFalse(
            IsInviteLeavePenaltyEligible(row, "active_event_only")
        )
        self.assertTrue(IsInviteLeavePenaltyEligible(row, "all_invites"))

    def test_duplicate_join_delivery_does_not_change_attribution_or_rearm_penalty(self):
        joinedAt = "2026-11-14T10:00:00+00:00"
        self.assertTrue(
            self.database.RecordInviteAttribution(
                1003, 2003, "first-code", joinedAt=joinedAt, inviteEventId=43
            )
        )
        self.assertTrue(
            self.database.MarkInviteLeavePenaltyApplied(1003, joinCycle=1)
        )
        self.assertFalse(
            self.database.RecordInviteAttribution(
                1003, 2999, "different-code", joinedAt=joinedAt, inviteEventId=99
            )
        )
        row = self.getAttribution(1003)
        self.assertEqual(int(row["inviter_user_id"]), 2003)
        self.assertEqual(row["invite_code"], "first-code")
        self.assertEqual(int(row["invite_event_id"]), 43)
        self.assertEqual(int(row["penalty_applied"]), 1)
        self.assertEqual(int(row["join_cycle"]), 1)

    def test_repeat_on_rejoin_rearms_once_and_updates_event_provenance(self):
        firstJoin = "2026-11-10T10:00:00+00:00"
        secondJoin = "2026-11-14T10:00:00+00:00"
        self.database.RecordInviteAttribution(
            1004, 2004, "first-code", joinedAt=firstJoin, inviteEventId=44
        )
        self.database.MarkInviteLeavePenaltyApplied(1004, joinCycle=1)

        self.assertTrue(
            self.database.RecordInviteAttribution(
                1004,
                2005,
                "second-code",
                repeatOnRejoin=True,
                joinedAt=secondJoin,
                inviteEventId=45,
            )
        )
        row = self.getAttribution(1004)
        self.assertEqual(int(row["inviter_user_id"]), 2005)
        self.assertEqual(row["invite_code"], "second-code")
        self.assertEqual(row["joined_at"], secondJoin)
        self.assertEqual(int(row["invite_event_id"]), 45)
        self.assertEqual(int(row["join_cycle"]), 2)
        self.assertEqual(int(row["penalty_applied"]), 0)

        # A duplicate delivery for the same join cycle must not replace provenance.
        self.assertFalse(
            self.database.RecordInviteAttribution(
                1004,
                2999,
                "duplicate-code",
                repeatOnRejoin=True,
                joinedAt=secondJoin,
                inviteEventId=46,
            )
        )
        row = self.getAttribution(1004)
        self.assertEqual(int(row["inviter_user_id"]), 2005)
        self.assertEqual(int(row["invite_event_id"]), 45)
        self.assertEqual(int(row["join_cycle"]), 2)

    def test_once_per_member_rejoin_keeps_original_inviter_and_provenance(self):
        firstJoin = "2026-11-10T10:00:00+00:00"
        secondJoin = "2026-11-14T10:00:00+00:00"
        self.database.RecordInviteAttribution(
            1005, 2006, "first-code", joinedAt=firstJoin
        )
        self.database.RecordInviteAttribution(
            1005,
            2007,
            "event-code",
            repeatOnRejoin=False,
            joinedAt=secondJoin,
            inviteEventId=47,
        )
        row = self.getAttribution(1005)
        self.assertEqual(int(row["inviter_user_id"]), 2006)
        self.assertEqual(row["invite_code"], "first-code")
        self.assertEqual(row["joined_at"], secondJoin)
        self.assertIsNone(row["invite_event_id"])
        self.assertEqual(int(row["join_cycle"]), 1)

    def test_old_leave_event_cannot_match_a_newer_join_cycle(self):
        firstJoin = "2026-11-10T10:00:00+00:00"
        secondJoin = "2026-11-14T10:00:00+00:00"
        self.database.RecordInviteAttribution(
            1006, 2008, "first-code", joinedAt=firstJoin
        )
        self.database.RecordInviteAttribution(
            1006,
            2009,
            "second-code",
            repeatOnRejoin=True,
            joinedAt=secondJoin,
        )
        self.assertIsNone(
            self.database.GetInviteAttribution(1006, joinedAt=firstJoin)
        )
        self.assertIsNotNone(
            self.database.GetInviteAttribution(1006, joinedAt=secondJoin)
        )

    def test_legacy_attribution_schema_migrates_with_null_event_provenance(self):
        self.database.Close()
        with closing(sqlite3.connect(self.databasePath)) as connection:
            with connection:
                connection.execute("DROP TABLE invite_attributions")
                connection.execute(
                    """CREATE TABLE invite_attributions (
                        invited_user_id INTEGER PRIMARY KEY,
                        inviter_user_id INTEGER NOT NULL,
                        invite_code TEXT NOT NULL DEFAULT '',
                        penalty_applied INTEGER NOT NULL DEFAULT 0
                            CHECK (penalty_applied IN (0, 1)),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                connection.execute(
                    """INSERT INTO invite_attributions
                       (invited_user_id, inviter_user_id, invite_code)
                       VALUES (?, ?, ?)""",
                    (1010, 2010, "legacy-code"),
                )

        migrated = GuildDatabase(
            self.databasePath,
            123456789012345678,
            100,
            DEFAULT_SERVICES,
        )
        try:
            columns = {
                str(row["name"])
                for row in migrated.connection.execute(
                    "PRAGMA table_info(invite_attributions)"
                ).fetchall()
            }
            self.assertTrue({"join_cycle", "joined_at", "invite_event_id"} <= columns)
            row = migrated.Execute(
                "SELECT * FROM invite_attributions WHERE invited_user_id = ?",
                (1010,),
                fetchOne=True,
            )
            self.assertEqual(int(row["inviter_user_id"]), 2010)
            self.assertEqual(row["invite_code"], "legacy-code")
            self.assertEqual(int(row["join_cycle"]), 1)
            self.assertEqual(row["joined_at"], "")
            self.assertIsNone(row["invite_event_id"])
        finally:
            migrated.Close()


if __name__ == "__main__":
    unittest.main()
