from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field


class RuneInstance(Document):
    owner_id: str
    rune_id: str          # key in RUNE_CATALOG
    rank: str = "F"       # F/E/D/C/B/A/S — quality tier
    display_id: int = 0
    is_equipped: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "rune_instances"
        indexes = ["owner_id", "display_id"]
