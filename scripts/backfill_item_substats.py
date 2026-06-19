"""
One-time migration: roll substats for all existing items that have none.
Count by rank: F-D=1, C-B=2, A=3, S=4
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
        {"$or": [{"substats": {"$exists": False}}, {"substats": {"$size": 0}}]}
    ).to_list()

    if not items:
        print("All items already have substats.")
        return

    from services.item_service import _roll_substats

    print(f"Backfilling substats for {len(items)} items...")
    for i, itm in enumerate(items, start=1):
        itm.substats = _roll_substats(itm.rank)
        await itm.save()
        if i % 100 == 0:
            print(f"  {i} done...")

    print(f"Done. {len(items)} items updated.")


if __name__ == "__main__":
    asyncio.run(migrate())
