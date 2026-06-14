"""
BattleSession — persistent record of a simulated battle.
The entire fight is simulated once, stored here, then revealed round-by-round
by editing a single Discord message.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from beanie import Document
from pydantic import Field


class BattleSession(Document):
    # Discord context
    owner_id: str
    guild_id: str = ""
    channel_id: str = ""
    message_id: str = ""
    static_image_url: str = ""   # unused for now; reserved for future image

    # Battle type
    battle_type: str = "hunt"    # "hunt", "boss", "raid"
    zone: str = ""

    # Status lifecycle
    status: str = "CREATING"    # CREATING / ACTIVE / VICTORY / DEFEAT / CANCELLED_* / ERROR / EXPIRED

    # Round tracking
    current_round: int = 0
    max_rounds: int = 50
    simulated_round_count: int = 0
    displayed_round_count: int = 0

    # Display speed
    fast_display: bool = False

    # Battle data
    battle_seed: int = 0
    winner: int = -1             # 0=players, 1=enemies, -1=pending

    # Stored rounds: list of round dicts
    simulated_rounds: list[dict] = Field(default_factory=list)

    # Snapshots
    player_snapshot: list[dict] = Field(default_factory=list)
    enemy_snapshot: list[dict] = Field(default_factory=list)

    # Rewards (pre-rolled)
    rewards_json: dict = Field(default_factory=dict)
    reward_claimed: bool = False

    # Entry cost for potential refund
    entry_cost_json: dict = Field(default_factory=dict)

    # Audit
    version: int = 0
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str = ""

    class Settings:
        name = "battle_sessions"
        indexes = [
            "owner_id",
            "status",
            "message_id",
        ]
