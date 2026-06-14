import pytest
from unittest.mock import AsyncMock, MagicMock

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.market import MarketListing
from services.market_service import list_item, buy_listing, cancel_listing, MarketError
from config.game_config import ITEM_BASE_MAIN_STAT, MARKET_LISTING_FEE_PCT, MARKET_TAX_PCT
import math


def make_session():
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=False)
    return s


async def _make_item(owner_id: str, rank: str = "C") -> ItemInstance:
    itm = ItemInstance(
        owner_id=owner_id,
        name="Infinity Edge",
        rank=rank,
        enhancement=0,
        main_stat_type="atk",
        main_stat_base=ITEM_BASE_MAIN_STAT[rank],
        passive_name="crit_damage_passive",
        secondary_stat_type="boss_dmg",
        secondary_stat_value=80,
    )
    await itm.insert()
    return itm


@pytest.mark.asyncio
async def test_market_listing_deducts_fee(user_a):
    before = user_a.gold
    itm = await _make_item("user_a")
    price = 1000
    fee = max(1, math.ceil(price * MARKET_LISTING_FEE_PCT))

    session = make_session()
    await list_item("user_a", str(itm.id), price, session)

    updated = await User.find_one(User.discord_id == "user_a")
    assert updated.gold == before - fee


@pytest.mark.asyncio
async def test_market_buy_transfers_ownership(user_a, user_b):
    itm = await _make_item("user_a")
    price = 500
    session = make_session()
    listing = await list_item("user_a", str(itm.id), price, session)

    await buy_listing("user_b", str(listing.id), session)

    updated_item = await ItemInstance.get(itm.id)
    assert updated_item.owner_id == "user_b"
    assert updated_item.in_market is False


@pytest.mark.asyncio
async def test_market_buy_deducts_buyer_gold(user_a, user_b):
    before_b = user_b.gold
    itm = await _make_item("user_a")
    price = 300
    session = make_session()
    listing = await list_item("user_a", str(itm.id), price, session)

    await buy_listing("user_b", str(listing.id), session)

    updated_b = await User.find_one(User.discord_id == "user_b")
    assert updated_b.gold == before_b - price


@pytest.mark.asyncio
async def test_market_buy_seller_receives_minus_tax(user_a, user_b):
    before_a = user_a.gold
    fee = max(1, math.ceil(500 * MARKET_LISTING_FEE_PCT))
    itm = await _make_item("user_a")
    price = 500
    session = make_session()
    listing = await list_item("user_a", str(itm.id), price, session)

    # user_a paid fee already
    after_listing = await User.find_one(User.discord_id == "user_a")
    gold_after_fee = after_listing.gold

    await buy_listing("user_b", str(listing.id), session)

    tax = max(1, math.ceil(price * MARKET_TAX_PCT))
    updated_a = await User.find_one(User.discord_id == "user_a")
    assert updated_a.gold == gold_after_fee + price - tax


@pytest.mark.asyncio
async def test_cannot_buy_own_listing(user_a):
    itm = await _make_item("user_a")
    session = make_session()
    listing = await list_item("user_a", str(itm.id), 200, session)

    with pytest.raises(MarketError, match="own listing"):
        await buy_listing("user_a", str(listing.id), session)


@pytest.mark.asyncio
async def test_cannot_list_equipped_item(user_a):
    itm = await _make_item("user_a")
    itm.equipped_to = "some_champion"
    await itm.save()

    session = make_session()
    with pytest.raises(MarketError, match="equipped"):
        await list_item("user_a", str(itm.id), 100, session)


@pytest.mark.asyncio
async def test_cancel_listing_restores_item_availability(user_a):
    itm = await _make_item("user_a")
    session = make_session()
    listing = await list_item("user_a", str(itm.id), 100, session)

    await cancel_listing("user_a", str(listing.id), session)

    updated_item = await ItemInstance.get(itm.id)
    assert updated_item.in_market is False


@pytest.mark.asyncio
async def test_cannot_buy_cancelled_listing(user_a, user_b):
    itm = await _make_item("user_a")
    session = make_session()
    listing = await list_item("user_a", str(itm.id), 100, session)
    await cancel_listing("user_a", str(listing.id), session)

    with pytest.raises(MarketError, match="no longer available"):
        await buy_listing("user_b", str(listing.id), session)
