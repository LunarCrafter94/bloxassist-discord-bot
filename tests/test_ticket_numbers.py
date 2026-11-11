import sys
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bloxassist_discord_bot.ticket_numbers import (
    FormatLegacyTicketLabel,
    FormatPermanentTicketNumber,
    FormatTicketLabel,
    TicketChannelLabelFromRow,
    TicketLabelFromRow,
)
from bloxassist_discord_bot.ticket_messages import (
    DEFAULT_TICKET_WELCOME_MESSAGE,
    RenderTicketWelcomeMessage,
)


class TicketNumberFormattingTests(unittest.TestCase):
    def test_permanent_transcript_labels_never_need_series_hyphens(self):
        expected = {
            1: "001",
            99: "099",
            100: "100",
            101: "101",
            999: "999",
            1000: "1│000",
            1001: "1│001",
            1999: "1│999",
            2000: "2│000",
            9999: "9│999",
            10000: "10│000",
        }
        for number, label in expected.items():
            with self.subTest(number=number):
                self.assertEqual(FormatPermanentTicketNumber(number), label)
                self.assertEqual(FormatTicketLabel(number, number), label)

    def test_legacy_wrapping_ticket_labels_remain_readable(self):
        self.assertEqual(FormatLegacyTicketLabel(101, 101), "2-101")
        self.assertEqual(TicketLabelFromRow({"ticket_number": 1, "ticket_sequence": None}), "001")
        self.assertEqual(TicketLabelFromRow({"ticket_number": 27}), "027")

    def test_new_ticket_row_uses_permanent_sequence_and_separate_channel_number(self):
        row = {"ticket_number": 1001, "ticket_sequence": 1001, "channel_ticket_number": 7}
        self.assertEqual(TicketLabelFromRow(row), "1│001")
        self.assertEqual(TicketChannelLabelFromRow(row), "007")

    def test_legacy_channel_label_is_not_silently_renamed(self):
        row = {"ticket_number": 101, "ticket_sequence": 101, "channel_ticket_number": None}
        self.assertEqual(TicketChannelLabelFromRow(row), "2-101")
        self.assertEqual(TicketLabelFromRow(row), "2-101")

    def test_scam_modal_label_fits_discord_limit(self):
        label = "What happened? Include ticket # if known."
        self.assertLessEqual(len(label), 45)


class TicketWelcomeMessageTests(unittest.TestCase):
    def test_default_message_is_plain_text(self):
        self.assertTrue(DEFAULT_TICKET_WELCOME_MESSAGE)
        self.assertNotIn("**", DEFAULT_TICKET_WELCOME_MESSAGE)

    def test_supported_placeholders_are_substituted_as_literals(self):
        rendered = RenderTicketWelcomeMessage(
            "Hello {requester}; helpers: {helpers}; ticket {ticket}; event {event}",
            requester="<@1>", helpers="<@2> <@3>", ticket="001", event="V4 Trials",
        )
        self.assertEqual(rendered, "Hello <@1>; helpers: <@2> <@3>; ticket 001; event V4 Trials")

    def test_unrecognized_braces_are_preserved_and_whitespace_trimmed(self):
        rendered = RenderTicketWelcomeMessage(
            "  Keep {unknown} and {ticket}  ", requester="R", helpers="H", ticket="002", event="E"
        )
        self.assertEqual(rendered, "Keep {unknown} and 002")


if __name__ == "__main__":
    unittest.main()
