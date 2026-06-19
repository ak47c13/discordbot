"""
Battle scene image generator.
Renders enemy row + player row with champion portraits, HP bars, and mana bars.
Returns a BytesIO PNG to be attached to Discord messages.
"""
from __future__ import annotations
import asyncio
import io
import os
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

import aiohttp

CACHE_DIR = Path("/tmp/champion_art")
CACHE_DIR.mkdir(exist_ok=True)

DDRAGON_LOADING = "https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg"

# Card dimensions
CARD_W = 160
CARD_H = 240   # portrait height
BAR_H  = 10    # HP bar height
MANA_H = 7     # mana bar height
BAR_MARGIN = 3
NAME_H = 22
CARD_TOTAL_H = CARD_H + BAR_H + BAR_MARGIN + MANA_H + BAR_MARGIN + NAME_H + 10
CARD_GAP = 12

# Canvas
BG_COLOR   = (13, 17, 23)      # near-black
ROW_LABEL_H = 24
SECTION_GAP = 20
CANVAS_PADDING = 16

# Bar colors
HP_ALLY    = (60, 210, 100)    # green
HP_ENEMY   = (210, 60, 60)     # red
MANA_COLOR = (60, 140, 230)    # blue
BAR_BG     = (40, 40, 50)

# Rank border colors
RANK_COLORS = {
    "F": (96, 125, 139),
    "E": (76, 175, 80),
    "D": (33, 150, 243),
    "C": (156, 39, 176),
    "B": (255, 152, 0),
    "A": (244, 67, 54),
    "S": (255, 215, 0),
}
BORDER = 3

# Status icon map (single chars for overlay)
STATUS_SHORT = {
    "Stun": "💫", "Poison": "☠", "Burn": "🔥",
    "Silence": "🔇", "Shield": "🛡", "DefenseDown": "↓",
}


def _riot_id_from_name(name: str) -> str:
    specials = {
        "Dr. Mundo": "DrMundo", "Kai'Sa": "KaiSa", "Kha'Zix": "Khazix",
        "Vel'Koz": "Velkoz", "Cho'Gath": "Chogath", "Kog'Maw": "KogMaw",
        "Rek'Sai": "RekSai", "Aurelion Sol": "AurelionSol", "Bel'Veth": "Belveth",
        "LeBlanc": "Leblanc", "Lee Sin": "LeeSin", "Master Yi": "MasterYi",
        "Miss Fortune": "MissFortune", "Tahm Kench": "TahmKench",
        "Twisted Fate": "TwistedFate", "Xin Zhao": "XinZhao",
        "Jarvan IV": "JarvanIV", "Nunu & Willump": "Nunu",
        "Renata Glasc": "Renata", "Wukong": "MonkeyKing",
    }
    return specials.get(name, name.replace(" ", "").replace("'", "").replace(".", ""))


async def _fetch_portrait(riot_id: str, session: aiohttp.ClientSession) -> Optional[Image.Image]:
    cache_path = CACHE_DIR / f"{riot_id}.jpg"
    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception:
            pass
    url = DDRAGON_LOADING.format(riot_id=riot_id)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.read()
                cache_path.write_bytes(data)
                return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        pass
    return None


