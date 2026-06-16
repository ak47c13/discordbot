"""Tests for bulk fusion/sell, favorite guards, and formation bonuses."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from models.champion import ChampionInstance
from models.item import ItemInstance
from models.user import User
from services.champion_service import bulk_fuse_champions, FusionError
from services.item_service import bulk_fuse_items, ItemFusionError
from services.bulk_service import bulk_sell_champions, bulk_sell_items
from services.market_service import list_champion, MarketError
from engine.combat import build_unit_from_champion


def make_mock_session():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


async def _make_champs(name, rank, n, **kw):
    out = []
    for _ in range(n):
        c = ChampionInstance(owner_id="user_a", name=name, rank=rank, level=1, **kw)
        await c.insert()
        out.append(c)
    return out


async def _make_items(name, rank, n, **kw):
    out = []
    for _ in range(n):
        itm = ItemInstance(
            owner_id="user_a", name=name, rank=rank, enhancement=0,
            main_stat_type="atk", main_stat_base=20, passive_name="p",
            secondary_stat_type="atk_pct", secondary_stat_value=20, **kw,
        )
        await itm.insert()
        out.append(itm)
    return out


@pytest.mark.asyncio
async def test_bulk_fuse_champions_basic(user_a):
    await _make_champs("Rengar", "F", 6)
    session = make_mock_session()
    created = await bulk_fuse_champions("user_a", "Rengar", "F", 6, session)
    assert len(created) == 2
    assert all(c.rank == "E" for c in created)
    remaining_f = await ChampionInstance.find(
        ChampionInstance.owner_id == "user_a",
        ChampionInstance.name == "Rengar",
        ChampionInstance.rank == "F",
    ).to_list()
    assert len(remaining_f) == 0


@pytest.mark.asyncio
async def test_bulk_fuse_requires_multiple_of_3(user_a):
    await _make_champs("Jinx", "F", 4)
    session = make_mock_session()
    with pytest.raises(FusionError):
        await bulk_fuse_champions("user_a", "Jinx", "F", 4, session)


@pytest.mark.asyncio
async def test_bulk_fuse_skips_locked_champions(user_a):
    await _make_champs("Leona", "F", 3)
    await _make_champs("Leona", "F", 1, locked=True)
    session = make_mock_session()
    created = await bulk_fuse_champions("user_a", "Leona", "F", 3, session)
    assert len(created) == 1
    # the locked one survives
    leftover = await ChampionInstance.find(
        ChampionInstance.owner_id == "user_a",
        ChampionInstance.name == "Leona",
        ChampionInstance.rank == "F",
    ).to_list()
    assert len(leftover) == 1
    assert leftover[0].locked


@pytest.mark.asyncio
async def test_bulk_fuse_skips_favorite_champions(user_a):
    await _make_champs("Darius", "F", 3)
    await _make_champs("Darius", "F", 2, favorite=True)
    session = make_mock_session()
    created = await bulk_fuse_champions("user_a", "Darius", "F", 3, session)
    assert len(created) == 1
    leftover = await ChampionInstance.find(
        ChampionInstance.owner_id == "user_a",
        ChampionInstance.name == "Darius",
        ChampionInstance.rank == "F",
    ).to_list()
    assert all(c.favorite for c in leftover)
    assert len(leftover) == 2


@pytest.mark.asyncio
async def test_bulk_sell_champions_skips_locked(user_a):
    await _make_champs("Lux", "F", 3)
    await _make_champs("Lux", "F", 1, locked=True)
    session = make_mock_session()
    res = await bulk_sell_champions("user_a", {"rank": "F", "name": "Lux"}, session)
    assert res["sold"] == 3
    leftover = await ChampionInstance.find(ChampionInstance.owner_id == "user_a").to_list()
    assert len(leftover) == 1 and leftover[0].locked


@pytest.mark.asyncio
async def test_bulk_sell_champions_skips_favorite(user_a):
    await _make_champs("Thresh", "F", 2)
    await _make_champs("Thresh", "F", 2, favorite=True)
    session = make_mock_session()
    res = await bulk_sell_champions("user_a", {"rank": "F", "name": "Thresh"}, session)
    assert res["sold"] == 2
    leftover = await ChampionInstance.find(ChampionInstance.owner_id == "user_a").to_list()
    assert len(leftover) == 2 and all(c.favorite for c in leftover)


@pytest.mark.asyncio
async def test_bulk_fuse_items_basic(user_a):
    await _make_items("Infinity Edge", "F", 6)
    session = make_mock_session()
    created = await bulk_fuse_items("user_a", "Infinity Edge", "F", 6, session)
    assert len(created) == 2
    assert all(i.rank == "E" for i in created)


@pytest.mark.asyncio
async def test_favorite_prevents_market_listing(user_a):
    c = ChampionInstance(owner_id="user_a", name="Yasuo", rank="F", level=1, favorite=True)
    await c.insert()
    session = make_mock_session()
    with pytest.raises(MarketError):
        await list_champion("user_a", str(c.id), 100, session)


def test_unit_builds_with_active_skill():
    champ = ChampionInstance(owner_id="user_a", name="Garen", rank="F", level=1)
    unit_q = build_unit_from_champion(champ, [], position=1, team=0, active_skill_key="q")
    unit_w = build_unit_from_champion(champ, [], position=1, team=0, active_skill_key="w")
    # Both should produce valid units with callable skills
    assert unit_q.basic_fn is not None
    assert unit_w.basic_fn is not None
    # Different skills should be distinct functions
    assert unit_q.basic_fn is not unit_w.basic_fn
