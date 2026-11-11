"""Guild-scoped credit lookup operations used by bot commands."""

from __future__ import annotations

from ..database import DatabaseManager


class CreditService:
    """A small application service that always resolves storage by guild ID."""

    def __init__(self, databaseManager: DatabaseManager) -> None:
        self.databaseManager = databaseManager

    def GetBalance(self, guildId: int | None, userId: int) -> int:
        database = self.databaseManager.ForServer(guildId)
        return database.GetBalance(userId)
