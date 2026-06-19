"""
Migration: remove RuneInstance documents whose rune_id is no longer in RUNE_CATALOG.
Also unequips them from any rune_page slot that references them.
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from database.connection import init_db
from models.rune_instance import RuneInstance
from models.user import User
from data.rune_catalog import RUNE_CATALOG

VALID_RUNE_IDS = set(RUNE_CATALOG.keys())


async def migrate():
    await init_db()

    all_runes = await RuneInstance.find().to_list()
    invalid = [r for r in all_runes if r.rune_id not in VALID_RUNE_IDS]

    if not invalid:
        print("No phased-out runes found.")
        return

    print(f"Found {len(invalid)} phased-out rune instance(s):")
    for r in invalid:
        print(f"  id={r.id}  owner={r.owner_id}  rune_id={r.rune_id}  rank={r.rank}  equipped={r.is_equipped}")

    # Unequip from rune pages first
    invalid_instance_ids = {str(r.id) for r in invalid}
    users_to_fix = set(r.owner_id for r in invalid if r.is_equipped)
    for uid in users_to_fix:
        user = await User.find_one(User.discord_id == uid)
        if not user:
            continue
        rp = user.rune_page
        changed = False
        from models.rune_page import RuneSlot
        for attr in ("reds", "yellows", "blues", "quints"):
            slots = getattr(rp, attr)
            for i, slot in enumerate(slots):
                if slot.instance_id in invalid_instance_ids:
                    slots[i] = RuneSlot()
                    changed = True
        if changed:
            await user.save()
            print(f"  Cleared rune_page slots for user {uid}")

    # Delete the invalid rune instances
    for r in invalid:
        await r.delete()

    print(f"Done. {len(invalid)} rune instance(s) removed.")


if __name__ == "__main__":
    asyncio.run(migrate())
