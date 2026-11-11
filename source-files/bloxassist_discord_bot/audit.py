"""Per-server audit-channel delivery helpers."""
from __future__ import annotations

import logging
import discord

logger = logging.getLogger(__name__)


async def ResolveAuditChannel(guild: discord.Guild, guildDatabase):
    raw = guildDatabase.GetSetting("audit_log_channel_id", "") or ""
    if not str(raw).isdigit():
        return None
    channel = guild.get_channel(int(raw))
    if channel is None:
        try:
            channel = await guild.fetch_channel(int(raw))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return channel if isinstance(channel, discord.TextChannel) else None


async def SendAuditLog(guild: discord.Guild, guildDatabase, embed: discord.Embed, *, content: str | None = None) -> bool:
    """Send a log to the configured channel; return False instead of hiding failures."""
    channel = await ResolveAuditChannel(guild, guildDatabase)
    if channel is None:
        logger.warning("Audit log is not configured or cannot be reached: guild=%s", guild.id)
        return False
    botMember = guild.me
    permissions = channel.permissions_for(botMember) if botMember else None
    if permissions is None or not permissions.send_messages or not permissions.embed_links:
        logger.error("Bot lacks Send Messages / Embed Links in audit channel: guild=%s channel=%s", guild.id, channel.id)
        return False
    try:
        await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions.none())
        return True
    except discord.HTTPException:
        logger.exception("Could not send audit log: guild=%s channel=%s", guild.id, channel.id)
        return False
