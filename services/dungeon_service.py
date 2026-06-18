"""
Dungeon service — floor-by-floor progression system.
Players fight through floors, saving progress at checkpoints.
"""
from __future__ import annotations
import random
from datetime import datetime, timezone
from typing import Any, Optional

from beanie import PydanticObjectId

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.dungeon import Dungeon, DungeonFloor, DungeonProgress, DungeonRun
from engine.combat import (
    CombatUnit,
    build_unit_from_champion,
    run_battle_with_rounds,
    BattleResult,
)
from engine.skills import CHAMPION_SKILLS
from config.game_config import (
    CHAMPION_BASE_STATS,
    CHAMPION_GROWTH_STATS,
    CHAMPION_MAX_LEVEL,
    DUNGEON_HP_SCALE_PER_FLOOR,
    DUNGEON_ATK_SCALE_PER_FLOOR,
    DUNGEON_DEF_SCALE_PER_FLOOR,
    DUNGEON_BOSS_HP_MULT,
    DUNGEON_BOSS_ATK_MULT,
    DUNGEON_FLOOR_GOLD_BASE,
    DUNGEON_FLOOR_GOLD_PER_FLOOR,
    DUNGEON_FLOOR_XP_BASE,
    DUNGEON_FLOOR_XP_PER_FLOOR,
    DUNGEON_RUNE_SHARD_CHANCE,
    DUNGEON_RUNE_FRAGMENT_CHANCE,
    DUNGEON_FIRST_CLEAR,
    DUNGEON_DAILY_CLEAR,
    DUNGEON_STAMINA_COST,
    DUNGEON_BOSS_RETRY_COST,
    champion_xp_threshold,
)
from utils.db_session import usable_session


class DungeonError(Exception):
    pass


# Map order defines global difficulty progression.
# map_multiplier = 1.0 + (map_index * MAP_SCALE_PER_MAP)
# So Map 2 Floor 1 is always slightly stronger than Map 1 Floor max.
_MAP_ORDER = [
    "map-1-demacia",
    "map-2-noxus",
    "map-3-freljord",
    "map-4-ionia",
    "map-5-piltover",
    "map-6-bilgewater",
    "map-7-shadow-isles",
    "map-8-void",
]
_MAP_SCALE_PER_MAP = 0.30  # each map adds 30% base stat multiplier on top of floor scaling


def _map_multiplier(dungeon_slug: str) -> float:
    """Return a global stat multiplier based on which map this dungeon is."""
    idx = _MAP_ORDER.index(dungeon_slug) if dungeon_slug in _MAP_ORDER else 0
    return 1.0 + idx * _MAP_SCALE_PER_MAP


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------
async def get_all_progress(owner_id: str, session=None) -> list[DungeonProgress]:
    return await DungeonProgress.find(
        DungeonProgress.owner_id == owner_id,
        session=usable_session(session),
    ).to_list()


async def get_or_create_progress(owner_id: str, dungeon_slug: str, session=None) -> DungeonProgress:
    prog = await DungeonProgress.find_one(
        DungeonProgress.owner_id == owner_id,
        DungeonProgress.dungeon_slug == dungeon_slug,
        session=usable_session(session),
    )
    if prog is None:
        prog = DungeonProgress(owner_id=owner_id, dungeon_slug=dungeon_slug)
        await prog.insert(session=usable_session(session))
    return prog


async def _completed_dungeons(owner_id: str, session=None) -> list[DungeonProgress]:
    return await DungeonProgress.find(
        DungeonProgress.owner_id == owner_id,
        session=usable_session(session),
    ).to_list()


async def can_enter_dungeon(owner_id: str, dungeon_slug: str, session=None) -> tuple[bool, str]:
    dungeon = await Dungeon.find_one(Dungeon.slug == dungeon_slug, session=usable_session(session))
    if dungeon is None:
        return False, "That dungeon does not exist."
    if not dungeon.is_active:
        return False, "That dungeon is not currently available."

    # Unlock requirement
    ok, reason = await _check_unlock(owner_id, dungeon, session)
    if not ok:
        return False, reason

    # Stamina
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user is None:
        return False, "You are not registered."
    if user.stamina < DUNGEON_STAMINA_COST:
        return False, f"Not enough stamina. Need {DUNGEON_STAMINA_COST}, have {user.stamina}."

    return True, ""


