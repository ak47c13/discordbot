"""
Data-driven skill factory. Skills are defined as dicts; this module converts them
to callable functions matching the combat engine's expected signature:
    fn(caster: CombatUnit, all_enemies: list[CombatUnit], all_allies: list[CombatUnit]) -> int
The return value is mana gained (always 0 for ultimates). Basic skills also mutate
caster.mana directly so the running combat engine keeps working with either contract.
"""
from __future__ import annotations
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.combat import CombatUnit


def _resolve_targets(targeting: str, caster, all_enemies, all_allies):
    """Return a list of target CombatUnits based on targeting string."""
    alive_enemies = [u for u in all_enemies if u.hp > 0]
    alive_allies = [u for u in all_allies if u.hp > 0]

    if not alive_enemies and targeting not in (
        "self", "all_allies", "weakest_ally", "random_ally",
    ):
        return []

    if targeting == "front":
        front = [u for u in alive_enemies if u.position in (1, 2)]
        return [random.choice(front)] if front else ([alive_enemies[0]] if alive_enemies else [])
    elif targeting == "weakest":
        return [min(alive_enemies, key=lambda u: u.hp)] if alive_enemies else []
    elif targeting == "strongest":
        return [max(alive_enemies, key=lambda u: u.hp)] if alive_enemies else []
    elif targeting == "random":
        return [random.choice(alive_enemies)] if alive_enemies else []
    elif targeting == "all":
        return alive_enemies
    elif targeting == "back":
        back = [u for u in alive_enemies if u.position in (3, 4, 5)]
        return back if back else alive_enemies
    elif targeting == "self":
        return [caster]
    elif targeting == "all_allies":
        return alive_allies
    elif targeting == "weakest_ally":
        return [min(alive_allies, key=lambda u: u.hp)] if alive_allies else []
    elif targeting == "random_ally":
        return [random.choice(alive_allies)] if alive_allies else [caster]
    else:
        return [random.choice(alive_enemies)] if alive_enemies else []


def _unit_defense(t) -> float:
    """Effective defense including DefenseDown effects."""
    from engine.status_effects import DefenseDown
    defense = getattr(t, "def_stat", 0.0)
    for eff in t.status_effects:
        if isinstance(eff, DefenseDown):
            defense *= (1 - eff.reduction_pct)
    return max(0.0, defense)


def _apply_damage(target, damage: int):
    """Apply damage through shields first, then HP."""
    from engine.status_effects import Shield
    for eff in list(target.status_effects):
        if isinstance(eff, Shield) and eff.absorb > 0:
            _absorbed, damage = eff.absorb_damage(damage)
            if eff.absorb <= 0:
                target.status_effects.remove(eff)
            break
    target.hp = max(0, target.hp - damage)
    return target.hp


