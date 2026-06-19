"""
Central configuration for all game rates, costs, drop tables, and multipliers.
Nothing numeric lives in business logic — change values here only.
"""
from datetime import timezone, timedelta

# Philippines Standard Time (UTC+8) — used for all user-facing time display
PHT = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Rank ordering
# ---------------------------------------------------------------------------
RANKS = ["F", "E", "D", "C", "B", "A", "S"]
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}  # F=0 … S=6

# ---------------------------------------------------------------------------
# Champion fusion costs (gold) indexed by resulting rank
CHAMPION_FUSION_COST = {
    "E": 200,
    "D": 500,
    "C": 1200,
    "B": 3000,
    "A": 7500,
    "S": 18000,
}

# ---------------------------------------------------------------------------
# Item fusion costs (gold) indexed by resulting rank
# ---------------------------------------------------------------------------
ITEM_FUSION_COST = {
    "E": 100,
    "D": 250,
    "C": 600,
    "B": 1500,
    "A": 3800,
    "S": 9000,
}

# ---------------------------------------------------------------------------
# Enhancement success rates (+current -> +current+1)
# Key is the CURRENT level (e.g. 0 means attempting +0 -> +1)
# ---------------------------------------------------------------------------
ENHANCEMENT_SUCCESS_RATE = {
    0: 1.00,
    1: 1.00,
    2: 0.95,
    3: 0.90,
    4: 0.85,
    5: 0.80,
    6: 0.75,
    7: 0.60,
    8: 0.50,
    9: 0.40,
    10: 0.30,
    11: 0.25,
    12: 0.20,
    13: 0.15,
    14: 0.10,
}

# Enhancement is risky (destruction on fail) above this level
ENHANCEMENT_SAFE_MAX = 7

# Enhancement stat multipliers: total bonus over base stat at each level
ENHANCEMENT_MULTIPLIER = {
    0: 0.00,
    1: 0.05,
    2: 0.10,
    3: 0.15,
    4: 0.21,
    5: 0.27,
    6: 0.34,
    7: 0.42,
    8: 0.51,
    9: 0.61,
    10: 0.72,
    11: 0.84,
    12: 0.97,
    13: 1.11,
    14: 1.26,
    15: 1.45,
}

# Enhancement gold cost per attempt: base * (level+1), min 50
ENHANCEMENT_GOLD_BASE = 50

def enhancement_gold_cost(current_level: int) -> int:
    return max(50, ENHANCEMENT_GOLD_BASE * (current_level + 1))

# Enhancement material cost per attempt (basic_enhance_mat quantity)
ENHANCEMENT_MAT_COST = {
    0: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3,
    7: 5, 8: 5, 9: 8, 10: 8, 11: 10, 12: 12, 13: 15, 14: 20,
}

# ---------------------------------------------------------------------------
# Clearing costs: gold = CLEAR_GOLD_BASE * rank_index * enhancement_level
# ---------------------------------------------------------------------------
CLEAR_GOLD_BASE = 20

def clearing_gold_cost(rank: str, enhancement: int) -> int:
    if enhancement == 0:
        return 0
    return max(50, CLEAR_GOLD_BASE * (RANK_INDEX[rank] + 1) * enhancement)

# ---------------------------------------------------------------------------
# Reroll costs (gold) by item rank
# ---------------------------------------------------------------------------
REROLL_FULL_COST  = {r: 500  * (RANK_INDEX[r] + 1) for r in RANKS}   # changes type+value
REROLL_VALUE_COST = {r: 250  * (RANK_INDEX[r] + 1) for r in RANKS}   # keeps type, changes value

# ---------------------------------------------------------------------------
# Rank-based champion base stats
# ---------------------------------------------------------------------------
CHAMPION_BASE_STATS = {
    "F": {"hp": 500,  "atk": 40,  "def": 20,  "spd": 80,  "mana": 0},
    "E": {"hp": 800,  "atk": 65,  "def": 32,  "spd": 85,  "mana": 0},
    "D": {"hp": 1200, "atk": 100, "def": 50,  "spd": 90,  "mana": 0},
    "C": {"hp": 1800, "atk": 150, "def": 75,  "spd": 95,  "mana": 0},
    "B": {"hp": 2600, "atk": 220, "def": 110, "spd": 100, "mana": 0},
    "A": {"hp": 3800, "atk": 320, "def": 160, "spd": 105, "mana": 0},
    "S": {"hp": 5500, "atk": 460, "def": 230, "spd": 110, "mana": 0},
}

