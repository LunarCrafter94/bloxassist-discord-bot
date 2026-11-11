"""Ticket-channel and permanent transcript identifiers.

Channel numbers may be reused after a guild has no open tickets. Transcript
sequences never reset, so historical transcript names remain distinguishable.
At 1,000 and above, the vertical box-drawing divider keeps labels compact.
"""

from __future__ import annotations
from typing import Any

TRANSCRIPT_DIVIDER = "│"


def FormatPermanentTicketNumber(number: int) -> str:
    """Format a globally unique ticket/transcript sequence for humans.

    1..999 are displayed with three digits; 1000 becomes ``1│000``, 1001
    becomes ``1│001``, 2000 becomes ``2│000``, and so on.
    """
    value = int(number)
    if value < 1:
        return "000"
    if value < 1000:
        return f"{value:03d}"
    thousands, remainder = divmod(value, 1000)
    return f"{thousands}{TRANSCRIPT_DIVIDER}{remainder:03d}"


def FormatLegacyTicketLabel(ticketNumber: int | None, ticketSequence: int | None = None) -> str:
    """Preserve the pre-v0.8.0 ``1-001`` / ``2-101`` labels for old rows."""
    if ticketSequence is not None:
        sequence = int(ticketSequence)
        if sequence > 0:
            series = ((sequence - 1) // 100) + 1
            return f"{series}-{sequence:03d}"
    return FormatPermanentTicketNumber(int(ticketNumber or 0))


def FormatTicketLabel(ticketNumber: int | None, ticketSequence: int | None = None) -> str:
    """Format the permanent transcript label for a database ticket row."""
    if ticketSequence is not None:
        return FormatPermanentTicketNumber(int(ticketSequence))
    return FormatPermanentTicketNumber(int(ticketNumber or 0))


def TicketLabelFromRow(ticket: Any) -> str:
    """Return the transcript/history label without renaming old published labels.

    Rows with ``channel_ticket_number`` assigned were created after v0.8.0 and
    use the new permanent transcript format. Rows with no channel number keep
    their legacy ``1-001`` / ``2-101`` formatting so historic log entries remain
    recognizable; truly old rows without a sequence use their stored number.
    """
    keys = set(ticket.keys()) if hasattr(ticket, "keys") else set(ticket)
    number = ticket["ticket_number"] if "ticket_number" in keys else 0
    sequence = ticket["ticket_sequence"] if "ticket_sequence" in keys else None
    channelNumber = ticket["channel_ticket_number"] if "channel_ticket_number" in keys else None
    if channelNumber is not None:
        return FormatPermanentTicketNumber(int(sequence if sequence is not None else number or 0))
    return FormatLegacyTicketLabel(number, sequence)


def TicketChannelLabelFromRow(ticket: Any) -> str:
    """Return the visible channel label, retaining old labels for migrated rows."""
    keys = set(ticket.keys()) if hasattr(ticket, "keys") else set(ticket)
    channelNumber = ticket["channel_ticket_number"] if "channel_ticket_number" in keys else None
    if channelNumber is not None:
        return FormatPermanentTicketNumber(int(channelNumber))
    number = ticket["ticket_number"] if "ticket_number" in keys else 0
    sequence = ticket["ticket_sequence"] if "ticket_sequence" in keys else None
    return FormatLegacyTicketLabel(number, sequence)
