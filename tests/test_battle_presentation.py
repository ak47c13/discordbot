import pytest
import pytest_asyncio

from engine.combat import CombatUnit, run_battle_with_rounds
from engine.skills import CHAMPION_SKILLS
from models.battle_session import BattleSession
from services.battle_presentation_service import (
    simulate_and_store,
    advance_and_display,
    finalize,
    cancel_battle,
)
from utils.battle_embeds import progress_bar, hp_display


def make_unit(name, team, hp=1000, atk=100.0, def_stat=50.0, spd=100, position=1):
    skills = CHAMPION_SKILLS.get(name, {})
    return CombatUnit(
        unit_id=f"{name}_{team}",
        name=name,
        rank="F",
        level=1,
        position=position,
        team=team,
        hp=hp,
        hp_max=hp,
        atk=atk,
        def_stat=def_stat,
        spd=spd,
        mana=0,
        basic_fn=skills.get("basic"),
        ultimate_fn=skills.get("ultimate"),
    )


class FakeMessage:
    """Minimal async message stub supporting edit()."""
    def __init__(self):
        self.edits = 0
        self.last_embed = None

    async def edit(self, **kwargs):
        self.edits += 1
        self.last_embed = kwargs.get("embed")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_progress_bar():
    assert progress_bar(8, 16) == "████████░░░░░░░░"


def test_progress_bar_zero_max():
    assert progress_bar(5, 0) == "░" * 16


def test_hp_display_format():
    out = hp_display(12482, 50000)
    assert "/" in out
    assert "12,482" in out


# ---------------------------------------------------------------------------
# Simulation / storage
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simulate_and_store_creates_session():
    players = [make_unit("Rengar", 0, hp=5000, atk=500)]
    enemies = [make_unit("Jinx", 1, hp=100, atk=10)]
    bs = await simulate_and_store(
        owner_id="u1", zone="Forest", player_units=players,
        enemy_units=enemies, battle_type="hunt", entry_cost={}, session=None,
    )
    assert bs.simulated_round_count > 0
    assert bs.status == "CREATING"
    assert len(bs.simulated_rounds) == bs.simulated_round_count


def test_battle_seed_deterministic():
    def run():
        players = [make_unit("Rengar", 0, hp=3000, atk=200)]
        enemies = [make_unit("Darius", 1, hp=3000, atk=200)]
        _, rounds = run_battle_with_rounds(players, enemies, seed=42)
        return rounds

    r1 = run()
    r2 = run()
    assert len(r1) == len(r2)
    for a, b in zip(r1, r2):
        assert a["player_hp"] == b["player_hp"]
        assert a["enemy_hp"] == b["enemy_hp"]


@pytest.mark.asyncio
async def test_advance_display_increments_counter():
    players = [make_unit("Rengar", 0, hp=5000, atk=500)]
    enemies = [make_unit("Jinx", 1, hp=100, atk=10)]
    bs = await simulate_and_store(
        owner_id="u1", zone="Forest", player_units=players,
        enemy_units=enemies, battle_type="hunt", entry_cost={}, session=None,
    )
    bs.status = "ACTIVE"
    bs.fast_display = True
    bs.message_id = "1"
    bs.channel_id = "1"
    await bs.save()

    msg = FakeMessage()
    # use interval 0 by monkeypatching display interval via fast + override
    import services.battle_presentation_service as svc
    orig = svc._interval_for
    svc._interval_for = lambda b: 0.0
    try:
        await advance_and_display(str(bs.id), msg)
    finally:
        svc._interval_for = orig

    refreshed = await BattleSession.get(bs.id)
    assert refreshed.displayed_round_count == refreshed.simulated_round_count
    assert msg.edits > 0


@pytest.mark.asyncio
async def test_victory_sets_status():
    players = [make_unit("Rengar", 0, hp=5000, atk=500)]
    enemies = [make_unit("Jinx", 1, hp=100, atk=10)]
    bs = await simulate_and_store(
        owner_id="u1", zone="Forest", player_units=players,
        enemy_units=enemies, battle_type="hunt", entry_cost={}, session=None,
    )
    bs.status = "ACTIVE"
    bs.message_id = "1"
    bs.channel_id = "1"
    await bs.save()

    msg = FakeMessage()
    import services.battle_presentation_service as svc
    orig = svc._interval_for
    svc._interval_for = lambda b: 0.0
    try:
        await advance_and_display(str(bs.id), msg)
    finally:
        svc._interval_for = orig

    refreshed = await BattleSession.get(bs.id)
    assert refreshed.status == "VICTORY"
    assert refreshed.reward_claimed is True


@pytest.mark.asyncio
async def test_cancel_prevents_rewards():
    players = [make_unit("Rengar", 0, hp=5000, atk=500)]
    enemies = [make_unit("Jinx", 1, hp=100, atk=10)]
    bs = await simulate_and_store(
        owner_id="u1", zone="Forest", player_units=players,
        enemy_units=enemies, battle_type="hunt", entry_cost={}, session=None,
    )
    bs.status = "ACTIVE"
    await bs.save()

    ok = await cancel_battle(str(bs.id), "CANCELLED_BY_USER", session=None)
    assert ok is True

    # Finalize should be a no-op since not ACTIVE
    reloaded = await BattleSession.get(bs.id)
    await finalize(reloaded, None, {}, session=None)
    refreshed = await BattleSession.get(bs.id)
    assert refreshed.reward_claimed is False
    assert refreshed.status == "CANCELLED_BY_USER"


@pytest.mark.asyncio
async def test_cancel_idempotent():
    players = [make_unit("Rengar", 0, hp=5000, atk=500)]
    enemies = [make_unit("Jinx", 1, hp=100, atk=10)]
    bs = await simulate_and_store(
        owner_id="u1", zone="Forest", player_units=players,
        enemy_units=enemies, battle_type="hunt", entry_cost={}, session=None,
    )
    bs.status = "ACTIVE"
    await bs.save()

    first = await cancel_battle(str(bs.id), "CANCELLED_BY_USER", session=None)
    second = await cancel_battle(str(bs.id), "CANCELLED_BY_USER", session=None)
    assert first is True
    assert second is False
