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


# ---------------------------------------------------------------------------
# Weekly item category pools
# ---------------------------------------------------------------------------
# Shop item pools — basics are most common, advanced components appear too.
# Completed items are not in these pools; craft them at /build.
ITEM_CATEGORIES: dict[str, list[tuple[str, str, str]]] = {
    "weapons": [
        # Basic
        ("Long Sword",         "atk", "atk_passive"),
        ("Pickaxe",            "atk", "atk_passive"),
        ("Dagger",             "atk", "attack_speed_passive"),
        ("Vampiric Scepter",   "atk", "lifesteal_passive"),
        # Advanced
        ("B.F. Sword",         "atk", "atk_passive"),
        ("Recurve Bow",        "atk", "attack_speed_passive"),
        ("Cloak of Agility",   "atk", "crit_damage_passive"),
        ("Zeal",               "atk", "attack_speed_passive"),
        ("Phage",              "atk", "atk_passive"),
    ],
    "armor": [
        # Basic
        ("Cloth Armor",        "def", "armor_passive"),
        ("Null-Magic Mantle",  "def", "magic_resist_passive"),
        # Advanced
        ("Chain Vest",         "def", "armor_passive"),
        ("Negatron Cloak",     "def", "magic_resist_passive"),
        ("Warden's Mail",      "def", "armor_passive"),
        ("Bramble Vest",       "def", "armor_passive"),
        ("Hexdrinker",         "def", "magic_resist_passive"),
        ("Spectre's Cowl",     "def", "magic_resist_passive"),
    ],
    "accessories": [
        # Basic
        ("Ruby Crystal",       "hp",  "fortify_passive"),
        ("Faerie Charm",       "hp",  "fortify_passive"),
        # Advanced
        ("Giant's Belt",       "hp",  "fortify_passive"),
        ("Kindlegem",          "hp",  "fortify_passive"),
        ("Sheen",              "atk", "sheen_passive"),
        ("Tear of the Goddess","atk", "atk_passive"),
    ],
    "magic": [
        # Basic
        ("Amplifying Tome",    "atk", "atk_passive"),
        ("Sapphire Crystal",   "atk", "atk_passive"),
        ("Aether Wisp",        "atk", "magic_pen_passive"),
        # Advanced
        ("Blasting Wand",      "atk", "atk_passive"),
        ("Needlessly Large Rod","atk", "crit_damage_passive"),
        ("Lost Chapter",       "atk", "atk_passive"),
        ("Fiendish Codex",     "atk", "attack_speed_passive"),
        ("Cryptbloom",         "atk", "magic_pen_passive"),
        ("Shadowflame",        "atk", "magic_pen_passive"),
    ],
    "assassin": [
        # Basic
        ("Serrated Dirk",      "atk", "armor_pen_passive"),
        ("Long Sword",         "atk", "atk_passive"),
        ("Dagger",             "atk", "attack_speed_passive"),
        # Advanced
        ("Cauterize",          "atk", "armor_pen_passive"),
        ("Serpent's Fang",     "atk", "armor_pen_passive"),
        ("Umbral Glaive",      "atk", "armor_pen_passive"),
        ("Prowler's Claw",     "atk", "armor_pen_passive"),
        ("Axiom Arc",          "atk", "armor_pen_passive"),
    ],
}
ITEM_CATEGORY_ROTATION = ["weapons", "armor", "accessories", "magic", "assassin"]
ITEM_CATEGORY_DISPLAY = {
    "weapons":     "Weapons",
    "armor":       "Armor",
    "accessories": "Accessories",
    "magic":       "Magic Items",
    "assassin":    "Assassin Items",
}

# ---------------------------------------------------------------------------
# Weekly rune category pools
# ---------------------------------------------------------------------------
RUNE_CATEGORIES: dict[str, dict] = {
    "precision": {
        "display": "Precision",
        "description": "Enhance attacks and abilities. Boosts crit, attack speed, and damage.",
        "stats": ["crit_chance", "crit_dmg", "attack_speed", "atk_pct"],
    },
    "domination": {
        "display": "Domination",
        "description": "Burst damage and target access. Boosts armor penetration and lifesteal.",
        "stats": ["armor_pen", "lifesteal", "atk_pct", "crit_chance"],
    },
    "resolve": {
        "display": "Resolve",
        "description": "Durability and crowd control resistance. Boosts HP and armor.",
        "stats": ["hp_pct", "def_pct", "dodge", "magic_resist"],
    },
    "sorcery": {
        "display": "Sorcery",
        "description": "Empowers abilities and resource manipulation. Boosts magic pen and speed.",
        "stats": ["magic_pen", "atk_pct", "crit_dmg", "attack_speed"],
    },
}
RUNE_CATEGORY_ROTATION = ["precision", "domination", "resolve", "sorcery"]
RUNE_CATEGORY_DISPLAY = {k: v["display"] for k, v in RUNE_CATEGORIES.items()}


