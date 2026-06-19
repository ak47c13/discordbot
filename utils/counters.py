"""MongoDB atomic counter for stable display IDs."""
from __future__ import annotations
from motor.motor_asyncio import AsyncIOMotorClient
from utils.db_session import get_motor_client


async def next_display_id(counter_name: str) -> int:
    """Atomically increment and return the next value for the named counter."""
    try:
        client: AsyncIOMotorClient = get_motor_client()
        if client is None:
            return 0
        db = client.get_default_database()
        result = await db["counters"].find_one_and_update(
            {"_id": counter_name},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        return result["seq"]
    except Exception:
        return 0
