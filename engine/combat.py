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

    # Extended stats
    crit_chance: float = 0.0      # percent (0–100)
    crit_dmg: float = 175.0       # percent (175 = 1.75× multiplier)
    armor_pen: float = 0.0        # flat armor penetration
    magic_pen: float = 0.0        # flat magic penetration
    magic_resist: float = 0.0     # flat magic resistance
    lifesteal: float = 0.0        # percent (0–100)
    dodge_chance: float = 0.0     # percent (0–100)
    attack_speed: float = 1.0     # multiplier

    # Item passive state
    has_sheen: bool = False           # True if unit has a Sheen/Trinity Force item equipped
    guardian_angel_ready: bool = False  # True if Guardian Angel has not yet triggered
    has_sterak: bool = False          # True if unit has Sterak's Gage
    sterak_triggered: bool = False    # True once Sterak's Gage shield has already fired
    banshee_ready: bool = False       # True if Banshee's Veil spell shield is active
    reflect_damage_pct: float = 0.0   # % of damage to return to attacker (Thornmail)
    sunfire_burn: bool = False        # True if unit has Sunfire Aegis (burns nearby enemies)
    liandry_burn: bool = False        # True if unit has Liandry's Anguish (burns on ability hit)
    warmog_regen: bool = False        # True if unit has Warmog's Armor (regenerate HP each round)

    # Boss mechanic state
    is_boss: bool = False
    mechanic: str = ""
    mechanic_triggered: bool = False

    # Dungeon boss passive state
    undying: bool = False
    undying_rounds: int = 0
    feast_stacks: int = 0
    darius_stacks: int = 0
    converted: bool = False   # mordekaiser: a defeated player champ now fights for the boss

    # Contribution tracking (for raid drop attribution)
    damage_dealt: int = 0
    damage_taken: int = 0

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
    active_skill_key: str = "q",
    rune_page=None,
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

    # ------------------------------------------------------------------
    # Resolve passive effects from the best item of each passive type.
    # passive_pool maps passive_name -> (sort_key, item).
    # We accumulate numeric bonuses here (before building the unit) so
    # we can pass them as constructor arguments.
    # ------------------------------------------------------------------
    passive_crit_chance: float = 0.0
    passive_crit_dmg: float = 0.0       # bonus on top of base 175
    passive_magic_resist: float = 0.0
    passive_lifesteal: float = 0.0
    passive_attack_speed: float = 0.0
    passive_armor_pen: float = 0.0
    has_sheen = False
    has_guardian_angel = False
    has_sterak = False
    has_banshee = False
    reflect_pct: float = 0.0
    has_sunfire = False
    has_liandry = False
    has_warmog = False

    # Also scan all items (not just best-per-passive) for numeric passives
    # that stack across items — but follow the dedup rule: only the best
    # item per passive key contributes its *passive* bonus.
    for pname, (_, itm) in passive_pool.items():
        if pname == "crit_damage_passive":
            # Infinity Edge: crit_dmg cap raised to 235, others give crit chance
            if itm.name == "Infinity Edge":
                passive_crit_dmg += 60.0      # 175 + 60 = 235%
            else:
                passive_crit_chance += 10.0   # generic crit item
        elif pname == "attack_speed_passive":
            passive_attack_speed += 0.20      # +20% attack speed per item tier
        elif pname == "lifesteal_passive":
            passive_lifesteal += 12.0         # 12% lifesteal
        elif pname == "magic_resist_passive":
            passive_magic_resist += 30.0      # +30 MR from best MR item
        elif pname == "armor_pen_passive":
            passive_armor_pen += 20.0         # flat armor pen
        elif pname == "sheen_passive":
            has_sheen = True

        # Item-name-specific specials
        if itm.name == "Guardian Angel":
            has_guardian_angel = True
        elif itm.name == "Sterak's Gage":
            has_sterak = True
        elif itm.name == "Banshee's Veil":
            has_banshee = True
        elif itm.name == "Thornmail":
            reflect_pct = 0.25
        elif itm.name == "Sunfire Aegis":
            has_sunfire = True
        elif itm.name == "Liandry's Anguish":
            has_liandry = True
        elif itm.name == "Warmog's Armor":
            has_warmog = True

    skills = CHAMPION_SKILLS.get(champ_doc.name, {})
    # Use player's chosen basic skill (q/w/e); R is always the ultimate
    basic_fn = skills.get(active_skill_key) or skills.get("q") or skills.get("basic")
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
        basic_fn=basic_fn,
        ultimate_fn=skills.get("r") or skills.get("ultimate"),
    )

    # Apply item passive bonuses to the unit
    if passive_crit_chance > 0:
        unit.crit_chance += passive_crit_chance
    if passive_crit_dmg > 0:
        unit.crit_dmg += passive_crit_dmg
    if passive_magic_resist > 0:
        unit.magic_resist += passive_magic_resist
    if passive_lifesteal > 0:
        unit.lifesteal += passive_lifesteal
    if passive_attack_speed > 0:
        unit.attack_speed += passive_attack_speed
    if passive_armor_pen > 0:
        unit.armor_pen += passive_armor_pen
    if has_sheen:
        unit.has_sheen = True
    if has_guardian_angel:
        unit.guardian_angel_ready = True
    if has_sterak:
        unit.has_sterak = True
        unit.sterak_triggered = False
    if has_banshee:
        unit.banshee_ready = True
    if reflect_pct > 0:
        unit.reflect_damage_pct = reflect_pct
    if has_sunfire:
        unit.sunfire_burn = True
    if has_liandry:
        unit.liandry_burn = True
    if has_warmog:
        unit.warmog_regen = True

    # Apply rune bonuses (after base stats + items, before combat)
    if rune_page is not None:
        from services.rune_service import apply_rune_bonuses
        apply_rune_bonuses(unit, rune_page, lvl)

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
        is_boss=boss_cfg.get("is_boss", True),
        mechanic=boss_cfg.get("mechanic", ""),
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
    # unit_id -> {"damage_dealt": int, "damage_taken": int} for all player units
    contributions: dict = field(default_factory=dict)


