"""
Helper to get the Motor client for starting MongoDB sessions/transactions.
"""
from motor.motor_asyncio import AsyncIOMotorClient


def get_motor_client() -> AsyncIOMotorClient:
    from database.connection import get_client
    return get_client()


def usable_session(session):
    """Return the session only if it is a real Motor client session.

    Test suites pass mock sessions (used purely as async context managers) and
    the in-memory mongomock backend cannot handle session kwargs. In that case
    we return None so DB operations run without an explicit session, while real
    production sessions are forwarded untouched to enable transactions.
    """
    from motor.motor_asyncio import AsyncIOMotorClientSession
    if isinstance(session, AsyncIOMotorClientSession):
        return session
    return None
