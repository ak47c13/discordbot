"""
Hunt service: resolve auto-combat against mobs/bosses and distribute loot.
"""
from __future__ import annotations
import random
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.team import Team
from models.audit_log import AuditLog
from engine.combat import (
    build_unit_from_champion,
    build_boss_unit,
    generate_mob_team,
    generate_boss_unit_for_zone,
    run_battle,
    BattleResult,
)
from services.champion_service import grant_champion
from services.item_service import grant_item
from config.game_config import (
    HUNT_ZONES,
    NORMAL_MOB_DROPS,
    ELITE_MOB_DROPS,
    BOSS_DROPS,
    RANKS,
)
from engine.skills import ALL_CHAMPION_NAMES


ITEM_POOL = [
    ("Infinity Edge", "atk", "crit_damage_passive"),
    ("Chain Vest",    "def", "armor_passive"),
    ("Ruby Crystal",  "hp",  "fortify_passive"),
    ("Recurve Bow",   "atk", "attack_speed_passive"),
    ("Cloak",         "def", "dodge_passive"),
    ("Giant's Belt",  "hp",  "hp_boost_passive"),
    ("B.F. Sword",    "atk", "atk_boost_passive"),
]


class HuntError(Exception):
    pass


async def run_hunt(
    owner_id: str,
    zone_key: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    zone_cfg = HUNT_ZONES.get(zone_key)
    if zone_cfg is None:
        raise HuntError(f"Unknown zone '{zone_key}'. Valid: {', '.join(HUNT_ZONES)}")

    # Stamina check
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    cost = zone_cfg["stamina_cost"]
    if user.stamina < cost:
        raise HuntError(f"Not enough stamina. Need {cost}, have {user.stamina}.")

    # Load team
    team = await Team.get_or_create(owner_id)
    active_slots = [s for s in team.slots if s is not None]
    if not active_slots:
        raise HuntError("Your team has no champions. Use /team add to set up your team.")

    # Build player units
    player_units = []
    for idx, champ_id in enumerate(active_slots):
        champ_doc = await ChampionInstance.get(champ_id)
        if champ_doc is None:
            continue
        item_docs = await ItemInstance.find(
            ItemInstance.equipped_to == str(champ_doc.id)
        ).to_list()
        unit = build_unit_from_champion(champ_doc, item_docs, position=idx + 1, team=0)
        player_units.append(unit)

    if not player_units:
        raise HuntError("No valid champions in team.")

    # Consume stamina
    user.stamina -= cost
    await user.save(session=usable_session(session))

    # Generate enemies
    min_mob, max_mob = zone_cfg["mob_count"]
    mob_count = random.randint(min_mob, max_mob)
    enemy_units = generate_mob_team(zone_key, min(mob_count, 5))

    # Determine if boss spawns this run
    boss_spawned = random.random() < zone_cfg["boss_chance"]
    if boss_spawned:
        boss = generate_boss_unit_for_zone(zone_key)
        enemy_units = [boss]  # Boss fight replaces mob wave

    # Run battle
    result: BattleResult = run_battle(player_units, enemy_units)

    # Determine drop table
    is_boss = boss_spawned
    is_elite = (not is_boss) and random.random() < zone_cfg["elite_chance"]

    rewards: dict[str, Any] = {"gold": 0, "champions": [], "items": [], "seals": 0}

    if result.winner == 0:   # player wins
        drop_table = BOSS_DROPS if is_boss else (ELITE_MOB_DROPS if is_elite else NORMAL_MOB_DROPS)
        rewards = await _roll_drops(owner_id, drop_table, zone_cfg["gold_multiplier"], session)

    return {
        "zone": zone_cfg["name"],
        "battle_result": result,
        "is_boss": is_boss,
        "is_elite": is_elite,
        "rewards": rewards,
        "battle_log": result.log,
    }


async def _roll_drops(
    owner_id: str,
    drop_table: dict,
    gold_multiplier: float,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    rewards: dict[str, Any] = {"gold": 0, "champions": [], "items": [], "seals": 0, "summon_tokens": 0}

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))

    for drop_key, cfg in drop_table.items():
        if random.random() > cfg["chance"]:
            continue

        if drop_key == "gold":
            amount = int(random.randint(cfg["min"], cfg["max"]) * gold_multiplier)
            user.gold += amount
            rewards["gold"] += amount

        elif drop_key in ("champion_F", "champion"):
            rank = "F"
            name = random.choice(ALL_CHAMPION_NAMES)
            c = await grant_champion(owner_id, name, rank, session)
            rewards["champions"].append({"name": name, "rank": rank, "id": str(c.id)})

        elif drop_key == "champion_FE":
            rank = random.choice(["F", "E"])
            name = random.choice(ALL_CHAMPION_NAMES)
            c = await grant_champion(owner_id, name, rank, session)
            rewards["champions"].append({"name": name, "rank": rank, "id": str(c.id)})

        elif drop_key in ("item_F", "item", "item_FE"):
            rank = "F" if drop_key == "item_F" else random.choice(["F", "E"])
            name, stat, passive = random.choice(ITEM_POOL)
            itm = await grant_item(owner_id, name, rank, stat, passive, session)
            rewards["items"].append({"name": name, "rank": rank, "id": str(itm.id)})

        elif drop_key == "seal":
            user.blacksmith_seals = getattr(user, "blacksmith_seals", 0) + 1
            rewards["seals"] += 1

        elif drop_key == "summon_token":
            amount = random.randint(cfg["min"], cfg["max"])
            user.summon_tokens += amount
            rewards["summon_tokens"] += amount

    await user.save(session=usable_session(session))
    return rewards
