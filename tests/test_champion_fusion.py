import pytest
from unittest.mock import AsyncMock, MagicMock

from models.champion import ChampionInstance
from models.user import User
from services.champion_service import fuse_champions, FusionError


def make_mock_session():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_fusion_creates_next_rank(user_a):
    champs = []
    for _ in range(3):
        c = ChampionInstance(owner_id="user_a", name="Rengar", rank="F", level=5)
        await c.insert()
        champs.append(c)

    session = make_mock_session()
    result = await fuse_champions("user_a", [str(c.id) for c in champs], session)

    assert result.name == "Rengar"
    assert result.rank == "E"
    assert result.level == 1  # resets to level 1


@pytest.mark.asyncio
async def test_fusion_deducts_gold(user_a):
    before = user_a.gold
    champs = []
    for _ in range(3):
        c = ChampionInstance(owner_id="user_a", name="Leona", rank="F", level=1)
        await c.insert()
        champs.append(c)

    session = make_mock_session()
    await fuse_champions("user_a", [str(c.id) for c in champs], session)

    updated = await User.find_one(User.discord_id == "user_a")
    assert updated.gold < before


@pytest.mark.asyncio
async def test_fusion_consumes_source_champions(user_a):
    champs = []
    for _ in range(3):
        c = ChampionInstance(owner_id="user_a", name="Jinx", rank="E", level=1)
        await c.insert()
        champs.append(c)

    session = make_mock_session()
    await fuse_champions("user_a", [str(c.id) for c in champs], session)

    for c in champs:
        found = await ChampionInstance.get(c.id)
        assert found is None


@pytest.mark.asyncio
async def test_fusion_requires_same_name(user_a):
    c1 = ChampionInstance(owner_id="user_a", name="Rengar", rank="F")
    c2 = ChampionInstance(owner_id="user_a", name="Leona",  rank="F")
    c3 = ChampionInstance(owner_id="user_a", name="Jinx",   rank="F")
    for c in [c1, c2, c3]:
        await c.insert()

    session = make_mock_session()
    with pytest.raises(FusionError, match="same name"):
        await fuse_champions("user_a", [str(c1.id), str(c2.id), str(c3.id)], session)


@pytest.mark.asyncio
async def test_fusion_requires_same_rank(user_a):
    c1 = ChampionInstance(owner_id="user_a", name="Rengar", rank="F")
    c2 = ChampionInstance(owner_id="user_a", name="Rengar", rank="E")
    c3 = ChampionInstance(owner_id="user_a", name="Rengar", rank="F")
    for c in [c1, c2, c3]:
        await c.insert()

    session = make_mock_session()
    with pytest.raises(FusionError, match="same rank"):
        await fuse_champions("user_a", [str(c1.id), str(c2.id), str(c3.id)], session)


@pytest.mark.asyncio
async def test_fusion_cannot_use_duplicate_id(user_a):
    c = ChampionInstance(owner_id="user_a", name="Rengar", rank="F")
    await c.insert()

    session = make_mock_session()
    with pytest.raises(FusionError, match="same champion twice"):
        await fuse_champions("user_a", [str(c.id), str(c.id), str(c.id)], session)


@pytest.mark.asyncio
async def test_fusion_cannot_fuse_s_rank(user_a):
    champs = []
    for _ in range(3):
        c = ChampionInstance(owner_id="user_a", name="Rengar", rank="S")
        await c.insert()
        champs.append(c)

    session = make_mock_session()
    with pytest.raises(FusionError, match="S-rank"):
        await fuse_champions("user_a", [str(c.id) for c in champs], session)


@pytest.mark.asyncio
async def test_fusion_blocked_if_insufficient_gold():
    poor_user = User(discord_id="poor", username="Poor", gold=0)
    await poor_user.insert()

    champs = []
    for _ in range(3):
        c = ChampionInstance(owner_id="poor", name="Rengar", rank="F")
        await c.insert()
        champs.append(c)

    session = make_mock_session()
    with pytest.raises(FusionError, match="gold"):
        await fuse_champions("poor", [str(c.id) for c in champs], session)


@pytest.mark.asyncio
async def test_fusion_blocked_if_equipped(user_a):
    champs = []
    for _ in range(3):
        c = ChampionInstance(owner_id="user_a", name="Rengar", rank="F")
        await c.insert()
        champs.append(c)

    # Mark one as active (active champions are protected from fusion)
    champs[0].is_active = True
    await champs[0].save()

    session = make_mock_session()
    with pytest.raises(FusionError, match="active"):
        await fuse_champions("user_a", [str(c.id) for c in champs], session)