# Per-level stat growth multipliers applied to base stats
CHAMPION_GROWTH_STATS = {
    "F": {"hp": 30,  "atk": 3,  "def": 1,  "spd": 0},
    "E": {"hp": 50,  "atk": 5,  "def": 2,  "spd": 0},
    "D": {"hp": 80,  "atk": 8,  "def": 3,  "spd": 0},
    "C": {"hp": 120, "atk": 12, "def": 5,  "spd": 0},
    "B": {"hp": 180, "atk": 18, "def": 8,  "spd": 0},
    "A": {"hp": 260, "atk": 26, "def": 12, "spd": 0},
    "S": {"hp": 380, "atk": 38, "def": 18, "spd": 0},
}

# Max level per rank
CHAMPION_MAX_LEVEL = {
    "F": 20, "E": 30, "D": 40, "C": 50, "B": 60, "A": 70, "S": 80,
}

# Exponential gold cost per level: base * growth^(level-1)
RANK_LEVELUP_BASE = {
    "F": 60, "E": 120, "D": 250, "C": 700, "B": 1800, "A": 3800, "S": 7500,
}
RANK_LEVELUP_GROWTH = 1.05
LEVEL_UP_GOLD_COST = 20  # legacy fallback; use levelup_cost() instead


def levelup_cost(rank: str, current_level: int) -> int:
    """Gold cost to go from current_level to current_level+1."""
    base = RANK_LEVELUP_BASE.get(rank, 50)
    return max(1, int(base * (RANK_LEVELUP_GROWTH ** (current_level - 1))))


def levelup_cost_range(rank: str, from_level: int, to_level: int) -> int:
    """Total gold cost to level from from_level to to_level (exclusive end)."""
    return sum(levelup_cost(rank, lvl) for lvl in range(from_level, to_level))

# ---------------------------------------------------------------------------
# Item base stats by rank
# ---------------------------------------------------------------------------
ITEM_BASE_MAIN_STAT = {
    "F": 20,
    "E": 35,
    "D": 55,
    "C": 80,
    "B": 115,
    "A": 165,
    "S": 240,
}

# Secondary stat roll ranges [min, max] by rank (stored *10, so 100 = 10.0%)
# F feels like noise; S visibly changes combat outcomes.
SECONDARY_STAT_RANGE = {
    "F": (5,   15),    # 0.5% - 1.5%
    "E": (10,  25),    # 1.0% - 2.5%
    "D": (20,  40),    # 2.0% - 4.0%
    "C": (35,  65),    # 3.5% - 6.5%
    "B": (55,  95),    # 5.5% - 9.5%
    "A": (80,  140),   # 8.0% - 14.0%
    "S": (120, 200),   # 12.0% - 20.0%
}

SECONDARY_STAT_TYPES = [
    "atk_pct",
    "hp_pct",
    "def_pct",
    "crit_chance",
    "crit_dmg",
    "lifesteal",
    "boss_dmg",
    "mob_dmg",
    "speed",
    "gold_find",
]

# ---------------------------------------------------------------------------
# Market economy
# ---------------------------------------------------------------------------
MARKET_LISTING_FEE_PCT = 0.02   # 2% of listed price, paid upfront
MARKET_TAX_PCT = 0.05           # 5% of sale price taken on purchase

# ---------------------------------------------------------------------------
# Summon / gacha
# ---------------------------------------------------------------------------
SUMMON_TOKEN_COST = 1            # per single pull
SUMMON_MULTI_COST = 10           # 10-pull (gives 11 results — 1 bonus)

# Starter rewards granted on /start registration
STARTER_SUMMON_TOKENS = 10   # enough for 1x10 pull
STARTER_GOLD = 5000

SUMMON_RATES = {
    # (item_or_champion, rank): probability
    "champion_F": 0.470,
    "champion_E": 0.265,
    "champion_D": 0.123,
    "champion_C": 0.057,
    "champion_B": 0.019,
    "champion_A": 0.005,
    "champion_S": 0.001,
    "item_D":     0.025,
    "item_C":     0.015,
    "item_B":     0.005,
    "gold_small": 0.030,   # 200-500 gold
    "enhance_mat":0.025,
    "reroll_mat": 0.015,
    "seal":       0.001,
    "rune":       0.040,   # rune instance (rank rolled from RUNE_SUMMON_RATES)
}

