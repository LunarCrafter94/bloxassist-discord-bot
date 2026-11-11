"""Reusable private paginator for BloxAssist history and staff-list commands."""

from __future__ import annotations

import logging
from collections.abc import Callable

import discord

from .interaction_utils import EditEphemeralOriginalResponse

logger = logging.getLogger(__name__)

PaginatorPageLoader = Callable[[int], tuple[discord.Embed, bool]]
PaginatorAccessCheck = Callable[[discord.Interaction], bool]

PAGINATOR_TIMEOUT_SECONDS = 55


class EphemeralPaginator(discord.ui.View):
    """Previous/Next controls for an ephemeral, invoker-bound paginated embed.

    pageLoader receives a 1-based page number and returns its embed plus a
    boolean indicating whether another page exists. accessCheck is evaluated
    on every button interaction, not just when the command is first invoked.
    """

    def __init__(
        self,
        pageLoader: PaginatorPageLoader,
        *,
        page: int,
        requesterUserId: int,
        guildId: int,
        originInteraction: discord.Interaction,
        accessCheck: PaginatorAccessCheck | None = None,
    ) -> None:
        super().__init__(timeout=PAGINATOR_TIMEOUT_SECONDS)
        self.pageLoader = pageLoader
        self.page = max(1, int(page))
        self.requesterUserId = int(requesterUserId)
        self.guildId = int(guildId)
        self.originInteraction = originInteraction
        self.accessCheck = accessCheck
        self.embed, self.hasNext = self.pageLoader(self.page)
        self._SyncButtons()

    @property
    def has_navigation(self) -> bool:
        """Whether the current page can move backward or forward."""
        return self.page > 1 or self.hasNext

    def _SyncButtons(self) -> None:
        self.previous_button.disabled = self.page <= 1
        self.page_button.label = f"Page {self.page}"
        self.next_button.disabled = not self.hasNext

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restrict controls to the invoker and recheck command-specific access."""
        if int(interaction.user.id) != self.requesterUserId:
            await interaction.response.send_message(
                "Only the person who opened this list can navigate it.",
                ephemeral=True,
            )
            return False
        if interaction.guild_id != self.guildId:
            await interaction.response.send_message(
                "This pagination session is no longer valid in this server.",
                ephemeral=True,
            )
            return False
        if self.accessCheck is not None and not self.accessCheck(interaction):
            await interaction.response.send_message(
                "Your access to this list is no longer authorized.",
                ephemeral=True,
            )
            self.stop()
            return False
        return True

    async def _Navigate(self, interaction: discord.Interaction, delta: int) -> None:
        nextPage = self.page + int(delta)
        if nextPage < 1 or (delta > 0 and not self.hasNext):
            return
        try:
            nextEmbed, nextHasNext = self.pageLoader(nextPage)
        except Exception:
            logger.exception(
                "Could not load paginated response: guild=%s requester=%s page=%s",
                self.guildId, self.requesterUserId, nextPage,
            )
            await interaction.response.send_message(
                "I couldn't load that page. Please try again.",
                ephemeral=True,
            )
            return

        self.page = nextPage
        self.embed = nextEmbed
        self.hasNext = bool(nextHasNext)
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
        """Disable stale controls while leaving the private result readable."""
        for item in self.children:
            item.disabled = True
        try:
            await EditEphemeralOriginalResponse(
                self.originInteraction,
                view=self,
            )
        except discord.HTTPException:
            logger.debug("Could not disable timed-out pagination controls", exc_info=True)
