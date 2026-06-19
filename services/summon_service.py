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
# Weekly item category pools — three tiers: basic (75%), advanced (20%), completed (5%)
# ---------------------------------------------------------------------------
ITEM_CATEGORIES: dict[str, dict] = {
    "weapons": {
        "basic": [
            ("Long Sword",         "atk", "atk_passive"),
            ("Pickaxe",            "atk", "atk_passive"),
            ("Dagger",             "atk", "attack_speed_passive"),
            ("Vampiric Scepter",   "atk", "lifesteal_passive"),
        ],
        "advanced": [
            ("B.F. Sword",         "atk", "atk_passive"),
            ("Recurve Bow",        "atk", "attack_speed_passive"),
            ("Cloak of Agility",   "atk", "crit_damage_passive"),
            ("Zeal",               "atk", "attack_speed_passive"),
            ("Phage",              "atk", "atk_passive"),
        ],
        "completed": [
            ("Infinity Edge",              "atk", "crit_damage_passive"),
            ("Phantom Dancer",             "atk", "attack_speed_passive"),
            ("Trinity Force",              "atk", "atk_passive"),
            ("Kraken Slayer",              "atk", "atk_passive"),
            ("Runaan's Hurricane",         "atk", "attack_speed_passive"),
            ("Blade of the Ruined King",   "atk", "lifesteal_passive"),
            ("Ravenous Hydra",             "atk", "lifesteal_passive"),
            ("Death's Dance",              "atk", "lifesteal_passive"),
            ("Immortal Shieldbow",         "atk", "lifesteal_passive"),
        ],
    },
    "armor": {
        "basic": [
            ("Cloth Armor",        "def", "armor_passive"),
            ("Null-Magic Mantle",  "def", "magic_resist_passive"),
        ],
        "advanced": [
            ("Chain Vest",         "def", "armor_passive"),
            ("Negatron Cloak",     "def", "magic_resist_passive"),
            ("Warden's Mail",      "def", "armor_passive"),
            ("Bramble Vest",       "def", "armor_passive"),
            ("Hexdrinker",         "def", "magic_resist_passive"),
            ("Spectre's Cowl",     "def", "magic_resist_passive"),
        ],
        "completed": [
            ("Thornmail",          "def", "armor_passive"),
            ("Frozen Heart",       "def", "armor_passive"),
            ("Gargoyle Stoneplate","def", "armor_passive"),
            ("Randuin's Omen",     "def", "armor_passive"),
            ("Dead Man's Plate",   "def", "armor_passive"),
            ("Guardian Angel",     "def", "armor_passive"),
            ("Spirit Visage",      "def", "magic_resist_passive"),
            ("Force of Nature",    "def", "magic_resist_passive"),
            ("Abyssal Mask",       "def", "magic_resist_passive"),
            ("Jak'Sho the Protean","def", "armor_passive"),
        ],
    },
    "accessories": {
        "basic": [
            ("Ruby Crystal",       "hp",  "fortify_passive"),
            ("Faerie Charm",       "hp",  "fortify_passive"),
        ],
        "advanced": [
            ("Giant's Belt",       "hp",  "fortify_passive"),
            ("Kindlegem",          "hp",  "fortify_passive"),
            ("Tear of the Goddess","atk", "atk_passive"),
        ],
        "completed": [
            ("Sheen",              "atk", "sheen_passive"),
            ("Warmog's Armor",     "hp",  "fortify_passive"),
            ("Sterak's Gage",      "hp",  "fortify_passive"),
            ("Heartsteel",         "hp",  "fortify_passive"),
            ("Sunfire Aegis",      "hp",  "fortify_passive"),
        ],
    },
    "magic": {
        "basic": [
            ("Amplifying Tome",    "atk", "atk_passive"),
            ("Sapphire Crystal",   "atk", "atk_passive"),
            ("Aether Wisp",        "atk", "magic_pen_passive"),
        ],
        "advanced": [
            ("Blasting Wand",          "atk", "atk_passive"),
            ("Needlessly Large Rod",   "atk", "crit_damage_passive"),
            ("Lost Chapter",           "atk", "atk_passive"),
            ("Fiendish Codex",         "atk", "attack_speed_passive"),
        ],
        "completed": [
            ("Shadowflame",            "atk", "magic_pen_passive"),
            ("Cryptbloom",             "atk", "magic_pen_passive"),
            ("Rabadon's Deathcap",    "atk", "crit_damage_passive"),
            ("Void Staff",             "atk", "magic_pen_passive"),
            ("Luden's Companion",      "atk", "magic_pen_passive"),
            ("Nashor's Tooth",         "atk", "attack_speed_passive"),
            ("Liandry's Anguish",      "atk", "magic_pen_passive"),
            ("Morellonomicon",         "atk", "magic_pen_passive"),
            ("Archangel's Staff",      "atk", "atk_passive"),
            ("Zhonya's Hourglass",     "atk", "armor_passive"),
            ("Banshee's Veil",         "atk", "magic_resist_passive"),
        ],
    },
    "assassin": {
        "basic": [
            ("Serrated Dirk",      "atk", "armor_pen_passive"),
            ("Long Sword",         "atk", "atk_passive"),
            ("Dagger",             "atk", "attack_speed_passive"),
        ],
        "advanced": [
            ("Cauterize",          "atk", "armor_pen_passive"),
            ("Serpent's Fang",     "atk", "armor_pen_passive"),
            ("Umbral Glaive",      "atk", "armor_pen_passive"),
            ("Prowler's Claw",     "atk", "armor_pen_passive"),
            ("Axiom Arc",          "atk", "armor_pen_passive"),
        ],
        "completed": [
            ("Duskblade of Draktharr", "atk", "armor_pen_passive"),
            ("Black Cleaver",          "atk", "armor_pen_passive"),
            ("Manamune",               "atk", "atk_passive"),
        ],
    },
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


def get_weekly_item_pool() -> tuple[str, dict]:
    """Return (category_display_name, category_dict) for the current week.

    The category_dict has keys 'basic', 'advanced', 'completed', each mapping
    to a list of (name, stat_type, passive) tuples.
    """
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



def _token_field_for_pool(pool_type: str) -> str:
    """Return the User attribute name for the token type matching pool_type."""
    return {
        "champion": "champion_tokens",
        "item": "item_tokens",
        "rune": "rune_tokens",
    }.get(pool_type, "champion_tokens")


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
    _token_field = _token_field_for_pool(pool_type)
    _token_count = getattr(user, _token_field, 0)
    if _token_count < SUMMON_TOKEN_COST:
        raise SummonError(
            f"Need {SUMMON_TOKEN_COST} {pool_type} tokens. Have {_token_count}."
        )
    setattr(user, _token_field, _token_count - SUMMON_TOKEN_COST)
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
    _token_field = _token_field_for_pool(pool_type)
    _token_count = getattr(user, _token_field, 0)
    if _token_count < SUMMON_MULTI_COST:
        raise SummonError(
            f"Need {SUMMON_MULTI_COST} {pool_type} tokens for 10x. Have {_token_count}."
        )
    setattr(user, _token_field, _token_count - SUMMON_MULTI_COST)
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
        _, item_cat = get_weekly_item_pool()
        # Roll tier: 75% basic, 20% advanced, 5% completed
        tier_name = random.choices(["basic", "advanced", "completed"], weights=[75, 20, 5], k=1)[0]
        tier_pool = item_cat.get(tier_name, item_cat.get("basic", []))
        if not tier_pool:
            tier_name = "basic"
            tier_pool = item_cat.get("basic", [])
        name, stat_type, passive = random.choice(tier_pool)
        # Set rank floor per tier; roll final rank clamped to floor
        rank_order = ["F", "E", "D", "C", "B", "A", "S"]
        if tier_name == "completed":
            floor = "A"
        elif tier_name == "advanced":
            floor = "C"
        else:
            floor = "F"
        # Use the rank rolled from the key (SUMMON_RATES) but clamp to floor
        rolled_rank = key.split("_")[1].upper() if "_" in key and key.split("_")[1].upper() in rank_order else "F"
        floor_idx = rank_order.index(floor)
        rolled_idx = rank_order.index(rolled_rank) if rolled_rank in rank_order else 0
        rank = rank_order[max(floor_idx, rolled_idx)]
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
            "tier": tier_name,
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
