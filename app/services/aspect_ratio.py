"""Соотношение сторон результата: такое же, как у исходного фото машины.

Модель не принимает произвольные пропорции — только фиксированный список.
Поэтому сначала просим ближайшее поддерживаемое соотношение, а потом
(см. images.fit_aspect_ratio) подрезаем небольшую разницу до точных
пропорций исходника.
"""

import io
import math
from dataclasses import dataclass

from PIL import Image

# Соотношения, которые принимает Nano Banana Pro (gemini-3-pro-image).
SUPPORTED_ASPECT_RATIOS: tuple[str, ...] = (
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
)


@dataclass(frozen=True, slots=True)
class ImageSize:
    width: int
    height: int

    @property
    def ratio(self) -> float:
        return self.width / self.height


def ratio_value(name: str) -> float:
    width, height = name.split(":")
    return int(width) / int(height)


def ratio_distance(a: float, b: float) -> float:
    """Насколько различаются пропорции, в долях (0.05 — на 5%).

    Считается через логарифм: «шире на 5%» и «уже на 5%» дают одно и то же
    число, а простая разность отношений завышала бы разницу у широких кадров.
    """
    return abs(math.log(a / b))


def nearest_aspect_ratio(size: ImageSize) -> str:
    """Ближайшее к пропорциям картинки соотношение из поддерживаемых."""
    return min(
        SUPPORTED_ASPECT_RATIOS,
        key=lambda name: ratio_distance(ratio_value(name), size.ratio),
    )


def read_size(data: bytes) -> ImageSize:
    """Размер картинки. Pillow читает только заголовок, пиксели не декодируются."""
    with Image.open(io.BytesIO(data)) as image:
        return ImageSize(width=image.width, height=image.height)
