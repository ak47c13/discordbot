"""
One-time migration: assign stable numeric display_id to all existing champions
that don't have one yet. IDs are assigned in created_at order (oldest gets #1).
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from database.connection import init_db
from models.champion import ChampionInstance


async def migrate():
    await init_db()

    # Find champions where display_id is missing or 0 (raw query covers both cases)
    champs = await ChampionInstance.find(
        {"$or": [{"display_id": {"$exists": False}}, {"display_id": 0}]}
    ).sort("created_at").to_list()

    if not champs:
        print("All champions already have display IDs.")
        return

    from utils.db_session import get_motor_client
    client = get_motor_client()
    db = client.get_default_database()

    # Seed the counter to the current max display_id so new summons don't collide
    existing_max = await ChampionInstance.find(
        ChampionInstance.display_id > 0
    ).sort("-display_id").first_or_none()
    start_seq = (existing_max.display_id if existing_max else 0)

    print(f"Backfilling {len(champs)} champions starting from ID {start_seq + 1}...")

    for i, champ in enumerate(champs, start=start_seq + 1):
        champ.display_id = i
        await champ.save()
        if i % 100 == 0:
            print(f"  {i} done...")

    # Update the counter so next_display_id() continues from the right value
    final_seq = start_seq + len(champs)
    await db["counters"].update_one(
        {"_id": "champion_display_id"},
        {"$set": {"seq": final_seq}},
        upsert=True,
    )

    print(f"Done. {len(champs)} champions assigned IDs {start_seq + 1}–{final_seq}.")


if __name__ == "__main__":
    asyncio.run(migrate())
