"""
Champion skill definitions. Each champion has exactly:
  - basic_skill(caster, targets, allies) -> list[str]  (log lines)
  - ultimate_skill(caster, targets, allies) -> list[str]

Both functions mutate CombatUnit objects directly and return battle log lines.
Mana generation is handled inside basic_skill.
"""
from __future__ import annotations
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.combat import CombatUnit

from engine.status_effects import Poison, Burn, Stun, Silence, DefenseDown, Shield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_damage(atk: float, defense: float, multiplier: float = 1.0) -> int:
    """Physical damage formula with defense mitigation."""
    raw = atk * multiplier
    mitigation = defense / (defense + 200)
    return max(1, int(raw * (1 - mitigation)))


def _calc_magic(matk: float, multiplier: float = 1.0) -> int:
    """Magic damage ignores defense (uses flat reduction = 50)."""
    return max(1, int(matk * multiplier * 0.9))


def _front_targets(enemies: list["CombatUnit"]) -> list["CombatUnit"]:
    alive = [u for u in enemies if u.hp > 0]
    front = [u for u in alive if u.position in (1, 2)]
    return front if front else alive


def _weakest(enemies: list["CombatUnit"]) -> list["CombatUnit"]:
    alive = [u for u in enemies if u.hp > 0]
    if not alive:
        return []
    return [min(alive, key=lambda u: u.hp)]


def _random_enemy(enemies: list["CombatUnit"]) -> list["CombatUnit"]:
    alive = [u for u in enemies if u.hp > 0]
    return [random.choice(alive)] if alive else []


def _all_enemies(enemies: list["CombatUnit"]) -> list["CombatUnit"]:
    return [u for u in enemies if u.hp > 0]


def _all_allies(allies: list["CombatUnit"], include_self: bool = True) -> list["CombatUnit"]:
    return [u for u in allies if u.hp > 0]


def _lowest_hp_ally(allies: list["CombatUnit"]) -> list["CombatUnit"]:
    alive = [u for u in allies if u.hp > 0]
    if not alive:
        return []
    return [min(alive, key=lambda u: u.hp)]


def _apply_damage(target: "CombatUnit", damage: int, log: list[str]) -> None:
    """Apply damage through shields first."""
    for eff in list(target.status_effects):
        if isinstance(eff, Shield) and eff.absorb > 0:
            absorbed, damage = eff.absorb_damage(damage)
            log.append(f"  Shield absorbs {absorbed} damage on {target.name}.")
            if eff.absorb <= 0:
                target.status_effects.remove(eff)
            break
    target.hp = max(0, target.hp - damage)


def _get_defense(target: "CombatUnit") -> float:
    defense = target.def_stat
    for eff in target.status_effects:
        if isinstance(eff, DefenseDown):
            defense *= (1 - eff.reduction_pct)
    return max(0.0, defense)


# ---------------------------------------------------------------------------
# RENGAR — Assassin: high single-target physical damage
# ---------------------------------------------------------------------------
def rengar_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _weakest(enemies)
    for t in targets:
        dmg = _calc_damage(caster.atk * 1.2, _get_defense(t), 1.0)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} slashes {t.name} for {dmg} damage.")
    caster.mana = min(100, caster.mana + 25)
    return log


def rengar_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _weakest(enemies)
    for t in targets:
        dmg = _calc_damage(caster.atk * 3.0, _get_defense(t), 1.0)
        _apply_damage(t, dmg, log)
        # Also applies bleed (poison)
        bleed = Poison(duration=3, damage_per_turn=int(caster.atk * 0.3))
        t.status_effects.append(bleed)
        log.append(f"  {caster.name} SAVAGES {t.name} for {dmg} damage and applies bleed!")
    return log


# ---------------------------------------------------------------------------
# LEONA — Tank: taunt and shield
# ---------------------------------------------------------------------------
def leona_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _front_targets(enemies)
    for t in targets[:1]:
        dmg = _calc_damage(caster.atk * 0.8, _get_defense(t), 1.0)
        dd = DefenseDown(duration=2, reduction_pct=0.20)
        t.status_effects.append(dd)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} strikes {t.name} for {dmg} damage (Defense -20% for 2 turns).")
    caster.mana = min(100, caster.mana + 20)
    return log


