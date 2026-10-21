"""Run the Discord bot with: python -m bloxfruits_helper_credit_bot"""

import logging

from .bot_client import CreateBot
from .settings import LoadRuntimeSettings


class OptionalVoiceWarningFilter(logging.Filter):
    """Hide missing optional voice-library notices when voice is not used."""

    _ignored_messages = (
        "PyNaCl is not installed, voice will NOT be supported",
        "davey is not installed, voice will NOT be supported",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "discord.client":
            message = record.getMessage()
            if any(message.startswith(prefix) for prefix in self._ignored_messages):
                return False
        return True


def Main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Voice is not used by this bot. Suppress only the two optional voice-library
    # notices; all other warnings and errors remain visible.
    logging.getLogger("discord.client").addFilter(OptionalVoiceWarningFilter())

    settings = LoadRuntimeSettings()
    print(f"Configuration file: {settings.envFile}")
    print(
        "Command sync target: "
        + (str(settings.commandGuildId) if settings.commandGuildId else "global slash commands")
    )
    if not settings.discordToken:
        raise RuntimeError(
            f"DISCORD_TOKEN is missing. Add it to {settings.envFile}; never share that file."
        )
    bot = CreateBot(settings)
    # Logging is configured above on the root logger. Do not let discord.py add
    # a second handler; otherwise Discord records propagate and appear twice.
    bot.run(settings.discordToken, log_handler=None)


if __name__ == "__main__":
    Main()
