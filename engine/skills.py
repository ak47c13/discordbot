"""
Champion skill registry — now data-driven with Q/W/E/R support.

CHAMPION_SKILLS maps champion name -> {
    "q": fn, "w": fn, "e": fn, "r": fn,
    "basic": fn,     # alias for "q" (backward compat for bosses)
    "ultimate": fn,  # alias for "r" (backward compat for bosses)
    "mana_gain": int,
}
"""
from __future__ import annotations

from data.champion_skills import CHAMPION_SKILLS as _RAW_SKILLS
from engine.skill_factory import skill_from_def

CHAMPION_SKILLS: dict[str, dict] = {}

for _name, _skill_defs in _RAW_SKILLS.items():
    _q_fn = skill_from_def(_skill_defs["q"])
    _w_fn = skill_from_def(_skill_defs["w"])
    _e_fn = skill_from_def(_skill_defs["e"])
    _r_fn = skill_from_def(_skill_defs["r"])
    CHAMPION_SKILLS[_name] = {
        "q": _q_fn,
        "w": _w_fn,
        "e": _e_fn,
        "r": _r_fn,
        # Backward-compat aliases used by boss unit builder and dungeon engine
        "basic": _q_fn,
        "ultimate": _r_fn,
        "mana_gain": _skill_defs["q"].get("mana_gain", 25),
    }

ALL_CHAMPION_NAMES = list(CHAMPION_SKILLS.keys())
