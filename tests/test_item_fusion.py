import pytest
from unittest.mock import AsyncMock, MagicMock

from models.item import ItemInstance
from models.user import User
from services.item_service import fuse_items, ItemFusionError
from config.game_config import ITEM_BASE_MAIN_STAT


def make_session():
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=False)
    return s


async def _make_item(owner_id: str, name: str = "Infinity Edge", rank: str = "F", enhancement: int = 0) -> ItemInstance:
    itm = ItemInstance(
        owner_id=owner_id,
        name=name,
        rank=rank,
        enhancement=enhancement,
        main_stat_type="atk",
        main_stat_base=ITEM_BASE_MAIN_STAT[rank],
        passive_name="crit_damage_passive",
        secondary_stat_type="crit_chance",
        secondary_stat_value=20,
    )
    await itm.insert()
    return itm


@pytest.mark.asyncio
async def test_item_fusion_creates_next_rank(user_a):
    items = [await _make_item("user_a") for _ in range(3)]
    session = make_session()
    result = await fuse_items("user_a", [str(i.id) for i in items], session)
    assert result.rank == "E"
    assert result.enhancement == 0
    assert result.name == "Infinity Edge"


@pytest.mark.asyncio
async def test_item_fusion_requires_plus_zero(user_a):
    items = [await _make_item("user_a") for _ in range(3)]
    items[0].enhancement = 3
    await items[0].save()

    session = make_session()
    with pytest.raises(ItemFusionError, match="\\+0"):
        await fuse_items("user_a", [str(i.id) for i in items], session)


@pytest.mark.asyncio
async def test_item_fusion_requires_same_name(user_a):
    i1 = await _make_item("user_a", name="Infinity Edge")
    i2 = await _make_item("user_a", name="Chain Vest")
    i3 = await _make_item("user_a", name="Ruby Crystal")

    session = make_session()
    with pytest.raises(ItemFusionError, match="same name"):
        await fuse_items("user_a", [str(i1.id), str(i2.id), str(i3.id)], session)


@pytest.mark.asyncio
async def test_item_fusion_requires_same_rank(user_a):
    i1 = await _make_item("user_a", rank="F")
    i2 = await _make_item("user_a", rank="E")
    i3 = await _make_item("user_a", rank="F")

    session = make_session()
    with pytest.raises(ItemFusionError, match="same rank"):
        await fuse_items("user_a", [str(i1.id), str(i2.id), str(i3.id)], session)


@pytest.mark.asyncio
async def test_item_fusion_cannot_use_duplicate_id(user_a):
    itm = await _make_item("user_a")
    session = make_session()
    with pytest.raises(ItemFusionError, match="same item twice"):
        await fuse_items("user_a", [str(itm.id), str(itm.id), str(itm.id)], session)


@pytest.mark.asyncio
async def test_item_fusion_blocked_if_equipped(user_a):
    items = [await _make_item("user_a") for _ in range(3)]
    items[0].equipped_to = "some_champ_id"
    await items[0].save()

    session = make_session()
    with pytest.raises(ItemFusionError, match="equipped"):
        await fuse_items("user_a", [str(i.id) for i in items], session)


@pytest.mark.asyncio
async def test_item_fusion_blocked_if_s_rank(user_a):
    items = [await _make_item("user_a", rank="S") for _ in range(3)]
    session = make_session()
    with pytest.raises(ItemFusionError, match="S-rank"):
        await fuse_items("user_a", [str(i.id) for i in items], session)


@pytest.mark.asyncio
async def test_item_fusion_new_secondary_stat(user_a):
    items = [await _make_item("user_a") for _ in range(3)]
    old_stat_type = items[0].secondary_stat_type
    session = make_session()
    result = await fuse_items("user_a", [str(i.id) for i in items], session)
    # New roll — just check it's a valid stat type
    from config.game_config import SECONDARY_STAT_TYPES
    assert result.secondary_stat_type in SECONDARY_STAT_TYPES
