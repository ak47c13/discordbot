"""
Champion service: fusion, leveling, acquisition.
All economy operations use MongoDB sessions (transactions).
"""
from __future__ import annotations
import random
from typing import Optional

from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.champion import ChampionInstance
from models.user import User
from models.audit_log import AuditLog
from data.champion_roster import CHAMPION_ROSTER


def _roster_fields(name: str) -> dict:
    """Return riot_id/title/source_roles from the roster for a champion name."""
    entry = CHAMPION_ROSTER.get(name, {})
    return {
        "riot_id": entry.get("riot_id", ""),
        "title": entry.get("title", ""),
        "source_roles": list(entry.get("source_roles", [])),
    }
from config.game_config import (
    RANKS,
    RANK_INDEX,
    CHAMPION_FUSION_COST,
    CHAMPION_MAX_LEVEL,
    LEVEL_UP_GOLD_COST,
    CHAMPION_BASE_STATS,
    CHAMPION_GROWTH_STATS,
    levelup_cost,
    levelup_cost_range,
)
from utils.counters import next_display_id


FUSE_REQUIRED: dict[str, int] = {
    "E": 3,
    "D": 5,
    "C": 8,
    "B": 12,
    "A": 20,
    "S": 30,
}


class FusionError(Exception):
    pass


async def fuse_champions(
    owner_id: str,
    champion_ids: list[str],
    session: AsyncIOMotorClientSession,
) -> ChampionInstance:
    """
    Fuse N identical same-rank champions into 1 of the next rank.
    The required count depends on the resulting rank (see FUSE_REQUIRED).
    Must be called inside an active MongoDB transaction.
    Raises FusionError on any rule violation.
    """
    # Deduplicate IDs (prevent using the same DB document twice)
    if len(set(champion_ids)) != len(champion_ids):
        raise FusionError("Cannot use the same champion twice in fusion.")

    # Fetch all champions with lock check — fetch inside session for transaction isolation
    champs: list[ChampionInstance] = []
    for cid in champion_ids:
        c = await ChampionInstance.get(PydanticObjectId(cid), session=usable_session(session))
        if c is None:
            raise FusionError(f"Champion {cid} not found.")
        if c.owner_id != owner_id:
            raise FusionError("You don't own all these champions.")
        if getattr(c, "favorite", False):
            raise FusionError("Cannot fuse a favorited champion. Unfavorite first.")
        if not c.is_available:
            raise FusionError(
                f"{c.name} is active, locked, in a trade, or listed on market."
            )
        champs.append(c)

    # All must be same name and same rank
    names = {c.name for c in champs}
    ranks = {c.rank for c in champs}
    if len(names) != 1:
        raise FusionError("All champions must have the same name.")
    if len(ranks) != 1:
        raise FusionError("All champions must be the same rank.")

    current_rank = champs[0].rank
    if current_rank == "S":
        raise FusionError("S-rank champions cannot be fused further.")

    next_rank = RANKS[RANK_INDEX[current_rank] + 1]
    required = FUSE_REQUIRED[next_rank]
    if len(champion_ids) != required:
        raise FusionError(f"Exactly {required} champions required to fuse into rank {next_rank}.")

    # Check gold cost
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    cost = CHAMPION_FUSION_COST[next_rank]
    if user.gold < cost:
        raise FusionError(f"Not enough gold. Need {cost}, have {user.gold}.")

    # Deduct gold
    user.gold -= cost
    await user.save(session=usable_session(session))

    # Delete the 3 source champions
    for c in champs:
        await c.delete(session=usable_session(session))

    # Create the result champion
    did = await next_display_id("champion_display_id")
    result = ChampionInstance(
        owner_id=owner_id,
        name=champs[0].name,
        rank=next_rank,
        level=1,
        exp=0,
        display_id=did,
        **_roster_fields(champs[0].name),
    )
    await result.insert(session=usable_session(session))

    # Audit log S-rank creation
    if next_rank == "S":
        await AuditLog.log(
            "S_CHAMPION_CREATED",
            actor_id=owner_id,
            target_id=str(result.id),
            champion_name=result.name,
            source_ids=champion_ids,
        )

    return result


