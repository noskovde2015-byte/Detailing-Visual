from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class ImageData:
    data: bytes
    mime_type: str


class ImageGenerationError(Exception):
    """Не удалось сгенерировать изображение. Текст безопасно показывать пользователю."""


class GenerationRefusedError(ImageGenerationError):
    """Модель отказалась или вернула ответ без изображения. Повторять бессмысленно."""


class GenerationTemporaryError(ImageGenerationError):
    """Кратковременный сбой (перегрузка, таймаут, 5xx). Можно повторить позже."""


class GenerationUnavailableError(ImageGenerationError):
    """Генерация недоступна до вмешательства: кончилась квота, нет биллинга,
    неверный ключ или модель. Требует внимания разработчика."""


class ImageGenerator(ABC):
    name: str

    @abstractmethod
    async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData: ...


@lru_cache
def get_image_generator() -> ImageGenerator:
    from app.core.config import settings

    match settings.generation.backend:
        case "gemini":
            from app.services.gemini import GeminiImageGenerator

            return GeminiImageGenerator()
        case "fake":
            from app.services.fake_generator import FakeImageGenerator

            return FakeImageGenerator()
        case backend:
            raise RuntimeError(f"Неизвестный бэкенд генерации: {backend}")
