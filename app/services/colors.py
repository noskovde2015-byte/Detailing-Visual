"""Работа с цветом из палитры: разбор HEX, словесное описание и образец для модели.

Модели генерации плохо понимают голый HEX, поэтому цвет передаётся двумя
способами одновременно: однотонной картинкой-образцом и словесным описанием
(плюс HEX и RGB для точности).
"""

import colorsys
import io
import re
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image

HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
_HEX_RE = re.compile(HEX_COLOR_PATTERN)

SWATCH_SIDE = 512

# Границы оттенков (hue, градусы) и их названия. Последняя граница 360,
# поэтому красный встречается дважды: в начале и в конце круга.
_HUE_NAMES: tuple[tuple[float, str], ...] = (
    (15, "red"),
    (40, "orange"),
    (65, "yellow"),
    (80, "lime"),
    (155, "green"),
    (185, "teal"),
    (200, "cyan"),
    (250, "blue"),
    (275, "violet"),
    (315, "purple"),
    (345, "magenta"),
    (360, "red"),
)

# Насыщенность ниже этого порога воспринимается как оттенок серого.
_ACHROMATIC_SATURATION = 0.12
_GRAYISH_SATURATION = 0.35


@dataclass(frozen=True, slots=True)
class Rgb:
    red: int
    green: int
    blue: int

    @property
    def hex(self) -> str:
        return f"#{self.red:02X}{self.green:02X}{self.blue:02X}"


def parse_hex(value: str) -> Rgb:
    if not _HEX_RE.fullmatch(value):
        raise ValueError(f"Цвет должен быть в формате #RRGGBB, получено: {value!r}")
    return Rgb(int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def _hue_name(hue_degrees: float) -> str:
    for upper_bound, name in _HUE_NAMES:
        if hue_degrees < upper_bound:
            return name
    return "red"


def _achromatic_name(lightness: float) -> str:
    if lightness < 0.08:
        return "black"
    if lightness < 0.25:
        return "very dark gray (anthracite)"
    if lightness < 0.45:
        return "dark gray"
    if lightness < 0.65:
        return "medium gray"
    if lightness < 0.9:
        return "light gray"
    return "white"


def _lightness_prefix(lightness: float) -> str:
    if lightness < 0.15:
        return "very dark "
    if lightness < 0.3:
        return "dark "
    if lightness > 0.85:
        return "very light "
    if lightness > 0.7:
        return "light "
    return ""


def describe_color(rgb: Rgb) -> str:
    """Короткое английское описание цвета для промпта, например «very dark red».

    Это подсказка модели, а не точное имя цвета: точный цвет задают образец,
    HEX и RGB. Поэтому достаточно грубой классификации по HLS.
    """
    hue, lightness, saturation = colorsys.rgb_to_hls(
        rgb.red / 255, rgb.green / 255, rgb.blue / 255
    )
    if saturation < _ACHROMATIC_SATURATION or lightness < 0.04 or lightness > 0.97:
        return _achromatic_name(lightness)

    hue_degrees = hue * 360
    name = _hue_name(hue_degrees)

    # Тёмный оранжевый и тёмный жёлтый человек видит как коричневый,
    # светлый красный — как розовый.
    if name in ("orange", "yellow") and lightness < 0.35:
        name = "brown"
    elif name in ("red", "magenta") and lightness > 0.7:
        name = "pink"

    tone = ""
    if saturation < _GRAYISH_SATURATION:
        tone = "muted grayish "
    elif saturation > 0.8 and 0.3 <= lightness <= 0.7:
        tone = "vivid "

    return f"{_lightness_prefix(lightness)}{tone}{name}"


@lru_cache(maxsize=256)
def render_swatch(hex_color: str) -> bytes:
    """Однотонный квадрат цвета в PNG. Результат детерминирован, поэтому кешируется."""
    rgb = parse_hex(hex_color)
    image = Image.new("RGB", (SWATCH_SIDE, SWATCH_SIDE), (rgb.red, rgb.green, rgb.blue))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