def _invoke_skill(fn, unit, enemies, allies) -> list[str]:
    """Call a skill function (which returns mana int) and recover its log lines."""
    result = fn(unit, enemies, allies)
    if isinstance(result, list):
        # Legacy contract: function already returned log lines.
        return result
    return list(getattr(fn, "last_log", []) or [])


def _reflect_ratio(boss) -> float:
    from config.game_config import BOSS_MECHANICS
    for cfg in BOSS_MECHANICS.values():
        if cfg.get("mechanic") == "reflect":
            return cfg.get("reflect_ratio", 0.15)
    return 0.15


def _apply_boss_mechanics(enemy_units, rnd, log):
    """Apply per-round boss mechanic triggers."""
    from config.game_config import BOSS_MECHANICS, CHAMPION_BASE_STATS
    from engine.status_effects import Shield

    spawned = []
    for boss in [b for b in enemy_units if getattr(b, "is_boss", False)]:
        cfg = None
        for zcfg in BOSS_MECHANICS.values():
            if zcfg.get("mechanic") == boss.mechanic:
                cfg = zcfg
                break
        if cfg is None:
            continue

        # Shield: applied once at round 1.
        if boss.mechanic == "shield" and rnd == 1 and not boss.mechanic_triggered:
            amt = int(boss.hp_max * cfg.get("shield_hp_ratio", 0.20))
            boss.status_effects.append(Shield(absorb=amt, duration=99))
            boss.mechanic_triggered = True
            log.append(f"  {boss.name} raises a {amt} HP barrier!")

        # Adds: spawn mini-bosses at round 10.
        if boss.mechanic == "adds" and rnd == 10 and not boss.mechanic_triggered:
            boss.mechanic_triggered = True
            for i in range(cfg.get("add_count", 2)):
                add = CombatUnit(
                    unit_id=f"{boss.unit_id}_add_{i}",
                    name=f"{boss.name} Add {i + 1}",
                    rank=boss.rank,
                    level=boss.level,
                    position=min(i + 2, 5),
                    team=boss.team,
                    hp=int(boss.hp_max * 0.30),
                    hp_max=int(boss.hp_max * 0.30),
                    atk=boss.atk * 0.30,
                    def_stat=boss.def_stat * 0.30,
                    spd=boss.spd,
                    basic_fn=boss.basic_fn,
                    ultimate_fn=boss.ultimate_fn,
                )
                spawned.append(add)
                log.append(f"  {boss.name} summons {add.name}!")

        # Enrage: multiply ATK at the enrage round.
        if boss.mechanic == "enrage" and rnd == cfg.get("enrage_round", 30) and not boss.mechanic_triggered:
            boss.atk *= cfg.get("enrage_atk_mult", 2.0)
            boss.mechanic_triggered = True
            log.append(f"  {boss.name} ENRAGES — attack power surges!")

    return spawned


