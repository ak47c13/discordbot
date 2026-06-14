"""
Champion skill registry — now data-driven.

Skills are generated from declarative definitions in ``data.champion_roster`` via
``engine.skill_factory.skill_from_def``. Each champion exposes a basic and an
ultimate skill function with the signature:

    fn(caster: CombatUnit, all_enemies: list[CombatUnit], all_allies: list[CombatUnit]) -> int

The integer return value is mana gained (always 0 for ultimates). Basic skills also
mutate ``caster.mana`` directly. Generated log lines are stashed on ``fn.last_log``.

``CHAMPION_SKILLS`` maps champion name -> {"basic": fn, "ultimate": fn, "mana_gain": int}
to remain backward compatible with the combat engine and existing tests.
"""
from __future__ import annotations

from data.champion_roster import CHAMPION_ROSTER, ALL_CHAMPION_NAMES as _ROSTER_NAMES
from engine.skill_factory import skill_from_def

CHAMPION_SKILLS: dict[str, dict] = {}

for _name, _data in CHAMPION_ROSTER.items():
    _basic_fn = skill_from_def(_data["basic"])
    _ult_fn = skill_from_def(_data["ultimate"])
    CHAMPION_SKILLS[_name] = {
        "basic": _basic_fn,
        "ultimate": _ult_fn,
        "mana_gain": _data["basic"].get("mana_gain", 25),
    }

ALL_CHAMPION_NAMES = list(CHAMPION_SKILLS.keys())
