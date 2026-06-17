from data.rune_catalog import RUNE_CATALOG


def apply_rune_bonuses(unit, rune_page, champion_level: int):
    """Apply rune page stat bonuses to a CombatUnit (mutated in place)."""
    all_rune_ids = (
        [s.rune_id for s in rune_page.reds] +
        [s.rune_id for s in rune_page.yellows] +
        [s.rune_id for s in rune_page.blues] +
        [s.rune_id for s in rune_page.quints[:3]]
    )

    for rune_id in all_rune_ids:
        if not rune_id:
            continue
        rune = RUNE_CATALOG.get(rune_id)
        if not rune:
            continue
        stat = rune["stat"]
        val = rune["value"]

        if stat == "atk":
            unit.atk += val
        elif stat == "hp":
            unit.hp += val
            unit.hp_max += val
        elif stat == "def_stat":
            unit.def_stat += val
        elif stat == "spd":
            unit.spd += val
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
            unit.atk += val * (champion_level // 10)
