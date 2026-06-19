"""
Battle presentation service.

Sequence:
1. simulate_and_store() — runs combat, stores all rounds, returns BattleSession
2. start_presentation() — sends initial Discord message, updates session
3. advance_and_display() — edits the Discord message to show next round
4. finalize() — grants rewards, marks VICTORY/DEFEAT
5. cancel_battle() — marks session cancelled, unlocks assets

All state lives in MongoDB. Bot restarts resume from displayed_round_count.
"""
from __future__ import annotations
import asyncio
import functools
import random
from datetime import datetime, timezone

from beanie import PydanticObjectId

from models.battle_session import BattleSession
from engine.combat import run_battle_with_rounds
from utils.db_session import usable_session
from utils.battle_embeds import (
    build_initial_embed,
    build_battle_embed,
    build_final_embed,
    CancelBattleView,
)
from config.game_config import (
    BATTLE_DISPLAY_INTERVALS,
    BATTLE_FAST_DISPLAY_INTERVAL,
    MAX_ROUNDS,
    DISPLAY_INTERVAL,
    DISPLAY_MAX_UPDATES,
)
from utils.image_gen import generate_team_banner, _riot_id_from_name
from utils.battle_image_gen import generate_battle_image
from data.champion_roster import CHAMPION_ROSTER

BATTLE_BANNER_FILENAME = "team.png"
BATTLE_BANNER_URL = f"attachment://{BATTLE_BANNER_FILENAME}"


def _roster_riot_id(name: str) -> str:
    entry = CHAMPION_ROSTER.get(name, {})
    return entry.get("riot_id") or _riot_id_from_name(name)


async def simulate_and_store(
    owner_id: str,
    zone: str,
    player_units,
    enemy_units,
    battle_type: str,
    entry_cost: dict,
    session,
    max_rounds: int | None = None,
) -> BattleSession:
    seed = random.randint(0, 2 ** 31)
    loop = asyncio.get_event_loop()
    result, rounds = await loop.run_in_executor(
        None, functools.partial(run_battle_with_rounds, player_units, enemy_units, seed=seed, max_rounds=max_rounds)
    )

    # Thin stored rounds to at most DISPLAY_MAX_UPDATES evenly-spaced snapshots so
    # MongoDB documents stay small and advance_and_display never runs for hours.
    if len(rounds) > DISPLAY_MAX_UPDATES:
        step = len(rounds) / DISPLAY_MAX_UPDATES
        kept = [rounds[int(i * step)] for i in range(DISPLAY_MAX_UPDATES - 1)]
        kept.append(rounds[-1])  # always include the final round
        rounds = kept

    bs = BattleSession(
        owner_id=owner_id,
        zone=zone,
        battle_type=battle_type,
        status="CREATING",
        max_rounds=MAX_ROUNDS,
        simulated_round_count=len(rounds),
        displayed_round_count=0,
        battle_seed=seed,
        winner=result.winner,
        simulated_rounds=rounds,
        player_snapshot=[
            {
                "name": u.name,
                "hp_max": u.hp_max,
                "rank": getattr(u, "rank", "F"),
                "level": getattr(u, "level", 1),
                "riot_id": _roster_riot_id(u.name),
            }
            for u in player_units
        ],
        enemy_snapshot=[
            {
                "name": u.name,
                "hp_max": u.hp_max,
                "rank": getattr(u, "rank", ""),
                "level": getattr(u, "level", 0),
                "is_boss": getattr(u, "is_boss", False),
            }
            for u in enemy_units
        ],
        entry_cost_json=entry_cost or {},
    )
    await bs.insert(session=usable_session(session))
    return bs


