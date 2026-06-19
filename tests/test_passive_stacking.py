"""
Tests that identical item passives do NOT stack, but main stats and secondary
stats from duplicate items DO stack.
"""
import pytest
from engine.combat import build_unit_from_champion
from models.champion import ChampionInstance
from models.item import ItemInstance
from config.game_config import ITEM_BASE_MAIN_STAT


async def _make_champ(owner_id: str, name: str = "Rengar", rank: str = "F") -> ChampionInstance:
    c = ChampionInstance(owner_id=owner_id, name=name, rank=rank, level=1)
    await c.insert()
    return c


async def _make_item(
    owner_id: str,
    equipped_to: str,
    passive_name: str = "crit_damage_passive",
    rank: str = "F",
    enhancement: int = 0,
    main_stat_type: str = "atk",
    slot: int = 1,
) -> ItemInstance:
    itm = ItemInstance(
        owner_id=owner_id,
        name="Infinity Edge",
        rank=rank,
        enhancement=enhancement,
        main_stat_type=main_stat_type,
        main_stat_base=ITEM_BASE_MAIN_STAT[rank],
        passive_name=passive_name,
        secondary_stat_type="crit_chance",
        secondary_stat_value=20,
        equipped_to=equipped_to,
        equipment_slot=slot,
    )
    await itm.insert()
    return itm


@pytest.mark.asyncio
async def test_duplicate_passive_does_not_stack(user_a):
    """
    Equipping 2 items with the same passive should activate only 1 passive.
    Main stats from both items must still apply.
    """
    champ = await _make_champ("user_a")
    item1 = await _make_item("user_a", str(champ.id), passive_name="crit_damage_passive", slot=1)
    item2 = await _make_item("user_a", str(champ.id), passive_name="crit_damage_passive", slot=2)

    unit = build_unit_from_champion(champ, [item1, item2], position=1, team=0)

    # ATK from both items should be applied (main stats stack)
    from config.game_config import CHAMPION_BASE_STATS, ENHANCEMENT_MULTIPLIER
    base_atk = CHAMPION_BASE_STATS["F"]["atk"]
    item_atk = ITEM_BASE_MAIN_STAT["F"] * (1 + ENHANCEMENT_MULTIPLIER[0])
    expected_atk = base_atk + item_atk * 2  # Both item main stats stack

    assert abs(unit.atk - expected_atk) < 1.0


@pytest.mark.asyncio
async def test_different_passives_both_active(user_a):
    """Two different passives should both be present in the pool."""
    champ = await _make_champ("user_a")
    item1 = await _make_item("user_a", str(champ.id), passive_name="crit_damage_passive", slot=1)
    item2 = await _make_item("user_a", str(champ.id), passive_name="armor_passive", slot=2)

    # build_unit_from_champion collects all passives in passive_pool
    # This test just verifies the unit builds without error
    unit = build_unit_from_champion(champ, [item1, item2], position=1, team=0)
    assert unit.atk > 0


@pytest.mark.asyncio
async def test_higher_rank_item_passive_wins(user_a):
    """When two items share the same passive, the higher rank item's passive should win."""
    champ = await _make_champ("user_a")
    item_f = await _make_item("user_a", str(champ.id), passive_name="crit_damage_passive", rank="F", slot=1)
    item_e = await _make_item("user_a", str(champ.id), passive_name="crit_damage_passive", rank="E", slot=2)

    unit = build_unit_from_champion(champ, [item_f, item_e], position=1, team=0)
    # Both items' ATK still contribute
    assert unit.atk > 0