async def bulk_fuse_champions(
    owner_id: str,
    champion_name: str,
    rank: str,
    count: int,
    session: AsyncIOMotorClientSession,
) -> list[ChampionInstance]:
    """
    Fuse ``count`` champions of (name, rank) in groups of FUSE_REQUIRED[next_rank]
    into the next rank.

    - ``count`` must be a positive multiple of the required fuse count.
    - Skips locked / favorited / unavailable champions.
    - Stops if fewer than FUSE_REQUIRED[next_rank] unfused candidates remain.
    Returns the list of created champions.
    """
    if rank == "S":
        raise FusionError("S-rank champions cannot be fused further.")

    next_rank = RANKS[RANK_INDEX[rank] + 1]
    required = FUSE_REQUIRED[next_rank]

    if count <= 0 or count % required != 0:
        raise FusionError(f"Count must be a positive multiple of {required} (copies needed for {rank}→{next_rank}).")

    fusions = count // required
    created: list[ChampionInstance] = []

    for _ in range(fusions):
        # Re-query each iteration so previously consumed champions are excluded.
        candidates = await ChampionInstance.find(
            ChampionInstance.owner_id == owner_id,
            ChampionInstance.name == champion_name,
            ChampionInstance.rank == rank,
            session=usable_session(session),
        ).to_list()
        usable = [
            c for c in candidates
            if c.is_available and not getattr(c, "favorite", False)
        ]
        if len(usable) < required:
            break
        group = usable[:required]
        result = await fuse_champions(owner_id, [str(c.id) for c in group], session)
        created.append(result)

    if not created:
        raise FusionError(
            f"Not enough available {champion_name} ({rank}) to fuse. "
            f"Need at least {required} unlocked, non-favorite copies."
        )

    return created


async def level_up_champion(
    owner_id: str,
    champion_id: str,
    session: AsyncIOMotorClientSession,
    times: int = 1,
) -> tuple[ChampionInstance, int]:
    """Level up a champion by up to `times` levels. Returns (champion, gold_spent).

    For times > 1 (including the 'Max' path), levels as many times as possible
    within the user's current gold, stopping at rank cap.
    """
    c = await ChampionInstance.get(PydanticObjectId(champion_id), session=usable_session(session))
    if c is None or c.owner_id != owner_id:
        raise ValueError("Champion not found or not owned by you.")

    max_lvl = CHAMPION_MAX_LEVEL.get(c.rank, 20)
    if c.level >= max_lvl:
        raise ValueError(f"{c.name} is already at max level ({max_lvl}) for rank {c.rank}.")

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))

    # Walk levels one by one to spend as much gold as possible.
    levels_gained = 0
    total_cost = 0
    while levels_gained < times and c.level + levels_gained < max_lvl:
        cost = levelup_cost(c.rank, c.level + levels_gained)
        if user.gold - total_cost < cost:
            break
        total_cost += cost
        levels_gained += 1

    if levels_gained == 0:
        cost_next = levelup_cost(c.rank, c.level)
        raise ValueError(f"Need {cost_next:,} gold for the next level. You have {user.gold:,}.")

    user.gold -= total_cost
    c.level += levels_gained
    await user.save(session=usable_session(session))
    await c.save(session=usable_session(session))
    return c, total_cost


async def grant_champion(
    owner_id: str,
    name: str,
    rank: str,
    session: Optional[AsyncIOMotorClientSession] = None,
) -> ChampionInstance:
    """Create and give a champion to a player (from drops, events, etc.)."""
    did = await next_display_id("champion_display_id")
    c = ChampionInstance(owner_id=owner_id, name=name, rank=rank, display_id=did, **_roster_fields(name))
    if session:
        await c.insert(session=usable_session(session))
    else:
        await c.insert()
    return c
