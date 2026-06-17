from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field


class ChampionInstance(Document):
    owner_id: str                    # discord_id of owner
    name: str                        # e.g. "Rengar"
    rank: str                        # F E D C B A S
    level: int = 1
    exp: int = 0

    # State flags — any truthy value locks the champion from most operations
    is_active: bool = False
    locked: bool = False
    in_trade: bool = False
    in_market: bool = False

    # Stable numeric display ID (assigned at creation, never changes)
    display_id: int = 0

    # Collection / metadata flags
    favorite: bool = False
    enabled: bool = True
    release_group: int = 1
    balance_status: str = "DRAFT"  # DRAFT/REVIEWED/TESTED/LIVE/DISABLED
    manually_reviewed: bool = False
    riot_id: str = ""
    title: str = ""
    source_roles: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "champions"
        indexes = [
            "owner_id",
            "display_id",
            [("owner_id", 1), ("name", 1), ("rank", 1)],
        ]

    @property
    def is_available(self) -> bool:
        """Champion can be used in fusion / traded / etc."""
        return (
            not self.is_active
            and not self.locked
            and not self.in_trade
            and not self.in_market
        )
