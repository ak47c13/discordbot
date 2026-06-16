# Discord Auto-Battler RPG Bot — Comprehensive Project Context

## Project Overview

This is a full-featured **auto-battler RPG Discord bot** inspired by League of Legends. Players summon champions and items, build teams, engage in automatic turn-based combat, progress through dungeons, participate in raids, and trade in a player-driven economy.

**Tech Stack:**
- **Language:** Python 3.10+
- **Framework:** discord.py (slash commands)
- **Database:** MongoDB with Beanie ODM (async)
- **Combat Engine:** Custom turn-based simulator with status effects, boss mechanics, and dungeon passives
- **Image Generation:** PIL/Pillow for champion banners and battle scenes
- **Asset Library:** Riot Data Dragon (League champion art)
- **Deployment:** PM2 on VPS, environment variables via `.env`

---

## Architecture

### File/Folder Structure

```
discordbot/
├── main.py                          # Bot entry point, cog loader, event handlers
├── config/
│   └── game_config.py              # Centralized game constants (rates, costs, stats)
├── models/                          # Beanie ODM documents (MongoDB schemas)
│   ├── user.py                      # User account, resources, progression
│   ├── champion.py                  # ChampionInstance — summoned champions
│   ├── item.py                      # ItemInstance — equipment for champions
│   ├── team.py                      # Team — 5-slot champion formation
│   ├── battle_session.py            # BattleSession — pre-simulated battle record
│   ├── dungeon.py                   # Dungeon, DungeonFloor, DungeonProgress, DungeonRun
│   ├── raid.py                      # RaidQueue — multiplayer raid lobbies
│   ├── market.py                    # MarketListing — player-to-player trading
│   ├── trade.py                     # Trade — direct offer/accept trades
│   ├── audit_log.py                 # Audit — transaction logging
│   └── processed_interaction.py      # Idempotency — prevent double-processing
├── engine/                          # Combat simulation (no async)
│   ├── combat.py                    # run_battle_with_rounds(), CombatUnit, boss mechanics
│   ├── skill_factory.py             # make_skill() — data-driven skill builder
│   ├── skills.py                    # CHAMPION_SKILLS dict, 170+ champions
│   └── status_effects.py            # Stun, Poison, Burn, Silence, DefenseDown, Shield
├── services/                        # Business logic (mostly async)
│   ├── battle_presentation_service.py  # Display battle round-by-round in Discord
│   ├── dungeon_service.py           # Floor progression, enemy construction, rewards
│   ├── hunt_service.py              # Hunt zone battles, mob generation
│   ├── raid_service.py              # Raid queue creation, joining, resolution
│   ├── summon_service.py            # Gacha pull logic, reward table rolls
│   ├── champion_service.py          # Fusion, leveling, stat calculations
│   ├── item_service.py              # Item management, dropping
│   ├── blacksmith_service.py        # Enhancement, clearing, rerolling
│   ├── market_service.py            # Listing, buying, canceling
│   ├── trade_service.py             # P2P trading workflow
│   └── bulk_service.py              # Bulk fusion, selling
├── commands/                        # Slash command cogs
│   ├── start_cmd.py                 # /start, /daily
│   ├── profile.py                   # /profile, profile viewing
│   ├── champions_cmd.py             # /champions, /fuse-champions, /levelup
│   ├── items_cmd.py                 # /items, /equip, /fuse-items
│   ├── team_cmd.py                  # /team, /team-add, /formation
│   ├── dungeon_cmd.py               # /dungeon-list, /dungeon-enter, /dungeon-resume
│   ├── hunt_cmd.py                  # /hunt (not listed but exists)
│   ├── raid_cmd.py                  # /raid-create, /raid-join, /raid-start
│   ├── summon_cmd.py                # /summon, /summon-rates
│   ├── market_cmd.py                # /market-* commands
│   ├── trade_cmd.py                 # /trade-* commands
│   ├── blacksmith_cmd.py            # /enhance, /clear, /reroll
│   └── help_cmd.py                  # /help
├── data/
│   ├── champion_roster.py           # 170+ champions with skill definitions
│   └── dungeon_seed.py              # 12 dungeons, 200+ floors, seeding logic
├── utils/
│   ├── embeds.py                    # Discord embed builders, color palette
│   ├── battle_embeds.py             # Battle-specific embeds, HP bars
│   ├── image_gen.py                 # Team banner generation (5 champions)
│   ├── battle_image_gen.py          # Battle scene (enemy row + player row)
│   ├── locks.py                     # User-level mutex for transaction isolation
│   ├── db_session.py                # Beanie session helpers
│   └── idempotency.py               # Interaction dedup
├── database/
│   └── connection.py                # MongoDB init_db()
└── tests/                           # pytest suite (20+ test modules)
```

### Layer Connections

```
Discord User → Commands (cogs) 
    ↓
    Services (business logic, db ops)
    ↓
    Models (Beanie documents, validation)
    ↓
    MongoDB
    
    Engine (combat.py) — pure logic, not async
    ↓ (simulation results)
    Services (store in DB, present to Discord)
```

### Database Patterns (Beanie + MongoDB)

- **Indexes:** All models have indexed `discord_id`, composite keys for lookups
- **Sessions:** Transaction-safe via `motor` client sessions (ACID on MongoDB 4.0+)
- **Idempotency:** `ProcessedInteraction` stores interaction IDs to prevent duplicate rewards
- **Locking:** User-level async locks in `utils/locks.py` prevent race conditions
- **Snapshots:** `BattleSession.player_snapshot` and `enemy_snapshot` capture unit state for replay

---

## Data Models

### User
- **discord_id** (str, indexed) — Discord user ID
- **username** (str) — display name
- **gold** (int) — currency
- **summon_tokens** (int) — gacha currency
- **blacksmith_seals** (int) — seal protection for high-level enhancements
- **registered** (bool) — account active
- **stamina** (int) — energy for hunts/dungeons
- **max_stamina** (int) — default 100
- **last_stamina_regen** (datetime) — tracking for passive regen
- **raids_completed** (int) — raid counter
- **rune_shards, rune_fragments** (int) — dungeon-exclusive crafting materials
- **last_daily** (Optional[datetime]) — daily reward tracking
- **created_at** (datetime)