def make_skill(
    *,
    name: str,
    targeting: str,
    damage_type: str = "physical",   # "physical", "magic", "true", "none"
    coeff: float = 0.0,
    hits: int = 1,
    mana_gain: int = 0,
    heal_coeff: float = 0.0,
    heal_target: str = "weakest_ally",
    shield_coeff: float = 0.0,
    shield_target: str = "self",
    status: str | None = None,        # "stun","poison","burn","silence","defense_down"
    status_duration: int = 1,
    status_chance: float = 1.0,
    boss_cc_cap: bool = True,         # if True, bosses get 1-turn CC max
):
    """Return a skill function from a declarative definition dict."""

    def skill_fn(caster, all_enemies, all_allies):
        from engine.status_effects import (
            Stun, Poison, Burn, Silence, DefenseDown, Shield,
        )

        log: list[str] = []
        dmg_targets = _resolve_targets(targeting, caster, all_enemies, all_allies)

        # Damage
        for t in dmg_targets:
            for _ in range(hits):
                if t.hp <= 0:
                    break
                dmg = 0
                crit_chance = getattr(caster, "crit_chance", 0.0)
                crit_dmg_mult = getattr(caster, "crit_dmg", 1.75)
                armor_pen = getattr(caster, "armor_pen", 0.0)
                magic_pen = getattr(caster, "magic_pen", 0.0)
                lifesteal = getattr(caster, "lifesteal", 0.0)

                # General dodge check for physical hits
                if damage_type == "physical":
                    dodge = getattr(t, "dodge_chance", 0.0)
                    if dodge > 0 and random.random() < dodge:
                        log.append(f"  {t.name} dodges {caster.name}'s attack!")
                        continue

                if damage_type == "physical" and coeff > 0:
                    raw = caster.atk * coeff
                    df = max(0.0, _unit_defense(t) - armor_pen)
                    mitigation = df / (df + 200)
                    dmg = max(1, int(raw * (1 - mitigation)))
                elif damage_type == "magic" and coeff > 0:
                    raw = caster.atk * coeff * 1.1
                    pen_bonus = min(magic_pen, 50)
                    dmg = max(1, int(raw * (1 - (15 - pen_bonus) / 100)))
                elif damage_type == "true" and coeff > 0:
                    dmg = max(1, int(caster.atk * coeff))

                is_crit = crit_chance > 0 and random.random() < crit_chance
                if is_crit:
                    dmg = int(dmg * crit_dmg_mult)

                if dmg > 0:
                    _apply_damage(t, dmg)
                    crit_label = " 💥CRIT!" if is_crit else ""
                    log.append(f"  🗡️ {caster.name} hits {t.name} for {dmg:,} damage.{crit_label}")
                    if lifesteal > 0 and damage_type == "physical":
                        heal = int(dmg * lifesteal)
                        if heal > 0:
                            caster.hp = min(caster.hp_max, caster.hp + heal)
                            log.append(f"  🩸 {caster.name} leeches {heal} HP.")
                    if t.hp <= 0:
                        log.append(f"  💀 {t.name} is defeated!")

            # Status
            if status and random.random() < status_chance and t.hp > 0:
                eff_dur = (
                    1 if (boss_cc_cap and getattr(t, "is_boss", False)
                          and status in ("stun", "silence"))
                    else status_duration
                )
                if status == "stun":
                    t.status_effects.append(Stun(duration=eff_dur))
                elif status == "poison":
                    t.status_effects.append(
                        Poison(duration=eff_dur, damage_per_turn=int(caster.atk * 0.25))
                    )
                elif status == "burn":
                    t.status_effects.append(
                        Burn(duration=eff_dur, damage_per_turn=int(caster.atk * 0.25))
                    )
                elif status == "silence":
                    t.status_effects.append(Silence(duration=eff_dur))
                elif status == "defense_down":
                    t.status_effects.append(DefenseDown(duration=eff_dur, reduction_pct=0.25))
                _status_emoji = {
                    "stun": "⚡", "poison": "☠️", "burn": "🔥",
                    "silence": "🔇", "defense_down": "🛡️",
                }.get(status, "⚡")
                log.append(f"  {_status_emoji} {t.name} is afflicted with {status}.")

        # Heal
        if heal_coeff > 0:
            h_targets = _resolve_targets(heal_target, caster, all_enemies, all_allies)
            for t in h_targets:
                amount = int(caster.hp_max * heal_coeff)
                t.hp = min(t.hp_max, t.hp + amount)
                log.append(f"  💚 {caster.name} heals {t.name} for {amount:,} HP.")

        # Shield
        if shield_coeff > 0:
            s_targets = _resolve_targets(shield_target, caster, all_enemies, all_allies)
            shield_amount = int(caster.hp_max * shield_coeff)
            for t in s_targets:
                t.status_effects.append(Shield(absorb=shield_amount, duration=3))
                log.append(f"  🛡️ {t.name} gains a {shield_amount:,} HP shield.")

        # Mana: mutate caster directly for the combat engine, and report via return value.
        if mana_gain:
            caster.mana = min(100, caster.mana + mana_gain)
        else:
            # mana_gain == 0 identifies an ultimate: casting it consumes all mana.
            caster.mana = 0

        skill_fn.last_log = log
        return mana_gain

    skill_fn.__name__ = name.lower().replace(" ", "_").replace("'", "")
    skill_fn.__doc__ = name
    skill_fn.last_log = []
    return skill_fn


def skill_from_def(d: dict):
    """Create a skill function from a definition dict."""
    return make_skill(
        name=d["name"],
        targeting=d.get("targeting", "front"),
        damage_type=d.get("damage_type", "physical"),
        coeff=d.get("coeff", 0.0),
        hits=d.get("hits", 1),
        mana_gain=d.get("mana_gain", 0),
        heal_coeff=d.get("heal_coeff", 0.0),
        heal_target=d.get("heal_target", "weakest_ally"),
        shield_coeff=d.get("shield_coeff", 0.0),
        shield_target=d.get("shield_target", "self"),
        status=d.get("status"),
        status_duration=d.get("status_duration", 1),
        status_chance=d.get("status_chance", 1.0),
        boss_cc_cap=d.get("boss_cc_cap", True),
    )
