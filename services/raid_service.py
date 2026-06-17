"""
Raid service: F-S difficulty tiers, 5 raids/day, solo or group (up to 5).
Boss stays at full raid strength for solo — it's intentionally hard.
"""
from __future__ import annotations
import random
from datetime import datetime, timezone, date
from typing import Any

from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.raid import RaidQueue
from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from engine.combat import build_unit_from_champion, run_battle
from engine.skills import ALL_CHAMPION_NAMES
from services.champion_service import grant_champion
from services.item_service import grant_item
from config.game_config import RAID_MAX_PLAYERS, RAID_DAILY_LIMIT, RAID_DIFFICULTIES, CHAMPION_BASE_STATS


class RaidError(Exception):
    pass


# ---------------------------------------------------------------------------
# Daily limit helpers
# ---------------------------------------------------------------------------

def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _reset_daily_raids_if_needed(user: User) -> None:
    today = _today_utc()
    reset_date = user.daily_raids_reset.date() if user.daily_raids_reset else None
    if reset_date != today:
        user.daily_raids_used = 0
        user.daily_raids_reset = datetime.now(timezone.utc)


def raids_remaining(user: User) -> int:
    _reset_daily_raids_if_needed(user)
    return max(0, RAID_DAILY_LIMIT - user.daily_raids_used)


# ---------------------------------------------------------------------------
# Boss generation
# ---------------------------------------------------------------------------

def _build_raid_boss(difficulty: str, n_players: int):
    """Build a boss CombatUnit scaled to the raid difficulty and player count."""
    from engine.combat import build_boss_unit
    cfg = RAID_DIFFICULTIES[difficulty]
    rank = cfg["boss_rank"]
    level = cfg["boss_level"]
    base = CHAMPION_BASE_STATS.get(rank, CHAMPION_BASE_STATS["F"])

    growth = 1.05 ** (level - 1)
    hp  = int(base["hp"]  * growth * cfg["boss_hp_mult"] * max(1, n_players * 0.6))
    atk = int(base["atk"] * growth * cfg["boss_hp_mult"] ** 0.5)
    defense = int(base["def"] * growth)

    boss_names = {
        "F": "Corrupted Scout",
        "E": "Void Marauder",
        "D": "Iron Colossus",
        "C": "Shadow Warlord",
        "B": "Abyssal Titan",
        "A": "Elder Dragon",
        "S": "Ancient Rift Herald",
    }

    return build_boss_unit({
        "name": boss_names.get(difficulty, "Raid Boss"),
        "rank": rank,
        "level": level,
        "hp": hp,
        "atk": atk,
        "def": defense,
        "spd": 95,
        "is_boss": True,
        "mechanic": "",
        "champion_name": "",
    }, position=1, team=1)


# ---------------------------------------------------------------------------
# Queue management
# ---------------------------------------------------------------------------

async def create_raid_queue(
    leader_id: str,
    difficulty: str,
    session: AsyncIOMotorClientSession,
) -> RaidQueue:
    if difficulty not in RAID_DIFFICULTIES:
        raise RaidError(f"Invalid difficulty '{difficulty}'. Choose F–S.")

    user = await User.find_one(User.discord_id == leader_id, session=usable_session(session))
    if user is None:
        raise RaidError("User not found.")
    _reset_daily_raids_if_needed(user)
    if user.daily_raids_used >= RAID_DAILY_LIMIT:
        raise RaidError(f"Daily raid limit reached ({RAID_DAILY_LIMIT}/day). Resets at midnight UTC.")

    existing = await RaidQueue.find_one(
        RaidQueue.leader_id == leader_id,
        RaidQueue.status == "waiting",
        session=usable_session(session),
    )
    if existing:
        raise RaidError("You already have an open raid. Start or cancel it first.")

    raid = RaidQueue(
        zone=difficulty,
        leader_id=leader_id,
        player_ids=[leader_id],
        status="waiting",
    )
    await raid.insert(session=usable_session(session))
    return raid


async def join_raid(
    player_id: str,
    raid_id: str,
    champion_id: str,
    session: AsyncIOMotorClientSession,
) -> RaidQueue:
    raid = await RaidQueue.get(PydanticObjectId(raid_id), session=usable_session(session))
    if raid is None:
        raise RaidError("Raid not found.")
    if raid.status != "waiting":
        raise RaidError("Raid is not accepting players.")
    if player_id in raid.player_ids:
        raise RaidError("You are already in this raid.")
    if len(raid.player_ids) >= RAID_MAX_PLAYERS:
        raise RaidError("Raid is full (5 players max).")

    user = await User.find_one(User.discord_id == player_id, session=usable_session(session))
    if user:
        _reset_daily_raids_if_needed(user)
        if user.daily_raids_used >= RAID_DAILY_LIMIT:
            raise RaidError(f"Daily raid limit reached ({RAID_DAILY_LIMIT}/day). Resets at midnight UTC.")

    c = await ChampionInstance.get(PydanticObjectId(champion_id), session=usable_session(session))
    if c is None or c.owner_id != player_id:
        raise RaidError("Champion not found or not owned by you.")

    raid.player_ids.append(player_id)
    raid.player_champions[player_id] = champion_id
    await raid.save(session=usable_session(session))
    return raid


