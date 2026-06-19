"""
Item service: fusion, passive stacking resolution, grants.
"""
from __future__ import annotations
import random

from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.item import ItemInstance
from models.user import User
from models.audit_log import AuditLog
from config.game_config import (
    RANKS,
    RANK_INDEX,
    ITEM_FUSION_COST,
    ITEM_BASE_MAIN_STAT,
    SECONDARY_STAT_TYPES,
    SECONDARY_STAT_RANGE,
)


FUSE_REQUIRED: dict[str, int] = {
    "E": 3,
    "D": 5,
    "C": 8,
    "B": 12,
    "A": 20,
    "S": 30,
}


class ItemFusionError(Exception):
    pass


async def fuse_items(
    owner_id: str,
    item_ids: list[str],
    session: AsyncIOMotorClientSession,
) -> ItemInstance:
    """
    Fuse N identical same-rank +0 items into 1 of the next rank.
    The required count depends on the resulting rank (see FUSE_REQUIRED).
    Must be called inside an active MongoDB transaction.
    """
    if len(set(item_ids)) != len(item_ids):
        raise ItemFusionError("Cannot use the same item twice in fusion.")

    items: list[ItemInstance] = []
    for iid in item_ids:
        itm = await ItemInstance.get(PydanticObjectId(iid), session=usable_session(session))
        if itm is None:
            raise ItemFusionError(f"Item {iid} not found.")
        if itm.owner_id != owner_id:
            raise ItemFusionError("You don't own all these items.")
        if getattr(itm, "favorite", False):
            raise ItemFusionError("Cannot fuse a favorited item. Unfavorite first.")
        if not itm.is_fusible:
            raise ItemFusionError(
                f"{itm.name} +{itm.enhancement} cannot be fused. "
                "Items must be +0 and not locked/equipped/traded/listed."
            )
        items.append(itm)

    names = {i.name for i in items}
    ranks = {i.rank for i in items}
    if len(names) != 1:
        raise ItemFusionError("All three items must have the same name.")
    if len(ranks) != 1:
        raise ItemFusionError("All three items must be the same rank.")

    current_rank = items[0].rank
    if current_rank == "S":
        raise ItemFusionError("S-rank items cannot be fused further.")

    next_rank = RANKS[RANK_INDEX[current_rank] + 1]
    required = FUSE_REQUIRED[next_rank]
    if len(item_ids) != required:
        raise ItemFusionError(f"Exactly {required} items required to fuse into rank {next_rank}.")

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    cost = ITEM_FUSION_COST[next_rank]
    if user.gold < cost:
        raise ItemFusionError(f"Not enough gold. Need {cost}, have {user.gold}.")

    user.gold -= cost
    await user.save(session=usable_session(session))

    for itm in items:
        await itm.delete(session=usable_session(session))

    # New secondary stat roll
    sec_type = random.choice(SECONDARY_STAT_TYPES)
    lo, hi = SECONDARY_STAT_RANGE[next_rank]
    sec_val = random.randint(lo, hi)

    result = ItemInstance(
        owner_id=owner_id,
        name=items[0].name,
        rank=next_rank,
        enhancement=0,
        main_stat_type=items[0].main_stat_type,
        main_stat_base=ITEM_BASE_MAIN_STAT[next_rank],
        passive_name=items[0].passive_name,
        secondary_stat_type=sec_type,
        secondary_stat_value=sec_val,
    )
    await result.insert(session=usable_session(session))

    if next_rank == "S":
        await AuditLog.log(
            "S_ITEM_CREATED",
            actor_id=owner_id,
            target_id=str(result.id),
            item_name=result.name,
            source_ids=item_ids,
        )

    return result


async def bulk_fuse_items(
    owner_id: str,
    item_name: str,
    rank: str,
    count: int,
    session: AsyncIOMotorClientSession,
) -> list[ItemInstance]:
    """
    Fuse ``count`` items of (name, rank) at +0 in groups of FUSE_REQUIRED[next_rank]
    into the next rank.

    - ``count`` must be a positive multiple of the required fuse count.
    - Skips locked / favorited / enhanced / unavailable items.
    - Stops if fewer than FUSE_REQUIRED[next_rank] fusible candidates remain.
    """
    if rank == "S":
        raise ItemFusionError("S-rank items cannot be fused further.")

    next_rank = RANKS[RANK_INDEX[rank] + 1]
    required = FUSE_REQUIRED[next_rank]

    if count <= 0 or count % required != 0:
        raise ItemFusionError(f"Count must be a positive multiple of {required} (copies needed for {rank}→{next_rank}).")

    fusions = count // required
    created: list[ItemInstance] = []

    for _ in range(fusions):
        candidates = await ItemInstance.find(
            ItemInstance.owner_id == owner_id,
            ItemInstance.name == item_name,
            ItemInstance.rank == rank,
            session=usable_session(session),
        ).to_list()
        usable = [
            i for i in candidates
            if i.is_fusible and not getattr(i, "favorite", False)
        ]
        if len(usable) < required:
            break
        group = usable[:required]
        result = await fuse_items(owner_id, [str(i.id) for i in group], session)
        created.append(result)

    if not created:
        raise ItemFusionError(
            f"Not enough fusible {item_name} ({rank}) at +0 to fuse. "
            f"Need at least {required} unlocked, non-favorite copies."
        )

    return created


async def grant_item(
    owner_id: str,
    name: str,
    rank: str,
    main_stat_type: str,
    passive_name: str,
    session=None,
) -> ItemInstance:
    lo, hi = SECONDARY_STAT_RANGE[rank]
    sec_val = random.randint(lo, hi)
    sec_type = random.choice(SECONDARY_STAT_TYPES)

    itm = ItemInstance(
        owner_id=owner_id,
        name=name,
        rank=rank,
        enhancement=0,
        main_stat_type=main_stat_type,
        main_stat_base=ITEM_BASE_MAIN_STAT[rank],
        passive_name=passive_name,
        secondary_stat_type=sec_type,
        secondary_stat_value=sec_val,
    )
    if session:
        await itm.insert(session=usable_session(session))
    else:
        await itm.insert()
    return itm