def leona_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    # Solar Flare: AoE stun + shield all allies
    alive_enemies = _all_enemies(enemies)
    for t in alive_enemies:
        dmg = _calc_damage(caster.atk * 1.0, _get_defense(t), 1.0)
        stun = Stun(duration=1)
        t.status_effects.append(stun)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} SOLAR FLARES {t.name} for {dmg} — STUNNED!")
    shield_val = int(caster.hp_max * 0.15)
    for ally in _all_allies(allies):
        ally.status_effects.append(Shield(duration=2, absorb=shield_val))
        log.append(f"  {ally.name} gains a {shield_val} HP shield.")
    return log


# ---------------------------------------------------------------------------
# SORAKA — Healer: heal + silence
# ---------------------------------------------------------------------------
def soraka_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _lowest_hp_ally(allies)
    for t in targets:
        heal = int(caster.atk * 1.5)
        t.hp = min(t.hp_max, t.hp + heal)
        log.append(f"  {caster.name} heals {t.name} for {heal} HP.")
    caster.mana = min(100, caster.mana + 30)
    return log


def soraka_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    # Heal all allies + silence all enemies
    for ally in _all_allies(allies):
        heal = int(caster.atk * 1.2)
        ally.hp = min(ally.hp_max, ally.hp + heal)
        log.append(f"  {caster.name} ASTRAL INFUSES {ally.name} for {heal} HP.")
    for t in _all_enemies(enemies):
        silence = Silence(duration=2)
        t.status_effects.append(silence)
        log.append(f"  {t.name} is SILENCED for 2 turns!")
    return log


# ---------------------------------------------------------------------------
# JINX — Ranged DPS: multi-target, AoE
# ---------------------------------------------------------------------------
def jinx_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = random.sample([u for u in enemies if u.hp > 0], min(2, len([u for u in enemies if u.hp > 0])))
    for t in targets:
        dmg = _calc_damage(caster.atk * 0.9, _get_defense(t), 1.0)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} sprays {t.name} for {dmg} damage.")
    caster.mana = min(100, caster.mana + 20)
    return log


def jinx_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    alive = [u for u in enemies if u.hp > 0]
    for t in alive:
        dmg = _calc_damage(caster.atk * 1.8, _get_defense(t), 1.0)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} SUPER MEGA DEATH ROCKETS {t.name} for {dmg}!")
    return log


# ---------------------------------------------------------------------------
# THRESH — Support: pull + shield
# ---------------------------------------------------------------------------
def thresh_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _front_targets(enemies)[:1]
    for t in targets:
        dmg = _calc_damage(caster.atk * 0.7, _get_defense(t), 1.0)
        dd = DefenseDown(duration=2, reduction_pct=0.25)
        t.status_effects.append(dd)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} HOOKS {t.name} for {dmg} (Defense -25%).")
    caster.mana = min(100, caster.mana + 25)
    return log


def thresh_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    # The Box: AoE slow (defense down) + shields weakest ally
    for t in _all_enemies(enemies):
        dmg = _calc_damage(caster.atk * 0.6, _get_defense(t), 1.0)
        dd = DefenseDown(duration=3, reduction_pct=0.30)
        t.status_effects.append(dd)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} DARK PASSAGE traps {t.name} for {dmg}!")
    for ally in _lowest_hp_ally(allies):
        shield_val = int(caster.hp_max * 0.20)
        ally.status_effects.append(Shield(duration=3, absorb=shield_val))
        log.append(f"  {ally.name} receives a {shield_val} HP lantern shield.")
    return log


# ---------------------------------------------------------------------------
# DARIUS — Bruiser: bleed stacks, front-row bully
# ---------------------------------------------------------------------------
def darius_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _front_targets(enemies)[:1]
    for t in targets:
        dmg = _calc_damage(caster.atk * 1.1, _get_defense(t), 1.0)
        bleed = Poison(duration=3, damage_per_turn=int(caster.atk * 0.2))
        t.status_effects.append(bleed)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} CRIPPLES {t.name} for {dmg} and applies hemorrhage!")
    caster.mana = min(100, caster.mana + 25)
    return log


