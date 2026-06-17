"""Shop service — buy summon tokens with gold, and pull champions/items/runes."""
from __future__ import annotations
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session
from models.user import User


class ShopError(Exception):
    pass


# Gold → Token bundles (simple: 1 or 10)
TOKEN_BUNDLES = [
    {"tokens": 1,  "gold": 500,   "label": "1 Token"},
    {"tokens": 10, "gold": 4500,  "label": "10 Tokens (10% off)"},
]

# Token costs for pulls
PULL_COSTS = {
    "champion_single": 1,
    "champion_multi": 10,
    "item_single": 1,
    "item_multi": 10,
    "rune_single": 1,
    "rune_multi": 10,
}


async def buy_token_bundle(owner_id: str, bundle_index: int, session=None) -> dict:
    """Buy a gold→token bundle. bundle_index 0-3."""
    if bundle_index < 0 or bundle_index >= len(TOKEN_BUNDLES):
        raise ShopError("Invalid bundle.")
    bundle = TOKEN_BUNDLES[bundle_index]
    user = await User.find_one(User.discord_id == owner_id, session=usable_session(session))
    if user is None:
        raise ShopError("User not found.")
    if user.gold < bundle["gold"]:
        raise ShopError(f"Need {bundle['gold']:,} gold. You have {user.gold:,}.")
    user.gold -= bundle["gold"]
    user.summon_tokens += bundle["tokens"]
    await user.save(session=usable_session(session))
    return {"tokens_gained": bundle["tokens"], "gold_spent": bundle["gold"]}