# ---------------------------------------------------------------------------
# Dungeon boss passives (round-by-round hooks)
# ---------------------------------------------------------------------------
def _dungeon_bosses(units: list[CombatUnit]) -> list[CombatUnit]:
    return [u for u in units if getattr(u, "is_boss", False) and getattr(u, "mechanic", "")]


def _apply_round_start_passives(
    player_units: list[CombatUnit],
    enemy_units: list[CombatUnit],
    rnd: int,
    log: list[str],
) -> None:
    """Apply dungeon boss passives that trigger at the start of a round."""
    from engine.status_effects import Shield, Stun
    for boss in _dungeon_bosses(enemy_units):
        if not boss.is_alive:
            continue
        m = boss.mechanic

        if m == "garen_passive":
            heal = int(boss.hp_max * 0.05)
            if boss.hp < boss.hp_max:
                boss.hp = min(boss.hp_max, boss.hp + heal)
                log.append(f"  {boss.name} regenerates {heal:,} HP (Perseverance).")

        elif m == "darius_passive":
            boss.darius_stacks += 1
            boss.atk *= 1.08
            log.append(f"  {boss.name} gains Hemorrhage — ATK rising ({boss.darius_stacks} stacks).")

        elif m == "jarvan_passive" and rnd == 1 and not boss.mechanic_triggered:
            amt = int(boss.hp_max * 0.25)
            boss.status_effects.append(Shield(absorb=amt, duration=99))
            boss.mechanic_triggered = True
            log.append(f"  {boss.name} raises a {amt:,} HP shield (Demacian Standard)!")

        elif m == "chogath_passive":
            boss.feast_stacks += 1
            gain = int(boss.hp_max * 0.05)
            boss.hp_max += gain
            boss.hp += gain
            log.append(f"  {boss.name} feasts — max HP grows ({boss.feast_stacks} stacks).")

        elif m == "jayce_passive":
            # Alternate cannon (high ATK / low DEF) and hammer (low ATK / high DEF).
            if rnd % 2 == 1:
                boss.atk = boss.atk * 1.4
                boss.def_stat = boss.def_stat * 0.6
                log.append(f"  {boss.name} shifts to CANNON form (Mercury Cannon).")
            else:
                boss.atk = boss.atk / 1.4 * 0.6
                boss.def_stat = boss.def_stat / 0.6 * 1.4
                log.append(f"  {boss.name} shifts to HAMMER form (Mercury Hammer).")

        elif m == "sejuani_passive" and rnd == 3 and not boss.mechanic_triggered:
            boss.mechanic_triggered = True
            alive = [u for u in player_units if u.is_alive]
            if alive:
                target = max(alive, key=lambda u: u.atk)
                target.status_effects.append(Stun(duration=1))
                log.append(f"  {boss.name} freezes {target.name} solid (Permafrost)!")