### ChampionInstance
- **owner_id** (str, indexed) — owner's discord_id
- **name** (str) — champion name (e.g., "Garen")
- **rank** (str) — F/E/D/C/B/A/S
- **level** (int) — current level (1 to max per rank)
- **exp** (int) — experience towards next level
- **equipped_in_team** (Optional[str]) — team document ID if in formation
- **formation_slot** (Optional[int]) — 1-5 if in team
- **locked** (bool) — protected from fusion/selling
- **in_trade, in_market** (bool) — state flags
- **favorite** (bool) — user-marked as keeper
- **balance_status** (str) — DRAFT/REVIEWED/TESTED/LIVE/DISABLED
- **riot_id, title, source_roles** — metadata from champion_roster.py

### ItemInstance
- **owner_id** (str, indexed)
- **name** (str) — item name
- **rank** (str) — F/E/D/C/B/A/S
- **enhancement** (int) — 0-15 (risky above 7)
- **main_stat_type** (str) — atk/hp/def/spd
- **main_stat_base** (int) — base value
- **passive_name** (str) — passive identifier (e.g., "lifesteal")
- **secondary_stat_type** (str) — atk_pct, hp_pct, dodge, crit_chance, etc.
- **secondary_stat_value** (int) — stored as int*10 for precision
- **equipped_to** (Optional[str]) — ChampionInstance ID
- **equipment_slot** (Optional[int]) — 1-5 per champion
- **locked, favorite, in_trade, in_market** (bool) — state flags
- **properties:** `is_available`, `is_fusible`, `effective_main_stat()` (considers enhancement)

### Team
- **owner_id** (str, indexed)
- **slots** (list[Optional[str]]) — 5 champion instance IDs (indices 0-4 = positions 1-5)
- **properties:** `active_champions` (non-None slots)

### BattleSession
- **owner_id, guild_id, channel_id, message_id** (str) — Discord context
- **battle_type** (str) — "hunt", "boss", "raid"
- **zone** (str) — hunt zone or dungeon slug
- **status** (str) — CREATING/ACTIVE/VICTORY/DEFEAT/CANCELLED_*/ERROR
- **current_round, max_rounds, simulated_round_count, displayed_round_count** (int)
- **battle_seed** (int) — deterministic RNG seed
- **winner** (int) — 0=players, 1=enemies, -1=pending/draw
- **simulated_rounds** (list[dict]) — all round snapshots
- **player_snapshot, enemy_snapshot** (list[dict]) — unit snapshots for UI
- **rewards_json** (dict) — pre-rolled loot
- **reward_claimed** (bool) — prevents double-claiming
- **entry_cost_json** (dict) — stamina/cost to refund on cancel
- **version, started_at, last_updated_at, finished_at** (audit fields)

### Dungeon / DungeonFloor / DungeonProgress / DungeonRun
- **Dungeon:** slug, name, region, total_floors, unlock_req, is_active, boss_name, boss_passive
- **DungeonFloor:** dungeon_slug, floor_num, enemies (list of dicts), boss_floor, boss_passive, hazard (wound/berserker/armored/speed_seal/double_strike), checkpoint_floor, reward_gold, reward_xp, extra_drop_chance
- **DungeonProgress:** owner_id, dungeon_slug, highest_floor, checkpoint_floor, completions, first_clear_at, last_daily_at, last_attempt_at
- **DungeonRun:** owner_id, dungeon_slug, floor_num, team_snapshot, result (win/loss/fled), damage_dealt, rewards_given, hazard, boss_passive

### RaidQueue
- **zone** (str) — hunt zone
- **leader_id** (str) — raid creator
- **player_ids** (list[str]) — discord_ids of participants
- **player_champions** (dict) — discord_id → champion instance id
- **status** (str) — waiting/in_progress/completed/failed
- **rewarded_player_ids** (list[str]) — idempotency guard
- **created_at, started_at, completed_at** (datetime)

### MarketListing
- **seller_id** (str, indexed)
- **champion_id, item_id** (Optional[str]) — exactly one set
- **price** (int) — asking price
- **listing_fee_paid** (int) — 2% of price
- **status** (str) — active/sold/cancelled
- **buyer_id** (Optional[str])
- **created_at, completed_at** (datetime)

---

## Game Systems

### Champion System

#### Ranks
Seven ranks in strict progression: **F → E → D → C → B → A → S**

Each rank has:
- **Base stats** (HP, ATK, DEF, SPD) defined in `CHAMPION_BASE_STATS`
- **Per-level growth** multiplier in `CHAMPION_GROWTH_STATS`
- **Max level** in `CHAMPION_MAX_LEVEL` (F:20, E:30, D:40, C:50, B:60, A:70, S:80)

#### Base Stats by Rank (at level 1)
```
F:  HP=500  ATK=40   DEF=20  SPD=80
E:  HP=800  ATK=65   DEF=32  SPD=85
D:  HP=1200 ATK=100  DEF=50  SPD=90
C:  HP=1800 ATK=150  DEF=75  SPD=95
B:  HP=2600 ATK=220  DEF=110 SPD=100
A:  HP=3800 ATK=320  DEF=160 SPD=105
S:  HP=5500 ATK=460  DEF=230 SPD=110
```

#### Per-Level Growth (multiplied by level-1)
```
F:  HP+30   ATK+3   DEF+1   SPD+0
E:  HP+50   ATK+5   DEF+2   SPD+0
D:  HP+80   ATK+8   DEF+3   SPD+0
C:  HP+120  ATK+12  DEF+5   SPD+0
B:  HP+180  ATK+18  DEF+8   SPD+0
A:  HP+260  ATK+26  DEF+12  SPD+0
S:  HP+380  ATK+38  DEF+18  SPD+0
```

