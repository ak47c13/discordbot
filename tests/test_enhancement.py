import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models.item import ItemInstance
from models.user import User
from services.blacksmith_service import enhance_item, clear_item, BlacksmithError
from config.game_config import ITEM_BASE_MAIN_STAT, ENHANCEMENT_SAFE_MAX


def make_session():
    s = MagicMock()
    s.__aenter__ = AsyncMock(return_value=s)
    s.__aexit__ = AsyncMock(return_value=False)
    return s


async def _make_item(owner_id: str, enhancement: int = 0, rank: str = "B") -> ItemInstance:
    itm = ItemInstance(
        owner_id=owner_id,
        name="Infinity Edge",
        rank=rank,
        enhancement=enhancement,
        main_stat_type="atk",
        main_stat_base=ITEM_BASE_MAIN_STAT[rank],
        passive_name="crit_damage_passive",
        secondary_stat_type="crit_chance",
        secondary_stat_value=50,
    )
    await itm.insert()
    return itm


@pytest.mark.asyncio
async def test_safe_enhancement_success(user_a):
    itm = await _make_item("user_a", enhancement=3)
    session = make_session()

    with patch("services.blacksmith_service.random.random", return_value=0.01):  # Always success
        result = await enhance_item("user_a", str(itm.id), False, session)

    assert result["success"] is True
    assert result["destroyed"] is False
    assert result["new_level"] == 4


@pytest.mark.asyncio
async def test_safe_enhancement_failure_no_destroy(user_a):
    itm = await _make_item("user_a", enhancement=5)
    session = make_session()

    with patch("services.blacksmith_service.random.random", return_value=0.99):  # Always fail
        result = await enhance_item("user_a", str(itm.id), False, session)

    assert result["success"] is False
    assert result["destroyed"] is False   # Safe range — no destruction
    # Item should still exist
    still_exists = await ItemInstance.get(itm.id)
    assert still_exists is not None


@pytest.mark.asyncio
async def test_risky_enhancement_failure_destroys_item(user_a):
    itm = await _make_item("user_a", enhancement=8)
    session = make_session()

    with patch("services.blacksmith_service.random.random", return_value=0.99):  # Always fail
        result = await enhance_item("user_a", str(itm.id), False, session)

    assert result["success"] is False
    assert result["destroyed"] is True
    # Item should be deleted
    gone = await ItemInstance.get(itm.id)
    assert gone is None


@pytest.mark.asyncio
async def test_risky_enhancement_failure_with_seal_survives(user_a):
    user_a.blacksmith_seals = 1
    await user_a.save()
    itm = await _make_item("user_a", enhancement=10)
    session = make_session()

    with patch("services.blacksmith_service.random.random", return_value=0.99):  # Always fail
        result = await enhance_item("user_a", str(itm.id), True, session)

    assert result["destroyed"] is False
    assert result["seal_used"] is True
    # Item should still exist at same level
    still = await ItemInstance.get(itm.id)
    assert still is not None
    assert still.enhancement == 10


@pytest.mark.asyncio
async def test_seal_consumed_on_success(user_a):
    user_a.blacksmith_seals = 1
    await user_a.save()
    itm = await _make_item("user_a", enhancement=9)
    session = make_session()

    with patch("services.blacksmith_service.random.random", return_value=0.01):  # Always success
        result = await enhance_item("user_a", str(itm.id), True, session)

    assert result["success"] is True
    assert result["seal_used"] is True
    updated_user = await User.find_one(User.discord_id == "user_a")
    assert updated_user.blacksmith_seals == 0   # Consumed even on success


@pytest.mark.asyncio
async def test_seal_consumed_on_failure(user_a):
    user_a.blacksmith_seals = 2
    await user_a.save()
    itm = await _make_item("user_a", enhancement=11)
    session = make_session()

    with patch("services.blacksmith_service.random.random", return_value=0.99):  # Always fail
        result = await enhance_item("user_a", str(itm.id), True, session)

    assert result["destroyed"] is False
    assert result["seal_used"] is True
    updated_user = await User.find_one(User.discord_id == "user_a")
    assert updated_user.blacksmith_seals == 1   # Only 1 consumed


@pytest.mark.asyncio
async def test_enhancement_costs_gold(user_a):
    before = user_a.gold
    itm = await _make_item("user_a", enhancement=0)
    session = make_session()

    with patch("services.blacksmith_service.random.random", return_value=0.01):
        await enhance_item("user_a", str(itm.id), False, session)

    updated = await User.find_one(User.discord_id == "user_a")
    assert updated.gold < before


@pytest.mark.asyncio
async def test_enhancement_fails_no_gold():
    broke = User(discord_id="broke", username="Broke", gold=0)
    await broke.insert()
    itm = await _make_item("broke", enhancement=0)
    session = make_session()

    with pytest.raises(BlacksmithError, match="gold"):
        await enhance_item("broke", str(itm.id), False, session)


@pytest.mark.asyncio
async def test_cannot_enhance_market_listed_item(user_a):
    itm = await _make_item("user_a", enhancement=2)
    itm.in_market = True
    await itm.save()
    session = make_session()

    with pytest.raises(BlacksmithError, match="listed"):
        await enhance_item("user_a", str(itm.id), False, session)


@pytest.mark.asyncio
async def test_clear_resets_to_zero(user_a):
    itm = await _make_item("user_a", enhancement=7)
    old_sec = itm.secondary_stat_type
    old_val = itm.secondary_stat_value
    session = make_session()

    cleared = await clear_item("user_a", str(itm.id), session)

    assert cleared.enhancement == 0
    assert cleared.secondary_stat_type == old_sec   # Secondary preserved
    assert cleared.secondary_stat_value == old_val


@pytest.mark.asyncio
async def test_clear_costs_gold(user_a):
    before = user_a.gold
    itm = await _make_item("user_a", enhancement=5)
    session = make_session()

    await clear_item("user_a", str(itm.id), session)

    updated = await User.find_one(User.discord_id == "user_a")
    assert updated.gold < before


@pytest.mark.asyncio
async def test_clear_already_zero_fails(user_a):
    itm = await _make_item("user_a", enhancement=0)
    session = make_session()

    with pytest.raises(BlacksmithError, match="already at \\+0"):
        await clear_item("user_a", str(itm.id), session)
