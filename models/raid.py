from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field


class RaidQueue(Document):
    zone: str
    leader_id: str
    player_ids: list[str] = []
    # champion chosen per player (discord_id -> champion instance id)
    player_champions: dict[str, str] = {}
    # "waiting" | "in_progress" | "completed" | "failed"
    status: str = "waiting"
    # Interaction IDs that already received rewards (idempotency)
    rewarded_player_ids: list[str] = []

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Settings:
        name = "raid_queues"
        indexes = ["leader_id", "status"]
