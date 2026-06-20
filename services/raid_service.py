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
from engine.combat import build_unit_from_champion, run_battle, run_battle_with_rounds
from engine.skills import ALL_CHAMPION_NAMES
from services.champion_service import grant_champion
from services.item_service import grant_item
from config.game_config import RAID_MAX_PLAYERS, RAID_DAILY_LIMIT, RAID_RESET_HOURS, RAID_DIFFICULTIES, RAID_DIFFICULTY_WEIGHTS, CHAMPION_BASE_STATS, RAID_BOSS_STATS, RANKS, PHT, RAID_XP_REWARDS, champion_xp_threshold, CHAMPION_MAX_LEVEL


class RaidError(Exception):
    pass


# ---------------------------------------------------------------------------
# Daily limit helpers
# ---------------------------------------------------------------------------

def _today_pht() -> date:
    return datetime.now(PHT).date()


def _reset_daily_raids_if_needed(user: User) -> None:
    now = datetime.now(timezone.utc)
    if user.daily_raids_reset is None:
        user.daily_raids_used = 0
        user.daily_raids_reset = now
        return
    last = user.daily_raids_reset
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    from datetime import timedelta
    if (now - last) >= timedelta(hours=RAID_RESET_HOURS):
        user.daily_raids_used = 0
        user.daily_raids_reset = now


def raids_remaining(user: User) -> int:
    _reset_daily_raids_if_needed(user)
    return max(0, RAID_DAILY_LIMIT - user.daily_raids_used)


