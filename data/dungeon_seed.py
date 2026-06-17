"""
Dungeon seed data — 8 linear maps, each unlocking the next on clear.

Progression:
  Map 1 (F)  → Map 2 (E)  → Map 3 (D)  → Map 4 (D/C)
  → Map 5 (C) → Map 6 (B) → Map 7 (A) → Map 8 (S)

Enemy rank, floor count, and boss difficulty all scale progressively.
"""
from __future__ import annotations
import random

from models.dungeon import Dungeon, DungeonFloor


# ---------------------------------------------------------------------------
# Region -> champion roster for floor enemies
# ---------------------------------------------------------------------------
REGION_ROSTERS: dict[str, list[str]] = {
    "demacia":      ["Garen", "Lux", "Fiora", "Jarvan IV", "Poppy"],
    "noxus":        ["Darius", "Draven", "Swain", "Katarina", "Sion"],
    "ionia":        ["Irelia", "Yasuo", "Karma", "Lee Sin", "Kennen"],
    "freljord":     ["Sejuani", "Ashe", "Tryndamere", "Nunu", "Volibear"],
    "void":         ["Cho'Gath", "Vel'Koz", "Kog'Maw", "Malzahar", "Kassadin"],
    "shadow-isles": ["Mordekaiser", "Thresh", "Karthus", "Hecarim", "Maokai"],
    "piltover":     ["Jayce", "Vi", "Jinx", "Ezreal", "Heimerdinger"],
    "bilgewater":   ["Gangplank", "Miss Fortune", "Fizz", "Graves", "Twisted Fate"],
}

REGION_EMOJI: dict[str, str] = {
    "demacia":      "🏰",
    "noxus":        "🗡️",
    "freljord":     "❄️",
    "ionia":        "🌸",
    "piltover":     "⚙️",
    "bilgewater":   "⚓",
    "shadow-isles": "💀",
    "void":         "🌌",
}

HAZARDS = ["wound", "berserker", "armored", "speed_seal", "double_strike"]


# ---------------------------------------------------------------------------
# Linear map chain
# (slug, name, region, total_floors, boss_name, boss_passive, unlock_req, rec_rank)
# ---------------------------------------------------------------------------
DUNGEON_DEFS = [
    ("map-1-demacia",      "Map 1: Demacia Outskirts",    "demacia",      15, "Garen",       "garen_passive",       "",                   "F"),
    ("map-2-noxus",        "Map 2: Noxus Warfront",       "noxus",        20, "Darius",       "darius_passive",      "map-1-demacia",      "E"),
    ("map-3-freljord",     "Map 3: Freljord Wilds",       "freljord",     25, "Sejuani",      "sejuani_passive",     "map-2-noxus",        "D"),
    ("map-4-ionia",        "Map 4: Ionia Temple Trials",  "ionia",        30, "Irelia",       "irelia_passive",      "map-3-freljord",     "D"),
    ("map-5-piltover",     "Map 5: Piltover Uprising",    "piltover",     35, "Jayce",        "jayce_passive",       "map-4-ionia",        "C"),
    ("map-6-bilgewater",   "Map 6: Bilgewater Docks",     "bilgewater",   40, "Gangplank",    "gangplank_passive",   "map-5-piltover",     "B"),
    ("map-7-shadow-isles", "Map 7: Shadow Isles",         "shadow-isles", 45, "Mordekaiser",  "mordekaiser_passive", "map-6-bilgewater",   "A"),
    ("map-8-void",         "Map 8: Void Incursion",       "void",         50, "Cho'Gath",     "chogath_passive",     "map-7-shadow-isles", "S"),
]

DUNGEON_DESCRIPTIONS = {
    "map-1-demacia":      "The sunlit borderlands of Demacia. A trial for fledgling summoners. F-rank champions recommended.",
    "map-2-noxus":        "Blood-soaked battlefields where only the strong advance. Bring an E-rank champion.",
    "map-3-freljord":     "Unforgiving frozen tundra ruled by warring tribes. D-rank champions and above.",
    "map-4-ionia":        "Sacred grounds testing balance, focus, and resolve. Enemies hit harder — D/C rank advised.",
    "map-5-piltover":     "The City of Progress turns its inventions to war. C-rank champions recommended.",
    "map-6-bilgewater":   "Lawless ports ruled by the Saltwater Scourge. Bring your best B-rank champion.",
    "map-7-shadow-isles": "A cursed mist swallows all. The Iron Revenant rules the dead. A-rank required.",
    "map-8-void":         "Reality tears open. The Terror of the Void hungers. S-rank only — the final challenge.",
}


# ---------------------------------------------------------------------------
# Floor generation
# ---------------------------------------------------------------------------

