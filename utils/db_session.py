"""
Helper to get the Motor client for starting MongoDB sessions/transactions.
"""
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import get_client


def get_motor_client() -> AsyncIOMotorClient:
    return get_client()
