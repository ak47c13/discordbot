"""
Champion service: fusion, leveling, acquisition.
All economy operations use MongoDB sessions (transactions).
"""
from __future__ import annotations
import random
from typing import Optional

from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession

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
        c = await ChampionInstance.get(PydanticObjectId(cid), session=session)
        if c is None:
            raise FusionError(f"Champion {cid} not found.")
        if c.owner_id != owner_id:
            raise FusionError("You don't own all these champions.")
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
    user = await User.find_one(User.discord_id == owner_id, session=session)
    cost = CHAMPION_FUSION_COST[next_rank]
    if user.gold < cost:
        raise FusionError(f"Not enough gold. Need {cost}, have {user.gold}.")

    # Deduct gold
    user.gold -= cost
    await user.save(session=session)

    # Delete the 3 source champions
    for c in champs:
        await c.delete(session=session)

    # Create the result champion
    result = ChampionInstance(
        owner_id=owner_id,
        name=champs[0].name,
        rank=next_rank,
        level=1,
        exp=0,
    )
    await result.insert(session=session)

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


async def level_up_champion(
    owner_id: str,
    champion_id: str,
    session: AsyncIOMotorClientSession,
) -> ChampionInstance:
    c = await ChampionInstance.get(PydanticObjectId(champion_id), session=session)
    if c is None or c.owner_id != owner_id:
        raise ValueError("Champion not found or not owned by you.")

    max_lvl = CHAMPION_MAX_LEVEL[c.rank]
    if c.level >= max_lvl:
        raise ValueError(f"Champion is already at max level ({max_lvl}) for rank {c.rank}.")

    user = await User.find_one(User.discord_id == owner_id, session=session)
    if user.gold < LEVEL_UP_GOLD_COST:
        raise ValueError(f"Need {LEVEL_UP_GOLD_COST} gold to level up.")

    user.gold -= LEVEL_UP_GOLD_COST
    c.level += 1
    await user.save(session=session)
    await c.save(session=session)
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
        await c.insert(session=session)
    else:
        await c.insert()
    return c
