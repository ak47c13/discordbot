"""
Central configuration for all game rates, costs, drop tables, and multipliers.
Nothing numeric lives in business logic — change values here only.
"""

# ---------------------------------------------------------------------------
# Rank ordering
# ---------------------------------------------------------------------------
RANKS = ["F", "E", "D", "C", "B", "A", "S"]
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}  # F=0 … S=6

# ---------------------------------------------------------------------------
# Champion fusion costs (gold) indexed by resulting rank
# F->E costs 100, E->D 200, D->C 400 …
# ---------------------------------------------------------------------------
CHAMPION_FUSION_COST = {
    "E": 100,
    "D": 200,
    "C": 400,
    "B": 800,
    "A": 1600,
    "S": 3200,
}

# ---------------------------------------------------------------------------
# Item fusion costs (gold) indexed by resulting rank
# ---------------------------------------------------------------------------
ITEM_FUSION_COST = {
    "E": 50,
    "D": 100,
    "C": 200,
    "B": 400,
    "A": 800,
    "S": 1600,
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

# Enhancement gold cost per attempt (multiplied by current enhancement level, min 10)
ENHANCEMENT_GOLD_BASE = 10

def enhancement_gold_cost(current_level: int) -> int:
    return max(10, ENHANCEMENT_GOLD_BASE * (current_level + 1))

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
REROLL_FULL_COST = {r: 100 * (RANK_INDEX[r] + 1) for r in RANKS}   # changes type+value
REROLL_VALUE_COST = {r: 50 * (RANK_INDEX[r] + 1) for r in RANKS}   # keeps type, changes value

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

# Gold cost to level up (per level)
LEVEL_UP_GOLD_COST = 20

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

# Secondary stat roll ranges [min, max] by rank (percentage values * 10 for int storage)
SECONDARY_STAT_RANGE = {
    "F": (10, 30),    # 1.0% - 3.0%
    "E": (20, 50),
    "D": (35, 75),
    "C": (50, 100),
    "B": (70, 140),
    "A": (100, 200),
    "S": (150, 300),
}

SECONDARY_STAT_TYPES = [
    "atk_pct",
    "hp_pct",
    "def_pct",
    "crit_chance",
    "crit_dmg",
    "accuracy",
    "dodge",
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
SUMMON_TOKEN_COST = 100          # per single pull
SUMMON_MULTI_COST = 950          # 10 pulls

# Starter rewards granted on /start registration
STARTER_SUMMON_TOKENS = 950   # enough for 1x10 pull
STARTER_GOLD = 500

SUMMON_RATES = {
    # (item_or_champion, rank): probability
    "champion_F": 0.40,
    "champion_E": 0.25,
    "champion_D": 0.15,
    "champion_C": 0.08,
    "champion_B": 0.04,
    "champion_A": 0.02,
    "champion_S": 0.005,
    "item_F":     0.00,   # items via summon
    "item_E":     0.00,
    "item_D":     0.025,
    "item_C":     0.015,
    "item_B":     0.005,
    "gold_small": 0.03,   # 200-500 gold
    "enhance_mat":0.025,
    "reroll_mat": 0.015,
    "seal":       0.001,
}

# Token income sources
DAILY_SUMMON_TOKENS = 50
BOSS_KILL_TOKENS = (10, 30)       # min, max
RAID_COMPLETE_TOKENS = (50, 100)

# ---------------------------------------------------------------------------
# Drop tables
# ---------------------------------------------------------------------------
NORMAL_MOB_DROPS = {
    "gold":         {"min": 10,  "max": 50,  "chance": 1.00},
    "champion_F":   {"chance": 0.02},
    "item_F":       {"chance": 0.05},
    "enhance_mat":  {"min": 1, "max": 2, "chance": 0.15},
    "reroll_mat":   {"min": 1, "max": 1, "chance": 0.08},
    "seal":         {"chance": 0.0005},
}

# Elite mob config
ELITE_MOB_STAT_MULTIPLIER = 2.5   # elite HP/ATK vs normal
ELITE_MOB_DROPS = {
    "gold":        {"chance": 1.0, "min": 200,  "max": 600},
    "champion":    {"chance": 0.25, "ranks": ["F", "E"]},
    "item":        {"chance": 0.30, "ranks": ["F", "E"]},
    "seal":        {"chance": 0.005},
    "enhance_mat": {"chance": 0.60, "min": 3, "max": 8},
    "reroll_mat":  {"chance": 0.40, "min": 1, "max": 3},
}

BOSS_DROPS = {
    "gold":         {"min": 200, "max": 500, "chance": 1.00},
    "champion":     {"chance": 0.10},   # rank determined by boss config
    "item":         {"chance": 0.15},
    "enhance_mat":  {"min": 5, "max": 15, "chance": 0.40},
    "reroll_mat":   {"min": 2, "max": 5, "chance": 0.20},
    "seal":         {"chance": 0.01},
    "summon_token": {"min": 10, "max": 30, "chance": 0.60},
}

RAID_DROPS = {
    "gold":         {"min": 300, "max": 800, "chance": 1.00},
    "champion":     {"chance": 0.15},
    "item":         {"chance": 0.20},
    "enhance_mat":  {"min": 8, "max": 20, "chance": 0.50},
    "reroll_mat":   {"min": 3, "max": 8,  "chance": 0.25},
    "seal":         {"chance": 0.02},
    "summon_token": {"min": 50, "max": 100, "chance": 1.00},
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

# ---------------------------------------------------------------------------
# Stamina regeneration
# ---------------------------------------------------------------------------
STAMINA_REGEN_SECONDS = 360   # 1 stamina per 6 minutes

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
DUNGEON_FLOOR_GOLD_BASE = 50
DUNGEON_FLOOR_GOLD_PER_FLOOR = 15
DUNGEON_FLOOR_XP_BASE = 20
DUNGEON_FLOOR_XP_PER_FLOOR = 8
DUNGEON_RUNE_SHARD_CHANCE = 0.10     # 10% per floor
DUNGEON_RUNE_FRAGMENT_CHANCE = 0.02  # 2% per floor

# First-clear bonuses by dungeon length
DUNGEON_FIRST_CLEAR = {
    20: {"gold": 500, "summon_tokens": 100},
    35: {"gold": 1000, "summon_tokens": 200},
    40: {"gold": 1500, "summon_tokens": 300},
    50: {"gold": 3000, "summon_tokens": 500},
}
DUNGEON_DAILY_CLEAR = {
    20: {"gold": 200},
    35: {"gold": 400},
    40: {"gold": 700},
    50: {"gold": 1200},
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
SELL_PRICE_CHAMPION = {"F": 50, "E": 150, "D": 400, "C": 1000, "B": 2500, "A": 6000, "S": 15000}
SELL_PRICE_ITEM     = {"F": 30, "E": 90,  "D": 240, "C": 600,  "B": 1500, "A": 3600, "S": 9000}

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
