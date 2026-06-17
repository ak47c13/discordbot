"""
Crafting recipes: component items combine into completed items.
Components are common drops. Completed items are rare drops or crafted here.
"""

# Each recipe: output_name -> {components: [name, ...], stat_type, passive, gold_cost}
# Components must be owned (any rank); recipe output inherits the LOWEST rank component.
ITEM_RECIPES: dict[str, dict] = {
    # --- ATTACK ---
    "Infinity Edge": {
        "components": ["B.F. Sword", "Pickaxe", "Cloak of Agility"],
        "stat_type": "atk",
        "passive": "crit_damage_passive",
        "gold_cost": 1000,
        "description": "Crit strikes deal massive bonus damage.",
    },
    "Trinity Force": {
        "components": ["Sheen", "Phage", "Zeal"],
        "stat_type": "atk",
        "passive": "attack_speed_passive",
        "gold_cost": 1200,
        "description": "After casting a skill, your next attack deals bonus damage.",
    },
    "Blade of the Ruined King": {
        "components": ["Vampiric Scepter", "Recurve Bow", "Long Sword"],
        "stat_type": "atk",
        "passive": "lifesteal_passive",
        "gold_cost": 900,
        "description": "Attacks steal life and deal bonus current-HP damage.",
    },
    "Kraken Slayer": {
        "components": ["Recurve Bow", "Pickaxe", "Long Sword"],
        "stat_type": "atk",
        "passive": "armor_pen_passive",
        "gold_cost": 800,
        "description": "Every third attack deals true damage.",
    },

    # --- DEFENSE ---
    "Sunfire Aegis": {
        "components": ["Chain Vest", "Cloth Armor", "Ruby Crystal"],
        "stat_type": "def",
        "passive": "armor_passive",
        "gold_cost": 700,
        "description": "Immolates nearby enemies each round.",
    },
    "Thornmail": {
        "components": ["Chain Vest", "Warden's Mail"],
        "stat_type": "def",
        "passive": "armor_passive",
        "gold_cost": 600,
        "description": "Returns a portion of physical damage to attackers.",
    },
    "Gargoyle Stoneplate": {
        "components": ["Cloth Armor", "Chain Vest", "Spectre's Cowl"],
        "stat_type": "def",
        "passive": "fortify_passive",
        "gold_cost": 900,
        "description": "Massively increases armor and HP when low on health.",
    },

    # --- HP ---
    "Warmog's Armor": {
        "components": ["Giant's Belt", "Ruby Crystal", "Spectre's Cowl"],
        "stat_type": "hp",
        "passive": "fortify_passive",
        "gold_cost": 800,
        "description": "Regenerates a large amount of HP each round.",
    },
    "Sterak's Gage": {
        "components": ["Giant's Belt", "Long Sword"],
        "stat_type": "hp",
        "passive": "fortify_passive",
        "gold_cost": 700,
        "description": "Grants a shield when dropping to low HP.",
    },

    # --- MAGIC / HYBRID ---
    "Rabadon's Deathcap": {
        "components": ["Needlessly Large Rod", "Blasting Wand", "Amplifying Tome"],
        "stat_type": "atk",
        "passive": "crit_damage_passive",
        "gold_cost": 1100,
        "description": "Dramatically amplifies all ability power.",
    },
    "Luden's Tempest": {
        "components": ["Lost Chapter", "Amplifying Tome", "Blasting Wand"],
        "stat_type": "atk",
        "passive": "attack_speed_passive",
        "gold_cost": 900,
        "description": "Hitting an enemy with a skill fires a bolt at additional enemies.",
    },
    "Void Staff": {
        "components": ["Blasting Wand", "Amplifying Tome"],
        "stat_type": "atk",
        "passive": "crit_damage_passive",
        "gold_cost": 700,
        "description": "Spells ignore a large portion of enemy magic resistance.",
    },
}

# Component items: these are the *only* items that drop commonly from dungeons/raids as components.
# Completed items (above) are either crafted here or are extremely rare drops.
COMPONENT_ITEMS: dict[str, dict] = {
    "B.F. Sword":         {"stat_type": "atk", "passive": "atk_passive"},
    "Pickaxe":            {"stat_type": "atk", "passive": "atk_passive"},
    "Long Sword":         {"stat_type": "atk", "passive": "atk_passive"},
    "Recurve Bow":        {"stat_type": "atk", "passive": "attack_speed_passive"},
    "Vampiric Scepter":   {"stat_type": "atk", "passive": "lifesteal_passive"},
    "Cloak of Agility":   {"stat_type": "atk", "passive": "crit_damage_passive"},
    "Sheen":              {"stat_type": "atk", "passive": "atk_passive"},
    "Phage":              {"stat_type": "hp",  "passive": "fortify_passive"},
    "Zeal":               {"stat_type": "atk", "passive": "attack_speed_passive"},
    "Chain Vest":         {"stat_type": "def", "passive": "armor_passive"},
    "Cloth Armor":        {"stat_type": "def", "passive": "armor_passive"},
    "Warden's Mail":      {"stat_type": "def", "passive": "armor_passive"},
    "Ruby Crystal":       {"stat_type": "hp",  "passive": "fortify_passive"},
    "Giant's Belt":       {"stat_type": "hp",  "passive": "fortify_passive"},
    "Spectre's Cowl":     {"stat_type": "hp",  "passive": "fortify_passive"},
    "Needlessly Large Rod": {"stat_type": "atk", "passive": "crit_damage_passive"},
    "Blasting Wand":      {"stat_type": "atk", "passive": "atk_passive"},
    "Amplifying Tome":    {"stat_type": "atk", "passive": "atk_passive"},
    "Lost Chapter":       {"stat_type": "atk", "passive": "crit_damage_passive"},
    "Fiendish Codex":     {"stat_type": "atk", "passive": "attack_speed_passive"},
    "Bramble Vest":       {"stat_type": "def", "passive": "armor_passive"},
    "Hexdrinker":         {"stat_type": "hp",  "passive": "fortify_passive"},
}

# Completed item names — used to make them rare from random drops
COMPLETED_ITEM_NAMES = set(ITEM_RECIPES.keys())
