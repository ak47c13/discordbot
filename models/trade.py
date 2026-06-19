from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field


class TradeOffer(Document):
    initiator_id: str
    target_id: str

    # What each side offers (lists of champion/item instance IDs + gold)
    initiator_champion_ids: list[str] = []
    initiator_item_ids: list[str] = []
    initiator_gold: int = 0

    target_champion_ids: list[str] = []
    target_item_ids: list[str] = []
    target_gold: int = 0

    # "pending" | "accepted" | "declined" | "cancelled" | "completed"
    status: str = "pending"

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    class Settings:
        name = "trades"
        indexes = ["initiator_id", "target_id", "status"]
