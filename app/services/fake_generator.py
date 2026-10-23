import asyncio
import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.services.image_generator import ImageData, ImageGenerator

LABEL = "FAKE GENERATION"


class FakeImageGenerator(ImageGenerator):
    """Генератор для разработки и тестов: не ходит во внешний API и ничего не стоит.

    Возвращает первую входную картинку (фото машины) с плашкой «FAKE GENERATION».
    """

    name = "fake"

    def __init__(self, delay_seconds: float | None = None) -> None:
        self._delay = (
            settings.generation.fake_delay_seconds
            if delay_seconds is None
            else delay_seconds
        )

    async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData:
        if not images:
            raise ValueError("Нужно хотя бы одно входное изображение")
        await asyncio.sleep(self._delay)
        data = await asyncio.to_thread(self._render, images[0].data)
        return ImageData(data=data, mime_type="image/png")

    @staticmethod
    def _render(source: bytes) -> bytes:
        with Image.open(io.BytesIO(source)) as opened:
            image = opened.convert("RGB")

        draw = ImageDraw.Draw(image, "RGBA")
        band_height = max(32, image.height // 10)
        font = ImageFont.load_default(size=int(band_height * 0.6))
        draw.rectangle(
            (0, image.height - band_height, image.width, image.height),
            fill=(0, 0, 0, 160),
        )
        draw.text(
            (image.width / 2, image.height - band_height / 2),
            LABEL,
            fill=(255, 255, 255, 255),
            font=font,
            anchor="mm",
        )

        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