def get_weekly_item_pool() -> tuple[str, list[tuple[str, str, str]]]:
    """Return (category_display_name, item_pool) for the current week."""
    import time
    ANCHOR_UTC = 1703959200
    WEEK_SECS = 604800
    week_index = int((time.time() - ANCHOR_UTC) // WEEK_SECS)
    key = ITEM_CATEGORY_ROTATION[week_index % len(ITEM_CATEGORY_ROTATION)]
    return ITEM_CATEGORY_DISPLAY[key], ITEM_CATEGORIES[key]


def get_weekly_rune_category() -> tuple[str, dict]:
    """Return (category_display_name, category_dict) for the current week."""
    import time
    ANCHOR_UTC = 1703959200
    WEEK_SECS = 604800
    # Offset by 2 so rune week differs from champion and item week
    week_index = int((time.time() - ANCHOR_UTC) // WEEK_SECS) + 2
    key = RUNE_CATEGORY_ROTATION[week_index % len(RUNE_CATEGORY_ROTATION)]
    return RUNE_CATEGORIES[key]["display"], RUNE_CATEGORIES[key]


# Maps weekly rune category → catalog rune IDs that match each stat theme
_RUNE_CATEGORY_POOLS: dict[str, list[str]] = {
    "precision":  [
        "mark-crit-t1", "mark-crit-t2", "mark-aspd-t1", "mark-aspd-t2",
        "glyph-critdmg-t1", "glyph-critdmg-t2", "mark-atk-t1", "mark-atk-t2",
    ],
    "domination": [
        "mark-arpen-t1", "mark-arpen-t2", "quint-lifesteal-t1", "quint-lifesteal-t2",
        "mark-atk-t1", "mark-atk-t2", "mark-crit-t1",
    ],
    "resolve": [
        "seal-hp-t1", "seal-hp-t2", "seal-def-t1", "seal-def-t2",
        "seal-dodge-t1", "glyph-def-t1", "glyph-def-t2", "seal-hpregen-t1",
    ],
    "sorcery": [
        "mark-mpen-t1", "mark-mpen-t2", "glyph-mana-t1", "glyph-mana-t2",
        "glyph-critdmg-t1", "mark-aspd-t1", "mark-atk-t1",
    ],
}

# Tier weights for rune pulls (tier 1 = common, tier 2 = uncommon, tier 3 = rare)
_RUNE_TIER_WEIGHTS = [0.65, 0.28, 0.07]


def _get_weekly_rune_pool() -> list[str]:
    """Return list of rune IDs for the current week's category."""
    import time
    ANCHOR_UTC = 1703959200
    WEEK_SECS = 604800
    week_index = int((time.time() - ANCHOR_UTC) // WEEK_SECS) + 2
    key = RUNE_CATEGORY_ROTATION[week_index % len(RUNE_CATEGORY_ROTATION)]
    return _RUNE_CATEGORY_POOLS.get(key, list(_RUNE_CATEGORY_POOLS["precision"]))


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
    for _ in range(11):  # 10 paid + 1 bonus
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
    if pool_type == "rune":
        # Rune pool uses its own tier-weighted logic — bypass SUMMON_RATES
        return await _apply_summon_result("rune", owner_id, session)

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
        _, item_pool = get_weekly_item_pool()
        name, stat_type, passive = random.choice(item_pool)
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

    elif key.startswith("rune"):
        from data.rune_catalog import RUNE_CATALOG
        from services.rune_service import grant_rune
        from config.game_config import RUNE_SUMMON_RATES

        # Determine rank: if key is "rune_X" use that rank, else roll from rates
        if "_" in key and key.split("_")[1].upper() in ("F","E","D","C","B","A","S"):
            rank = key.split("_")[1].upper()
        else:
            ranks = list(RUNE_SUMMON_RATES.keys())
            weights = list(RUNE_SUMMON_RATES.values())
            rank_key = random.choices(ranks, weights=weights, k=1)[0]
            rank = rank_key.split("_")[1].upper()

        pool = _get_weekly_rune_pool()
        # Pick rune ID from pool weighted by tier aligned to rank
        rank_to_tier = {"F": 1, "E": 1, "D": 2, "C": 2, "B": 3, "A": 3, "S": 3}
        tier = rank_to_tier.get(rank, 1)
        tier_pool = [rid for rid in pool if rid.endswith(f"-t{tier}")]
        if not tier_pool:
            tier_pool = pool
        rune_id = random.choice(tier_pool)
        rune = RUNE_CATALOG.get(rune_id, {})

        inst = await grant_rune(owner_id, rune_id, rank, session)
        return {
            "type": "rune",
            "rune_id": rune_id,
            "instance_id": str(inst.id),
            "display_id": inst.display_id,
            "name": rune.get("name", rune_id),
            "description": rune.get("description", ""),
            "color": rune.get("color", "red"),
            "rank": rank,
            "tier": tier,
        }

    return {"type": "nothing", "amount": 0}
