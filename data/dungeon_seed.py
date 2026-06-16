"""
Dungeon seed data — 12 LoL-region dungeons with full floor definitions.

All Dungeon and DungeonFloor documents are generated here and inserted once via
``seed_dungeons()`` (idempotent). Floor enemy stats are computed at battle time
from the per-floor multipliers stored on each DungeonFloor, using the scaling
formula in ``services.dungeon_service``.
"""
from __future__ import annotations
import random

from models.dungeon import Dungeon, DungeonFloor


# ---------------------------------------------------------------------------
# Region -> champion roster used to populate floors
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
    "demacia": "🏰",
    "noxus": "🗡️",
    "ionia": "🌸",
    "freljord": "❄️",
    "void": "🌌",
    "shadow-isles": "💀",
    "piltover": "⚙️",
    "bilgewater": "⚓",
}

HAZARDS = ["wound", "berserker", "armored", "speed_seal", "double_strike"]


# ---------------------------------------------------------------------------
# Dungeon catalogue
# (slug, name, region, total_floors, boss_name, boss_passive, unlock_req, rank)
# ---------------------------------------------------------------------------
DUNGEON_DEFS = [
    ("demacia-outskirts", "Demacia Outskirts", "demacia", 20, "Garen", "garen_passive", "", "F"),
    ("noxus-warfront", "Noxus Warfront", "noxus", 20, "Darius", "darius_passive", "", "F"),
    ("ionia-temple-trials", "Ionia Temple Trials", "ionia", 20, "Irelia", "irelia_passive", "", "F"),
    ("freljord-wilds", "Freljord Wilds", "freljord", 20, "Sejuani", "sejuani_passive", "", "F"),
    ("demacias-depths", "Demacia's Depths", "demacia", 40, "Jarvan IV", "jarvan_passive", "demacia-outskirts", "D"),
    ("noxian-conquest", "Noxian Conquest", "noxus", 40, "Swain", "swain_passive", "noxus-warfront", "D"),
    ("ionian-war", "Ionian War", "ionia", 40, "Yasuo", "yasuo_passive", "ionia-temple-trials", "D"),
    ("freljord-siege", "Freljord Siege", "freljord", 40, "Tryndamere", "tryndamere_passive", "freljord-wilds", "D"),
    ("void-incursion", "Void Incursion", "void", 50, "Cho'Gath", "chogath_passive", "ANY_40", "B"),
    ("shadow-isles", "Shadow Isles", "shadow-isles", 50, "Mordekaiser", "mordekaiser_passive", "ANY_40", "B"),
    ("piltover-uprising", "Piltover Uprising", "piltover", 35, "Jayce", "jayce_passive", "ANY_20", "C"),
    ("bilgewater-docks", "Bilgewater Docks", "bilgewater", 35, "Gangplank", "gangplank_passive", "ANY_20", "C"),
]

DUNGEON_DESCRIPTIONS = {
    "demacia-outskirts": "The sunlit borderlands of Demacia. A trial for fledgling summoners.",
    "noxus-warfront": "Blood-soaked battlefields where only the strong advance.",
    "ionia-temple-trials": "Sacred grounds testing balance, focus, and resolve.",
    "freljord-wilds": "Unforgiving frozen tundra ruled by warring tribes.",
    "demacias-depths": "Forgotten dungeons beneath the Great City, guarded by the Exemplar of Demacia.",
    "noxian-conquest": "The march of empire — Swain's grand vision realized in steel.",
    "ionian-war": "Ionia rises against invaders. The Unforgiven awaits.",
    "freljord-siege": "An endless winter assault led by the Barbarian King.",
    "void-incursion": "Reality tears open. The Terror of the Void hungers.",
    "shadow-isles": "A cursed mist swallows all. The Iron Revenant rules the dead.",
    "piltover-uprising": "The City of Progress turns its inventions to war.",
    "bilgewater-docks": "Lawless ports ruled by the Saltwater Scourge.",
}


def _rank_for_floor(total_floors: int, floor_num: int) -> str:
    """Progressive enemy rank scaling across the dungeon's floors."""
    ranks = ["F", "E", "D", "C", "B", "A", "S"]
    frac = floor_num / max(1, total_floors)
    idx = min(len(ranks) - 1, int(frac * len(ranks)))
    return ranks[idx]


def _checkpoints_for(total_floors: int) -> set[int]:
    return {f for f in range(10, total_floors, 10)}


def _hazard_for_floor(rng: random.Random, floor_num: int, boss_floor: bool) -> str:
    if boss_floor:
        return ""
    # ~35% of non-boss floors carry a hazard, deterministic per dungeon/floor.
    if rng.random() < 0.35:
        return rng.choice(HAZARDS)
    return ""


def build_floors(slug: str, region: str, total_floors: int,
                 boss_name: str, boss_passive: str) -> list[DungeonFloor]:
    """Generate the DungeonFloor documents for one dungeon."""
    roster = REGION_ROSTERS[region]
    checkpoints = _checkpoints_for(total_floors)
    rng = random.Random(slug)  # deterministic per dungeon
    floors: list[DungeonFloor] = []

    for floor_num in range(1, total_floors + 1):
        boss_floor = floor_num == total_floors
        rank = _rank_for_floor(total_floors, floor_num)
        hazard = _hazard_for_floor(rng, floor_num, boss_floor)

        if boss_floor:
            enemies = [{
                "name": boss_name,
                "rank": rank,
                "level": 10 + floor_num,
                "hp_mult": 1.0,
                "atk_mult": 1.0,
                "def_mult": 1.0,
            }]
        else:
            count = rng.randint(1, 3)
            enemies = []
            for _ in range(count):
                name = rng.choice(roster)
                enemies.append({
                    "name": name,
                    "rank": rank,
                    "level": max(1, floor_num),
                    "hp_mult": round(rng.uniform(0.9, 1.15), 2),
                    "atk_mult": round(rng.uniform(0.9, 1.1), 2),
                    "def_mult": round(rng.uniform(0.9, 1.1), 2),
                })

        floors.append(DungeonFloor(
            dungeon_slug=slug,
            floor_num=floor_num,
            enemies=enemies,
            boss_floor=boss_floor,
            boss_passive=boss_passive if boss_floor else "",
            hazard=hazard,
            checkpoint_floor=floor_num in checkpoints,
            reward_gold=50 + floor_num * 15,
            reward_xp=20 + floor_num * 8,
            extra_drop_chance=0.10,
        ))
    return floors


async def seed_dungeons() -> bool:
    """Create all Dungeon and DungeonFloor documents. Idempotent.

    Returns True if seeding ran, False if dungeons already existed.
    """
    existing = await Dungeon.find_one(Dungeon.slug == "demacia-outskirts")
    if existing is not None:
        return False

    for (slug, name, region, total_floors, boss_name,
         boss_passive, unlock_req, rank) in DUNGEON_DEFS:
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

        floors = build_floors(slug, region, total_floors, boss_name, boss_passive)
        for floor in floors:
            await floor.insert()

    return True
