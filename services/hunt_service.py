"""
Hunt service: resolve auto-combat against mobs/bosses and distribute loot.
"""
from __future__ import annotations
import random
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session, get_motor_client

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

    # Determine elite encounter (only for non-boss waves)
    is_elite = (not boss_spawned) and random.random() < zone_cfg["elite_chance"]
    if is_elite:
        from config.game_config import ELITE_MOB_STAT_MULTIPLIER
        for e in enemy_units:
            e.hp = int(e.hp * ELITE_MOB_STAT_MULTIPLIER)
            e.hp_max = int(e.hp_max * ELITE_MOB_STAT_MULTIPLIER)
            e.atk = e.atk * ELITE_MOB_STAT_MULTIPLIER
            e.name = f"Elite {e.name}"

    if boss_spawned:
        boss = generate_boss_unit_for_zone(zone_key)
        enemy_units = [boss]  # Boss fight replaces mob wave

    # Run battle
    result: BattleResult = run_battle(player_units, enemy_units)

    # Determine drop table
    is_boss = boss_spawned

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


async def start_hunt(
    player_id: str,
    zone_key: str,
    session: AsyncIOMotorClientSession,
    discord_channel=None,
) -> Any:
    """Hunt entrypoint with AniGame-style visual presentation.

    When ``discord_channel`` is provided, the battle is simulated, stored as a
    BattleSession, and revealed round-by-round by editing a single message.
    When ``discord_channel`` is None (tests), falls back to ``run_hunt`` which
    returns the legacy result dict.
    """
    if discord_channel is None:
        return await run_hunt(player_id, zone_key, session)

    zone_cfg = HUNT_ZONES.get(zone_key)
    if zone_cfg is None:
        raise HuntError(f"Unknown zone '{zone_key}'. Valid: {', '.join(HUNT_ZONES)}")

    user = await User.find_one(User.discord_id == player_id, session=usable_session(session))
    cost = zone_cfg["stamina_cost"]
    if user.stamina < cost:
        raise HuntError(f"Not enough stamina. Need {cost}, have {user.stamina}.")

    team = await Team.get_or_create(player_id)
    active_slots = [s for s in team.slots if s is not None]
    if not active_slots:
        raise HuntError("Your team has no champions. Use /team add to set up your team.")

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

    user.stamina -= cost
    await user.save(session=usable_session(session))

    min_mob, max_mob = zone_cfg["mob_count"]
    mob_count = random.randint(min_mob, max_mob)
    enemy_units = generate_mob_team(zone_key, min(mob_count, 5))

    boss_spawned = random.random() < zone_cfg["boss_chance"]
    is_elite = (not boss_spawned) and random.random() < zone_cfg["elite_chance"]
    if is_elite:
        from config.game_config import ELITE_MOB_STAT_MULTIPLIER
        for e in enemy_units:
            e.hp = int(e.hp * ELITE_MOB_STAT_MULTIPLIER)
            e.hp_max = int(e.hp_max * ELITE_MOB_STAT_MULTIPLIER)
            e.atk = e.atk * ELITE_MOB_STAT_MULTIPLIER
            e.name = f"Elite {e.name}"

    if boss_spawned:
        boss = generate_boss_unit_for_zone(zone_key)
        enemy_units = [boss]

    battle_type = "boss" if boss_spawned else ("elite" if is_elite else "hunt")
    enemy_name = enemy_units[0].name if enemy_units else "Enemy"
    player_team_names = [u.name for u in player_units]

    from services.battle_presentation_service import (
        simulate_and_store, start_presentation, advance_and_display,
    )

    bs = await simulate_and_store(
        owner_id=player_id,
        zone=zone_cfg["name"],
        player_units=player_units,
        enemy_units=enemy_units,
        battle_type=battle_type,
        entry_cost={"stamina": cost},
        session=session,
    )

    is_boss = boss_spawned
    drop_table = BOSS_DROPS if is_boss else (ELITE_MOB_DROPS if is_elite else NORMAL_MOB_DROPS)
    gold_multiplier = zone_cfg["gold_multiplier"]

    async def _reward_fn():
        client = get_motor_client()
        if client is None:
            return await _roll_drops(player_id, drop_table, gold_multiplier, None)
        async with await client.start_session() as s:
            async with s.start_transaction():
                return await _roll_drops(player_id, drop_table, gold_multiplier, s)

    message = await start_presentation(bs, discord_channel, player_team_names, enemy_name)
    await advance_and_display(str(bs.id), message, reward_fn=_reward_fn)
    return bs


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

        elif drop_key in ("champion_F", "champion", "champion_FE"):
            ranks = cfg.get("ranks")
            if ranks:
                rank = random.choice(ranks)
            elif drop_key == "champion_FE":
                rank = random.choice(["F", "E"])
            else:
                rank = "F"
            name = random.choice(ALL_CHAMPION_NAMES)
            c = await grant_champion(owner_id, name, rank, session)
            rewards["champions"].append({"name": name, "rank": rank, "id": str(c.id)})

        elif drop_key in ("item_F", "item", "item_FE"):
            ranks = cfg.get("ranks")
            if ranks:
                rank = random.choice(ranks)
            elif drop_key == "item_F":
                rank = "F"
            else:
                rank = random.choice(["F", "E"])
            name, stat, passive = random.choice(ITEM_POOL)
            itm = await grant_item(owner_id, name, rank, stat, passive, session)
            rewards["items"].append({"name": name, "rank": rank, "id": str(itm.id)})

        elif drop_key in ("enhance_mat", "reroll_mat"):
            amount = random.randint(cfg.get("min", 1), cfg.get("max", 1))
            rewards[drop_key] = rewards.get(drop_key, 0) + amount

        elif drop_key == "seal":
            user.blacksmith_seals = getattr(user, "blacksmith_seals", 0) + 1
            rewards["seals"] += 1

        elif drop_key == "summon_token":
            amount = random.randint(cfg["min"], cfg["max"])
            user.summon_tokens += amount
            rewards["summon_tokens"] += amount

    await user.save(session=usable_session(session))
    return rewards
