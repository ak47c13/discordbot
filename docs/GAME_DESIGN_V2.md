# Game Design V2 — Feature Specification

## 1. Dungeons

### 1.1 Checkpoint System
- **Field added:** `last_completed_floor: int = 0` on the user's dungeon progress document.
- When a user re-enters a dungeon map they've partially cleared, they start from `last_completed_floor + 1`.
- Checkpoint updates only after a floor is fully won.
- Resetting to floor 1 is not automatic — a user must explicitly reset (future feature).

### 1.2 Map Locking
- A map is **locked** until the user has completed every floor of the previous map.
- The `/dungeon` command dropdown only shows maps the user has unlocked.
- Map 1 is always available.
- Completion tracked via `maps_completed: list[str]` on dungeon progress.
- **Slash command:** options are filtered server-side before building the dropdown choices.

### 1.3 Battle Image Positioning
- Champion card renders at the **top** of the battle image.
- Enemy cards render at the **bottom**.
- Change is purely in `utils/battle_image_gen.py` render order — no data changes.

### 1.4 Continuous Mode
- New button **"▶ Run Continuously"** appears on the dungeon floor confirmation.
- Automatically advances floor by floor, consuming stamina each floor.
- Stops when:
  - User loses a battle.
  - Stamina reaches 0.
  - Map is fully cleared.
- Sends a single summary embed at the end: floors cleared, total rewards, stamina spent, stop reason.
- No per-floor message spam — only shows the final round of each floor's battle, then immediately advances.

---

## 2. Champion

### 2.1 Stable Numeric Display IDs
- New field: `display_id: int` on `ChampionInstance`.
- Auto-incremented globally using a `counters` MongoDB collection (`{"_id": "champion_display_id", "seq": N}`).
- IDs are assigned at summon time and never change (even after fusion, trade, etc.).
- `/champion-select 3` uses `display_id`, not MongoDB ObjectId or index.
- One-time migration backfills all existing champions with sequential IDs.
- **Format:** plain integer only (e.g. `1`, `42`, `1337`). No rank prefix, no alphanumeric.

### 2.2 Fix /champion Command Text
- Remove all references to the removed `/team-select` command from the embed text.
- Replace with `/champion-select <id>` where relevant.

---

## 3. Summon

### 3.1 Weekly Rotating Region
- Regions cycle Monday 00:00 → Sunday 23:59 **GMT+8 (Philippine Time)**.
- Rotation is **deterministic**: `week_index = floor(timestamp / 604800)` anchored to the first Monday epoch in 2024 GMT+8.
- No cron job or DB record needed — computed on every summon call.
- **Region pool order** (loops after last):
  1. Demacia
  2. Noxus
  3. Freljord
  4. Piltover & Zaun
  5. Ionia
  6. Shadow Isles
  7. Bilgewater
  8. Shurima
  9. Targon
  10. Ixtal
  11. Bandle City
  12. Void
- Champions filtered by `source_roles` or a `region` tag in the roster.
- Summon header shows current region and days/hours until next rotation.
- All champions remain obtainable (rotation only affects the standard summon pool; boss drops and event banners are separate).

### 3.2 Shop — `/shop`
Subcommands:

| Subcommand | Description |
|---|---|
| `/shop champions` | Buy champion summon pulls using Summon Tokens |
| `/shop items` | Buy item pulls or specific items using Gold |
| `/shop runes` | Buy individual runes or rune pages using Gold |
| `/shop pulls` | Buy **Summon Tokens** using Gold |

#### `/shop pulls` — Gold → Summon Tokens
| Bundle | Cost (Gold) | Tokens | Value |
|---|---|---|---|
| 1 Token | 500g | 1 | baseline |
| 5 Tokens | 2,250g | 5 | 10% discount |
| 11 Tokens | 4,500g | 11 | ~18% discount (1 free) |
| 22 Tokens | 8,500g | 22 | ~23% discount (2 free) |

#### `/shop items` — Sample pricing
| Item | Cost |
|---|---|
| Common item pull | 300g |
| Rare item pull | 800g |
| Specific item (by name) | 1,200–3,000g depending on tier |

#### `/shop runes` — Sample pricing
| Rune | Cost |
|---|---|
| Tier 1 rune | 150g |
| Tier 2 rune | 400g |
| Tier 3 rune | 1,000g |
| Full rune page reset | 100g |

---

## 4. Level-Up

### 4.1 Rank-Based Level Caps
| Rank | Max Level |
|---|---|
| F | 20 |
| E | 30 |
| D | 40 |
| C | 50 |
| B | 60 |
| A | 70 |
| S | 80 |

Champion cannot level beyond their rank cap. Rank-up (fusion) raises the cap and resets EXP curve at the new rank's base.

