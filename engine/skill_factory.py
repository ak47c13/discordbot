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


def _apply_damage(target, damage: int, damage_type: str = "physical"):
    """Apply damage through shields first, then HP.

    Banshee's Veil blocks the first magic hit; Guardian Angel revive is
    handled in the main combat loop after all actions resolve.
    """
    from engine.status_effects import Shield

    # Banshee's Veil: block the first magic-damage hit
    if damage_type == "magic" and getattr(target, "banshee_ready", False):
        target.banshee_ready = False
        return target.hp  # damage fully absorbed

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
    self_buff: dict | None = None,    # {"stat": str, "value": float, "duration": int}
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
                crit_dmg_mult = getattr(caster, "crit_dmg", 175.0)
                armor_pen = getattr(caster, "armor_pen", 0.0)
                magic_pen = getattr(caster, "magic_pen", 0.0)
                lifesteal = getattr(caster, "lifesteal", 0.0)

                # General dodge check for physical hits
                if damage_type == "physical":
                    dodge = getattr(t, "dodge_chance", 0.0)
                    if dodge > 0 and random.random() < (dodge / 100.0):
                        log.append(f"  {t.name} dodges {caster.name}'s attack!")
                        continue

                if damage_type == "physical" and coeff > 0:
                    raw = caster.atk * coeff
                    df = max(0.0, _unit_defense(t) - armor_pen)
                    mitigation = df / (df + 200)
                    dmg = max(1, int(raw * (1 - mitigation)))
                elif damage_type == "magic" and coeff > 0:
                    ap = getattr(caster, "ap", 0.0)
                    # fall back to atk if champion has no AP (shouldn't happen for magic skills)
                    effective_power = ap if ap > 0 else caster.atk * 0.9
                    raw = effective_power * coeff
                    pen_bonus = min(magic_pen, 50)
                    target_mr = max(0.0, getattr(t, "magic_resist", 0.0) - pen_bonus)
                    mr_mitigation = target_mr / (target_mr + 200)
                    dmg = max(1, int(raw * (1 - mr_mitigation)))
                elif damage_type == "true" and coeff > 0:
                    dmg = max(1, int(caster.atk * coeff))

                is_crit = crit_chance > 0 and random.random() < (crit_chance / 100.0)
                if is_crit:
                    dmg = int(dmg * (crit_dmg_mult / 100.0))

                if dmg > 0:
                    _apply_damage(t, dmg, damage_type)
                    crit_label = " 💥CRIT!" if is_crit else ""
                    log.append(f"  🗡️ {caster.name} hits {t.name} for {dmg:,} damage.{crit_label}")
                    if lifesteal > 0 and damage_type in ("physical", "magic"):
                        heal = int(dmg * lifesteal / 100.0)
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

        # Self-buff (temporary stat increase; applied immediately, no expiry mechanic yet)
        # Value is applied as a flat additive boost. Not reversed — intentional simplification.
        if self_buff:
            _stat = self_buff.get("stat", "")
            _val = self_buff.get("value", 0)
            _dur = self_buff.get("duration", 1)
            if _stat == "atk":
                caster.atk += _val
                log.append(f"  ⬆️ {caster.name} gains +{_val} ATK ({name}) for {_dur} rounds.")
            elif _stat == "def_stat":
                # value is a multiplier (e.g. 0.20 = +20% DEF)
                bonus = int(caster.def_stat * _val)
                caster.def_stat += bonus
                log.append(f"  🛡️ {caster.name} gains +{bonus} DEF ({name}) for {_dur} rounds.")
            elif _stat == "spd":
                caster.spd = int(caster.spd + _val)
                log.append(f"  💨 {caster.name} gains +{int(_val)} SPD ({name}) for {_dur} rounds.")

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
        self_buff=d.get("self_buff"),
    )
