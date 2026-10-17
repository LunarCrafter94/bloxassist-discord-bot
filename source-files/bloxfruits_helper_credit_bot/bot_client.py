"""Discord bot setup, gateway events, and slash-command registration."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from .admin.dashboard_views import (
    CreateOrUpdateDashboard,
    GetDashboardModeratorRoleIds,
    RestoreSavedDashboardMessage,
)
from .credits.credit_service import CreditService
from .interaction_utils import DeferEphemeralResponse, EditEphemeralOriginalResponse, SendEphemeralFollowup, SendEphemeralResponse
from .database import DatabaseManager
from .settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES, RuntimeSettings
from .tickets.ticket_views import (
    CancelUserTicket,
    CompleteCurrentTicket,
    DisableResolutionPromptById,
    EditTicketWorkflowMessage,
    ReplacementRequestView,
    PostOrUpdateHelpCenterPanel,
    RefundCurrentTicket,
    SetupViews,
)

logger = logging.getLogger(__name__)



def IsServerOwner(interaction: discord.Interaction) -> bool:
    """Credit adjustments are a server-owner-only capability."""
    return bool(
        interaction.guild is not None
        and interaction.user.id == interaction.guild.owner_id
    )


def HasConfiguredStaffAccess(interaction: discord.Interaction, databaseManager: DatabaseManager) -> bool:
    """Owner, Administrator, and dashboard-configured moderator roles are trusted staff. Manage Server alone does not grant moderator access."""
    guild = interaction.guild
    if guild is None or interaction.guild_id is None:
        return False
    if interaction.user.id == guild.owner_id:
        return True
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions and permissions.administrator:
        return True
    db = databaseManager.ForServer(interaction.guild_id)
    allowedRoleIds = set(GetDashboardModeratorRoleIds(db))
    userRoleIds = {role.id for role in getattr(interaction.user, "roles", ())}
    return bool(allowedRoleIds.intersection(userRoleIds))


def CreateBot(settings: RuntimeSettings) -> discord.Client:
    """Create a bot instance wired to a guild-aware database manager."""
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True

    databaseManager = DatabaseManager(
        dataDir=settings.projectRoot / "data",
        defaultJoinCredits=DEFAULT_JOIN_CREDITS,
        defaultServices=DEFAULT_SERVICES,
    )
    creditService = CreditService(databaseManager)

    class CreditBot(discord.Client):
        def __init__(self) -> None:
            # This bot uses application/slash commands only. A plain Client avoids
            # enabling the privileged Message Content Intent for unused prefix commands.
            super().__init__(intents=intents)
            self.tree = app_commands.CommandTree(self)

        async def setup_hook(self) -> None:
            await SetupViews(self, databaseManager)

            if settings.commandGuildId is not None:
                commandGuild = discord.Object(id=settings.commandGuildId)
                self.tree.copy_global_to(guild=commandGuild)
                syncedCommands = await self.tree.sync(guild=commandGuild)
                logger.info(
                    "Synced %s slash commands to guild %s",
                    len(syncedCommands), settings.commandGuildId,
                )
            else:
                syncedCommands = await self.tree.sync()
                logger.info("Synced %s global slash commands", len(syncedCommands))
            self.resolutionExpiryTask = asyncio.create_task(self.ResolutionExpiryLoop())

        async def ResolutionExpiryLoop(self) -> None:
            """Expire unconfirmed completion/cancellation proposals after 15 minutes."""
            await self.wait_until_ready()
            while not self.is_closed():
                for guild in list(self.guilds):
                    try:
                        guildDatabase = databaseManager.ForServer(guild.id)
                        expiredTickets = guildDatabase.ExpireStaleResolutionRequests(15)
                        for ticketId, channelId, resolutionType, resolutionMessageId in expiredTickets:
                            channel = guild.get_channel(channelId) if channelId else None
                            if isinstance(channel, discord.TextChannel):
                                try:
                                    await DisableResolutionPromptById(
                                        channel,
                                        resolutionMessageId,
                                        f"⌛ The proposed {resolutionType} request for ticket #{ticketId} expired after 15 minutes. No credits were paid or refunded. The requester may submit a new proposal.",
                                    )
                                    await channel.send(
                                        f"⌛ The proposed {resolutionType} request for ticket #{ticketId} expired after 15 minutes without every active helper confirming. No credits were paid or refunded. The requester may submit a new request; staff can use an override command."
                                    )
                                except discord.HTTPException:
                                    logger.exception(
                                        "Could not post resolution-expiry notice: guild=%s ticket=%s channel=%s",
                                        guild.id, ticketId, channelId,
                                    )
                            logger.info(
                                "Expired ticket resolution request: guild=%s ticket=%s type=%s",
                                guild.id, ticketId, resolutionType,
                            )
                    except Exception:
                        logger.exception("Could not expire stale ticket requests for guild %s", guild.id)
                await asyncio.sleep(60)

        async def close(self) -> None:
            task = getattr(self, "resolutionExpiryTask", None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            try:
                await super().close()
            finally:
                databaseManager.CloseAll()

        async def on_ready(self) -> None:
            logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")
            logger.info("Per-server database directory: %s", settings.projectRoot / "data" / "servers")
            # Persistent views are registered in setup_hook. Refresh saved messages as well,
            # recreating a deleted panel when its configured channel still exists.
            for guild in self.guilds:
                try:
                    await RestoreSavedDashboardMessage(guild, databaseManager)
                    from .tickets.ticket_views import RefreshHelpCenterPanel, RefreshOpenTicketViews
                    await RefreshHelpCenterPanel(guild, databaseManager)
                    await RefreshOpenTicketViews(guild, databaseManager)
                except Exception:
                    logger.exception("Could not restore saved bot panels for guild %s", guild.id)

        async def on_disconnect(self) -> None:
            logger.warning("Discord Gateway disconnected; waiting for reconnection.")

        async def on_resumed(self) -> None:
            logger.info("Discord Gateway session resumed.")

        async def on_guild_join(self, guild: discord.Guild) -> None:
            # Create/seed this server's database as soon as the bot joins it.
            databaseManager.ForServer(guild.id)
            logger.info("Initialized database for newly joined guild %s (%s)", guild.name, guild.id)

        async def on_member_join(self, member: discord.Member) -> None:
            guildDatabase = databaseManager.ForServer(member.guild.id)
            startingCredits = guildDatabase.GetDefaultJoinCredits()
            accountCreated = guildDatabase.CreateUser(member.id, startingCredits)
            if accountCreated:
                logger.info(
                    "Created member account: guild=%s member=%s starting_credits=%s",
                    member.guild.id, member.id, startingCredits,
                )

    bot = CreditBot()

    @bot.tree.command(name="balance", description="Check your credits in this server.")
    @app_commands.guild_only()
    async def Balance(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, 
                "This command must be used inside a server.", ephemeral=True
            )
            return
        amount = creditService.GetBalance(interaction.guild_id, interaction.user.id)
        await SendEphemeralResponse(interaction, 
            f"💰 You have **{amount:,} credits** in this server.", ephemeral=True
        )

    @bot.tree.command(name="credits", description="Check another member's credits in this server.")
    @app_commands.describe(member="The member whose credits you want to check")
    @app_commands.guild_only()
    async def Credits(interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, 
                "This command must be used inside a server.", ephemeral=True
            )
            return
        amount = creditService.GetBalance(interaction.guild_id, member.id)
        await SendEphemeralResponse(interaction, 
            f"💰 {member.mention} has **{amount:,} credits** in this server.", ephemeral=True
        )

    setupGroup = app_commands.Group(
        name="setup",
        description="Set up the public ticket panel or admin dashboard.",
    )

    @setupGroup.command(
        name="public_tickets",
        description="Post or update the public Help Center panel in this channel.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def SetupPublicPanel(interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, 
                "This command must be used in a server text channel.", ephemeral=True
            )
            return
        if not interaction.user.guild_permissions.administrator:
            await SendEphemeralResponse(interaction, 
                "Only server Administrators can use `/setup public_tickets`.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await SendEphemeralResponse(interaction, 
                "Use `/setup public_tickets` in a normal text channel (not a thread or voice channel).",
                ephemeral=True,
            )
            return

        await DeferEphemeralResponse(interaction, thinking=True)
        try:
            databaseManager.ForServer(interaction.guild_id)
            panelMessage, wasUpdated = await PostOrUpdateHelpCenterPanel(
                interaction.guild, interaction.channel, databaseManager
            )
        except PermissionError as error:
            await SendEphemeralFollowup(interaction, 
                f"❌ I cannot use this channel. {error} Give the bot View Channel, Send Messages, Embed Links, and Read Message History permissions.",
                ephemeral=True,
            )
            return
        except discord.Forbidden:
            await SendEphemeralFollowup(interaction, 
                "❌ Discord denied access to this channel. Check the bot's channel permissions.",
                ephemeral=True,
            )
            return
        except Exception:
            logger.exception("Failed to post Help Center panel for guild %s", interaction.guild_id)
            await SendEphemeralFollowup(interaction, 
                "❌ I couldn't post or update the Help Center panel. Check the bot's permissions and logs.",
                ephemeral=True,
            )
            return

        actionText = "updated" if wasUpdated else "posted"
        await SendEphemeralFollowup(interaction, 
            f"✅ Help Center panel {actionText} in {interaction.channel.mention} (message `{panelMessage.id}`).",
            ephemeral=True,
        )

    @setupGroup.command(
        name="admin_dashboard",
        description="Post or update the admin dashboard in this channel.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def AdminDashboard(interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, 
                "This command can only be used inside a server.", ephemeral=True
            )
            return
        if not interaction.user.guild_permissions.administrator:
            await SendEphemeralResponse(interaction, 
                "Only server Administrators can use `/setup admin_dashboard`.", ephemeral=True
            )
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await SendEphemeralResponse(interaction, 
                "Use `/setup admin_dashboard` in a normal text channel (not a thread or voice channel).",
                ephemeral=True,
            )
            return

        await DeferEphemeralResponse(interaction, thinking=True)
        try:
            dashboardChannel, dashboardMessage = await CreateOrUpdateDashboard(
                interaction.guild, interaction.channel, databaseManager
            )
        except PermissionError as error:
            await SendEphemeralFollowup(interaction, f"❌ {error}", ephemeral=True)
            return
        except discord.Forbidden:
            await SendEphemeralFollowup(interaction, 
                "❌ Discord denied access to this channel. Check the bot's channel permissions.",
                ephemeral=True,
            )
            return
        except Exception:
            logger.exception("Failed to post/update admin dashboard in guild %s", interaction.guild_id)
            await SendEphemeralFollowup(interaction, 
                "❌ I couldn't post or update the admin dashboard. Check the bot's permissions and logs.",
                ephemeral=True,
            )
            return

        await SendEphemeralFollowup(interaction, 
            f"✅ Admin dashboard posted or updated in {dashboardChannel.mention} (message `{dashboardMessage.id}`). "
            "For privacy, use a staff-only channel. Dashboard actions still check your configured staff permissions.",
            ephemeral=True,
        )

    bot.tree.add_command(setupGroup)

    @bot.tree.command(name="cancel_ticket", description="Cancel one of your active tickets in this server.")
    @app_commands.guild_only()
    async def CancelTicket(interaction: discord.Interaction) -> None:
        await CancelUserTicket(interaction, databaseManager)

    @bot.tree.command(name="complete_ticket", description="Complete the current help ticket.")
    @app_commands.guild_only()
    async def CompleteTicket(interaction: discord.Interaction) -> None:
        await CompleteCurrentTicket(interaction, databaseManager)

    @bot.tree.command(name="admin_complete", description="Admin: complete the current ticket.")
    @app_commands.guild_only()
    async def AdminComplete(interaction: discord.Interaction) -> None:
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, 
                "You need Administrator or a configured moderator role.", ephemeral=True
            )
            return
        await CompleteCurrentTicket(interaction, databaseManager, admin=True)

    @bot.tree.command(name="admin_refund", description="Admin: refund the current ticket.")
    @app_commands.guild_only()
    async def AdminRefund(interaction: discord.Interaction) -> None:
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, 
                "You need Administrator or a configured moderator role.", ephemeral=True
            )
            return
        await RefundCurrentTicket(interaction, databaseManager)

    @bot.tree.command(name="add", description="Server owner only: add credits to a member with an audit record.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(member="Member receiving credits", amount="Positive number of credits", reason="Why these credits are being added (optional)")
    async def AddCredits(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str | None = None) -> None:
        if interaction.guild_id is None or interaction.guild is None:
            await SendEphemeralResponse(interaction, "This command must be used inside a server.", ephemeral=True)
            return
        if not IsServerOwner(interaction):
            await SendEphemeralResponse(interaction, "Only this Discord server's owner can use `/add`. Configured moderators and other Administrators cannot adjust balances.", ephemeral=True)
            return
        guildDatabase = databaseManager.ForServer(interaction.guild_id)
        if guildDatabase.IsUserParticipantInAnyOpenTicket(interaction.user.id):
            await SendEphemeralResponse(interaction, "Credit moderation is disabled while you're the requester, an original/current helper, or a selected replacement in any open ticket. Wait until your ticket is resolved.", ephemeral=True)
            return
        if isinstance(amount, bool) or amount <= 0 or amount > 1_000_000_000:
            await SendEphemeralResponse(interaction, "Amount must be a whole number between 1 and 1,000,000,000.", ephemeral=True)
            return
        if member.bot:
            await SendEphemeralResponse(interaction, "Credits cannot be adjusted for bot accounts.", ephemeral=True)
            return
        await DeferEphemeralResponse(interaction, thinking=True)
        db = databaseManager.ForServer(interaction.guild_id)
        try:
            status, newBalance = db.ApplyCreditAdjustment(
                member.id, amount, direction="add", actorUserId=interaction.user.id,
                note=reason, idempotencyKey=f"slash-add:{interaction.id}",
            )
        except Exception:
            logger.exception("Credit addition failed: guild=%s actor=%s target=%s", interaction.guild_id, interaction.user.id, member.id)
            await EditEphemeralOriginalResponse(interaction, content="The credit addition failed. No success was recorded; check the transaction ledger before retrying.")
            return
        if status != "added" or newBalance is None:
            await EditEphemeralOriginalResponse(interaction, content=f"Credit addition was not applied (status: {status}).")
            return
        await EditEphemeralOriginalResponse(interaction, content=f"✅ Added **{amount:,} credits** to {member.mention}. New balance: **{newBalance:,}**.\nReason: {reason.strip() if reason and reason.strip() else 'Not provided'}")
        logger.info("Server-owner credit add: guild=%s actor=%s target=%s amount=%s reason=%r", interaction.guild_id, interaction.user.id, member.id, amount, reason)

    @bot.tree.command(name="deduct", description="Server owner only: deduct credits from a member with an audit record.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(member="Member losing credits", amount="Positive number of credits", reason="Why these credits are being deducted (optional)")
    async def DeductCredits(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str | None = None) -> None:
        if interaction.guild_id is None or interaction.guild is None:
            await SendEphemeralResponse(interaction, "This command must be used inside a server.", ephemeral=True)
            return
        if not IsServerOwner(interaction):
            await SendEphemeralResponse(interaction, "Only this Discord server's owner can use `/deduct`. Configured moderators and other Administrators cannot adjust balances.", ephemeral=True)
            return
        guildDatabase = databaseManager.ForServer(interaction.guild_id)
        if guildDatabase.IsUserParticipantInAnyOpenTicket(interaction.user.id):
            await SendEphemeralResponse(interaction, "Credit moderation is disabled while you're the requester, an original/current helper, or a selected replacement in any open ticket. Wait until your ticket is resolved.", ephemeral=True)
            return
        if isinstance(amount, bool) or amount <= 0 or amount > 1_000_000_000:
            await SendEphemeralResponse(interaction, "Amount must be a whole number between 1 and 1,000,000,000.", ephemeral=True)
            return
        if member.bot:
            await SendEphemeralResponse(interaction, "Credits cannot be adjusted for bot accounts.", ephemeral=True)
            return
        await DeferEphemeralResponse(interaction, thinking=True)
        db = databaseManager.ForServer(interaction.guild_id)
        try:
            status, newBalance = db.ApplyCreditAdjustment(
                member.id, amount, direction="deduct", actorUserId=interaction.user.id,
                note=reason, idempotencyKey=f"slash-deduct:{interaction.id}",
            )
        except Exception:
            logger.exception("Credit deduction failed: guild=%s actor=%s target=%s", interaction.guild_id, interaction.user.id, member.id)
            await EditEphemeralOriginalResponse(interaction, content="The credit deduction failed. No success was recorded; check the transaction ledger before retrying.")
            return
        if status == "insufficient":
            await EditEphemeralOriginalResponse(interaction, content=f"❌ {member.mention} only has **{newBalance or 0:,} credits**. No credits were deducted.")
            return
        if status != "deducted" or newBalance is None:
            await EditEphemeralOriginalResponse(interaction, content=f"Credit deduction was not applied (status: {status}).")
            return
        await EditEphemeralOriginalResponse(interaction, content=f"✅ Deducted **{amount:,} credits** from {member.mention}. New balance: **{newBalance:,}**.\nReason: {reason.strip() if reason and reason.strip() else 'Not provided'}")
        logger.info("Server-owner credit deduct: guild=%s actor=%s target=%s amount=%s reason=%r", interaction.guild_id, interaction.user.id, member.id, amount, reason)

    replacementAdminGroup = app_commands.Group(
        name="admin_helper-replace",
        description="Approve or disapprove the replacement helpers selected by a ticket requester.",
    )

    @replacementAdminGroup.command(name="approve", description="Approve the requester-selected replacement helpers in this ticket.")
    @app_commands.guild_only()
    async def AdminHelperReplaceApprove(interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id is None or not isinstance(interaction.channel, discord.TextChannel):
            await SendEphemeralResponse(interaction, "Use this command inside the ticket with a pending replacement request.", ephemeral=True)
            return
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "You are not authorized to approve replacement helpers.", ephemeral=True)
            return
        await DeferEphemeralResponse(interaction, thinking=True)
        db = databaseManager.ForServer(interaction.guild_id)
        ticket = db.GetTicketByChannel(interaction.channel.id)
        if ticket is None or ticket["status"] != "open":
            await EditEphemeralOriginalResponse(interaction, content="This is not an open ticket channel.")
            return
        ticketId = int(ticket["ticket_id"])
        if db.IsUserTicketParticipant(ticketId, interaction.user.id):
            await EditEphemeralOriginalResponse(interaction, content="You cannot approve or disapprove replacement helpers for a ticket you are involved in. A configured staff member outside this ticket must decide.")
            return
        candidateIds = db.GetReplacementCandidateIds(ticketId)
        if int(ticket["replacement_requested"] or 0) != 1 or not candidateIds:
            await EditEphemeralOriginalResponse(interaction, content="There is no requester-selected replacement list waiting for approval in this ticket.")
            return

        botMember = interaction.guild.me
        if botMember is None and interaction.client.user is not None:
            botMember = interaction.guild.get_member(interaction.client.user.id)
        if botMember is None:
            await EditEphemeralOriginalResponse(interaction, content="I couldn't verify my server membership. No replacements were added.")
            return
        effectivePermissions = interaction.channel.permissions_for(botMember)
        # Channel permission overwrite edits require MANAGE_ROLES. MANAGE_CHANNELS
        # remains needed for channel creation/deletion, but is not sufficient here.
        if not effectivePermissions.manage_roles:
            logger.error(
                "Replacement approval permission preflight failed: guild=%s channel=%s bot=%s "
                "effective_manage_roles=%s guild_manage_roles=%s effective_manage_channels=%s "
                "guild_manage_channels=%s category=%s",
                interaction.guild_id, interaction.channel.id, botMember.id,
                effectivePermissions.manage_roles, botMember.guild_permissions.manage_roles,
                effectivePermissions.manage_channels, botMember.guild_permissions.manage_channels,
                interaction.channel.category_id,
            )
            await EditEphemeralOriginalResponse(
                interaction,
                content=("I cannot apply replacement permissions in this ticket. Discord requires Manage Roles "
                         "to edit channel permission overwrites; Manage Channels alone is not sufficient. Enable "
                         "Manage Roles for the bot role and ensure it is not denied by ticket/category overrides. "
                         "No roster or credit changes were made."),
            )
            return

        candidateMembers: list[discord.Member] = []
        for candidateId in candidateIds:
            member = interaction.guild.get_member(candidateId)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(candidateId)
                except discord.HTTPException:
                    member = None
            if member is None or member.bot:
                await EditEphemeralOriginalResponse(
                    interaction,
                    content=f"Selected candidate `{candidateId}` is no longer a current human member. No replacements were added; ask the requester to submit a fresh selection.",
                )
                return
            candidateMembers.append(member)

        previousOverwrites: dict[int, tuple[discord.Member, discord.PermissionOverwrite]] = {}
        appliedMembers: list[discord.Member] = []
        try:
            for member in candidateMembers:
                previousOverwrite = interaction.channel.overwrites_for(member)
                previousOverwrites[member.id] = (member, previousOverwrite)
                await interaction.channel.set_permissions(
                    member,
                    overwrite=discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                    reason=f"Staff approved requester-selected replacement for ticket {ticketId}",
                )
                appliedMembers.append(member)
        except discord.HTTPException as error:
            logger.exception(
                "Could not set replacement helper overwrite: guild=%s ticket=%s channel=%s status=%s discord_code=%s "
                "effective_manage_roles=%s guild_manage_roles=%s effective_manage_channels=%s guild_manage_channels=%s",
                interaction.guild_id, ticketId, interaction.channel.id,
                getattr(error, "status", None), getattr(error, "code", None),
                effectivePermissions.manage_roles, botMember.guild_permissions.manage_roles,
                effectivePermissions.manage_channels, botMember.guild_permissions.manage_channels,
            )
            for member in reversed(appliedMembers):
                previousOverwrite = previousOverwrites[member.id][1]
                try:
                    await interaction.channel.set_permissions(
                        member,
                        overwrite=None if previousOverwrite.is_empty() else previousOverwrite,
                        reason="Rollback failed replacement approval",
                    )
                except discord.HTTPException:
                    logger.exception("Rollback failed for candidate %s in channel %s", member.id, interaction.channel.id)
            await EditEphemeralOriginalResponse(
                interaction,
                content=(f"Discord refused to update replacement permissions (error code {getattr(error, 'code', 'unknown')}). "
                         "No roster or credit changes were made. Discord requires Manage Roles to edit channel permission "
                         "overwrites; Manage Channels alone is not sufficient. Check effective Manage Roles in this ticket "
                         "and category; the full error is logged in the terminal."),
            )
            return

        try:
            status, appliedIds, activeIds = db.ApplyReplacementCandidates(ticketId, interaction.user.id, candidateIds)
        except Exception:
            logger.exception("Could not commit requester-selected replacements: guild=%s ticket=%s", interaction.guild_id, ticketId)
            status, appliedIds, activeIds = "database_error", [], []
        if status != "added":
            for member in reversed(appliedMembers):
                previousOverwrite = previousOverwrites[member.id][1]
                try:
                    await interaction.channel.set_permissions(
                        member,
                        overwrite=None if previousOverwrite.is_empty() else previousOverwrite,
                        reason="Rollback replacement permissions because the database did not approve roster update",
                    )
                except discord.HTTPException:
                    logger.exception("Could not roll back candidate permissions for %s", member.id)
            await EditEphemeralOriginalResponse(interaction, content=f"The replacement roster was not changed (status: {status}). Candidate permissions were rolled back where possible; no credits were moved.")
            return

        await DisableResolutionPromptById(
            interaction.channel, ticket["resolution_message_id"],
            "ℹ️ The helper roster changed, so the earlier resolution proposal was cancelled. No credits were moved; the requester may submit a new proposal.",
        )
        await EditTicketWorkflowMessage(
            interaction.channel, ticket["replacement_request_message_id"],
            f"✅ Staff member {interaction.user.mention} approved the requester-selected replacement helpers: {', '.join(f'<@{item}>' for item in appliedIds)}. Active helpers are now {', '.join(f'<@{item}>' for item in activeIds)}. The original reserved price is unchanged.",
        )
        await interaction.channel.send(
            f"✅ Staff member {interaction.user.mention} approved replacement helper(s): "
            f"{', '.join(f'<@{item}>' for item in appliedIds)}. The original reserved price is unchanged."
        )
        await EditEphemeralOriginalResponse(interaction, content=f"✅ Approved all requester-selected replacement helper(s): {', '.join(f'<@{item}>' for item in appliedIds)}.")
        logger.info("Staff approved requester-selected replacements: guild=%s ticket=%s actor=%s candidates=%s", interaction.guild_id, ticketId, interaction.user.id, candidateIds)

    @replacementAdminGroup.command(name="disapprove", description="Reject the requester-selected replacement helpers in this ticket.")
    @app_commands.guild_only()
    async def AdminHelperReplaceDisapprove(interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id is None or not isinstance(interaction.channel, discord.TextChannel):
            await SendEphemeralResponse(interaction, "Use this command inside the ticket with a pending replacement request.", ephemeral=True)
            return
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "You are not authorized to disapprove replacement helpers.", ephemeral=True)
            return
        await DeferEphemeralResponse(interaction, thinking=True)
        db = databaseManager.ForServer(interaction.guild_id)
        ticket = db.GetTicketByChannel(interaction.channel.id)
        if ticket is None or ticket["status"] != "open":
            await EditEphemeralOriginalResponse(interaction, content="This is not an open ticket channel.")
            return
        ticketId = int(ticket["ticket_id"])
        if db.IsUserTicketParticipant(ticketId, interaction.user.id):
            await EditEphemeralOriginalResponse(interaction, content="You cannot approve or disapprove replacement helpers for a ticket you are involved in. A configured staff member outside this ticket must decide.")
            return
        if int(ticket["replacement_requested"] or 0) != 1 or not db.GetReplacementCandidateIds(ticketId):
            await EditEphemeralOriginalResponse(interaction, content="There is no requester-selected replacement list waiting for a decision in this ticket.")
            return
        status, candidateIds = db.DisapproveReplacementRequest(ticketId, interaction.user.id)
        if status != "disapproved":
            await EditEphemeralOriginalResponse(interaction, content=f"Replacement request could not be disapproved (status: {status}).")
            return
        await EditTicketWorkflowMessage(
            interaction.channel, ticket["replacement_request_message_id"],
            f"❌ Staff member {interaction.user.mention} disapproved the requested replacements ({', '.join(f'<@{item}>' for item in candidateIds)}). No roster changes, access changes, or credit movements were made.",
        )
        originalCount = len(db._ParseIdCsv(str(ticket["helper_ids"])))
        activeIds = db._ParseIdCsv(str(ticket["active_helper_ids"]))
        if originalCount > 1 and len(activeIds) == 1:
            retryButton = await interaction.channel.send(
                content=f"<@{ticket['creator_id']}> Staff disapproved the previous replacement selection. You may choose new replacement helper(s) below; the reserved price remains unchanged.",
                view=ReplacementRequestView(databaseManager),
            )
            db.SetReplacementButtonMessageId(ticketId, retryButton.id)
        await EditEphemeralOriginalResponse(interaction, content="Replacement request disapproved. The active helper roster and all balances remain unchanged.")
        logger.info("Staff disapproved requester-selected replacements: guild=%s ticket=%s actor=%s candidates=%s", interaction.guild_id, ticketId, interaction.user.id, candidateIds)

    bot.tree.add_command(replacementAdminGroup)

    return bot
