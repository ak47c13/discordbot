"""
Champion banner image generator.
Downloads Riot Data Dragon loading screen art and stitches into one banner.
Caches downloaded images locally in /tmp/champion_art/.
"""
from __future__ import annotations
import asyncio
import io
import os
from pathlib import Path

import discord
from PIL import Image
import aiohttp

CACHE_DIR = Path("/tmp/champion_art")
CACHE_DIR.mkdir(exist_ok=True)

DDRAGON_LOADING = "https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg"

# Card dimensions (original: 308x560)
CARD_W = 220   # scaled down to fit 5 cards in embed nicely
CARD_H = 400
BANNER_PADDING = 4   # gap between cards
BANNER_BG = (15, 15, 25)   # dark background matching LoL aesthetic

# Rank border colors
RANK_COLORS = {
    "F": (120, 120, 120),   # gray
    "E": (80, 180, 80),     # green
    "D": (60, 120, 200),    # blue
    "C": (140, 60, 200),    # purple
    "B": (200, 60, 60),     # red
    "A": (220, 180, 0),     # gold
    "S": (200, 100, 255),   # prismatic-ish purple
}

BORDER_THICKNESS = 4


def _riot_id_from_name(name: str) -> str:
    """Derive Data Dragon riot_id from champion name."""
    special = {
        "Dr. Mundo": "DrMundo",
        "Kai'Sa": "KaiSa",
        "Kha'Zix": "Khazix",
        "Vel'Koz": "Velkoz",
        "Cho'Gath": "Chogath",
        "Kog'Maw": "KogMaw",
        "Rek'Sai": "RekSai",
        "Aurelion Sol": "AurelionSol",
        "Bel'Veth": "Belveth",
        "LeBlanc": "Leblanc",
        "Lee Sin": "LeeSin",
        "Master Yi": "MasterYi",
        "Miss Fortune": "MissFortune",
        "Nunu": "Nunu",
        "Renata Glasc": "Renata",
        "Tahm Kench": "TahmKench",
        "Twisted Fate": "TwistedFate",
        "Xin Zhao": "XinZhao",
        "Jarvan IV": "JarvanIV",
        "K'Sante": "KSante",
        "Wukong": "MonkeyKing",
        "Ambessa": "Ambessa",
        "Mel": "Mel",
    }
    if name in special:
        return special[name]
    # Remove spaces, apostrophes, dots
    return name.replace(" ", "").replace("'", "").replace(".", "")


async def _download_image(session: aiohttp.ClientSession, riot_id: str) -> Image.Image | None:
    """Download and cache a champion loading screen image."""
    cache_path = CACHE_DIR / f"{riot_id}.jpg"
    if cache_path.exists():
        return Image.open(cache_path).convert("RGB")

    url = DDRAGON_LOADING.format(riot_id=riot_id)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img.save(cache_path, "JPEG", quality=85)
                return img
    except Exception:
        pass
    return None


def _placeholder_card(name: str, rank: str) -> Image.Image:
    """Create a placeholder card when image download fails."""
    img = Image.new("RGB", (308, 560), color=(30, 30, 50))
    # We don't use ImageDraw/font to avoid font dependency issues
    return img


async def _get_champion_card(
    session: aiohttp.ClientSession,
    champion_name: str,
    rank: str,
    level: int,
    riot_id_override: str = "",
) -> Image.Image:
    """Get a champion card image with rank border overlay."""
    riot_id = riot_id_override if riot_id_override else _riot_id_from_name(champion_name)

    raw = await _download_image(session, riot_id)
    if raw is None:
        raw = _placeholder_card(champion_name, rank)

    # Resize to card dimensions
    card = raw.resize((CARD_W, CARD_H), Image.LANCZOS)

    # Add rank-colored border
    bordered = Image.new(
        "RGB",
        (CARD_W + BORDER_THICKNESS * 2, CARD_H + BORDER_THICKNESS * 2),
        RANK_COLORS.get(rank, (100, 100, 100)),
    )
    bordered.paste(card, (BORDER_THICKNESS, BORDER_THICKNESS))

    return bordered


async def generate_team_banner(
    champions: list[dict],   # list of {"name": str, "rank": str, "level": int, "riot_id": str}
    title: str = "",
) -> io.BytesIO:
    """
    Generate a loading-screen-style banner for a team of up to 5 champions.
    Returns a BytesIO PNG buffer ready to send as a Discord attachment.

    Each dict in champions: {"name": str, "rank": str, "level": int, "riot_id": str (optional)}
    """
    card_w_bordered = CARD_W + BORDER_THICKNESS * 2
    card_h_bordered = CARD_H + BORDER_THICKNESS * 2

    n = max(1, len(champions))
    total_w = n * card_w_bordered + (n - 1) * BANNER_PADDING
    total_h = card_h_bordered

    banner = Image.new("RGB", (total_w, total_h), BANNER_BG)

    if champions:
        async with aiohttp.ClientSession() as session:
            tasks = [
                _get_champion_card(
                    session,
                    c["name"],
                    c.get("rank", "F"),
                    c.get("level", 1),
                    c.get("riot_id", ""),
                )
                for c in champions
            ]
            cards = await asyncio.gather(*tasks)

        x = 0
        for card in cards:
            banner.paste(card, (x, 0))
            x += card_w_bordered + BANNER_PADDING

    buf = io.BytesIO()
    banner.save(buf, "PNG")
    buf.seek(0)
    return buf


async def generate_vs_banner(
    player_champions: list[dict],
    enemy_name: str,
    enemy_riot_id: str = "",
) -> io.BytesIO:
    """
    Generate a battle banner: player team on bottom, enemy on top-right area.
    For hunts/boss fights.
    """
    # For now, just generate player team banner with enemy name in title
    return await generate_team_banner(player_champions, title=f"vs {enemy_name}")


async def send_team_banner_embed(
    channel_or_interaction,
    champions: list[dict],
    embed: discord.Embed,
    filename: str = "team.png",
) -> discord.Message:
    """Generate banner, attach to embed, send to channel."""
    buf = await generate_team_banner(champions)
    file = discord.File(buf, filename=filename)
    embed.set_image(url=f"attachment://{filename}")

    if hasattr(channel_or_interaction, "send"):
        return await channel_or_interaction.send(embed=embed, file=file)
    else:
        return await channel_or_interaction.followup.send(embed=embed, file=file)
