import enum
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


class OutageReason(enum.StrEnum):
    """Почему генерация недоступна для всех, а не для одной задачи."""

    REGION = "region"
    """Google не обслуживает страну, из которой пришёл запрос."""
    BILLING = "billing"
    """Кончилась предоплата или проблема с оплатой."""
    QUOTA = "quota"
    """Исчерпана квота или достигнут лимит расходов."""
    AUTH = "auth"
    """Ключ отклонён или проект заблокирован."""
    MODEL = "model"
    """Модель не найдена."""
    NETWORK = "network"
    """Нет связи с Google (например, лежат оба выходных узла)."""
    MANUAL = "manual"
    """Приостановлено администратором."""

    @property
    def auto_resume(self) -> bool:
        """Можно ли проверить устранение автоматически, без запроса на генерацию.

        Только связь: остальное (оплата, регион, ключ) проверяется лишь
        настоящим запросом, а слать в Google заведомо отклоняемые запросы
        раз в минуту — лишний повод для блокировки аккаунта.
        """
        return self is OutageReason.NETWORK


class GenerationUnavailableError(ImageGenerationError):
    """Генерация недоступна до устранения причины: регион, оплата, квота, ключ,
    модель или связь. Касается всех задач, а не одной, поэтому очередь
    ставится на паузу, а задачи ждут, а не проваливаются одна за другой."""

    def __init__(self, message: str, *, reason: OutageReason, detail: str = "") -> None:
        super().__init__(message)
        self.reason = reason
        self.detail = detail
        """Технические подробности для администратора. Пользователю не показывать."""


class ImageGenerator(ABC):
    name: str

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        images: Sequence[ImageData],
        *,
        aspect_ratio: str | None = None,
    ) -> ImageData:
        """aspect_ratio — желаемое соотношение сторон результата («5:4»).
        Генератор, который не умеет его задавать, может параметр игнорировать:
        точные пропорции всё равно подгоняются после генерации."""

    async def check(self) -> None:
        """Лёгкая проверка доступности без генерации (и без оплаты).

        Бросает GenerationUnavailableError, если генерация недоступна.
        По умолчанию проверять нечего.
        """


def configured_model_name() -> str:
    """Имя модели, которой будет выполнена генерация.

    Нужно API, чтобы записать его в генерацию, не создавая клиента Gemini:
    генерацию выполняет воркер, и API не должен зависеть от ключа модели.
    """
    from app.core.config import settings

    match settings.generation.backend:
        case "gemini":
            return settings.gemini.model
        case backend:
            return backend


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
