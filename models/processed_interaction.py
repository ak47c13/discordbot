from datetime import datetime, timezone
from typing import Any, Optional
from beanie import Document
from pydantic import Field


class ProcessedInteraction(Document):
    interaction_id: str
    result_summary: Optional[str] = None    # short text for duplicate-reply
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "processedinteractions"
        indexes = ["interaction_id"]
