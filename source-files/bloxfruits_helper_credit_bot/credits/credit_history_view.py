"""Interactive, ephemeral pagination for member credit history."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import discord

from ..interaction_utils import EditEphemeralOriginalResponse

logger = logging.getLogger(__name__)

CREDIT_HISTORY_PAGE_SIZE = 10
_CREDIT_HISTORY_FETCH_SIZE = CREDIT_HISTORY_PAGE_SIZE + 1
_VIEW_TIMEOUT_SECONDS = 55


def BuildCreditHistoryEmbed(
    rows: list[dict[str, Any]],
    *,
    targetUserId: int,
    targetLabel: str,
    page: int,
) -> discord.Embed:
    """Build one page of credit history from newest-first transaction rows."""
    embed = discord.Embed(
        title=f"📜 Credit history · {targetLabel}",
        color=discord.Color.blurple(),
        timestamp=discord.utils.utcnow(),
    )
    embed.description = (
        f"Member ID: {int(targetUserId)}\n"
        f"Showing page {int(page)} · {CREDIT_HISTORY_PAGE_SIZE} transactions per page. Newest first."
    )
    visibleRows = rows[:CREDIT_HISTORY_PAGE_SIZE]
    if not visibleRows:
        embed.description += "\nNo credit transactions were found on this page."
        return embed

    for row in visibleRows:
        transactionType = str(row["type"]).replace("_", " ").title()
        amountText = f"{int(row['amount']):,} credits"
        if row["type"] == "debt_repayment":
            amountText = f"−{amountText} (debt repayment)"
        elif row["type"] == "penalty_debt":
            amountText = f"−{amountText} (penalty)"
        elif row["to_user"] == targetUserId:
            amountText = f"+{amountText}"
        elif row["from_user"] == targetUserId:
            amountText = f"−{amountText}"
        note = str(row["note"] or "No note")[:180]
        embed.add_field(
            name=f"#{int(row['id'])} · {transactionType} · {amountText}",
            value=f"{row['created_at']}\n{note}",
            inline=False,
        )
    return embed


class CreditHistoryView(discord.ui.View):
    """A short-lived Previous/Next pager bound to the command invoker."""

    def __init__(
        self,
        database: Any,
        *,
        targetUserId: int,
        targetLabel: str,
        requesterUserId: int,
        guildId: int,
        page: int,
        originInteraction: discord.Interaction,
        staffAccessCheck: Callable[[discord.Interaction], bool],
    ) -> None:
        super().__init__(timeout=_VIEW_TIMEOUT_SECONDS)
        self.database = database
        self.targetUserId = int(targetUserId)
        self.targetLabel = str(targetLabel)
        self.requesterUserId = int(requesterUserId)
        self.guildId = int(guildId)
        self.page = max(1, int(page))
        self.originInteraction = originInteraction
        self.staffAccessCheck = staffAccessCheck
        self.hasNext = False
        self.embed = self._BuildCurrentPage()
        self._SyncButtons()

    @property
    def has_navigation(self) -> bool:
        """Whether at least one page transition is available."""
        return self.page > 1 or self.hasNext

    def _BuildCurrentPage(self) -> discord.Embed:
        rows = self.database.ListCreditTransactions(
            self.targetUserId,
            limit=_CREDIT_HISTORY_FETCH_SIZE,
            offset=(self.page - 1) * CREDIT_HISTORY_PAGE_SIZE,
        )
        self.hasNext = len(rows) > CREDIT_HISTORY_PAGE_SIZE
        return BuildCreditHistoryEmbed(
            rows,
            targetUserId=self.targetUserId,
            targetLabel=self.targetLabel,
            page=self.page,
        )

    def _SyncButtons(self) -> None:
        self.previous_button.disabled = self.page <= 1
        self.page_button.label = f"Page {self.page}"
        self.next_button.disabled = not self.hasNext

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Keep the ephemeral pager private to its invoker and recheck staff access."""
        if int(interaction.user.id) != self.requesterUserId:
            await interaction.response.send_message(
                "Only the person who opened this credit history can navigate it.",
                ephemeral=True,
            )
            return False
        if interaction.guild_id != self.guildId:
            await interaction.response.send_message(
                "This credit-history session is no longer valid in this server.",
                ephemeral=True,
            )
            return False
        if self.targetUserId != self.requesterUserId and not self.staffAccessCheck(interaction):
            await interaction.response.send_message(
                "Your staff access is no longer sufficient to view another member's credit history.",
                ephemeral=True,
            )
            self.stop()
            return False
        return True

    async def _Navigate(self, interaction: discord.Interaction, delta: int) -> None:
        nextPage = self.page + int(delta)
        if nextPage < 1:
            return
        self.page = nextPage
        self.embed = self._BuildCurrentPage()
        self._SyncButtons()
        if self.has_navigation:
            await interaction.response.edit_message(embed=self.embed, view=self)
        else:
            await interaction.response.edit_message(embed=self.embed, view=None)
            self.stop()

    @discord.ui.button(
        label="Previous",
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def previous_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._Navigate(interaction, -1)

    @discord.ui.button(
        label="Page 1",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        row=0,
    )
    async def page_button(
        self,
        _interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        # The disabled page indicator is intentionally non-interactive.
        return

    @discord.ui.button(
        label="Next",
        emoji="▶️",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        await self._Navigate(interaction, 1)

    async def on_timeout(self) -> None:
        """Disable stale controls before the ephemeral response expires."""
        self.disable_all_items()
        try:
            await EditEphemeralOriginalResponse(
                self.originInteraction,
                view=self,
            )
        except discord.HTTPException:
            logger.debug("Could not disable expired credit-history controls", exc_info=True)
