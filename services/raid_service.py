"""
Raid service: queue management, auto-battle, personal loot per player.
Reward idempotency: each player can only claim once per raid.
"""
from __future__ import annotations
import random
from datetime import datetime, timezone
from typing import Any

from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession

from models.raid import RaidQueue
from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from engine.combat import build_unit_from_champion, generate_boss_unit_for_zone, run_battle
from services.champion_service import grant_champion
from services.item_service import grant_item
from config.game_config import RAID_MAX_PLAYERS, RAID_DROPS, HUNT_ZONES
from engine.skills import ALL_CHAMPION_NAMES


ITEM_POOL = [
    ("Infinity Edge", "atk", "crit_damage_passive"),
    ("Chain Vest",    "def", "armor_passive"),
    ("Ruby Crystal",  "hp",  "fortify_passive"),
    ("Recurve Bow",   "atk", "attack_speed_passive"),
    ("Giant's Belt",  "hp",  "hp_boost_passive"),
]


class RaidError(Exception):
    pass


async def create_raid_queue(
    leader_id: str,
    zone_key: str,
    session: AsyncIOMotorClientSession,
) -> RaidQueue:
    if zone_key not in HUNT_ZONES:
        raise RaidError(f"Invalid zone '{zone_key}'.")

    existing = await RaidQueue.find_one(
        RaidQueue.leader_id == leader_id,
        RaidQueue.status == "waiting",
        session=session,
    )
    if existing:
        raise RaidError("You already have an open raid queue.")

    raid = RaidQueue(
        zone=zone_key,
        leader_id=leader_id,
        player_ids=[leader_id],
        status="waiting",
    )
    await raid.insert(session=session)
    return raid


async def join_raid(
    player_id: str,
    raid_id: str,
    champion_id: str,
    session: AsyncIOMotorClientSession,
) -> RaidQueue:
    raid = await RaidQueue.get(PydanticObjectId(raid_id), session=session)
    if raid is None:
        raise RaidError("Raid not found.")
    if raid.status != "waiting":
        raise RaidError("Raid is not accepting players.")
    if player_id in raid.player_ids:
        raise RaidError("You are already in this raid.")
    if len(raid.player_ids) >= RAID_MAX_PLAYERS:
        raise RaidError("Raid is full (5 players max).")

    c = await ChampionInstance.get(PydanticObjectId(champion_id), session=session)
    if c is None or c.owner_id != player_id:
        raise RaidError("Champion not found or not owned by you.")

    raid.player_ids.append(player_id)
    raid.player_champions[player_id] = champion_id
    await raid.save(session=session)
    return raid


async def start_raid(
    leader_id: str,
    raid_id: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    raid = await RaidQueue.get(PydanticObjectId(raid_id), session=session)
    if raid is None:
        raise RaidError("Raid not found.")
    if raid.leader_id != leader_id:
        raise RaidError("Only the raid leader can start.")
    if raid.status != "waiting":
        raise RaidError(f"Raid is already {raid.status}.")

    raid.status = "in_progress"
    raid.started_at = datetime.now(timezone.utc)
    await raid.save(session=session)

    # Build player team from each player's chosen champion
    player_units = []
    for idx, player_id in enumerate(raid.player_ids):
        champ_id = raid.player_champions.get(player_id)
        if not champ_id:
            continue
        champ_doc = await ChampionInstance.get(PydanticObjectId(champ_id))
        if champ_doc is None:
            continue
        item_docs = await ItemInstance.find(
            ItemInstance.equipped_to == str(champ_doc.id)
        ).to_list()
        unit = build_unit_from_champion(champ_doc, item_docs, position=idx + 1, team=0)
        player_units.append(unit)

    if not player_units:
        raise RaidError("No valid champions in raid.")

    # Build boss
    boss = generate_boss_unit_for_zone(raid.zone)
    # Buff boss for raid (more HP per player)
    boss.hp = boss.hp * len(player_units)
    boss.hp_max = boss.hp

    battle_result = run_battle(player_units, [boss])

    # Distribute personal loot
    player_rewards = {}
    if battle_result.winner == 0:
        zone_cfg = HUNT_ZONES[raid.zone]
        for player_id in raid.player_ids:
            # Idempotency: skip if already rewarded
            if player_id in raid.rewarded_player_ids:
                player_rewards[player_id] = {"already_rewarded": True}
                continue
            rewards = await _roll_raid_drops(player_id, zone_cfg["gold_multiplier"], session)
            raid.rewarded_player_ids.append(player_id)
            player_rewards[player_id] = rewards

    raid.status = "completed" if battle_result.winner == 0 else "failed"
    raid.completed_at = datetime.now(timezone.utc)
    await raid.save(session=session)

    return {
        "battle_result": battle_result,
        "player_rewards": player_rewards,
        "battle_log": battle_result.log,
    }


async def _roll_raid_drops(
    owner_id: str,
    gold_multiplier: float,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    rewards: dict[str, Any] = {"gold": 0, "champions": [], "items": [], "seals": 0, "summon_tokens": 0}
    user = await User.find_one(User.discord_id == owner_id, session=session)

    for drop_key, cfg in RAID_DROPS.items():
        if random.random() > cfg["chance"]:
            continue

        if drop_key == "gold":
            amount = int(random.randint(cfg["min"], cfg["max"]) * gold_multiplier)
            user.gold += amount
            rewards["gold"] += amount

        elif drop_key == "champion":
            rank = random.choice(["D", "C", "B"])
            name = random.choice(ALL_CHAMPION_NAMES)
            c = await grant_champion(owner_id, name, rank, session)
            rewards["champions"].append({"name": name, "rank": rank})

        elif drop_key == "item":
            rank = random.choice(["C", "B"])
            name, stat, passive = random.choice(ITEM_POOL)
            await grant_item(owner_id, name, rank, stat, passive, session)
            rewards["items"].append({"name": name, "rank": rank})

        elif drop_key == "seal":
            user.blacksmith_seals = getattr(user, "blacksmith_seals", 0) + 1
            rewards["seals"] += 1

        elif drop_key == "summon_token":
            amount = random.randint(cfg["min"], cfg["max"])
            user.summon_tokens += amount
            rewards["summon_tokens"] += amount

    await user.save(session=session)
    return rewards
