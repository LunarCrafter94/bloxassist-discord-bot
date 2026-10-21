"""Invite use attribution helpers for time-bounded invite reward events."""
from __future__ import annotations

import logging
import discord

logger = logging.getLogger(__name__)


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