def _placeholder(name: str, rank: str) -> Image.Image:
    img = Image.new("RGB", (308, 560), color=(30, 30, 50))
    draw = ImageDraw.Draw(img)
    initial = (name[0] if name else "?").upper()
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
    except Exception:
        font = ImageFont.load_default()
    color = RANK_COLORS.get(rank, (128, 128, 128))
    bbox = draw.textbbox((0, 0), initial, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((308 - tw) // 2, (560 - th) // 2 - 40), initial, fill=color, font=font)
    return img


def _draw_bar(draw: ImageDraw.Draw, x: int, y: int, w: int, h: int,
              ratio: float, fill: tuple, bg: tuple = BAR_BG):
    draw.rectangle([x, y, x + w, y + h], fill=bg)
    filled = max(0, min(w, int(w * ratio)))
    if filled > 0:
        draw.rectangle([x, y, x + filled, y + h], fill=fill)


def _render_card(portrait: Image.Image, unit: dict, is_enemy: bool) -> Image.Image:
    rank = unit.get("rank", "F")
    hp = unit.get("hp", 0)
    hp_max = unit.get("hp_max", 1)
    mana = unit.get("mana", 0)
    name = unit.get("name", "?")
    level = unit.get("level", 1)
    is_dead = hp <= 0

    border_color = RANK_COLORS.get(rank, (128, 128, 128))
    total_w = CARD_W + BORDER * 2
    total_h = CARD_TOTAL_H + BORDER * 2

    card = Image.new("RGB", (total_w, total_h), color=BG_COLOR)
    draw = ImageDraw.Draw(card)

    # Draw border
    draw.rectangle([0, 0, total_w - 1, CARD_H + BORDER * 2 - 1], outline=border_color, width=BORDER)

    # Scale portrait to card dims
    portrait_scaled = portrait.resize((CARD_W, CARD_H), Image.LANCZOS)
    if is_dead:
        portrait_scaled = portrait_scaled.convert("L").convert("RGB")

    card.paste(portrait_scaled, (BORDER, BORDER))

    # Dead overlay
    if is_dead:
        overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 120))
        card_rgba = card.convert("RGBA")
        card_rgba.paste(overlay, (BORDER, BORDER), overlay)
        card = card_rgba.convert("RGB")
        draw = ImageDraw.Draw(card)

    # Bar area Y start (below portrait + border)
    bar_y = CARD_H + BORDER * 2 + BAR_MARGIN
    bar_x = BORDER

    # HP bar
    hp_ratio = max(0.0, min(1.0, hp / hp_max)) if hp_max > 0 else 0.0
    hp_color = HP_ENEMY if is_enemy else HP_ALLY
    _draw_bar(draw, bar_x, bar_y, CARD_W, BAR_H, hp_ratio, hp_color)

    # Mana bar
    mana_ratio = max(0.0, min(1.0, mana / 100))
    mana_y = bar_y + BAR_H + BAR_MARGIN
    _draw_bar(draw, bar_x, mana_y, CARD_W, MANA_H, mana_ratio, MANA_COLOR)

    # Name label
    name_y = mana_y + MANA_H + BAR_MARGIN + 2
    try:
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    except Exception:
        font_sm = ImageFont.load_default()

    short_name = name if len(name) <= 12 else name[:11] + "…"
    label = f"{short_name} [{rank}] {level}"
    bbox = draw.textbbox((0, 0), label, font=font_sm)
    tw = bbox[2] - bbox[0]
    draw.text((BORDER + max(0, (CARD_W - tw) // 2), name_y), label,
              fill=(220, 220, 220), font=font_sm)

    # Status icons
    statuses = unit.get("status_effects", [])
    if statuses:
        status_str = " ".join(STATUS_SHORT.get(s, "") for s in statuses if s in STATUS_SHORT)
        if status_str:
            draw.text((BORDER + 2, BORDER + 4), status_str, fill=(255, 230, 100), font=font_sm)

    return card


async def generate_battle_image(
    player_units: list[dict],
    enemy_units: list[dict],
) -> Optional[io.BytesIO]:
    if not _PIL_AVAILABLE:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            # Fetch all portraits concurrently
            all_units = [(u, False) for u in player_units] + [(u, True) for u in enemy_units]

            async def get_portrait(unit: dict) -> Image.Image:
                riot_id = unit.get("riot_id") or _riot_id_from_name(unit.get("name", ""))
                img = await _fetch_portrait(riot_id, session)
                return img or _placeholder(unit.get("name", "?"), unit.get("rank", "F"))

            portraits = await asyncio.gather(*[get_portrait(u) for u, _ in all_units])

        n_enemy = len(enemy_units)
        n_player = len(player_units)
        max_cols = max(n_enemy, n_player, 1)

        card_w = CARD_W + BORDER * 2
        card_h_total = CARD_TOTAL_H + BORDER * 2

        canvas_w = CANVAS_PADDING * 2 + max_cols * card_w + (max_cols - 1) * CARD_GAP
        canvas_h = (CANVAS_PADDING * 2 + ROW_LABEL_H * 2 + card_h_total * 2 + SECTION_GAP)

        canvas = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        try:
            font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except Exception:
            font_label = ImageFont.load_default()

        # Helper to paste a row of cards centered
        def paste_row(units_with_portraits, y_start: int, label: str, label_color: tuple, is_enemy: bool):
            # Row label
            draw.text((CANVAS_PADDING, y_start), label, fill=label_color, font=font_label)
            y = y_start + ROW_LABEL_H

            row_count = len(units_with_portraits)
            total_row_w = row_count * card_w + (row_count - 1) * CARD_GAP
            x_start = (canvas_w - total_row_w) // 2

            for i, (unit, portrait) in enumerate(units_with_portraits):
                card_img = _render_card(portrait, unit, is_enemy)
                x = x_start + i * (card_w + CARD_GAP)
                canvas.paste(card_img, (x, y))

        # Player row (top) — portraits[0:n_player] (players come first in all_units)
        player_pairs = list(zip(player_units, portraits[:n_player]))
        paste_row(player_pairs, CANVAS_PADDING, "YOUR TEAM", (80, 210, 120), is_enemy=False)

        # Separator
        sep_y = CANVAS_PADDING + ROW_LABEL_H + card_h_total + SECTION_GAP // 2
        draw.rectangle([CANVAS_PADDING, sep_y, canvas_w - CANVAS_PADDING, sep_y + 1], fill=(50, 55, 70))

        # Enemy row (bottom) — portraits[n_player:] (enemies come after players in all_units)
        enemy_y = CANVAS_PADDING + ROW_LABEL_H + card_h_total + SECTION_GAP
        enemy_pairs = list(zip(enemy_units, portraits[n_player:]))
        paste_row(enemy_pairs, enemy_y, "ENEMIES", (210, 80, 80), is_enemy=True)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    except Exception:
        return None
