from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field


class ItemInstance(Document):
    owner_id: str                    # discord_id of owner
    name: str                        # e.g. "Infinity Edge"
    rank: str                        # F E D C B A S
    enhancement: int = 0             # 0-15

    # Stats
    main_stat_type: str              # e.g. "atk"
    main_stat_base: int              # base value before enhancement
    passive_name: str                # fixed passive identifier
    secondary_stat_type: str
    secondary_stat_value: int        # stored as int (value * 10 for precision)

    # State flags
    equipped_to: Optional[str] = None   # ChampionInstance id if equipped
    equipment_slot: Optional[int] = None  # 1-5
    locked: bool = False
    favorite: bool = False
    in_trade: bool = False
    in_market: bool = False

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "items"
        indexes = [
            "owner_id",
            [("owner_id", 1), ("name", 1), ("rank", 1), ("enhancement", 1)],
        ]

    @property
    def is_available(self) -> bool:
        return (
            not self.locked
            and not self.in_trade
            and not self.in_market
            and self.equipped_to is None
        )

    @property
    def is_fusible(self) -> bool:
        """Must be +0 and fully available."""
        return self.enhancement == 0 and self.is_available

    def effective_main_stat(self) -> float:
        from config.game_config import ENHANCEMENT_MULTIPLIER
        multiplier = ENHANCEMENT_MULTIPLIER.get(self.enhancement, 0.0)
        return self.main_stat_base * (1 + multiplier)