#### Summoning
- **Single summon:** 100 tokens (10x = 950 tokens, 5% savings)
- **Starter:** 950 tokens + 500 gold
- **Pull rates** (SUMMON_RATES):
  - Champion F: 40%, E: 25%, D: 15%, C: 8%, B: 4%, A: 2%, S: 0.5%
  - Item D+: small chance (0.025-0.015%)
  - Gold small: 3%, enhance_mat: 2.5%, reroll_mat: 1.5%, seal: 0.1%

#### Leveling
- Cost: 20 gold per level
- Max level determined by rank
- XP threshold per level: `100 + (level-1)*50`
- Level-up grants no immediate stat boost (continuous formula)

#### Fusion (Combining)
- **Cost:** F→E:100g, E→D:200g, D→C:400g, C→B:800g, B→A:1600g, A→S:3200g
- **Mechanic:** Combine 3 identical same-rank champions → 1 of next rank
- **Level:** Result gets max level of the 3 fused (or custom logic)
- **Requirement:** Champions must be available (not locked, equipped, in trade/market)

#### Aura/Visual Levels
- Levels 0-6: no aura
- Levels 7-9: ✨
- Levels 10-11: 💫
- Levels 12-14: 🌟
- Level 15+: ⭐

### Item System

#### Rarity (Rank)
Same 7 ranks as champions (F→S). Items drop from hunts, dungeons, raids, or summons.

#### Main Stats
Each item has one **main stat type** (atk/hp/def/spd) with a base value that scales by rank and enhancement:

```
Base values by rank (before enhancement):
F:  20     E:  35     D:  55     C:  80
B:  115    A:  165    S:  240
```

Effective main stat = `base * (1 + ENHANCEMENT_MULTIPLIER[enhancement_level])`

#### Enhancement
- **Range:** 0-15
- **Safe range:** 0-7 (100% success)
- **Risky range:** 8-15 (declining success rates, 20%-50%, destruction on failure)
- **Cost:** `max(10, 10 * (current_level + 1))` gold per attempt
- **Materials:** `ENHANCEMENT_MAT_COST[level]` enhance_mats per attempt
- **Protection:** Blacksmith's Seal prevents destruction on failure above +7
- **Clearing:** Reset to +0 (costs `20 * rank_index * enhancement gold`), keeps secondary stat, makes item fusible

#### Clearing Success Rates
```
+0→+1: 100%    +1→+2: 100%    +2→+3: 95%     +3→+4: 90%
+4→+5: 85%     +5→+6: 80%     +6→+7: 75%     +7→+8: 60%
+8→+9: 50%     +9→+10: 40%    +10→+11: 30%   +11→+12: 25%
+12→+13: 20%   +13→+14: 15%   +14→+15: 10%
```

#### Secondary Stats
Each item rolls **one secondary stat type** (atk_pct, hp_pct, def_pct, crit_chance, crit_dmg, accuracy, dodge, lifesteal, boss_dmg, mob_dmg, speed, gold_find) with a value range determined by rank:

```
F: 1.0%-3.0%     E: 2.0%-5.0%     D: 3.5%-7.5%
C: 5.0%-10.0%    B: 7.0%-14.0%    A: 10.0%-20.0%    S: 15.0%-30.0%
```

Stored as int*10 internally (e.g., 25 = 2.5%).

#### Rerolling
- **Full reroll** (type + value): costs `50-600 gold` by rank
- **Value reroll** (type stays): costs `25-300 gold` by rank
- Both show preview before committing

#### Fusion
- 3 identical same-rank +0 items → 1 of next rank, +0
- Cost: `50-1600 gold` by rank

### Battle System

#### Core Flow: `run_battle_with_rounds()`

1. **Initialization:** Build player team and enemy team as `CombatUnit` instances
2. **Main loop** (up to 50 rounds):
   - Apply boss mechanics (shield, adds, enrage, reflect)
   - Apply dungeon boss passives (round-start hooks)
   - Determine turn order by speed/rank/level/RNG
   - Each unit attacks: basic skill (mana < 100) or ultimate (mana = 100)
   - Apply status effects (poison damage, burn, expiry)
   - Reflect damage back to attacker
   - Dodge mechanic (block damage retroactively)
   - Apply round-end boss passives
   - Check win/loss/stalemate conditions
   - Snapshot round state
3. **Output:** `BattleResult` with winner, rounds, log, surviving units

#### CombatUnit Fields
- **Identity:** unit_id, name, rank, level, position (1-5), team (0=player, 1=enemy)
- **Stats:** hp, hp_max, atk, def_stat, spd, mana (0-100)
- **Skills:** basic_fn, ultimate_fn (callables)
- **Effects:** status_effects (list of Stun/Poison/Burn/Silence/DefenseDown/Shield)
- **Boss flags:** is_boss, mechanic (string slug), mechanic_triggered
- **Dungeon passives:** dodge_chance, undying, undying_rounds, feast_stacks, darius_stacks, converted

#### Skill System

Data-driven via `skill_factory.py`. Each skill is a function returning mana gain:
- **Basic skills:** return mana gain (typically 20-30), used below 100 mana
- **Ultimates:** return 0 (consumes all 100 mana), auto-cast when mana full

Skills defined in `CHAMPION_ROSTER[champion_name]["basic"]` and `["ultimate"]` as dicts with:
- `name, targeting, damage_type, coeff, hits, mana_gain, heal_coeff, shield_coeff, status, status_duration, status_chance`

**Targeting options:**
- front/back/weakest/strongest/random/all (enemies)
- self/all_allies/weakest_ally/random_ally (allies)

**Damage types:**
- physical: `atk * coeff * (1 - def_mitigation)` where `mitigation = def / (def + 200)`
- magic: `atk * coeff * 1.1 * 0.85` (ignores ~15% def)
- true: `atk * coeff` (ignores defense)
- none: no damage