def _apply_round_end_passives(
    player_units: list[CombatUnit],
    enemy_units: list[CombatUnit],
    rnd: int,
    log: list[str],
) -> None:
    """Apply dungeon boss passives that trigger at the end of a round."""
    for boss in _dungeon_bosses(enemy_units):
        if not boss.is_alive:
            continue
        m = boss.mechanic

        if m == "swain_passive":
            alive = [u for u in player_units if u.is_alive]
            total = sum(u.hp for u in alive)
            drain = int(total * 0.08)
            if drain > 0:
                per = max(1, drain // max(1, len(alive)))
                for u in alive:
                    u.hp = max(0, u.hp - per)
                boss.hp = min(boss.hp_max, boss.hp + drain)
                log.append(f"  {boss.name} drains {drain:,} HP from your team (Soul Steal).")

        elif m == "gangplank_passive" and rnd in (5, 10, 15):
            alive = [u for u in player_units if u.is_alive]
            for u in alive:
                dmg = max(1, int(u.hp * 0.15))
                u.hp = max(0, u.hp - dmg)
            if alive:
                log.append(f"  {boss.name} fires a CANNON BARRAGE on your whole team!")

    # Irelia: heal when an ally (enemy-side ally) dies — handled via death tracking
    # Tryndamere undying decrement & Mordekaiser conversion handled in main loop.


def _team_hp(units: list[CombatUnit]) -> tuple[int, int]:
    cur = sum(max(0, u.hp) for u in units)
    mx = sum(u.hp_max for u in units)
    return cur, mx


def run_battle(
    player_units: list[CombatUnit],
    enemy_units: list[CombatUnit],
) -> BattleResult:
    result, _rounds = run_battle_with_rounds(player_units, enemy_units, seed=None)
    return result


def run_battle_with_rounds(
    player_units: list[CombatUnit],
    enemy_units: list[CombatUnit],
    seed: int | None = None,
) -> tuple[BattleResult, list[dict]]:
    if seed is not None:
        random.seed(seed)

    log: list[str] = []
    round_snapshots: list[dict] = []
    all_units = player_units + enemy_units
    rounds = 0

    def _snapshot(rnd: int, round_log_start: int) -> None:
        p_cur, p_max = _team_hp(player_units)
        e_cur, e_max = _team_hp(enemy_units)
        events = [l.strip() for l in log[round_log_start:] if l.strip()]

        def _unit_state(u: CombatUnit) -> dict:
            return {
                "name": u.name,
                "rank": getattr(u, "rank", "F") or "F",
                "level": getattr(u, "level", 1) or 1,
                "hp": max(0, u.hp),
                "hp_max": u.hp_max,
                "mana": u.mana,
                "status_effects": [type(e).__name__ for e in u.status_effects],
            }

        round_snapshots.append({
            "round": rnd,
            "events": events,
            "player_units": [_unit_state(u) for u in player_units],
            "enemy_units": [_unit_state(u) for u in enemy_units],
            "player_hp": p_cur,
            "player_hp_max": p_max,
            "enemy_hp": e_cur,
            "enemy_hp_max": e_max,
            "mana_states": {u.name: u.mana for u in all_units if u.is_alive},
            "alive_players": sum(1 for u in player_units if u.is_alive),
            "alive_enemies": sum(1 for u in enemy_units if u.is_alive),
        })

    for rnd in range(1, MAX_ROUNDS + 1):
        rounds = rnd
        round_log_start = len(log)
        alive_players = [u for u in player_units if u.is_alive]
        alive_enemies = [u for u in enemy_units if u.is_alive]

        if not alive_players or not alive_enemies:
            break

        # Detect teams that cannot damage each other (invincible heal loops)
        if _detect_stalemate(alive_players, alive_enemies, rnd):
            log.append(f"[Round {rnd}] Stalemate detected — battle ends in DRAW.")
            _snapshot(rnd, round_log_start)
            return BattleResult(
                winner=-1, rounds=rnd, log=log,
                player_survived=[u.unit_id for u in alive_players],
                enemy_survived=[u.unit_id for u in alive_enemies],
            ), round_snapshots

        log.append(f"\n=== Round {rnd} ===")

        # Boss mechanics (may spawn additional enemies)
        new_adds = _apply_boss_mechanics(enemy_units, rnd, log)
        if new_adds:
            enemy_units.extend(new_adds)
            all_units.extend(new_adds)
            alive_enemies = [u for u in enemy_units if u.is_alive]

        # Dungeon boss round-start passives
        _apply_round_start_passives(player_units, enemy_units, rnd, log)
        alive_players = [u for u in player_units if u.is_alive]
        alive_enemies = [u for u in enemy_units if u.is_alive]

        # Track HP before round for Irelia (heal when ally dies)
        _hp_before_round = {id(u): u.hp for u in enemy_units}

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
                log.append(f"  ☠️ {unit.name} has fallen to poison.")
                continue

            # Stun check
            if unit.has_effect(Stun):
                log.append(f"  ⚡ {unit.name} is stunned — skipping turn.")
                unit.tick_effects_end()
                continue

            # Snapshot enemy HP for reflect mechanic and contribution tracking.
            reflect_bosses = [b for b in enemies_of_unit if getattr(b, "mechanic", "") == "reflect"]
            hp_before = {id(b): b.hp for b in reflect_bosses}

            # Snapshot HP of dodging units (yasuo_passive) so a dodge negates damage.
            dodge_units = [b for b in enemies_of_unit if getattr(b, "dodge_chance", 0.0) > 0]
            dodge_hp_before = {id(b): b.hp for b in dodge_units}

            # Snapshot all enemy HPs before action for damage_dealt tracking.
            _enemy_hp_before = {id(e): e.hp for e in enemies_of_unit}
            # Snapshot own HP for damage_taken tracking.
            _self_hp_before = unit.hp

            # Choose skill
            silenced = unit.has_effect(Silence)
            _used_skill = False
            if unit.mana >= MANA_ULTIMATE_THRESHOLD and not silenced and unit.ultimate_fn:
                log.append(f"  💫 {unit.name} casts ULTIMATE!")
                skill_log = _invoke_skill(unit.ultimate_fn, unit, enemies_of_unit, allies_of_unit)
                unit.mana = 0
                _used_skill = True
            elif unit.basic_fn:
                skill_log = _invoke_skill(unit.basic_fn, unit, enemies_of_unit, allies_of_unit)
                _used_skill = True
            else:
                # Fallback: simple auto-attack
                t = random.choice(enemies_of_unit)
                dmg = max(1, int(unit.atk * 0.8))
                t.hp = max(0, t.hp - dmg)
                skill_log = [f"  🗡️ {unit.name} struck {t.name} for {dmg:,} damage."]
                unit.mana = min(MANA_MAX, unit.mana + 20)

            log.extend(skill_log)

            # Sheen: after using a skill, deal 150% ATK as a bonus hit
            if _used_skill and unit.has_sheen:
                alive_now = [u for u in enemies_of_unit if u.is_alive]
                if alive_now:
                    sheen_target = alive_now[0]
                    sheen_dmg = max(1, int(unit.atk * 1.5))
                    sheen_target.hp = max(0, sheen_target.hp - sheen_dmg)
                    log.append(f"  ⚡ {unit.name}'s Sheen empowers a bonus strike on {sheen_target.name} for {sheen_dmg:,}!")

            # --- Attack Speed passive: extra hit when attack_speed >= 1.15 ---
            if getattr(unit, "attack_speed", 1.0) >= 1.15 and unit.is_alive:
                alive_now = [u for u in enemies_of_unit if u.is_alive]
                if alive_now:
                    asp_target = random.choice(alive_now)
                    asp_dmg = max(1, int(unit.atk * 0.6))
                    asp_target.hp = max(0, asp_target.hp - asp_dmg)
                    log.append(f"  ⚡ {unit.name} attacks again (Attack Speed) — {asp_dmg:,} dmg to {asp_target.name}!")

            # Attribute contribution stats.
            for e in enemies_of_unit:
                unit.damage_dealt += max(0, _enemy_hp_before.get(id(e), e.hp) - e.hp)
            unit.damage_taken += max(0, _self_hp_before - unit.hp)

            # Dodge mechanic (yasuo_passive): roll per dodging unit; on success
            # restore the HP it lost this turn (damage negated).
            for db in dodge_units:
                lost = dodge_hp_before[id(db)] - db.hp
                if lost > 0 and random.random() < (db.dodge_chance / 100.0):
                    db.hp = dodge_hp_before[id(db)]
                    log.append(f"  {db.name} blocks the strike (Way of the Wanderer)!")

            # Reflect mechanic: bosses return a portion of damage taken to the attacker.
            for boss in reflect_bosses:
                dealt = hp_before[id(boss)] - boss.hp
                if dealt > 0 and unit.is_alive:
                    reflected = max(1, int(dealt * _reflect_ratio(boss)))
                    unit.hp = max(0, unit.hp - reflected)
                    log.append(f"  {boss.name} reflects {reflected} damage back to {unit.name}!")

            # Item reflect (Thornmail): any enemy with reflect_damage_pct returns damage.
            for defender in enemies_of_unit:
                rpct = getattr(defender, "reflect_damage_pct", 0.0)
                if rpct > 0:
                    dmg_dealt_to_def = max(0, _enemy_hp_before.get(id(defender), defender.hp) - defender.hp)
                    if dmg_dealt_to_def > 0 and unit.is_alive:
                        reflected = max(1, int(dmg_dealt_to_def * rpct))
                        unit.hp = max(0, unit.hp - reflected)
                        log.append(f"  🌿 {defender.name}'s Thornmail reflects {reflected} dmg to {unit.name}!")

            # Liandry's Anguish: after ability use, apply % max HP burn to hit targets
            if _used_skill and getattr(unit, "liandry_burn", False):
                for t in [e for e in enemies_of_unit if e.is_alive]:
                    burn_dmg = max(1, int(t.hp_max * 0.04))
                    t.hp = max(0, t.hp - burn_dmg)
                    log.append(f"  🔥 {unit.name}'s Liandry's burns {t.name} for {burn_dmg:,}!")

            # Banshee's Veil: block one magic skill per battle (toggle on first magic hit received)
            # Note: handled passively in skill_factory via _apply_damage; we mark the unit here.
            # The blocking itself is in _apply_damage_with_banshee called from skill resolution.

            # Sterak's Gage: grant shield when HP drops below 30% for first time
            if unit.has_sterak and not unit.sterak_triggered:
                if unit.hp_max > 0 and unit.hp <= int(unit.hp_max * 0.30) and unit.is_alive:
                    shield_amt = int(unit.hp_max * 0.75)
                    from engine.status_effects import Shield
                    unit.status_effects.append(Shield(absorb=shield_amt, duration=3))
                    unit.sterak_triggered = True
                    log.append(f"  🛡️ {unit.name}'s Sterak's Gage activates — {shield_amt:,} HP shield!")

            # Guardian Angel: revive at 50% HP on lethal hit (checked post-action)
            if getattr(unit, "guardian_angel_ready", False) and unit.hp <= 0:
                unit.hp = int(unit.hp_max * 0.50)
                unit.guardian_angel_ready = False
                log.append(f"  👼 {unit.name}'s Guardian Angel revives them at {unit.hp:,} HP!")

            # End-of-turn effects
            log.extend(unit.tick_effects_end())

            # Death announcements
            for u in enemy_units + player_units:
                if u.hp == 0 and u in enemies_of_unit + allies_of_unit:
                    pass  # handled in next-round check

        # Sunfire Aegis: at round end, units with sunfire_burn deal aura damage to all enemies
        for u in alive_players + alive_enemies:
            if getattr(u, "sunfire_burn", False) and u.is_alive:
                foes = [x for x in (alive_enemies if u.team == 0 else alive_players) if x.is_alive]
                for foe in foes:
                    sfb = max(1, int(u.hp_max * 0.02))
                    foe.hp = max(0, foe.hp - sfb)
                log.append(f"  🔥 {u.name}'s Sunfire Aegis burns nearby enemies for {sfb:,} each!")

        # Warmog's Armor: regenerate 15% of missing HP each round
        for u in alive_players + alive_enemies:
            if getattr(u, "warmog_regen", False) and u.is_alive and u.hp < u.hp_max:
                regen = max(1, int((u.hp_max - u.hp) * 0.15))
                u.hp = min(u.hp_max, u.hp + regen)
                log.append(f"  💚 {u.name}'s Warmog's Armor regenerates {regen:,} HP.")

        # Dungeon boss round-end passives (swain drain, gangplank barrage)
        _apply_round_end_passives(player_units, enemy_units, rnd, log)

        # Tryndamere undying rage: survive at 1 HP for a couple rounds.
        for boss in _dungeon_bosses(enemy_units):
            if boss.mechanic == "tryndamere_passive":
                if boss.hp <= 0 and getattr(boss, "undying", False):
                    boss.hp = 1
                    boss.undying = False
                    boss.undying_rounds = 2
                    log.append(f"  {boss.name} refuses to die — UNDYING RAGE!")
                elif boss.undying_rounds > 0:
                    boss.undying_rounds -= 1
                    if boss.undying_rounds <= 0:
                        boss.hp = 0
                        log.append(f"  {boss.name}'s rage finally fades.")
                    else:
                        boss.hp = max(1, boss.hp)

        # Irelia: heal 20% max HP when an (enemy-side) ally dies this round.
        irelia = [b for b in _dungeon_bosses(enemy_units) if b.mechanic == "irelia_passive"]
        if irelia:
            for ally in enemy_units:
                if ally is irelia[0]:
                    continue
                if _hp_before_round.get(id(ally), 0) > 0 and ally.hp <= 0:
                    boss = irelia[0]
                    if boss.is_alive:
                        heal = int(boss.hp_max * 0.20)
                        boss.hp = min(boss.hp_max, boss.hp + heal)
                        log.append(f"  {boss.name} heals {heal:,} HP avenging {ally.name} (Bladesurge)!")

        # Mordekaiser: defeated player champions fight for the boss.
        morde = [b for b in _dungeon_bosses(enemy_units) if b.mechanic == "mordekaiser_passive"]
        if morde and morde[0].is_alive:
            for pu in player_units:
                if pu.hp <= 0 and not getattr(pu, "converted", False) and pu.team == 0:
                    pu.converted = True
                    pu.team = 1
                    pu.hp = int(pu.hp_max * 0.5)
                    pu.status_effects = []
                    enemy_units.append(pu)
                    player_units.remove(pu)
                    log.append(f"  {morde[0].name} raises {pu.name} from death (Realm of Death)!")

        # Post-round check
        alive_players = [u for u in player_units if u.is_alive]
        alive_enemies = [u for u in enemy_units if u.is_alive]
        for dead in [u for u in all_units if not u.is_alive]:
            log.append(f"  💀 {dead.name} has been defeated.")

        _snapshot(rnd, round_log_start)

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

    contributions = {
        u.unit_id: {"damage_dealt": u.damage_dealt, "damage_taken": u.damage_taken}
        for u in player_units
    }
    return BattleResult(
        winner=winner,
        rounds=rounds,
        log=log,
        player_survived=[u.unit_id for u in alive_players],
        enemy_survived=[u.unit_id for u in alive_enemies],
        contributions=contributions,
    ), round_snapshots


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

    from config.game_config import MOB_RANK_BY_ZONE, CHAMPION_GROWTH_STATS

    zone_cfg = HUNT_ZONES[zone]
    rank = MOB_RANK_BY_ZONE.get(zone, "F")
    base = CHAMPION_BASE_STATS[rank]
    growth = CHAMPION_GROWTH_STATS[rank]

    enemies = []
    for i in range(mob_count):
        champ_name = random.choice(ALL_CHAMPION_NAMES)
        skills = CHAMPION_SKILLS.get(champ_name, {})
        level = random.randint(1, 10)
        hp = int(base["hp"] + growth["hp"] * (level - 1))
        atk = (base["atk"] + growth["atk"] * (level - 1)) * 0.8
        dfn = (base["def"] + growth["def"] * (level - 1)) * 0.8
        unit = CombatUnit(
            unit_id=f"mob_{i}",
            name=f"Mob {champ_name}",
            rank=rank,
            level=level,
            position=min(i + 1, 5),
            team=1,
            hp=hp,
            hp_max=hp,
            atk=atk,
            def_stat=dfn,
            spd=base["spd"],
            basic_fn=skills.get("basic"),
            ultimate_fn=skills.get("ultimate"),
        )
        enemies.append(unit)
    return enemies


def generate_boss_unit_for_zone(zone: str) -> CombatUnit:
    from config.game_config import (
        HUNT_ZONES, CHAMPION_BASE_STATS, CHAMPION_GROWTH_STATS, BOSS_MECHANICS,
    )
    zone_cfg = HUNT_ZONES[zone]
    rank = zone_cfg.get("boss_rank", "D")
    level = zone_cfg.get("boss_level", 10)
    mult = zone_cfg.get("boss_level_mult", 1.0)

    base = CHAMPION_BASE_STATS[rank]
    growth = CHAMPION_GROWTH_STATS[rank]

    hp = int((base["hp"] + growth["hp"] * (level - 1)) * mult)
    atk = int((base["atk"] + growth["atk"] * (level - 1)) * mult)
    defense = int((base["def"] + growth["def"] * (level - 1)) * mult)
    spd = base["spd"]

    mech_cfg = BOSS_MECHANICS.get(zone, {})
    boss_cfg = {
        "name": zone_cfg["boss_name"],
        "rank": rank,
        "level": level,
        "hp": hp,
        "atk": atk,
        "def": defense,
        "spd": spd,
        "is_boss": True,
        "mechanic": mech_cfg.get("mechanic", ""),
    }
    return build_boss_unit(boss_cfg, position=1, team=1)