def _rank_for_floor(map_index: int, total_floors: int, floor_num: int) -> str:
    """
    Enemy rank scales with both the map number and floor position within the map.
    Map 1 → mostly F/E; Map 8 → mostly A/S.
    """
    all_ranks = ["F", "E", "D", "C", "B", "A", "S"]
    # Base rank index determined by which map this is (0-7 → rank offset 0-4)
    base_idx = min(map_index // 2, 4)
    # Within the map, enemies get tougher on later floors
    frac = floor_num / max(1, total_floors)
    floor_bonus = int(frac * 2)  # +0 early floors, +1 mid, +2 boss area
    idx = min(len(all_ranks) - 1, base_idx + floor_bonus)
    return all_ranks[idx]


def _checkpoints_for(total_floors: int) -> set[int]:
    return {f for f in range(10, total_floors, 10)}


def _hazard_for_floor(rng: random.Random, floor_num: int, boss_floor: bool, map_index: int) -> str:
    if boss_floor:
        return ""
    # Hazard frequency increases slightly on later maps
    chance = 0.25 + map_index * 0.03
    if rng.random() < chance:
        return rng.choice(HAZARDS)
    return ""


def build_floors(slug: str, region: str, total_floors: int,
                 boss_name: str, boss_passive: str, map_index: int) -> list[DungeonFloor]:
    roster = REGION_ROSTERS[region]
    checkpoints = _checkpoints_for(total_floors)
    rng = random.Random(slug)
    floors: list[DungeonFloor] = []

    for floor_num in range(1, total_floors + 1):
        boss_floor = floor_num == total_floors
        rank = _rank_for_floor(map_index, total_floors, floor_num)
        hazard = _hazard_for_floor(rng, floor_num, boss_floor, map_index)

        # Boss stats scale with map depth
        boss_hp_mult = 1.2 + map_index * 0.15
        boss_atk_mult = 1.1 + map_index * 0.10

        if boss_floor:
            enemies = [{
                "name": boss_name,
                "rank": rank,
                "level": 5 + total_floors + map_index * 5,
                "hp_mult": boss_hp_mult,
                "atk_mult": boss_atk_mult,
                "def_mult": 1.0 + map_index * 0.05,
            }]
        else:
            # Enemy count increases on later maps
            max_count = min(3, 1 + map_index // 3)
            count = rng.randint(1, max_count)
            enemies = []
            for _ in range(count):
                name = rng.choice(roster)
                enemies.append({
                    "name": name,
                    "rank": rank,
                    "level": max(1, floor_num + map_index * 2),
                    "hp_mult":  round(rng.uniform(0.9, 1.15), 2),
                    "atk_mult": round(rng.uniform(0.9, 1.10), 2),
                    "def_mult": round(rng.uniform(0.9, 1.10), 2),
                })

        # Gold and XP scale with map depth
        gold_base = 50 + map_index * 30
        xp_base = 20 + map_index * 15

        floors.append(DungeonFloor(
            dungeon_slug=slug,
            floor_num=floor_num,
            enemies=enemies,
            boss_floor=boss_floor,
            boss_passive=boss_passive if boss_floor else "",
            hazard=hazard,
            checkpoint_floor=floor_num in checkpoints,
            reward_gold=gold_base + floor_num * (10 + map_index * 5),
            reward_xp=xp_base + floor_num * (5 + map_index * 3),
            extra_drop_chance=0.08 + map_index * 0.015,
        ))
    return floors


async def seed_dungeons() -> bool:
    """Create all Dungeon and DungeonFloor documents. Idempotent.

    If old-style dungeons exist (pre-linear-chain), wipes them and reseeds.
    Returns True if seeding ran, False if already up to date.
    """
    # Check if new-style linear maps already exist
    existing_new = await Dungeon.find_one(Dungeon.slug == "map-1-demacia")
    if existing_new is not None:
        return False

    # Wipe any legacy dungeons so old/new don't coexist
    await Dungeon.delete_all()
    await DungeonFloor.delete_all()

    for idx, (slug, name, region, total_floors, boss_name,
               boss_passive, unlock_req, rank) in enumerate(DUNGEON_DEFS):
        dungeon = Dungeon(
            slug=slug,
            name=name,
            region=region,
            emoji=REGION_EMOJI.get(region, "🗺️"),
            total_floors=total_floors,
            unlock_req=unlock_req,
            is_active=True,
            description=DUNGEON_DESCRIPTIONS.get(slug, ""),
            boss_name=boss_name,
            boss_passive=boss_passive,
            recommended_rank=rank,
        )
        await dungeon.insert()

        floors = build_floors(slug, region, total_floors, boss_name, boss_passive, idx)
        for floor in floors:
            await floor.insert()

    return True
