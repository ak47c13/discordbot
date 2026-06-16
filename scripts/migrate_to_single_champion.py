"""One-time migration: initialize active_champion_id and rune_page for all users."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import init_db
from models.user import User
from models.champion import ChampionInstance
from models.rune_page import RunePage


async def migrate():
    await init_db()
    users = await User.find_all().to_list()
    migrated = 0
    for user in users:
        changed = False
        if not user.active_champion_id:
            champs = await ChampionInstance.find(ChampionInstance.owner_id == user.discord_id).to_list()
            if champs:
                best = champs[0]
                user.active_champion_id = str(best.id)
                user.active_skill = "q"
                best.is_active = True
                await best.save()
                changed = True
        if user.rune_page is None:
            user.rune_page = RunePage()
            changed = True
        if changed:
            await user.save()
            migrated += 1
    print(f"Migrated {migrated}/{len(users)} users.")


if __name__ == "__main__":
    asyncio.run(migrate())
