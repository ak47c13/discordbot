from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field


class User(Document):
    discord_id: str
    username: str
    gold: int = 0
    summon_tokens: int = 0
    blacksmith_seals: int = 0
    registered: bool = False
    stamina: int = 100
    max_stamina: int = 100
    last_stamina_regen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_daily: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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
