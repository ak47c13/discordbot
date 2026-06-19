import pytest

from models.user import User
from commands.start_cmd import register_user, AlreadyRegisteredError
from config.game_config import STARTER_SUMMON_TOKENS, STARTER_GOLD


@pytest.mark.asyncio
async def test_start_creates_user():
    user = await register_user("new_user", "Newbie")
    assert user.registered is True

    fetched = await User.find_one(User.discord_id == "new_user")
    assert fetched is not None
    assert fetched.registered is True


@pytest.mark.asyncio
async def test_start_gives_tokens():
    user = await register_user("token_user", "Tokie")
    assert user.summon_tokens == STARTER_SUMMON_TOKENS

    fetched = await User.find_one(User.discord_id == "token_user")
    assert fetched.summon_tokens == STARTER_SUMMON_TOKENS


@pytest.mark.asyncio
async def test_start_gives_gold():
    user = await register_user("gold_user", "Goldie")
    assert user.gold == STARTER_GOLD

    fetched = await User.find_one(User.discord_id == "gold_user")
    assert fetched.gold == STARTER_GOLD


@pytest.mark.asyncio
async def test_double_start_blocked():
    await register_user("dup_user", "Dup")
    with pytest.raises(AlreadyRegisteredError):
        await register_user("dup_user", "Dup")

    # Rewards were not granted twice
    fetched = await User.find_one(User.discord_id == "dup_user")
    assert fetched.summon_tokens == STARTER_SUMMON_TOKENS
    assert fetched.gold == STARTER_GOLD
