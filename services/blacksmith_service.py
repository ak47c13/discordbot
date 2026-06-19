"""
Blacksmith service: enhance, clear, reroll (full and value).
All operations are atomic. Seal logic consumes on both success and failure.
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
    ENHANCEMENT_SUCCESS_RATE,
    ENHANCEMENT_SAFE_MAX,
    ENHANCEMENT_MULTIPLIER,
    REROLL_FULL_COST,
    REROLL_VALUE_COST,
    SECONDARY_STAT_TYPES,
    SECONDARY_STAT_RANGE,
    clearing_gold_cost,
    enhancement_gold_cost,
    ENHANCEMENT_MAT_COST,
)


class BlacksmithError(Exception):
    pass


# ---------------------------------------------------------------------------
# Enhancement
# ---------------------------------------------------------------------------
async def enhance_item(
    owner_id: str,
    item_id: str,
    use_seal: bool,
    session: AsyncIOMotorClientSession,
) -> dict:
    """
    Attempt to enhance an item by +1.
    Returns dict with keys: success, destroyed, seal_used, new_level, item.
    Must be called inside an active transaction.
    """
    itm = await ItemInstance.get(PydanticObjectId(item_id), session=usable_session(session))
    if itm is None or itm.owner_id != owner_id:
        raise BlacksmithError("Item not found or not owned by you.")
    if itm.in_trade or itm.in_market:
        raise BlacksmithError("Cannot enhance an item that is listed or in a trade.")
    if itm.enhancement >= 15:
        raise BlacksmithError("Item is already at maximum enhancement (+15).")

    current_lvl = itm.enhancement
    is_risky = current_lvl >= ENHANCEMENT_SAFE_MAX

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))

    # Gold cost
    gold_cost = enhancement_gold_cost(current_lvl)
    if user.gold < gold_cost:
        raise BlacksmithError(f"Not enough gold. Need {gold_cost}, have {user.gold}.")

    # Material cost (stored as generic enhance_mat count on user — simplified)
    mat_cost = ENHANCEMENT_MAT_COST[current_lvl]
    # We track enhance_mat as a field — if not present assume we use gold only for now
    # (full material inventory system would expand this)

    # Seal requirement for risky enhancement
    if is_risky and use_seal:
        # Verify user has at least 1 seal
        if getattr(user, "blacksmith_seals", 0) < 1:
            raise BlacksmithError("You don't have a Blacksmith's Seal.")

    # Deduct gold (always)
    user.gold -= gold_cost

    # Roll success
    success_rate = ENHANCEMENT_SUCCESS_RATE[current_lvl]
    success = random.random() < success_rate

    result = {
        "success": success,
        "destroyed": False,
        "seal_used": False,
        "new_level": current_lvl,
        "item": itm,
    }

    if is_risky and use_seal:
        # Consume seal regardless of outcome
        user.blacksmith_seals -= 1
        result["seal_used"] = True
        await AuditLog.log(
            "SEAL_USED",
            actor_id=owner_id,
            target_id=str(itm.id),
            item_name=itm.name,
            current_level=current_lvl,
            attempt_success=success,
        )

    if success:
        itm.enhancement += 1
        result["new_level"] = itm.enhancement
        await AuditLog.log(
            "ENHANCEMENT_ABOVE_7",
            actor_id=owner_id,
            target_id=str(itm.id),
            item_name=itm.name,
            old_level=current_lvl,
            new_level=itm.enhancement,
            success=True,
        ) if is_risky else None
    else:
        if is_risky:
            if use_seal:
                # Seal protects — item stays at current level
                await AuditLog.log(
                    "ENHANCEMENT_ABOVE_7",
                    actor_id=owner_id,
                    target_id=str(itm.id),
                    item_name=itm.name,
                    current_level=current_lvl,
                    success=False,
                    seal_protected=True,
                )
            else:
                # Item destroyed
                result["destroyed"] = True
                await AuditLog.log(
                    "ITEM_DESTROYED",
                    actor_id=owner_id,
                    target_id=str(itm.id),
                    item_name=itm.name,
                    item_rank=itm.rank,
                    enhancement=current_lvl,
                )
                await user.save(session=usable_session(session))
                await itm.delete(session=usable_session(session))
                return result
        # Non-risky failure: item survives, gold already spent

    await user.save(session=usable_session(session))
    await itm.save(session=usable_session(session))
    return result


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------
async def clear_item(
    owner_id: str,
    item_id: str,
    session: AsyncIOMotorClientSession,
) -> ItemInstance:
    """
    Reset an item to +0. Preserves identity, rank, secondary stat.
    Costs gold. No refund of materials or previous attempts.
    """
    itm = await ItemInstance.get(PydanticObjectId(item_id), session=usable_session(session))
    if itm is None or itm.owner_id != owner_id:
        raise BlacksmithError("Item not found or not owned by you.")
    if itm.in_trade or itm.in_market:
        raise BlacksmithError("Cannot clear an item that is listed or in a trade.")
    if itm.enhancement == 0:
        raise BlacksmithError("Item is already at +0.")

    gold_cost = clearing_gold_cost(itm.rank, itm.enhancement)
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.gold < gold_cost:
        raise BlacksmithError(f"Need {gold_cost} gold to clear. Have {user.gold}.")

    user.gold -= gold_cost
    itm.enhancement = 0
    await user.save(session=usable_session(session))
    await itm.save(session=usable_session(session))
    return itm


# ---------------------------------------------------------------------------
# Reroll — Full (changes type + value)
# ---------------------------------------------------------------------------
async def reroll_secondary_full(
    owner_id: str,
    item_id: str,
    session: AsyncIOMotorClientSession,
) -> dict:
    """
    Returns dict with old_type, old_value, new_type, new_value, item.
    Player must CONFIRM before calling accept_reroll.
    This call only generates the pending result — does NOT apply it yet.
    """
    itm = await ItemInstance.get(PydanticObjectId(item_id), session=usable_session(session))
    if itm is None or itm.owner_id != owner_id:
        raise BlacksmithError("Item not found or not owned by you.")
    if itm.in_trade or itm.in_market:
        raise BlacksmithError("Cannot reroll an item that is listed or in a trade.")

    gold_cost = REROLL_FULL_COST[itm.rank]
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.gold < gold_cost:
        raise BlacksmithError(f"Need {gold_cost} gold. Have {user.gold}.")

    from services.item_service import _roll_substats
    old_substats = list(itm.substats)
    new_substats = _roll_substats(itm.rank)

    return {
        "old_substats": old_substats,
        "new_substats": new_substats,
        "gold_cost": gold_cost,
        "item": itm,
    }


async def accept_reroll_full(
    owner_id: str,
    item_id: str,
    new_substats: list,
    session: AsyncIOMotorClientSession,
) -> ItemInstance:
    """Apply a pending full reroll result. Deducts gold."""
    itm = await ItemInstance.get(PydanticObjectId(item_id), session=usable_session(session))
    if itm is None or itm.owner_id != owner_id:
        raise BlacksmithError("Item not found.")
    if itm.in_trade or itm.in_market:
        raise BlacksmithError("Item state changed — reroll cancelled.")

    gold_cost = REROLL_FULL_COST[itm.rank]
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.gold < gold_cost:
        raise BlacksmithError(f"Need {gold_cost} gold.")

    user.gold -= gold_cost
    itm.substats = new_substats
    await user.save(session=usable_session(session))
    await itm.save(session=usable_session(session))
    return itm


# ---------------------------------------------------------------------------
# Reroll — Value only (keeps type)
# ---------------------------------------------------------------------------
async def reroll_secondary_value(
    owner_id: str,
    item_id: str,
    session: AsyncIOMotorClientSession,
) -> dict:
    itm = await ItemInstance.get(PydanticObjectId(item_id), session=usable_session(session))
    if itm is None or itm.owner_id != owner_id:
        raise BlacksmithError("Item not found or not owned by you.")
    if itm.in_trade or itm.in_market:
        raise BlacksmithError("Cannot reroll an item that is listed or in a trade.")

    gold_cost = REROLL_VALUE_COST[itm.rank]
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.gold < gold_cost:
        raise BlacksmithError(f"Need {gold_cost} gold. Have {user.gold}.")

    lo, hi = SECONDARY_STAT_RANGE[itm.rank]
    old_substats = list(itm.substats)
    new_substats = [
        {"type": s["type"], "value": random.randint(lo, hi)}
        for s in old_substats
    ]

    return {
        "old_substats": old_substats,
        "new_substats": new_substats,
        "gold_cost": gold_cost,
        "item": itm,
    }


async def accept_reroll_value(
    owner_id: str,
    item_id: str,
    new_substats: list,
    session: AsyncIOMotorClientSession,
) -> ItemInstance:
    itm = await ItemInstance.get(PydanticObjectId(item_id), session=usable_session(session))
    if itm is None or itm.owner_id != owner_id:
        raise BlacksmithError("Item not found.")
    if itm.in_trade or itm.in_market:
        raise BlacksmithError("Item state changed — reroll cancelled.")

    gold_cost = REROLL_VALUE_COST[itm.rank]
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.gold < gold_cost:
        raise BlacksmithError(f"Need {gold_cost} gold.")

    user.gold -= gold_cost
    itm.substats = new_substats
    await user.save(session=usable_session(session))
    await itm.save(session=usable_session(session))
    return itm
