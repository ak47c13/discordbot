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

# --------------------------------------------------------------------------- #
# Region-weighted champion pool helpers
# --------------------------------------------------------------------------- #

def get_weekly_champion_pool() -> tuple[str, list[str]]:
    """Return (region_display_name, list_of_champion_names_in_region).

    Only returns champions that actually exist in ALL_CHAMPION_NAMES so the
    caller never gets a name that isn't in the skill/roster tables.
    """
    from data.champion_regions import current_region, CHAMPION_REGIONS, REGION_DISPLAY_NAMES
    region_key = current_region()
    region_champs = CHAMPION_REGIONS.get(region_key, [])
    valid = [c for c in region_champs if c in ALL_CHAMPION_NAMES]
    return REGION_DISPLAY_NAMES.get(region_key, region_key), valid


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
    pool_type: str = "mixed",
) -> dict[str, Any]:
    """Perform a single summon.

    Parameters
    ----------
    pool_type:
        ``"champion"`` – roll only from the champion tables (region-biased).
        ``"item"``     – roll only from the item tables.
        ``"mixed"``    – original behaviour: roll from the full SUMMON_RATES
                         table which may yield champions, items, gold, or mats.
    """
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.summon_tokens < SUMMON_TOKEN_COST:
        raise SummonError(
            f"Need {SUMMON_TOKEN_COST} summon tokens. Have {user.summon_tokens}."
        )
    user.summon_tokens -= SUMMON_TOKEN_COST
    await user.save(session=usable_session(session))
    result = await _roll_summon(owner_id, session, pool_type=pool_type)
    return result


async def summon_multi(
    owner_id: str,
    session: AsyncIOMotorClientSession,
    pool_type: str = "mixed",
) -> list[dict[str, Any]]:
    """Perform a 10x summon.

    Parameters
    ----------
    pool_type:
        Same semantics as :func:`summon_single`.
    """
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user.summon_tokens < SUMMON_MULTI_COST:
        raise SummonError(
            f"Need {SUMMON_MULTI_COST} summon tokens for 10x. Have {user.summon_tokens}."
        )
    user.summon_tokens -= SUMMON_MULTI_COST
    await user.save(session=usable_session(session))
    results = []
    for _ in range(10):
        results.append(await _roll_summon(owner_id, session, pool_type=pool_type))
    return results


async def _roll_summon(
    owner_id: str,
    session: AsyncIOMotorClientSession,
    pool_type: str = "mixed",
) -> dict[str, Any]:
    """Roll one summon result.

    When *pool_type* is ``"champion"`` only champion-keyed entries in
    SUMMON_RATES are considered.  When it is ``"item"`` only item-keyed
    entries are considered.  ``"mixed"`` (default) preserves the original
    behaviour of rolling across the full table.

    Champion name selection is region-biased: 80 % of champion rolls are
    drawn from the current week's region pool; the remaining 20 % are drawn
    from the full champion list.
    """
    if pool_type == "champion":
        filtered = {k: v for k, v in SUMMON_RATES.items() if k.startswith("champion_")}
    elif pool_type == "item":
        filtered = {k: v for k, v in SUMMON_RATES.items() if k.startswith("item_")}
    else:
        filtered = SUMMON_RATES

    # Normalise rates so they sum to 1.0 after filtering
    total = sum(filtered.values())
    roll = random.random() * total
    cumulative = 0.0

    for key, rate in filtered.items():
        cumulative += rate
        if roll < cumulative:
            return await _apply_summon_result(key, owner_id, session)

    # Fallback: use the first key in the filtered table
    fallback = next(iter(filtered), "champion_F")
    return await _apply_summon_result(fallback, owner_id, session)


async def _apply_summon_result(
    key: str,
    owner_id: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    if key.startswith("champion_"):
        rank = key.split("_")[1].upper()
        # 80 % from this week's region, 20 % from the full roster
        region_display, region_pool = get_weekly_champion_pool()
        if region_pool and random.random() < 0.80:
            name = random.choice(region_pool)
        else:
            name = random.choice(list(ALL_CHAMPION_NAMES))
        champ = await grant_champion(owner_id, name, rank, session)
        from data.champion_roster import CHAMPION_ROSTER
        roster = CHAMPION_ROSTER.get(name, {})
        return {
            "type": "champion",
            "name": name,
            "rank": rank,
            "id": str(champ.id),
            "title": roster.get("title", ""),
            "role": roster.get("role", "fighter"),
            "riot_id": roster.get("riot_id", ""),
            "region": region_display,
        }

    elif key.startswith("item_"):
        rank = key.split("_")[1].upper()
        name, stat_type, passive = random.choice(SUMMON_ITEM_POOL)
        itm = await grant_item(owner_id, name, rank, stat_type, passive, session)
        return {
            "type": "item",
            "name": name,
            "rank": rank,
            "id": str(itm.id),
            "stat_type": stat_type,
            "passive": passive,
            "secondary_stat": itm.secondary_stat_type,
            "secondary_val": itm.secondary_stat_value,
        }

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
