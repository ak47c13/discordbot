"""
Bulk sell operations for champions and items.

Selling converts owned champions/items into gold. Locked and favorited assets are
never sold. Equipped / market-listed / in-trade assets are excluded by default.
"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.champion import ChampionInstance
from models.item import ItemInstance
from models.user import User
from config.game_config import SELL_PRICE_CHAMPION, SELL_PRICE_ITEM


class BulkSellError(Exception):
    pass


_DEFAULT_FILTERS = {
    "rank": None,
    "name": None,
    "min_enhance": None,
    "max_enhance": None,
    "exclude_locked": True,
    "exclude_favorite": True,
    "exclude_equipped": True,
}


def _merge_filters(filters: dict | None) -> dict:
    f = dict(_DEFAULT_FILTERS)
    if filters:
        f.update(filters)
    return f


async def bulk_sell_champions(
    owner_id: str,
    filters: dict,
    session: AsyncIOMotorClientSession,
) -> dict:
    """Sell matching champions for gold. Returns {sold: int, gold: int, ids: [...]}."""
    f = _merge_filters(filters)

    candidates = await ChampionInstance.find(
        ChampionInstance.owner_id == owner_id,
        session=usable_session(session),
    ).to_list()

    to_sell = []
    for c in candidates:
        if f["rank"] is not None and c.rank != f["rank"]:
            continue
        if f["name"] is not None and c.name != f["name"]:
            continue
        # Never sell locked or favorited, regardless of flags.
        if c.locked or getattr(c, "favorite", False):
            continue
        if c.in_trade or c.in_market:
            continue
        if f["exclude_equipped"] and getattr(c, "is_active", False):
            continue
        to_sell.append(c)

    total_gold = 0
    sold_ids = []
    for c in to_sell:
        total_gold += SELL_PRICE_CHAMPION.get(c.rank, 0)
        sold_ids.append(str(c.id))
        await c.delete(session=usable_session(session))

    if sold_ids:
        user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
        user.gold += total_gold
        await user.save(session=usable_session(session))

    return {"sold": len(sold_ids), "gold": total_gold, "ids": sold_ids}


async def bulk_sell_items(
    owner_id: str,
    filters: dict,
    session: AsyncIOMotorClientSession,
) -> dict:
    """Sell matching items for gold. Returns {sold: int, gold: int, ids: [...]}."""
    f = _merge_filters(filters)

    candidates = await ItemInstance.find(
        ItemInstance.owner_id == owner_id,
        session=usable_session(session),
    ).to_list()

    to_sell = []
    for itm in candidates:
        if f["rank"] is not None and itm.rank != f["rank"]:
            continue
        if f["name"] is not None and itm.name != f["name"]:
            continue
        if itm.locked or getattr(itm, "favorite", False):
            continue
        if itm.in_trade or itm.in_market:
            continue
        if f["exclude_equipped"] and itm.equipped_to is not None:
            continue
        if f["min_enhance"] is not None and itm.enhancement < f["min_enhance"]:
            continue
        if f["max_enhance"] is not None and itm.enhancement > f["max_enhance"]:
            continue
        to_sell.append(itm)

    total_gold = 0
    sold_ids = []
    for itm in to_sell:
        total_gold += SELL_PRICE_ITEM.get(itm.rank, 0)
        sold_ids.append(str(itm.id))
        await itm.delete(session=usable_session(session))

    if sold_ids:
        user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
        user.gold += total_gold
        await user.save(session=usable_session(session))

    return {"sold": len(sold_ids), "gold": total_gold, "ids": sold_ids}
