"""Shop service — buy summon tokens with gold, and pull champions/items/runes."""
from __future__ import annotations
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session
from models.user import User


class ShopError(Exception):
    pass


# Gold → Token bundles per type
CHAMPION_TOKEN_BUNDLES = [
    {"tokens": 1,  "gold": 10_000,  "label": "1 Champion Token"},
    {"tokens": 10, "gold": 100_000, "label": "10 Champion Tokens"},
]
ITEM_TOKEN_BUNDLES = [
    {"tokens": 1,  "gold": 5_000,  "label": "1 Item Token"},
    {"tokens": 10, "gold": 50_000, "label": "10 Item Tokens"},
]
RUNE_TOKEN_BUNDLES = [
    {"tokens": 1,  "gold": 3_000,  "label": "1 Rune Token"},
    {"tokens": 10, "gold": 30_000, "label": "10 Rune Tokens"},
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


async def buy_token_bundle(owner_id: str, bundle_index: int, token_type: str = "champion", session=None) -> dict:
    """Buy a gold→token bundle. token_type: 'champion'/'item'/'rune'. bundle_index 0-1."""
    from utils.db_session import usable_session as _usable
    bundle_map = {
        "champion": CHAMPION_TOKEN_BUNDLES,
        "item": ITEM_TOKEN_BUNDLES,
        "rune": RUNE_TOKEN_BUNDLES,
    }
    bundles = bundle_map.get(token_type, CHAMPION_TOKEN_BUNDLES)
    if bundle_index < 0 or bundle_index >= len(bundles):
        raise ShopError("Invalid bundle.")
    bundle = bundles[bundle_index]
    user = await User.find_one(User.discord_id == owner_id, session=_usable(session))
    if user is None:
        raise ShopError("User not found. Use /start to register.")
    if user.gold < bundle["gold"]:
        raise ShopError(f"Need {bundle['gold']:,} gold. You have {user.gold:,}.")
    user.gold -= bundle["gold"]
    token_field = f"{token_type}_tokens"
    setattr(user, token_field, getattr(user, token_field, 0) + bundle["tokens"])
    await user.save(session=_usable(session))
    return {"tokens_gained": bundle["tokens"], "gold_spent": bundle["gold"], "token_type": token_type}
