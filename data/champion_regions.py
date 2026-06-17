"""
Maps each LoL champion to their lore region, used for weekly summon rotation.
"""
from __future__ import annotations

# Maps region_key -> list of champion names
CHAMPION_REGIONS: dict[str, list[str]] = {
    "demacia": [
        "Garen", "Lux", "Fiora", "Jarvan IV", "Poppy", "Xin Zhao", "Galio",
        "Sona", "Vayne", "Quinn", "Shyvana", "Sylas", "Camille", "Kayle",
        "Morgana", "Lucian",
    ],
    "noxus": [
        "Darius", "Draven", "Katarina", "Swain", "Vladimir", "Mordekaiser",
        "Urgot", "Sion", "Talon", "Cassiopeia", "Riven", "LeBlanc", "Samira",
        "Kled", "Alistar", "Annie", "Mel",
    ],
    "freljord": [
        "Ashe", "Tryndamere", "Braum", "Sejuani", "Volibear", "Lissandra",
        "Anivia", "Nunu & Willump", "Gragas", "Trundle", "Udyr", "Olaf",
        "Brand", "Gnar", "Ornn",
    ],
    "piltover_zaun": [
        "Jayce", "Vi", "Caitlyn", "Jinx", "Ekko", "Heimerdinger", "Blitzcrank",
        "Ziggs", "Zac", "Warwick", "Singed", "Viktor", "Orianna", "Janna",
        "Twitch", "Renata Glasc", "Dr. Mundo", "Ezreal", "Ryze",
    ],
    "ionia": [
        "Ahri", "Irelia", "Yasuo", "Yone", "Zed", "Kennen", "Karma",
        "Lee Sin", "Master Yi", "Shen", "Akali", "Wukong", "Syndra", "Kayn",
        "Jhin", "Xayah", "Rakan", "Varus", "Sett", "Jax", "Yunara",
    ],
    "shadow_isles": [
        "Thresh", "Hecarim", "Karthus", "Yorick", "Senna", "Viego", "Gwen",
        "Maokai", "Kalista", "Elise", "Nocturne", "Evelynn", "Briar",
        "Fiddlesticks", "Kindred", "Shaco",
    ],
    "bilgewater": [
        "Gangplank", "Miss Fortune", "Graves", "Twisted Fate", "Nautilus",
        "Illaoi", "Pyke", "Fizz", "Tahm Kench", "Nami",
    ],
    "shurima": [
        "Azir", "Nasus", "Renekton", "Sivir", "Taliyah", "Rammus", "Amumu",
        "Xerath", "Zilean", "Akshan", "K'Sante", "Naafiri", "Skarner",
        "Rengar", "Aatrox", "Nilah",
    ],
    "targon": [
        "Pantheon", "Leona", "Diana", "Aurelion Sol", "Taric", "Aphelios",
        "Zoe", "Soraka", "Malphite", "Bard",
    ],
    "ixtal": [
        "Nidalee", "Qiyana", "Milio", "Zyra", "Neeko", "Ivern",
    ],
    "bandle_city": [
        "Teemo", "Lulu", "Tristana", "Corki", "Rumble", "Yuumi", "Veigar",
    ],
    "void": [
        "Cho'Gath", "Kog'Maw", "Kha'Zix", "Vel'Koz", "Rek'Sai", "Bel'Veth",
        "Malzahar", "Kassadin", "Kai'Sa",
    ],
}

# Ordered rotation list (cycles weekly Mon-Sun GMT+8)
REGION_ROTATION = [
    "demacia", "noxus", "freljord", "piltover_zaun",
    "ionia", "shadow_isles", "bilgewater", "shurima",
    "targon", "ixtal", "bandle_city", "void",
]

REGION_DISPLAY_NAMES = {
    "demacia": "Demacia",
    "noxus": "Noxus",
    "freljord": "Freljord",
    "piltover_zaun": "Piltover & Zaun",
    "ionia": "Ionia",
    "shadow_isles": "Shadow Isles",
    "bilgewater": "Bilgewater",
    "shurima": "Shurima",
    "targon": "Targon",
    "ixtal": "Ixtal",
    "bandle_city": "Bandle City",
    "void": "Void",
}


def current_region() -> str:
    """Return the current week's region key (deterministic, no DB needed)."""
    import time
    # Monday 00:00 GMT+8 = Sunday 16:00 UTC
    # Anchor: first Monday GMT+8 of 2024-01-01 = 2023-12-31 16:00 UTC = 1703959200
    ANCHOR_UTC = 1703959200
    WEEK_SECS = 604800
    week_index = int((time.time() - ANCHOR_UTC) // WEEK_SECS)
    return REGION_ROTATION[week_index % len(REGION_ROTATION)]


def days_until_rotation() -> float:
    """Days remaining until next Monday 00:00 GMT+8."""
    import time
    ANCHOR_UTC = 1703959200
    WEEK_SECS = 604800
    elapsed = (time.time() - ANCHOR_UTC) % WEEK_SECS
    return (WEEK_SECS - elapsed) / 86400
