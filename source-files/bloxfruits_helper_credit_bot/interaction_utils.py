"""Utilities for short-lived private Discord interaction responses."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

EPHEMERAL_MESSAGE_TTL_SECONDS = 60
_logger = logging.getLogger(__name__)
_cleanupTasks: set[asyncio.Task[Any]] = set()
_originalResponseTasks: dict[int, asyncio.Task[Any]] = {}


def _KeepTask(task: asyncio.Task[Any]) -> None:
    _cleanupTasks.add(task)
    task.add_done_callback(_cleanupTasks.discard)


async def _DeleteOriginalResponseLater(
    interaction: discord.Interaction, delaySeconds: int
) -> None:
    await asyncio.sleep(delaySeconds)
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        _logger.debug(
            "Could not delete ephemeral interaction response %s", interaction.id,
            exc_info=True,
        )


async def _DeleteWebhookMessageLater(
    message: discord.WebhookMessage, delaySeconds: int
) -> None:
    await asyncio.sleep(delaySeconds)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        _logger.debug("Could not delete ephemeral follow-up %s", message.id, exc_info=True)


def ScheduleEphemeralOriginalDeletion(
    interaction: discord.Interaction, delaySeconds: int = EPHEMERAL_MESSAGE_TTL_SECONDS
) -> None:
    """Delete this interaction's ephemeral original response after the TTL.

    Re-scheduling resets the countdown from the latest content update, so a slower
    ticket creation does not delete its pending response while it is still processing.
    """
    previousTask = _originalResponseTasks.pop(interaction.id, None)
    if previousTask is not None and not previousTask.done():
        previousTask.cancel()

    task = asyncio.create_task(_DeleteOriginalResponseLater(interaction, delaySeconds))
    _originalResponseTasks[interaction.id] = task
    _KeepTask(task)

    def ClearTask(completedTask: asyncio.Task[Any]) -> None:
        if _originalResponseTasks.get(interaction.id) is completedTask:
            _originalResponseTasks.pop(interaction.id, None)

    task.add_done_callback(ClearTask)


async def EditEphemeralOriginalResponse(
    interaction: discord.Interaction, *args: Any, **kwargs: Any
) -> Any:
    """Edit an ephemeral original response and restart its one-minute TTL."""
    message = await interaction.edit_original_response(*args, **kwargs)
    ScheduleEphemeralOriginalDeletion(interaction)
    return message


async def SendEphemeralResponse(
    interaction: discord.Interaction, *args: Any, **kwargs: Any
) -> Any:
    """Send an ephemeral original response and remove it after one minute."""
    kwargs.pop("ephemeral", None)
    kwargs.pop("delete_after", None)
    response = await interaction.response.send_message(*args, ephemeral=True, **kwargs)
    ScheduleEphemeralOriginalDeletion(interaction)
    return response


async def DeferEphemeralResponse(
    interaction: discord.Interaction, *args: Any, **kwargs: Any
) -> Any:
    """Defer privately and schedule the original response for automatic cleanup."""
    kwargs.pop("ephemeral", None)
    response = await interaction.response.defer(*args, ephemeral=True, **kwargs)
    ScheduleEphemeralOriginalDeletion(interaction)
    return response


async def SendEphemeralFollowup(
    interaction: discord.Interaction, *args: Any, **kwargs: Any
) -> discord.WebhookMessage:
    """Send a private follow-up and remove it after one minute."""
    kwargs.pop("ephemeral", None)
    kwargs.pop("wait", None)
    kwargs.pop("delete_after", None)
    message = await interaction.followup.send(
        *args, ephemeral=True, wait=True, **kwargs
    )
    _KeepTask(asyncio.create_task(_DeleteWebhookMessageLater(message, EPHEMERAL_MESSAGE_TTL_SECONDS)))
    return message


async def DeleteEphemeralOriginalResponse(
    interaction: discord.Interaction,
) -> None:
    """Delete a prior ephemeral interaction response immediately when needed."""
    scheduledTask = _originalResponseTasks.pop(interaction.id, None)
    if scheduledTask is not None and not scheduledTask.done():
        scheduledTask.cancel()
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        _logger.debug(
            "Could not immediately delete ephemeral interaction response %s", interaction.id,
            exc_info=True,
        )


async def DeleteEphemeralOriginalResponses(
    interactions: list[discord.Interaction],
) -> None:
    """Delete a ticket wizard's previous ephemeral steps without failing the flow."""
    for interaction in interactions:
        await DeleteEphemeralOriginalResponse(interaction)
