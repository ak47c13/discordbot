"""
Turn-based status effects. All durations are in turns (the affected unit's own turns).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.combat import CombatUnit


@dataclass
class StatusEffect:
    name: str = ""
    duration: int = 0       # remaining turns

    def tick(self) -> bool:
        """Decrement duration. Returns True if effect should be removed."""
        self.duration -= 1
        return self.duration <= 0


@dataclass
class StunImmunity(StatusEffect):
    name: str = "stun_immunity"
    # Lasts 1 turn — guarantees at least one free action after a stun expires


@dataclass
class Stun(StatusEffect):
    name: str = "stun"

    def apply(self, unit: "CombatUnit") -> str:
        return f"{unit.name} is stunned and loses their turn!"


@dataclass
class Poison(StatusEffect):
    name: str = "poison"
    damage_per_turn: int = 0

    def apply_start_of_turn(self, unit: "CombatUnit") -> tuple[int, str]:
        dmg = max(1, self.damage_per_turn)
        unit.hp -= dmg
        return dmg, f"{unit.name} takes {dmg} poison damage."


@dataclass
class Burn(StatusEffect):
    name: str = "burn"
    damage_per_turn: int = 0

    def apply_end_of_turn(self, unit: "CombatUnit") -> tuple[int, str]:
        dmg = max(1, self.damage_per_turn)
        unit.hp -= dmg
        return dmg, f"{unit.name} takes {dmg} burn damage."


@dataclass
class Silence(StatusEffect):
    name: str = "silence"
    # Forces basic skill even when mana >= 100


@dataclass
class DefenseDown(StatusEffect):
    name: str = "defense_down"
    reduction_pct: float = 0.3   # 30% defense reduction


@dataclass
class Shield(StatusEffect):
    name: str = "shield"
    absorb: int = 0   # remaining HP absorbed

    def absorb_damage(self, damage: int) -> tuple[int, int]:
        """Returns (damage_absorbed, remaining_damage)."""
        absorbed = min(self.absorb, damage)
        self.absorb -= absorbed
        return absorbed, damage - absorbed
