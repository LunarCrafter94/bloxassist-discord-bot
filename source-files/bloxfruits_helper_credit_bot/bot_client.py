"""Discord bot setup, gateway events, and slash-command registration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands

from .admin.dashboard_views import (
    CreateOrUpdateDashboard,
    GetDashboardModeratorRoleIds,
    RestoreSavedDashboardMessage,
)
from .credits.credit_service import CreditService
from .audit import ResolveAuditChannel, SendAuditLog
from .invites.invite_events import FetchInviteUseCounts, FindUsedInvite
from .backups import PerServerBackupService
from .interaction_utils import DeferEphemeralResponse, EditEphemeralOriginalResponse, SendEphemeralFollowup, SendEphemeralResponse
from .database import DatabaseManager
from .settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES, RuntimeSettings
from .ticket_numbers import TicketLabelFromRow
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


def CanViewMemberCreditDebt(
    interaction: discord.Interaction,
    targetUserId: int,
    databaseManager: DatabaseManager,
) -> bool:
    """Allow members to see their own debt and configured staff to see another member's debt."""
    if interaction.guild is None or interaction.guild_id is None:
        return False
    if int(interaction.user.id) == int(targetUserId):
        return True
    return HasConfiguredStaffAccess(interaction, databaseManager)


def CreateBot(settings: RuntimeSettings) -> discord.Client:
    """Create a bot instance wired to a guild-aware database manager."""
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    # Ticket transcripts must include user-authored message text. This privileged
    # intent must also be enabled in the Discord Developer Portal for the bot.
    intents.message_content = True

    databaseManager = DatabaseManager(
        dataDir=settings.projectRoot / "data",
        defaultJoinCredits=DEFAULT_JOIN_CREDITS,
        defaultServices=DEFAULT_SERVICES,
        backend=settings.databaseBackend,
        databaseUrl=settings.databaseUrl,
    )
    creditService = CreditService(databaseManager)

    class CreditBot(discord.Client):
        def __init__(self) -> None:
            # This bot uses application/slash commands only. A plain Client avoids
            # enabling the privileged Message Content Intent for unused prefix commands.
            super().__init__(intents=intents)
            self.tree = app_commands.CommandTree(self)
            self.inviteUsage: dict[int, dict[str, int]] = {}
            self.backupService = PerServerBackupService(
                databaseManager,
                recipientUserId=settings.backupUserId,
                encryptionPassword=settings.backupEncryptionPassword,
            )
            self.backupTask: asyncio.Task | None = None
            self._closeStarted = False
            self._startupStatusNotified: set[int] = set()

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
            if settings.backupUserId and settings.backupEncryptionPassword:
                self.backupTask = asyncio.create_task(self.backupService.HourlyLoop(self))
                logger.info("Per-server encrypted database backups enabled; recipient ID=%s", settings.backupUserId)
            else:
                logger.warning("Automated DM backups are disabled: set BACKUP_DISCORD_USER_ID and BACKUP_ENCRYPTION_PASSWORD in private-configs/credentials.env or hosting secrets.")

        async def ResolutionExpiryLoop(self) -> None:
            """Expire unconfirmed completion/cancellation proposals after 15 minutes."""
            await self.wait_until_ready()
            while not self.is_closed():
                for guild in list(self.guilds):
                    try:
                        guildDatabase = databaseManager.ForServer(guild.id)
                        expiredInviteEvent = guildDatabase.ExpireInviteEventIfDue()
                        if expiredInviteEvent is not None:
                            eventEmbed = discord.Embed(
                                title="⏰ Invite reward event expired",
                                description=f"Invite event #{int(expiredInviteEvent['event_id'])} expired automatically. New joins will no longer earn rewards from that event.",
                                color=discord.Color.orange(), timestamp=discord.utils.utcnow(),
                            )
                            await SendAuditLog(guild, guildDatabase, eventEmbed)
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
            if self._closeStarted:
                return
            self._closeStarted = True
            task = getattr(self, "resolutionExpiryTask", None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            backupTask = getattr(self, "backupTask", None)
            if backupTask is not None:
                backupTask.cancel()
                try:
                    await backupTask
                except asyncio.CancelledError:
                    pass
                try:
                    await self.backupService.BackupAllServers(self)
                except Exception:
                    logger.exception("Final graceful-shutdown backup failed")
            # A forced process kill may skip this entirely. When the host sends
            # SIGTERM or an Administrator closes the client cleanly, leave a
            # status entry in each server's configured audit channel.
            for guild in list(self.guilds):
                try:
                    guildDatabase = databaseManager.ForServer(guild.id)
                    if not (guildDatabase.GetSetting("audit_log_channel_id", "") or "").strip():
                        continue
                    statusEmbed = discord.Embed(
                        title="⏹️ BloxAssist is shutting down",
                        description="The bot received a graceful shutdown request and is closing its Discord connection.",
                        color=discord.Color.orange(), timestamp=discord.utils.utcnow(),
                    )
                    await SendAuditLog(guild, guildDatabase, statusEmbed)
                except Exception:
                    logger.exception("Could not post graceful-shutdown status: guild=%s", guild.id)
            try:
                await super().close()
            finally:
                databaseManager.CloseAll()

        async def on_ready(self) -> None:
            logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")
            logger.info("Per-server database directory: %s", settings.projectRoot / "data" / "servers" if settings.databaseBackend == "sqlite" else "PostgreSQL per-server schemas")
            # Restore invite-use snapshots on each gateway ready/resume. Attribution is
            # intentionally skipped when the initial uses snapshot is unavailable.
            for guild in self.guilds:
                try:
                    inviteUses = await FetchInviteUseCounts(guild)
                    if inviteUses is not None:
                        self.inviteUsage[guild.id] = inviteUses
                except Exception:
                    logger.exception("Could not initialize invite tracking for guild %s", guild.id)
                try:
                    await RestoreSavedDashboardMessage(guild, databaseManager)
                    from .tickets.ticket_views import RefreshHelpCenterPanel, RefreshOpenTicketViews
                    await RefreshHelpCenterPanel(guild, databaseManager)
                    await RefreshOpenTicketViews(guild, databaseManager)
                except Exception:
                    logger.exception("Could not restore saved bot panels for guild %s", guild.id)
                if guild.id not in self._startupStatusNotified:
                    try:
                        guildDatabase = databaseManager.ForServer(guild.id)
                        if (guildDatabase.GetSetting("audit_log_channel_id", "") or "").strip():
                            statusEmbed = discord.Embed(
                                title="✅ BloxAssist is online",
                                description="The bot connected to Discord and completed its startup ready event.",
                                color=discord.Color.green(), timestamp=discord.utils.utcnow(),
                            )
                            await SendAuditLog(guild, guildDatabase, statusEmbed)
                    except Exception:
                        logger.exception("Could not post startup status: guild=%s", guild.id)
                    finally:
                        # on_ready can run again after a gateway resume; don't send
                        # duplicate status pings for the same process lifetime.
                        self._startupStatusNotified.add(guild.id)

        async def on_disconnect(self) -> None:
            logger.warning("Discord Gateway disconnected; waiting for reconnection.")

        async def on_resumed(self) -> None:
            logger.info("Discord Gateway session resumed.")

        async def on_guild_join(self, guild: discord.Guild) -> None:
            # Create/seed this server's database as soon as the bot joins it.
            databaseManager.ForServer(guild.id)
            inviteUses = await FetchInviteUseCounts(guild)
            if inviteUses is not None:
                self.inviteUsage[guild.id] = inviteUses
            logger.info("Initialized database for newly joined guild %s (%s)", guild.name, guild.id)

        async def on_invite_create(self, invite: discord.Invite) -> None:
            if invite.guild is None:
                return
            inviteUses = await FetchInviteUseCounts(invite.guild)
            if inviteUses is not None:
                self.inviteUsage[invite.guild.id] = inviteUses

        async def on_invite_delete(self, invite: discord.Invite) -> None:
            if invite.guild is None:
                return
            inviteUses = await FetchInviteUseCounts(invite.guild)
            if inviteUses is not None:
                self.inviteUsage[invite.guild.id] = inviteUses

        async def on_member_join(self, member: discord.Member) -> None:
            guildDatabase = databaseManager.ForServer(member.guild.id)
            startingCredits = guildDatabase.GetDefaultJoinCredits()
            accountCreated = guildDatabase.CreateUser(member.id, startingCredits)
            if accountCreated:
                logger.info(
                    "Created member account: guild=%s member=%s starting_credits=%s",
                    member.guild.id, member.id, startingCredits,
                )
            # Attribution requires the Manage Server permission so the bot can read invite use counts.
            previousUses = self.inviteUsage.get(member.guild.id)
            try:
                liveInvites = await member.guild.invites()
                currentUses = {str(invite.code): int(invite.uses or 0) for invite in liveInvites}
                usedInvite = FindUsedInvite(liveInvites, previousUses or {}) if previousUses is not None else None
                self.inviteUsage[member.guild.id] = currentUses
            except discord.Forbidden:
                logger.warning("Invite rewards cannot attribute joins in guild %s; grant Manage Server to the bot if desired", member.guild.id)
                return
            except discord.HTTPException:
                logger.exception("Could not inspect invite uses on member join: guild=%s member=%s", member.guild.id, member.id)
                return
            if usedInvite is None or usedInvite.inviter is None or usedInvite.inviter.bot:
                return
            # Save attribution even outside an active reward event so leave penalties
            # can only ever affect the inviter actually identified for this member.
            guildDatabase.RecordInviteAttribution(member.id, usedInvite.inviter.id, str(usedInvite.code))
            event = guildDatabase.GetActiveInviteEvent()
            if event is None:
                return
            previousDebt = guildDatabase.GetCreditDebt(usedInvite.inviter.id)
            status, newBalance, reward = guildDatabase.AwardInviteReward(
                int(event["event_id"]), member.id, usedInvite.inviter.id, str(usedInvite.code)
            )
            if status == "awarded":
                remainingDebt = guildDatabase.GetCreditDebt(usedInvite.inviter.id)
                debtRepaid = max(0, previousDebt - remainingDebt)
                rewardDescription = f"<@{usedInvite.inviter.id}> earned **{reward:,} credits** for inviting <@{member.id}>."
                if debtRepaid:
                    rewardDescription += f"\\n**{debtRepaid:,} credits** were automatically applied to outstanding debt."
                rewardEmbed = discord.Embed(
                    title="🎟️ Invite reward awarded",
                    description=rewardDescription,
                    color=discord.Color.green(), timestamp=discord.utils.utcnow(),
                )
                rewardEmbed.add_field(name="Invite event", value=f"#{int(event['event_id'])}", inline=True)
                rewardEmbed.add_field(name="New inviter balance", value=f"{int(newBalance or 0):,} credits", inline=True)
                rewardEmbed.add_field(name="Remaining debt", value=f"{remainingDebt:,} credits", inline=True)
                rewardEmbed.add_field(name="Invite code", value=f"`{usedInvite.code}`", inline=True)
                await SendAuditLog(member.guild, guildDatabase, rewardEmbed)
                try:
                    dmText = f"🎟️ You earned **{reward:,} credits** in **{member.guild.name}** for inviting a new member during invite event #{int(event['event_id'])}."
                    if debtRepaid:
                        dmText += f"\\n**{debtRepaid:,} credits** automatically repaid your outstanding debt. Remaining debt: **{remainingDebt:,} credits**."
                    await usedInvite.inviter.send(dmText)
                except discord.HTTPException:
                    logger.info("Could not DM inviter %s about reward in guild %s", usedInvite.inviter.id, member.guild.id)

        async def on_member_remove(self, member: discord.Member) -> None:
            """Apply the configured leave penalty only to this member's recorded inviter."""
            guildDatabase = databaseManager.ForServer(member.guild.id)
            try:
                penalty = int(guildDatabase.GetSetting("invite_leave_penalty_credits", "0") or "0")
            except (TypeError, ValueError):
                logger.error("Invalid invite leave penalty setting in guild %s", member.guild.id)
                return
            if penalty <= 0:
                return
            attribution = guildDatabase.GetInviteAttribution(member.id)
            if attribution is None:
                # No reliable invite attribution means no penalty; never guess or deduct
                # from unrelated members.
                return
            inviterId = int(attribution["inviter_user_id"])
            if inviterId == int(member.id) or (self.user is not None and inviterId == self.user.id):
                return
            try:
                status, balance, debt = guildDatabase.ApplyPenaltyDebt(
                    inviterId,
                    penalty,
                    actorUserId=self.user.id if self.user is not None else member.guild.owner_id,
                    reason=f"Invite penalty: invited member {member.id} left the server (invite {str(attribution['invite_code'])[:80] or 'unknown'})",
                    idempotencyKey=f"invite-leave-penalty:{member.guild.id}:{member.id}",
                )
                if status not in {"penalized", "duplicate"}:
                    logger.warning("Invite leave penalty not applied: guild=%s invited=%s inviter=%s status=%s", member.guild.id, member.id, inviterId, status)
                    return
                guildDatabase.MarkInviteLeavePenaltyApplied(member.id)
                if status == "penalized":
                    embed = discord.Embed(
                        title="⚖️ Inviter leave penalty applied",
                        description=f"Invited member <@{member.id}> left the server. Only their recorded inviter, <@{inviterId}>, was penalized.",
                        color=discord.Color.orange(),
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.add_field(name="Penalty", value=f"{penalty:,} credits", inline=True)
                    embed.add_field(name="Inviter balance", value=f"{int(balance or 0):,} credits", inline=True)
                    embed.add_field(name="Outstanding debt", value=f"{int(debt):,} credits", inline=True)
                    embed.add_field(name="Invite code", value=f"`{str(attribution['invite_code'])[:80] or 'unknown'}`", inline=False)
                    await SendAuditLog(member.guild, guildDatabase, embed)
                    try:
                        inviter = member.guild.get_member(inviterId)
                        if inviter is not None:
                            await inviter.send(
                                f"⚖️ A **{penalty:,}-credit** invite penalty was applied in **{member.guild.name}** "
                                f"because a member you invited (<@{member.id}>) left. Your balance is "
                                f"**{int(balance or 0):,}** and outstanding debt is **{int(debt):,}**."
                            )
                    except discord.HTTPException:
                        logger.info("Could not DM inviter %s about leave penalty in guild %s", inviterId, member.guild.id)
            except Exception:
                logger.exception("Could not apply invite leave penalty: guild=%s invited=%s", member.guild.id, member.id)

    bot = CreditBot()

    @bot.tree.command(name="balance", description="Check your credits in this server.")
    @app_commands.guild_only()
    async def Balance(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, 
                "This command must be used inside a server.", ephemeral=True
            )
            return
        db = databaseManager.ForServer(interaction.guild_id)
        amount = creditService.GetBalance(interaction.guild_id, interaction.user.id)
        debt = db.GetCreditDebt(interaction.user.id)
        embed = discord.Embed(title="💰 Your credit account", color=discord.Color.blurple())
        embed.add_field(name="Available credits", value=f"**{amount:,}**", inline=True)
        embed.add_field(name="Outstanding debt", value=f"**{debt:,}**", inline=True)
        embed.add_field(name="Net position", value=f"**{amount - debt:+,}**", inline=True)
        if debt:
            embed.set_footer(text="Use /repay-debt to pay down your outstanding debt.")
        await SendEphemeralResponse(interaction, embed=embed, ephemeral=True)

    @bot.tree.command(name="credits", description="Check another member's credits in this server.")
    @app_commands.describe(member="The member whose credits you want to check")
    @app_commands.guild_only()
    async def Credits(interaction: discord.Interaction, member: discord.Member) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, 
                "This command must be used inside a server.", ephemeral=True
            )
            return
        db = databaseManager.ForServer(interaction.guild_id)
        amount = creditService.GetBalance(interaction.guild_id, member.id)
        embed = discord.Embed(title="💰 Member credit account", color=discord.Color.blurple())
        embed.add_field(name="Member", value=member.mention, inline=False)
        embed.add_field(name="Available credits", value=f"**{amount:,}**", inline=True)
        if CanViewMemberCreditDebt(interaction, member.id, databaseManager):
            debt = db.GetCreditDebt(member.id)
            embed.add_field(name="Outstanding debt", value=f"**{debt:,}**", inline=True)
        await SendEphemeralResponse(interaction, embed=embed, ephemeral=True)

    @bot.tree.command(name="repay-debt", description="Use your available credits to repay outstanding debt.")
    @app_commands.guild_only()
    @app_commands.describe(amount="Number of credits to apply to your outstanding debt")
    async def RepayDebt(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1_000_000_000]) -> None:
        if interaction.guild_id is None or interaction.guild is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        await DeferEphemeralResponse(interaction, thinking=True)
        try:
            status, balance, debt = db.RepayCreditDebt(
                interaction.user.id, int(amount),
                idempotencyKey=f"slash-debt-repayment:{interaction.id}",
            )
        except Exception:
            logger.exception("Debt repayment failed: guild=%s user=%s", interaction.guild_id, interaction.user.id)
            await EditEphemeralOriginalResponse(interaction, content="The repayment failed. No success was recorded; check your credit history before retrying.")
            return
        if status == "insufficient_credits":
            await EditEphemeralOriginalResponse(interaction, content=f"You have **{int(balance or 0):,} available credits**, which is not enough for that repayment. Your debt remains **{debt:,} credits**.")
            return
        if status == "exceeds_debt":
            await EditEphemeralOriginalResponse(interaction, content=f"Your outstanding debt is only **{debt:,} credits**. Enter an amount no greater than your debt.")
            return
        if status == "no_debt":
            await EditEphemeralOriginalResponse(interaction, content="You do not have any outstanding credit debt.")
            return
        if status == "duplicate":
            await EditEphemeralOriginalResponse(interaction, content=f"This repayment was already processed. Available credits: **{int(balance or 0):,}** · Remaining debt: **{debt:,}**.")
            return
        if status != "repaid":
            await EditEphemeralOriginalResponse(interaction, content=f"Repayment was not applied (status: {status}).")
            return
        await EditEphemeralOriginalResponse(interaction, content=f"✅ Repaid **{int(amount):,} credits**.\nAvailable credits: **{int(balance or 0):,}**\nRemaining debt: **{debt:,}**.")
        embed = discord.Embed(title="💳 Credit debt repayment", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Member", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Repaid", value=f"{int(amount):,} credits", inline=True)
        embed.add_field(name="Remaining debt", value=f"{debt:,} credits", inline=True)
        embed.add_field(name="Available balance", value=f"{int(balance or 0):,} credits", inline=True)
        await SendAuditLog(interaction.guild, db, embed)
        logger.info("Member debt repayment: guild=%s user=%s amount=%s remaining_debt=%s", interaction.guild_id, interaction.user.id, int(amount), debt)

    @bot.tree.command(name="credit-history", description="View recent credit transactions for yourself or a member (staff).")
    @app_commands.guild_only()
    @app_commands.describe(member="Optional member (staff access required to view another member)", page="History page, 10 transactions per page")
    async def CreditHistory(
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        page: app_commands.Range[int, 1, 1000] = 1,
    ) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        target = member or interaction.user
        if target.id != interaction.user.id and not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "Only Administrators or configured dashboard moderators can view another member's credit history.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        rows = db.ListCreditTransactions(target.id, limit=10, offset=(int(page) - 1) * 10)
        embed = discord.Embed(title=f"📜 Credit history · {target}", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        embed.description = f"Showing page {int(page)} · 10 transactions per page. Newest first."
        if not rows:
            embed.description += "\nNo credit transactions were found on this page."
        else:
            for row in rows:
                transactionType = str(row["type"]).replace("_", " ").title()
                amountText = f"{int(row['amount']):,} credits"
                if row["type"] == "debt_repayment":
                    amountText = f"−{amountText} (debt repayment)"
                elif row["type"] == "penalty_debt":
                    amountText = f"−{amountText} (penalty)"
                elif row["to_user"] == target.id:
                    amountText = f"+{amountText}"
                elif row["from_user"] == target.id:
                    amountText = f"−{amountText}"
                note = str(row["note"] or "No note")[:180]
                embed.add_field(
                    name=f"#{int(row['id'])} · {transactionType} · {amountText}",
                    value=f"{row['created_at']}\n{note}",
                    inline=False,
                )
        await SendEphemeralResponse(interaction, embed=embed, ephemeral=True)

    @bot.tree.command(name="diagnostics", description="Server owner only: check bot and credit database configuration.")
    @app_commands.guild_only()
    async def Diagnostics(interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        if not IsServerOwner(interaction):
            await SendEphemeralResponse(interaction, "Only this server's owner can run /diagnostics.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        await DeferEphemeralResponse(interaction, thinking=True)
        checks: list[tuple[str, bool, str]] = []
        try:
            db.Execute("SELECT 1", fetchOne=True)
            checks.append(("Database connection", True, f"{db.backend.upper()} reachable"))
        except Exception:
            logger.exception("Database diagnostics failed: guild=%s", interaction.guild_id)
            checks.append(("Database connection", False, "Connection/query failed; inspect host logs"))
        try:
            for table in ("users", "transactions", "credit_debts", "tickets", "scam_reports"):
                db.Execute(f"SELECT 1 FROM {table} LIMIT 1", fetchOne=True)
            checks.append(("Core tables", True, "Required tables are queryable"))
        except Exception:
            logger.exception("Core table diagnostics failed: guild=%s", interaction.guild_id)
            checks.append(("Core tables", False, "One or more required tables could not be queried"))
        auditChannel = await ResolveAuditChannel(interaction.guild, db)
        if isinstance(auditChannel, discord.TextChannel):
            permissions = auditChannel.permissions_for(interaction.guild.me) if interaction.guild.me else None
            canAudit = bool(permissions and permissions.view_channel and permissions.send_messages and permissions.embed_links)
            checks.append(("Audit log channel", canAudit, auditChannel.mention if canAudit else "Configured channel lacks required bot permissions"))
        else:
            checks.append(("Audit log channel", False, "Not configured or channel unavailable"))
        embed = discord.Embed(title="🔎 BloxAssist diagnostics", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        for label, passed, detail in checks:
            embed.add_field(name=f"{'✅' if passed else '⚠️'} {label}", value=detail, inline=False)
        embed.set_footer(text="Diagnostics never displays database credentials or secret values.")
        await EditEphemeralOriginalResponse(interaction, embed=embed)

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
    @app_commands.describe(member="Member receiving credits", amount="Positive number of credits", reason="Required reason for adding these credits")
    async def AddCredits(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str) -> None:
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
        if not reason or not reason.strip():
            await SendEphemeralResponse(interaction, "A reason is required so the credit change is documented in the audit log.", ephemeral=True)
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
        auditEmbed = discord.Embed(title="💰 Credit balance changed", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        auditEmbed.add_field(name="Action", value="Add credits", inline=True)
        auditEmbed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
        auditEmbed.add_field(name="Changed by", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        auditEmbed.add_field(name="Change", value=f"+{amount:,} credits", inline=True)
        auditEmbed.add_field(name="New balance", value=f"{newBalance:,} credits", inline=True)
        auditEmbed.add_field(name="Reason", value=(reason.strip() if reason and reason.strip() else "Not provided")[:1000], inline=False)
        await SendAuditLog(interaction.guild, db, auditEmbed)
        logger.info("Server-owner credit add: guild=%s actor=%s target=%s amount=%s reason=%r", interaction.guild_id, interaction.user.id, member.id, amount, reason)

    @bot.tree.command(name="penalty", description="Server owner only: apply a penalty that may create credit debt.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(member="Member receiving the penalty", amount="Penalty amount in credits", reason="Required reason for the penalty")
    async def CreditPenalty(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "This command must be used inside a server.", ephemeral=True)
            return
        if not IsServerOwner(interaction):
            await SendEphemeralResponse(interaction, "Only the server owner can use /penalty. Players and configured moderators cannot create credit debt.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        if db.IsUserParticipantInAnyOpenTicket(interaction.user.id):
            await SendEphemeralResponse(interaction, "Credit moderation is disabled while you participate in an open ticket. Wait until it is resolved.", ephemeral=True)
            return
        if member.bot or member.id == interaction.user.id:
            await SendEphemeralResponse(interaction, "Choose another human member; bot accounts and yourself cannot receive this penalty.", ephemeral=True)
            return
        if isinstance(amount, bool) or amount <= 0 or amount > 1_000_000_000 or not reason or not reason.strip():
            await SendEphemeralResponse(interaction, "Provide a penalty from 1 to 1,000,000,000 credits and a non-empty reason.", ephemeral=True)
            return
        await DeferEphemeralResponse(interaction, thinking=True)
        try:
            status, balance, debt = db.ApplyPenaltyDebt(member.id, amount, actorUserId=interaction.user.id, reason=reason, idempotencyKey=f"slash-penalty:{interaction.id}")
        except Exception:
            logger.exception("Credit penalty failed: guild=%s actor=%s target=%s", interaction.guild_id, interaction.user.id, member.id)
            await EditEphemeralOriginalResponse(interaction, content="The penalty failed. No success was recorded; check the transaction ledger before retrying.")
            return
        if status != "penalized":
            await EditEphemeralOriginalResponse(interaction, content=f"Penalty was not applied (status: {status}).")
            return
        await EditEphemeralOriginalResponse(interaction, content=f"⚖️ Applied a {amount:,}-credit penalty to {member.mention}.\nCurrent credits: {balance:,}. Outstanding debt: {debt:,}.\nReason: {reason.strip()[:500]}\nMembers with debt cannot create/host services.")
        embed = discord.Embed(title="⚖️ Credit penalty applied", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Applied by", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Penalty", value=f"{amount:,} credits", inline=True)
        embed.add_field(name="Outstanding debt", value=f"{debt:,} credits", inline=True)
        embed.add_field(name="Reason", value=reason.strip()[:1000], inline=False)
        await SendAuditLog(interaction.guild, db, embed)
        logger.info("Server-owner penalty applied: guild=%s actor=%s target=%s amount=%s debt=%s reason=%r", interaction.guild_id, interaction.user.id, member.id, amount, debt, reason)
    @bot.tree.command(name="deduct", description="Server owner only: deduct credits from a member with an audit record.")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(member="Member losing credits", amount="Positive number of credits", reason="Required reason for deducting these credits")
    async def DeductCredits(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str) -> None:
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
        if not reason or not reason.strip():
            await SendEphemeralResponse(interaction, "A reason is required so the credit change is documented in the audit log.", ephemeral=True)
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
        auditEmbed = discord.Embed(title="💰 Credit balance changed", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
        auditEmbed.add_field(name="Action", value="Deduct credits", inline=True)
        auditEmbed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
        auditEmbed.add_field(name="Changed by", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        auditEmbed.add_field(name="Change", value=f"-{amount:,} credits", inline=True)
        auditEmbed.add_field(name="New balance", value=f"{newBalance:,} credits", inline=True)
        auditEmbed.add_field(name="Reason", value=(reason.strip() if reason and reason.strip() else "Not provided")[:1000], inline=False)
        await SendAuditLog(interaction.guild, db, auditEmbed)
        logger.info("Server-owner credit deduct: guild=%s actor=%s target=%s amount=%s reason=%r", interaction.guild_id, interaction.user.id, member.id, amount, reason)

    inviteEventGroup = app_commands.Group(
        name="invite-event",
        description="Start or end invite reward events for this server.",
    )

    @inviteEventGroup.command(name="start", description="Start an invite reward event.")
    @app_commands.guild_only()
    @app_commands.describe(
        reward_credits="Credits per eligible invite (defaults to the Admin Dashboard value)",
        duration_minutes="Duration in minutes, max 7 days (ignored if run_forever is enabled)",
        run_forever="Keep the event active until /invite-event end is run",
    )
    async def StartInviteRewardEvent(
        interaction: discord.Interaction,
        reward_credits: app_commands.Range[int, 0, 1_000_000_000] | None = None,
        duration_minutes: app_commands.Range[int, 1, 10080] | None = None,
        run_forever: bool = False,
    ) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "Only Administrators or configured dashboard moderators can start invite reward events.", ephemeral=True)
            return
        if not interaction.guild.me or not interaction.guild.me.guild_permissions.manage_guild:
            await SendEphemeralResponse(interaction, "Invite tracking requires the bot to have the Manage Server permission so it can compare invite use counts.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        inviteRewardsEnabled = (db.GetSetting("invite_rewards_enabled", "false") or "false").lower() in {"true", "1", "yes", "on"}
        if not inviteRewardsEnabled:
            await SendEphemeralResponse(interaction, "Invite rewards are disabled in the Admin Dashboard. An Administrator must enable them before starting an event.", ephemeral=True)
            return
        # Dashboard values are defaults; an explicit command argument overrides them.
        savedReward = db.GetSetting("invite_reward_credits", "50") or "50"
        savedDuration = db.GetSetting("invite_duration_minutes", "60") or "60"
        try:
            rewardAmount = int(reward_credits if reward_credits is not None else savedReward)
            durationAmount = None if run_forever else int(duration_minutes if duration_minutes is not None else savedDuration)
            if not 0 <= rewardAmount <= 1_000_000_000:
                raise ValueError("Reward must be between 0 and 1,000,000,000 credits.")
            if durationAmount is not None and not 1 <= durationAmount <= 10_080:
                raise ValueError("Duration must be between 1 minute and 7 days.")
            status, eventId, endsAt = db.StartInviteEvent(rewardAmount, durationAmount, interaction.user.id)
        except Exception:
            logger.exception("Could not start invite reward event: guild=%s actor=%s", interaction.guild_id, interaction.user.id)
            await SendEphemeralResponse(interaction, "The invite event could not be started. Check the database logs and try again.", ephemeral=True)
            return
        if status == "already_active":
            await SendEphemeralResponse(interaction, f"Invite event #{eventId} is already active. End it before starting another.", ephemeral=True)
            return
        embed = discord.Embed(title="🎟️ Invite reward event started", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Event ID", value=f"#{eventId}", inline=True)
        embed.add_field(name="Reward per eligible join", value=f"{rewardAmount:,} credits", inline=True)
        embed.add_field(name="Duration", value="Until manually ended" if durationAmount is None else f"{durationAmount} minute(s)", inline=True)
        if endsAt is not None:
            embed.add_field(name="Ends at (UTC)", value=str(endsAt), inline=False)
        else:
            embed.add_field(name="End condition", value="Runs until staff uses /invite-event end.", inline=False)
        confirmation = (
            f"✅ Started invite reward event #{eventId}. It will keep running until staff uses **/invite-event end**."
            if durationAmount is None
            else f"✅ Started invite reward event #{eventId}. It ends automatically at {endsAt} UTC."
        )
        await SendEphemeralResponse(interaction, confirmation, ephemeral=True)
        await SendAuditLog(interaction.guild, db, embed)
        currentInvites = await FetchInviteUseCounts(interaction.guild)
        if currentInvites is not None:
            bot.inviteUsage[interaction.guild.id] = currentInvites

    @inviteEventGroup.command(name="end", description="End the active invite reward event now.")
    @app_commands.guild_only()
    async def EndInviteRewardEvent(interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "Only Administrators or configured dashboard moderators can end invite reward events.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        status, event = db.EndInviteEvent(endedBy=interaction.user.id)
        if status == "none_active" or event is None:
            await SendEphemeralResponse(interaction, "There is no active invite reward event to end.", ephemeral=True)
            return
        embed = discord.Embed(title="🛑 Invite reward event ended", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Event ID", value=f"#{int(event['event_id'])}", inline=True)
        embed.add_field(name="Reward per eligible join", value=f"{int(event['reward_credits']):,} credits", inline=True)
        embed.add_field(name="Ended by", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        await SendEphemeralResponse(interaction, f"✅ Invite reward event #{int(event['event_id'])} ended. New joins will no longer earn its reward.", ephemeral=True)
        await SendAuditLog(interaction.guild, db, embed)

    bot.tree.add_command(inviteEventGroup)

    @bot.tree.command(name="ticket-history", description="Staff only: review a member's retained ticket history.")
    @app_commands.guild_only()
    @app_commands.describe(member="The member whose tickets you want to review", limit="Number of recent tickets to show (1–10)")
    async def TicketHistory(interaction: discord.Interaction, member: discord.Member, limit: app_commands.Range[int, 1, 10] = 10) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "Only Administrators or configured dashboard moderators can view ticket history.", ephemeral=True)
            return
        rows = db.ListTicketHistoryForMember(member.id, int(limit))
        embed = discord.Embed(title=f"📚 Ticket history · {member}", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        embed.description = f"Member ID: `{member.id}`\nShowing {len(rows)} most recent matching ticket(s). The database retains ticket/transaction metadata even after the ticket channel is deleted."
        for row in rows[:10]:
            ticketNumber = int(row["ticket_number"] or 0)
            ticketLabel = TicketLabelFromRow(row)
            helpers = db._ParseIdCsv(str(row["helper_ids"] or ""))
            value = (f"Status: **{row['status']}** · Event key: `{row['event_key']}`\n"
                     f"Requester: <@{int(row['creator_id'])}> · Helpers: " + (", ".join(f"<@{x}>" for x in helpers) or "none") +
                     f"\nReserved: {int(row['reserved_credits']):,} credits · Created: {row['created_at']}")
            transcriptChannelId = row["transcript_channel_id"] if "transcript_channel_id" in row.keys() else None
            transcriptMessageId = row["transcript_message_id"] if "transcript_message_id" in row.keys() else None
            if transcriptChannelId and transcriptMessageId:
                value += f"\n[Open transcript](https://discord.com/channels/{interaction.guild_id}/{int(transcriptChannelId)}/{int(transcriptMessageId)})"
            else:
                value += "\nTranscript link: unavailable (no successfully saved transcript was recorded)."
            embed.add_field(name=f"Ticket #{ticketLabel} · Database ID {int(row['ticket_id'])}", value=value[:1024], inline=False)
        if not rows:
            embed.description += "\nNo retained ticket records matched this member."
        await SendEphemeralResponse(interaction, embed=embed, ephemeral=True)

    @bot.tree.command(name="reports", description="Staff only: browse open reports by category and page.")
    @app_commands.guild_only()
    @app_commands.describe(page="Page number (5 reports per page)", category="Optional report category filter")
    @app_commands.choices(category=[
        app_commands.Choice(name="All categories", value="all"),
        app_commands.Choice(name="Scam / Fraud", value="scam"),
        app_commands.Choice(name="Bug / Bot Issue", value="bug"),
        app_commands.Choice(name="Ticket / Credit Issue", value="ticket_credit"),
        app_commands.Choice(name="Member Misconduct", value="member_behavior"),
        app_commands.Choice(name="Other / General Issue", value="other"),
    ])
    async def Reports(
        interaction: discord.Interaction,
        page: app_commands.Range[int, 1, 1000] = 1,
        category: app_commands.Choice[str] | None = None,
    ) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "Only Administrators or configured dashboard moderators can review reports.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        rows = db.ListScamReports(status="open", limit=5, reportType=category.value if category else None, offset=(int(page) - 1) * 5)
        categoryText = category.name if category else "All categories"
        embed = discord.Embed(title=f"📨 Open reports · {categoryText}", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        embed.set_footer(text=f"Page {int(page)} · 5 reports per page · Use /reports page:<number> to navigate")
        if not rows:
            embed.description = "No open reports were found on this page for the selected category."
        else:
            embed.description = "Use `/report-review` to confirm or dismiss a report after reviewing the available evidence."
            categoryLabels = {
                "scam": "Scam / Fraud",
                "bug": "Bug / Bot Issue",
                "ticket_credit": "Ticket / Credit Issue",
                "member_behavior": "Member Misconduct",
                "other": "Other / General Issue",
            }
            for row in rows[:10]:
                reportedUserId = int(row["reported_user_id"] or 0)
                reportType = str(row["report_type"] if "report_type" in row.keys() else "scam")
                categoryLabel = categoryLabels.get(reportType, "Other / General Issue")
                relatedTickets = db.ListTicketHistoryForMember(reportedUserId, limit=2) if reportedUserId > 0 else []
                relatedLinks = []
                for ticketRow in relatedTickets:
                    ticketLabel = TicketLabelFromRow(ticketRow)
                    transcriptChannelId = ticketRow["transcript_channel_id"] if "transcript_channel_id" in ticketRow.keys() else None
                    transcriptMessageId = ticketRow["transcript_message_id"] if "transcript_message_id" in ticketRow.keys() else None
                    if transcriptChannelId and transcriptMessageId:
                        relatedLinks.append(
                            f"[ticket-{ticketLabel} transcript](https://discord.com/channels/{interaction.guild_id}/{int(transcriptChannelId)}/{int(transcriptMessageId)})"
                        )
                    elif str(ticketRow["status"]) == "open" and ticketRow["channel_id"]:
                        relatedLinks.append(
                            f"[ticket-{ticketLabel} open channel](https://discord.com/channels/{interaction.guild_id}/{int(ticketRow['channel_id'])})"
                        )
                linksText = (
                    "\n".join(relatedLinks) if relatedLinks
                    else ("No member was attached to this report." if reportedUserId <= 0
                          else "No transcript/open ticket links found for this member.")
                )
                memberText = f"<@{reportedUserId}> (`{reportedUserId}`)" if reportedUserId > 0 else "Not specified"
                embed.add_field(
                    name=f"Report #{int(row['report_id'])} · {str(row['created_at'])}",
                    value=(
                        f"**Category:** {categoryLabel}\n"
                        f"**Reported member:** {memberText}\n"
                        f"**Reporter:** <@{int(row['reporter_user_id'])}> (`{int(row['reporter_user_id'])}`)\n"
                        f"**Details:** {str(row['details'])[:250]}\n"
                        f"**Related history:** {linksText}"
                    )[:1024],
                    inline=False,
                )
        await SendEphemeralResponse(interaction, embed=embed, ephemeral=True)

    @bot.tree.command(name="report-review", description="Staff only: confirm or dismiss an open report.")
    @app_commands.guild_only()
    @app_commands.describe(report_id="The report number shown by /reports", decision="Outcome after checking evidence", note="Optional moderation note")
    @app_commands.choices(decision=[
        app_commands.Choice(name="Confirm report", value="confirmed"),
        app_commands.Choice(name="Dismiss report", value="dismissed"),
    ])
    async def ReportReview(interaction: discord.Interaction, report_id: app_commands.Range[int, 1, 2_147_483_647], decision: app_commands.Choice[str], note: str | None = None) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, "Use this command inside a server.", ephemeral=True)
            return
        if not HasConfiguredStaffAccess(interaction, databaseManager):
            await SendEphemeralResponse(interaction, "Only Administrators or configured dashboard moderators can review reports.", ephemeral=True)
            return
        db = databaseManager.ForServer(interaction.guild_id)
        try:
            changed = db.ResolveScamReport(int(report_id), interaction.user.id, decision.value, note or "")
        except ValueError as error:
            await SendEphemeralResponse(interaction, str(error), ephemeral=True)
            return
        if not changed:
            await SendEphemeralResponse(interaction, f"Report #{int(report_id)} was not found as an open report. It may already have been reviewed.", ephemeral=True)
            return
        outcomeText = "confirmed" if decision.value == "confirmed" else "dismissed"
        await SendEphemeralResponse(interaction, f"✅ Report #{int(report_id)} marked **{outcomeText}**.", ephemeral=True)
        embed = discord.Embed(title="🛡️ Report reviewed", color=discord.Color.orange() if decision.value == "dismissed" else discord.Color.blurple(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Report", value=f"#{int(report_id)}", inline=True)
        embed.add_field(name="Decision", value=outcomeText, inline=True)
        embed.add_field(name="Reviewed by", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="Moderator note", value=(note.strip()[:1000] if note and note.strip() else "Not provided"), inline=False)
        await SendAuditLog(interaction.guild, db, embed)

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
