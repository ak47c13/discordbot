import pytest
import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.team import Team
from models.trade import TradeOffer
from models.market import MarketListing
from models.audit_log import AuditLog
from models.processed_interaction import ProcessedInteraction
from models.raid import RaidQueue


ALL_MODELS = [
    User, ChampionInstance, ItemInstance, Team,
    TradeOffer, MarketListing, AuditLog, ProcessedInteraction, RaidQueue,
]


@pytest_asyncio.fixture(autouse=True)
async def init_test_db():
    client = AsyncMongoMockClient()
    await init_beanie(database=client.test_db, document_models=ALL_MODELS)
    yield
    # mongomock auto-cleans


@pytest_asyncio.fixture
async def user_a():
    u = User(discord_id="user_a", username="Alice", gold=10000, summon_tokens=1000)
    await u.insert()
    return u


@pytest_asyncio.fixture
async def user_b():
    u = User(discord_id="user_b", username="Bob", gold=5000, summon_tokens=500)
    await u.insert()
    return u