# ---------------------------------------------------------------------------
# Run the raid
# ---------------------------------------------------------------------------

async def start_raid(
    leader_id: str,
    raid_id: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    raid = await RaidQueue.get(PydanticObjectId(raid_id), session=usable_session(session))
    if raid is None:
        raise RaidError("Raid not found.")
    if raid.leader_id != leader_id:
        raise RaidError("Only the raid leader can start.")
    if raid.status != "waiting":
        raise RaidError(f"Raid is already {raid.status}.")

    difficulty = raid.zone  # zone field reused as difficulty key
    cfg = RAID_DIFFICULTIES.get(difficulty, RAID_DIFFICULTIES["F"])
    n_players = len(raid.player_ids)
    is_solo = n_players == 1

    raid.status = "in_progress"
    raid.started_at = datetime.now(timezone.utc)
    await raid.save(session=usable_session(session))

    # Build player team
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

    boss = _build_raid_boss(difficulty, n_players)
    battle_result = run_battle(player_units, [boss])

    # Spend daily raid slots and distribute loot
    player_rewards = {}
    for player_id in raid.player_ids:
        if player_id in raid.rewarded_player_ids:
            player_rewards[player_id] = {"already_rewarded": True}
            continue

        user = await User.find_one(User.discord_id == player_id, session=usable_session(session))
        if user:
            _reset_daily_raids_if_needed(user)
            user.daily_raids_used += 1
            user.raids_completed += (1 if battle_result.winner == 0 else 0)

        if battle_result.winner == 0:
            rewards = await _roll_raid_drops(player_id, difficulty, is_solo, session)
            raid.rewarded_player_ids.append(player_id)
            player_rewards[player_id] = rewards
            if user:
                await user.save(session=usable_session(session))
        else:
            player_rewards[player_id] = {"gold": 0, "lost": True}
            if user:
                await user.save(session=usable_session(session))

    raid.status = "completed" if battle_result.winner == 0 else "failed"
    raid.completed_at = datetime.now(timezone.utc)
    await raid.save(session=usable_session(session))

    return {
        "battle_result": battle_result,
        "player_rewards": player_rewards,
        "difficulty": difficulty,
        "is_solo": is_solo,
        "battle_log": battle_result.log,
    }


# ---------------------------------------------------------------------------
# Loot rolling
# ---------------------------------------------------------------------------

RAID_ITEM_POOL = [
    ("Infinity Edge",        "atk", "crit_damage_passive"),
    ("Chain Vest",           "def", "armor_passive"),
    ("Ruby Crystal",         "hp",  "fortify_passive"),
    ("Recurve Bow",          "atk", "attack_speed_passive"),
    ("Needlessly Large Rod", "atk", "crit_damage_passive"),
    ("Warmog's Armor",       "hp",  "fortify_passive"),
    ("Warden's Mail",        "def", "armor_passive"),
]


async def _roll_raid_drops(
    owner_id: str,
    difficulty: str,
    is_solo: bool,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    cfg = RAID_DIFFICULTIES[difficulty]
    rewards: dict[str, Any] = {
        "gold": 0, "champions": [], "items": [], "seals": 0, "summon_tokens": 0
    }

    # Solo penalty: 60% gold and tokens (risk vs reward, you don't die for free)
    solo_mult = 0.60 if is_solo else 1.0

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))

    # Gold — always drops
    gold = int(random.randint(cfg["gold_min"], cfg["gold_max"]) * solo_mult)
    user.gold += gold
    rewards["gold"] = gold

    # Tokens — always drops
    tokens = int(random.randint(cfg["token_min"], cfg["token_max"]) * solo_mult)
    user.summon_tokens += tokens
    rewards["summon_tokens"] = tokens

    # Champion drop
    if random.random() < cfg["champ_chance"]:
        rank = random.choice(cfg["champ_ranks"])
        name = random.choice(list(ALL_CHAMPION_NAMES))
        await grant_champion(owner_id, name, rank, session)
        rewards["champions"].append({"name": name, "rank": rank})

    # Item drop
    if random.random() < cfg["item_chance"]:
        rank = random.choice(cfg["item_ranks"])
        name, stat, passive = random.choice(RAID_ITEM_POOL)
        await grant_item(owner_id, name, rank, stat, passive, session)
        rewards["items"].append({"name": name, "rank": rank})

    # Blacksmith seal (rare)
    if random.random() < cfg["seal_chance"]:
        user.blacksmith_seals = getattr(user, "blacksmith_seals", 0) + 1
        rewards["seals"] = 1

    await user.save(session=usable_session(session))
    return rewards
