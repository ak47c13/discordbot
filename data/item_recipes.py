"""
Full LoL-accurate item system.

Two recipe tiers:
  COMPONENT_RECIPES  — basic components → advanced components (e.g. Dagger+Dagger = Zeal)
  COMPLETED_RECIPES  — advanced components → finished items (e.g. B.F.Sword+Cloak = IE)

Drop sources:
  BASIC_COMPONENTS   — raw items; most common dungeon/shop drops
  ADVANCED_COMPONENTS — built from basics OR medium-rarity drops
  Completed items    — crafting only, or ~3-5% on high-tier raid drops

stat_type: "atk" | "def" | "hp"
passive  : short key describing the item's effect (used by combat engine)
"""

# ---------------------------------------------------------------------------
# Basic components — common drops, 1-2 stat focus
# ---------------------------------------------------------------------------
BASIC_COMPONENTS: dict[str, dict] = {
    # Attack
    "Long Sword":          {"stat_type": "atk", "passive": "atk_passive",          "desc": "+10 ATK"},
    "Pickaxe":             {"stat_type": "atk", "passive": "atk_passive",          "desc": "+15 ATK"},
    "Dagger":              {"stat_type": "atk", "passive": "attack_speed_passive",  "desc": "+10% Attack Speed"},
    "Vampiric Scepter":    {"stat_type": "atk", "passive": "lifesteal_passive",     "desc": "+10% Lifesteal"},
    # Defense
    "Cloth Armor":         {"stat_type": "def", "passive": "armor_passive",         "desc": "+15 Armor"},
    "Null-Magic Mantle":   {"stat_type": "def", "passive": "magic_resist_passive",  "desc": "+20 Magic Resist"},
    # HP
    "Ruby Crystal":        {"stat_type": "hp",  "passive": "fortify_passive",       "desc": "+150 HP"},
    "Faerie Charm":        {"stat_type": "hp",  "passive": "fortify_passive",       "desc": "+15 HP + slight HP regen"},
    # Magic
    "Amplifying Tome":     {"stat_type": "ap",  "passive": "atk_passive",          "desc": "+20 AP (Ability Power)"},
    "Sapphire Crystal":    {"stat_type": "ap",  "passive": "atk_passive",          "desc": "+20 AP + mana utility"},
}