def darius_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _weakest(enemies)
    for t in targets:
        # Noxian Guillotine: massive true damage (ignores defense) on low-HP targets
        hp_pct = t.hp / t.hp_max
        multiplier = 3.5 if hp_pct < 0.25 else 2.0
        dmg = max(1, int(caster.atk * multiplier))
        t.hp = max(0, t.hp - dmg)
        if t.hp == 0:
            log.append(f"  {caster.name} GUILLOTINES {t.name} for {dmg} — EXECUTION!")
        else:
            log.append(f"  {caster.name} GUILLOTINES {t.name} for {dmg} true damage!")
    return log


# ---------------------------------------------------------------------------
# LUX — Mage: AoE magic, team shield
# ---------------------------------------------------------------------------
def lux_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    targets = _front_targets(enemies)[:2]
    for t in targets:
        dmg = _calc_magic(caster.atk * 1.0)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} LIGHT BINDINGS {t.name} for {dmg} magic damage.")
    caster.mana = min(100, caster.mana + 22)
    return log


def lux_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    for t in _all_enemies(enemies):
        dmg = _calc_magic(caster.atk * 2.2)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} FINAL SPARKS {t.name} for {dmg} magic damage!")
    shield_val = int(caster.atk * 1.5)
    for ally in _all_allies(allies):
        ally.status_effects.append(Shield(duration=2, absorb=shield_val))
        log.append(f"  {ally.name} protected by a {shield_val} HP luminous shield.")
    return log


# ---------------------------------------------------------------------------
# YASUO — Swordsman: crit chance, wind wall passive-in-ultimate
# ---------------------------------------------------------------------------
def yasuo_basic(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    # Steel Tempest: hits all front-row
    targets = _front_targets(enemies)
    for t in targets:
        crit = random.random() < 0.35
        mult = 2.0 if crit else 1.0
        dmg = _calc_damage(caster.atk * mult, _get_defense(t), 1.0)
        _apply_damage(t, dmg, log)
        tag = " (CRIT!)" if crit else ""
        log.append(f"  {caster.name} STEEL TEMPEST {t.name} for {dmg}{tag}.")
    caster.mana = min(100, caster.mana + 20)
    return log


def yasuo_ultimate(caster: "CombatUnit", enemies: list["CombatUnit"], allies: list["CombatUnit"]) -> list[str]:
    log = []
    # Last Breath: lifts all enemies, guaranteed crit AoE + wind wall shield for team
    for t in _all_enemies(enemies):
        dmg = _calc_damage(caster.atk * 2.5, _get_defense(t), 1.0)
        # Guaranteed crit
        dmg = int(dmg * 2.0)
        stun = Stun(duration=1)
        t.status_effects.append(stun)
        _apply_damage(t, dmg, log)
        log.append(f"  {caster.name} LAST BREATH {t.name} for {dmg} (CRIT + STUN)!")
    # Wind Wall: dodge shield
    for ally in _all_allies(allies):
        ally.status_effects.append(Shield(duration=1, absorb=int(caster.atk * 1.0)))
        log.append(f"  Wind Wall protects {ally.name}.")
    return log


# ---------------------------------------------------------------------------
# Registry: maps champion name -> (basic_fn, ultimate_fn, mana_per_basic)
# ---------------------------------------------------------------------------
CHAMPION_SKILLS: dict[str, dict] = {
    "Rengar":  {"basic": rengar_basic,  "ultimate": rengar_ultimate,  "mana_gain": 25},
    "Leona":   {"basic": leona_basic,   "ultimate": leona_ultimate,   "mana_gain": 20},
    "Soraka":  {"basic": soraka_basic,  "ultimate": soraka_ultimate,  "mana_gain": 30},
    "Jinx":    {"basic": jinx_basic,    "ultimate": jinx_ultimate,    "mana_gain": 20},
    "Thresh":  {"basic": thresh_basic,  "ultimate": thresh_ultimate,  "mana_gain": 25},
    "Darius":  {"basic": darius_basic,  "ultimate": darius_ultimate,  "mana_gain": 25},
    "Lux":     {"basic": lux_basic,     "ultimate": lux_ultimate,     "mana_gain": 22},
    "Yasuo":   {"basic": yasuo_basic,   "ultimate": yasuo_ultimate,   "mana_gain": 20},
}

ALL_CHAMPION_NAMES = list(CHAMPION_SKILLS.keys())
