"""
Per-user asyncio locks. Prevents the same user from running two concurrent
state-changing commands (double-spend, duplicate reward, race condition).
"""
import asyncio

_user_locks: dict[str, asyncio.Lock] = {}


def get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]
