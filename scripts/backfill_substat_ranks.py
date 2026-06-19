"""
Migration: assign a 'rank' field to existing substats that don't have one.
Rank is inferred from the stored value using SUBSTAT_STAT_RANGE boundaries.
"""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from database.connection import init_db
from models.item import ItemInstance
from config.game_config import SUBSTAT_STAT_RANGE

RANK_ORDER = ["F", "E", "D", "C", "B", "A", "S"]


def infer_rank(value: int) -> str:
    """Best-fit rank for a substat value based on range boundaries."""
    best = "F"
    for rank in RANK_ORDER:
        lo, hi = SUBSTAT_STAT_RANGE[rank]
        if lo <= value <= hi:
            return rank
        if value >= lo:
            best = rank
    return best


async def migrate():
    await init_db()

    items = await ItemInstance.find().to_list()
    updated = 0

    for itm in items:
        substats = getattr(itm, "substats", [])
        if not substats:
            continue
        changed = False
        for s in substats:
            if "rank" not in s:
                s["rank"] = infer_rank(s.get("value", 5))
                changed = True
        if changed:
            itm.substats = substats
            await itm.save()
            updated += 1
        if updated % 100 == 0 and updated > 0:
            print(f"  {updated} items updated...")

    print(f"Done. {updated} items backfilled with substat ranks.")


if __name__ == "__main__":
    asyncio.run(migrate())
