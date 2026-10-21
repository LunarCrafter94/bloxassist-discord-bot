"""Persistent, guild-scoped admin dashboard and configuration controls."""

from __future__ import annotations

import logging
import re
import unicodedata

import discord

from ..database import DatabaseManager, GuildDatabase
from ..interaction_utils import SendEphemeralResponse
from ..ticket_messages import DEFAULT_TICKET_WELCOME_MESSAGE, RenderTicketWelcomeMessage

logger = logging.getLogger(__name__)

MAX_SERVICES = 25
MAX_CREDITS = 1_000_000_000


def _ParseIdList(value: str | None) -> list[int]:
    parsed: list[int] = []
    for token in (value or "").split(","):
        try:
            identifier = int(token.strip())
        except (TypeError, ValueError):
            continue
        if identifier > 0 and identifier not in parsed:
            parsed.append(identifier)
    return parsed


def GetDashboardModeratorRoleIds(guildDatabase: GuildDatabase) -> list[int]:
    return _ParseIdList(guildDatabase.GetSetting("dashboard_moderator_role_ids", ""))


def GetEffectiveTicketStaffRoleIds(
    guild: discord.Guild,
    guildDatabase: GuildDatabase,
) -> list[int]:
    """Return the selected staff role and non-managed roles above it in the hierarchy."""
    try:
        baselineRoleId = int(guildDatabase.GetSetting("ticket_staff_role_baseline_id", "") or 0)
    except (TypeError, ValueError):
        baselineRoleId = 0
    if not baselineRoleId:
        return []
    baselineRole = guild.get_role(baselineRoleId)
    if baselineRole is None or baselineRole.is_default():
        return []
    return [
        role.id
        for role in guild.roles
        if not role.is_default() and not role.managed and role.position >= baselineRole.position
    ]


def _IsAdministrator(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return False
    if interaction.user.id == interaction.guild.owner_id:
        return True
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.administrator)


async def EnsureDashboardAccess(
    interaction: discord.Interaction,
    databaseManager: DatabaseManager,
    *,
    administratorOnly: bool = False,
) -> bool:
    """Authorize every dashboard action in code, not solely through channel overwrites."""
    if interaction.guild is None or interaction.guild_id is None:
        await SendEphemeralResponse(interaction, 
            "This dashboard can only be used inside a server.", ephemeral=True
        )
        return False

    guildDatabase = databaseManager.ForServer(interaction.guild_id)
    expectedChannelText = guildDatabase.GetSetting("dashboard_channel_id", "") or ""
    try:
        expectedChannelId = int(expectedChannelText) if expectedChannelText else 0
    except ValueError:
        expectedChannelId = 0
    if expectedChannelId and interaction.channel_id and interaction.channel_id != expectedChannelId:
        await SendEphemeralResponse(interaction, 
            "Please use the latest dashboard message in the channel where an Administrator last ran `/setup admin_dashboard`.", ephemeral=True
        )
        return False

    if _IsAdministrator(interaction):
        return True
    if administratorOnly:
        await SendEphemeralResponse(interaction, 
            "Only a server Administrator can change dashboard access roles.", ephemeral=True
        )
        return False

    userRoles = getattr(interaction.user, "roles", ())
    userRoleIds = {role.id for role in userRoles}
    allowedRoleIds = set(GetDashboardModeratorRoleIds(guildDatabase))
    if allowedRoleIds.intersection(userRoleIds):
        return True

    await SendEphemeralResponse(interaction, 
        "You are not authorized to use this dashboard. Ask a server Administrator to configure a moderator role.",
        ephemeral=True,
    )
    return False



async def ApplyTicketStaffRolePolicy(
    guild: discord.Guild,
    guildDatabase: GuildDatabase,
) -> tuple[int, list[int]]:
    """Apply the new staff-role policy to all open ticket channels.

    Returns (updated channel count, failed channel IDs). The previous applied-role list
    remains saved if any update fails, so a later dashboard refresh can safely retry.
    """
    oldRoleIds = set(_ParseIdList(guildDatabase.GetSetting("ticket_staff_role_ids_effective", "")))
    newRoleIds = set(GetEffectiveTicketStaffRoleIds(guild, guildDatabase))
    if oldRoleIds == newRoleIds:
        return 0, []
    rows = guildDatabase.Execute(
        "SELECT channel_id FROM tickets WHERE status = 'open' AND channel_id IS NOT NULL",
        fetchAll=True,
    )
    updatedChannels = 0
    failedChannelIds: list[int] = []
    for row in rows:
        channelId = int(row["channel_id"])
        channel = guild.get_channel(channelId)
        if not isinstance(channel, discord.TextChannel):
            # It may already have been deleted; there is no active channel to modify.
            continue
        botMember = guild.me
        if botMember is None or not channel.permissions_for(botMember).manage_roles:
            logger.error(
                "Cannot update staff-role overwrites: guild=%s channel=%s bot_member=%s "
                "effective_manage_roles=%s guild_manage_roles=%s category=%s",
                guild.id, channel.id, botMember.id if botMember else None,
                channel.permissions_for(botMember).manage_roles if botMember else False,
                botMember.guild_permissions.manage_roles if botMember else False,
                channel.category_id,
            )
            failedChannelIds.append(channelId)
            continue
        try:
            for roleId in oldRoleIds | newRoleIds:
                role = guild.get_role(roleId)
                if role is None or role.is_default() or role.managed:
                    continue
                overwrite = channel.overwrites_for(role)
                if roleId in newRoleIds:
                    overwrite.view_channel = True
                    overwrite.send_messages = True
                    overwrite.read_message_history = True
                else:
                    overwrite.view_channel = None
                    overwrite.send_messages = None
                    overwrite.read_message_history = None
                await channel.set_permissions(
                    role,
                    overwrite=None if overwrite.is_empty() else overwrite,
                    reason="Update configured ticket staff access",
                )
            updatedChannels += 1
        except discord.HTTPException:
            logger.exception("Could not update staff access for open ticket channel %s", channelId)
            failedChannelIds.append(channelId)

    if not failedChannelIds:
        guildDatabase.SetSetting("ticket_staff_role_ids_effective", ",".join(str(x) for x in sorted(newRoleIds)))
    return updatedChannels, failedChannelIds


