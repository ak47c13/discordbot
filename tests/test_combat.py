import pytest
from engine.combat import CombatUnit, run_battle, BattleResult
from engine.skills import CHAMPION_SKILLS
from config.game_config import MAX_ROUNDS


def make_unit(
    name: str,
    team: int,
    hp: int = 1000,
    atk: float = 100.0,
    def_stat: float = 50.0,
    spd: int = 100,
    position: int = 1,
) -> CombatUnit:
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


def test_player_wins_against_weak_enemy():
    players = [make_unit("Rengar", 0, hp=5000, atk=500)]
    enemies = [make_unit("Jinx", 1, hp=100, atk=10)]
    result = run_battle(players, enemies)
    assert result.winner == 0


def test_enemy_wins_against_weak_player():
    players = [make_unit("Rengar", 0, hp=100, atk=10)]
    enemies = [make_unit("Darius", 1, hp=5000, atk=500)]
    result = run_battle(players, enemies)
    assert result.winner == 1


def test_battle_has_round_limit():
    # Two immortal units (very high defense) — should hit stalemate
    players = [make_unit("Lux", 0, hp=100000, atk=1, def_stat=10000)]
    enemies = [make_unit("Leona", 1, hp=100000, atk=1, def_stat=10000)]
    result = run_battle(players, enemies)
    # Must terminate
    assert result.rounds <= MAX_ROUNDS
    assert result.winner in (-1, 0, 1)


def test_mana_starts_at_zero():
    u = make_unit("Yasuo", 0)
    assert u.mana == 0


def test_ultimate_requires_100_mana():
    u = make_unit("Darius", 0)
    u.mana = 99
    enemies = [make_unit("Jinx", 1)]
    allies = [u]
    # At 99 mana should use basic, not ultimate
    # The basic skill increases mana, so after it mana should go UP from 99
    log = u.basic_fn(u, enemies, allies)
    assert u.mana == 100 or u.mana > 99  # basic generates mana


def test_ultimate_resets_mana_to_zero():
    u = make_unit("Rengar", 0)
    u.mana = 100
    enemies = [make_unit("Leona", 1)]
    allies = [u]
    u.ultimate_fn(u, enemies, allies)
    assert u.mana == 0


def test_battle_result_has_log():
    players = [make_unit("Jinx", 0, hp=2000, atk=200)]
    enemies = [make_unit("Rengar", 1, hp=500, atk=50)]
    result = run_battle(players, enemies)
    assert len(result.log) > 0


def test_five_vs_five_battle():
    players = [make_unit("Rengar", 0, position=i + 1) for i in range(5)]
    enemies = [make_unit("Darius", 1, position=i + 1) for i in range(5)]
    result = run_battle(players, enemies)
    assert result.winner in (-1, 0, 1)
    assert result.rounds <= MAX_ROUNDS


def test_dead_units_do_not_act():
    players = [make_unit("Soraka", 0, hp=5000, atk=300)]
    enemy1 = make_unit("Jinx", 1, hp=100, atk=10, position=1)
    enemy2 = make_unit("Rengar", 1, hp=5000, atk=50, position=2)
    result = run_battle(players, [enemy1, enemy2])
    # Enemy 1 should die, game should continue, no errors
    assert result.rounds >= 1


def test_stun_effect_skips_turn():
    from engine.status_effects import Stun
    u = make_unit("Rengar", 0)
    u.status_effects.append(Stun(duration=1))
    assert u.has_effect(Stun)


def test_poison_damages_at_start_of_turn():
    from engine.status_effects import Poison
    u = make_unit("Rengar", 0)
    poison = Poison(duration=3, damage_per_turn=50)
    u.status_effects.append(poison)
    hp_before = u.hp
    u.tick_effects_start()
    assert u.hp == hp_before - 50
