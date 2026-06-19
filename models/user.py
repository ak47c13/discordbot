from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field
from models.rune_page import RunePage


class User(Document):
    discord_id: str
    username: str
    gold: int = 0
    champion_tokens: int = 0
    item_tokens: int = 0
    rune_tokens: int = 0
    blacksmith_seals: int = 0
    registered: bool = False
    stamina: int = 100
    max_stamina: int = 100
    last_stamina_regen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raids_completed: int = 0
    daily_raids_used: int = 0
    daily_raids_reset: Optional[datetime] = None
    rune_shards: int = 0        # legacy field — no longer used
    last_daily: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Starter free pulls claimed (values: "champion", "rune", "item")
    starter_pulls_claimed: list[str] = Field(default_factory=list)

    # Single active champion
    active_champion_id: Optional[str] = None
    active_skill: str = "q"
    rune_page: RunePage = Field(default_factory=RunePage)

    class Settings:
        name = "users"
        indexes = ["discord_id"]

    @classmethod
    async def get_or_create(cls, discord_id: str, username: str) -> "User":
        user = await cls.find_one(cls.discord_id == discord_id)
        if not user:
            user = cls(discord_id=discord_id, username=username)
            await user.insert()
        return user