async def _check_unlock(owner_id: str, dungeon: Dungeon, session=None) -> tuple[bool, str]:
    req = dungeon.unlock_req
    if not req:
        return True, ""

    progresses = await _completed_dungeons(owner_id, session)
    completed_slugs = {p.dungeon_slug for p in progresses if p.completions > 0}

    if req in completed_slugs:
        return True, ""
    d = await Dungeon.find_one(Dungeon.slug == req, session=usable_session(session))
    name = d.name if d else req
    return False, f"Locked. Clear {name} first."


# ---------------------------------------------------------------------------
# Enemy construction
# ---------------------------------------------------------------------------
def _build_enemy_unit(enemy: dict, floor_num: int, boss_floor: bool, position: int, dungeon_slug: str = "") -> CombatUnit:
    rank = enemy.get("rank", "F")
    base = CHAMPION_BASE_STATS.get(rank, CHAMPION_BASE_STATS["F"])
    growth = CHAMPION_GROWTH_STATS.get(rank, CHAMPION_GROWTH_STATS["F"])
    level = enemy.get("level", floor_num)

    base_hp = base["hp"] + growth["hp"] * (level - 1)
    base_atk = base["atk"] + growth["atk"] * (level - 1)
    base_def = base["def"] + growth["def"] * (level - 1)
    base_spd = base["spd"]

    map_mult = _map_multiplier(dungeon_slug)
    hp = base_hp * (1 + (floor_num - 1) * DUNGEON_HP_SCALE_PER_FLOOR) * enemy.get("hp_mult", 1.0) * map_mult
    atk = base_atk * (1 + (floor_num - 1) * DUNGEON_ATK_SCALE_PER_FLOOR) * enemy.get("atk_mult", 1.0) * map_mult
    defense = base_def * (1 + (floor_num - 1) * DUNGEON_DEF_SCALE_PER_FLOOR) * enemy.get("def_mult", 1.0) * map_mult
    spd = base_spd + (floor_num // 5)

    if boss_floor:
        hp *= DUNGEON_BOSS_HP_MULT
        atk *= DUNGEON_BOSS_ATK_MULT

    skills = CHAMPION_SKILLS.get(enemy["name"], {})
    unit = CombatUnit(
        unit_id=f"dmob_{position}_{enemy['name']}",
        name=enemy["name"],
        rank=rank,
        level=level,
        position=position,
        team=1,
        hp=int(hp),
        hp_max=int(hp),
        atk=atk,
        def_stat=defense,
        spd=spd,
        basic_fn=skills.get("basic"),
        ultimate_fn=skills.get("ultimate"),
    )
    return unit


def _apply_boss_passive(boss: CombatUnit, passive: str) -> None:
    """Tag the boss unit with its passive for the battle engine to handle."""
    boss.mechanic = passive
    boss.is_boss = True

    if passive == "yasuo_passive":
        boss.dodge_chance = 50.0
    elif passive == "tryndamere_passive":
        boss.undying = True
    elif passive == "chogath_passive":
        boss.feast_stacks = 0


def _apply_hazard_to_enemies(enemies: list[CombatUnit], hazard: str) -> None:
    if hazard == "berserker":
        for e in enemies:
            e.atk *= 1.30
            e.def_stat *= 0.80
    elif hazard == "armored":
        for e in enemies:
            e.def_stat *= 1.40
    elif hazard == "speed_seal":
        for e in enemies:
            e.spd = 50


def _apply_hazard_to_players(players: list[CombatUnit], hazard: str) -> None:
    if hazard == "wound":
        for p in players:
            p.hp = max(1, int(p.hp_max * 0.70))
    elif hazard == "speed_seal":
        for p in players:
            p.spd = 50


# ---------------------------------------------------------------------------
# Floor preview
# ---------------------------------------------------------------------------
async def get_floor_preview(dungeon_slug: str, floor_num: int, session=None) -> dict:
    floor = await DungeonFloor.find_one(
        DungeonFloor.dungeon_slug == dungeon_slug,
        DungeonFloor.floor_num == floor_num,
        session=usable_session(session),
    )
    if floor is None:
        raise DungeonError(f"Floor {floor_num} not found for {dungeon_slug}.")
    enemy_units = [
        _build_enemy_unit(e, floor_num, floor.boss_floor, i + 1, dungeon_slug)
        for i, e in enumerate(floor.enemies)
    ]
    return {
        "floor_num": floor_num,
        "boss_floor": floor.boss_floor,
        "boss_passive": floor.boss_passive,
        "hazard": floor.hazard,
        "checkpoint_floor": floor.checkpoint_floor,
        "reward_gold": floor.reward_gold,
        "reward_xp": floor.reward_xp,
        "enemies": [
            {"name": u.name, "rank": u.rank, "level": u.level,
             "hp": u.hp_max, "atk": int(u.atk), "def": int(u.def_stat)}
            for u in enemy_units
        ],
    }


# ---------------------------------------------------------------------------
# Champion XP / leveling
# ---------------------------------------------------------------------------
async def _award_champion_xp(champ_ids: list[str], xp: int, session=None) -> list[dict]:
    """Grant XP to each champion, leveling them up when thresholds are crossed."""
    leveled: list[dict] = []
    for cid in champ_ids:
        try:
            champ = await ChampionInstance.get(PydanticObjectId(cid), session=usable_session(session))
        except Exception:
            champ = None
        if champ is None:
            continue
        max_lvl = CHAMPION_MAX_LEVEL.get(champ.rank, 20)
        if champ.level >= max_lvl:
            continue
        champ.exp += xp
        gained = 0
        while champ.level < max_lvl and champ.exp >= champion_xp_threshold(champ.level):
            champ.exp -= champion_xp_threshold(champ.level)
            champ.level += 1
            gained += 1
        if champ.level >= max_lvl:
            champ.exp = 0
        await champ.save(session=usable_session(session))
        if gained:
            leveled.append({"name": champ.name, "level": champ.level, "gained": gained})
    return leveled


# ---------------------------------------------------------------------------
# Build player units
# ---------------------------------------------------------------------------
async def _build_player_units(champion_ids: list[str], session=None, active_skill_key: str = "q", rune_page=None) -> list[CombatUnit]:
    units: list[CombatUnit] = []
    for idx, cid in enumerate(champion_ids):
        try:
            champ = await ChampionInstance.get(PydanticObjectId(cid), session=usable_session(session))
        except Exception:
            champ = None
        if champ is None:
            continue
        item_docs = await ItemInstance.find(
            ItemInstance.equipped_to == str(champ.id),
            session=usable_session(session),
        ).to_list()
        units.append(build_unit_from_champion(champ, item_docs, position=idx + 1, team=0, active_skill_key=active_skill_key, rune_page=rune_page))
    return units


async def build_floor_units(
    owner_id: str,
    dungeon_slug: str,
    floor_num: int,
    champion_ids: list[str],
    session=None,
) -> dict:
    """Build player + enemy units for a floor with hazards/passives applied.

    Used by the command layer to feed the visual battle presentation. Returns a
    dict with player_units, enemy_units, and floor metadata (no DB writes).
    """
    dungeon = await Dungeon.find_one(Dungeon.slug == dungeon_slug, session=usable_session(session))
    if dungeon is None:
        raise DungeonError("Dungeon not found.")
    floor = await DungeonFloor.find_one(
        DungeonFloor.dungeon_slug == dungeon_slug,
        DungeonFloor.floor_num == floor_num,
        session=usable_session(session),
    )
    if floor is None:
        raise DungeonError(f"Floor {floor_num} not found.")

    _skill_key = "q"
    _rune_page = None
    _usr = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if _usr:
        _skill_key = getattr(_usr, "active_skill", "q") or "q"
        _rune_page = getattr(_usr, "rune_page", None)

    player_units = await _build_player_units(champion_ids, session, active_skill_key=_skill_key, rune_page=_rune_page)
    if not player_units:
        raise DungeonError("No valid champions provided for this run.")

    enemy_units = [
        _build_enemy_unit(e, floor_num, floor.boss_floor, i + 1, dungeon_slug)
        for i, e in enumerate(floor.enemies)
    ]
    boss_passive = floor.boss_passive or (dungeon.boss_passive if floor.boss_floor else "")
    if floor.boss_floor and boss_passive and enemy_units:
        _apply_boss_passive(enemy_units[0], boss_passive)

    hazard = floor.hazard
    if hazard:
        _apply_hazard_to_enemies(enemy_units, hazard)
        _apply_hazard_to_players(player_units, hazard)

    return {
        "player_units": player_units,
        "enemy_units": enemy_units,
        "boss_floor": floor.boss_floor,
        "boss_passive": boss_passive,
        "hazard": hazard,
        "checkpoint_floor": floor.checkpoint_floor,
        "total_floors": dungeon.total_floors,
        "dungeon_name": dungeon.name,
    }


async def grant_floor_rewards(
    owner_id: str,
    dungeon_slug: str,
    floor_num: int,
    champion_ids: list[str],
    won: bool,
    seed: int,
    session=None,
) -> dict:
    """Apply stamina cost, progress changes, and rewards for a completed floor.

    Separated from simulation so the command layer can reveal the battle first
    (via the presentation pipeline) and grant rewards only after.
    """
    dungeon = await Dungeon.find_one(Dungeon.slug == dungeon_slug, session=usable_session(session))
    floor = await DungeonFloor.find_one(
        DungeonFloor.dungeon_slug == dungeon_slug,
        DungeonFloor.floor_num == floor_num,
        session=usable_session(session),
    )
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    cost = DUNGEON_BOSS_RETRY_COST if floor.boss_floor else DUNGEON_STAMINA_COST
    user.stamina = max(0, user.stamina - cost)

    prog = await get_or_create_progress(owner_id, dungeon_slug, session)
    prog.last_attempt_at = datetime.now(timezone.utc)

    rewards: dict[str, Any] = {
        "gold": 0, "xp": 0, "rune_shards": 0, "rune_fragments": 0,
        "leveled": [], "bonus": None,
    }
    if won:
        map_mult = _map_multiplier(dungeon_slug)
        gold = int((DUNGEON_FLOOR_GOLD_BASE + floor_num * DUNGEON_FLOOR_GOLD_PER_FLOOR) * map_mult)
        xp = int((DUNGEON_FLOOR_XP_BASE + floor_num * DUNGEON_FLOOR_XP_PER_FLOOR) * map_mult)
        # Rune drop chance scales with map (higher maps = better drop rates)
        rune_shard_chance = min(0.40, DUNGEON_RUNE_SHARD_CHANCE * map_mult)
        rune_fragment_chance = min(0.15, DUNGEON_RUNE_FRAGMENT_CHANCE * map_mult)
        rewards["gold"] = gold
        rewards["xp"] = xp
        user.gold += gold
        rng = random.Random(seed)
        if rng.random() < rune_shard_chance:
            user.rune_shards += 1
            rewards["rune_shards"] = 1
        if rng.random() < rune_fragment_chance:
            user.rune_fragments += 1
            rewards["rune_fragments"] = 1
        rewards["leveled"] = await _award_champion_xp(champion_ids, xp, session)
        if floor_num > prog.highest_floor:
            prog.highest_floor = floor_num
        if floor_num > prog.checkpoint_floor:
            prog.checkpoint_floor = floor_num
        await user.save(session=usable_session(session))
        await prog.save(session=usable_session(session))
        if prog.highest_floor >= dungeon.total_floors:
            comp = await check_dungeon_completion(owner_id, dungeon_slug, session)
            if comp:
                rewards["bonus"] = comp
    else:
        prog.highest_floor = prog.checkpoint_floor
        await user.save(session=usable_session(session))
        await prog.save(session=usable_session(session))

    run = DungeonRun(
        owner_id=owner_id, dungeon_slug=dungeon_slug, floor_num=floor_num,
        team_snapshot=[{"name": c} for c in champion_ids],
        result="win" if won else "loss",
        rewards_given=rewards,
        hazard=floor.hazard,
        boss_passive=floor.boss_passive or (dungeon.boss_passive if floor.boss_floor else ""),
    )
    await run.insert(session=usable_session(session))
    rewards["checkpoint_floor"] = prog.checkpoint_floor
    rewards["next_floor"] = floor_num + 1 if (won and floor_num < dungeon.total_floors) else None
    return rewards


# ---------------------------------------------------------------------------
# Enter a floor
# ---------------------------------------------------------------------------
async def enter_floor(
    owner_id: str,
    dungeon_slug: str,
    floor_num: int,
    champion_ids: list[str],
    session=None,
    seed: Optional[int] = None,
) -> dict:
    dungeon = await Dungeon.find_one(Dungeon.slug == dungeon_slug, session=usable_session(session))
    if dungeon is None:
        raise DungeonError("Dungeon not found.")

    floor = await DungeonFloor.find_one(
        DungeonFloor.dungeon_slug == dungeon_slug,
        DungeonFloor.floor_num == floor_num,
        session=usable_session(session),
    )
    if floor is None:
        raise DungeonError(f"Floor {floor_num} not found.")

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user is None:
        raise DungeonError("You are not registered.")

    cost = DUNGEON_BOSS_RETRY_COST if floor.boss_floor else DUNGEON_STAMINA_COST
    if user.stamina < cost:
        raise DungeonError(f"Not enough stamina. Need {cost}, have {user.stamina}.")

    # Build player units — use user's active skill and rune page
    _active_skill = getattr(user, "active_skill", "q") or "q"
    _rune_pg = getattr(user, "rune_page", None)
    player_units = await _build_player_units(champion_ids, session, active_skill_key=_active_skill, rune_page=_rune_pg)
    if not player_units:
        raise DungeonError("No valid champions provided for this run.")

    # Build enemy units
    enemy_units = [
        _build_enemy_unit(e, floor_num, floor.boss_floor, i + 1, dungeon_slug)
        for i, e in enumerate(floor.enemies)
    ]
    if not enemy_units:
        raise DungeonError("Floor has no enemies configured.")

    # Boss passive
    boss_passive = floor.boss_passive or (dungeon.boss_passive if floor.boss_floor else "")
    if floor.boss_floor and boss_passive:
        _apply_boss_passive(enemy_units[0], boss_passive)

    # Hazards
    hazard = floor.hazard
    if hazard:
        _apply_hazard_to_enemies(enemy_units, hazard)
        _apply_hazard_to_players(player_units, hazard)

    # Deduct stamina
    user.stamina -= cost

    # Run battle
    if seed is None:
        seed = random.randint(0, 2 ** 31)
    result, rounds = run_battle_with_rounds(player_units, enemy_units, seed=seed)
    won = result.winner in (0, -1)  # draw counts as player win (survived time limit)

    damage_dealt = sum(e.hp_max for e in enemy_units) - sum(max(0, e.hp) for e in enemy_units)

    # Progress
    prog = await get_or_create_progress(owner_id, dungeon_slug, session)
    prog.last_attempt_at = datetime.now(timezone.utc)

    rewards: dict[str, Any] = {
        "gold": 0, "xp": 0, "rune_shards": 0, "rune_fragments": 0,
        "leveled": [], "bonus": None,
    }
    completion: Optional[dict] = None

    if won:
        map_mult = _map_multiplier(dungeon_slug)
        gold = int((DUNGEON_FLOOR_GOLD_BASE + floor_num * DUNGEON_FLOOR_GOLD_PER_FLOOR) * map_mult)
        xp = int((DUNGEON_FLOOR_XP_BASE + floor_num * DUNGEON_FLOOR_XP_PER_FLOOR) * map_mult)
        rune_shard_chance = min(0.40, DUNGEON_RUNE_SHARD_CHANCE * map_mult)
        rune_fragment_chance = min(0.15, DUNGEON_RUNE_FRAGMENT_CHANCE * map_mult)
        rewards["gold"] = gold
        rewards["xp"] = xp
        user.gold += gold

        rng = random.Random(seed)
        if rng.random() < rune_shard_chance:
            user.rune_shards += 1
            rewards["rune_shards"] = 1
        if rng.random() < rune_fragment_chance:
            user.rune_fragments += 1
            rewards["rune_fragments"] = 1

        rewards["leveled"] = await _award_champion_xp(champion_ids, xp, session)

        if floor_num > prog.highest_floor:
            prog.highest_floor = floor_num
        if floor_num > prog.checkpoint_floor:
            prog.checkpoint_floor = floor_num

        await user.save(session=usable_session(session))
        await prog.save(session=usable_session(session))

        if prog.highest_floor >= dungeon.total_floors:
            completion = await check_dungeon_completion(owner_id, dungeon_slug, session)
            if completion:
                rewards["bonus"] = completion
    else:
        # Loss: reset position to last checkpoint
        prog.highest_floor = prog.checkpoint_floor
        await user.save(session=usable_session(session))
        await prog.save(session=usable_session(session))

    # Log run
    run = DungeonRun(
        owner_id=owner_id,
        dungeon_slug=dungeon_slug,
        floor_num=floor_num,
        team_snapshot=[{"name": u.name, "rank": u.rank, "level": u.level} for u in player_units],
        result="win" if won else "loss",
        damage_dealt=int(damage_dealt),
        rewards_given=rewards,
        hazard=hazard,
        boss_passive=boss_passive,
    )
    await run.insert(session=usable_session(session))

    next_floor = None
    if won and floor_num < dungeon.total_floors:
        next_floor = floor_num + 1

    return {
        "result": "win" if won else "loss",
        "rewards": rewards,
        "battle_result": result,
        "rounds": rounds,
        "seed": seed,
        "player_units": player_units,
        "enemy_units": enemy_units,
        "next_floor": next_floor,
        "checkpoint_floor": prog.checkpoint_floor,
        "boss_floor": floor.boss_floor,
        "hazard": hazard,
        "boss_passive": boss_passive,
        "total_floors": dungeon.total_floors,
        "completion": completion,
    }


# ---------------------------------------------------------------------------
# Flee
# ---------------------------------------------------------------------------
async def flee_dungeon(owner_id: str, dungeon_slug: str, session=None) -> dict:
    prog = await get_or_create_progress(owner_id, dungeon_slug, session)
    prog.last_attempt_at = datetime.now(timezone.utc)
    await prog.save(session=usable_session(session))
    return {
        "fled": True,
        "checkpoint_floor": prog.checkpoint_floor,
        "highest_floor": prog.highest_floor,
    }


# ---------------------------------------------------------------------------
# Completion bonuses
# ---------------------------------------------------------------------------
async def check_dungeon_completion(owner_id: str, dungeon_slug: str, session=None) -> Optional[dict]:
    dungeon = await Dungeon.find_one(Dungeon.slug == dungeon_slug, session=usable_session(session))
    if dungeon is None:
        return None
    prog = await get_or_create_progress(owner_id, dungeon_slug, session)
    if prog.highest_floor < dungeon.total_floors:
        return None

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    now = datetime.now(timezone.utc)
    granted: dict[str, Any] = {}

    is_first_clear = prog.first_clear_at is None

    if is_first_clear:
        bonus = DUNGEON_FIRST_CLEAR.get(dungeon.total_floors, {})
        if bonus:
            user.gold += bonus.get("gold", 0)
            user.summon_tokens += bonus.get("summon_tokens", 0)
            granted = {"type": "first_clear", **bonus}
        prog.first_clear_at = now
        prog.last_daily_at = now
    else:
        # Daily clear bonus if eligible
        last = prog.last_daily_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        eligible = (last is None) or (last.date() < now.date())
        if eligible:
            bonus = DUNGEON_DAILY_CLEAR.get(dungeon.total_floors, {})
            if bonus:
                user.gold += bonus.get("gold", 0)
                granted = {"type": "daily_clear", **bonus}
            prog.last_daily_at = now

    prog.completions += 1
    await user.save(session=usable_session(session))
    await prog.save(session=usable_session(session))

    return granted or None
