import io

import pytest
from PIL import Image

import utils.image_gen as image_gen
from utils.image_gen import (
    _riot_id_from_name,
    generate_team_banner,
    CARD_W,
    CARD_H,
    BORDER_THICKNESS,
    BANNER_PADDING,
)


def test_riot_id_special_cases():
    assert _riot_id_from_name("Kai'Sa") == "KaiSa"
    assert _riot_id_from_name("Dr. Mundo") == "DrMundo"
    assert _riot_id_from_name("Wukong") == "MonkeyKing"
    assert _riot_id_from_name("Nunu") == "Nunu"


def test_riot_id_fallback_strips_chars():
    # Not in the special table -> strip spaces/apostrophes/dots
    assert _riot_id_from_name("Some New'Champ") == "SomeNewChamp"


@pytest.mark.asyncio
async def test_generate_team_banner_dimensions(monkeypatch):
    """Banner stitches N bordered cards side by side. No real downloads."""
    async def fake_download(session, riot_id):
        return Image.new("RGB", (308, 560), color=(10, 20, 30))

    monkeypatch.setattr(image_gen, "_download_image", fake_download)

    champions = [
        {"name": "Aatrox", "rank": "S", "level": 5, "riot_id": "Aatrox"},
        {"name": "Ahri", "rank": "F", "level": 1, "riot_id": ""},
        {"name": "Kai'Sa", "rank": "A", "level": 3},
    ]
    buf = await generate_team_banner(champions)
    assert isinstance(buf, io.BytesIO)

    img = Image.open(buf)
    n = len(champions)
    card_w = CARD_W + BORDER_THICKNESS * 2
    card_h = CARD_H + BORDER_THICKNESS * 2
    assert img.size == (n * card_w + (n - 1) * BANNER_PADDING, card_h)


@pytest.mark.asyncio
async def test_generate_team_banner_download_failure_uses_placeholder(monkeypatch):
    async def fail_download(session, riot_id):
        return None

    monkeypatch.setattr(image_gen, "_download_image", fail_download)

    buf = await generate_team_banner([{"name": "Aatrox", "rank": "F", "level": 1}])
    img = Image.open(buf)
    card_w = CARD_W + BORDER_THICKNESS * 2
    card_h = CARD_H + BORDER_THICKNESS * 2
    assert img.size == (card_w, card_h)
