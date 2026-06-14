"""
Gacha / summon service. All currency is in-game only. No pity. No real money.
"""
from __future__ import annotations
import random
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from services.champion_service import grant_champion
from services.item_service import grant_item
from config.game_config import (
    SUMMON_TOKEN_COST,
    SUMMON_MULTI_COST,
    SUMMON_RATES,
    RANKS,
    ITEM_BASE_MAIN_STAT,
    SECONDARY_STAT_TYPES,
    SECONDARY_STAT_RANGE,
)
from engine.skills import ALL_CHAMPION_NAMES

# Item pool for summons
SUMMON_ITEM_POOL = [
    ("Infinity Edge", "atk", "crit_damage_passive"),
    ("Chain Vest",    "def", "armor_passive"),
    ("Ruby Crystal",  "hp",  "fortify_passive"),
    ("Recurve Bow",   "atk", "attack_speed_passive"),
    ("Cloak",         "def", "dodge_passive"),
]


class SummonError(Exception):
    pass


async def summon_single(
    owner_id: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.summon_tokens < SUMMON_TOKEN_COST:
        raise SummonError(
            f"Need {SUMMON_TOKEN_COST} summon tokens. Have {user.summon_tokens}."
        )
    user.summon_tokens -= SUMMON_TOKEN_COST
    await user.save(session=usable_session(session))
    result = await _roll_summon(owner_id, session)
    return result


async def summon_multi(
    owner_id: str,
    session: AsyncIOMotorClientSession,
) -> list[dict[str, Any]]:
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.summon_tokens < SUMMON_MULTI_COST:
        raise SummonError(
            f"Need {SUMMON_MULTI_COST} summon tokens for 10x. Have {user.summon_tokens}."
        )
    user.summon_tokens -= SUMMON_MULTI_COST
    await user.save(session=usable_session(session))
    results = []
    for _ in range(10):
        results.append(await _roll_summon(owner_id, session))
    return results


async def _roll_summon(
    owner_id: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    roll = random.random()
    cumulative = 0.0

    for key, rate in SUMMON_RATES.items():
        cumulative += rate
        if roll < cumulative:
            return await _apply_summon_result(key, owner_id, session)

    # Fallback
    return await _apply_summon_result("champion_F", owner_id, session)


async def _apply_summon_result(
    key: str,
    owner_id: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    if key.startswith("champion_"):
        rank = key.split("_")[1].upper()
        name = random.choice(ALL_CHAMPION_NAMES)
        champ = await grant_champion(owner_id, name, rank, session)
        return {"type": "champion", "name": name, "rank": rank, "id": str(champ.id)}

    elif key.startswith("item_"):
        rank = key.split("_")[1].upper()
        name, stat_type, passive = random.choice(SUMMON_ITEM_POOL)
        itm = await grant_item(owner_id, name, rank, stat_type, passive, session)
        return {"type": "item", "name": name, "rank": rank, "id": str(itm.id)}

    elif key == "gold_small":
        amount = random.randint(200, 500)
        user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
        user.gold += amount
        await user.save(session=usable_session(session))
        return {"type": "gold", "amount": amount}

    elif key == "enhance_mat":
        amount = random.randint(3, 8)
        # We'll store this as a user attribute; simplified
        return {"type": "enhance_mat", "amount": amount}

    elif key == "reroll_mat":
        amount = random.randint(1, 3)
        return {"type": "reroll_mat", "amount": amount}

    elif key == "seal":
        user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
        if not hasattr(user, "blacksmith_seals"):
            user.blacksmith_seals = 0
        user.blacksmith_seals = getattr(user, "blacksmith_seals", 0) + 1
        await user.save(session=usable_session(session))
        return {"type": "seal", "amount": 1}

    return {"type": "nothing", "amount": 0}
