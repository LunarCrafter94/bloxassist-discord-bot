"""Discord UI for the Blox Fruits ticket and credit system.

Views keep a DatabaseManager, never a single Database. Each callback resolves
the database from the guild that generated that interaction.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import discord

from ..settings import MAX_HELPERS, TICKET_CATEGORY_NAME
from ..interaction_utils import (
    DeferEphemeralResponse,
    EditEphemeralOriginalResponse,
    DeleteEphemeralOriginalResponse,
    DeleteEphemeralOriginalResponses,
    SendEphemeralResponse,
)
from ..database import DatabaseManager, GuildDatabase
from ..admin.dashboard_views import GetDashboardModeratorRoleIds, GetEffectiveTicketStaffRoleIds, SetupDashboardViews


def GetDatabaseForInteraction(interaction: discord.Interaction, databaseManager: DatabaseManager) -> GuildDatabase:
    if interaction.guild_id is None:
        raise ValueError("This control can only be used inside a Discord server.")
    return databaseManager.ForServer(interaction.guild_id)


def GetServerOnlyMessage() -> str:
    return "This control can only be used inside a Discord server."


def GetTicketStaffMentions(guild: discord.Guild, guildDatabase: GuildDatabase) -> str:
    roleIds = set(GetDashboardModeratorRoleIds(guildDatabase))
    roleIds.update(GetEffectiveTicketStaffRoleIds(guild, guildDatabase))
    return " ".join(
        role.mention
        for roleId in sorted(roleIds)
        if (role := guild.get_role(roleId)) is not None and not role.is_default() and not role.managed
    )


def IsConfiguredTicketStaff(interaction: discord.Interaction, guildDatabase: GuildDatabase) -> bool:
    """Return true for owner, Administrator, or configured dashboard moderator roles.

    Manage Server alone is deliberately not an implicit staff grant.
    """
    guild = interaction.guild
    if guild is None:
        return False
    if interaction.user.id == guild.owner_id:
        return True
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions and permissions.administrator:
        return True
    permittedRoleIds = set(GetDashboardModeratorRoleIds(guildDatabase))
    memberRoleIds = {role.id for role in getattr(interaction.user, "roles", ())}
    return bool(permittedRoleIds.intersection(memberRoleIds))


class MainPanelView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager):
        super().__init__(timeout=None)
        self.databaseManager = databaseManager

    @discord.ui.button(
        label="Create Ticket",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="bf:create_ticket",
    )
    async def CreateTicket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        print(
            f"[UI] Create Ticket | guild={interaction.guild_id} | "
            f"age={age:.3f}s | gateway_latency={interaction.client.latency:.3f}s"
        )
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
            return
        await DeferEphemeralResponse(interaction, thinking=True)
        guildDatabase = GetDatabaseForInteraction(interaction, self.databaseManager)
        if guildDatabase.GetOpenTicketForUser(interaction.user.id):
            await EditEphemeralOriginalResponse(interaction, 
                content="You already have an open ticket in this server.", view=None
            )
            return
        await EditEphemeralOriginalResponse(interaction, 
            content="Choose how many helpers you want.",
            view=HelperCountView(self.databaseManager, interaction.guild_id, [interaction]),
        )

    @discord.ui.button(
        label="Balance",
        emoji="💰",
        style=discord.ButtonStyle.secondary,
        custom_id="bf:balance",
    )
    async def Balance(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
            return
        guildDatabase = GetDatabaseForInteraction(interaction, self.databaseManager)
        credits = guildDatabase.GetBalance(interaction.user.id)
        await SendEphemeralResponse(interaction, 
            f"💰 You have **{credits:,} credits** in this server.", ephemeral=True
        )


class HelperCountSelect(discord.ui.Select):
    def __init__(self, databaseManager: DatabaseManager, guildId: int, wizardInteractions: list[discord.Interaction] | None = None):
        maxHelpers = databaseManager.ForServer(guildId).GetMaxHelpers()
        options = [
            discord.SelectOption(
                label=str(count),
                value=str(count),
                description=f"Request help from {count} member(s).",
            )
            for count in range(1, maxHelpers + 1)
        ]
        super().__init__(
            placeholder="Select number of helpers",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="bf:helper_count",
        )
        self.databaseManager = databaseManager
        self.wizardInteractions = list(wizardInteractions or [])

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
            return
        count = int(self.values[0])
        if count > GetDatabaseForInteraction(interaction, self.databaseManager).GetMaxHelpers():
            await SendEphemeralResponse(interaction, 
                "The server's maximum helper setting changed. Please restart your ticket request.",
                ephemeral=True,
            )
            return
        await SendEphemeralResponse(interaction, 
            f"Select **{count}** helper(s) from this server.",
            view=HelperPickerView(self.databaseManager, count, self.wizardInteractions + [interaction]),
            ephemeral=True,
        )


class HelperCountView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager, guildId: int, wizardInteractions: list[discord.Interaction] | None = None):
        super().__init__(timeout=60)
        self.add_item(HelperCountSelect(databaseManager, guildId, wizardInteractions))


class HelperPicker(discord.ui.UserSelect):
    def __init__(self, databaseManager: DatabaseManager, count: int, wizardInteractions: list[discord.Interaction] | None = None):
        super().__init__(
            placeholder=f"Choose {count} helper(s)",
            min_values=count,
            max_values=count,
            custom_id=f"bf:helpers:{count}",
        )
        self.databaseManager = databaseManager
        self.count = count
        self.wizardInteractions = list(wizardInteractions or [])

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
            return
        helpers = [member for member in self.values if member.id != interaction.user.id]
        if self.count > GetDatabaseForInteraction(interaction, self.databaseManager).GetMaxHelpers():
            await SendEphemeralResponse(interaction, 
                "The server's maximum helper setting changed. Please restart your ticket request.",
                ephemeral=True,
            )
            return
        if len(helpers) != self.count:
            await SendEphemeralResponse(interaction, 
                "You cannot select yourself as a helper. Please select other members.",
                ephemeral=True,
            )
            return
        guildDatabase = GetDatabaseForInteraction(interaction, self.databaseManager)
        if guildDatabase.GetOpenTicketForUser(interaction.user.id):
            await SendEphemeralResponse(interaction, 
                "You already have an open ticket in this server.", ephemeral=True
            )
            return
        services = guildDatabase.ListServices(activeOnly=True)
        if not services:
            await SendEphemeralResponse(interaction, 
                "No services are currently available. Please contact a server moderator.",
                ephemeral=True,
            )
            return
        await SendEphemeralResponse(interaction, 
            "Now choose the Blox Fruits event.",
            view=EventView(self.databaseManager, [member.id for member in helpers], interaction.guild_id, self.wizardInteractions + [interaction]),
            ephemeral=True,
        )


class HelperPickerView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager, count: int, wizardInteractions: list[discord.Interaction] | None = None):
        super().__init__(timeout=60)
        self.add_item(HelperPicker(databaseManager, count, wizardInteractions))


class EventSelect(discord.ui.Select):
    def __init__(
        self,
        databaseManager: DatabaseManager,
        helperIds: list[int],
        guildId: int,
        wizardInteractions: list[discord.Interaction] | None = None,
    ):
        self.databaseManager = databaseManager
        self.helperIds = helperIds
        self.wizardInteractions = list(wizardInteractions or [])
        guildDatabase = databaseManager.ForServer(guildId)
        services = guildDatabase.ListServices(activeOnly=True)
        options = [
            discord.SelectOption(
                label=str(service["name"])[:100],
                value=str(service["service_key"]),
                description=f"{int(service['price']):,} credits per helper."[:100],
            )
            for service in services[:25]
        ]
        super().__init__(
            placeholder="Choose a Blox Fruits event",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="bf:event",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
            return
        guildDatabase = GetDatabaseForInteraction(interaction, self.databaseManager)
        service = guildDatabase.GetService(self.values[0], activeOnly=True)
        if service is None:
            await SendEphemeralResponse(interaction, 
                "That service is no longer available. Please start a new ticket.",
                ephemeral=True,
            )
            return
        await CreateTicketChannel(
            interaction=interaction,
            databaseManager=self.databaseManager,
            eventKey=str(service["service_key"]),
            eventName=str(service["name"]),
            cost=int(service["price"]),
            helperIds=self.helperIds,
            wizardInteractions=self.wizardInteractions,
        )


class EventView(discord.ui.View):
    def __init__(self, databaseManager: DatabaseManager, helperIds: list[int], guildId: int, wizardInteractions: list[discord.Interaction] | None = None):
        super().__init__(timeout=60)
        self.add_item(EventSelect(databaseManager, helperIds, guildId, wizardInteractions))


async def CreateTicketChannel(
    interaction: discord.Interaction,
    databaseManager: DatabaseManager,
    eventKey: str,
    eventName: str,
    cost: int,
    helperIds: list[int],
    wizardInteractions: list[discord.Interaction] | None = None,
) -> None:
    if interaction.guild is None or interaction.guild_id is None:
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return

    guild = interaction.guild
    creator = interaction.user
    wizardInteractions = list(wizardInteractions or [])
    guildDatabase = databaseManager.ForServer(guild.id)
    unitPrice = int(cost)
    if not helperIds:
        await SendEphemeralResponse(interaction, "Choose at least one helper.", ephemeral=True)
        return
    cost = unitPrice * len(helperIds)
    if len(helperIds) > guildDatabase.GetMaxHelpers():
        await SendEphemeralResponse(interaction, 
            "The server's maximum helper setting changed. Please restart your ticket request.",
            ephemeral=True,
        )
        return

    # Respond before Discord API calls and database work that may take time.
    await DeferEphemeralResponse(interaction, thinking=True)

    # Check current balance before creating the channel. The actual reservation below
    # is atomic, so this preliminary check is only for a helpful error message.
    balance = guildDatabase.GetBalance(creator.id)
    if balance < cost:
        await EditEphemeralOriginalResponse(interaction, 
            content=(f"❌ **{eventName}** costs **{unitPrice:,} credits per helper** × "
                     f"**{len(helperIds)} helper(s)** = **{cost:,} credits total**, "
                     f"but you have **{balance:,}** in this server."),
            view=None,
        )
        return

    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(TICKET_CATEGORY_NAME)

    botMember = guild.get_member(interaction.client.user.id) if interaction.client.user else None
    if botMember is None:
        botMember = guild.me

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        creator: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
    }
    if botMember is not None:
        overwrites[botMember] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            read_message_history=True,
        )

    helperMembers: list[discord.Member] = []
    for helperId in helperIds:
        member = guild.get_member(helperId)
        if member is None:
            try:
                member = await guild.fetch_member(helperId)
            except discord.HTTPException:
                member = None
        if member is None:
            await EditEphemeralOriginalResponse(interaction, 
                content=f"❌ I couldn't verify helper `{helperId}` in this server. Please start the ticket again and select current server members.",
                view=None,
            )
            return
        helperMembers.append(member)
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    # Apply this server's configured staff role baseline (and higher roles) to new tickets.
    # This is permission overwriting only; the bot never grants Administrator.
    for staffRoleId in GetEffectiveTicketStaffRoleIds(guild, guildDatabase):
        staffRole = guild.get_role(staffRoleId)
        if staffRole is not None and not staffRole.is_default() and not staffRole.managed:
            overwrites[staffRole] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            )

    # Create a private temporary channel first. The database assigns the next number
    # number only after Discord has successfully created a channel, so channel-creation
    # permission/API failures do not consume a visible ticket number.
    temporaryChannelName = f"ticket-pending-{interaction.id}"
    channel = await guild.create_text_channel(
        temporaryChannelName,
        category=category,
        overwrites=overwrites,
        topic=f"Initializing Blox Fruits ticket | creator={creator.id} | guild={guild.id}",
    )

    ticketId: int | None = None
    try:
        # Re-read price/availability immediately before the synchronous reservation call.
        # This means a dashboard price change while Discord was creating the channel is
        # reflected in the reservation and stored ticket snapshot.
        currentService = guildDatabase.GetService(eventKey, activeOnly=True)
        if currentService is None:
            await channel.delete(reason="Selected event was disabled before reservation")
            await EditEphemeralOriginalResponse(interaction, 
                content="❌ That event was disabled before your ticket could be reserved. No credits were deducted; please start again.",
                view=None,
            )
            return
        eventName = str(currentService["name"])
        unitPrice = int(currentService["price"])
        cost = unitPrice * len(helperIds)
        currentBalance = guildDatabase.GetBalance(creator.id)
        if currentBalance < cost:
            await channel.delete(reason="Service price changed; requester cannot cover updated total")
            await EditEphemeralOriginalResponse(
                interaction,
                content=(f"❌ The price changed before reservation. **{eventName}** now costs "
                         f"**{unitPrice:,} credits per helper** × **{len(helperIds)} helper(s)** = "
                         f"**{cost:,} credits total**; your balance is **{currentBalance:,}**. "
                         "No credits were deducted."),
                view=None,
            )
            return
        ticketId = guildDatabase.ReserveTicket(
            channelId=channel.id,
            creatorId=creator.id,
            eventKey=eventKey,
            helperIds=helperIds,
            requiredCredits=cost,
            pricePerHelper=unitPrice,
        )
        if ticketId is None:
            await channel.delete(reason="Insufficient credits at atomic reservation")
            await EditEphemeralOriginalResponse(interaction, 
                content=(f"❌ Your balance or the event price changed before reservation. The current total is "
                         f"{unitPrice:,} × {len(helperIds)} = {cost:,} credits. No credits were deducted."),
                view=None,
            )
            return

        ticket = guildDatabase.GetTicketByChannel(channel.id)
        if ticket is None or ticket["ticket_number"] is None:
            raise RuntimeError("The reserved ticket is missing its assigned ticket number.")

        ticketNumber = int(ticket["ticket_number"])
        ticketLabel = f"{ticketNumber:03d}"
        channel = await channel.edit(
            name=f"ticket-{ticketLabel}",
            topic=(
                f"Blox Fruits ticket #{ticketLabel} | {eventName} | "
                f"creator={creator.id} | guild={guild.id}"
            ),
        )

        helperMentions = " ".join(member.mention for member in helperMembers)
        embed = discord.Embed(
            title=f"🎫 Ticket #{ticketLabel} — {eventName}",
            description=(
                f"**Requester:** {creator.mention}\n"
                f"**Ticket:** `ticket-{ticketLabel}`\n"
                f"**Helpers:** {helperMentions} ({len(helperIds)} invited)\n"
                f"**Price per helper:** {unitPrice:,} credits\n"
                f"**Total reserved:** {unitPrice:,} × {len(helperIds)} = {cost:,} credits\n\n"
                "The configured event price is per helper. Each active helper earns that amount at completion. "
                "If an original helper slot is left unfilled when the ticket is completed, that slot's price is refunded to the requester.\n\n"
                "When the help is finished, the requester can use "
                "`/complete_ticket`. Configured staff who are not participants in this ticket "
                "may use `/admin_complete` only for an escalation.\n\n"
                "Completion and cancellation require confirmation from every active helper. "
                "Helpers can leave; replacement requests are shown when only one helper remains."
            ),
            color=discord.Color.green(),
        )
        await channel.send(
            content=f"{creator.mention} {helperMentions}",
            embed=embed,
            view=TicketView(databaseManager),
        )
    except Exception:
        # If a ticket was recorded but its channel panel failed, refund atomically.
        if ticketId is not None:
            guildDatabase.RefundTicket(ticketId, note="automatic refund after ticket setup failure")
        try:
            await channel.delete(reason="Ticket creation failed; cleanup")
        except discord.HTTPException:
            pass
        raise

    await EditEphemeralOriginalResponse(interaction, 
        content=f"✅ Ticket created: {channel.mention}", view=None
    )
    # The final success acknowledgement remains visible privately for up to one minute;
    # clear the prior wizard steps immediately so old menus don't accumulate.
    await DeleteEphemeralOriginalResponses(wizardInteractions)


class TicketView(discord.ui.View):
    """Stable controls that are relevant throughout an open ticket."""

    def __init__(self, databaseManager: DatabaseManager):
        super().__init__(timeout=None)
        self.databaseManager = databaseManager

    @discord.ui.button(label="Complete", emoji="✅", style=discord.ButtonStyle.success, custom_id="bf:ticket_complete")
    async def Complete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await CompleteCurrentTicket(interaction, self.databaseManager)

    @discord.ui.button(label="Cancel", emoji="🛑", style=discord.ButtonStyle.danger, custom_id="bf:ticket_cancel")
    async def Cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await CancelUserTicket(interaction, self.databaseManager)

    @discord.ui.button(label="Leave as Helper", emoji="🚪", style=discord.ButtonStyle.secondary, custom_id="bf:ticket_leave", row=1)
    async def Leave(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await LeaveTicketHelper(interaction, self.databaseManager)


class TicketResolutionView(discord.ui.View):
    """Resolution-specific controls shown only while a proposal is pending."""

    def __init__(self, databaseManager: DatabaseManager, resolutionType: str | None = None):
        super().__init__(timeout=None)
        self.databaseManager = databaseManager
        if resolutionType == "complete":
            confirmLabel, rejectLabel = "Confirm Completion", "Reject Completion"
        elif resolutionType == "cancel":
            confirmLabel, rejectLabel = "Confirm Cancellation", "Reject Cancellation"
        else:
            confirmLabel, rejectLabel = "Confirm Proposal", "Reject Proposal"
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.custom_id == "bf:resolution:confirm":
                item.label = confirmLabel
            elif item.custom_id == "bf:resolution:reject":
                item.label = rejectLabel

    @discord.ui.button(label="Confirm Resolution", emoji="👍", style=discord.ButtonStyle.primary, custom_id="bf:resolution:confirm")
    async def ConfirmResolution(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await ConfirmTicketResolutionCurrent(interaction, self.databaseManager)

    @discord.ui.button(label="Reject Resolution", emoji="👎", style=discord.ButtonStyle.danger, custom_id="bf:resolution:reject")
    async def RejectResolution(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await RejectTicketResolutionCurrent(interaction, self.databaseManager)


class ReplacementRequestView(discord.ui.View):
    """Requester's entry point for selecting replacement candidates when eligible."""

    def __init__(self, databaseManager: DatabaseManager):
        super().__init__(timeout=None)
        self.databaseManager = databaseManager

    @discord.ui.button(label="Choose Replacement Helpers", emoji="➕", style=discord.ButtonStyle.secondary, custom_id="bf:ticket_request_replacements")
    async def RequestReplacements(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await RequestTicketReplacements(interaction, self.databaseManager)


class ReplacementCandidateSelect(discord.ui.UserSelect):
    """Private requester-only selector for exactly the missing helper slots."""

    def __init__(
        self,
        databaseManager: DatabaseManager,
        ticketId: int,
        ticketChannelId: int,
        requesterId: int,
        candidateCount: int,
        triggerMessageId: int | None,
        selectionPromptInteraction: discord.Interaction,
    ):
        super().__init__(
            placeholder=f"Choose exactly {candidateCount} replacement helper(s)",
            min_values=candidateCount,
            max_values=candidateCount,
            custom_id=f"bf:replacement_candidates:{ticketId}:{requesterId}",
        )
        self.databaseManager = databaseManager
        self.ticketId = int(ticketId)
        self.ticketChannelId = int(ticketChannelId)
        self.requesterId = int(requesterId)
        self.candidateCount = int(candidateCount)
        self.triggerMessageId = int(triggerMessageId) if triggerMessageId else None
        self.selectionPromptInteraction = selectionPromptInteraction

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild_id is None:
            await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
            return
        if interaction.user.id != self.requesterId:
            await SendEphemeralResponse(interaction, "Only the ticket requester can select replacement helpers.", ephemeral=True)
            return
        await DeferEphemeralResponse(interaction, thinking=True)
        guildDatabase = self.databaseManager.ForServer(interaction.guild_id)
        ticket = guildDatabase.GetTicketById(self.ticketId)
        if ticket is None or int(ticket["channel_id"] or 0) != self.ticketChannelId or int(ticket["creator_id"]) != interaction.user.id:
            await EditEphemeralOriginalResponse(interaction, content="This replacement selection is no longer valid for this ticket.")
            return

        selectedMembers: list[discord.Member] = []
        for selected in self.values:
            selectedId = int(selected.id)
            member = interaction.guild.get_member(selectedId)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(selectedId)
                except discord.HTTPException:
                    member = None
            if member is None:
                await EditEphemeralOriginalResponse(interaction, content=f"I couldn't verify member `{selectedId}` in this server. Please choose current members again.")
                return
            if member.bot:
                await EditEphemeralOriginalResponse(interaction, content=f"{member.mention} is a bot. Please choose human server members only.")
                return
            selectedMembers.append(member)

        candidateIds = [member.id for member in selectedMembers]
        status, activeCount, originalCount, requiredCount = guildDatabase.SubmitReplacementCandidates(
            self.ticketId, interaction.user.id, candidateIds
        )
        if status != "requested":
            messages = {
                "not_eligible": f"Replacement selection is available only when exactly one helper remains. Current active helpers: {activeCount}/{originalCount}.",
                "already_requested": "A replacement request is already waiting for staff. Please wait for their decision.",
                "processing": "The ticket is being finalized or has a pending resolution. Please wait before requesting replacements.",
                "invalid_candidates": "Choose distinct human members who are not the requester, current helpers, or members of the original helper roster.",
                "wrong_candidate_count": f"You must choose exactly {requiredCount} replacement helper(s) to restore the original roster size.",
                "not_authorized": "Only the requester of this open ticket can propose replacement helpers.",
            }
            await EditEphemeralOriginalResponse(interaction, content=messages.get(status, f"Replacement request was not saved (status: {status})."))
            return

        channel = interaction.guild.get_channel(self.ticketChannelId)
        if not isinstance(channel, discord.TextChannel):
            await EditEphemeralOriginalResponse(interaction, content="The ticket channel is no longer available. Contact staff; your candidate selection was saved, but staff notification may need to be restored.")
            return

        staffRoleMentions = GetTicketStaffMentions(interaction.guild, guildDatabase)
        staffText = staffRoleMentions or "server staff"
        candidateMentions = ", ".join(member.mention for member in selectedMembers)
        try:
            requestMessage = await channel.send(
                f"🆘 <@{interaction.user.id}> requested replacement helpers: {candidateMentions}. {staffText}, please review this exact selection.\n"
                "Approve all selected candidates with `/admin_helper-replace approve`, or reject the request with `/admin_helper-replace disapprove`. "
                "No access or roster changes occur before approval; the original reserved price remains unchanged."
            )
            guildDatabase.SetReplacementRequestMessageId(self.ticketId, requestMessage.id)
        except discord.HTTPException:
            _logger.exception("Replacement candidates saved but staff notification failed: guild=%s ticket=%s", interaction.guild_id, self.ticketId)
            await EditEphemeralOriginalResponse(interaction, content="Your candidates were saved, but I couldn't notify staff in the ticket channel. Please alert a moderator; no roster changes have been made.")
            return

        if self.triggerMessageId:
            try:
                triggerMessage = await channel.fetch_message(self.triggerMessageId)
                await triggerMessage.edit(
                    content=f"✅ Replacement candidates submitted by <@{interaction.user.id}> and sent to staff for approval: {candidateMentions}. The reserved price is unchanged.",
                    view=None,
                )
            except discord.HTTPException:
                _logger.warning("Could not disable replacement selection button: guild=%s ticket=%s message=%s", interaction.guild_id, self.ticketId, self.triggerMessageId, exc_info=True)
        await DeleteEphemeralOriginalResponse(self.selectionPromptInteraction)
        await EditEphemeralOriginalResponse(interaction, content=f"✅ Replacement request submitted. Staff have been notified and must approve all {len(candidateIds)} selected candidate(s).")


class ReplacementCandidateView(discord.ui.View):
    def __init__(
        self,
        databaseManager: DatabaseManager,
        ticketId: int,
        ticketChannelId: int,
        requesterId: int,
        candidateCount: int,
        triggerMessageId: int | None,
        selectionPromptInteraction: discord.Interaction,
    ):
        super().__init__(timeout=180)
        self.add_item(ReplacementCandidateSelect(
            databaseManager, ticketId, ticketChannelId, requesterId,
            candidateCount, triggerMessageId, selectionPromptInteraction,
        ))


_activeTicketDeletionChannelIds: set[int] = set()
_logger = logging.getLogger(__name__)


async def DeleteTicketChannelAfterDelay(
    channel: discord.abc.GuildChannel,
    delaySeconds: int,
    reason: str,
    notice: str,
) -> None:
    """Notify ticket participants, then delete the channel even if sending fails."""
    channelId = channel.id
    try:
        try:
            await channel.send(notice)
        except discord.HTTPException:
            _logger.exception("Could not post ticket closing notice in channel %s", channelId)

        await asyncio.sleep(delaySeconds)
        try:
            await channel.delete(reason=reason)
        except discord.NotFound:
            pass
        except discord.HTTPException:
            _logger.exception("Could not delete closed ticket channel %s", channelId)
    finally:
        _activeTicketDeletionChannelIds.discard(channelId)


def ScheduleTicketChannelDeletion(
    channel: discord.abc.GuildChannel,
    delaySeconds: int,
    reason: str,
    notice: str,
) -> None:
    """Schedule cleanup once per channel without blocking the interaction reply."""
    if channel.id in _activeTicketDeletionChannelIds:
        return
    _activeTicketDeletionChannelIds.add(channel.id)
    asyncio.create_task(
        DeleteTicketChannelAfterDelay(channel, delaySeconds, reason, notice)
    )


async def PostResolutionPrompt(
    channel: discord.TextChannel,
    guildDatabase: GuildDatabase,
    ticket: object,
    resolutionType: str,
    requesterId: int,
    activeHelperIds: list[int],
    databaseManager: DatabaseManager,
) -> discord.Message:
    """Post helper-confirmation controls with the requester counted as approval #1."""
    currentTicket = guildDatabase.GetTicketById(int(ticket["ticket_id"]))  # type: ignore[index]
    if currentTicket is not None:
        ticket = currentTicket
    ticketNumber = int(ticket["ticket_number"] or 0)  # type: ignore[index]
    activeMentions = " ".join(f"<@{helperId}>" for helperId in activeHelperIds)
    if resolutionType == "complete":
        heading = "✅ Completion proposed"
        instruction = "The ticket pays its active helpers only after every active helper confirms. Any one rejection cancels the proposal."
    else:
        heading = "🛑 Cancellation proposed"
        instruction = "The reserved credits are refunded only after every active helper confirms. Any one rejection cancels the proposal."
    confirmationIds = guildDatabase._ParseIdCsv(str(ticket["resolution_confirmations"] or ""))  # type: ignore[index]
    requiredIds = set([int(requesterId), *activeHelperIds])
    confirmedCount = len(set(confirmationIds).intersection(requiredIds))
    requiredCount = len(requiredIds)
    prompt = await channel.send(
        content=(
            f"**{heading} — ticket #{ticketNumber:03d}**\n"
            f"Requester: <@{requesterId}> (their proposal counts as the first approval)\n"
            f"Active helpers: {activeMentions}\n{instruction}\n\n"
            f"**Progress:** {confirmedCount}/{requiredCount} participants approved.\n"
            "Only the assigned active helpers can confirm or reject. A helper may veto a proposal while it is still pending, even if they previously confirmed. Once everyone has approved and finalization begins, the decision is locked."
        ),
        view=TicketResolutionView(databaseManager, resolutionType),
    )
    if not guildDatabase.SetResolutionMessageId(int(ticket["ticket_id"]), prompt.id):  # type: ignore[index]
        await prompt.edit(
            content="This resolution proposal is no longer active. No credits were changed.",
            view=None,
        )
    return prompt


async def DisableResolutionPromptById(
    channel: discord.TextChannel,
    messageId: int | None,
    content: str | None = None,
) -> None:
    """Remove stale resolution controls after completion, rejection, expiry, or roster change."""
    if not messageId:
        return
    try:
        message = await channel.fetch_message(int(messageId))
        await message.edit(content=content if content is not None else message.content, view=None)
    except discord.NotFound:
        pass
    except discord.HTTPException:
        _logger.debug("Could not remove stale resolution controls in channel %s", channel.id, exc_info=True)


async def CompleteCurrentTicket(
    interaction: discord.Interaction,
    databaseManager: DatabaseManager,
    admin: bool = False,
) -> None:
    if interaction.guild_id is None or interaction.channel is None:
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return
    await DeferEphemeralResponse(interaction, thinking=True)
    guildDatabase = databaseManager.ForServer(interaction.guild_id)
    ticket = guildDatabase.GetTicketByChannel(interaction.channel.id)
    if ticket is None:
        await EditEphemeralOriginalResponse(interaction, content="This channel is not registered as a Blox Fruits ticket.")
        return
    if not admin and interaction.user.id != int(ticket["creator_id"]):
        await EditEphemeralOriginalResponse(interaction, content="Only the requester can propose ticket completion.")
        return
    if admin and not IsConfiguredTicketStaff(interaction, guildDatabase):
        await EditEphemeralOriginalResponse(interaction, content="You need Administrator or a configured moderator role to override ticket confirmations.")
        return
    if admin and guildDatabase.IsUserTicketParticipant(int(ticket["ticket_id"]), interaction.user.id):
        await EditEphemeralOriginalResponse(interaction, content="Staff overrides are disabled for ticket participants. Requesters, original/current helpers, and selected replacement candidates must use the normal ticket workflow; a configured staff member outside this ticket must handle an escalation.")
        return
    if ticket["status"] != "open":
        await EditEphemeralOriginalResponse(interaction, content="This ticket is already closed. No additional credits were changed.")
        return

    if not admin:
        result, activeHelperIds = guildDatabase.RequestTicketResolution(
            int(ticket["ticket_id"]), "complete", interaction.user.id
        )
        if result != "requested":
            message = (
                "There are no active helpers. Please ask a moderator to refund or resolve this ticket."
                if result == "no_active_helpers" else
                "A completion or cancellation proposal is already awaiting helper responses."
                if result == "existing_request" else
                "A replacement request is waiting for staff approval. Please wait before proposing completion or cancellation." if result == "replacement_pending" else
                "This ticket is already being finalized. Please wait for the result."
                if result == "processing" else
                "I couldn't start the completion request because this ticket is no longer open."
            )
            await EditEphemeralOriginalResponse(interaction, content=message)
            return
        try:
            await PostResolutionPrompt(
                interaction.channel, guildDatabase, ticket, "complete",
                interaction.user.id, activeHelperIds, databaseManager,
            )
        except discord.HTTPException:
            guildDatabase.ClearTicketResolutionRequest(int(ticket["ticket_id"]))
            _logger.exception("Could not post completion confirmation prompt for ticket %s", ticket["ticket_id"])
            await EditEphemeralOriginalResponse(interaction, content="I couldn't post the helper-confirmation message. No credits were moved; please retry or contact staff.")
            return
        await EditEphemeralOriginalResponse(interaction, content="Completion proposed. The ticket will be paid only after every active helper confirms.")
        return

    # A moderator's explicit /admin_complete remains an auditable override path.
    try:
        status, payouts = guildDatabase.CompleteTicket(
            int(ticket["ticket_id"]), actorUserId=interaction.user.id,
            note="moderator override completed ticket; helper confirmation bypassed",
        )
    except Exception:
        _logger.exception("Ticket completion failed for ticket %s", ticket["ticket_id"])
        await EditEphemeralOriginalResponse(interaction, content="I couldn't finish processing this ticket. Ask another moderator to check its status before retrying.")
        return
    if status != "completed":
        await EditEphemeralOriginalResponse(interaction, content="This ticket is already closed or could not be completed. No additional credits were changed.")
        return
    await DisableResolutionPromptById(
        interaction.channel, ticket["resolution_message_id"],
        "✅ A moderator resolved this ticket. This proposal is no longer active.",
    )
    ScheduleTicketChannelDeletion(
        interaction.channel, 15, "Blox Fruits ticket completed by moderator override",
        "🔒 A moderator completed this ticket. Credits were distributed and this channel will be deleted in 15 seconds.",
    )
    payoutSummary = ", ".join(f"<@{userId}>: {amount:,}" for userId, amount in payouts)
    unusedRefund = guildDatabase.GetCompletionRefundAmount(int(ticket["ticket_id"]))
    refundText = f" Unfilled helper-slot refund returned to requester: **{unusedRefund:,} credits**." if unusedRefund else ""
    await EditEphemeralOriginalResponse(interaction, content=f"✅ Moderator override complete. Credits distributed: {payoutSummary or 'none'}.{refundText}")


async def CancelUserTicket(interaction: discord.Interaction, databaseManager: DatabaseManager) -> None:
    """Requester button/command always follows normal helper-confirmation workflow."""
    if interaction.guild_id is None:
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return
    await DeferEphemeralResponse(interaction, thinking=True)
    guildDatabase = databaseManager.ForServer(interaction.guild_id)
    ticket = guildDatabase.GetTicketByChannel(interaction.channel.id) if interaction.channel else None
    if ticket is None or ticket["status"] != "open":
        ticket = guildDatabase.GetOpenTicketForUser(interaction.user.id)
    if ticket is None or ticket["status"] != "open":
        await EditEphemeralOriginalResponse(interaction, content="You don't have an open ticket in this server.")
        return

    # Being the server owner, an administrator, or a configured moderator never
    # turns this button/command into an override. Overrides are explicit commands
    # and are unavailable to anyone involved in the ticket.
    if interaction.user.id != int(ticket["creator_id"]):
        await EditEphemeralOriginalResponse(
            interaction,
            content=("Only the requester can propose cancellation through the normal workflow. "
                     "Configured staff who are not participants may use `/admin_refund` for an escalation."),
        )
        return

    ticketChannel = interaction.guild.get_channel(int(ticket["channel_id"])) if interaction.guild else None
    if not isinstance(ticketChannel, discord.TextChannel):
        await EditEphemeralOriginalResponse(interaction, content="I couldn't find the ticket channel. Please ask configured staff outside this ticket to review it.")
        return

    result, activeHelperIds = guildDatabase.RequestTicketResolution(
        int(ticket["ticket_id"]), "cancel", interaction.user.id
    )
    if result == "no_active_helpers":
        # There is nobody left to confirm; return reserved funds rather than strand them.
        status, amount = guildDatabase.RefundTicket(
            int(ticket["ticket_id"]), actorUserId=interaction.user.id,
            note="automatic refund because no active helpers remain",
        )
        if status == "refunded" and amount is not None:
            ScheduleTicketChannelDeletion(
                ticketChannel, 10, "Ticket cancelled after all helpers left",
                "🔒 No active helpers remain. The requester was refunded; this channel will be deleted in 10 seconds.",
            )
            await EditEphemeralOriginalResponse(interaction, content=f"All helpers have left. Your **{amount:,} credits** were refunded automatically.")
        else:
            await EditEphemeralOriginalResponse(interaction, content="The ticket was already resolved. No additional credits were changed.")
        return
    if result != "requested":
        message = (
            "A completion or cancellation proposal is already awaiting helper responses."
            if result == "existing_request" else
            "A replacement request is waiting for staff approval. Please wait before proposing completion or cancellation."
            if result == "replacement_pending" else
            "This ticket is already being finalized. Please wait for the result."
            if result == "processing" else
            "I couldn't start the cancellation request because this ticket is no longer open."
        )
        await EditEphemeralOriginalResponse(interaction, content=message)
        return
    try:
        await PostResolutionPrompt(
            ticketChannel, guildDatabase, ticket, "cancel",
            interaction.user.id, activeHelperIds, databaseManager,
        )
    except discord.HTTPException:
        guildDatabase.ClearTicketResolutionRequest(int(ticket["ticket_id"]))
        _logger.exception("Could not post cancellation confirmation prompt for ticket %s", ticket["ticket_id"])
        await EditEphemeralOriginalResponse(interaction, content="I couldn't post the helper-confirmation message. No credits were moved; please retry or contact staff.")
        return
    await EditEphemeralOriginalResponse(interaction, content="Cancellation proposed. The reserved credits will be refunded only after every active helper confirms.")


async def ConfirmTicketResolutionCurrent(interaction: discord.Interaction, databaseManager: DatabaseManager) -> None:
    if interaction.guild_id is None or interaction.channel is None or interaction.guild is None:
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return
    await DeferEphemeralResponse(interaction, thinking=True)
    db = databaseManager.ForServer(interaction.guild_id)
    ticket = db.GetTicketByChannel(interaction.channel.id)
    if ticket is None:
        await EditEphemeralOriginalResponse(interaction, content="This is not a registered ticket channel.")
        if isinstance(interaction.message, discord.Message):
            await interaction.message.edit(view=None, content="This proposal is no longer active.")
        return

    result, confirmed, required, resolutionType = db.ConfirmTicketResolution(int(ticket["ticket_id"]), interaction.user.id)
    promptMessage = interaction.message if isinstance(interaction.message, discord.Message) else None
    if result == "no_request":
        await EditEphemeralOriginalResponse(interaction, content="There is no pending resolution proposal. The requester must submit completion or cancellation first.")
        if promptMessage is not None:
            await promptMessage.edit(content="ℹ️ This proposal is no longer active. No credits were changed.", view=None)
        return
    if result == "expired":
        if promptMessage is not None:
            await promptMessage.edit(content="⌛ This proposal expired after 15 minutes. No credits were changed; the requester may submit a new request.", view=None)
        await interaction.channel.send("⌛ The completion/cancellation proposal expired after 15 minutes without every active helper confirming. No credits were changed.")
        await EditEphemeralOriginalResponse(interaction, content="That request expired after 15 minutes. No credits were changed.")
        return
    if result == "not_active_helper":
        await EditEphemeralOriginalResponse(interaction, content="Only a currently active helper assigned to this ticket can confirm it.")
        return
    if result == "duplicate":
        await EditEphemeralOriginalResponse(interaction, content=f"You've already confirmed this request ({confirmed}/{required}).")
        return
    if result == "processing":
        if promptMessage is not None:
            await promptMessage.edit(content="⏳ All required confirmations have been received. The ticket is being finalized.", view=None)
        await EditEphemeralOriginalResponse(interaction, content="All required confirmations have been received. The ticket is being finalized; please wait.")
        return
    if result not in {"confirmed", "ready"}:
        await EditEphemeralOriginalResponse(interaction, content="This ticket is no longer open, so the request cannot be confirmed.")
        if promptMessage is not None:
            await promptMessage.edit(view=None)
        return
    if result == "confirmed":
        await interaction.channel.send(f"👍 {interaction.user.mention} confirmed the {resolutionType} proposal ({confirmed}/{required} participants approved; requester included).")
        if promptMessage is not None:
            promptBase = promptMessage.content.split("\n\n**Progress:**")[0]
            await promptMessage.edit(
                content=f"{promptBase}\n\n**Progress:** {confirmed}/{required} participants approved (requester included).",
                view=TicketResolutionView(databaseManager, resolutionType),
            )
        await EditEphemeralOriginalResponse(interaction, content=f"Your confirmation was recorded ({confirmed}/{required}).")
        return

    try:
        if resolutionType == "complete":
            status, payouts = db.CompleteTicket(int(ticket["ticket_id"]), actorUserId=interaction.user.id, note="all active helpers confirmed completion")
            if status != "completed":
                if promptMessage is not None:
                    await promptMessage.edit(content="This ticket was resolved by another action. No duplicate payout was made.", view=None)
                await EditEphemeralOriginalResponse(interaction, content="The ticket was resolved by another action. No duplicate payout was made.")
                return
            summary = ", ".join(f"<@{userId}>: {amount:,}" for userId, amount in payouts)
            unusedRefund = db.GetCompletionRefundAmount(int(ticket["ticket_id"]))
            refundText = f" Unfilled helper-slot refund returned to requester: **{unusedRefund:,} credits**." if unusedRefund else ""
            if promptMessage is not None:
                await promptMessage.edit(content=f"✅ All active helpers approved completion. Credits distributed: {summary or 'none'}.{refundText}", view=None)
            ScheduleTicketChannelDeletion(interaction.channel, 15, "Blox Fruits ticket completed after helper confirmations", "🔒 All active helpers confirmed. Credits were distributed; this channel will be deleted in 15 seconds.")
            await interaction.channel.send(f"✅ All active helpers confirmed completion. Credits distributed: {summary or 'none'}.{refundText}")
            await EditEphemeralOriginalResponse(interaction, content=f"✅ Completion confirmed by all participants ({required}/{required}); credits paid.{refundText}")
        else:
            status, amount = db.RefundTicket(int(ticket["ticket_id"]), actorUserId=interaction.user.id, note="all active helpers confirmed cancellation")
            if status != "refunded" or amount is None:
                if promptMessage is not None:
                    await promptMessage.edit(content="This ticket was resolved by another action. No duplicate refund was made.", view=None)
                await EditEphemeralOriginalResponse(interaction, content="The ticket was resolved by another action. No duplicate refund was made.")
                return
            if promptMessage is not None:
                await promptMessage.edit(content=f"↩️ All active helpers approved cancellation. <@{ticket['creator_id']}> was refunded **{amount:,} credits**.", view=None)
            ScheduleTicketChannelDeletion(interaction.channel, 10, "Blox Fruits ticket cancelled after helper confirmations", "🔒 All active helpers confirmed cancellation. The requester was refunded; this channel will be deleted in 10 seconds.")
            await interaction.channel.send(f"↩️ All active helpers confirmed cancellation. <@{ticket['creator_id']}> was refunded **{amount:,} credits**.")
            await EditEphemeralOriginalResponse(interaction, content=f"✅ Cancellation confirmed by all participants ({required}/{required}); **{amount:,} credits** refunded.")
    except Exception:
        _logger.exception("Could not finalize helper-confirmed ticket %s", ticket["ticket_id"])
        if promptMessage is not None:
            try:
                await promptMessage.edit(content="⚠️ All confirmations were received, but final processing needs staff review. Do not retry payments manually.", view=None)
            except discord.HTTPException:
                _logger.exception("Could not disable resolution prompt for ticket %s", ticket["ticket_id"])
        await EditEphemeralOriginalResponse(interaction, content="The confirmation was recorded, but final processing failed. Please ask a moderator to resolve this ticket; do not retry payments manually.")


async def RejectTicketResolutionCurrent(interaction: discord.Interaction, databaseManager: DatabaseManager) -> None:
    if interaction.guild_id is None or interaction.channel is None:
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return
    await DeferEphemeralResponse(interaction, thinking=True)
    db = databaseManager.ForServer(interaction.guild_id)
    ticket = db.GetTicketByChannel(interaction.channel.id)
    if ticket is None:
        await EditEphemeralOriginalResponse(interaction, content="This is not a registered ticket channel.")
        if isinstance(interaction.message, discord.Message):
            await interaction.message.edit(view=None, content="This proposal is no longer active.")
        return
    result, resolutionType = db.RejectTicketResolution(int(ticket["ticket_id"]), interaction.user.id)
    promptMessage = interaction.message if isinstance(interaction.message, discord.Message) else None
    if result == "no_request":
        await EditEphemeralOriginalResponse(interaction, content="No pending resolution proposal exists. Wait for the requester to propose completion or cancellation.")
        if promptMessage is not None:
            await promptMessage.edit(content="ℹ️ This proposal is no longer active. No credits were changed.", view=None)
        return
    if result == "not_active_helper":
        await EditEphemeralOriginalResponse(interaction, content="Only an active assigned helper can reject this request.")
        return
    if result == "already_confirmed":
        if promptMessage is not None:
            await promptMessage.edit(content="⏳ All active helpers have confirmed. The ticket is being finalized.", view=None)
        await EditEphemeralOriginalResponse(interaction, content="All active helpers have already confirmed; this proposal can no longer be rejected.")
        return
    if result != "rejected":
        await EditEphemeralOriginalResponse(interaction, content="This ticket is no longer open.")
        if promptMessage is not None:
            await promptMessage.edit(view=None)
        return
    if promptMessage is not None:
        await promptMessage.edit(content=f"👎 {interaction.user.mention} rejected this {resolutionType} proposal. No payout or refund was made. The requester may discuss the issue and submit a new proposal.", view=None)
    await interaction.channel.send(f"👎 {interaction.user.mention} rejected the proposed {resolutionType} request. No payout or refund was made. The requester can discuss the issue and submit a new request, or staff can resolve it with an override command.")
    await EditEphemeralOriginalResponse(interaction, content=f"The {resolutionType} proposal was rejected. No credits were changed.")


async def EditTicketWorkflowMessage(
    channel: discord.TextChannel,
    messageId: int | None,
    content: str,
) -> None:
    """Update/disable a saved workflow message when its request is resolved."""
    if not messageId:
        return
    await _EditMessageOrLog(channel, messageId, content)


async def _RestoreMemberOverwriteAfterFailure(
    channel: discord.TextChannel,
    member: discord.Member,
    previousOverwrite: discord.PermissionOverwrite,
    reason: str,
) -> None:
    try:
        await channel.set_permissions(
            member,
            overwrite=None if previousOverwrite.is_empty() else previousOverwrite,
            reason=reason,
        )
    except discord.HTTPException:
        _logger.exception("Could not restore overwrite for member %s in channel %s", member.id, channel.id)


async def _EditMessageOrLog(
    channel: discord.TextChannel,
    messageId: int | None,
    content: str,
) -> None:
    if not messageId:
        return
    try:
        message = await channel.fetch_message(int(messageId))
        await message.edit(content=content, view=None)
    except discord.NotFound:
        pass
    except discord.HTTPException:
        _logger.warning("Could not update workflow message %s in channel %s", messageId, channel.id, exc_info=True)


async def LeaveTicketHelper(interaction: discord.Interaction, databaseManager: DatabaseManager) -> None:
    if interaction.guild_id is None or interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return
    await DeferEphemeralResponse(interaction, thinking=True)
    db = databaseManager.ForServer(interaction.guild_id)
    ticket = db.GetTicketByChannel(interaction.channel.id)
    if ticket is None:
        await EditEphemeralOriginalResponse(interaction, content="This is not a registered ticket channel.")
        return
    activeBefore = db._ParseIdCsv(str(ticket["active_helper_ids"]))
    if interaction.user.id not in activeBefore:
        await EditEphemeralOriginalResponse(interaction, content="Only an active assigned helper can leave this ticket.")
        return
    if int(ticket["resolution_locked"] or 0):
        await EditEphemeralOriginalResponse(interaction, content="This ticket is being finalized; you cannot leave while completion or cancellation is being processed.")
        return

    channel = interaction.channel
    botMember = interaction.guild.me
    if botMember is None and interaction.client.user is not None:
        botMember = interaction.guild.get_member(interaction.client.user.id)
    if botMember is None:
        await EditEphemeralOriginalResponse(interaction, content="I couldn't verify my server membership, so your helper status was not changed.")
        return
    effectivePermissions = channel.permissions_for(botMember)
    # discord.py's TextChannel.set_permissions endpoint requires MANAGE_ROLES;
    # MANAGE_CHANNELS alone is not sufficient for editing permission overwrites.
    if not effectivePermissions.manage_roles:
        _logger.error(
            "Helper-leave permission preflight failed: guild=%s channel=%s bot=%s "
            "effective_manage_roles=%s guild_manage_roles=%s effective_manage_channels=%s "
            "guild_manage_channels=%s category=%s",
            interaction.guild_id, channel.id, botMember.id,
            effectivePermissions.manage_roles, botMember.guild_permissions.manage_roles,
            effectivePermissions.manage_channels, botMember.guild_permissions.manage_channels,
            channel.category_id,
        )
        await EditEphemeralOriginalResponse(
            interaction,
            content=("I couldn't update this ticket's access, so your active-helper status has NOT changed. "
                     "Discord requires the bot to have Manage Roles to edit channel permission overwrites; "
                     "Manage Channels alone is not sufficient. Enable Manage Roles for the bot role and ensure "
                     "it is not denied by the ticket/category overrides, then try again."),
        )
        return

    previousOverwrite = channel.overwrites_for(interaction.user)
    try:
        # Revoke channel access first; never remove a helper from the payout roster if
        # Discord refuses to remove their access.
        await channel.set_permissions(
            interaction.user,
            overwrite=discord.PermissionOverwrite(view_channel=False, send_messages=False, read_message_history=False),
            reason="Helper leave request; revoke access before changing active roster",
        )
    except discord.HTTPException as error:
        _logger.exception(
            "Could not revoke departing helper access: guild=%s channel=%s user=%s "
            "http_status=%s discord_code=%s effective_manage_roles=%s guild_manage_roles=%s "
            "effective_manage_channels=%s guild_manage_channels=%s",
            interaction.guild_id, channel.id, interaction.user.id,
            getattr(error, "status", None), getattr(error, "code", None),
            effectivePermissions.manage_roles, botMember.guild_permissions.manage_roles,
            effectivePermissions.manage_channels, botMember.guild_permissions.manage_channels,
        )
        discordCode = getattr(error, "code", "unknown")
        await EditEphemeralOriginalResponse(
            interaction,
            content=(f"Discord refused the channel permission change (error code {discordCode}). "
                     "Your active-helper status has NOT changed. Discord requires Manage Roles to edit channel "
                     "permission overwrites; Manage Channels alone is insufficient. Check the bot's Manage Roles "
                     "permission and any ticket/category overrides. The full error is logged in the bot terminal."),
        )
        return

    try:
        result, activeIds, originalCount = db.LeaveTicketHelper(int(ticket["ticket_id"]), interaction.user.id)
    except Exception:
        await _RestoreMemberOverwriteAfterFailure(channel, interaction.user, previousOverwrite, "Restore helper access because roster transaction failed")
        _logger.exception("Could not update helper roster after permissions were revoked: ticket=%s", ticket["ticket_id"])
        await EditEphemeralOriginalResponse(interaction, content="The helper roster could not be updated. I restored your previous channel access; please try again or contact staff.")
        return

    if result != "left":
        await _RestoreMemberOverwriteAfterFailure(channel, interaction.user, previousOverwrite, "Restore helper access because leave was not accepted")
        message = "The ticket is being finalized; you can't change the helper roster right now." if result == "processing" else "This ticket is no longer open, so you cannot leave it."
        if result == "not_active_helper":
            message = "Only an active assigned helper can leave this ticket. Your previous channel access was restored."
        await EditEphemeralOriginalResponse(interaction, content=message)
        return

    await DisableResolutionPromptById(
        channel,
        ticket["resolution_message_id"],
        "ℹ️ The helper roster changed, so the previous resolution proposal was cancelled. No credits were moved; the requester may submit a new proposal.",
    )
    await _EditMessageOrLog(
        channel, ticket["replacement_request_message_id"],
        "ℹ️ The active helper roster changed, so the previous replacement request was cancelled. No roster or credit changes were made by that request.",
    )
    await _EditMessageOrLog(
        channel, ticket["replacement_button_message_id"],
        "ℹ️ The active helper roster changed; this replacement selection button is no longer current.",
    )

    if not activeIds:
        status, amount = db.RefundTicket(int(ticket["ticket_id"]), actorUserId=interaction.user.id, note="automatic refund because all helpers left")
        if status == "refunded" and amount is not None:
            ScheduleTicketChannelDeletion(channel, 10, "All helpers left ticket", "🔒 All helpers have left. The requester's reservation was refunded; this channel will be deleted in 10 seconds.")
            await channel.send(f"🚨 <@{ticket['creator_id']}> No active helpers remain. Your **{amount:,} reserved credits** have been refunded automatically.")
            roleMentions = GetTicketStaffMentions(interaction.guild, db)
            staffNotice = f"Staff review requested: {roleMentions}." if roleMentions else "Server staff: please review this ticket."
            await channel.send(f"{staffNotice} All helpers left ticket #{int(ticket['ticket_number'] or 0):03d}; the requester was automatically refunded.")
            try:
                requester = interaction.guild.get_member(int(ticket["creator_id"])) or await interaction.guild.fetch_member(int(ticket["creator_id"]))
                await requester.send(f"Your ticket in **{interaction.guild.name}** was closed because all helpers left. Your **{amount:,} reserved credits** were refunded automatically.")
            except (discord.HTTPException, AttributeError):
                _logger.info("Could not DM requester %s about all-helper departure", ticket["creator_id"])
            await EditEphemeralOriginalResponse(interaction, content="You left the ticket. No helpers remain, so the requester was refunded automatically.")
            return

    await channel.send(f"🚪 {interaction.user.mention} left the active helper roster. Remaining active helpers: {', '.join(f'<@{item}>' for item in activeIds)}.")
    updatedTicket = db.GetTicketById(int(ticket["ticket_id"]))
    if originalCount > 1 and len(activeIds) == 1 and int(ticket["creator_id"]) != interaction.user.id and not int(updatedTicket["replacement_requested"] or 0):
        buttonMessage = await channel.send(
            content=f"<@{ticket['creator_id']}> Only **one active helper** remains. Choose replacement helper(s) below. You must select exactly {originalCount - 1} new member(s); staff approval is required and the original reserved price will stay unchanged.",
            view=ReplacementRequestView(databaseManager),
        )
        db.SetReplacementButtonMessageId(int(ticket["ticket_id"]), buttonMessage.id)
    await EditEphemeralOriginalResponse(interaction, content="You've left this ticket and your access was revoked successfully.")


async def RequestTicketReplacements(interaction: discord.Interaction, databaseManager: DatabaseManager) -> None:
    if interaction.guild_id is None or interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return
    db = databaseManager.ForServer(interaction.guild_id)
    ticket = db.GetTicketByChannel(interaction.channel.id)
    if ticket is None:
        await SendEphemeralResponse(interaction, "This is not a registered ticket channel.", ephemeral=True)
        return
    status, activeCount, originalCount = db.CheckReplacementEligibility(int(ticket["ticket_id"]), interaction.user.id)
    if status != "eligible":
        if status == "processing":
            message = "This ticket has a pending resolution or is being finalized. Please wait."
        elif status == "already_requested":
            message = "Replacement candidates have already been submitted and are waiting for staff."
        elif status == "not_authorized":
            message = "Only the ticket requester can select replacement helpers."
        else:
            message = f"Replacement selection is available only when exactly one active helper remains and the original roster had multiple helpers (active: {activeCount}, original: {originalCount})."
        await SendEphemeralResponse(interaction, message, ephemeral=True)
        return
    activeIds = db._ParseIdCsv(str(ticket["active_helper_ids"]))
    candidateCount = len(db._ParseIdCsv(str(ticket["helper_ids"]))) - len(activeIds)
    await SendEphemeralResponse(
        interaction,
        f"Select exactly **{candidateCount} new member(s)** to propose as replacements. Staff will approve or disapprove your selection; they will not choose replacements for you.",
        view=ReplacementCandidateView(
            databaseManager, int(ticket["ticket_id"]), interaction.channel.id,
            int(interaction.user.id), candidateCount,
            interaction.message.id if isinstance(interaction.message, discord.Message) else None,
            interaction,
        ),
        ephemeral=True,
    )


async def RefundCurrentTicket(
    interaction: discord.Interaction,
    databaseManager: DatabaseManager,
) -> None:
    if interaction.guild_id is None or interaction.channel is None:
        await SendEphemeralResponse(interaction, GetServerOnlyMessage(), ephemeral=True)
        return

    await DeferEphemeralResponse(interaction, thinking=True)
    guildDatabase = databaseManager.ForServer(interaction.guild_id)
    ticket = guildDatabase.GetTicketByChannel(interaction.channel.id)
    if ticket is None:
        await EditEphemeralOriginalResponse(interaction, content="This is not a ticket channel.")
        return
    if not IsConfiguredTicketStaff(interaction, guildDatabase):
        await EditEphemeralOriginalResponse(
            interaction,
            content="You need Administrator or a configured moderator role to refund tickets.",
        )
        return
    if guildDatabase.IsUserTicketParticipant(int(ticket["ticket_id"]), interaction.user.id):
        await EditEphemeralOriginalResponse(
            interaction,
            content="Staff overrides are disabled for ticket participants. A configured staff member outside this ticket must handle the refund escalation.",
        )
        return

    try:
        status, amount = guildDatabase.RefundTicket(
            int(ticket["ticket_id"]),
            actorUserId=interaction.user.id,
            note="moderator refund",
        )
    except Exception:
        _logger.exception("Moderator refund failed for ticket %s", ticket["ticket_id"])
        await EditEphemeralOriginalResponse(interaction, 
            content="The refund failed due to an internal error. Please check the ticket status before trying again."
        )
        return

    if status != "refunded" or amount is None:
        await EditEphemeralOriginalResponse(interaction, 
            content="This ticket is not open or has already been refunded. No additional credits were changed."
        )
        return
    await DisableResolutionPromptById(
        interaction.channel, ticket["resolution_message_id"],
        "↩️ A moderator refunded this ticket. This proposal is no longer active.",
    )
    ScheduleTicketChannelDeletion(
        interaction.channel, 10, "Blox Fruits ticket refunded by staff override",
        f"🔒 A moderator refunded **{amount:,} credits** to <@{ticket['creator_id']}>. This channel will be deleted in 10 seconds.",
    )
    await EditEphemeralOriginalResponse(interaction, 
        content=f"↩️ Refunded **{amount:,} credits** to <@{ticket['creator_id']}>. The channel will be deleted in 10 seconds."
    )


def BuildHelpCenterEmbed(guildDatabase: GuildDatabase) -> discord.Embed:
    activeServices = guildDatabase.ListServices(activeOnly=True)
    serviceLines = [
        f"• **{str(service['name'])[:80]}** — {int(service['price']):,} credits per helper"
        for service in activeServices[:20]
    ]
    if len(activeServices) > 20:
        serviceLines.append(f"…and {len(activeServices) - 20} more event(s).")
    eventText = "\n".join(serviceLines) if serviceLines else "No events are currently enabled. Please contact a moderator."
    embed = discord.Embed(
        title="🍎 Blox Fruits Help Center",
        description=(
            "Use the buttons below to check your balance or create a help ticket.\n\n"
            "🎫 **Create Ticket** — Request help for a Blox Fruits event.\n"
            "💰 **Balance** — Check your credits in this server.\n\n"
            f"New accounts start with **{guildDatabase.GetDefaultJoinCredits():,} credits**. Existing balances do not change when this value is updated. Event prices are per helper; total reservation = listed price × selected helper count."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Enabled events · price per helper", value=eventText[:1024], inline=False)
    embed.set_footer(text="Prices are per helper. Active helpers earn one unit price; unfilled helper slots are refunded at completion.")
    return embed


async def PostOrUpdateHelpCenterPanel(
    guild: discord.Guild,
    targetChannel: discord.TextChannel,
    databaseManager: DatabaseManager,
) -> tuple[discord.Message, bool]:
    """Create or edit the saved public Help Center panel for a guild."""
    if targetChannel.guild.id != guild.id:
        raise ValueError("The Help Center channel must belong to this server.")
    guildDatabase = databaseManager.ForServer(guild.id)
    botMember = guild.me
    if botMember is None:
        raise RuntimeError("The bot's server membership could not be verified.")
    permissions = targetChannel.permissions_for(botMember)
    requiredPermissions = {
        "View Channel": permissions.view_channel,
        "Send Messages": permissions.send_messages,
        "Embed Links": permissions.embed_links,
        "Read Message History": permissions.read_message_history,
    }
    missingPermissions = [name for name, allowed in requiredPermissions.items() if not allowed]
    if missingPermissions:
        raise PermissionError("Missing channel permissions: " + ", ".join(missingPermissions))

    oldChannelText = guildDatabase.GetSetting("help_center_channel_id", "") or ""
    oldMessageText = guildDatabase.GetSetting("help_center_message_id", "") or ""
    wasUpdated = False
    oldChannelId = int(oldChannelText) if oldChannelText.isdigit() else 0
    oldMessageId = int(oldMessageText) if oldMessageText.isdigit() else 0
    if oldChannelId == targetChannel.id and oldMessageId:
        try:
            oldMessage = await targetChannel.fetch_message(oldMessageId)
            await oldMessage.edit(embed=BuildHelpCenterEmbed(guildDatabase), view=MainPanelView(databaseManager))
            panelMessage = oldMessage
            wasUpdated = True
        except discord.NotFound:
            panelMessage = await targetChannel.send(embed=BuildHelpCenterEmbed(guildDatabase), view=MainPanelView(databaseManager))
    else:
        # Post the new panel first. Only after it succeeds do we retire the previous one,
        # so a permission error cannot leave this guild with no working public panel.
        panelMessage = await targetChannel.send(embed=BuildHelpCenterEmbed(guildDatabase), view=MainPanelView(databaseManager))
        if oldChannelId and oldMessageId:
            oldChannel = guild.get_channel(oldChannelId)
            if isinstance(oldChannel, discord.TextChannel):
                try:
                    oldMessage = await oldChannel.fetch_message(oldMessageId)
                    await oldMessage.edit(
                        content=f"This Help Center panel has moved to {targetChannel.mention}.",
                        embed=None,
                        view=None,
                    )
                except discord.HTTPException:
                    # The new panel remains active even if the old message is no longer editable.
                    logger.warning("Could not retire old Help Center panel %s in guild %s", oldMessageId, guild.id)

    guildDatabase.SetSetting("help_center_channel_id", targetChannel.id)
    guildDatabase.SetSetting("help_center_message_id", panelMessage.id)
    return panelMessage, wasUpdated


async def RefreshOpenTicketViews(guild: discord.Guild, databaseManager: DatabaseManager) -> None:
    """Attach the current persistent workflow controls to existing open ticket messages."""
    db = databaseManager.ForServer(guild.id)
    botUser = guild.me
    if botUser is None:
        return
    for ticket in db.ListOpenTickets():
        channelId = ticket["channel_id"]
        if channelId is None:
            continue
        channel = guild.get_channel(int(channelId))
        if not isinstance(channel, discord.TextChannel):
            continue
        refreshed = False
        try:
            async for message in channel.history(limit=50):
                if message.author.id != botUser.id or not message.embeds:
                    continue
                if any((embed.title or "").startswith("🎫 Ticket #") for embed in message.embeds):
                    await message.edit(view=TicketView(databaseManager))
                    refreshed = True
                    break
            if not refreshed:
                activeIds = db._ParseIdCsv(str(ticket["active_helper_ids"]))
                helpers = " ".join(f"<@{helperId}>" for helperId in activeIds) or "No active helpers"
                service = db.GetService(str(ticket["event_key"]), activeOnly=False)
                eventName = str(service["name"]) if service is not None else str(ticket["event_key"])
                ticketNumber = int(ticket["ticket_number"] or 0)
                embed = discord.Embed(
                    title=f"🎫 Ticket #{ticketNumber:03d} — {eventName}",
                    description=(
                        f"**Requester:** <@{ticket['creator_id']}>\n"
                        f"**Active helpers:** {helpers}\n"
                        f"**Reserved:** {int(ticket['reserved_credits']):,} credits\n\n"
                        "Complete/cancel requests need confirmation from every active helper. "
                        "Helpers can leave; replacement helpers need staff approval."
                    ),
                    color=discord.Color.green(),
                )
                await channel.send(embed=embed, view=TicketView(databaseManager))

            # Restore a separate resolution-control message only when a proposal is pending.
            currentTicket = db.GetTicketById(int(ticket["ticket_id"]))
            resolutionType = str(currentTicket["resolution_type"] or "")
            if resolutionType in {"complete", "cancel"}:
                resolutionMessageId = currentTicket["resolution_message_id"]
                existingPrompt = None
                if resolutionMessageId:
                    try:
                        existingPrompt = await channel.fetch_message(int(resolutionMessageId))
                    except discord.NotFound:
                        existingPrompt = None
                if existingPrompt is None:
                    activeIds = db._ParseIdCsv(str(currentTicket["active_helper_ids"]))
                    existingPrompt = await PostResolutionPrompt(
                        channel, db, currentTicket, resolutionType,
                        int(currentTicket["creator_id"]), activeIds, databaseManager,
                    )
                else:
                    activeIds = db._ParseIdCsv(str(currentTicket["active_helper_ids"]))
                    confirmationIds = db._ParseIdCsv(str(currentTicket["resolution_confirmations"] or ""))
                    requiredIds = set([int(currentTicket["creator_id"]), *activeIds])
                    confirmedCount = len(set(confirmationIds).intersection(requiredIds))
                    requiredCount = len(requiredIds)
                    promptText = (
                        f"**{'✅ Completion' if resolutionType == 'complete' else '🛑 Cancellation'} proposed — "
                        f"ticket #{int(currentTicket['ticket_number'] or 0):03d}**\n"
                        f"Requester: <@{currentTicket['creator_id']}> (their proposal counts as the first approval)\n"
                        f"Active helpers: {' '.join(f'<@{helperId}>' for helperId in activeIds)}\n"
                        f"{'The ticket pays its active helpers only after every active helper confirms.' if resolutionType == 'complete' else 'The reserved credits are refunded only after every active helper confirms.'} Any one rejection cancels the proposal.\n\n"
                        f"**Progress:** {confirmedCount}/{requiredCount} participants approved.\n"
                        "Only active helpers assigned to this ticket can respond. A helper may veto a proposal while it is pending, even if they previously confirmed. Once everyone has approved and finalization begins, the decision is locked."
                    )
                    await existingPrompt.edit(content=promptText, view=TicketResolutionView(databaseManager, resolutionType))

            currentTicket = db.GetTicketById(int(ticket["ticket_id"]))
            originalIds = db._ParseIdCsv(str(currentTicket["helper_ids"]))
            activeIds = db._ParseIdCsv(str(currentTicket["active_helper_ids"]))
            if currentTicket["status"] == "open" and len(originalIds) > 1 and len(activeIds) == 1 and not int(currentTicket["replacement_requested"] or 0) and not str(currentTicket["resolution_type"] or ""):
                buttonMessageId = currentTicket["replacement_button_message_id"]
                buttonMessage = None
                if buttonMessageId:
                    try:
                        buttonMessage = await channel.fetch_message(int(buttonMessageId))
                    except discord.NotFound:
                        buttonMessage = None
                if buttonMessage is None:
                    buttonMessage = await channel.send(
                        content=f"<@{currentTicket['creator_id']}> Only **one active helper** remains. Choose exactly {len(originalIds) - 1} new member(s) to propose as replacements; staff approval is required and the reserved price stays unchanged.",
                        view=ReplacementRequestView(databaseManager),
                    )
                    db.SetReplacementButtonMessageId(int(currentTicket["ticket_id"]), buttonMessage.id)
                else:
                    await buttonMessage.edit(view=ReplacementRequestView(databaseManager))
        except discord.HTTPException:
            _logger.exception("Could not refresh the ticket controls for channel %s", channelId)


async def RefreshHelpCenterPanel(guild: discord.Guild, databaseManager: DatabaseManager) -> None:
    """Refresh the saved Help Center message if it still exists; never post to an unknown channel."""
    guildDatabase = databaseManager.ForServer(guild.id)
    try:
        channelId = int(guildDatabase.GetSetting("help_center_channel_id", "") or 0)
    except (TypeError, ValueError):
        return
    targetChannel = guild.get_channel(channelId) if channelId else None
    if not isinstance(targetChannel, discord.TextChannel):
        return
    await PostOrUpdateHelpCenterPanel(guild, targetChannel, databaseManager)


async def SetupViews(bot: discord.Client, databaseManager: DatabaseManager) -> None:
    """Register persistent views; callbacks resolve the database by guild ID."""
    bot.add_view(MainPanelView(databaseManager))
    bot.add_view(TicketView(databaseManager))
    bot.add_view(TicketResolutionView(databaseManager))
    bot.add_view(ReplacementRequestView(databaseManager))
    await SetupDashboardViews(bot, databaseManager)
