"""
One-time migration: assign stable numeric display_id to all existing items
that don't have one yet. IDs are assigned in created_at order (oldest gets #1).
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from database.connection import init_db
from models.item import ItemInstance


async def migrate():
    await init_db()

    items = await ItemInstance.find(
        {"$or": [{"display_id": {"$exists": False}}, {"display_id": 0}]}
    ).sort("created_at").to_list()

    if not items:
        print("All items already have display IDs.")
        return

    from utils.db_session import get_motor_client
    client = get_motor_client()
    db = client.get_default_database()

    existing_max = await ItemInstance.find(
        ItemInstance.display_id > 0
    ).sort("-display_id").first_or_none()
    start_seq = existing_max.display_id if existing_max else 0

    print(f"Backfilling {len(items)} items starting from ID {start_seq + 1}...")

    for i, itm in enumerate(items, start=start_seq + 1):
        itm.display_id = i
        await itm.save()
        if i % 100 == 0:
            print(f"  {i} done...")

    final_seq = start_seq + len(items)
    await db["counters"].update_one(
        {"_id": "item_display_id"},
        {"$set": {"seq": final_seq}},
        upsert=True,
    )

    print(f"Done. {len(items)} items assigned IDs {start_seq + 1}–{final_seq}.")


if __name__ == "__main__":
    asyncio.run(migrate())
