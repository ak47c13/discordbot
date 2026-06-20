"""
Migration: wipe and reseed all dungeon floors.
Run after changes to dungeon_seed.py (hazards, enemy counts, etc.).
Player progress (highest_floor, checkpoints) is preserved.
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from database.connection import init_db
from data.dungeon_seed import seed_dungeons


async def main():
    await init_db()
    print("Force-reseeding all dungeons...")
    ran = await seed_dungeons(force=True)
    if ran:
        print("Done. All dungeon floors reseeded.")
    else:
        print("Seed did not run (already up to date or force flag missing).")


if __name__ == "__main__":
    asyncio.run(main())
