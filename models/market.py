from datetime import datetime, timezone
from typing import Optional
from beanie import Document
from pydantic import Field


class MarketListing(Document):
    seller_id: str
    # Exactly one of these is set
    champion_id: Optional[str] = None
    item_id: Optional[str] = None

    price: int                         # asking price in gold
    listing_fee_paid: int = 0          # 2% of price, non-refundable

    # "active" | "sold" | "cancelled"
    status: str = "active"
    buyer_id: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    class Settings:
        name = "market_listings"
        indexes = ["seller_id", "status", "champion_id", "item_id"]
