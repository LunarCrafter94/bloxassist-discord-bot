"""Utilities for short-lived private Discord interaction responses."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

import discord

EPHEMERAL_MESSAGE_TTL_SECONDS = 60
_logger = logging.getLogger(__name__)
_cleanupTasks: set[asyncio.Task[Any]] = set()
_originalResponseTasks: dict[int, asyncio.Task[Any]] = {}
_expiredInteractionIds: set[int] = set()
_expiredInteractionOrder: deque[int] = deque()
_EXPIRED_INTERACTION_CACHE_LIMIT = 512


def _IsExpiredInteraction(interaction: discord.Interaction) -> bool:
    return int(interaction.id) in _expiredInteractionIds


def _MarkExpiredInteraction(interaction: discord.Interaction, action: str, error: discord.NotFound) -> None:
    """Remember expired tokens so later response attempts do not add traceback spam."""
    if getattr(error, "code", None) != 10062:
        raise error
    interactionId = int(interaction.id)
    if interactionId not in _expiredInteractionIds:
        _expiredInteractionIds.add(interactionId)
        _expiredInteractionOrder.append(interactionId)
    while len(_expiredInteractionOrder) > _EXPIRED_INTERACTION_CACHE_LIMIT:
        oldId = _expiredInteractionOrder.popleft()
        _expiredInteractionIds.discard(oldId)
    _logger.warning(
        "Discord interaction expired before %s could be delivered (interaction=%s); "
        "the client may need to retry after its connection stabilizes.", action, interactionId,
    )


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
    if _IsExpiredInteraction(interaction):
        return None
    try:
        message = await interaction.edit_original_response(*args, **kwargs)
    except discord.NotFound as error:
        if getattr(error, "code", None) == 10008:
            # The ephemeral response may already have been removed by its TTL task
            # while a slower ticket finalization/transcript-retention pass ran.
            # Its absence must not turn an already-committed ticket operation into
            # a reported processing failure.
            _logger.debug(
                "Ephemeral original response %s no longer exists; skipping edit.",
                interaction.id,
            )
            return None
        _MarkExpiredInteraction(interaction, "editing the response", error)
        return None
    ScheduleEphemeralOriginalDeletion(interaction)
    return message


async def SendEphemeralResponse(
    interaction: discord.Interaction, *args: Any, **kwargs: Any
) -> Any:
    """Send an ephemeral original response and remove it after one minute."""
    kwargs.pop("ephemeral", None)
    kwargs.pop("delete_after", None)
    if _IsExpiredInteraction(interaction):
        return None
    try:
        response = await interaction.response.send_message(*args, ephemeral=True, **kwargs)
    except discord.NotFound as error:
        _MarkExpiredInteraction(interaction, "sending an ephemeral response", error)
        return None
    ScheduleEphemeralOriginalDeletion(interaction)
    return response


async def DeferEphemeralResponse(
    interaction: discord.Interaction, *args: Any, **kwargs: Any
) -> Any:
    """Defer privately and schedule the original response for automatic cleanup."""
    kwargs.pop("ephemeral", None)
    if _IsExpiredInteraction(interaction):
        return None
    try:
        response = await interaction.response.defer(*args, ephemeral=True, **kwargs)
    except discord.NotFound as error:
        _MarkExpiredInteraction(interaction, "deferring the response", error)
        return None
    ScheduleEphemeralOriginalDeletion(interaction)
    return response


async def SendEphemeralFollowup(
    interaction: discord.Interaction, *args: Any, **kwargs: Any
) -> discord.WebhookMessage | None:
    """Send a private follow-up and remove it after one minute."""
    kwargs.pop("ephemeral", None)
    kwargs.pop("wait", None)
    kwargs.pop("delete_after", None)
    if _IsExpiredInteraction(interaction):
        return None
    try:
        message = await interaction.followup.send(
            *args, ephemeral=True, wait=True, **kwargs
        )
    except discord.NotFound as error:
        _MarkExpiredInteraction(interaction, "sending a follow-up", error)
        return None
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