# ---------------------------------------------------------------------------
# Advanced components — crafted from basics OR mid-tier drops
# ---------------------------------------------------------------------------
ADVANCED_COMPONENTS: dict[str, dict] = {
    # Attack advanced
    "B.F. Sword":              {"stat_type": "atk", "passive": "atk_passive",          "desc": "+40 ATK"},
    "Recurve Bow":             {"stat_type": "atk", "passive": "attack_speed_passive",  "desc": "+25% Attack Speed"},
    "Cloak of Agility":        {"stat_type": "atk", "passive": "crit_damage_passive",   "desc": "+10% Crit Chance"},
    "Zeal":                    {"stat_type": "atk", "passive": "attack_speed_passive",  "desc": "+15% Crit · +10% Attack Speed"},
    "Hearthbound Axe":         {"stat_type": "atk", "passive": "attack_speed_passive",  "desc": "+15 ATK · +15% AS · builds into Trinity Force"},
    "Noonquiver":              {"stat_type": "atk", "passive": "attack_speed_passive",  "desc": "+30 ATK · +15% AS · builds into Shieldbow, Kraken Slayer"},
    "Tiamat":                  {"stat_type": "atk", "passive": "atk_passive",          "desc": "+25 ATK · splash damage · builds into Hydras"},
    "Caulfield's Warhammer":   {"stat_type": "atk", "passive": "atk_passive",          "desc": "+25 ATK · ability haste · builds into Death's Dance, Ravenous Hydra"},
    "Phage":                   {"stat_type": "atk", "passive": "atk_passive",          "desc": "+20 ATK · +200 HP · slowing hit"},
    "Sheen":                   {"stat_type": "atk", "passive": "sheen_passive",         "desc": "After using a skill, next attack deals 150% ATK"},
    "Kindlegem":               {"stat_type": "hp",  "passive": "fortify_passive",       "desc": "+200 HP"},
    # Defense advanced
    "Chain Vest":              {"stat_type": "def", "passive": "armor_passive",         "desc": "+40 Armor"},
    "Negatron Cloak":          {"stat_type": "def", "passive": "magic_resist_passive",  "desc": "+40 Magic Resist"},
    "Warden's Mail":           {"stat_type": "def", "passive": "armor_passive",         "desc": "+40 Armor · slows attackers"},
    "Bramble Vest":            {"stat_type": "def", "passive": "armor_passive",         "desc": "+30 Armor · reflects damage"},
    "Spectre's Cowl":          {"stat_type": "def", "passive": "magic_resist_passive",  "desc": "+30 Magic Resist · +250 HP"},
    "Hexdrinker":              {"stat_type": "def", "passive": "magic_resist_passive",  "desc": "+20 ATK · +25 Magic Resist · magic shield"},
    # HP/utility advanced
    "Giant's Belt":            {"stat_type": "hp",  "passive": "fortify_passive",       "desc": "+380 HP"},
    # Magic advanced
    "Blasting Wand":           {"stat_type": "atk", "passive": "atk_passive",          "desc": "+40 ATK (Ability Power)"},
    "Needlessly Large Rod":    {"stat_type": "ap",  "passive": "crit_damage_passive",   "desc": "+60 AP (Ability Power)"},
    "Lost Chapter":            {"stat_type": "atk", "passive": "atk_passive",          "desc": "+40 ATK · mana regen"},
    "Fiendish Codex":          {"stat_type": "ap",  "passive": "attack_speed_passive",  "desc": "+35 AP · ability haste"},
    "Tear of the Goddess":     {"stat_type": "atk", "passive": "atk_passive",          "desc": "+15 ATK · stacking mana"},
    # Assassin / lethality components
    "Serrated Dirk":           {"stat_type": "atk", "passive": "armor_pen_passive",     "desc": "+30 ATK · +10 Lethality (armor pen)"},
    "Cauterize":               {"stat_type": "atk", "passive": "armor_pen_passive",     "desc": "+20 ATK · +15 Lethality · builds into lethality items"},
    "Serpent's Fang":          {"stat_type": "atk", "passive": "armor_pen_passive",     "desc": "+55 ATK · +10 Lethality · reduces shields on targets"},
    "Umbral Glaive":           {"stat_type": "atk", "passive": "armor_pen_passive",     "desc": "+40 ATK · +15 Lethality · anti-ward utility"},
    # Starter items (no recipes, drop-only, cannot build into completed items)
    "Doran's Blade":           {"stat_type": "atk", "passive": "lifesteal_passive",     "desc": "+80 HP · +8 ATK · 3% omnivamp"},
    "Doran's Ring":            {"stat_type": "atk", "passive": "atk_passive",          "desc": "+70 HP · +15 ATK (AP) · mana regen"},
    "Doran's Shield":          {"stat_type": "hp",  "passive": "fortify_passive",       "desc": "+80 HP · +6 HP regen/5s"},
    "Cull":                    {"stat_type": "atk", "passive": "atk_passive",          "desc": "+7 ATK · 1 gold/kill · pay-off bonus"},
}

# All components together for quick lookup
COMPONENT_ITEMS: dict[str, dict] = {**BASIC_COMPONENTS, **ADVANCED_COMPONENTS}

