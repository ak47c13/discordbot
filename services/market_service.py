"""
Market service: list, buy, cancel. Atomic with listing fees and taxes.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Optional

from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.market import MarketListing
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.user import User
from config.game_config import MARKET_LISTING_FEE_PCT, MARKET_TAX_PCT


class MarketError(Exception):
    pass


async def list_champion(
    seller_id: str,
    champion_id: str,
    price: int,
    session: AsyncIOMotorClientSession,
) -> MarketListing:
    if price <= 0:
        raise MarketError("Price must be positive.")

    c = await ChampionInstance.get(PydanticObjectId(champion_id), session=usable_session(session))
    if c is None or c.owner_id != seller_id:
        raise MarketError("Champion not found or not owned by you.")
    if getattr(c, "favorite", False):
        raise MarketError("Cannot list a favorited champion. Unfavorite first.")
    if not c.is_available:
        raise MarketError("Champion is equipped, locked, or already in a trade/listing.")

    fee = max(1, math.ceil(price * MARKET_LISTING_FEE_PCT))
    user = await User.find_one(User.discord_id == seller_id, session=usable_session(session))
    if user.gold < fee:
        raise MarketError(f"Need {fee} gold for listing fee.")

    user.gold -= fee
    c.in_market = True
    await user.save(session=usable_session(session))
    await c.save(session=usable_session(session))

    listing = MarketListing(
        seller_id=seller_id,
        champion_id=champion_id,
        price=price,
        listing_fee_paid=fee,
    )
    await listing.insert(session=usable_session(session))
    return listing


async def list_item(
    seller_id: str,
    item_id: str,
    price: int,
    session: AsyncIOMotorClientSession,
) -> MarketListing:
    if price <= 0:
        raise MarketError("Price must be positive.")

    itm = await ItemInstance.get(PydanticObjectId(item_id), session=usable_session(session))
    if itm is None or itm.owner_id != seller_id:
        raise MarketError("Item not found or not owned by you.")
    if getattr(itm, "favorite", False):
        raise MarketError("Cannot list a favorited item. Unfavorite first.")
    if not itm.is_available:
        raise MarketError("Item is equipped, locked, or already in a trade/listing.")

    fee = max(1, math.ceil(price * MARKET_LISTING_FEE_PCT))
    user = await User.find_one(User.discord_id == seller_id, session=usable_session(session))
    if user.gold < fee:
        raise MarketError(f"Need {fee} gold for listing fee.")

    user.gold -= fee
    itm.in_market = True
    await user.save(session=usable_session(session))
    await itm.save(session=usable_session(session))

    listing = MarketListing(
        seller_id=seller_id,
        item_id=item_id,
        price=price,
        listing_fee_paid=fee,
    )
    await listing.insert(session=usable_session(session))
    return listing


async def buy_listing(
    buyer_id: str,
    listing_id: str,
    session: AsyncIOMotorClientSession,
) -> MarketListing:
    listing = await MarketListing.get(PydanticObjectId(listing_id), session=usable_session(session))
    if listing is None:
        raise MarketError("Listing not found.")
    if listing.status != "active":
        raise MarketError("Listing is no longer available.")
    if listing.seller_id == buyer_id:
        raise MarketError("Cannot buy your own listing.")

    buyer = await User.find_one(User.discord_id == buyer_id, session=usable_session(session))
    if buyer.gold < listing.price:
        raise MarketError(f"Need {listing.price} gold. Have {buyer.gold}.")

    tax = max(1, math.ceil(listing.price * MARKET_TAX_PCT))
    seller_receives = listing.price - tax

    buyer.gold -= listing.price
    seller = await User.find_one(User.discord_id == listing.seller_id, session=usable_session(session))
    seller.gold += seller_receives

    # Transfer ownership
    if listing.champion_id:
        c = await ChampionInstance.get(PydanticObjectId(listing.champion_id), session=usable_session(session))
        c.owner_id = buyer_id
        c.in_market = False
        await c.save(session=usable_session(session))
    elif listing.item_id:
        itm = await ItemInstance.get(PydanticObjectId(listing.item_id), session=usable_session(session))
        itm.owner_id = buyer_id
        itm.in_market = False
        await itm.save(session=usable_session(session))

    await buyer.save(session=usable_session(session))
    await seller.save(session=usable_session(session))

    listing.status = "sold"
    listing.buyer_id = buyer_id
    listing.completed_at = datetime.now(timezone.utc)
    await listing.save(session=usable_session(session))
    return listing


async def cancel_listing(
    seller_id: str,
    listing_id: str,
    session: AsyncIOMotorClientSession,
) -> MarketListing:
    listing = await MarketListing.get(PydanticObjectId(listing_id), session=usable_session(session))
    if listing is None:
        raise MarketError("Listing not found.")
    if listing.seller_id != seller_id:
        raise MarketError("Not your listing.")
    if listing.status != "active":
        raise MarketError(f"Listing is already {listing.status}.")

    if listing.champion_id:
        c = await ChampionInstance.get(PydanticObjectId(listing.champion_id), session=usable_session(session))
        if c:
            c.in_market = False
            await c.save(session=usable_session(session))
    elif listing.item_id:
        itm = await ItemInstance.get(PydanticObjectId(listing.item_id), session=usable_session(session))
        if itm:
            itm.in_market = False
            await itm.save(session=usable_session(session))

    listing.status = "cancelled"
    await listing.save(session=usable_session(session))
    # Note: listing fee is NOT refunded per rules
    return listing
