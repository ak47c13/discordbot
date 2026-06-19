"""
Data-driven skill factory — Phase 2 engine.

Skills are defined as dicts; this module converts them to callable functions.

Signature:
    fn(caster: CombatUnit, all_enemies: list, all_allies: list) -> int
    Returns mana gained (0 for ultimates).

TIER SYSTEM
-----------
Each skill dict may optionally include "advanced" and "prestige" sub-dicts
that override base fields at higher ranks:
    base     — F, E, D  (default, backward-compatible with old flat dicts)
    advanced — C, B     (overrides base fields)
    prestige — A, S     (overrides advanced fields; feel the difference)

MECHANICS
---------
"mechanic" field activates one special behavior per skill:
    execute        — bonus true damage when target HP% < mechanic_value
    stack_damage   — caster builds stacks per cast; +mechanic_value% ATK/stack (cap 6)
    reset_on_kill  — killing any target sets caster mana to 100 (fires R again next turn)
    armor_shred    — reduces target def_stat by mechanic_value% flat after damage
    drain          — lifesteal at mechanic_value rate (overrides item lifesteal)
    mark_detonate  — skill marks target; next skill from same caster detonates for 2× bonus

AP RATIO
--------
"ap_ratio" float (0.0–1.0) splits damage between ATK and AP:
    0.0 = pure physical/ATK  (default)
    1.0 = pure magic/AP      (default for magic skills)
    0.5 = hybrid             (uses both stats, applies both mitigations)
"""
from __future__ import annotations
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.combat import CombatUnit

RANK_ORDER = ["F", "E", "D", "C", "B", "A", "S"]


def _rank_index(rank: str) -> int:
    try:
        return RANK_ORDER.index(rank)
    except ValueError:
        return 0


def _resolve_tier(d: dict, rank: str) -> dict:
    """Merge base skill dict with tier overrides based on rank."""
    idx = _rank_index(rank)
    # Build from base (strip tier sub-dicts)
    resolved = {k: v for k, v in d.items() if k not in ("advanced", "prestige")}
    if idx >= 3:  # C or higher → apply advanced
        resolved.update(d.get("advanced", {}))
    if idx >= 5:  # A or higher → apply prestige
        resolved.update(d.get("prestige", {}))
    return resolved


def _resolve_targets(targeting: str, caster, all_enemies, all_allies):
    """Return a list of target CombatUnits based on targeting string."""
    alive_enemies = [u for u in all_enemies if u.hp > 0]
    alive_allies  = [u for u in all_allies  if u.hp > 0]

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
    """Apply damage through shields first, then HP."""
    from engine.status_effects import Shield

    # Banshee's Veil: block the first magic-damage hit
    if damage_type == "magic" and getattr(target, "banshee_ready", False):
        target.banshee_ready = False
        return target.hp

    for eff in list(target.status_effects):
        if isinstance(eff, Shield) and eff.absorb > 0:
            _absorbed, damage = eff.absorb_damage(damage)
            if eff.absorb <= 0:
                target.status_effects.remove(eff)
            break
    target.hp = max(0, target.hp - damage)
    return target.hp


def _calc_phys_damage(caster, t, coeff: float, armor_pen: float) -> int:
    raw = caster.atk * coeff
    df  = max(0.0, _unit_defense(t) - armor_pen)
    mit = df / (df + 200)
    return max(1, int(raw * (1 - mit)))


def _calc_magic_damage(caster, t, coeff: float, magic_pen: float) -> int:
    ap = getattr(caster, "ap", 0.0)
    effective_power = ap if ap > 0 else caster.atk * 0.9
    raw = effective_power * coeff
    pen = min(magic_pen, 50)
    mr  = max(0.0, getattr(t, "magic_resist", 0.0) - pen)
    mit = mr / (mr + 200)
    return max(1, int(raw * (1 - mit)))


def _calc_true_damage(caster, coeff: float) -> int:
    return max(1, int(caster.atk * coeff))