# Item pull rank rates — used when pool_type="item"
ITEM_SUMMON_RATES = {
    "item_F": 0.400,
    "item_E": 0.250,
    "item_D": 0.180,
    "item_C": 0.100,
    "item_B": 0.050,
    "item_A": 0.015,
    "item_S": 0.005,
}

# Within a confirmed rank, single flat roll for item tier.
# Floors enforced: advanced >= C, completed >= B.
ITEM_TIER_UPGRADE_RATES = {
    "F": {"common": 1.00, "advanced": 0.00, "completed": 0.00},
    "E": {"common": 1.00, "advanced": 0.00, "completed": 0.00},
    "D": {"common": 1.00, "advanced": 0.00, "completed": 0.00},
    "C": {"common": 0.93, "advanced": 0.07, "completed": 0.00},
    "B": {"common": 0.80, "advanced": 0.15, "completed": 0.05},
    "A": {"common": 0.65, "advanced": 0.25, "completed": 0.10},
    "S": {"common": 0.45, "advanced": 0.35, "completed": 0.20},
}

# Gold cost to lock a single substat slot (per item rank)
SUBSTAT_LOCK_COST = {
    "F":   500,
    "E":  1_000,
    "D":  3_000,
    "C":  8_000,
    "B": 20_000,
    "A": 50_000,
    "S": 120_000,
}

# Rune pull rank rates — used when pool_type="rune"
RUNE_SUMMON_RATES = {
    "rune_F": 0.450,
    "rune_E": 0.255,
    "rune_D": 0.150,
    "rune_C": 0.080,
    "rune_B": 0.040,
    "rune_A": 0.020,
    "rune_S": 0.005,
}

# Stat multiplier applied to catalog base value based on rune rank
RUNE_RANK_MULTIPLIERS = {
    "F": 0.50,
    "E": 0.70,
    "D": 0.85,
    "C": 1.00,
    "B": 1.20,
    "A": 1.40,
    "S": 1.65,
}

# Token income sources
DAILY_SUMMON_TOKENS = 50
BOSS_KILL_TOKENS = (10, 30)       # min, max
RAID_COMPLETE_TOKENS = (50, 100)

# ---------------------------------------------------------------------------
# Drop tables
# ---------------------------------------------------------------------------
NORMAL_MOB_DROPS = {
    "gold":          {"min": 10,  "max": 50,  "chance": 1.00},
    "champion_F":    {"chance": 0.02},
    "item_basic":    {"chance": 0.20, "ranks": ["F", "E"]},
    "item_advanced": {"chance": 0.03, "ranks": ["F"]},
    "enhance_mat":   {"min": 1, "max": 2, "chance": 0.15},
    "reroll_mat":    {"min": 1, "max": 1, "chance": 0.08},
    "seal":          {"chance": 0.0005},
}

# Elite mob config
ELITE_MOB_STAT_MULTIPLIER = 2.5   # elite HP/ATK vs normal
ELITE_MOB_DROPS = {
    "gold":          {"chance": 1.0, "min": 200,  "max": 600},
    "champion":      {"chance": 0.25, "ranks": ["F", "E"]},
    "item_basic":    {"chance": 0.30, "ranks": ["F", "E"]},
    "item_advanced": {"chance": 0.15, "ranks": ["F", "E"]},
    "seal":          {"chance": 0.005},
    "enhance_mat":   {"chance": 0.60, "min": 3, "max": 8},
    "reroll_mat":    {"chance": 0.40, "min": 1, "max": 3},
}

BOSS_DROPS = {
    "gold":          {"min": 200, "max": 500, "chance": 1.00},
    "champion":      {"chance": 0.10},   # rank determined by boss config
    "item_basic":    {"chance": 0.10, "ranks": ["F", "E"]},
    "item_advanced": {"chance": 0.25, "ranks": ["F", "E", "D"]},
    "enhance_mat":   {"min": 5, "max": 15, "chance": 0.40},
    "reroll_mat":    {"min": 2, "max": 5, "chance": 0.20},
    "seal":          {"chance": 0.01},
    "summon_token":  {"min": 10, "max": 30, "chance": 0.60},
}


