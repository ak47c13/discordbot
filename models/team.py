from typing import Optional
from beanie import Document


class TeamSlot:
    champion_id: Optional[str] = None   # ChampionInstance id
    position: int = 0                    # 1-5


class Team(Document):
    owner_id: str
    # Ordered list of champion instance IDs, index = slot (0-4 → positions 1-5)
    # None means empty slot
    slots: list[Optional[str]] = [None, None, None, None, None]

    class Settings:
        name = "teams"
        indexes = ["owner_id"]

    @property
    def active_champions(self) -> list[str]:
        return [s for s in self.slots if s is not None]

    @classmethod
    async def get_or_create(cls, owner_id: str) -> "Team":
        team = await cls.find_one(cls.owner_id == owner_id)
        if not team:
            team = cls(owner_id=owner_id)
            await team.insert()
        return team