# ---------------------------------------------------------------------------
# Component recipes — build advanced components from basics
# ---------------------------------------------------------------------------
COMPONENT_RECIPES: dict[str, dict] = {
    "B.F. Sword":           {"components": ["Long Sword", "Long Sword"],            "stat_type": "atk", "passive": "atk_passive",          "gold_cost": 300,  "description": "Powerful sword. Core component for many completed items."},
    "Recurve Bow":          {"components": ["Dagger", "Dagger"],                    "stat_type": "atk", "passive": "attack_speed_passive",  "gold_cost": 200,  "description": "Strung for rapid fire. Builds into on-hit items."},
    "Cloak of Agility":     {"components": ["Dagger"],                              "stat_type": "atk", "passive": "crit_damage_passive",   "gold_cost": 150,  "description": "+10% Crit Chance. Foundation of crit builds."},
    "Zeal":                 {"components": ["Dagger", "Cloak of Agility"],          "stat_type": "atk", "passive": "attack_speed_passive",  "gold_cost": 250,  "description": "Crit and attack speed. Builds into all crit-AS completed items."},
    "Phage":                {"components": ["Long Sword", "Ruby Crystal"],          "stat_type": "atk", "passive": "atk_passive",          "gold_cost": 250,  "description": "ATK + HP. Slow on hit. Builds into Trinity Force and Black Cleaver."},
    "Sheen":                {"components": ["Sapphire Crystal", "Amplifying Tome"], "stat_type": "atk", "passive": "sheen_passive",         "gold_cost": 350,  "description": "Spellblade: empowers next attack after casting a skill."},
    "Kindlegem":            {"components": ["Ruby Crystal", "Long Sword"],          "stat_type": "hp",  "passive": "fortify_passive",       "gold_cost": 200,  "description": "+200 HP · builds into most tank and fighter completed items."},
    "Chain Vest":           {"components": ["Cloth Armor", "Cloth Armor"],          "stat_type": "def", "passive": "armor_passive",         "gold_cost": 150,  "description": "Sturdy armor. Core armor component."},
    "Negatron Cloak":       {"components": ["Null-Magic Mantle", "Null-Magic Mantle"], "stat_type": "def", "passive": "magic_resist_passive", "gold_cost": 150, "description": "Core magic resistance component."},
    "Warden's Mail":        {"components": ["Cloth Armor", "Chain Vest"],           "stat_type": "def", "passive": "armor_passive",         "gold_cost": 200,  "description": "Slows the attack speed of attackers."},
    "Bramble Vest":         {"components": ["Cloth Armor", "Cloth Armor"],          "stat_type": "def", "passive": "armor_passive",         "gold_cost": 150,  "description": "Deals magic damage back to physical attackers."},
    "Hexdrinker":           {"components": ["Long Sword", "Null-Magic Mantle"],     "stat_type": "def", "passive": "magic_resist_passive",  "gold_cost": 300,  "description": "Grants a magic damage shield when HP drops low."},
    "Spectre's Cowl":       {"components": ["Ruby Crystal", "Null-Magic Mantle"],   "stat_type": "def", "passive": "magic_resist_passive",  "gold_cost": 250,  "description": "+30 MR · +250 HP. Builds into most MR completed items."},
    "Giant's Belt":         {"components": ["Ruby Crystal", "Ruby Crystal"],        "stat_type": "hp",  "passive": "fortify_passive",       "gold_cost": 250,  "description": "Massive HP. Builds into all HP completed items."},
    "Blasting Wand":        {"components": ["Amplifying Tome", "Amplifying Tome"],  "stat_type": "atk", "passive": "atk_passive",          "gold_cost": 250,  "description": "+40 AP. Builds into all ability power completed items."},
    "Needlessly Large Rod": {"components": ["Amplifying Tome", "Blasting Wand"],    "stat_type": "ap",  "passive": "crit_damage_passive",   "gold_cost": 350,  "description": "+60 AP. Highest AP component. Builds into Rabadon's and Zhonya's."},
    "Lost Chapter":         {"components": ["Sapphire Crystal", "Amplifying Tome"], "stat_type": "atk", "passive": "atk_passive",          "gold_cost": 300,  "description": "AP + mana regen. Builds into mage power items."},
    "Fiendish Codex":       {"components": ["Amplifying Tome", "Faerie Charm"],     "stat_type": "ap",  "passive": "attack_speed_passive",  "gold_cost": 200,  "description": "AP + ability haste. Builds into Nashor's and morello."},
    "Tear of the Goddess":  {"components": ["Faerie Charm", "Sapphire Crystal"],    "stat_type": "atk", "passive": "atk_passive",          "gold_cost": 200,  "description": "Stacks ATK through casting. Builds into Manamune and Archangel's."},
    "Vampiric Scepter":     {"components": ["Long Sword", "Faerie Charm"],          "stat_type": "atk", "passive": "lifesteal_passive",     "gold_cost": 200,  "description": "+10% Lifesteal. Builds into Blade of the Ruined King and Ravenous Hydra."},
    "Hearthbound Axe":      {"components": ["Long Sword", "Dagger"],               "stat_type": "atk", "passive": "attack_speed_passive",  "gold_cost": 200,  "description": "+15 ATK · +15% AS. Builds into Trinity Force."},
    "Noonquiver":           {"components": ["Long Sword", "Cloak of Agility"],    "stat_type": "atk", "passive": "attack_speed_passive",  "gold_cost": 250,  "description": "ATK + crit chance. Builds into Immortal Shieldbow and Kraken Slayer."},
    "Tiamat":               {"components": ["Long Sword", "Long Sword"],          "stat_type": "atk", "passive": "atk_passive",          "gold_cost": 350,  "description": "ATK with splash. Builds into Ravenous Hydra and Titanic Hydra."},
    "Caulfield's Warhammer":{"components": ["Pickaxe", "Long Sword"],             "stat_type": "atk", "passive": "atk_passive",          "gold_cost": 300,  "description": "ATK + ability haste. Builds into Death's Dance and Ravenous Hydra."},
    "Serrated Dirk":        {"components": ["Long Sword"],                        "stat_type": "atk", "passive": "armor_pen_passive",     "gold_cost": 200,  "description": "+30 ATK · +10 Lethality. Builds into most assassin items."},
    "Cauterize":            {"components": ["Serrated Dirk", "Long Sword"],       "stat_type": "atk", "passive": "armor_pen_passive",     "gold_cost": 300,  "description": "+20 ATK · +15 Lethality. Mid-tier assassin component."},
}