# ---------------------------------------------------------------------------
# Hunt zones
# ---------------------------------------------------------------------------
HUNT_ZONES = {
    "forest": {
        "name": "Whispering Forest",
        "min_team_power": 0,
        "power_requirement": 0,
        "recommended_rank": "F",
        "mob_count": (3, 5),
        "elite_chance": 0.10,
        "boss_chance": 0.05,
        "boss_name": "Forest Troll",
        "boss_rank": "E",
        "boss_level": 5,
        "boss_level_mult": 1.0,
        "stamina_cost": 5,
        "gold_multiplier": 1.0,
        "description": "Peaceful woods. Good for beginners.",
    },
    "dungeon": {
        "name": "Dark Dungeon",
        "min_team_power": 500,
        "power_requirement": 0,
        "recommended_rank": "D",
        "mob_count": (4, 6),
        "elite_chance": 0.15,
        "boss_chance": 0.10,
        "boss_name": "Dungeon Lord",
        "boss_rank": "C",
        "boss_level": 15,
        "boss_level_mult": 1.5,
        "stamina_cost": 10,
        "gold_multiplier": 1.5,
        "description": "Treacherous corridors. Bring strong champions.",
    },
    "castle": {
        "name": "Ruined Castle",
        "min_team_power": 2000,
        "power_requirement": 0,
        "recommended_rank": "B",
        "mob_count": (5, 7),
        "elite_chance": 0.20,
        "boss_chance": 0.15,
        "boss_name": "Dark Knight",
        "boss_rank": "B",
        "boss_level": 30,
        "boss_level_mult": 2.0,
        "stamina_cost": 20,
        "gold_multiplier": 2.5,
        "description": "Ancient fortress. Only seasoned warriors survive.",
    },
    "abyss": {
        "name": "The Abyss",
        "min_team_power": 8000,
        "power_requirement": 0,
        "recommended_rank": "S",
        "mob_count": (6, 8),
        "elite_chance": 0.25,
        "boss_chance": 0.20,
        "boss_name": "Void Colossus",
        "boss_rank": "A",
        "boss_level": 60,
        "boss_level_mult": 3.0,
        "stamina_cost": 40,
        "gold_multiplier": 5.0,
        "description": "Absolute darkness. Legendary warriors only.",
    },
}

# Normal mobs: rank used to scale stats per zone
MOB_RANK_BY_ZONE = {
    "forest": "F",
    "dungeon": "E",
    "castle": "C",
    "abyss": "B",
}

# ---------------------------------------------------------------------------
# Boss portrait champions (Riot Data Dragon stand-ins) per zone
# ---------------------------------------------------------------------------
BOSS_PORTRAIT_RIOT_IDS = {
    "forest":  "Maokai",
    "dungeon": "Nocturne",
    "castle":  "Mordekaiser",
    "abyss":   "Chogath",
}

# Riot ID used for raid boss portrait art
RAID_BOSS_PORTRAIT_RIOT_ID = "Aatrox"

# ---------------------------------------------------------------------------
# Combat constants
# ---------------------------------------------------------------------------
MAX_ROUNDS = 50
MANA_MAX = 100
MANA_ULTIMATE_THRESHOLD = 100
TEAM_SIZE = 5

# ---------------------------------------------------------------------------
# Raid
# ---------------------------------------------------------------------------
RAID_MAX_PLAYERS = 5
RAID_QUEUE_TIMEOUT_SECONDS = 300   # 5 min to fill before auto-start
RAID_DAILY_LIMIT = 5               # max raids per reset window per player
RAID_RESET_HOURS = 3               # raid limit resets every 3 hours

# Raid difficulty weights for RNG roll (higher weight = more common)
RAID_DIFFICULTY_WEIGHTS = {
    "F": 35, "E": 25, "D": 18, "C": 11, "B": 6, "A": 3, "S": 2,
}

