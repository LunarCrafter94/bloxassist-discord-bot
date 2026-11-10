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
    databaseBackend: str = "sqlite"
    databaseUrl: str = ""
    backupUserId: int | None = None
    backupEncryptionPassword: str = ""


def LoadRuntimeSettings() -> RuntimeSettings:
    """Load private credentials; keep the actual credentials.env out of Git."""
    projectRoot = Path(__file__).resolve().parents[2]
    # The general credentials.env replaces tokens.env. Older paths remain as
    # read-only compatibility fallbacks so existing deployments continue to start.
    credentialsFile = projectRoot / "private-configs" / "credentials.env"
    runtimeEnvFile = projectRoot / "private-configs" / "runtime.env"
    legacyEnvFile = projectRoot / "private-configs" / "tokens.env"
    if credentialsFile.is_file():
        envFile = credentialsFile
    elif runtimeEnvFile.is_file():
        envFile = runtimeEnvFile
    elif legacyEnvFile.is_file():
        envFile = legacyEnvFile
    else:
        # Keep first-run instructions and missing-token errors pointed at the
        # current filename even when the user has not copied the example yet.
        envFile = credentialsFile
    # Host-provided environment variables take precedence on managed hosts.
    # Local values still load from credentials.env when no process value exists.
    load_dotenv(envFile, override=False)

    discordToken = os.getenv("DISCORD_TOKEN", "").strip()
    guildIdText = os.getenv("GUILD_ID", "").strip()
    commandGuildId = int(guildIdText) if guildIdText else None
    databaseBackend = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower() or "sqlite"
    if databaseBackend not in {"sqlite", "postgresql"}:
        raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'postgresql'.")
    databaseUrl = os.getenv("DATABASE_URL", "").strip()
    if databaseBackend == "postgresql" and not databaseUrl:
        raise ValueError("DATABASE_URL is required when DATABASE_BACKEND=postgresql.")
    backupUserText = os.getenv("BACKUP_DISCORD_USER_ID", "").strip()
    backupUserId = int(backupUserText) if backupUserText else None
    backupEncryptionPassword = os.getenv("BACKUP_ENCRYPTION_PASSWORD", "").strip()

    return RuntimeSettings(
        projectRoot=projectRoot,
        envFile=envFile,
        discordToken=discordToken,
        commandGuildId=commandGuildId,
        databaseBackend=databaseBackend,
        databaseUrl=databaseUrl,
        backupUserId=backupUserId,
        backupEncryptionPassword=backupEncryptionPassword,
    )
