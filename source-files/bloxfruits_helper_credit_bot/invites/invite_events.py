"""Invite use attribution helpers for time-bounded invite reward events."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

logger = logging.getLogger(__name__)


def FormatInviteEventCountdown(event: object, *, now: datetime | None = None) -> str:
    """Format an event end as Discord's viewer-local relative-time countdown.

    Infinite events use the existing year-9999 end marker and are displayed as
    Forever. The stored absolute end instant remains the durable expiry source,
    so finite events continue to expire correctly across bot restarts.
    """
    try:
        rawEnd = str(event["ends_at"])
    except (KeyError, TypeError, IndexError):
        return "Unavailable"
    try:
        endsAt = datetime.fromisoformat(rawEnd.replace("Z", "+00:00"))
    except ValueError:
        return "Unavailable"
    if endsAt.year >= 9999:
        return "♾️ Forever (until manually ended)"
    if endsAt.tzinfo is None:
        endsAt = endsAt.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    unixTimestamp = int(endsAt.timestamp())
    if endsAt <= current:
        return f"<t:{unixTimestamp}:R> (ending now)"
    return f"<t:{unixTimestamp}:R>"


async def FetchInviteUseCounts(guild: discord.Guild) -> dict[str, int] | None:
    """Return current invite uses. The bot needs Manage Server to inspect invites."""
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        logger.warning("Cannot track invite rewards in guild %s: bot needs Manage Server permission", guild.id)
        return None
    except discord.HTTPException:
        logger.exception("Failed to fetch invites for guild %s", guild.id)
        return None
    return {str(invite.code): int(invite.uses or 0) for invite in invites}


def FindUsedInvite(invites: list[discord.Invite], before: dict[str, int]) -> discord.Invite | None:
    """Return the invite whose use count increased, if attribution is unambiguous."""
    increased = [invite for invite in invites if int(invite.uses or 0) > int(before.get(str(invite.code), 0))]
    if len(increased) == 1:
        return increased[0]
    return None