async def start_presentation(
    battle_session: BattleSession,
    discord_channel,
    player_team_names: list[str],
    enemy_name: str,
    followup=None,
    reuse_message=None,
) -> "object":
    """Send (or reuse) the battle message and mark the session ACTIVE.

    If *reuse_message* is provided the existing Discord message is edited in
    place rather than a new message being sent — used by continuous dungeon runs
    so every floor updates the same embed.
    """
    banner_file = None
    banner_url = ""
    try:
        champions = [
            {
                "name": s.get("name", ""),
                "rank": s.get("rank", "F"),
                "level": s.get("level", 1),
                "riot_id": s.get("riot_id", ""),
            }
            for s in battle_session.player_snapshot
        ]
        if champions:
            import discord
            buf = await generate_team_banner(champions)
            banner_file = discord.File(buf, filename=BATTLE_BANNER_FILENAME)
            banner_url = BATTLE_BANNER_URL
    except Exception:
        banner_file = None
        banner_url = ""

    from utils.battle_embeds import _zone_key_for_name
    embed = build_initial_embed(
        battle_session.zone, player_team_names, enemy_name, battle_session.battle_type,
        banner_url=banner_url, zone_key=_zone_key_for_name(battle_session.zone),
    )
    view = CancelBattleView(str(battle_session.id), battle_session.owner_id)

    if reuse_message is not None:
        # Edit the existing message in place — clears old attachments then adds banner
        if banner_file is not None:
            await reuse_message.edit(embed=embed, view=view, attachments=[banner_file])
        else:
            await reuse_message.edit(embed=embed, view=view, attachments=[])
        message = reuse_message
    elif followup is not None:
        if banner_file is not None:
            message = await followup.send(embed=embed, view=view, file=banner_file)
        else:
            message = await followup.send(embed=embed, view=view)
    elif banner_file is not None:
        message = await discord_channel.send(embed=embed, view=view, file=banner_file)
    else:
        message = await discord_channel.send(embed=embed, view=view)

    battle_session.message_id = str(message.id)
    battle_session.channel_id = str(getattr(discord_channel, "id", ""))
    battle_session.static_image_url = banner_url
    battle_session.status = "ACTIVE"
    battle_session.last_updated_at = datetime.now(timezone.utc)
    await battle_session.save()
    return message


def _interval_for(battle_session: BattleSession) -> float:
    if battle_session.fast_display:
        return BATTLE_FAST_DISPLAY_INTERVAL
    return BATTLE_DISPLAY_INTERVALS.get(battle_session.battle_type, 1.0)


async def advance_and_display(
    battle_session_id: str,
    discord_bot,
    until_round: int | None = None,
    reward_fn=None,
) -> dict | None:
    """Edit the Discord message round-by-round, then finalize.

    discord_bot may be a discord.Client (to resolve the channel/message) or a
    direct message-like object exposing an async edit() method (used in tests).
    """
    bs = await BattleSession.get(PydanticObjectId(battle_session_id))
    if bs is None or bs.status != "ACTIVE":
        return

    message = await _resolve_message(bs, discord_bot)
    if message is None:
        await cancel_battle(str(bs.id), "CANCELLED_MESSAGE_DELETED", session=None)
        return

    interval = _interval_for(bs)
    raw_target = bs.simulated_round_count if until_round is None else min(until_round, bs.simulated_round_count)
    # Hard cap: never display more than DISPLAY_MAX_UPDATES rounds regardless of simulation length.
    target = min(raw_target, bs.displayed_round_count + DISPLAY_MAX_UPDATES)

    for idx in range(bs.displayed_round_count, target):
        # Re-check status for cooperative cancellation
        fresh = await BattleSession.get(bs.id)
        if fresh is None or fresh.status != "ACTIVE":
            return
        bs = fresh

        rs = bs.simulated_rounds[idx]
        player_names = [s["name"] for s in bs.player_snapshot]
        embed = build_battle_embed(bs, rs, bs.zone, player_names, banner_url="attachment://battle.png")

        # Generate per-round battle image (champion cards with HP/mana bars)
        battle_file = None
        player_u = rs.get("player_units")
        enemy_u = rs.get("enemy_units")
        if player_u and enemy_u:
            # Attach riot_id from snapshot for portrait lookup
            for u in player_u:
                if not u.get("riot_id"):
                    u["riot_id"] = _roster_riot_id(u.get("name", ""))
            for u in enemy_u:
                if not u.get("riot_id"):
                    u["riot_id"] = _roster_riot_id(u.get("name", ""))
            img_buf = await generate_battle_image(player_u, enemy_u)
            if img_buf:
                import discord as _discord
                battle_file = _discord.File(img_buf, filename="battle.png")

        try:
            if battle_file:
                await message.edit(embed=embed, attachments=[battle_file])
            else:
                await message.edit(embed=embed)
        except Exception:
            await cancel_battle(str(bs.id), "CANCELLED_MESSAGE_DELETED", session=None)
            return

        bs.displayed_round_count = idx + 1
        bs.current_round = rs["round"]
        bs.last_updated_at = datetime.now(timezone.utc)
        await bs.save()

        if interval > 0:
            await asyncio.sleep(interval)

    # Jump displayed count to end so finalize always triggers even when we capped display.
    if bs.displayed_round_count < bs.simulated_round_count:
        bs.displayed_round_count = bs.simulated_round_count
        await bs.save()
    return await finalize(bs, message, bs.rewards_json, session=None, reward_fn=reward_fn)


