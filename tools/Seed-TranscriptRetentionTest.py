#!/usr/bin/env python3
"""Seed/check/clean a dedicated Discord test channel for transcript retention.

This utility is for a local SQLite development database only. It refuses to run
unless the supplied channel belongs to the supplied server and its name includes
"test" or "debug". Seeded posts and database tickets are marked with a unique run ID.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT_DEFAULT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT_DEFAULT / "source-files"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from dotenv import load_dotenv
from bloxfruits_helper_credit_bot.database import DatabaseManager
from bloxfruits_helper_credit_bot.settings import DEFAULT_JOIN_CREDITS, DEFAULT_SERVICES

FIXTURE_PREFIX = "BLOXASSIST_RETENTION_TEST::"
MESSAGE_PREFIX = "BLOXASSIST_TEST_TRANSCRIPT"
FIXTURE_COUNT = 100


def _load_token(project_root: Path) -> str:
    env_candidates = (
        project_root / "private-configs" / "credentials.env",
        project_root / "private-configs" / "runtime.env",
        project_root / "private-configs" / "tokens.env",
    )
    env_file = next((path for path in env_candidates if path.is_file()), env_candidates[0])
    if env_file.is_file():
        load_dotenv(env_file, override=False)
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError(f"DISCORD_TOKEN was not found in {env_file} or the process environment.")
    backend = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower() or "sqlite"
    if backend != "sqlite":
        raise RuntimeError("This debug utility only operates on a local SQLite database; DATABASE_BACKEND must be sqlite.")
    return token


def _make_manager(project_root: Path) -> DatabaseManager:
    return DatabaseManager(
        project_root / "data",
        defaultJoinCredits=DEFAULT_JOIN_CREDITS,
        defaultServices=DEFAULT_SERVICES,
        backend="sqlite",
    )


def _fixture_key(run_id: str, index: int | None = None) -> str:
    if index is None:
        return f"{FIXTURE_PREFIX}{run_id}::"
    return f"{FIXTURE_PREFIX}{run_id}::{index:03d}"


def _event_is_fixture(event_key: str, run_id: str) -> bool:
    return str(event_key).startswith(_fixture_key(run_id))


def _message_id_from_event(event_key: str) -> int | None:
    token = "::msg="
    text = str(event_key)
    if token not in text:
        return None
    try:
        return int(text.rsplit(token, 1)[1])
    except ValueError:
        return None


async def _delete_fixture_message(message: Any, not_found_error: type[BaseException]) -> bool:
    """Delete one fixture post; return False when retention already removed it."""
    try:
        # discord.py PartialMessage.delete() does not accept a reason keyword.
        await message.delete()
        return True
    except not_found_error:
        return False


async def _connect_discord(token: str):
    try:
        import discord
    except ImportError as error:
        raise RuntimeError("discord.py is required. Run this with the project's .venv Python.") from error
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token)
    return client, discord


async def _get_test_channel(client: Any, discord_module: Any, guild_id: int, channel_id: int, confirmation_id: int):
    if channel_id != confirmation_id:
        raise RuntimeError("--confirm-test-channel-id must exactly match --channel-id.")
    channel = await client.fetch_channel(channel_id)
    if not isinstance(channel, discord_module.TextChannel):
        raise RuntimeError("The target must be a normal Discord text channel, not a thread or forum.")
    if int(channel.guild.id) != int(guild_id):
        raise RuntimeError("The target channel does not belong to the supplied guild ID.")
    lowered = channel.name.casefold()
    if "test" not in lowered and "debug" not in lowered:
        raise RuntimeError("Safety check failed: the channel name must contain 'test' or 'debug'.")
    return channel


async def _seed(args, project_root: Path, token: str) -> None:
    client, discord_module = await _connect_discord(token)
    manager = _make_manager(project_root)
    try:
        channel = await _get_test_channel(
            client, discord_module, args.guild_id, args.channel_id, args.confirm_test_channel_id
        )
        db = manager.ForServer(args.guild_id)
        run_id = secrets.token_hex(5)
        fake_snowflake_component = int(run_id, 16)
        print(f"Seeding run {run_id}: {FIXTURE_COUNT} dummy transcript posts into #{channel.name}.")
        print("This takes about 1–2 minutes due to Discord message rate limits. Keep RunBot.py running on the same local database.")
        created = 0
        for index in range(1, FIXTURE_COUNT + 1):
            requester_id = 1_000_000_000_000_000_000 + fake_snowflake_component * 100 + index
            helper_id = 2_000_000_000_000_000_000 + fake_snowflake_component * 100 + index
            fake_channel_id = 8_000_000_000_000_000_000 + fake_snowflake_component * 100 + index
            event_key = _fixture_key(run_id, index)
            ticket_id = db.ReserveTicket(
                channelId=fake_channel_id,
                creatorId=requester_id,
                eventKey=event_key,
                helperIds=[helper_id],
                requiredCredits=0,
            )
            if ticket_id is None:
                raise RuntimeError(f"Could not create the dummy database ticket for item {index}.")
            status, _ = db.RefundTicket(ticket_id, note="development-only transcript retention fixture")
            if status != "refunded":
                raise RuntimeError(f"Could not close the dummy database ticket {ticket_id}: {status}.")

            content = f"{MESSAGE_PREFIX} run={run_id} item={index:03d}/{FIXTURE_COUNT} — TEST DATA ONLY; NOT A REAL TICKET."
            message = await channel.send(content, allowed_mentions=discord_module.AllowedMentions.none())
            db.Execute(
                "UPDATE tickets SET event_key = ? WHERE ticket_id = ?",
                (f"{event_key}::msg={int(message.id)}", int(ticket_id)),
            )
            db.SetTicketTranscriptMessage(int(ticket_id), int(channel.id), int(message.id))
            created += 1
            if created % 10 == 0:
                print(f"  created {created}/{FIXTURE_COUNT}")
            await asyncio.sleep(0.8)

        print("\nSeed complete.")
        print(f"Run ID: {run_id}")
        print(f"Test guild: {args.guild_id}; channel: #{channel.name} ({channel.id})")
        print("NEXT: Complete or cancel one ordinary test ticket while RunBot.py uses this same local database.")
        print("THEN: Run the check command with --run-id shown above. After checking, run cleanup with the same run ID.")
        print("Do not use a production ticket or production transcript channel for this test.")
    finally:
        manager.CloseAll()
        await client.close()


async def _check(args, project_root: Path, token: str) -> None:
    client, discord_module = await _connect_discord(token)
    manager = _make_manager(project_root)
    try:
        channel = await _get_test_channel(
            client, discord_module, args.guild_id, args.channel_id, args.confirm_test_channel_id
        )
        db = manager.ForServer(args.guild_id)
        fixture_prefix = _fixture_key(args.run_id)
        fixtures = db.Execute(
            "SELECT * FROM tickets WHERE substr(event_key, 1, ?) = ? ORDER BY ticket_id",
            (len(fixture_prefix), fixture_prefix), fetchAll=True,
        )
        print(f"Debug run: {args.run_id}")
        print(f"Fixture rows: {len(fixtures)} (expected {FIXTURE_COUNT})")
        cleared = [row for row in fixtures if row["transcript_saved"] and row["transcript_message_id"] is None]
        print(f"Dummy fixture rows whose transcript pointer was cleared: {len(cleared)}")

        oldest_id = _message_id_from_event(fixtures[0]["event_key"]) if fixtures else None
        newest_id = _message_id_from_event(fixtures[-1]["event_key"]) if fixtures else None

        async def exists(message_id: int | None) -> bool:
            if message_id is None:
                return False
            try:
                await channel.fetch_message(message_id)
                return True
            except discord_module.NotFound:
                return False

        oldest_exists = await exists(oldest_id)
        newest_exists = await exists(newest_id)
        print(f"Oldest dummy Discord message exists: {oldest_exists}")
        print(f"Newest dummy Discord message exists: {newest_exists}")

        if fixtures:
            max_fixture_ticket_id = int(fixtures[-1]["ticket_id"])
            real_rows = db.Execute(
                "SELECT COUNT(*) AS amount FROM tickets "
                "WHERE ticket_id > ? AND transcript_saved = 1 AND transcript_channel_id = ? "
                "AND transcript_message_id IS NOT NULL AND substr(event_key, 1, ?) <> ?",
                (max_fixture_ticket_id, int(channel.id), len(fixture_prefix), fixture_prefix),
                fetchOne=True,
            )
            real_count = int(real_rows["amount"] or 0)
        else:
            real_count = 0
        print(f"Real (non-fixture) transcript rows created since seeding: {real_count}")

        passed = (
            len(fixtures) == FIXTURE_COUNT
            and len(cleared) >= 1
            and oldest_id is not None and not oldest_exists
            and newest_id is not None and newest_exists
            and real_count >= 1
        )
        print("RESULT: PASS — retention evidence matches the expected behavior." if passed else
              "RESULT: NOT CONFIRMED — complete/cancel one ordinary test ticket in the running bot, then check again.")
    finally:
        manager.CloseAll()
        await client.close()


async def _cleanup(args, project_root: Path, token: str) -> None:
    if args.confirm_run_id != args.run_id:
        raise RuntimeError("--confirm-run-id must exactly match --run-id.")
    client, discord_module = await _connect_discord(token)
    manager = _make_manager(project_root)
    try:
        channel = await _get_test_channel(
            client, discord_module, args.guild_id, args.channel_id, args.confirm_test_channel_id
        )
        db = manager.ForServer(args.guild_id)
        marker = f"{MESSAGE_PREFIX} run={args.run_id} "
        deleted_messages = 0
        already_missing_messages = 0
        # Delete only messages authored by this bot that contain this exact run marker.
        # Retention may already have removed the oldest fixture posts, so missing
        # messages are expected and must not block removal of the matching DB fixtures.
        async for message in channel.history(limit=1000, oldest_first=True):
            if message.author.id == client.user.id and marker in message.content:
                if await _delete_fixture_message(message, discord_module.NotFound):
                    deleted_messages += 1
                else:
                    already_missing_messages += 1
                await asyncio.sleep(0.35)

        fixture_prefix = _fixture_key(args.run_id)
        with db.databaseLock:
            db.connection.execute("BEGIN IMMEDIATE")
            try:
                fixtures = db.connection.execute(
                    "SELECT ticket_id, creator_id, helper_ids, active_helper_ids, replacement_candidate_ids "
                    "FROM tickets WHERE substr(event_key, 1, ?) = ?",
                    (len(fixture_prefix), fixture_prefix),
                ).fetchall()
                ticket_ids = [int(row["ticket_id"]) for row in fixtures]
                user_ids: set[int] = set()
                for row in fixtures:
                    user_ids.add(int(row["creator_id"]))
                    for column in ("helper_ids", "active_helper_ids", "replacement_candidate_ids"):
                        for raw_id in str(row[column] or "").split(","):
                            try:
                                user_ids.add(int(raw_id.strip()))
                            except ValueError:
                                pass
                for start in range(0, len(ticket_ids), 400):
                    batch = ticket_ids[start:start + 400]
                    placeholders = ",".join("?" for _ in batch)
                    db.connection.execute(
                        f"DELETE FROM transactions WHERE ticket_id IN ({placeholders})", tuple(batch)
                    )
                for start in range(0, len(ticket_ids), 400):
                    batch = ticket_ids[start:start + 400]
                    placeholders = ",".join("?" for _ in batch)
                    db.connection.execute(f"DELETE FROM tickets WHERE ticket_id IN ({placeholders})", tuple(batch))
                user_list = sorted(user_ids)
                for start in range(0, len(user_list), 400):
                    batch = user_list[start:start + 400]
                    placeholders = ",".join("?" for _ in batch)
                    db.connection.execute(
                        f"DELETE FROM transactions WHERE from_user IN ({placeholders}) "
                        f"OR to_user IN ({placeholders}) OR actor_user_id IN ({placeholders})",
                        tuple(batch) * 3,
                    )
                    db.connection.execute(f"DELETE FROM users WHERE user_id IN ({placeholders})", tuple(batch))
                db.connection.commit()
            except Exception:
                db.connection.rollback()
                raise

        print(f"Cleanup complete for run {args.run_id}.")
        print(f"Deleted dummy Discord posts: {deleted_messages}.")
        print(f"Already-pruned/missing dummy Discord posts: {already_missing_messages}.")
        print(f"Deleted dummy ticket rows: {len(ticket_ids)}; removed their test-only ledger rows and synthetic accounts.")
    finally:
        manager.CloseAll()
        await client.close()


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("seed", "check", "cleanup"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--guild-id", type=int, required=True)
        sub.add_argument("--channel-id", type=int, required=True)
        sub.add_argument("--confirm-test-channel-id", type=int, required=True)
        if command in ("check", "cleanup"):
            sub.add_argument("--run-id", required=True)
        if command == "cleanup":
            sub.add_argument("--confirm-run-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    project_root = args.project_root.resolve()
    token = _load_token(project_root)
    try:
        if args.command == "seed":
            asyncio.run(_seed(args, project_root, token))
        elif args.command == "check":
            asyncio.run(_check(args, project_root, token))
        else:
            asyncio.run(_cleanup(args, project_root, token))
    except KeyboardInterrupt:
        print("\nInterrupted. Some fixture data may remain; rerun cleanup with the same run ID if one was printed.")
        return 130
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
