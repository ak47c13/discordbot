from models.user import User

async def deduct_gold(user: User, amount: int, session=None) -> bool:
    if user.gold < amount:
        return False
    user.gold -= amount
    await user.save()
    return True

async def deduct_tokens(user: User, amount: int, session=None) -> bool:
    if user.summon_tokens < amount:
        return False
    user.summon_tokens -= amount
    await user.save()
    return True