def BuildDashboardEmbed(guild: discord.Guild, guildDatabase: GuildDatabase) -> discord.Embed:
    activeServices = guildDatabase.ListServices(activeOnly=True)
    serviceLines = [
        f"• **{str(service['name'])[:80]}** — {int(service['price']):,} credits per helper"
        for service in activeServices[:15]
    ]
    if len(activeServices) > 15:
        serviceLines.append(f"…plus {len(activeServices) - 15} more enabled event(s).")
    if not serviceLines:
        serviceLines = ["No events are enabled. Add or enable an event below."]

    helpChannelId = guildDatabase.GetSetting("help_center_channel_id", "") or ""
    helpCenterText = f" <#{helpChannelId}>" if helpChannelId.isdigit() else "Not configured"
    roleIds = GetDashboardModeratorRoleIds(guildDatabase)
    roleNames = [
        guild.get_role(roleId).mention
        for roleId in roleIds
        if guild.get_role(roleId) is not None
    ]
    moderatorText = ", ".join(roleNames) if roleNames else "Administrators only"

    try:
        baselineId = int(guildDatabase.GetSetting("ticket_staff_role_baseline_id", "") or 0)
    except ValueError:
        baselineId = 0
    baselineRole = guild.get_role(baselineId) if baselineId else None
    baselineText = baselineRole.mention if baselineRole else "Not configured (only ticket participants and bot)"

    enabledInvites = (guildDatabase.GetSetting("invite_rewards_enabled", "false") or "false").lower() in {"true", "1", "yes", "on"}
    rewardCredits = int(guildDatabase.GetSetting("invite_reward_credits", "50") or "50")
    durationMinutes = int(guildDatabase.GetSetting("invite_duration_minutes", "60") or "60")
    inviteState = "Enabled" if enabledInvites else "Disabled (safe default; no rewards are issued by this setting alone)"

    embed = discord.Embed(
        title="⚙️ Private Admin Dashboard",
        description=(
            "Configure this server's credit and Help Center settings. Changes are saved in this server's own database.\n\n"
            "**Access:** server Administrators and the configured moderator roles below."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Starting credits for new accounts",
        value=f"**{guildDatabase.GetDefaultJoinCredits():,} credits**\nExisting balances are not changed.",
        inline=True,
    )
    embed.add_field(name="Maximum helpers per ticket", value=f"**{guildDatabase.GetMaxHelpers()}**", inline=True)
    embed.add_field(name="Invite reward defaults", value=f"{inviteState}\nReward: **{rewardCredits:,}** credits\nDefault duration: **{durationMinutes} minutes**", inline=True)
    leavePenalty = int(guildDatabase.GetSetting("invite_leave_penalty_credits", "0") or "0")
    embed.add_field(name="Inviter leave penalty", value=f"**{leavePenalty:,} credits** per invited member who leaves\nSet to **0** to disable. Only the recorded inviter is penalized.", inline=True)
    embed.add_field(name="Enabled events · price per helper", value="\n".join(serviceLines)[:1024], inline=False)
    embed.add_field(name="Public Help Center", value=helpCenterText, inline=True)
    embed.add_field(name="Ticket staff access baseline", value=baselineText, inline=True)
    embed.add_field(name="Dashboard moderator roles", value=moderatorText, inline=False)
    auditChannelId = guildDatabase.GetSetting("audit_log_channel_id", "") or ""
    auditChannelText = f" <#{auditChannelId}>" if auditChannelId.isdigit() else "Not configured"
    embed.add_field(name="Ticket transcripts · credit audit · reports", value=auditChannelText, inline=False)
    welcomeText = (guildDatabase.GetSetting("ticket_welcome_message", "") or "").strip()
    welcomeState = "Enabled" if welcomeText else "Disabled"
    embed.add_field(
        name="New ticket welcome message",
        value=f"{welcomeState} · ordinary text, not pinned and not an embed",
        inline=False,
    )
    activeInviteEvent = guildDatabase.GetActiveInviteEvent()
    if activeInviteEvent is not None:
        embed.add_field(
            name="Active invite event",
            value=f"Event #{int(activeInviteEvent['event_id'])} · {int(activeInviteEvent['reward_credits']):,} credits per eligible join\nEnds: {activeInviteEvent['ends_at']}",
            inline=False,
        )
    else:
        embed.add_field(name="Active invite event", value="None", inline=False)
    embed.set_footer(text="Event price is per helper. Total reservation = price per helper × selected helper count. Unfilled slots are refunded at completion.")
    return embed


async def RefreshDashboardMessage(guild: discord.Guild, guildDatabase: GuildDatabase, databaseManager: DatabaseManager) -> None:
    try:
        channelId = int(guildDatabase.GetSetting("dashboard_channel_id", "") or 0)
        messageId = int(guildDatabase.GetSetting("dashboard_message_id", "") or 0)
    except (TypeError, ValueError):
        return
    channel = guild.get_channel(channelId) if channelId else None
    if not isinstance(channel, discord.TextChannel) or not messageId:
        return
    try:
        message = await channel.fetch_message(messageId)
        await message.edit(embed=BuildDashboardEmbed(guild, guildDatabase), view=DashboardView(databaseManager))
    except discord.HTTPException:
        logger.exception("Could not refresh the dashboard message in guild %s", guild.id)


async def RefreshHelpCenterPanelIfConfigured(guild: discord.Guild, databaseManager: DatabaseManager) -> None:
    try:
        from ..tickets.ticket_views import RefreshHelpCenterPanel
        await RefreshHelpCenterPanel(guild, databaseManager)
    except Exception:
        logger.exception("Could not refresh Help Center panel for guild %s", guild.id)


async def _CreateOrUpdateDashboard(
    guild: discord.Guild,
    targetChannel: discord.TextChannel,
    guildDatabase: GuildDatabase,
    databaseManager: DatabaseManager,
) -> tuple[discord.TextChannel, discord.Message]:
    """Post/update the dashboard in the channel selected by the invoking command."""
    if targetChannel.guild.id != guild.id:
        raise ValueError("The dashboard channel must belong to the current server.")

    botMember = guild.me
    if botMember is None:
        raise PermissionError("I could not verify my membership in this server.")
    channelPermissions = targetChannel.permissions_for(botMember)
    missingPermissions = []
    if not channelPermissions.view_channel:
        missingPermissions.append("View Channel")
    if not channelPermissions.send_messages:
        missingPermissions.append("Send Messages")
    if not channelPermissions.embed_links:
        missingPermissions.append("Embed Links")
    if not channelPermissions.read_message_history:
        missingPermissions.append("Read Message History")
    if missingPermissions:
        raise PermissionError(
            "I need these permissions in this channel: " + ", ".join(missingPermissions) + "."
        )

    oldChannelIdText = guildDatabase.GetSetting("dashboard_channel_id", "") or ""
    oldMessageIdText = guildDatabase.GetSetting("dashboard_message_id", "") or ""
    try:
        oldChannelId = int(oldChannelIdText) if oldChannelIdText else 0
        oldMessageId = int(oldMessageIdText) if oldMessageIdText else 0
    except (TypeError, ValueError):
        oldChannelId = oldMessageId = 0

    oldChannel = guild.get_channel(oldChannelId) if oldChannelId else None
    oldMessage = None
    if oldChannelId == targetChannel.id and oldMessageId:
        try:
            oldMessage = await targetChannel.fetch_message(oldMessageId)
        except discord.NotFound:
            oldMessage = None
        except discord.HTTPException:
            logger.exception("Could not fetch the saved dashboard message in guild %s", guild.id)
            raise

    if oldMessage is not None:
        dashboardMessage = await oldMessage.edit(
            embed=BuildDashboardEmbed(guild, guildDatabase),
            view=DashboardView(databaseManager),
        )
    else:
        dashboardMessage = await targetChannel.send(
            embed=BuildDashboardEmbed(guild, guildDatabase),
            view=DashboardView(databaseManager),
        )

    # Store the new location only after Discord confirms the message exists.
    guildDatabase.SetSetting("dashboard_channel_id", targetChannel.id)
    guildDatabase.SetSetting("dashboard_message_id", dashboardMessage.id)

    # If the dashboard was moved, remove the old bot message when possible. Never delete
    # the old channel; it may contain unrelated messages or be used for other purposes.
    if oldChannelId and oldMessageId and oldChannelId != targetChannel.id:
        if isinstance(oldChannel, discord.TextChannel):
            try:
                staleMessage = await oldChannel.fetch_message(oldMessageId)
                await staleMessage.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                logger.warning(
                    "Moved dashboard, but could not remove old dashboard message %s in channel %s",
                    oldMessageId, oldChannelId,
                )

    return targetChannel, dashboardMessage


class DashboardView(discord.ui.View):
    """Persistent dashboard actions. Each callback performs a fresh authorization check."""

    def __init__(self, databaseManager: DatabaseManager):
        super().__init__(timeout=None)
        self.databaseManager = databaseManager

    @discord.ui.button(label="Starting Credits", emoji="💰", style=discord.ButtonStyle.primary, custom_id="bf:dashboard:starting_credits", row=0)
    async def StartingCredits(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        await interaction.response.send_modal(StartingCreditsModal(self.databaseManager, db.GetDefaultJoinCredits()))

    @discord.ui.button(label="Event Catalog", emoji="📋", style=discord.ButtonStyle.primary, custom_id="bf:dashboard:events", row=0)
    async def EventCatalog(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        view = EventCatalogView(self.databaseManager, interaction.guild_id)
        await SendEphemeralResponse(interaction, 
            embed=BuildServiceCatalogEmbed(self.databaseManager.ForServer(interaction.guild_id)),
            content="Select an event first, then choose an action below.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Maximum Helpers", emoji="👥", style=discord.ButtonStyle.primary, custom_id="bf:dashboard:max_helpers", row=1)
    async def MaximumHelpers(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        await interaction.response.send_modal(MaxHelpersModal(self.databaseManager, db.GetMaxHelpers()))

    @discord.ui.button(label="Invite Defaults", emoji="🎟️", style=discord.ButtonStyle.secondary, custom_id="bf:dashboard:invite_defaults", row=1)
    async def InviteDefaults(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        await interaction.response.send_modal(InviteSettingsModal(self.databaseManager, db))

    @discord.ui.button(label="Inviter Leave Penalty", emoji="⚖️", style=discord.ButtonStyle.danger, custom_id="bf:dashboard:invite_leave_penalty", row=4)
    async def InviteLeavePenalty(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.guild.owner_id != interaction.user.id:
            await SendEphemeralResponse(interaction, "Only the server owner can change inviter leave penalties.", ephemeral=True)
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        await interaction.response.send_modal(InviteLeavePenaltyModal(self.databaseManager, db.GetSetting("invite_leave_penalty_credits", "0") or "0"))

    @discord.ui.button(label="Help Center Channel", emoji="📣", style=discord.ButtonStyle.primary, custom_id="bf:dashboard:help_channel", row=2)
    async def HelpCenterChannel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        await SendEphemeralResponse(interaction, 
            "Choose the text channel where the public Help Center panel should be posted or updated.",
            view=HelpCenterChannelView(self.databaseManager),
            ephemeral=True,
        )

    @discord.ui.button(label="Moderator Roles", emoji="🛡️", style=discord.ButtonStyle.secondary, custom_id="bf:dashboard:moderator_roles", row=2)
    async def ModeratorRoles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager, administratorOnly=True):
            return
        guildDatabase = self.databaseManager.ForServer(interaction.guild_id)
        selectedIds = GetDashboardModeratorRoleIds(guildDatabase)
        view = ModeratorRoleView(self.databaseManager, selectedIds, interaction.guild)
        await SendEphemeralResponse(interaction, 
            "Select the role(s) allowed to use dashboard controls. Only an Administrator can change this list. "
            "Roles with Administrator permission can access the dashboard regardless of this list.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Ticket Staff Role", emoji="🔐", style=discord.ButtonStyle.secondary, custom_id="bf:dashboard:ticket_staff_role", row=3)
    async def TicketStaffRole(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        try:
            selectedId = int(db.GetSetting("ticket_staff_role_baseline_id", "") or 0)
        except ValueError:
            selectedId = 0
        view = TicketStaffRoleView(self.databaseManager, selectedId or None, interaction.guild)
        await SendEphemeralResponse(interaction, 
            "Select a baseline staff role. That role and non-managed roles above it in the server role hierarchy "
            "will receive access to new and currently open tickets. This does not grant Administrator permission.",
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Audit Log Channel", emoji="📜", style=discord.ButtonStyle.primary, custom_id="bf:dashboard:audit_channel", row=3)
    async def AuditLogChannel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        await SendEphemeralResponse(
            interaction,
            "Choose the private channel where ticket transcripts, credit-change audit entries, invite rewards, and general moderation reports should be posted. Give the bot Send Messages, Embed Links, Attach Files, and Read Message History.",
            view=AuditLogChannelView(self.databaseManager),
            ephemeral=True,
        )

    @discord.ui.button(label="Ticket Welcome Message", emoji="💬", style=discord.ButtonStyle.primary, custom_id="bf:dashboard:ticket_welcome_message", row=4)
    async def TicketWelcomeMessage(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        currentMessage = db.GetSetting("ticket_welcome_message", DEFAULT_TICKET_WELCOME_MESSAGE)
        await interaction.response.send_modal(
            TicketWelcomeMessageModal(self.databaseManager, currentMessage or "")
        )

    @discord.ui.button(label="Preview Welcome", emoji="👁️", style=discord.ButtonStyle.secondary, custom_id="bf:dashboard:ticket_welcome_preview", row=4)
    async def PreviewTicketWelcome(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        template = db.GetSetting("ticket_welcome_message", "") or ""
        if not template.strip():
            await SendEphemeralResponse(interaction, "The custom ticket welcome message is disabled.", ephemeral=True)
            return
        preview = RenderTicketWelcomeMessage(
            template,
            requester="@Requester",
            helpers="@Helper1 @Helper2",
            ticket="001",
            event="V4 Trials",
        )
        if len(preview) > 1750:
            preview = preview[:1747] + "..."
        await SendEphemeralResponse(
            interaction,
            "**Preview only — these are example values, not real mentions:**\n\n" + preview,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Reset Welcome Message", emoji="↩️", style=discord.ButtonStyle.secondary, custom_id="bf:dashboard:ticket_welcome_reset", row=4)
    async def ResetTicketWelcome(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        db.SetSetting("ticket_welcome_message", DEFAULT_TICKET_WELCOME_MESSAGE)
        await SendEphemeralResponse(
            interaction,
            "✅ The ticket welcome message was reset to the default for new tickets. Existing tickets are unchanged.",
            ephemeral=True,
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)

    @discord.ui.button(label="Refresh Dashboard", emoji="🔄", style=discord.ButtonStyle.success, custom_id="bf:dashboard:refresh", row=3)
    async def Refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        await interaction.response.defer()
        guildDatabase = self.databaseManager.ForServer(interaction.guild_id)
        await ApplyTicketStaffRolePolicy(interaction.guild, guildDatabase)
        await interaction.edit_original_response(embed=BuildDashboardEmbed(interaction.guild, guildDatabase), view=self)
        await RefreshHelpCenterPanelIfConfigured(interaction.guild, self.databaseManager)


class TicketWelcomeMessageModal(discord.ui.Modal, title="Ticket Welcome Message"):
    welcomeMessage = discord.ui.TextInput(
        label="Plain-text message (blank disables)",
        placeholder="Use {requester}, {helpers}, {ticket}, or {event}",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=2000,
    )

    def __init__(self, databaseManager: DatabaseManager, currentMessage: str):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        # A blank value intentionally disables the optional message.
        self.welcomeMessage.default = currentMessage[:2000] if currentMessage else None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this setting inside a server.", ephemeral=True)
            return
        content = str(self.welcomeMessage.value or "").strip()
        if len(content) > 2000:
            await SendEphemeralResponse(interaction, "The welcome message must be 2,000 characters or fewer.", ephemeral=True)
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        db.SetSetting("ticket_welcome_message", content)
        status = "disabled for new tickets" if not content else "saved for new tickets"
        await SendEphemeralResponse(
            interaction,
            f"✅ Ticket welcome message {status}. This is an ordinary message, not pinned and not an embed. Existing tickets are unchanged.\n\n"
            "Supported placeholders: {requester}, {helpers}, {ticket}, {event}. "
            "Mentions in this custom message will not ping members. Reopen the editor to change it again.",
            ephemeral=True,
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)


class InviteLeavePenaltyModal(discord.ui.Modal, title="Inviter Leave Penalty"):
    amount = discord.ui.TextInput(
        label="Penalty per invited member (0 disables)",
        placeholder="0",
        min_length=1,
        max_length=10,
        required=True,
    )

    def __init__(self, databaseManager: DatabaseManager, currentAmount: str):
        super().__init__()
        self.databaseManager = databaseManager
        self.amount.default = str(currentAmount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.owner_id != interaction.user.id:
            await SendEphemeralResponse(interaction, "Only the server owner can change inviter leave penalties.", ephemeral=True)
            return
        raw = str(self.amount.value).strip()
        if not raw.isdigit() or int(raw) > MAX_CREDITS:
            await SendEphemeralResponse(interaction, f"Enter a whole number from 0 to {MAX_CREDITS:,}.", ephemeral=True)
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        db.SetSetting("invite_leave_penalty_credits", int(raw))
        await SendEphemeralResponse(
            interaction,
            f"✅ Inviter leave penalty saved: **{int(raw):,} credits** per attributed member who leaves. "
            + ("Penalties are disabled." if int(raw) == 0 else "Only that member's recorded inviter can be penalized."),
            ephemeral=True,
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)


class StartingCreditsModal(discord.ui.Modal, title="Starting Credits for New Accounts"):
    startingCredits = discord.ui.TextInput(
        label="Starting credits (0 or higher)",
        placeholder="100",
        min_length=1,
        max_length=10,
    )

    def __init__(self, databaseManager: DatabaseManager, currentCredits: int):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        self.startingCredits.default = str(currentCredits)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        rawValue = str(self.startingCredits.value).strip()
        if not rawValue.isdecimal() or int(rawValue) > MAX_CREDITS:
            await SendEphemeralResponse(interaction, 
                f"Enter a whole number from 0 to {MAX_CREDITS:,}.", ephemeral=True
            )
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        db.SetDefaultJoinCredits(int(rawValue))
        await SendEphemeralResponse(interaction, 
            f"✅ New accounts will start with **{int(rawValue):,} credits**. Existing balances were not changed.",
            ephemeral=True,
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)
        await RefreshHelpCenterPanelIfConfigured(interaction.guild, self.databaseManager)


class MaxHelpersModal(discord.ui.Modal, title="Maximum Helpers per Ticket"):
    maxHelpers = discord.ui.TextInput(
        label="Maximum helpers (1–25)", placeholder="5", min_length=1, max_length=2
    )

    def __init__(self, databaseManager: DatabaseManager, currentMax: int):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        self.maxHelpers.default = str(currentMax)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        rawValue = str(self.maxHelpers.value).strip()
        if not rawValue.isdecimal() or not 1 <= int(rawValue) <= 25:
            await SendEphemeralResponse(interaction, "Enter a whole number from 1 to 25.", ephemeral=True)
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        db.SetMaxHelpers(int(rawValue))
        await SendEphemeralResponse(interaction, 
            f"✅ New ticket requests may select up to **{int(rawValue)} helpers**. Existing tickets are unchanged.",
            ephemeral=True,
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)


class InviteSettingsModal(discord.ui.Modal, title="Invite Reward Defaults"):
    enabled = discord.ui.TextInput(
        label="Enable invite rewards? (yes/no)", placeholder="no", min_length=2, max_length=5
    )
    rewardCredits = discord.ui.TextInput(
        label="Credits per eligible invite", placeholder="50", min_length=1, max_length=10
    )
    durationMinutes = discord.ui.TextInput(
        label="Default event duration in minutes", placeholder="60", min_length=1, max_length=5
    )

    def __init__(self, databaseManager: DatabaseManager, guildDatabase: GuildDatabase):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        self.enabled.default = guildDatabase.GetSetting("invite_rewards_enabled", "false") or "false"
        self.rewardCredits.default = guildDatabase.GetSetting("invite_reward_credits", "50") or "50"
        self.durationMinutes.default = guildDatabase.GetSetting("invite_duration_minutes", "60") or "60"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        enabledText = str(self.enabled.value).strip().lower()
        if enabledText not in {"yes", "no", "true", "false", "on", "off", "1", "0"}:
            await SendEphemeralResponse(interaction, "Use yes or no for the enabled setting.", ephemeral=True)
            return
        rewardText = str(self.rewardCredits.value).strip()
        durationText = str(self.durationMinutes.value).strip()
        if not rewardText.isdecimal() or int(rewardText) > MAX_CREDITS:
            await SendEphemeralResponse(interaction, 
                f"Reward credits must be a whole number from 0 to {MAX_CREDITS:,}.", ephemeral=True
            )
            return
        if not durationText.isdecimal() or not 1 <= int(durationText) <= 10_080:
            await SendEphemeralResponse(interaction, "Duration must be between 1 and 10080 minutes (7 days).", ephemeral=True)
            return

        isEnabled = enabledText in {"yes", "true", "on", "1"}
        db = self.databaseManager.ForServer(interaction.guild_id)
        db.SetSetting("invite_rewards_enabled", "true" if isEnabled else "false")
        db.SetSetting("invite_reward_credits", int(rewardText))
        db.SetSetting("invite_duration_minutes", int(durationText))
        endedActiveEvent = None
        if not isEnabled:
            # Turning off the global invite-reward switch also ends a live event, so
            # joins after this change cannot receive rewards unexpectedly.
            endStatus, endedActiveEvent = db.EndInviteEvent(endedBy=interaction.user.id)
            if endStatus == "none_active":
                endedActiveEvent = None
        await SendEphemeralResponse(
            interaction,
            "✅ Invite reward settings saved. " + (
                "The active event was ended because invite rewards were disabled. " if endedActiveEvent else ""
            ) + "When enabled, staff can use `/invite-event start` to begin a timed event and `/invite-event end` to stop it early. Invite attribution requires the bot's Manage Server permission.",
            ephemeral=True,
        )
        if endedActiveEvent is not None:
            auditEmbed = discord.Embed(
                title="🛑 Invite reward event ended",
                description=f"Invite event #{int(endedActiveEvent['event_id'])} ended because invite rewards were disabled in the Admin Dashboard by <@{interaction.user.id}>.",
                color=discord.Color.orange(), timestamp=discord.utils.utcnow(),
            )
            await SendAuditLog(interaction.guild, db, auditEmbed)
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)


def BuildServiceCatalogEmbed(guildDatabase: GuildDatabase) -> discord.Embed:
    allServices = guildDatabase.ListServices(activeOnly=False)
    lines = []
    for service in allServices[:MAX_SERVICES]:
        state = "Enabled" if int(service["active"]) else "Disabled"
        lines.append(f"• **{str(service['name'])[:80]}** — {int(service['price']):,} credits per helper · {state}\n  Key: `{service['service_key']}`")
    if not lines:
        lines = ["No events are configured yet."]
    return discord.Embed(
        title="📋 Event Catalog",
        description=("The listed price is the fixed price per helper. Total reservation = price per helper × the number of helpers selected when the ticket is created. Each active helper earns one unit price; if helper slots remain empty at completion, the unfilled slots are refunded to the requester. Replacements fill existing slots and do not raise the reserved total.\n\n" + "\n".join(lines))[:4096],
        color=discord.Color.blurple(),
    )


class EventSelect(discord.ui.Select):
    def __init__(self, guildDatabase: GuildDatabase):
        services = guildDatabase.ListServices(activeOnly=False)[:MAX_SERVICES]
        options = [
            discord.SelectOption(
                label=str(service["name"])[:100],
                value=str(service["service_key"]),
                description=f"{int(service['price']):,} credits per helper · {'enabled' if int(service['active']) else 'disabled'}"[:100],
            )
            for service in services
        ]
        super().__init__(
            placeholder="Select an event to edit or enable/disable",
            min_values=1,
            max_values=1,
            options=options or [discord.SelectOption(label="No events configured", value="__none__")],
            disabled=not bool(options),
            custom_id="bf:dashboard:event_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, EventCatalogView):
            await SendEphemeralResponse(interaction, "This event catalog has expired. Reopen it from the dashboard.", ephemeral=True)
            return
        if not await EnsureDashboardAccess(interaction, view.databaseManager):
            return
        view.sourceMessage = interaction.message
        view.selectedKey = self.values[0] if self.values and self.values[0] != "__none__" else None
        db = view.databaseManager.ForServer(interaction.guild_id)
        selected = db.GetService(view.selectedKey, activeOnly=False) if view.selectedKey else None
        if selected is None:
            content = "No event is selected. Use Add Event to create one."
        else:
            state = "enabled" if int(selected["active"]) else "disabled"
            content = f"Selected **{selected['name']}** · {int(selected['price']):,} credits per helper · {state}."
        await interaction.response.edit_message(content=content, embed=BuildServiceCatalogEmbed(db), view=view)


class EventCatalogView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager, guildId: int):
        super().__init__(timeout=300)
        self.databaseManager = databaseManager
        self.selectedKey: str | None = None
        self.sourceMessage: discord.Message | None = None
        self.add_item(EventSelect(databaseManager.ForServer(guildId)))

    async def _Authorized(self, interaction: discord.Interaction) -> bool:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return False
        return True

    async def RefreshSourceMessage(self, guildDatabase: GuildDatabase, content: str) -> None:
        if self.sourceMessage is None:
            return
        selectedKey = self.selectedKey
        refreshedView = EventCatalogView(self.databaseManager, guildDatabase.guildId)
        if selectedKey and guildDatabase.GetService(selectedKey, activeOnly=False) is not None:
            refreshedView.selectedKey = selectedKey
        refreshedView.sourceMessage = self.sourceMessage
        try:
            await self.sourceMessage.edit(
                content=content,
                embed=BuildServiceCatalogEmbed(guildDatabase),
                view=refreshedView,
            )
        except discord.HTTPException:
            logger.exception("Could not refresh event catalog message after a setting change")

    @discord.ui.button(label="Add Event", emoji="➕", style=discord.ButtonStyle.success, row=1)
    async def AddEvent(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._Authorized(interaction):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        if len(db.ListServices(activeOnly=False)) >= MAX_SERVICES:
            await SendEphemeralResponse(interaction, 
                "The catalog supports up to 25 events so every event can fit in Discord's selection menu. Disable an event to keep it configured; the 25-event limit keeps the Discord selection menu usable.",
                ephemeral=True,
            )
            return
        self.sourceMessage = interaction.message
        await interaction.response.send_modal(ServiceModal(self.databaseManager, mode="add", catalogView=self))

    @discord.ui.button(label="Edit Selected", emoji="✏️", style=discord.ButtonStyle.primary, row=1)
    async def EditSelected(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._Authorized(interaction):
            return
        if not self.selectedKey:
            await SendEphemeralResponse(interaction, "Select an event in the menu first.", ephemeral=True)
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        service = db.GetService(self.selectedKey, activeOnly=False)
        if service is None:
            await SendEphemeralResponse(interaction, "That event no longer exists. Refresh the catalog.", ephemeral=True)
            return
        self.sourceMessage = interaction.message
        await interaction.response.send_modal(
            ServiceModal(
                self.databaseManager,
                mode="edit",
                serviceKey=self.selectedKey,
                currentName=str(service["name"]),
                currentPrice=int(service["price"]),
                catalogView=self,
            )
        )

    @discord.ui.button(label="Enable / Disable", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def ToggleSelected(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._Authorized(interaction):
            return
        if not self.selectedKey:
            await SendEphemeralResponse(interaction, "Select an event in the menu first.", ephemeral=True)
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        service = db.GetService(self.selectedKey, activeOnly=False)
        if service is None:
            await SendEphemeralResponse(interaction, "That event no longer exists. Refresh the catalog.", ephemeral=True)
            return
        newState = not bool(int(service["active"]))
        db.SaveService(self.selectedKey, str(service["name"]), int(service["price"]), active=newState)
        stateText = "enabled" if newState else "disabled"
        self.sourceMessage = interaction.message
        await interaction.response.edit_message(
            content=f"✅ **{service['name']}** is now {stateText}.",
            embed=BuildServiceCatalogEmbed(db),
            view=self,
        )
        await self.RefreshSourceMessage(db, f"✅ **{service['name']}** is now {stateText}.")
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)
        await RefreshHelpCenterPanelIfConfigured(interaction.guild, self.databaseManager)

    @discord.ui.button(label="Remove Event", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def RemoveSelected(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._Authorized(interaction):
            return
        if not self.selectedKey:
            await SendEphemeralResponse(interaction, "Select an event first.", ephemeral=True)
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        service = db.GetService(self.selectedKey, activeOnly=False)
        if service is None:
            await SendEphemeralResponse(interaction, "That event no longer exists.", ephemeral=True)
            return
        if not bool(int(service["active"])):
            await SendEphemeralResponse(interaction, f"**{service['name']}** is already removed from the active event list.", ephemeral=True)
            return
        # Soft-remove: preserve service key/name and old ticket references for history.
        db.SaveService(self.selectedKey, str(service["name"]), int(service["price"]), active=False)
        self.sourceMessage = interaction.message
        await interaction.response.edit_message(
            content=f"🗑️ **{service['name']}** was removed from new ticket requests. Historical tickets remain intact.",
            embed=BuildServiceCatalogEmbed(db), view=self,
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)
        await RefreshHelpCenterPanelIfConfigured(interaction.guild, self.databaseManager)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def Refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._Authorized(interaction):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        self.sourceMessage = interaction.message
        refreshedView = EventCatalogView(self.databaseManager, interaction.guild_id)
        if self.selectedKey and db.GetService(self.selectedKey, activeOnly=False) is not None:
            refreshedView.selectedKey = self.selectedKey
        refreshedView.sourceMessage = interaction.message
        await interaction.response.edit_message(
            content="Event catalog refreshed.",
            embed=BuildServiceCatalogEmbed(db),
            view=refreshedView,
        )


class ServiceModal(discord.ui.Modal):
    def __init__(
        self,
        databaseManager: DatabaseManager,
        *,
        mode: str,
        serviceKey: str | None = None,
        currentName: str = "",
        currentPrice: int = 100,
        catalogView: EventCatalogView,
    ):
        super().__init__(title="Add Event" if mode == "add" else "Edit Event", timeout=180)
        self.databaseManager = databaseManager
        self.mode = mode
        self.serviceKey = serviceKey
        self.catalogView = catalogView
        self.eventName = discord.ui.TextInput(
            label="Event name",
            placeholder="Example: V4 Trials",
            min_length=1,
            max_length=80,
            default=currentName if mode == "edit" else None,
        )
        self.totalPrice = discord.ui.TextInput(
            label="Price per helper in credits (0 or higher)",
            placeholder="200",
            min_length=1,
            max_length=10,
            default=str(currentPrice) if mode == "edit" else None,
        )
        self.add_item(self.eventName)
        self.add_item(self.totalPrice)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        name = str(self.eventName.value).strip()
        priceText = str(self.totalPrice.value).strip()
        if not name:
            await SendEphemeralResponse(interaction, "Event name cannot be empty.", ephemeral=True)
            return
        if not priceText.isdecimal() or int(priceText) > MAX_CREDITS:
            await SendEphemeralResponse(interaction, 
                f"Price must be a whole number from 0 to {MAX_CREDITS:,}.", ephemeral=True
            )
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        if self.mode == "add":
            if len(db.ListServices(activeOnly=False)) >= MAX_SERVICES:
                await SendEphemeralResponse(interaction, "The catalog already contains 25 events.", ephemeral=True)
                return
            serviceKey = _MakeUniqueServiceKey(db, name)
            db.SaveService(serviceKey, name, int(priceText), active=True)
            self.catalogView.selectedKey = serviceKey
            result = f"✅ Added **{name}** at **{int(priceText):,} credits per helper**."
        else:
            serviceKey = self.serviceKey or ""
            oldService = db.GetService(serviceKey, activeOnly=False)
            if oldService is None:
                await SendEphemeralResponse(interaction, "That event no longer exists. Reopen the event catalog.", ephemeral=True)
                return
            db.SaveService(serviceKey, name, int(priceText), active=bool(int(oldService["active"])))
            result = f"✅ Updated **{name}** to **{int(priceText):,} credits per helper**."
        await SendEphemeralResponse(interaction, result, ephemeral=True)
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)
        await RefreshHelpCenterPanelIfConfigured(interaction.guild, self.databaseManager)
        await self.catalogView.RefreshSourceMessage(db, result)


def _MakeUniqueServiceKey(guildDatabase: GuildDatabase, name: str) -> str:
    normalizedName = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    baseKey = re.sub(r"[^a-z0-9]+", "_", normalizedName).strip("_")[:48] or "event"
    candidate = baseKey
    suffix = 2
    while guildDatabase.GetService(candidate, activeOnly=False) is not None:
        suffixText = f"_{suffix}"
        candidate = f"{baseKey[:48-len(suffixText)]}{suffixText}"
        suffix += 1
    return candidate


class AuditLogChannelPicker(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Choose the private audit/transcript text channel",
            min_values=1, max_values=1, channel_types=[discord.ChannelType.text],
            custom_id="bf:dashboard:audit_channel_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, AuditLogChannelView):
            await SendEphemeralResponse(interaction, "This selector expired. Reopen Audit Log Channel from the dashboard.", ephemeral=True)
            return
        if not await EnsureDashboardAccess(interaction, view.databaseManager):
            return
        channel = interaction.guild.get_channel(self.values[0].id) if interaction.guild else None
        if not isinstance(channel, discord.TextChannel):
            await SendEphemeralResponse(interaction, "Choose a normal text channel in this server.", ephemeral=True)
            return
        botMember = interaction.guild.me
        permissions = channel.permissions_for(botMember) if botMember else None
        required = {
            "View Channel": bool(permissions and permissions.view_channel),
            "Send Messages": bool(permissions and permissions.send_messages),
            "Embed Links": bool(permissions and permissions.embed_links),
            "Attach Files": bool(permissions and permissions.attach_files),
            "Read Message History": bool(permissions and permissions.read_message_history),
        }
        missing = [name for name, allowed in required.items() if not allowed]
        if missing:
            await SendEphemeralResponse(interaction, "I need these permissions in the selected channel: " + ", ".join(missing) + ".", ephemeral=True)
            return
        db = view.databaseManager.ForServer(interaction.guild_id)
        db.SetSetting("audit_log_channel_id", channel.id)
        await SendEphemeralResponse(
            interaction,
            f"✅ Audit log channel set to {channel.mention}. New ticket transcripts, credit-change logs, invite rewards, and general reports will be sent there.",
            ephemeral=True,
        )
        await RefreshDashboardMessage(interaction.guild, db, view.databaseManager)


class AuditLogChannelView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        self.add_item(AuditLogChannelPicker())


class HelpCenterChannelPicker(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Choose a public Help Center text channel",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text],
            custom_id="bf:dashboard:help_channel_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpCenterChannelView):
            await SendEphemeralResponse(interaction, "This selector has expired. Reopen it from the dashboard.", ephemeral=True)
            return
        if not await EnsureDashboardAccess(interaction, view.databaseManager):
            return
        selectedValue = self.values[0]
        selectedChannel = interaction.guild.get_channel(selectedValue.id)
        if not isinstance(selectedChannel, discord.TextChannel):
            await SendEphemeralResponse(interaction, "Please choose a normal text channel in this server.", ephemeral=True)
            return
        await interaction.response.defer()
        db = view.databaseManager.ForServer(interaction.guild_id)
        try:
            from ..tickets.ticket_views import PostOrUpdateHelpCenterPanel
            panelMessage, wasUpdated = await PostOrUpdateHelpCenterPanel(
                interaction.guild, selectedChannel, view.databaseManager
            )
        except PermissionError as error:
            await interaction.edit_original_response(
                content=f"❌ I cannot use that channel. {error} Give the bot the listed channel permissions, then try again.",
                view=None,
            )
            return
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="❌ Discord denied access to that channel. Give the bot View Channel, Send Messages, Read Message History, and Embed Links permissions there, then try again.",
                view=None,
            )
            return
        except Exception:
            logger.exception("Could not set Help Center channel for guild %s", interaction.guild_id)
            await interaction.edit_original_response(
                content="❌ I couldn't update the Help Center panel. Check the bot's channel permissions and logs.",
                view=None,
            )
            return
        status = "updated" if wasUpdated else "posted"
        await interaction.edit_original_response(
            content=f"✅ Help Center panel {status} in {selectedChannel.mention}.", view=None
        )
        await RefreshDashboardMessage(interaction.guild, db, view.databaseManager)


class HelpCenterChannelView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        self.add_item(HelpCenterChannelPicker())


class ModeratorRolePicker(discord.ui.RoleSelect):
    def __init__(self, defaultRoles: list[discord.Role]):
        super().__init__(
            placeholder="Choose allowed moderator roles",
            min_values=0,
            max_values=25,
            default_values=defaultRoles,
            custom_id="bf:dashboard:moderator_role_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ModeratorRoleView):
            await SendEphemeralResponse(interaction, "This selector has expired. Reopen it from the dashboard.", ephemeral=True)
            return
        if not await EnsureDashboardAccess(interaction, view.databaseManager, administratorOnly=True):
            return
        validRoles = [role for role in self.values if not role.is_default() and not role.managed]
        view.selectedRoleIds = [role.id for role in validRoles]
        ignoredCount = len(self.values) - len(validRoles)
        content = f"Selected {len(view.selectedRoleIds)} moderator role(s). Press **Save Roles** to apply."
        if ignoredCount:
            content += " Everyone and integration-managed roles are ignored."
        await interaction.response.edit_message(content=content, view=view)


class ModeratorRoleView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager, selectedRoleIds: list[int], guild: discord.Guild):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        self.selectedRoleIds = list(selectedRoleIds)
        defaultRoles = [
            role for roleId in selectedRoleIds
            if (role := guild.get_role(roleId)) is not None
            and not role.is_default() and not role.managed
        ]
        self.add_item(ModeratorRolePicker(defaultRoles))

    @discord.ui.button(label="Save Roles", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def SaveRoles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager, administratorOnly=True):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        validRoleIds = [
            roleId for roleId in self.selectedRoleIds
            if (interaction.guild.get_role(roleId) is not None
                and not interaction.guild.get_role(roleId).is_default()
                and not interaction.guild.get_role(roleId).managed)
        ]
        db.SetSetting("dashboard_moderator_role_ids", ",".join(str(x) for x in validRoleIds))
        await interaction.response.defer()
        await interaction.edit_original_response(
            content=f"✅ Dashboard moderator roles saved ({len(validRoleIds)} role(s)).", view=None
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)

    @discord.ui.button(label="Clear Roles", emoji="🧹", style=discord.ButtonStyle.danger, row=1)
    async def ClearRoles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager, administratorOnly=True):
            return
        db = self.databaseManager.ForServer(interaction.guild_id)
        db.SetSetting("dashboard_moderator_role_ids", "")
        await interaction.response.defer()
        await interaction.edit_original_response(
            content="✅ Moderator roles cleared. Only server Administrators can use the dashboard now.", view=None
        )
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)


class TicketStaffRolePicker(discord.ui.RoleSelect):
    def __init__(self, defaultRole: discord.Role | None):
        super().__init__(
            placeholder="Choose the baseline ticket staff role",
            min_values=0,
            max_values=1,
            default_values=[defaultRole] if defaultRole is not None else [],
            custom_id="bf:dashboard:ticket_staff_role_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, TicketStaffRoleView):
            await SendEphemeralResponse(interaction, "This selector has expired. Reopen it from the dashboard.", ephemeral=True)
            return
        if not await EnsureDashboardAccess(interaction, view.databaseManager):
            return
        if not self.values:
            view.selectedRoleId = None
            await interaction.response.edit_message(
                content="No baseline role selected. Use **Clear Baseline** to remove ticket staff access, or select a role.",
                view=view,
            )
            return
        role = self.values[0]
        if role.is_default() or role.managed:
            await SendEphemeralResponse(interaction, "Choose a normal server role, not @everyone or an integration-managed role.", ephemeral=True)
            return
        view.selectedRoleId = role.id
        await interaction.response.edit_message(
            content=f"Selected baseline: {role.mention}. Press **Apply Role** to update new and open tickets.",
            view=view,
        )


class TicketStaffRoleView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager, currentRoleId: int | None, guild: discord.Guild):
        super().__init__(timeout=180)
        self.databaseManager = databaseManager
        self.selectedRoleId = currentRoleId
        self.add_item(TicketStaffRolePicker(guild.get_role(currentRoleId) if currentRoleId else None))

    async def _Apply(self, interaction: discord.Interaction, roleId: int | None) -> None:
        db = self.databaseManager.ForServer(interaction.guild_id)
        if roleId is not None:
            role = interaction.guild.get_role(roleId)
            if role is None or role.is_default() or role.managed:
                await SendEphemeralResponse(interaction, "That role is no longer available. Choose a current server role.", ephemeral=True)
                return
        db.SetSetting("ticket_staff_role_baseline_id", roleId or "")
        await interaction.response.defer()
        updatedCount, failedChannels = await ApplyTicketStaffRolePolicy(interaction.guild, db)
        if failedChannels:
            result = (
                f"⚠️ Saved the ticket staff role policy, but could not update {len(failedChannels)} open ticket channel(s). "
                "Use Refresh Dashboard to retry. New tickets will use the saved role policy."
            )
        elif roleId is None:
            result = f"✅ Ticket staff access cleared. Updated {updatedCount} open ticket channel(s); future tickets are accessible only to participants, bot, and server Administrators."
        else:
            result = f"✅ Ticket staff access updated to {interaction.guild.get_role(roleId).mention} and roles above it. Updated {updatedCount} open ticket channel(s)."
        await interaction.edit_original_response(content=result, view=None)
        await RefreshDashboardMessage(interaction.guild, db, self.databaseManager)

    @discord.ui.button(label="Apply Role", emoji="✅", style=discord.ButtonStyle.success, row=1)
    async def ApplyRole(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        if not self.selectedRoleId:
            await SendEphemeralResponse(interaction, "Choose a baseline role in the menu first.", ephemeral=True)
            return
        await self._Apply(interaction, self.selectedRoleId)

    @discord.ui.button(label="Clear Baseline", emoji="🧹", style=discord.ButtonStyle.danger, row=1)
    async def ClearBaseline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await EnsureDashboardAccess(interaction, self.databaseManager):
            return
        await self._Apply(interaction, None)


async def CreateOrUpdateDashboard(
    guild: discord.Guild,
    targetChannel: discord.TextChannel,
    databaseManager: DatabaseManager,
) -> tuple[discord.TextChannel, discord.Message]:
    guildDatabase = databaseManager.ForServer(guild.id)
    return await _CreateOrUpdateDashboard(guild, targetChannel, guildDatabase, databaseManager)


async def SetupDashboardViews(bot: discord.Client, databaseManager: DatabaseManager) -> None:
    """Register the dashboard's persistent button view after every restart."""
    bot.add_view(DashboardView(databaseManager))


async def RestoreSavedDashboardMessage(guild: discord.Guild, databaseManager: DatabaseManager) -> None:
    """Reattach the saved dashboard view and recreate the dashboard message if it was deleted."""
    db = databaseManager.ForServer(guild.id)
    try:
        channelId = int(db.GetSetting("dashboard_channel_id", "") or 0)
        messageId = int(db.GetSetting("dashboard_message_id", "") or 0)
    except (TypeError, ValueError):
        return
    channel = guild.get_channel(channelId) if channelId else None
    if not isinstance(channel, discord.TextChannel):
        # Do not silently create a new private channel on every gateway reconnect. An
        # Administrator can run `/setup admin_dashboard` in the desired text channel to repair the dashboard.
        return
    try:
        if messageId:
            message = await channel.fetch_message(messageId)
            await message.edit(embed=BuildDashboardEmbed(guild, db), view=DashboardView(databaseManager))
            return
    except discord.NotFound:
        pass
    except discord.HTTPException:
        logger.exception("Could not restore dashboard message in guild %s", guild.id)
        return
    message = await channel.send(embed=BuildDashboardEmbed(guild, db), view=DashboardView(databaseManager))
    db.SetSetting("dashboard_message_id", message.id)
