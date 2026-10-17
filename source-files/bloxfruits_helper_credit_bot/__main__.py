"""Run the Discord bot with: python -m bloxfruits_helper_credit_bot"""

import logging

from .bot_client import CreateBot
from .settings import LoadRuntimeSettings


def Main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
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
