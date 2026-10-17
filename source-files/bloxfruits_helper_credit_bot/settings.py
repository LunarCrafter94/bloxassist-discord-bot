"""Application defaults and runtime environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_JOIN_CREDITS = 100
MAX_HELPERS = 5
MAX_CONFIGURABLE_HELPERS = 25
DEFAULT_INVITE_REWARD_CREDITS = 50
DEFAULT_INVITE_DURATION_MINUTES = 60
TICKET_CATEGORY_NAME = "Blox Fruits Tickets"

# (service key, display name, initial price). Defaults are seeded separately
# into each guild database and can later be changed through that guild's admin UI.
DEFAULT_SERVICES = (
    ("v4_trials", "V4 Trials", 200),
    ("leviathan", "Leviathan", 100),
    ("mirage", "Mirage Island", 100),
    ("race_awakening", "Race Awakening", 200),
    ("cake_prince", "Cake Prince", 100),
    ("dough_king", "Dough King", 100),
    ("sea_events", "Sea Events", 100),
)


@dataclass(frozen=True)
class RuntimeSettings:
    projectRoot: Path
    envFile: Path
    discordToken: str
    commandGuildId: int | None


def LoadRuntimeSettings() -> RuntimeSettings:
    """Load the local tokens.env file without committing its real contents."""
    projectRoot = Path(__file__).resolve().parents[2]
    envFile = projectRoot / "private-configs" / "tokens.env"
    load_dotenv(envFile, override=True)

    discordToken = os.getenv("DISCORD_TOKEN", "").strip()
    guildIdText = os.getenv("GUILD_ID", "").strip()
    commandGuildId = int(guildIdText) if guildIdText else None

    return RuntimeSettings(
        projectRoot=projectRoot,
        envFile=envFile,
        discordToken=discordToken,
        commandGuildId=commandGuildId,
    )
