from models.user import User

async def deduct_gold(user: User, amount: int, session=None) -> bool:
    if user.gold < amount:
        return False
    user.gold -= amount
    await user.save()
    return True

async def deduct_tokens(user: User, amount: int, session=None) -> bool:
    # deduct from champion_tokens by default (legacy function)
    tok = getattr(user, "champion_tokens", 0)
    if tok < amount:
        return False
    user.champion_tokens = tok - amount
    await user.save()
    return True
