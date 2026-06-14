"""
Fully automatic combat engine.
No player input occurs after combat begins.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional

from config.game_config import (
    MAX_ROUNDS,
    MANA_MAX,
    MANA_ULTIMATE_THRESHOLD,
    RANK_INDEX,
    CHAMPION_BASE_STATS,
    CHAMPION_GROWTH_STATS,
    ENHANCEMENT_MULTIPLIER,
    ITEM_BASE_MAIN_STAT,
)
from engine.status_effects import (
    StatusEffect, Stun, Poison, Burn, Silence, DefenseDown, Shield,
)
from engine.skills import CHAMPION_SKILLS


# ---------------------------------------------------------------------------
# CombatUnit — runtime champion state
# ---------------------------------------------------------------------------
@dataclass
class CombatUnit:
    unit_id: str           # ChampionInstance id or "boss_X"
    name: str
    rank: str
    level: int
    position: int          # 1-5 (1-2 = front row)
    team: int              # 0 = player team, 1 = enemy team

    hp: int = 0
    hp_max: int = 0
    atk: float = 0.0
    def_stat: float = 0.0
    spd: int = 80
    mana: int = 0

    status_effects: list[StatusEffect] = field(default_factory=list)

    # Skill callables (set during build)
    basic_fn: Optional[callable] = field(default=None, repr=False)
    ultimate_fn: Optional[callable] = field(default=None, repr=False)

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    def has_effect(self, effect_type: type) -> bool:
        return any(isinstance(e, effect_type) for e in self.status_effects)

    def tick_effects_start(self) -> list[str]:
        """Process start-of-turn effects (poison). Returns log lines."""
        log = []
        for eff in list(self.status_effects):
            if isinstance(eff, Poison):
                dmg, msg = eff.apply_start_of_turn(self)
                log.append(msg)
        return log

    def tick_effects_end(self) -> list[str]:
        """Process end-of-turn effects (burn) and decrement durations."""
        log = []
        for eff in list(self.status_effects):
            if isinstance(eff, Burn):
                dmg, msg = eff.apply_end_of_turn(self)
                log.append(msg)
        # Expire effects
        expired = [e for e in self.status_effects if e.tick()]
        for e in expired:
            self.status_effects.remove(e)
            log.append(f"  {self.name}: {e.name} fades.")
        return log


# ---------------------------------------------------------------------------
# Build a CombatUnit from model data
# ---------------------------------------------------------------------------
def build_unit_from_champion(
    champ_doc,
    item_docs: list,
    position: int,
    team: int,
) -> CombatUnit:
    rank = champ_doc.rank
    lvl = champ_doc.level
    base = CHAMPION_BASE_STATS[rank]
    growth = CHAMPION_GROWTH_STATS[rank]

    hp  = base["hp"]  + growth["hp"]  * (lvl - 1)
    atk = base["atk"] + growth["atk"] * (lvl - 1)
    dfn = base["def"] + growth["def"] * (lvl - 1)
    spd = base["spd"]

    # Accumulate item main stats and secondary stats
    item_atk_bonus = 0
    item_hp_bonus  = 0
    item_def_bonus = 0
    item_spd_bonus = 0

    # Passive non-stacking: collect by passive_name, keep only best
    passive_pool: dict[str, tuple] = {}  # passive_name -> (rank_idx, enhancement, item)

    for itm in item_docs:
        enh_mult = ENHANCEMENT_MULTIPLIER.get(itm.enhancement, 0.0)
        eff_stat = itm.main_stat_base * (1 + enh_mult)

        if itm.main_stat_type == "atk":
            item_atk_bonus += eff_stat
        elif itm.main_stat_type == "hp":
            item_hp_bonus += eff_stat
        elif itm.main_stat_type == "def":
            item_def_bonus += eff_stat
        elif itm.main_stat_type == "spd":
            item_spd_bonus += eff_stat

        # Secondary stat contributions
        sec = itm.secondary_stat_type
        sec_val = itm.secondary_stat_value / 10.0  # stored *10
        if sec == "atk_pct":
            item_atk_bonus += atk * (sec_val / 100)
        elif sec == "hp_pct":
            item_hp_bonus += hp * (sec_val / 100)
        elif sec == "def_pct":
            item_def_bonus += dfn * (sec_val / 100)
        elif sec == "speed":
            item_spd_bonus += sec_val

        # Passive dedup — best by rank, then enhancement, then id
        pname = itm.passive_name
        cur = passive_pool.get(pname)
        this_key = (RANK_INDEX[itm.rank], itm.enhancement, str(itm.id))
        if cur is None or this_key > cur[0]:
            passive_pool[pname] = (this_key, itm)

    final_atk = atk + item_atk_bonus
    final_hp  = hp  + item_hp_bonus
    final_def = dfn + item_def_bonus
    final_spd = int(spd + item_spd_bonus)

    skills = CHAMPION_SKILLS.get(champ_doc.name, {})
    unit = CombatUnit(
        unit_id=str(champ_doc.id),
        name=champ_doc.name,
        rank=rank,
        level=lvl,
        position=position,
        team=team,
        hp=int(final_hp),
        hp_max=int(final_hp),
        atk=final_atk,
        def_stat=final_def,
        spd=final_spd,
        mana=0,
        basic_fn=skills.get("basic"),
        ultimate_fn=skills.get("ultimate"),
    )
    return unit


def build_boss_unit(boss_cfg: dict, position: int, team: int) -> CombatUnit:
    """Build an enemy CombatUnit from a boss config dict."""
    skills = CHAMPION_SKILLS.get(boss_cfg.get("champion_name", ""), {})
    unit = CombatUnit(
        unit_id=f"boss_{position}",
        name=boss_cfg["name"],
        rank=boss_cfg.get("rank", "D"),
        level=boss_cfg.get("level", 20),
        position=position,
        team=team,
        hp=boss_cfg["hp"],
        hp_max=boss_cfg["hp"],
        atk=boss_cfg["atk"],
        def_stat=boss_cfg["def"],
        spd=boss_cfg.get("spd", 90),
        mana=0,
        basic_fn=skills.get("basic"),
        ultimate_fn=skills.get("ultimate"),
    )
    return unit


# ---------------------------------------------------------------------------
# Turn order
# ---------------------------------------------------------------------------
def _sort_turn_order(units: list[CombatUnit]) -> list[CombatUnit]:
    return sorted(
        units,
        key=lambda u: (
            -u.spd,
            -RANK_INDEX.get(u.rank, 0),
            -u.level,
            random.random(),
        ),
    )


# ---------------------------------------------------------------------------
# Main battle resolver
# ---------------------------------------------------------------------------
@dataclass
class BattleResult:
    winner: int            # 0 = player team, 1 = enemy team, -1 = draw
    rounds: int
    log: list[str]
    player_survived: list[str]   # unit_ids of surviving player units
    enemy_survived: list[str]


def run_battle(
    player_units: list[CombatUnit],
    enemy_units: list[CombatUnit],
) -> BattleResult:
    log: list[str] = []
    all_units = player_units + enemy_units
    rounds = 0

    for rnd in range(1, MAX_ROUNDS + 1):
        rounds = rnd
        alive_players = [u for u in player_units if u.is_alive]
        alive_enemies = [u for u in enemy_units if u.is_alive]

        if not alive_players or not alive_enemies:
            break

        # Detect teams that cannot damage each other (invincible heal loops)
        if _detect_stalemate(alive_players, alive_enemies, rnd):
            log.append(f"[Round {rnd}] Stalemate detected — battle ends in DRAW.")
            return BattleResult(
                winner=-1, rounds=rnd, log=log,
                player_survived=[u.unit_id for u in alive_players],
                enemy_survived=[u.unit_id for u in alive_enemies],
            )

        log.append(f"\n=== Round {rnd} ===")
        turn_order = _sort_turn_order(alive_players + alive_enemies)

        for unit in turn_order:
            if not unit.is_alive:
                continue

            enemies_of_unit = alive_enemies if unit.team == 0 else alive_players
            allies_of_unit  = alive_players if unit.team == 0 else alive_enemies

            # Refresh alive lists
            enemies_of_unit = [u for u in enemies_of_unit if u.is_alive]
            allies_of_unit  = [u for u in allies_of_unit if u.is_alive]

            if not enemies_of_unit:
                break

            # Start-of-turn effects (poison)
            log.extend(unit.tick_effects_start())
            if not unit.is_alive:
                log.append(f"  {unit.name} has fallen to poison.")
                continue

            # Stun check
            if unit.has_effect(Stun):
                log.append(f"  {unit.name} is stunned — skipping turn.")
                unit.tick_effects_end()
                continue

            # Choose skill
            silenced = unit.has_effect(Silence)
            if unit.mana >= MANA_ULTIMATE_THRESHOLD and not silenced and unit.ultimate_fn:
                log.append(f"  {unit.name} casts ULTIMATE (mana={unit.mana})")
                skill_log = unit.ultimate_fn(unit, enemies_of_unit, allies_of_unit)
                unit.mana = 0
            elif unit.basic_fn:
                skill_log = unit.basic_fn(unit, enemies_of_unit, allies_of_unit)
                log.append(f"  {unit.name} uses basic skill (mana={unit.mana})")
            else:
                # Fallback: simple auto-attack
                t = random.choice(enemies_of_unit)
                dmg = max(1, int(unit.atk * 0.8))
                t.hp = max(0, t.hp - dmg)
                skill_log = [f"  {unit.name} attacks {t.name} for {dmg}."]
                unit.mana = min(MANA_MAX, unit.mana + 20)

            log.extend(skill_log)

            # End-of-turn effects
            log.extend(unit.tick_effects_end())

            # Death announcements
            for u in enemy_units + player_units:
                if u.hp == 0 and u in enemies_of_unit + allies_of_unit:
                    pass  # handled in next-round check

        # Post-round check
        alive_players = [u for u in player_units if u.is_alive]
        alive_enemies = [u for u in enemy_units if u.is_alive]
        for dead in [u for u in all_units if not u.is_alive]:
            log.append(f"  ✗ {dead.name} has been defeated.")

    # Final outcome
    alive_players = [u for u in player_units if u.is_alive]
    alive_enemies = [u for u in enemy_units if u.is_alive]

    if alive_players and not alive_enemies:
        winner = 0
        log.append("\n🏆 Victory! Your team wins!")
    elif alive_enemies and not alive_players:
        winner = 1
        log.append("\n💀 Defeat! Your team was wiped out.")
    else:
        winner = -1
        log.append(f"\n⏳ Battle ended after {MAX_ROUNDS} rounds — DRAW.")

    return BattleResult(
        winner=winner,
        rounds=rounds,
        log=log,
        player_survived=[u.unit_id for u in alive_players],
        enemy_survived=[u.unit_id for u in alive_enemies],
    )


def _detect_stalemate(
    players: list[CombatUnit],
    enemies: list[CombatUnit],
    current_round: int,
) -> bool:
    """After round 30 with no deaths possible, declare stalemate."""
    if current_round < 30:
        return False
    # If all player units and enemy units have full shields and no damage skills, stalemate
    # Simple heuristic: if both sides have max HP for 5+ rounds, it's a stalemate
    # We track this by checking if no unit took damage in the last 5 rounds
    # For simplicity, force stalemate after round 40 regardless
    return current_round >= 40


# ---------------------------------------------------------------------------
# Generate enemy teams from zone config
# ---------------------------------------------------------------------------
def generate_mob_team(zone: str, mob_count: int) -> list[CombatUnit]:
    """Create simple enemy combatants for a hunt zone."""
    from config.game_config import HUNT_ZONES, CHAMPION_BASE_STATS
    from engine.skills import ALL_CHAMPION_NAMES

    zone_cfg = HUNT_ZONES[zone]
    boss_rank = zone_cfg["boss_rank"]

    enemies = []
    for i in range(mob_count):
        champ_name = random.choice(ALL_CHAMPION_NAMES)
        skills = CHAMPION_SKILLS.get(champ_name, {})
        rank = "F"
        base = CHAMPION_BASE_STATS[rank]
        unit = CombatUnit(
            unit_id=f"mob_{i}",
            name=f"Mob {champ_name}",
            rank=rank,
            level=random.randint(1, 10),
            position=min(i + 1, 5),
            team=1,
            hp=base["hp"],
            hp_max=base["hp"],
            atk=base["atk"] * 0.8,
            def_stat=base["def"] * 0.8,
            spd=base["spd"],
            basic_fn=skills.get("basic"),
            ultimate_fn=skills.get("ultimate"),
        )
        enemies.append(unit)
    return enemies


def generate_boss_unit_for_zone(zone: str) -> CombatUnit:
    from config.game_config import HUNT_ZONES, CHAMPION_BASE_STATS
    zone_cfg = HUNT_ZONES[zone]
    rank = zone_cfg["boss_rank"]
    base = CHAMPION_BASE_STATS[rank]
    boss_cfg = {
        "name": zone_cfg["boss_name"],
        "rank": rank,
        "level": 30,
        "hp": int(base["hp"] * 3),
        "atk": int(base["atk"] * 1.5),
        "def": int(base["def"] * 1.5),
        "spd": base["spd"] - 5,
    }
    return build_boss_unit(boss_cfg, position=1, team=1)
