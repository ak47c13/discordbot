from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from beanie import Document
from pydantic import Field


class Dungeon(Document):
    """Static dungeon definition (seeded once, never changes per player)."""
    slug: str                          # e.g. "demacia-outskirts"
    name: str                          # display name
    region: str                        # "demacia" | "noxus" | ...
    emoji: str                         # region emoji
    total_floors: int
    unlock_req: str = ""               # slug of dungeon to complete first; "" = always unlocked
    is_active: bool = True
    description: str = ""
    boss_name: str = ""
    boss_passive: str = ""             # slug of boss mechanic
    recommended_rank: str = "F"        # suggested player rank

    class Settings:
        name = "dungeons"
        indexes = ["slug", "region"]


class DungeonFloor(Document):
    """Per-floor enemy and reward config."""
    dungeon_slug: str
    floor_num: int
    enemies: list[dict] = Field(default_factory=list)
    # each enemy: {"name": str, "rank": str, "level": int, "hp_mult": float, "atk_mult": float, "def_mult": float}
    boss_floor: bool = False
    boss_passive: str = ""             # overrides dungeon boss_passive on boss floor
    hazard: str = ""                   # "" | "wound" | "berserker" | "armored" | "speed_seal" | "double_strike"
    checkpoint_floor: bool = False
    reward_gold: int = 0
    reward_xp: int = 0
    extra_drop_chance: float = 0.0     # chance to drop a rune_shard

    class Settings:
        name = "dungeon_floors"
        indexes = [("dungeon_slug", "floor_num")]


class DungeonProgress(Document):
    """Per-player per-dungeon progress."""
    owner_id: str
    dungeon_slug: str
    highest_floor: int = 0
    checkpoint_floor: int = 0          # last checkpoint reached
    completions: int = 0
    first_clear_at: datetime | None = None
    last_daily_at: datetime | None = None
    last_attempt_at: datetime | None = None

    class Settings:
        name = "dungeon_progress"
        indexes = [("owner_id", "dungeon_slug")]


class DungeonRun(Document):
    """Log of each floor attempt."""
    owner_id: str
    dungeon_slug: str
    floor_num: int
    team_snapshot: list[dict] = Field(default_factory=list)
    result: str = "win"                # "win" | "loss" | "fled"
    damage_dealt: int = 0
    rewards_given: dict = Field(default_factory=dict)
    hazard: str = ""
    boss_passive: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "dungeon_runs"
        indexes = ["owner_id", "dungeon_slug"]
