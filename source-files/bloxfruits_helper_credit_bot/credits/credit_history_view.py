"""Credit-history page builder and compatibility wrapper around the shared paginator."""

from __future__ import annotations

from typing import Any, Callable

import discord

from ..pagination import EphemeralPaginator

CREDIT_HISTORY_PAGE_SIZE = 10
_CREDIT_HISTORY_FETCH_SIZE = CREDIT_HISTORY_PAGE_SIZE + 1


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


class CreditHistoryView(EphemeralPaginator):
    """Compatibility wrapper that supplies member credit-history pages."""

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
        normalizedTargetId = int(targetUserId)

        def LoadPage(pageNumber: int) -> tuple[discord.Embed, bool]:
            rows = database.ListCreditTransactions(
                normalizedTargetId,
                limit=_CREDIT_HISTORY_FETCH_SIZE,
                offset=(pageNumber - 1) * CREDIT_HISTORY_PAGE_SIZE,
            )
            return (
                BuildCreditHistoryEmbed(
                    rows,
                    targetUserId=normalizedTargetId,
                    targetLabel=targetLabel,
                    page=pageNumber,
                ),
                len(rows) > CREDIT_HISTORY_PAGE_SIZE,
            )

        accessCheck = (
            None
            if normalizedTargetId == int(requesterUserId)
            else staffAccessCheck
        )
        super().__init__(
            LoadPage,
            page=page,
            requesterUserId=requesterUserId,
            guildId=guildId,
            originInteraction=originInteraction,
            accessCheck=accessCheck,
        )