**Status effects:** stun (1-turn max on bosses), poison, burn, silence, defense_down (25% reduction)

#### Boss Mechanics (Hunt Zones)

All are triggered by zone-based config in `BOSS_MECHANICS`:

1. **Forest (Shield):**
   - At round 1: boss gains shield = 20% of max HP
   - Shield absorbs damage until depleted

2. **Dungeon (Adds):**
   - At round 10: spawn 2 minions (30% of boss HP/ATK/DEF each)
   - Minions inherit boss skills

3. **Castle (Reflect):**
   - When boss takes damage, reflects 15% back to attacker
   - Reflection damage is pure

4. **Abyss (Enrage):**
   - At round 30: boss's ATK × 2.0
   - Permanently active

#### Dungeon Boss Passives (12 Named Bosses)

Applied every round via hooks in `combat.py`:

1. **Garen** (garen_passive):
   - Each round start: heal 5% max HP

2. **Darius** (darius_passive):
   - Each round start: +8% ATK (stacking), Hemorrhage stacks visible

3. **Jarvan IV** (jarvan_passive):
   - Round 1: gain 25% max HP shield (Demacian Standard)

4. **Cho'Gath** (chogath_passive):
   - Each round start: +5% max HP permanently, stack counter shown

5. **Sejuani** (sejuani_passive):
   - Round 3: stun your highest-ATK unit for 1 round (Permafrost)

6. **Swain** (swain_passive):
   - Each round end: drain 8% of your team's total HP, boss heals

7. **Yasuo** (yasuo_passive):
   - 50% chance to dodge incoming damage (Way of the Wanderer)

8. **Tryndamere** (tryndamere_passive):
   - If defeated, survive at 1 HP for 2 rounds (Undying Rage)

9. **Mordekaiser** (mordekaiser_passive):
   - Defeated player champions rise to fight for the boss (Realm of Death)

10. **Jayce** (jayce_passive):
    - Odd rounds: Cannon form (ATK ×1.4, DEF ×0.6)
    - Even rounds: Hammer form (ATK ×0.6, DEF ×1.4)

11. **Gangplank** (gangplank_passive):
    - Rounds 5, 10, 15: blast your team for 15% current HP each

12. **Irelia** (irelia_passive):
    - When a boss-side ally dies: heal 20% max HP (Bladesurge)

#### Floor Hazards (Dungeon-only)

Applied when fighting a dungeon floor (not hunt zones):

- **wound:** team enters at 70% HP
- **berserker:** enemies +30% ATK, -20% DEF
- **armored:** enemies +40% DEF
- **speed_seal:** all units SPD set to 50
- **double_strike:** enemies strike twice per turn (implemented via extra hit)

#### Formation Bonuses

Applied before battle to `CombatUnit` stats:

```
Slots 1-2 (front row):  DEF +10%
Slots 3-5 (back row):   ATK +5%
```

### Dungeon System

#### Overview
12 permanent dungeons across 8 League regions. Players progress floor-by-floor, saving at checkpoints, fighting progressively harder enemies and unique boss mechanics.

#### Dungeons (DUNGEON_DEFS)

| Slug | Name | Region | Floors | Boss | Passive | Unlock | Rank |
|------|------|--------|--------|------|---------|--------|------|
| demacia-outskirts | Demacia Outskirts | demacia | 20 | Garen | garen_passive | — | F |
| noxus-warfront | Noxus Warfront | noxus | 20 | Darius | darius_passive | — | F |
| ionia-temple-trials | Ionia Temple Trials | ionia | 20 | Irelia | irelia_passive | — | F |
| freljord-wilds | Freljord Wilds | freljord | 20 | Sejuani | sejuani_passive | — | F |
| demacias-depths | Demacia's Depths | demacia | 40 | Jarvan IV | jarvan_passive | demacia-outskirts | D |
| noxian-conquest | Noxian Conquest | noxus | 40 | Swain | swain_passive | noxus-warfront | D |
| ionian-war | Ionian War | ionia | 40 | Yasuo | yasuo_passive | ionia-temple-trials | D |
| freljord-siege | Freljord Siege | freljord | 40 | Tryndamere | tryndamere_passive | freljord-wilds | D |
| void-incursion | Void Incursion | void | 50 | Cho'Gath | chogath_passive | ANY_40 | B |
| shadow-isles | Shadow Isles | shadow-isles | 50 | Mordekaiser | mordekaiser_passive | ANY_40 | B |
| piltover-uprising | Piltover Uprising | piltover | 35 | Jayce | jayce_passive | ANY_20 | C |
| bilgewater-docks | Bilgewater Docks | bilgewater | 35 | Gangplank | gangplank_passive | ANY_20 | C |

