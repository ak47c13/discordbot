import os
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.team import Team
from models.trade import TradeOffer
from models.market import MarketListing
from models.audit_log import AuditLog
from models.processed_interaction import ProcessedInteraction
from models.raid import RaidQueue
from models.battle_session import BattleSession


_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient | None:
    return _client


async def init_db() -> None:
    global _client
    uri = os.environ["MONGODB_URI"]
    client = AsyncIOMotorClient(uri)
    _client = client
    db = client.get_default_database()

    await init_beanie(
        database=db,
        document_models=[
            User,
            ChampionInstance,
            ItemInstance,
            Team,
            TradeOffer,
            MarketListing,
            AuditLog,
            ProcessedInteraction,
            RaidQueue,
            BattleSession,
        ],
    )

    # TTL index on processed interactions — auto-expire after 24 hours
    await db["processedinteractions"].create_index(
        "created_at", expireAfterSeconds=86400
    )
