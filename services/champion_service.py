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
from config.game_config import (
    RANKS,
    RANK_INDEX,
    CHAMPION_FUSION_COST,
    CHAMPION_MAX_LEVEL,
    LEVEL_UP_GOLD_COST,
    CHAMPION_BASE_STATS,
    CHAMPION_GROWTH_STATS,
)


class FusionError(Exception):
    pass


async def fuse_champions(
    owner_id: str,
    champion_ids: list[str],
    session: AsyncIOMotorClientSession,
) -> ChampionInstance:
    """
    Fuse exactly 3 identical same-rank champions into 1 of the next rank.
    Must be called inside an active MongoDB transaction.
    Raises FusionError on any rule violation.
    """
    if len(champion_ids) != 3:
        raise FusionError("Exactly 3 champions required for fusion.")

    # Deduplicate IDs (prevent using the same DB document twice)
    if len(set(champion_ids)) != 3:
        raise FusionError("Cannot use the same champion twice in fusion.")

    # Fetch all three with lock check — fetch inside session for transaction isolation
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
                f"{c.name} is equipped, locked, in a trade, or listed on market."
            )
        champs.append(c)

    # All must be same name and same rank
    names = {c.name for c in champs}
    ranks = {c.rank for c in champs}
    if len(names) != 1:
        raise FusionError("All three champions must have the same name.")
    if len(ranks) != 1:
        raise FusionError("All three champions must be the same rank.")

    current_rank = champs[0].rank
    if current_rank == "S":
        raise FusionError("S-rank champions cannot be fused further.")

    next_rank = RANKS[RANK_INDEX[current_rank] + 1]

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
    result = ChampionInstance(
        owner_id=owner_id,
        name=champs[0].name,
        rank=next_rank,
        level=1,
        exp=0,
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
    Fuse ``count`` champions of (name, rank) in groups of 3 into the next rank.

    - ``count`` must be a positive multiple of 3.
    - Runs ``count // 3`` sequential fusions, each consuming 3 source champions.
    - Skips locked / favorited / unavailable champions.
    - Stops if fewer than 3 unfused candidates remain.
    Returns the list of created champions.
    """
    if count <= 0 or count % 3 != 0:
        raise FusionError("Count must be a positive multiple of 3.")
    if rank == "S":
        raise FusionError("S-rank champions cannot be fused further.")

    fusions = count // 3
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
        if len(usable) < 3:
            break
        trio = usable[:3]
        result = await fuse_champions(owner_id, [str(c.id) for c in trio], session)
        created.append(result)

    if not created:
        raise FusionError(
            f"Not enough available {champion_name} ({rank}) to fuse. "
            "Need at least 3 unlocked, non-favorite copies."
        )

    return created


async def level_up_champion(
    owner_id: str,
    champion_id: str,
    session: AsyncIOMotorClientSession,
) -> ChampionInstance:
    c = await ChampionInstance.get(PydanticObjectId(champion_id), session=usable_session(session))
    if c is None or c.owner_id != owner_id:
        raise ValueError("Champion not found or not owned by you.")

    max_lvl = CHAMPION_MAX_LEVEL[c.rank]
    if c.level >= max_lvl:
        raise ValueError(f"Champion is already at max level ({max_lvl}) for rank {c.rank}.")

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.gold < LEVEL_UP_GOLD_COST:
        raise ValueError(f"Need {LEVEL_UP_GOLD_COST} gold to level up.")

    user.gold -= LEVEL_UP_GOLD_COST
    c.level += 1
    await user.save(session=usable_session(session))
    await c.save(session=usable_session(session))
    return c


async def grant_champion(
    owner_id: str,
    name: str,
    rank: str,
    session: Optional[AsyncIOMotorClientSession] = None,
) -> ChampionInstance:
    """Create and give a champion to a player (from drops, events, etc.)."""
    c = ChampionInstance(owner_id=owner_id, name=name, rank=rank)
    if session:
        await c.insert(session=usable_session(session))
    else:
        await c.insert()
    return c
