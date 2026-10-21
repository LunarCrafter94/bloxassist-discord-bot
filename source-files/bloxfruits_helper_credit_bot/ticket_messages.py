"""Plain-text templates for new ticket channels."""

from __future__ import annotations

DEFAULT_TICKET_WELCOME_MESSAGE = (
    "Please describe what help you need and keep the discussion in this ticket. "
    "Follow the server rules, and never share your password or other private account information."
)

WELCOME_PLACEHOLDERS = ("{requester}", "{helpers}", "{ticket}", "{event}")


def RenderTicketWelcomeMessage(
    template: str,
    *,
    requester: str,
    helpers: str,
    ticket: str,
    event: str,
) -> str:
    """Replace supported literal placeholders without using Python format syntax."""
    rendered = str(template or "")
    for placeholder, value in (
        ("{requester}", requester),
        ("{helpers}", helpers),
        ("{ticket}", ticket),
        ("{event}", event),
    ):
        rendered = rendered.replace(placeholder, str(value))
    return rendered.strip()