async def _resolve_message(bs: BattleSession, discord_bot):
    # Direct message-like object (tests / resume with message)
    if hasattr(discord_bot, "edit"):
        return discord_bot
    if discord_bot is None or not bs.channel_id or not bs.message_id:
        return None
    try:
        channel = discord_bot.get_channel(int(bs.channel_id))
        if channel is None:
            channel = await discord_bot.fetch_channel(int(bs.channel_id))
        return await channel.fetch_message(int(bs.message_id))
    except Exception:
        return None


async def finalize(
    battle_session: BattleSession,
    discord_channel,
    rewards: dict,
    session,
    reward_fn=None,
) -> dict | None:
    # Reload to ensure not cancelled in the meantime
    bs = await BattleSession.get(battle_session.id)
    if bs is None or bs.status != "ACTIVE":
        return

    # winner == 0: player win; winner == -1: draw (treat as player win — survived the time limit)
    player_won = bs.winner in (0, -1)
    bs.status = "VICTORY" if player_won else "DEFEAT"
    bs.reward_claimed = True
    bs.finished_at = datetime.now(timezone.utc)
    bs.last_updated_at = bs.finished_at
    await bs.save()

    granted = rewards or {}
    if reward_fn is not None:
        try:
            granted = await reward_fn()
        except Exception as _reward_err:
            import logging as _logging
            _logging.getLogger(__name__).exception("reward_fn failed: %s", _reward_err)
            granted = rewards or {}
        bs.rewards_json = granted or {}
        await bs.save()

    # Update battle message with final embed (rewards included inline)
    final_snap = bs.simulated_rounds[-1] if bs.simulated_rounds else None
    final_embed = build_final_embed(bs, final_snap, bs.zone, bs.winner, banner_url=bs.static_image_url, rewards=granted if player_won else None)
    edit_target = None
    if hasattr(discord_channel, "edit"):
        edit_target = discord_channel
    try:
        if edit_target is not None:
            await edit_target.edit(embed=final_embed, attachments=[], view=None)
    except Exception:
        pass

    return granted


async def cancel_battle(battle_session_id: str, reason: str, session) -> bool:
    bs = await BattleSession.get(PydanticObjectId(battle_session_id))
    if bs is None:
        return False
    if bs.reward_claimed or bs.status != "ACTIVE":
        return False

    bs.status = reason if reason.startswith("CANCELLED") else f"CANCELLED_{reason}"
    bs.cancellation_reason = reason
    bs.cancelled_at = datetime.now(timezone.utc)
    bs.last_updated_at = bs.cancelled_at
    await bs.save()
    return True


async def resume_battle_presentation(battle_session, bot) -> None:
    """Resume a battle that lost its worker (bot restart)."""
    message = await _resolve_message(battle_session, bot)
    if message is None:
        await cancel_battle(str(battle_session.id), "CANCELLED_MESSAGE_DELETED", session=None)
        return
    await advance_and_display(str(battle_session.id), message)