### 4.2 Level-Up Options
`/levelup` gains three options:
- **×1** — level up once (existing behavior)
- **×10** — level up ten times (if cap allows), paying the sum of those 10 levels' costs
- **Max** — level up to the current rank's cap, paying the total cost

### 4.3 Exponential Gold Cost Formula
```
cost(level) = base_rank_cost × growth_rate ^ (current_level - 1)
```

| Rank | Base Cost | Growth Rate | Lv1→2 | Lv cap-1→cap |
|---|---|---|---|---|
| F | 50g | 1.18 | 50g | ~660g |
| E | 120g | 1.18 | 120g | ~2,400g |
| D | 280g | 1.18 | 280g | ~8,000g |
| C | 600g | 1.18 | 600g | ~24,000g |
| B | 1,200g | 1.18 | 1,200g | ~65,000g |
| A | 2,500g | 1.18 | 2,500g | ~160,000g |
| S | 5,000g | 1.18 | 5,000g | ~360,000g |

×10 and Max show the total cost before confirming.

---

## 5. Stats Expansion

### 5.1 Stats Added to CombatUnit
Keep only LoL-relevant stats. Drop: secondary resource bars, attack range, attack windup, health regen.

| Stat | Field | Default | Notes |
|---|---|---|---|
| Attack | `atk` | existing | — |
| Defense (Armor) | `def_stat` | existing | — |
| Speed | `spd` | existing | — |
| Mana | `mana` | existing | — |
| Crit Chance | `crit_chance` | 0.0 | 0.0–1.0 float |
| Crit Damage | `crit_dmg` | 1.75 | multiplier on crit hit |
| Armor Penetration | `armor_pen` | 0 | flat, reduces enemy def_stat |
| Magic Penetration | `magic_pen` | 0 | flat, for skill damage |
| Lifesteal | `lifesteal` | 0.0 | % of physical damage healed |
| Dodge Chance | `dodge_chance` | 0.0 | % chance to avoid basic attacks |
| Attack Speed | `attack_speed` | 1.0 | multiplier; >1.0 = more attacks per turn |

### 5.2 Combat Formula Changes (engine/combat.py)
- **Crit:** each hit rolls `random() < crit_chance`; if crit, multiply raw damage by `crit_dmg`.
- **Armor pen:** `effective_def = max(0, target.def_stat - attacker.armor_pen)`.
- **Dodge:** defender rolls `random() < dodge_chance`; if dodge, 0 damage, log "dodged".
- **Lifesteal:** `caster.hp = min(caster.hp_max, caster.hp + damage_dealt * caster.lifesteal)`.
- **Attack speed:** a unit with `attack_speed = 1.5` takes an extra basic attack action every other round (tracked via `attack_speed_counter` on the unit).

---

## 6. Profile Upgrade

### 6.1 Layout
`/profile` shows a richer embed (or two-page embed with a next button):

**Page 1 — Overview (existing)**
- Username, gold, tokens, rank badge

**Page 2 — Champion Detail**
- Active champion name, rank, level, display_id
- Full stat block (all stats from §5 above) as a formatted field
- Equipped items listed with their stat bonuses
- Rune page summary: filled/total slots per color, total stat bonuses contributed by runes

### 6.2 Stat Block Format (example)
```
⚔️ ATK      420    🛡️ DEF     180
⚡ SPD      310    💧 MANA     55/100
🎯 CRIT    12.5%  💥 CRIT DMG 175%
🔱 ARM PEN  25    🔮 MAG PEN   10
🩸 LIFESTEAL 8%   💨 DODGE    4.0%
⚡ ATK SPD  1.2x
```

---

## 7. Stamina (deferred)
No changes in this cycle. Stamina exists but consumption rates need balancing once continuous dungeon mode is in place and usage data can be gathered.

---

## Implementation Order

| Priority | Feature | Files Touched |
|---|---|---|
| 1 | Champion: fix /champion text | `commands/champions_cmd.py` |
| 2 | Champion: numeric display IDs + migration | `models/champion.py`, `scripts/`, `commands/champion_select_cmd.py` |
| 3 | Dungeon: image positioning (enemy bottom, champ top) | `utils/battle_image_gen.py` |
| 4 | Dungeon: checkpoint + map locking | `models/`, `commands/dungeon_cmd.py`, `services/dungeon_service.py` |
| 5 | Dungeon: continuous mode | `commands/dungeon_cmd.py`, `services/dungeon_service.py` |
| 6 | Stats: expand CombatUnit + wire into combat | `engine/combat.py`, `models/champion.py` |
| 7 | Level-up: caps + ×10/max + gold formula | `services/levelup_service.py`, `commands/` |
| 8 | Summon: weekly rotating region | `services/summon_service.py`, `commands/summon_cmd.py` |
| 9 | Shop: `/shop` command | `commands/shop_cmd.py`, `services/shop_service.py` |
| 10 | Profile: champion stats + runes + items page | `commands/profile.py`, `utils/embeds.py` |
