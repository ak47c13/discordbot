"""
Champion skill registry — tier-aware, data-driven Q/W/E/R.

CHAMPION_SKILLS maps champion name -> raw skill defs (not compiled functions).
Compilation happens per-unit in build_unit_from_champion() so rank is available.

get_skill_fns(name, rank, active_key) compiles the correct tier for a given rank.
"""
from __future__ import annotations

from data.champion_skills import CHAMPION_SKILLS as _RAW_SKILLS
from engine.skill_factory import skill_from_def

# Pre-compiled at F-rank for backward compat (boss units, dungeon, tests)
CHAMPION_SKILLS: dict[str, dict] = {}

for _name, _skill_defs in _RAW_SKILLS.items():
    _q_fn = skill_from_def(_skill_defs["q"], rank="F")
    _w_fn = skill_from_def(_skill_defs["w"], rank="F")
    _e_fn = skill_from_def(_skill_defs["e"], rank="F")
    _r_fn = skill_from_def(_skill_defs["r"], rank="F")
    CHAMPION_SKILLS[_name] = {
        "q": _q_fn, "w": _w_fn, "e": _e_fn, "r": _r_fn,
        "basic": _q_fn, "ultimate": _r_fn,
        "mana_gain": _skill_defs["q"].get("mana_gain", 25),
        "_raw": _skill_defs,  # keep raw for rank-resolved compilation
    }

ALL_CHAMPION_NAMES = list(CHAMPION_SKILLS.keys())


def get_skill_fns(champion_name: str, rank: str, active_key: str = "q") -> dict:
    """Return rank-resolved skill functions for a champion.

    Returns dict with keys: basic_fn, ultimate_fn (the active basic + R).
    Falls back to F-rank pre-compiled if champion not found.
    """
    entry = CHAMPION_SKILLS.get(champion_name)
    if entry is None:
        return {"basic_fn": None, "ultimate_fn": None}

    raw = entry.get("_raw", {})
    if not raw:
        # No raw defs (shouldn't happen) — fall back to pre-compiled
        return {"basic_fn": entry.get(active_key) or entry.get("q"), "ultimate_fn": entry.get("r")}

    basic_key = active_key if active_key in raw else "q"
    basic_fn   = skill_from_def(raw[basic_key], rank=rank)
    ultimate_fn = skill_from_def(raw["r"], rank=rank)
    return {"basic_fn": basic_fn, "ultimate_fn": ultimate_fn}
