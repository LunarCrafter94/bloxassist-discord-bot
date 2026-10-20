"""Run the Discord bot with: python RunBot.py"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

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

    async def Run() -> None:
        loop = asyncio.get_running_loop()

        def RequestGracefulStop() -> None:
            logging.getLogger(__name__).warning(
                "Received a termination signal; beginning graceful shutdown and final configured per-server backups."
            )
            asyncio.create_task(bot.close())

        # Linux hosts (including most bot-hosting platforms) send SIGTERM before
        # terminating a container. Handling it lets the bot close DB connections and
        # attempt the configured final backup. A forced kill can still interrupt this.
        if sys.platform != "win32":
            try:
                loop.add_signal_handler(signal.SIGTERM, RequestGracefulStop)
            except (NotImplementedError, RuntimeError):
                logging.getLogger(__name__).warning("SIGTERM handler could not be installed; shutdown backup is best-effort.")
        try:
            async with bot:
                await bot.start(settings.discordToken)
        finally:
            if sys.platform != "win32":
                try:
                    loop.remove_signal_handler(signal.SIGTERM)
                except (NotImplementedError, RuntimeError):
                    pass

    try:
        asyncio.run(Run())
    except KeyboardInterrupt:
        # asyncio.run cancels the main task on Ctrl+C. The ``async with bot``
        # block performs Client.close() during cancellation, which attempts the
        # configured shutdown backup. Swallow only the final terminal interrupt
        # so a normal operator stop does not print a traceback.
        logging.getLogger(__name__).info("Ctrl+C received; the bot shutdown path returned. Check preceding logs for the final-backup result.")


if __name__ == "__main__":
    Main()