# ---------------------------------------------------------------------------
# Completed item recipes — 3-4 components, strong passives
# ---------------------------------------------------------------------------
COMPLETED_RECIPES: dict[str, dict] = {
    # ── ATTACK / CRIT ───────────────────────────────────────────────────
    "Infinity Edge": {
        "components": ["B.F. Sword", "Pickaxe", "Cloak of Agility"],
        "stat_type": "atk", "passive": "crit_damage_passive", "gold_cost": 1200,
        "description": "Crit strikes deal 210% instead of 175% damage. Massive crit power spike.",
    },
    "Immortal Shieldbow": {
        "components": ["Noonquiver", "B.F. Sword", "Cloak of Agility"],
        "stat_type": "atk", "passive": "lifesteal_passive", "gold_cost": 1200,
        "description": "Saves you from a lethal hit with a shield. Lifeline for marksmen.",
    },
    "Phantom Dancer": {
        "components": ["Recurve Bow", "Cloak of Agility", "Dagger"],
        "stat_type": "atk", "passive": "attack_speed_passive", "gold_cost": 900,
        "description": "High crit and attack speed. Grants a shield while at low HP.",
    },
    "Runaan's Hurricane": {
        "components": ["Recurve Bow", "Cloak of Agility", "Dagger"],
        "stat_type": "atk", "passive": "attack_speed_passive", "gold_cost": 900,
        "description": "Attacks fire bolts that hit two additional nearby enemies.",
    },
    "Kraken Slayer": {
        "components": ["Noonquiver", "Recurve Bow", "Long Sword"],
        "stat_type": "atk", "passive": "armor_pen_passive", "gold_cost": 1000,
        "description": "Every third attack deals true damage, ignoring all defenses.",
    },
    "Trinity Force": {
        "components": ["Sheen", "Phage", "Hearthbound Axe"],
        "stat_type": "atk", "passive": "sheen_passive", "gold_cost": 1400,
        "description": "Spellblade empowers next attack after casting. ATK, HP, and attack speed.",
    },
    "Blade of the Ruined King": {
        "components": ["Vampiric Scepter", "Recurve Bow", "Long Sword"],
        "stat_type": "atk", "passive": "lifesteal_passive", "gold_cost": 1100,
        "description": "Attacks deal % current HP bonus damage and steal 10% move speed.",
    },
    "Ravenous Hydra": {
        "components": ["Tiamat", "Vampiric Scepter", "Caulfield's Warhammer"],
        "stat_type": "atk", "passive": "lifesteal_passive", "gold_cost": 1200,
        "description": "Attacks splash to nearby enemies. Massive omnivamp.",
    },
    "Death's Dance": {
        "components": ["Caulfield's Warhammer", "Pickaxe", "Kindlegem"],
        "stat_type": "atk", "passive": "lifesteal_passive", "gold_cost": 1100,
        "description": "Stores 30% of damage taken, then bleeds it out over time. Defer burst.",
    },
    "Black Cleaver": {
        "components": ["Long Sword", "Ruby Crystal", "Phage"],
        "stat_type": "atk", "passive": "armor_pen_passive", "gold_cost": 1100,
        "description": "Stacks armor shred on each hit. Shreds up to 24% armor over 6 hits.",
    },
    "Titanic Hydra": {
        "components": ["Tiamat", "Giant's Belt", "Ruby Crystal"],
        "stat_type": "atk", "passive": "atk_passive", "gold_cost": 1200,
        "description": "Attacks deal bonus damage based on max HP. Tank with damage.",
    },
    "Manamune": {
        "components": ["Tear of the Goddess", "Long Sword", "Pickaxe"],
        "stat_type": "atk", "passive": "atk_passive", "gold_cost": 1100,
        "description": "Stacking item. Converts mana into ATK — huge power at full stacks.",
    },
    "Guardian Angel": {
        "components": ["Chain Vest", "Pickaxe"],
        "stat_type": "def", "passive": "fortify_passive", "gold_cost": 900,
        "description": "Revives you at 50% HP upon taking lethal damage. One-time per battle.",
    },

    # ── ABILITY POWER ────────────────────────────────────────────────────
    "Rabadon's Deathcap": {
        "components": ["Needlessly Large Rod", "Blasting Wand", "Amplifying Tome"],
        "stat_type": "ap", "passive": "crit_damage_passive", "gold_cost": 1400,
        "description": "Amplifies all AP by 35%. Biggest AP item in the game.",
    },
    "Luden's Companion": {
        "components": ["Lost Chapter", "Blasting Wand", "Amplifying Tome"],
        "stat_type": "ap", "passive": "attack_speed_passive", "gold_cost": 1200,
        "description": "First skill hit fires an echo that bounces to 3 nearby enemies.",
    },
    "Shadowflame": {
        "components": ["Needlessly Large Rod", "Amplifying Tome"],
        "stat_type": "ap", "passive": "crit_damage_passive", "gold_cost": 1000,
        "description": "Crits and high damage kills ignore shields and grievously wound.",
    },
    "Void Staff": {
        "components": ["Blasting Wand", "Amplifying Tome", "Null-Magic Mantle"],
        "stat_type": "ap", "passive": "armor_pen_passive", "gold_cost": 900,
        "description": "Magic damage ignores 40% of enemy magic resistance.",
    },
    "Nashor's Tooth": {
        "components": ["Fiendish Codex", "Recurve Bow", "Amplifying Tome"],
        "stat_type": "ap", "passive": "attack_speed_passive", "gold_cost": 1200,
        "description": "High AP and attack speed. Attacks deal bonus magic damage on-hit.",
    },
    "Liandry's Anguish": {
        "components": ["Fiendish Codex", "Blasting Wand", "Amplifying Tome"],
        "stat_type": "ap", "passive": "atk_passive", "gold_cost": 1200,
        "description": "Deals % max HP burn magic damage per second. Melts tanky enemies.",
    },
    "Morellonomicon": {
        "components": ["Blasting Wand", "Fiendish Codex"],
        "stat_type": "ap", "passive": "atk_passive", "gold_cost": 900,
        "description": "Applies Grievous Wounds on skill hit — reduces enemy healing by 40%.",
    },
    "Archangel's Staff": {
        "components": ["Tear of the Goddess", "Blasting Wand", "Amplifying Tome"],
        "stat_type": "ap", "passive": "atk_passive", "gold_cost": 1200,
        "description": "Huge AP at full stacks. Shield that scales with stacked ATK.",
    },
    "Rod of Ages": {
        "components": ["Lost Chapter", "Ruby Crystal", "Giant's Belt"],
        "stat_type": "ap", "passive": "fortify_passive", "gold_cost": 1200,
        "description": "Stacks HP, AP, and mana over time. Massive scaling power.",
    },
    "Rylai's Crystal Scepter": {
        "components": ["Blasting Wand", "Ruby Crystal", "Amplifying Tome"],
        "stat_type": "ap", "passive": "atk_passive", "gold_cost": 1000,
        "description": "Skills slow enemies by 20%. AP + HP bruiser mage item.",
    },
    "Zhonya's Hourglass": {
        "components": ["Needlessly Large Rod", "Cloth Armor"],
        "stat_type": "ap", "passive": "armor_passive", "gold_cost": 1000,
        "description": "Active: become invulnerable for 2.5 seconds. AP + armor.",
    },
    "Banshee's Veil": {
        "components": ["Blasting Wand", "Null-Magic Mantle"],
        "stat_type": "ap", "passive": "magic_resist_passive", "gold_cost": 900,
        "description": "Spell shield that blocks one skill every 40 seconds.",
    },
    "Horizon Focus": {
        "components": ["Blasting Wand", "Fiendish Codex"],
        "stat_type": "ap", "passive": "crit_damage_passive", "gold_cost": 1000,
        "description": "Skills that hit at long range or stun deal 10% bonus damage.",
    },

    # ── DEFENSE ──────────────────────────────────────────────────────────
    "Sunfire Aegis": {
        "components": ["Chain Vest", "Ruby Crystal", "Cloth Armor"],
        "stat_type": "def", "passive": "armor_passive", "gold_cost": 1000,
        "description": "Immolates nearby enemies each round dealing magic damage.",
    },
    "Thornmail": {
        "components": ["Chain Vest", "Warden's Mail"],
        "stat_type": "def", "passive": "armor_passive", "gold_cost": 900,
        "description": "Returns 25 + 10% ATK magic damage to physical attackers.",
    },
    "Frozen Heart": {
        "components": ["Chain Vest", "Warden's Mail", "Sapphire Crystal"],
        "stat_type": "def", "passive": "armor_passive", "gold_cost": 1100,
        "description": "Reduces nearby enemies' attack speed by 20%.",
    },
    "Gargoyle Stoneplate": {
        "components": ["Chain Vest", "Cloth Armor", "Negatron Cloak"],
        "stat_type": "def", "passive": "fortify_passive", "gold_cost": 1100,
        "description": "Massively increases armor and magic resist when surrounded by 3+ enemies.",
    },
    "Randuin's Omen": {
        "components": ["Warden's Mail", "Giant's Belt", "Cloth Armor"],
        "stat_type": "def", "passive": "armor_passive", "gold_cost": 1000,
        "description": "Reduces crit damage received by 20%. Active slows nearby enemies.",
    },
    "Dead Man's Plate": {
        "components": ["Chain Vest", "Giant's Belt"],
        "stat_type": "def", "passive": "armor_passive", "gold_cost": 1000,
        "description": "Stack momentum to empower your next basic attack to slow enemies.",
    },
    "Warmog's Armor": {
        "components": ["Giant's Belt", "Ruby Crystal", "Spectre's Cowl"],
        "stat_type": "hp", "passive": "fortify_passive", "gold_cost": 1100,
        "description": "Regenerates a large amount of HP each round out of combat.",
    },
    "Sterak's Gage": {
        "components": ["Giant's Belt", "Long Sword", "Kindlegem"],
        "stat_type": "hp", "passive": "fortify_passive", "gold_cost": 1000,
        "description": "Grants a shield equal to 75% base HP when dropping to low health.",
    },
    "Spirit Visage": {
        "components": ["Spectre's Cowl", "Negatron Cloak", "Kindlegem"],
        "stat_type": "def", "passive": "magic_resist_passive", "gold_cost": 1100,
        "description": "Increases all healing received by 25%. HP and magic resist.",
    },
    "Force of Nature": {
        "components": ["Negatron Cloak", "Spectre's Cowl", "Null-Magic Mantle"],
        "stat_type": "def", "passive": "magic_resist_passive", "gold_cost": 1000,
        "description": "Stacks magic resist each time you take magic damage. Move speed.",
    },
    "Abyssal Mask": {
        "components": ["Negatron Cloak", "Ruby Crystal", "Spectre's Cowl"],
        "stat_type": "def", "passive": "magic_resist_passive", "gold_cost": 1000,
        "description": "Nearby enemies take 10% more magic damage.",
    },
    "Jak'Sho the Protean": {
        "components": ["Chain Vest", "Negatron Cloak", "Ruby Crystal"],
        "stat_type": "def", "passive": "fortify_passive", "gold_cost": 1100,
        "description": "Voidborn: stacks resistances each round in combat. High per-fight scaling.",
    },
    "Heartsteel": {
        "components": ["Giant's Belt", "Ruby Crystal", "Kindlegem"],
        "stat_type": "hp", "passive": "fortify_passive", "gold_cost": 1100,
        "description": "Charges up a massive bonus HP-scaling strike. Enormous HP stacking.",
    },
    "Duskblade of Draktharr": {
        "components": ["Serrated Dirk", "Cauterize", "Long Sword"],
        "stat_type": "atk", "passive": "armor_pen_passive", "gold_cost": 1200,
        "description": "Nightstalker: after being unseen, next attack deals massive bonus damage.",
    },
    "Prowler's Claw": {
        "components": ["Serrated Dirk", "Cauterize", "Dagger"],
        "stat_type": "atk", "passive": "armor_pen_passive", "gold_cost": 1200,
        "description": "Lunge to a target and deal bonus physical damage, ignoring armor.",
    },
    "Serpent's Fang": {
        "components": ["Serrated Dirk", "Long Sword"],
        "stat_type": "atk", "passive": "armor_pen_passive", "gold_cost": 900,
        "description": "Reduces shields on enemies hit. Strong against shielding teams.",
    },
    "Umbral Glaive": {
        "components": ["Serrated Dirk", "Pickaxe"],
        "stat_type": "atk", "passive": "armor_pen_passive", "gold_cost": 900,
        "description": "+40 ATK · +15 Lethality. Efficient lethality item for burst assassins.",
    },
    "Axiom Arc": {
        "components": ["Serrated Dirk", "Caulfield's Warhammer"],
        "stat_type": "atk", "passive": "armor_pen_passive", "gold_cost": 1000,
        "description": "Refunds ultimate cooldown on kills. Resets for multi-kill potential.",
    },
}

# All recipes together for /build and /recipes commands
ITEM_RECIPES: dict[str, dict] = {**COMPONENT_RECIPES, **COMPLETED_RECIPES}

# Names of completed items — very rare to drop naturally
COMPLETED_ITEM_NAMES: set[str] = set(COMPLETED_RECIPES.keys())