def roll_raid_difficulty() -> str:
    """Roll a random difficulty tier weighted toward easier tiers."""
    keys = list(RAID_DIFFICULTY_WEIGHTS.keys())
    weights = [RAID_DIFFICULTY_WEIGHTS[k] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Boss generation
# ---------------------------------------------------------------------------

# Champion drop chance by rank (chance that boss drops its own champion card)
CHAMP_DROP_CHANCE: dict[str, float] = {
    "F": 0.15, "E": 0.12, "D": 0.10, "C": 0.07, "B": 0.05, "A": 0.03, "S": 0.015,
}


def _build_raid_boss(difficulty: str, n_players: int, boss_name: str):
    """Build a boss CombatUnit scaled for a full 5-player team, reduced for smaller parties.

    Stats are explicit per-tier values (not formula-derived) so the boss is always
    a meaningful threat regardless of level randomness.
    HP scales linearly: 5 players = 100%, 1 player = 30% (solo is intentionally brutal).
    """
    from engine.combat import build_boss_unit
    cfg = RAID_DIFFICULTIES[difficulty]
    rank = cfg["boss_rank"]
    tier_stats = RAID_BOSS_STATS[rank]

    # HP, ATK, DEF are fixed regardless of party size — the boss is the same challenge.
    # Solo players get 60% payout as consolation, not an easier boss.
    hp = tier_stats["hp"]
    atk = tier_stats["atk"]
    defense = tier_stats["def"]
    spd = tier_stats["spd"]

    # Assign a pseudo-level for display purposes only
    level = 1 + RANKS.index(rank) * 20

    return build_boss_unit({
        "name": boss_name,
        "rank": rank,
        "level": level,
        "hp": hp,
        "atk": atk,
        "def": defense,
        "spd": spd,
        "is_boss": True,
        "mechanic": "",
        "champion_name": boss_name,
    }, position=1, team=1)


# ---------------------------------------------------------------------------
# Queue management
# ---------------------------------------------------------------------------

async def create_raid_queue(
    leader_id: str,
    session: AsyncIOMotorClientSession,
    difficulty: str | None = None,
) -> tuple[RaidQueue, str]:
    """Create a raid queue. Returns (raid, difficulty_key).
    If difficulty is None, it is rolled randomly.
    """
    difficulty = difficulty or roll_raid_difficulty()
    if difficulty not in RAID_DIFFICULTIES:
        raise RaidError(f"Invalid difficulty '{difficulty}'.")

    user = await User.find_one(User.discord_id == leader_id, session=usable_session(session))
    if user is None:
        raise RaidError("User not found.")
    _reset_daily_raids_if_needed(user)
    if user.daily_raids_used >= RAID_DAILY_LIMIT:
        raise RaidError(f"Raid limit reached ({RAID_DAILY_LIMIT} raids per {RAID_RESET_HOURS}h). Try again later.")
    user.daily_raids_used += 1
    await user.save(session=usable_session(session))

    existing = await RaidQueue.find_one(
        RaidQueue.leader_id == leader_id,
        RaidQueue.status == "waiting",
        session=usable_session(session),
    )
    if existing:
        raise RaidError("You already have an open raid. Start or cancel it first.")

    # Resolve the leader's active champion
    if not user.active_champion_id:
        raise RaidError("No active champion. Use /champion-select to pick one first.")
    leader_champ = await ChampionInstance.get(user.active_champion_id)
    if leader_champ is None or leader_champ.owner_id != leader_id:
        raise RaidError("Active champion not found. Use /champion-select to pick one first.")

    cfg = RAID_DIFFICULTIES.get(difficulty, RAID_DIFFICULTIES["F"])
    boss_name = random.choice(list(ALL_CHAMPION_NAMES))
    boss_rank = cfg["boss_rank"]

    raid = RaidQueue(
        zone=difficulty,
        leader_id=leader_id,
        player_ids=[leader_id],
        player_champions={leader_id: str(leader_champ.id)},
        status="waiting",
        boss_champion_name=boss_name,
        boss_rank=boss_rank,
    )
    await raid.insert(session=usable_session(session))
    return raid, difficulty


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

async def prepare_raid(
    leader_id: str,
    raid_id: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    """Validate, build units, mark raid in_progress. Does NOT run combat."""
    raid = await RaidQueue.get(PydanticObjectId(raid_id), session=usable_session(session))
    if raid is None:
        raise RaidError("Raid not found.")
    if raid.leader_id != leader_id:
        raise RaidError("Only the raid leader can start.")
    if raid.status != "waiting":
        raise RaidError(f"Raid is already {raid.status}.")

    difficulty = raid.zone
    cfg = RAID_DIFFICULTIES.get(difficulty, RAID_DIFFICULTIES["F"])
    n_players = len(raid.player_ids)
    is_solo = n_players == 1
    boss_rank = cfg["boss_rank"]
    boss_name = raid.boss_champion_name or random.choice(list(ALL_CHAMPION_NAMES))

    player_units = []
    unit_to_player: dict[str, str] = {}
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
        unit_to_player[unit.unit_id] = player_id

    if not player_units:
        raise RaidError("No valid champions in raid.")

    boss = _build_raid_boss(difficulty, n_players, boss_name)

    raid.status = "in_progress"
    raid.started_at = datetime.now(timezone.utc)
    raid.boss_champion_name = boss_name
    raid.boss_rank = boss_rank
    await raid.save(session=usable_session(session))

    return {
        "raid_id": str(raid.id),
        "player_units": player_units,
        "enemy_units": [boss],
        "unit_to_player": unit_to_player,
        "player_ids": list(raid.player_ids),
        "difficulty": difficulty,
        "is_solo": is_solo,
        "boss_name": boss_name,
        "boss_rank": boss_rank,
    }


async def finalize_raid(
    raid_id: str,
    player_units: list,
    unit_to_player: dict[str, str],
    player_ids: list[str],
    winner: int,
    difficulty: str,
    is_solo: bool,
    boss_name: str,
    boss_rank: str,
    session: AsyncIOMotorClientSession,
) -> dict[str, Any]:
    """Calculate contributions and distribute rewards after combat resolves."""
    raid = await RaidQueue.get(PydanticObjectId(raid_id), session=usable_session(session))
    if raid is None:
        raise RaidError("Raid session not found — rewards could not be distributed.")

    raw_scores: dict[str, float] = {}
    for unit in player_units:
        pid = unit_to_player.get(unit.unit_id)
        if pid:
            raw_scores[pid] = (
                getattr(unit, "damage_dealt", 0) * 0.5
                + getattr(unit, "damage_taken", 0) * 0.3
                + getattr(unit, "healing_done", 0) * 0.2
            )
    total_score = sum(raw_scores.values()) or 1
    contributions: dict[str, float] = {pid: s / total_score for pid, s in raw_scores.items()}

    champ_dropped: list[str] = []
    won = winner in (0, -1)
    if won:
        drop_chance = CHAMP_DROP_CHANCE.get(boss_rank, 0.05)
        if is_solo:
            drop_chance *= 0.5
        if random.random() < drop_chance:
            eligible = {p: c for p, c in contributions.items() if c >= 0.10}
            if not eligible:
                eligible = contributions
            player_list = list(eligible.keys())
            weights = [eligible[p] for p in player_list]
            winner_pid = random.choices(player_list, weights=weights, k=1)[0]
            champ_dropped.append(winner_pid)

    player_rewards: dict[str, Any] = {}
    rewarded = set(raid.rewarded_player_ids) if raid else set()
    for player_id in player_ids:
        if player_id in rewarded:
            player_rewards[player_id] = {"already_rewarded": True}
            continue
        user = await User.find_one(User.discord_id == player_id, session=usable_session(session))
        if user:
            _reset_daily_raids_if_needed(user)
            user.raids_completed += (1 if won else 0)
            await user.save(session=usable_session(session))
        if won:
            drop_copies = champ_dropped.count(player_id)
            p_champ_id = (raid.player_champions or {}).get(player_id) if raid else None
            rewards = await _roll_raid_drops(
                player_id, difficulty, is_solo, session,
                boss_name=boss_name, boss_rank=boss_rank, champ_copies=drop_copies,
                contribution=contributions.get(player_id, 0.0),
                champ_id=p_champ_id,
            )
            if raid:
                raid.rewarded_player_ids.append(player_id)
            player_rewards[player_id] = rewards
        else:
            player_rewards[player_id] = {"gold": 0, "lost": True}

    if raid:
        raid.status = "completed" if won else "failed"
        raid.completed_at = datetime.now(timezone.utc)
        await raid.save(session=usable_session(session))

    return {
        "player_rewards": player_rewards,
        "contributions": contributions,
        "won": won,
    }


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

    # Use the boss champion rolled at queue creation time
    boss_rank = cfg["boss_rank"]
    boss_name = raid.boss_champion_name or random.choice(list(ALL_CHAMPION_NAMES))

    # Build player team BEFORE marking in_progress so a bad state can't get stuck
    # Keep a map from unit_id -> player_id for contribution lookup
    player_units = []
    unit_to_player: dict[str, str] = {}
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
        unit_to_player[unit.unit_id] = player_id

    if not player_units:
        raise RaidError("No valid champions in raid.")

    raid.status = "in_progress"
    raid.started_at = datetime.now(timezone.utc)
    raid.boss_champion_name = boss_name
    raid.boss_rank = boss_rank
    await raid.save(session=usable_session(session))

    boss = _build_raid_boss(difficulty, n_players, boss_name)
    # Raids are uncapped — fight until party wipes or boss dies (no draw on round count)
    battle_result, _rounds = run_battle_with_rounds(player_units, [boss], max_rounds=0)

    # Build per-player contribution scores from unit tracking
    # score = 60% damage dealt + 40% damage taken (normalized)
    raw_scores: dict[str, float] = {}
    for unit in player_units:
        pid = unit_to_player.get(unit.unit_id)
        if pid:
            raw_scores[pid] = (
                unit.damage_dealt * 0.5
                + unit.damage_taken * 0.3
                + getattr(unit, "healing_done", 0) * 0.2
            )
    total_score = sum(raw_scores.values()) or 1
    contributions: dict[str, float] = {pid: s / total_score for pid, s in raw_scores.items()}

    # Roll champion drop once for the whole raid (not per-player)
    champ_dropped: list[str] = []   # list of player_ids who receive a champion copy
    if battle_result.winner in (0, -1):
        drop_chance = CHAMP_DROP_CHANCE.get(boss_rank, 0.05)
        if is_solo:
            drop_chance *= 0.5   # solo penalty
        if random.random() < drop_chance:
            eligible = {p: c for p, c in contributions.items() if c >= 0.10}
            if not eligible:
                eligible = contributions  # fallback: solo or all below threshold
            player_list = list(eligible.keys())
            weights = [eligible[p] for p in player_list]
            winner_pid = random.choices(player_list, weights=weights, k=1)[0]
            champ_dropped.append(winner_pid)

    # Spend daily raid slots and distribute loot
    player_rewards = {}
    for player_id in raid.player_ids:
        if player_id in raid.rewarded_player_ids:
            player_rewards[player_id] = {"already_rewarded": True}
            continue

        user = await User.find_one(User.discord_id == player_id, session=usable_session(session))
        if user:
            _reset_daily_raids_if_needed(user)
            user.raids_completed += (1 if battle_result.winner in (0, -1) else 0)

        if user:
            await user.save(session=usable_session(session))   # save daily count updates
        if battle_result.winner in (0, -1):
            drop_copies = champ_dropped.count(player_id)
            p_champ_id = (raid.player_champions or {}).get(player_id)
            rewards = await _roll_raid_drops(
                player_id, difficulty, is_solo, session,
                boss_name=boss_name, boss_rank=boss_rank, champ_copies=drop_copies,
                contribution=contributions.get(player_id, 0.0),
                champ_id=p_champ_id,
            )
            raid.rewarded_player_ids.append(player_id)
            player_rewards[player_id] = rewards
        else:
            player_rewards[player_id] = {"gold": 0, "lost": True}

    raid.status = "completed" if battle_result.winner in (0, -1) else "failed"
    raid.completed_at = datetime.now(timezone.utc)
    await raid.save(session=usable_session(session))

    return {
        "battle_result": battle_result,
        "player_rewards": player_rewards,
        "difficulty": difficulty,
        "is_solo": is_solo,
        "battle_log": battle_result.log,
        "boss_name": boss_name,
        "boss_rank": boss_rank,
        "contributions": contributions,
    }


# ---------------------------------------------------------------------------
# Loot rolling
# ---------------------------------------------------------------------------

# Raids drop components (common) or completed items (rare ~5% of item drops)
RAID_ITEM_POOL = [
    # basics
    ("Long Sword",         "atk", "atk_passive"),
    ("Pickaxe",            "atk", "atk_passive"),
    ("Dagger",             "atk", "attack_speed_passive"),
    ("Cloth Armor",        "def", "armor_passive"),
    ("Null-Magic Mantle",  "def", "magic_resist_passive"),
    ("Ruby Crystal",       "hp",  "fortify_passive"),
    ("Amplifying Tome",    "atk", "atk_passive"),
    # advanced
    ("B.F. Sword",         "atk", "atk_passive"),
    ("Recurve Bow",        "atk", "attack_speed_passive"),
    ("Chain Vest",         "def", "armor_passive"),
    ("Negatron Cloak",     "def", "magic_resist_passive"),
    ("Warden's Mail",      "def", "armor_passive"),
    ("Giant's Belt",       "hp",  "fortify_passive"),
    ("Needlessly Large Rod","atk", "crit_damage_passive"),
    ("Vampiric Scepter",   "atk", "lifesteal_passive"),
    ("Zeal",               "atk", "attack_speed_passive"),
    ("Spectre's Cowl",     "def", "magic_resist_passive"),
    ("Blasting Wand",      "atk", "atk_passive"),
    ("Tear of the Goddess","atk", "atk_passive"),
    ("Serrated Dirk",      "atk", "armor_pen_passive"),
    ("Cauterize",          "atk", "armor_pen_passive"),
    ("Umbral Glaive",      "atk", "armor_pen_passive"),
    ("Aether Wisp",        "atk", "magic_pen_passive"),
    ("Cryptbloom",         "atk", "magic_pen_passive"),
    ("Shadowflame",        "atk", "magic_pen_passive"),
]
# Completed items that can rarely drop from raids (~5% of item drops)
RAID_COMPLETED_ITEM_POOL = [
    ("Infinity Edge",          "atk", "crit_damage_passive"),
    ("Blade of the Ruined King","atk", "lifesteal_passive"),
    ("Sunfire Aegis",          "def", "armor_passive"),
    ("Warmog's Armor",         "hp",  "fortify_passive"),
    ("Rabadon's Deathcap",     "atk", "crit_damage_passive"),
    ("Trinity Force",          "atk", "sheen_passive"),
    ("Spirit Visage",          "def", "magic_resist_passive"),
    ("Sterak's Gage",          "hp",  "fortify_passive"),
    ("Nashor's Tooth",         "atk", "attack_speed_passive"),
    ("Death's Dance",          "atk", "lifesteal_passive"),
    ("Duskblade of Draktharr", "atk", "armor_pen_passive"),
    ("Prowler's Claw",         "atk", "armor_pen_passive"),
    ("Void Staff",             "atk", "magic_pen_passive"),
    ("Shadowflame",            "atk", "magic_pen_passive"),
]
RAID_COMPLETED_DROP_CHANCE = 0.05  # 5% chance the item drop is a completed item


async def _grant_raid_xp(owner_id: str, difficulty: str, champ_id: str | None, session) -> int:
    """Grant XP to the player's active raid champion. Returns XP granted."""
    if not champ_id:
        return 0
    xp = RAID_XP_REWARDS.get(difficulty, 0)
    if not xp:
        return 0
    try:
        champ = await ChampionInstance.get(PydanticObjectId(champ_id), session=usable_session(session))
    except Exception:
        return 0
    if champ is None or champ.owner_id != owner_id:
        return 0
    max_lvl = CHAMPION_MAX_LEVEL.get(champ.rank, 20)
    if champ.level >= max_lvl:
        return 0
    champ.exp += xp
    while champ.level < max_lvl and champ.exp >= champion_xp_threshold(champ.level, champ.rank):
        champ.exp -= champion_xp_threshold(champ.level, champ.rank)
        champ.level += 1
    if champ.level >= max_lvl:
        champ.exp = 0
    await champ.save(session=usable_session(session))
    return xp


async def _roll_raid_drops(
    owner_id: str,
    difficulty: str,
    is_solo: bool,
    session: AsyncIOMotorClientSession,
    boss_name: str = "",
    boss_rank: str = "",
    champ_copies: int = 0,
    contribution: float = 0.0,
    champ_id: str | None = None,
) -> dict[str, Any]:
    cfg = RAID_DIFFICULTIES[difficulty]
    rewards: dict[str, Any] = {
        "gold": 0, "champions": [], "items": [], "seals": 0, "champion_tokens": 0, "xp": 0
    }

    # Solo penalty: 60% gold and tokens
    solo_mult = 0.60 if is_solo else 1.0

    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user is None:
        return rewards

    # Gold — always drops
    gold = int(random.randint(cfg["gold_min"], cfg["gold_max"]) * solo_mult)
    user.gold += gold
    rewards["gold"] = gold

    # Tokens — always drops
    tokens = int(random.randint(cfg["token_min"], cfg["token_max"]) * solo_mult)
    user.champion_tokens = getattr(user, "champion_tokens", 0) + tokens
    rewards["champion_tokens"] = tokens

    # Boss champion drop (pre-rolled by start_raid, champ_copies already determined)
    for _ in range(champ_copies):
        rank = boss_rank or cfg["boss_rank"]
        name = boss_name or random.choice(list(ALL_CHAMPION_NAMES))
        await grant_champion(owner_id, name, rank, session)
        rewards["champions"].append({"name": name, "rank": rank, "is_boss_drop": True})

    # Item drop — 5% chance of completed item, otherwise component
    if random.random() < cfg["item_chance"]:
        rank = random.choice(cfg["item_ranks"])
        if random.random() < RAID_COMPLETED_DROP_CHANCE:
            pool = RAID_COMPLETED_ITEM_POOL
        else:
            pool = RAID_ITEM_POOL
        name, stat, passive = random.choice(pool)
        await grant_item(owner_id, name, rank, stat, passive, session)
        rewards["items"].append({"name": name, "rank": rank})

    # Blacksmith seal (rare)
    if random.random() < cfg["seal_chance"]:
        user.blacksmith_seals = getattr(user, "blacksmith_seals", 0) + 1
        rewards["seals"] = 1

    xp_gained = await _grant_raid_xp(owner_id, difficulty, champ_id, session)
    rewards["xp"] = xp_gained
    rewards["contribution_pct"] = round(contribution * 100, 1)
    await user.save(session=usable_session(session))
    return rewards


async def cancel_raid(leader_id: str, raid_id: str, session=None) -> None:
    """Cancel a waiting raid. Only the leader can cancel, and only before it starts."""
    raid = await RaidQueue.get(PydanticObjectId(raid_id), session=usable_session(session))
    if raid is None:
        raise RaidError("Raid not found.")
    if raid.leader_id != leader_id:
        raise RaidError("Only the raid leader can cancel.")
    if raid.status != "waiting":
        raise RaidError("Cannot cancel a raid that has already started.")
    raid.status = "cancelled"
    await raid.save(session=usable_session(session))