# Raid boss explicit stat targets — designed for 5 fully-itemized players.
# HP is the full-team (5p) value; _build_raid_boss scales it down for smaller parties.
# ATK/DEF are absolute values fed directly into combat (not multipliers).
# Each tier is ~2–2.5× the previous in effective threat.
RAID_BOSS_STATS = {
    #        hp        atk    def   spd
    "F": {"hp":  40_000, "atk":  450, "def":  180, "spd":  90},
    "E": {"hp":  90_000, "atk":  800, "def":  320, "spd":  92},
    "D": {"hp": 200_000, "atk": 1_400, "def":  560, "spd":  95},
    "C": {"hp": 440_000, "atk": 2_400, "def":  950, "spd":  98},
    "B": {"hp": 950_000, "atk": 4_000, "def": 1_600, "spd": 101},
    "A": {"hp":2_100_000,"atk": 6_500, "def": 2_600, "spd": 104},
    "S": {"hp":4_800_000,"atk":10_500, "def": 4_200, "spd": 108},
}

# F→S raid difficulties — boss stats scale exponentially
# gold/token payouts multiply by ~2.5x per tier; champion/item drop quality rises
RAID_DIFFICULTIES = {
    "F": {
        "display": "F — Skirmish",
        "boss_rank": "F",
        "gold_min": 3_000,   "gold_max":  6_000,
        "token_min": 15,     "token_max": 30,
        "champ_chance": 0.10, "champ_ranks": ["F", "E"],
        "item_chance":  0.15, "item_ranks":  ["F", "E"],
        "seal_chance":  0.02,
    },
    "E": {
        "display": "E — Skirmish+",
        "boss_rank": "E",
        "gold_min":  8_000,  "gold_max": 15_000,
        "token_min": 40,     "token_max": 70,
        "champ_chance": 0.12, "champ_ranks": ["E", "D"],
        "item_chance":  0.18, "item_ranks":  ["E", "D"],
        "seal_chance":  0.04,
    },
    "D": {
        "display": "D — Incursion",
        "boss_rank": "D",
        "gold_min": 20_000,  "gold_max": 40_000,
        "token_min": 100,    "token_max": 180,
        "champ_chance": 0.15, "champ_ranks": ["D", "C"],
        "item_chance":  0.20, "item_ranks":  ["D", "C"],
        "seal_chance":  0.06,
    },
    "C": {
        "display": "C — Siege",
        "boss_rank": "C",
        "gold_min":  50_000, "gold_max": 100_000,
        "token_min": 250,    "token_max": 450,
        "champ_chance": 0.18, "champ_ranks": ["C", "B"],
        "item_chance":  0.22, "item_ranks":  ["C", "B"],
        "seal_chance":  0.09,
    },
    "B": {
        "display": "B — Assault",
        "boss_rank": "B",
        "gold_min": 120_000, "gold_max": 240_000,
        "token_min": 600,    "token_max": 1_100,
        "champ_chance": 0.20, "champ_ranks": ["B", "A"],
        "item_chance":  0.25, "item_ranks":  ["B", "A"],
        "seal_chance":  0.13,
    },
    "A": {
        "display": "A — Conquest",
        "boss_rank": "A",
        "gold_min": 300_000, "gold_max": 600_000,
        "token_min": 1_400,  "token_max": 2_600,
        "champ_chance": 0.22, "champ_ranks": ["A", "S"],
        "item_chance":  0.28, "item_ranks":  ["A", "S"],
        "seal_chance":  0.18,
    },
    "S": {
        "display": "S — Annihilation",
        "boss_rank": "S",
        "gold_min": 750_000, "gold_max":1_500_000,
        "token_min": 3_500,  "token_max": 6_500,
        "champ_chance": 0.25, "champ_ranks": ["A", "S"],
        "item_chance":  0.30, "item_ranks":  ["A", "S"],
        "seal_chance":  0.25,
    },
}

# ---------------------------------------------------------------------------
# Stamina regeneration
# ---------------------------------------------------------------------------
STAMINA_REGEN_SECONDS = 36    # 1 stamina per 36 seconds → full 100 stamina in 1 hour

# ---------------------------------------------------------------------------
# Aura visuals (for embed display)
# ---------------------------------------------------------------------------
AURA_BY_LEVEL = {
    range(0, 7):   "",
    range(7, 10):  "✨",
    range(10, 12): "💫",
    range(12, 15): "🌟",
    range(15, 16): "⭐",
}

AURA_COLOR_BY_RANK = {
    "F": 0x808080,   # Gray
    "E": 0x00AA00,   # Green
    "D": 0x0055FF,   # Blue
    "C": 0x9900CC,   # Purple
    "B": 0xCC0000,   # Red
    "A": 0xFFAA00,   # Gold
    "S": 0xFF00FF,   # Prismatic (magenta as fallback)
}

