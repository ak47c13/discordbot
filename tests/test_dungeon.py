import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta

from models.user import User
from models.champion import ChampionInstance
from models.dungeon import Dungeon, DungeonFloor, DungeonProgress
from data.dungeon_seed import seed_dungeons
from services import dungeon_service
from config.game_config import DUNGEON_STAMINA_COST


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded():
    await seed_dungeons()


@pytest_asyncio.fixture
async def player():
    u = User(discord_id="dplayer", username="Diver", gold=0, summon_tokens=0,
             stamina=100, max_stamina=100, registered=True)
    await u.insert()
    champs = []
    for name in ["Garen", "Lux", "Fiora"]:
        c = ChampionInstance(owner_id="dplayer", name=name, rank="C", level=20)
        await c.insert()
        champs.append(str(c.id))
    return u, champs


async def test_dungeon_seed_creates_dungeons(seeded):
    dungeons = await Dungeon.find_all().to_list()
    assert len(dungeons) == 12
    # idempotent: running again creates no duplicates
    ran_again = await seed_dungeons()
    assert ran_again is False
    assert len(await Dungeon.find_all().to_list()) == 12


async def test_dungeon_floor_scaling(seeded):
    f1 = await DungeonFloor.find_one(
        DungeonFloor.dungeon_slug == "demacia-outskirts", DungeonFloor.floor_num == 1)
    f20 = await DungeonFloor.find_one(
        DungeonFloor.dungeon_slug == "demacia-outskirts", DungeonFloor.floor_num == 20)
    u1 = dungeon_service._build_enemy_unit(f1.enemies[0], 1, f1.boss_floor, 1)
    u20 = dungeon_service._build_enemy_unit(f20.enemies[0], 20, f20.boss_floor, 1)
    assert u20.hp_max > u1.hp_max
    assert u20.atk > u1.atk


async def test_dungeon_progress_created_on_enter(seeded, player):
    u, champs = player
    res = await dungeon_service.enter_floor("dplayer", "demacia-outskirts", 1, champs, None, seed=1)
    prog = await DungeonProgress.find_one(
        DungeonProgress.owner_id == "dplayer",
        DungeonProgress.dungeon_slug == "demacia-outskirts")
    assert prog is not None


async def test_checkpoint_saves_on_checkpoint_floor(seeded, player):
    u, champs = player
    res = await dungeon_service.enter_floor("dplayer", "demacia-outskirts", 10, champs, None, seed=1)
    assert res["result"] == "win"  # strong team vs floor 10
    prog = await DungeonProgress.find_one(
        DungeonProgress.owner_id == "dplayer",
        DungeonProgress.dungeon_slug == "demacia-outskirts")
    assert prog.checkpoint_floor == 10


async def test_loss_resets_to_checkpoint(seeded):
    u = User(discord_id="weak", username="Weak", stamina=100, registered=True)
    await u.insert()
    c = ChampionInstance(owner_id="weak", name="Garen", rank="F", level=1)
    await c.insert()
    prog = DungeonProgress(owner_id="weak", dungeon_slug="demacia-outskirts",
                           highest_floor=14, checkpoint_floor=10)
    await prog.insert()
    res = await dungeon_service.enter_floor("weak", "demacia-outskirts", 15, [str(c.id)], None, seed=2)
    assert res["result"] == "loss"
    prog2 = await DungeonProgress.find_one(
        DungeonProgress.owner_id == "weak",
        DungeonProgress.dungeon_slug == "demacia-outskirts")
    assert prog2.highest_floor == 10


async def test_first_clear_bonus(seeded, player):
    u, champs = player
    prog = DungeonProgress(owner_id="dplayer", dungeon_slug="demacia-outskirts",
                           highest_floor=19, checkpoint_floor=10)
    await prog.insert()
    # Strong team to guarantee the boss kill.
    for cid in champs:
        c = await ChampionInstance.get(cid)
        c.rank = "S"
        c.level = 80
        await c.save()
    gold_before = (await User.find_one(User.discord_id == "dplayer")).gold
    res = await dungeon_service.enter_floor("dplayer", "demacia-outskirts", 20, champs, None, seed=1)
    assert res["result"] == "win"
    user = await User.find_one(User.discord_id == "dplayer")
    # 500 first-clear gold + floor gold
    assert user.gold >= gold_before + 500
    assert res["rewards"]["bonus"]["type"] == "first_clear"


async def test_daily_clear_respects_cooldown(seeded, player):
    u, champs = player
    now = datetime.now(timezone.utc)
    prog = DungeonProgress(owner_id="dplayer", dungeon_slug="demacia-outskirts",
                           highest_floor=20, checkpoint_floor=10, completions=1,
                           first_clear_at=now, last_daily_at=now)
    await prog.insert()
    comp = await dungeon_service.check_dungeon_completion("dplayer", "demacia-outskirts", None)
    assert comp is None  # already claimed today


async def test_unlock_requirement(seeded):
    u = User(discord_id="locked", username="Locked", stamina=100, registered=True)
    await u.insert()
    ok, reason = await dungeon_service.can_enter_dungeon("locked", "demacias-depths", None)
    assert ok is False
    # Complete the 20F prerequisite
    prog = DungeonProgress(owner_id="locked", dungeon_slug="demacia-outskirts", completions=1)
    await prog.insert()
    ok2, _ = await dungeon_service.can_enter_dungeon("locked", "demacias-depths", None)
    assert ok2 is True


async def test_hazard_wound_reduces_hp(seeded, player):
    u, champs = player
    units = dungeon_service._build_player_units
    pus = await units(champs, None)
    full = pus[0].hp_max
    dungeon_service._apply_hazard_to_players(pus, "wound")
    assert pus[0].hp == max(1, int(full * 0.70))


async def test_stamina_deducted_on_enter(seeded, player):
    u, champs = player
    before = (await User.find_one(User.discord_id == "dplayer")).stamina
    await dungeon_service.enter_floor("dplayer", "demacia-outskirts", 1, champs, None, seed=1)
    after = (await User.find_one(User.discord_id == "dplayer")).stamina
    assert after == before - DUNGEON_STAMINA_COST
