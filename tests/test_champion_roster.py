"""Tests for the data-driven champion roster and skill factory."""
import pytest

from data.champion_roster import CHAMPION_ROSTER, ALL_CHAMPION_NAMES
from engine.skills import CHAMPION_SKILLS
from engine.combat import CombatUnit


def _mk(name, team, hp=2000, atk=100, position=1):
    skills = CHAMPION_SKILLS.get(name, {})
    return CombatUnit(
        unit_id=f"{name}_{team}_{position}",
        name=name,
        rank="F",
        level=1,
        position=position,
        team=team,
        hp=hp,
        hp_max=hp,
        atk=atk,
        def_stat=50.0,
        spd=100,
        mana=0,
        basic_fn=skills.get("basic"),
        ultimate_fn=skills.get("ultimate"),
    )


def test_champion_count():
    assert len(CHAMPION_ROSTER) >= 172


def test_all_champions_have_two_skills():
    for name in ALL_CHAMPION_NAMES:
        assert name in CHAMPION_SKILLS, f"{name} missing from CHAMPION_SKILLS"
        skills = CHAMPION_SKILLS[name]
        assert callable(skills["basic"]), f"{name} basic not callable"
        assert callable(skills["ultimate"]), f"{name} ultimate not callable"


def test_basic_skills_return_positive_mana():
    for name in ALL_CHAMPION_NAMES:
        caster = _mk(name, 0)
        enemies = [_mk("Dummy", 1, position=1), _mk("Dummy2", 1, position=3)]
        allies = [caster, _mk("AllyDummy", 0, position=2)]
        # lower an ally's HP so heal targeting has work to do
        allies[1].hp = 100
        result = CHAMPION_SKILLS[name]["basic"](caster, enemies, allies)
        assert isinstance(result, int)
        assert result > 0, f"{name} basic returned non-positive mana ({result})"


def test_ultimate_skills_return_zero_mana():
    for name in ALL_CHAMPION_NAMES:
        caster = _mk(name, 0)
        caster.mana = 100
        enemies = [_mk("Dummy", 1, position=1), _mk("Dummy2", 1, position=3)]
        allies = [caster, _mk("AllyDummy", 0, position=2)]
        allies[1].hp = 100
        result = CHAMPION_SKILLS[name]["ultimate"](caster, enemies, allies)
        assert result == 0, f"{name} ultimate returned {result} (expected 0)"


def test_all_basics_have_min_mana_in_roster():
    for name, data in CHAMPION_ROSTER.items():
        assert data["basic"]["mana_gain"] >= 20, f"{name} basic mana too low"
        assert data["ultimate"]["mana_gain"] == 0, f"{name} ultimate mana not 0"
