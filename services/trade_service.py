"""
P2P trade service. Both sides confirm. Atomic swap via MongoDB transaction.
"""
from __future__ import annotations
from datetime import datetime, timezone

from beanie import PydanticObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession
from utils.db_session import usable_session

from models.trade import TradeOffer
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.user import User
from models.audit_log import AuditLog
from config.game_config import TRADING_MIN_ACCOUNT_AGE_HOURS


class TradeError(Exception):
    pass


async def create_trade(
    initiator_id: str,
    target_id: str,
    initiator_champion_ids: list[str],
    initiator_item_ids: list[str],
    initiator_gold: int,
    target_champion_ids: list[str],
    target_item_ids: list[str],
    target_gold: int,
    session: AsyncIOMotorClientSession,
) -> TradeOffer:
    # Account age check
    initiator_user = await User.find_one(User.discord_id == initiator_id, session=usable_session(session))
    created = initiator_user.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds() / 3600
    if age < TRADING_MIN_ACCOUNT_AGE_HOURS:
        raise TradeError(f"Account must be at least {TRADING_MIN_ACCOUNT_AGE_HOURS}h old to trade.")

    if initiator_gold < 0 or target_gold < 0:
        raise TradeError("Gold amounts cannot be negative.")

    if initiator_user.gold < initiator_gold:
        raise TradeError("Not enough gold to offer.")

    # Lock all initiator items/champions
    await _lock_assets(
        initiator_id, initiator_champion_ids, initiator_item_ids, True, session
    )

    # Verify target owns their side
    target_user = await User.find_one(User.discord_id == target_id, session=usable_session(session))
    if target_user.gold < target_gold:
        raise TradeError("Target doesn't have enough gold.")

    trade = TradeOffer(
        initiator_id=initiator_id,
        target_id=target_id,
        initiator_champion_ids=initiator_champion_ids,
        initiator_item_ids=initiator_item_ids,
        initiator_gold=initiator_gold,
        target_champion_ids=target_champion_ids,
        target_item_ids=target_item_ids,
        target_gold=target_gold,
        status="pending",
    )
    await trade.insert(session=usable_session(session))
    return trade


async def accept_trade(
    trade_id: str,
    target_id: str,
    session: AsyncIOMotorClientSession,
) -> TradeOffer:
    trade = await TradeOffer.get(PydanticObjectId(trade_id), session=usable_session(session))
    if trade is None:
        raise TradeError("Trade not found.")
    if trade.target_id != target_id:
        raise TradeError("You are not the target of this trade.")
    if trade.status != "pending":
        raise TradeError(f"Trade is already {trade.status}.")

    # Lock target assets
    await _lock_assets(
        target_id, trade.target_champion_ids, trade.target_item_ids, True, session
    )

    # Verify gold on both sides
    initiator = await User.find_one(User.discord_id == trade.initiator_id, session=usable_session(session))
    target = await User.find_one(User.discord_id == target_id, session=usable_session(session))

    if initiator.gold < trade.initiator_gold:
        raise TradeError("Initiator no longer has enough gold.")
    if target.gold < trade.target_gold:
        raise TradeError("You no longer have enough gold.")

    # Swap gold
    initiator.gold -= trade.initiator_gold
    initiator.gold += trade.target_gold
    target.gold -= trade.target_gold
    target.gold += trade.initiator_gold

    # Transfer champions
    all_champ_ids = trade.initiator_champion_ids + trade.target_champion_ids
    for cid in trade.initiator_champion_ids:
        c = await ChampionInstance.get(PydanticObjectId(cid), session=usable_session(session))
        c.owner_id = target_id
        c.in_trade = False
        await c.save(session=usable_session(session))
    for cid in trade.target_champion_ids:
        c = await ChampionInstance.get(PydanticObjectId(cid), session=usable_session(session))
        c.owner_id = trade.initiator_id
        c.in_trade = False
        await c.save(session=usable_session(session))

    # Transfer items
    for iid in trade.initiator_item_ids:
        itm = await ItemInstance.get(PydanticObjectId(iid), session=usable_session(session))
        itm.owner_id = target_id
        itm.in_trade = False
        await itm.save(session=usable_session(session))
    for iid in trade.target_item_ids:
        itm = await ItemInstance.get(PydanticObjectId(iid), session=usable_session(session))
        itm.owner_id = trade.initiator_id
        itm.in_trade = False
        await itm.save(session=usable_session(session))

    await initiator.save(session=usable_session(session))
    await target.save(session=usable_session(session))

    trade.status = "completed"
    trade.completed_at = datetime.now(timezone.utc)
    await trade.save(session=usable_session(session))

    total_gold = trade.initiator_gold + trade.target_gold
    if total_gold >= 10000:
        await AuditLog.log(
            "HIGH_VALUE_TRADE",
            actor_id=trade.initiator_id,
            target_id=trade.target_id,
            trade_id=str(trade.id),
            gold_exchanged=total_gold,
        )

    return trade


async def cancel_trade(
    trade_id: str,
    user_id: str,
    session: AsyncIOMotorClientSession,
) -> TradeOffer:
    trade = await TradeOffer.get(PydanticObjectId(trade_id), session=usable_session(session))
    if trade is None:
        raise TradeError("Trade not found.")
    if trade.status != "pending":
        raise TradeError(f"Trade is already {trade.status}.")
    if user_id not in (trade.initiator_id, trade.target_id):
        raise TradeError("Not your trade.")

    await _lock_assets(
        trade.initiator_id, trade.initiator_champion_ids, trade.initiator_item_ids, False, session
    )

    trade.status = "cancelled"
    await trade.save(session=usable_session(session))
    return trade


async def _lock_assets(
    owner_id: str,
    champion_ids: list[str],
    item_ids: list[str],
    lock: bool,
    session: AsyncIOMotorClientSession,
) -> None:
    for cid in champion_ids:
        c = await ChampionInstance.get(PydanticObjectId(cid), session=usable_session(session))
        if c is None or c.owner_id != owner_id:
            raise TradeError(f"Champion {cid} not found or not owned by you.")
        if lock and getattr(c, "favorite", False):
            raise TradeError(f"Cannot trade favorited champion {c.name}. Unfavorite first.")
        if lock and not c.is_available:
            raise TradeError(f"{c.name} is already locked, equipped, or in another trade.")
        c.in_trade = lock
        await c.save(session=usable_session(session))

    for iid in item_ids:
        itm = await ItemInstance.get(PydanticObjectId(iid), session=usable_session(session))
        if itm is None or itm.owner_id != owner_id:
            raise TradeError(f"Item {iid} not found or not owned by you.")
        if lock and getattr(itm, "favorite", False):
            raise TradeError(f"Cannot trade favorited item {itm.name}. Unfavorite first.")
        if lock and not itm.is_available:
            raise TradeError(f"{itm.name} is already locked, equipped, or in another trade.")
        itm.in_trade = lock
        await itm.save(session=usable_session(session))