def get_aura(level: int) -> str:
    for r, symbol in AURA_BY_LEVEL.items():
        if level in r:
            return symbol
    return "⭐"

# ---------------------------------------------------------------------------
# New-account trading restrictions
# ---------------------------------------------------------------------------
TRADING_MIN_ACCOUNT_AGE_HOURS = 24

# ---------------------------------------------------------------------------
# Boss mechanics flags (per zone)
# ---------------------------------------------------------------------------
BOSS_MECHANICS = {
    "forest":  {"mechanic": "shield",  "shield_hp_ratio": 0.20, "enrage_round": 45},
    "dungeon": {"mechanic": "adds",    "add_count": 2,          "enrage_round": 40},
    "castle":  {"mechanic": "reflect", "reflect_ratio": 0.15,   "enrage_round": 35},
    "abyss":   {"mechanic": "enrage",  "enrage_atk_mult": 2.0,  "enrage_round": 30},
}

# ---------------------------------------------------------------------------
# Dungeon rewards
# ---------------------------------------------------------------------------
DUNGEON_FLOOR_GOLD_BASE = 200
DUNGEON_FLOOR_GOLD_PER_FLOOR = 50
DUNGEON_FLOOR_XP_BASE = 20
DUNGEON_FLOOR_XP_PER_FLOOR = 8
DUNGEON_RUNE_SHARD_CHANCE = 0.10     # 10% per floor

# First-clear bonuses by dungeon length
DUNGEON_FIRST_CLEAR = {
    20: {"gold": 5000,  "champion_tokens": 100},
    35: {"gold": 15000, "champion_tokens": 200},
    40: {"gold": 25000, "champion_tokens": 300},
    50: {"gold": 50000, "champion_tokens": 500},
}
DUNGEON_DAILY_CLEAR = {
    20: {"gold": 2000},
    35: {"gold": 5000},
    40: {"gold": 9000},
    50: {"gold": 15000},
}

# Stamina costs
DUNGEON_STAMINA_COST = 2
DUNGEON_BOSS_RETRY_COST = 1

# Floor scaling
DUNGEON_HP_SCALE_PER_FLOOR = 0.08
DUNGEON_ATK_SCALE_PER_FLOOR = 0.06
DUNGEON_DEF_SCALE_PER_FLOOR = 0.04
DUNGEON_BOSS_HP_MULT = 1.5
DUNGEON_BOSS_ATK_MULT = 1.3

# Champion XP / leveling thresholds (exp needed to reach next level)
def champion_xp_threshold(level: int) -> int:
    return 100 + (level - 1) * 50

# ---------------------------------------------------------------------------
# Formation bonuses (applied to CombatUnit before battle)
# ---------------------------------------------------------------------------
FORMATION_BONUSES = {
    # position: {stat: bonus_fraction}
    1: {"def": 0.10},   # front row tank bonus
    2: {"def": 0.10},
    3: {"atk": 0.05},   # back row damage bonus
    4: {"atk": 0.05},
    5: {"atk": 0.05},
}

# ---------------------------------------------------------------------------
# Bulk sell prices (gold) by rank
# ---------------------------------------------------------------------------
SELL_PRICE_CHAMPION = {"F": 100, "E": 400, "D": 1200, "C": 4000, "B": 12000, "A": 35000, "S": 100000}
SELL_PRICE_ITEM     = {"F": 50,  "E": 200, "D": 600,  "C": 2000, "B": 6000,  "A": 18000, "S": 50000}

# ---------------------------------------------------------------------------
# Battle presentation display timing (seconds per round)
# ---------------------------------------------------------------------------
BATTLE_DISPLAY_INTERVALS = {
    "hunt":   0.7,
    "elite":  1.0,
    "boss":   1.0,
    "raid":   1.5,
}
BATTLE_FAST_DISPLAY_INTERVAL = 0.3

# Batched display tuning (avoid Discord per-message edit rate limits)
DISPLAY_BATCH_SIZE = 2        # combine N rounds per embed edit
DISPLAY_INTERVAL = 0.8        # seconds between edits
DISPLAY_MAX_UPDATES = 15      # cap total message edits per battle
