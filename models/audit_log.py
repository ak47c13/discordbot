from datetime import datetime, timezone
from typing import Any, Optional
from beanie import Document
from pydantic import Field


class AuditLog(Document):
    event_type: str          # S_CHAMPION_CREATED, ITEM_DESTROYED, etc.
    actor_id: str            # discord_id of player
    target_id: Optional[str] = None   # affected item/champion id
    details: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "audit_logs"
        indexes = ["actor_id", "event_type", "created_at"]

    @classmethod
    async def log(
        cls,
        event_type: str,
        actor_id: str,
        target_id: Optional[str] = None,
        **details: Any,
    ) -> None:
        entry = cls(
            event_type=event_type,
            actor_id=actor_id,
            target_id=target_id,
            details=details,
        )
        await entry.insert()
