"""
Remove champions that are not in the official LoL roster (Maeve, Calix) from
all users' inventories. If the removed champion was the user's active champion,
the active_champion_id is cleared so the user can pick a new one.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import init_db
from models.user import User
from models.champion import ChampionInstance

INVALID_NAMES = {"Maeve", "Calix"}


async def migrate():
    await init_db()

    to_delete = await ChampionInstance.find(
        {"name": {"$in": list(INVALID_NAMES)}}
    ).to_list()

    if not to_delete:
        print("No invalid champions found in database.")
        return

    affected_owners = {c.owner_id for c in to_delete}
    print(f"Found {len(to_delete)} invalid champion(s) across {len(affected_owners)} user(s).")

    deleted = 0
    cleared_active = 0

    for champ in to_delete:
        print(f"  Deleting {champ.name} [{champ.rank}] owned by {champ.owner_id}")

        # If this was the user's active champion, clear the reference
        user = await User.find_one(User.discord_id == champ.owner_id)
        if user and user.active_champion_id == str(champ.id):
            user.active_champion_id = None
            await user.save()
            cleared_active += 1
            print(f"    → Cleared active_champion_id for user {champ.owner_id}")

        await champ.delete()
        deleted += 1

    print(f"\nDone. Deleted {deleted} champion(s), cleared active slot for {cleared_active} user(s).")


if __name__ == "__main__":
    asyncio.run(migrate())