**Unlock Requirements:**
- 20F dungeons: always available
- 40F dungeons: complete their corresponding 20F (Demacia→Demacia's Depths, etc.)
- Void/Shadow Isles (50F): complete any 40F dungeon
- Piltover/Bilgewater (35F): complete any 20F dungeon

#### Floor Scaling

Enemy stats computed at battle time from base formula:

```
floor_hp = base_hp * (1 + DUNGEON_HP_SCALE_PER_FLOOR * floor_num)
floor_atk = base_atk * (1 + DUNGEON_ATK_SCALE_PER_FLOOR * floor_num)
floor_def = base_def * (1 + DUNGEON_DEF_SCALE_PER_FLOOR * floor_num)

Boss floors: HP ×1.5, ATK ×1.3
```

Constants:
- `DUNGEON_HP_SCALE_PER_FLOOR = 0.08` (8% per floor)
- `DUNGEON_ATK_SCALE_PER_FLOOR = 0.06` (6% per floor)
- `DUNGEON_DEF_SCALE_PER_FLOOR = 0.04` (4% per floor)

#### Enemy Composition

Per-floor enemy roster drawn from region roster (e.g., Demacia has Garen, Lux, Fiora, etc.). Each floor randomly selects 2-4 champions, scaled to the floor's rank.

Boss floors (every 10th floor) feature the region's unique boss with special passive mechanic.

#### Checkpoints
Every 10 floors (10, 20, 30, ...). Players can retreat from a floor and resume at the last checkpoint.

#### Rewards (Per Floor)

**Base rewards:**
- Gold: `50 + 15*floor_num`
- XP: `20 + 8*floor_num`
- Rune shard (10% chance per floor)
- Rune fragment (2% chance per floor)

**First-clear bonus** (one-time per dungeon):
```
20F: 500 gold, 100 tokens
35F: 1000 gold, 200 tokens
40F: 1500 gold, 300 tokens
50F: 3000 gold, 500 tokens
```

**Daily-clear bonus** (once per day per dungeon):
```
20F: 200 gold
35F: 400 gold
40F: 700 gold
50F: 1200 gold
```

**Champion drops:** Slight chance to drop champions matching floor rank (via drop table rolls).

#### Stamina Costs
- Entry: 2 stamina
- Boss retry: 1 stamina (attempting boss floor again after defeat)
- No cost for floor retries at non-boss floors

#### Progression Tracking (DungeonProgress)
- `highest_floor` — furthest reached (even if retreated)
- `checkpoint_floor` — last safe checkpoint
- `completions` — times fully cleared
- `first_clear_at` — when 100% first time
- `last_daily_at` — last time daily bonus was claimed

### Raid System

#### Mechanics
- **Creation:** `/raid-create <zone>` opens a queue for up to 5 players
- **Joining:** `/raid-join <raid_id> <champion_number>` — player submits 1 champion
- **Starting:** Leader uses `/raid-start <raid_id>` when ready or timeout (5 min)
- **Battle:** All player champions in random order vs scaled boss
- **Scaling:** Boss HP/ATK scales by party size (rough 1.5-2.0x multiplier)
- **Rewards:** Personal loot per player (gold, items, tokens)

#### RaidQueue Model
- **leader_id, player_ids, player_champions** (discord_id → champion_id mapping)
- **status:** waiting → in_progress → completed/failed
- **rewarded_player_ids:** tracks who already got loot (idempotency)

#### Raid Boss
Uses the zone's boss config from HUNT_ZONES, same mechanics as hunt zone bosses.

### Economy

#### Gold Sources
- Hunt kills: `10-50` gold per mob (zone-multiplied)
- Hunt bosses: `200-500` gold (zone-multiplied)
- Dungeon floors: `50 + 15*floor`
- Elite mobs: `200-600` gold
- Raid completion: `300-800` gold per player
- Market sales (after 5% tax)
- Bulk selling champions/items (varies by rank)

#### Gold Sinks
- Champion leveling: 20 gold/level
- Champion fusion: 100-3200 gold by rank
- Item fusion: 50-1600 gold by rank
- Item enhancement: 10-200+ gold per attempt
- Item clearing: 0 (safe) to high (enhanced items)
- Market listing fee: 2% of list price (upfront, non-refundable)
- Market tax: 5% of sale price (taken from buyer)
- Rerolling: 25-600 gold by rank/type
- Blacksmith operations (mats required, not gold)

#### Summon Tokens
**Sources:**
- Daily reward: 50 tokens
- Boss kills: 10-30 tokens (hunt/dungeon)
- Raid completion: 50-100 tokens
- Summon: rolls small chance (~3%)
- Starter bonus: 950 tokens

**Sinks:**
- Single summon: 100 tokens
- 10-summon: 950 tokens (5% discount)

#### Materials
- **Enhance mats:** dropped in hunt/dungeon/raid; required for item enhancement
- **Reroll mats:** dropped; required for secondary stat rerolls
- **Rune shards/fragments:** dungeon-exclusive; used for future evolution system
- **Blacksmith seals:** rare drops; prevent item destruction on risky enhances

#### Market Economy
- **Listing fee:** 2% of list price, paid upfront (non-refundable even if unsold)
- **Sales tax:** 5% of sale price paid by buyer
- **Net to seller:** price - fee
- **Net to buyer:** price * 1.05 gold spent
- Listings auto-expire after 7 days (not enforced yet)

#### Stamina System
- **Max:** 100
- **Regeneration:** +1 per 6 minutes (STAMINA_REGEN_SECONDS = 360)
- **Costs:** 5-40 per hunt zone; 2 per dungeon entry
- **Passive regen:** tracked via last_stamina_regen timestamp

### Summon System (Gacha)

#### Rates (SUMMON_RATES)
```
Champions:
  F: 40.0%   E: 25.0%   D: 15.0%   C: 8.0%
  B: 4.0%    A: 2.0%    S: 0.5%

Items:
  D: 2.5%    C: 1.5%    B: 0.5%

Other:
  gold_small (200-500): 3.0%
  enhance_mat: 2.5%
  reroll_mat: 1.5%
  seal: 0.1%
```

#### Pull Results
Each pull rolls a weighted random outcome, then if champion/item, rolls rank and specific champion/item from roster.

- **Champions:** rolled from CHAMPION_ROSTER (170+ champions)
- **Items:** generated with random main stat, random passive, random secondary stat
- **Gold/Mats:** direct award

#### Drop Tables (Reward Rolls)

**Normal mobs:**
- Gold: 10-50 (100% chance)
- Champion F: 2% chance
- Item F: 5% chance
- Enhance mat: 15% chance, 1-2x
- Reroll mat: 8% chance
- Seal: 0.05% chance

**Elite mobs:**
- Gold: 200-600 (100%)
- Champion (F-E): 25%
- Item (F-E): 30%
- Seal: 0.5%
- Enhance mat: 60%, 3-8x
- Reroll mat: 40%, 1-3x

**Bosses:**
- Gold: 200-500 (100%)
- Champion: 10% (rank from config)
- Item: 15%
- Seal: 1%
- Enhance mat: 40%, 5-15x
- Reroll mat: 20%, 2-5x
- **Summon token: 60%, 10-30x** (special to bosses)

**Raids:**
- Gold: 300-800 (100%)
- Champion: 15%
- Item: 20%
- Seal: 2%
- Enhance mat: 50%, 8-20x
- Reroll mat: 25%, 3-8x
- **Summon token: 100%, 50-100x** (guaranteed in raids)

---

## Slash Commands

### Account / Profile
- **/start** — register account, claim starter rewards (950 tokens, 500 gold)
- **/profile** [user] — view resources, stamina, team count
- **/daily** — claim daily 50 tokens (once per calendar day)
- **/stamina** — check current stamina and regen rate
- **/leaderboard** — see raid completion rankings (if implemented)

### Champions
- **/champions** [rank=] [name=] — paginated inventory (100 per page or chunked)
- **/champion-info** <number> — detailed stats, portrait, skills
- **/fuse-champions** <name> <rank> — combine 3 same-rank into next rank
- **/champions-bulk-fuse** <name> <rank> <count> — fuse many in sequence
- **/champions-bulk-sell** <rank> — sell all of a rank (bulk price)
- **/champions-duplicates** — list fusion-ready sets
- **/levelup** <number> — spend gold to level up
- **/lock-champion** <number> — protect from fusion/selling
- **/champion-favorite** <number> — mark as keeper

### Items
- **/items** [rank=] [name=] — paginated item inventory
- **/item-info** <number> — detailed item stats and passive
- **/equip** <item_number> <champion_number> <slot(1-5)> — attach to champion
- **/unequip** <champion_number> <slot> — remove item
- **/fuse-items** <name> <rank> — combine 3 +0 items of same rank into next
- **/lock-item** <number> — protect item
- **/favorite-item** <number> — mark as keeper
- **/bulk-sell-items** <rank> — sell all of a rank

### Team / Formation
- **/team** — view current 5-slot formation with banner
- **/team-add** <champion_number> <slot(1-5)> — add to slot
- **/team-remove** <slot(1-5)> — remove from slot
- **/formation set** <slot> <position> — reorder (not fully implemented)

### Hunt / Combat
- **/hunt** <zone(forest/dungeon/castle/abyss)> — fight mobs in zone
- **/hunt-auto** <zone> <count> — repeat hunt N times (if implemented)

### Dungeon
- **/dungeon-list** — view all 12 dungeons, your progress, unlock status
- **/dungeon-enter** <dungeon_slug> — start floor 1 or resume from checkpoint
- **/dungeon-resume** <dungeon_slug> — explicitly resume from checkpoint
- **/dungeon-floor-info** <dungeon_slug> <floor> — enemy composition, hazard, boss info
- **/dungeon-rewards** <dungeon_slug> — show first-clear and daily bonuses

### Raid
- **/raid-create** <zone> — open raid queue (you become leader)
- **/raid-list** — see open raids
- **/raid-join** <raid_id> <champion_number> — join a queue
- **/raid-status** <raid_id> — check queue status and player list
- **/raid-start** <raid_id> — leader initiates battle (requires 2+ players or auto-wait 5 min)
- **/raid-leave** <raid_id> — exit queue (leader can't leave without disbanding)

### Summon
- **/summon** [multi=false] — pull 1 (or 10) champions/items
- **/summon-rates** — display gacha rates table

### Market
- **/market-list-champion** <champion_number> <price> — list champion
- **/market-list-item** <item_number> <price> — list item
- **/market-browse** [type=both] — see active listings
- **/market-search** <name> — filter by champion/item name
- **/market-buy** <listing_id> — purchase (costs listed price + 5% tax)
- **/market-my-listings** — see your active listings
- **/market-cancel** <listing_id> — delist (recover 98% of fee if unsold immediately)

### Trade
- **/trade-offer** <target_user> <give_champion_number> <get_champion_number> — propose swap
- **/trade-accept** <trade_id> — accept offer
- **/trade-decline** <trade_id> — reject offer
- **/trade-cancel** <trade_id> — withdraw offer
- **/trade-list** [user=] — see pending trades

### Blacksmith
- **/enhance** <item_number> [use_seal=false] — +1 enhancement
- **/clear** <item_number> — reset to +0
- **/reroll** <item_number> — randomize secondary stat type AND value
- **/refine** <item_number> — randomize secondary stat VALUE only (keep type)

### Help / Meta
- **/help** [topic] — game guide (getting-started, champions, items, blacksmith, combat, economy, raids, commands)

---

## UI/UX Systems

### Battle Presentation (`battle_presentation_service.py`)

**Sequence:**
1. `simulate_and_store()` — run full battle, store in BattleSession
2. `start_presentation()` — send initial Discord message with cancel button
3. `advance_and_display()` — edit message to show next round (batched)
4. `finalize()` — display victory/defeat, grant rewards
5. `cancel_battle()` — mark cancelled, unlock assets

**Timing:**
- Display interval: 0.8 seconds per batch (2 rounds per edit)
- Hunt: 0.7s/round
- Elite: 1.0s/round
- Boss: 1.0s/round
- Raid: 1.5s/round
- Fast mode: 0.3s/round (for testing)

**Embed Architecture:**
- Initial embed: Loading screen with team banner and zone info
- Round embeds: HP bars, mana states, event log (truncated to fit 2048 char limit)
- Final embed: Victory/defeat message, rewards (pre-rolled and claimed on command)

### Battle Image Generation (`battle_image_gen.py`)

Generates a PNG with:
- **Enemy row** (top): 5 enemy cards with portraits, HP/mana bars, status icons
- **Player row** (bottom): 5 player cards (same format)
- **Colors:** rank-based borders (F:gray, E:green, D:blue, C:purple, B:red, A:gold, S:magenta)
- **Caching:** Downloaded Riot Data Dragon portraits stored in `/tmp/champion_art/`

### Team Banner Generation (`image_gen.py`)

Stitches up to 5 champion loading screen portraits side-by-side with rank borders. Dimensions:
- Card: 220×400 pixels
- Total: ~1100×450 with padding
- Cached in `/tmp/champion_art/`

### Embed Color Palette (`embeds.py`)

```python
COLOR_INFO      = 0x5865F2   # Discord blurple
COLOR_SUCCESS   = 0x00CC44   # Green
COLOR_WARNING   = 0xFF8800   # Orange
COLOR_DANGER    = 0xFF3333   # Red
COLOR_GOLD      = 0xFFD700   # Gold

RANK_COLORS:
  F: 0x888888   E: 0x44BB44   D: 0x4488FF   C: 0xAA44FF
  B: 0xFF4444   A: 0xFFAA00   S: 0xCC44FF
```

### Interactive Views

- **ConfirmView** — Yes/No buttons with timeout
- **SummonRevealView** — paginated summon results (10-pull reveal)
- **PaginatedChampionView** — browse champion inventory
- **CancelBattleView** — cancel battle mid-fight
- **RerollPreviewView** — preview item reroll before committing

### HP/Mana Display
- Progress bar: 16 chars, filled/empty blocks
- Compact mana: `"Garen 75/100"`
- Status icons: 🟢 (OK) 🟡 (warning) 🔴 (critical) 🚨 (danger) ☠️ (dead)

---

## Known Flaws & Design Debt

### Silent Truncation Issues
1. **Round event logs:** `BattleSession.simulated_rounds` events truncated to 2048 chars when displayed (Discord embed limit). Late-round events may be silently dropped.
2. **Champion/item count:** `/champions` and `/items` paginate but don't warn if total exceeds pagination limit.
3. **Dungeon floor list:** If a dungeon has 100+ floors with hazards, no UI shows all hazard info — truncated in embed.

### Incomplete Implementations
1. **Dungeon seeding:** `dungeon_seed.py` structure exists but `seed_dungeons()` may not be fully hooked into startup.
2. **Leaderboard:** `/leaderboard` command stub exists but has no real logic for raid ranking.
3. **Auto-hunt:** `/hunt-auto` mentioned in help but not in commands cogs.
4. **Trading restrictions:** Min account age (24 hours) configured but not enforced in `trade_service.py`.
5. **Listing expiry:** Market listings have no auto-expiry after 7 days (configurable but not used).
6. **Formation set:** `/formation set` command stubbed but doesn't actually reorder slots.

### Potential Race Conditions
1. **Concurrent hunts:** If user launches 2 hunts simultaneously before first completes, stamina could be deducted twice. Mitigated by user-level locks but lock contention not tested.
2. **Dungeon checkpoint save:** If user defeats floor and bot crashes during checkpoint write, progress may be lost.
3. **Market simultaneous buys:** Two buyers could both see a listing and buy it; the second buy should fail gracefully but error handling untested.

### Missing Error Handling
1. **Image generation failures:** If Riot Data Dragon is down, battle banners fail silently (caught Exception, no retry/fallback).
2. **Database transient failures:** `start_transaction()` on MongoDB doesn't retry on transient network errors.
3. **Discord rate limits:** Battle presentation edits may hit rate limit (15 edits max per battle); no backoff implemented.
4. **Very large teams:** Battles with 50+ units may timeout before 50-round limit; no graceful degradation.

### UX Dead Ends
1. **Unfusible duplicates:** User can summon 2 D-rank champions of the same name but can't fuse them (need 3); no "find fusions in progress" helper.
2. **Equip UI lag:** When user equips an item, the command doesn't show updated stats until next `/champion-info` call.
3. **Team slot drag:** No reordering UI (would need ephemeral buttons); users must remove and re-add.
4. **Item secondary stat ambiguity:** Secondary stat values stored as int*10 but not always displayed as decimal (e.g., "45" shown instead of "4.5%").

### Economy Balance Concerns
1. **Gold inflation:** Boss hunts in abyss zone yield 5x multiplier (1000-2500 gold each), but fusion costs scale linearly. Late-game gold can be trivial.
2. **Item scarcity:** D-rank item summon rate only 2.5%; mid-game players may be under-equipped.
3. **Summon token sink:** No long-term use for excess tokens (max 2 multi-pulls per daily reset); could add cosmetics or paid rerolls.
4. **Seal rarity:** 0.1% base drop rate; high-level enchanting effectively requires luck not skill/time investment.
5. **Raid scaling:** Boss HP/ATK scaling by party size not dynamic; a 1-player raid is trivial.

### Performance Issues
1. **Champion roster:** 170+ champions, each with 2 skills, 12 dungeon bosses with passives — large in-memory footprint on bot startup.
2. **Battle simulation:** 50-round battles with 10 units can be slow; no async awaiting in combat engine.
3. **Pagination:** `/champions` with 500+ champions loads all into memory; should use cursor pagination.
4. **Image caching:** `/tmp/champion_art/` can grow unbounded; no cache eviction policy.

### Inconsistencies
1. **Rank naming:** Internally "S-rank" but in some UX shown as "[S]" vs "S" vs "SS-rank".
2. **Abbreviations:** Some messages use "Lv." others use "Level"; inconsistent emoji across commands.
3. **Time zones:** User created_at stored in UTC but profile doesn't show it in their timezone.
4. **Damage rounding:** Some skills round down, others truncate; affects critical hit calcs.

### Missing Validation
1. **Champion level cap:** No runtime check that champion level never exceeds CHAMPION_MAX_LEVEL[rank].
2. **Item enhancement limit:** No validation that enhancement never exceeds 15.
3. **Negative gold/tokens:** If a database record is corrupted, no guardrails prevent negative balance operations.
4. **Team size:** Team model allows empty slots but no validation that champion_id is unique in slots.

---

## Configuration Constants

Key values from `game_config.py`:

```python
# Stamina
STAMINA_REGEN_SECONDS = 360                 # 6 minutes per 1 stamina

# Summon economy
SUMMON_TOKEN_COST = 100
SUMMON_MULTI_COST = 950
STARTER_SUMMON_TOKENS = 950
STARTER_GOLD = 500
DAILY_SUMMON_TOKENS = 50

# Fusion
CHAMPION_FUSION_COST = {E:100, D:200, C:400, B:800, A:1600, S:3200}
ITEM_FUSION_COST = {E:50, D:100, C:200, B:400, A:800, S:1600}

# Enhancement
ENHANCEMENT_SAFE_MAX = 7
ENHANCEMENT_SUCCESS_RATE = {0:1.0, ..., 14:0.1}
enhancement_gold_cost(level) = max(10, 10*(level+1))
ENHANCEMENT_MAT_COST = {0:1, ..., 14:20}

# Leveling
LEVEL_UP_GOLD_COST = 20
CHAMPION_MAX_LEVEL = {F:20, E:30, D:40, C:50, B:60, A:70, S:80}
champion_xp_threshold(level) = 100 + (level-1)*50

# Dungeon
DUNGEON_STAMINA_COST = 2
DUNGEON_BOSS_RETRY_COST = 1
DUNGEON_HP_SCALE_PER_FLOOR = 0.08
DUNGEON_ATK_SCALE_PER_FLOOR = 0.06
DUNGEON_DEF_SCALE_PER_FLOOR = 0.04
DUNGEON_BOSS_HP_MULT = 1.5
DUNGEON_BOSS_ATK_MULT = 1.3

# Dungeon rewards
DUNGEON_FLOOR_GOLD_BASE = 50
DUNGEON_FLOOR_GOLD_PER_FLOOR = 15
DUNGEON_FLOOR_XP_BASE = 20
DUNGEON_FLOOR_XP_PER_FLOOR = 8
DUNGEON_RUNE_SHARD_CHANCE = 0.10
DUNGEON_RUNE_FRAGMENT_CHANCE = 0.02

# Market
MARKET_LISTING_FEE_PCT = 0.02       # 2%
MARKET_TAX_PCT = 0.05               # 5%

# Raid
RAID_MAX_PLAYERS = 5
RAID_QUEUE_TIMEOUT_SECONDS = 300

# Combat
MAX_ROUNDS = 50
MANA_MAX = 100
MANA_ULTIMATE_THRESHOLD = 100
TEAM_SIZE = 5

# Battle display
BATTLE_DISPLAY_INTERVALS = {hunt:0.7, elite:1.0, boss:1.0, raid:1.5}
DISPLAY_BATCH_SIZE = 2
DISPLAY_INTERVAL = 0.8
DISPLAY_MAX_UPDATES = 15

# Hunt zones (forest, dungeon, castle, abyss)
# Example: forest costs 5 stamina, forest boss is "Forest Troll" (E-rank, Lv5)
HUNT_ZONES[zone]["stamina_cost"]       # 5, 10, 20, 40
HUNT_ZONES[zone]["gold_multiplier"]    # 1.0x, 1.5x, 2.5x, 5.0x

# Sell prices
SELL_PRICE_CHAMPION = {F:50, E:150, D:400, C:1000, B:2500, A:6000, S:15000}
SELL_PRICE_ITEM = {F:30, E:90, D:240, C:600, B:1500, A:3600, S:9000}

# Trading restrictions
TRADING_MIN_ACCOUNT_AGE_HOURS = 24
```

---

## Deployment

### Environment Variables (`.env`)
```bash
DISCORD_TOKEN=your_token_here
GUILD_ID=123456789              # Optional: guild for faster command sync
MONGODB_URI=mongodb+srv://...   # MongoDB connection string
DEBUG=false
```

### Database Setup
1. Create MongoDB cluster (MongoDB Atlas or self-hosted)
2. Ensure MongoDB 4.0+ for transaction support
3. Initialize collections via `database/connection.py` on first bot startup
4. `await init_db()` creates indexes automatically (Beanie)

### Running the Bot
**Local development:**
```bash
pip install -r requirements.txt
python main.py
```

**Production (PM2):**
```bash
pm2 start main.py --name discordbot --max-memory-restart 500M
pm2 save
pm2 startup
```

**Systemd alternative:**
```bash
[Unit]
Description=Discord Auto-Battler Bot
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/discordbot
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Database Indexes
Auto-created by Beanie on model definition. Key indexes:
- `discord_id` (all player-owned documents)
- `status` (BattleSession, RaidQueue)
- `message_id` (BattleSession for message edits)
- Composite: `(owner_id, rank)`, `(owner_id, dungeon_slug)`, etc.

### Monitoring
- Check bot presence: `await bot.user` in on_ready()
- Monitor battle sessions: query `BattleSession.find(status="ACTIVE")` (should be low count)
- Check MongoDB connection health: `ping()` on motor client
- Discord rate limits: log 429 responses and back off

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **Database** | MongoDB + Beanie (async), 12 document models |
| **Champion Roster** | 170+ League champions, 340+ skills (basic+ultimate) |
| **Dungeons** | 12 permanent dungeons, 200+ floors total, 12 unique boss passives |
| **Combat Engine** | 50-round max, status effects, boss mechanics, formation bonuses |
| **Economy** | Gold, summon tokens, seals, materials; market with fees/taxes |
| **Gacha** | ~20% champion pull rate; 40% F-rank, 25% E, etc. |
| **Hunts** | 4 zones (forest/dungeon/castle/abyss) with difficulty scaling |
| **Raids** | Up to 5-player multiplayer, scaled boss, personal loot |
| **Crafting** | Champion fusion (3→1 per rank), item fusion, enhancement (0-15), rerolling |
| **UI Framework** | Discord.py slash commands, ephemeral interactions, ephemeral embeds |
| **Image Assets** | Riot Data Dragon portraits, locally cached, PIL-generated battle scenes |
| **Test Coverage** | 20+ pytest modules covering combat, fusion, dungeon, economy, etc. |
