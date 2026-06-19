from __future__ import annotations
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from data.rune_catalog import RUNE_CATALOG
from models.rune_instance import RuneInstance
from config.game_config import RUNE_RANK_MULTIPLIERS
from utils.counters import next_display_id


async def grant_rune(
    owner_id: str,
    rune_id: str,
    rank: str,
    session: AsyncIOMotorClientSession | None = None,
) -> RuneInstance:
    """Create and persist a new owned rune for the given owner."""
    did = await next_display_id("rune_instances")
    inst = RuneInstance(owner_id=owner_id, rune_id=rune_id, rank=rank, display_id=did)
    await inst.insert(session=usable_session(session))
    return inst


def apply_rune_bonuses(unit, rune_page, champion_level: int):
    """Apply rune page stat bonuses to a CombatUnit (mutated in place)."""
    all_slots = (
        list(rune_page.reds) +
        list(rune_page.yellows) +
        list(rune_page.blues) +
        list(rune_page.quints[:3])
    )

    for slot in all_slots:
        if not slot.rune_id:
            continue
        rune = RUNE_CATALOG.get(slot.rune_id)
        if not rune:
            continue
        stat = rune["stat"]
        rank = getattr(slot, "rank", "C")
        mult = RUNE_RANK_MULTIPLIERS.get(rank, 1.0)
        val = rune["value"] * mult

        if stat == "atk":
            unit.atk += int(val)
        elif stat == "hp":
            bonus = int(val)
            unit.hp += bonus
            unit.hp_max += bonus
        elif stat == "def_stat":
            unit.def_stat += int(val)
        elif stat == "spd":
            unit.spd += int(val)
        elif stat == "crit_chance":
            unit.crit_chance = getattr(unit, "crit_chance", 0.0) + val
        elif stat == "crit_dmg":
            unit.crit_dmg = getattr(unit, "crit_dmg", 175.0) + val
        elif stat == "armor_pen":
            unit.armor_pen = getattr(unit, "armor_pen", 0.0) + val
        elif stat == "magic_pen":
            unit.magic_pen = getattr(unit, "magic_pen", 0.0) + val
        elif stat == "magic_resist":
            unit.magic_resist = getattr(unit, "magic_resist", 0.0) + val
        elif stat == "lifesteal":
            unit.lifesteal = getattr(unit, "lifesteal", 0.0) + val
        elif stat == "dodge_chance":
            unit.dodge_chance = getattr(unit, "dodge_chance", 0.0) + val
        elif stat == "attack_speed":
            unit.attack_speed = getattr(unit, "attack_speed", 1.0) + val
        elif stat == "hp_regen":
            unit.hp_regen = getattr(unit, "hp_regen", 0) + val
        elif stat == "mana_gain_bonus":
            unit.mana_gain_bonus = getattr(unit, "mana_gain_bonus", 0) + val
        elif stat == "gold_find":
            unit.gold_find_mult = getattr(unit, "gold_find_mult", 1.0) + val
        elif stat == "xp_gain":
            unit.xp_gain_mult = getattr(unit, "xp_gain_mult", 1.0) + val
        elif stat == "atk_per_10_levels":
            unit.atk += int(val * (champion_level // 10))