def make_skill(
    *,
    name: str,
    targeting: str,
    damage_type: str    = "physical",
    coeff: float        = 0.0,
    hits: int           = 1,
    mana_gain: int      = 0,
    heal_coeff: float   = 0.0,
    heal_target: str    = "weakest_ally",
    shield_coeff: float = 0.0,
    shield_target: str  = "self",
    status: str | None  = None,
    status_duration: int   = 1,
    status_chance: float   = 1.0,
    boss_cc_cap: bool      = True,
    self_buff: dict | None = None,
    # --- Phase 2 additions ---
    mechanic: str | None   = None,   # execute | stack_damage | reset_on_kill | armor_shred | drain | mark_detonate
    mechanic_value: float  = 0.0,
    ap_ratio: float        = 0.0,    # 0=pure ATK-based, 1=pure AP-based, 0.5=hybrid
):
    """Return a skill function from a declarative definition dict."""

    def skill_fn(caster, all_enemies, all_allies):
        from engine.status_effects import Stun, Poison, Burn, Silence, DefenseDown, Shield

        log: list[str] = []
        dmg_targets = _resolve_targets(targeting, caster, all_enemies, all_allies)

        total_damage_dealt = 0
        killed_any = False

        armor_pen  = getattr(caster, "armor_pen",  0.0)
        magic_pen  = getattr(caster, "magic_pen",  0.0)
        crit_chance = getattr(caster, "crit_chance", 0.0)
        crit_dmg_mult = getattr(caster, "crit_dmg",  175.0)
        lifesteal  = getattr(caster, "lifesteal",  0.0)

        # stack_damage: build stacks on caster per cast
        if mechanic == "stack_damage":
            caster.skill_stacks = min(6, getattr(caster, "skill_stacks", 0) + 1)
            stack_bonus_coeff = coeff + mechanic_value * caster.skill_stacks
        else:
            stack_bonus_coeff = coeff

        # mark_detonate: if target already marked by this caster, detonate for 2× bonus
        detonate_bonus = False
        if mechanic == "mark_detonate":
            first_target = dmg_targets[0] if dmg_targets else None
            if first_target and getattr(first_target, "marked_by", None) == id(caster):
                detonate_bonus = True
                first_target.marked_by = None
            elif first_target:
                first_target.marked_by = id(caster)

        for t in dmg_targets:
            for hit_num in range(hits):
                if t.hp <= 0:
                    break

                # Dodge check for physical hits
                if damage_type == "physical":
                    dodge = getattr(t, "dodge_chance", 0.0)
                    if dodge > 0 and random.random() < (dodge / 100.0):
                        log.append(f"  {t.name} dodges {caster.name}'s attack!")
                        continue

                # --- Damage calculation ---
                dmg = 0
                active_coeff = stack_bonus_coeff if mechanic == "stack_damage" else coeff

                if active_coeff > 0:
                    if damage_type == "physical":
                        dmg = _calc_phys_damage(caster, t, active_coeff, armor_pen)
                    elif damage_type == "magic":
                        dmg = _calc_magic_damage(caster, t, active_coeff, magic_pen)
                    elif damage_type == "true":
                        dmg = _calc_true_damage(caster, active_coeff)
                    elif damage_type == "hybrid":
                        # Split between physical and magic
                        phys_coeff  = active_coeff * (1.0 - ap_ratio)
                        magic_coeff = active_coeff * ap_ratio
                        phys_dmg  = _calc_phys_damage(caster, t, phys_coeff, armor_pen)  if phys_coeff  > 0 else 0
                        magic_dmg = _calc_magic_damage(caster, t, magic_coeff, magic_pen) if magic_coeff > 0 else 0
                        dmg = phys_dmg + magic_dmg

                # mark_detonate: double damage on detonation
                if detonate_bonus and dmg > 0:
                    dmg = int(dmg * 2.0)
                    detonate_bonus = False  # only once

                # Crit
                is_crit = crit_chance > 0 and random.random() < (crit_chance / 100.0)
                if is_crit and dmg > 0:
                    dmg = int(dmg * (crit_dmg_mult / 100.0))

                # Execute mechanic: bonus true damage when target is low HP
                execute_dmg = 0
                if mechanic == "execute" and mechanic_value > 0 and dmg > 0:
                    if t.hp / max(1, t.hp_max) < mechanic_value:
                        execute_dmg = max(1, int(caster.atk * mechanic_value * 2))

                if dmg > 0:
                    _apply_damage(t, dmg, damage_type if damage_type != "hybrid" else "physical")
                    total_damage_dealt += dmg
                    crit_label = " 💥CRIT!" if is_crit else ""
                    stack_label = f" [{caster.skill_stacks} stacks]" if mechanic == "stack_damage" else ""
                    log.append(f"  🗡️ {caster.name} hits {t.name} for {dmg:,} damage.{crit_label}{stack_label}")

                    # Lifesteal (drain mechanic uses mechanic_value rate instead)
                    steal_rate = mechanic_value if mechanic == "drain" else lifesteal
                    if steal_rate > 0 and damage_type in ("physical", "magic", "hybrid"):
                        heal = int(dmg * steal_rate / 100.0)
                        if heal > 0:
                            caster.hp = min(caster.hp_max, caster.hp + heal)
                            log.append(f"  🩸 {caster.name} leeches {heal} HP.")

                    # Execute bonus
                    if execute_dmg > 0 and t.hp > 0:
                        _apply_damage(t, execute_dmg, "true")
                        total_damage_dealt += execute_dmg
                        log.append(f"  ⚔️ {caster.name} executes {t.name} for {execute_dmg:,} true damage!")

                    # Armor shred mechanic
                    if mechanic == "armor_shred" and mechanic_value > 0 and t.hp > 0:
                        shred = t.def_stat * mechanic_value
                        t.def_stat = max(0.0, t.def_stat - shred)
                        log.append(f"  🪓 {t.name}'s armor shredded by {int(shred)} ({mechanic_value*100:.0f}%).")

                    if t.hp <= 0:
                        log.append(f"  💀 {t.name} is defeated!")
                        killed_any = True

            # Status effect application (per target, after all hits)
            if status and t.hp > 0 and random.random() < status_chance:
                eff_dur = (
                    1 if (boss_cc_cap and getattr(t, "is_boss", False)
                          and status in ("stun", "silence"))
                    else status_duration
                )
                if status == "stun":
                    from engine.status_effects import StunImmunity
                    if any(isinstance(e, StunImmunity) for e in t.status_effects):
                        log.append(f"  🛡️ {t.name} is stun-immune — resists the stun!")
                    elif any(isinstance(e, Stun) for e in t.status_effects):
                        pass  # already stunned — don't refresh, let it expire naturally
                    else:
                        t.status_effects.append(Stun(duration=eff_dur))
                elif status == "poison":
                    t.status_effects.append(Poison(duration=eff_dur, damage_per_turn=int(caster.atk * 0.25)))
                elif status == "burn":
                    t.status_effects.append(Burn(duration=eff_dur, damage_per_turn=int(caster.atk * 0.25)))
                elif status == "silence":
                    existing = next((e for e in t.status_effects if isinstance(e, Silence)), None)
                    if existing:
                        existing.duration = max(existing.duration, eff_dur)
                    else:
                        t.status_effects.append(Silence(duration=eff_dur))
                elif status == "defense_down":
                    t.status_effects.append(DefenseDown(duration=eff_dur, reduction_pct=0.25))
                _status_emoji = {
                    "stun": "⚡", "poison": "☠️", "burn": "🔥",
                    "silence": "🔇", "defense_down": "🛡️",
                }.get(status, "⚡")
                log.append(f"  {_status_emoji} {t.name} is afflicted with {status}.")

        # reset_on_kill mechanic: if any target died, caster mana → 100 (fires R next turn)
        if mechanic == "reset_on_kill" and killed_any and mana_gain == 0:
            caster.pending_reset = True
            log.append(f"  🔄 {caster.name} resets! Ultimate available again.")

        # Heal
        if heal_coeff > 0:
            h_targets = _resolve_targets(heal_target, caster, all_enemies, all_allies)
            for t in h_targets:
                if coeff > 0 and total_damage_dealt > 0:
                    amount = int(total_damage_dealt * heal_coeff)
                else:
                    amount = int(caster.hp_max * heal_coeff)
                if amount > 0:
                    t.hp = min(t.hp_max, t.hp + amount)
                    log.append(f"  💚 {caster.name} heals {t.name} for {amount:,} HP.")

        # Shield
        if shield_coeff > 0:
            s_targets = _resolve_targets(shield_target, caster, all_enemies, all_allies)
            shield_amount = int(caster.hp_max * shield_coeff)
            for t in s_targets:
                t.status_effects.append(Shield(absorb=shield_amount, duration=3))
                log.append(f"  🛡️ {t.name} gains a {shield_amount:,} HP shield.")

        # Self-buff
        if self_buff:
            _stat = self_buff.get("stat", "")
            _val  = self_buff.get("value", 0)
            if _stat == "atk":
                caster.atk += _val
                log.append(f"  ⬆️ {caster.name} gains +{_val} ATK ({name}).")
            elif _stat == "def_stat":
                bonus = int(caster.def_stat * _val)
                caster.def_stat += bonus
                log.append(f"  🛡️ {caster.name} gains +{bonus} DEF ({name}).")
            elif _stat == "spd":
                caster.spd = int(caster.spd + _val)
                log.append(f"  💨 {caster.name} gains +{int(_val)} SPD ({name}).")

        # Mana
        if mana_gain:
            caster.mana = min(100, caster.mana + mana_gain)
        else:
            caster.mana = 0

        skill_fn.last_log = log
        return mana_gain

    skill_fn.__name__ = name.lower().replace(" ", "_").replace("'", "")
    skill_fn.__doc__  = name
    skill_fn.last_log = []
    return skill_fn


def skill_from_def(d: dict, rank: str = "F"):
    """Create a skill function from a definition dict, resolved to the correct tier."""
    resolved = _resolve_tier(d, rank)
    return make_skill(
        name            = resolved["name"],
        targeting       = resolved.get("targeting", "front"),
        damage_type     = resolved.get("damage_type", "physical"),
        coeff           = resolved.get("coeff", 0.0),
        hits            = resolved.get("hits", 1),
        mana_gain       = resolved.get("mana_gain", 0),
        heal_coeff      = resolved.get("heal_coeff", 0.0),
        heal_target     = resolved.get("heal_target", "weakest_ally"),
        shield_coeff    = resolved.get("shield_coeff", 0.0),
        shield_target   = resolved.get("shield_target", "self"),
        status          = resolved.get("status"),
        status_duration = resolved.get("status_duration", 1),
        status_chance   = resolved.get("status_chance", 1.0),
        boss_cc_cap     = resolved.get("boss_cc_cap", True),
        self_buff       = resolved.get("self_buff"),
        mechanic        = resolved.get("mechanic"),
        mechanic_value  = resolved.get("mechanic_value", 0.0),
        ap_ratio        = resolved.get("ap_ratio", 0.0),
    )
