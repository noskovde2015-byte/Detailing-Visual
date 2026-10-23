import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from google import genai
from google.genai import errors, types
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImageData:
    data: bytes
    mime_type: str


class ImageGenerationError(Exception):
    """Не удалось сгенерировать изображение. Текст безопасно показывать пользователю."""


class GenerationRefusedError(ImageGenerationError):
    """Модель отказалась или вернула ответ без изображения. Повторять запрос бессмысленно."""


class GenerationTemporaryError(ImageGenerationError):
    """Временный сбой (лимиты, таймаут, 5xx). Можно попробовать позже."""


class ImageGenerator(ABC):
    @abstractmethod
    async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData: ...


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, errors.APIError):
        return exc.code == 429 or exc.code >= 500
    return False


class GeminiImageService(ImageGenerator):
    def __init__(self) -> None:
        config = settings.gemini
        if config.api_key is None:
            raise RuntimeError("Не задан APP_CONFIG__GEMINI__API_KEY")
        self._client = genai.Client(api_key=config.api_key.get_secret_value())
        self._model = config.model
        self._timeout = config.timeout_seconds
        self._max_attempts = config.max_attempts

    async def generate(self, prompt: str, images: Sequence[ImageData]) -> ImageData:
        contents: list[str | types.Part] = [
            prompt,
            *(
                types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
                for image in images
            ),
        ]

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_exponential(multiplier=2, max=20),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    response = await self._request(contents)
        except Exception as exc:
            logger.exception("Ошибка запроса к Gemini (модель %s)", self._model)
            if _is_retryable(exc):
                raise GenerationTemporaryError(
                    "Сервис генерации временно перегружен. Попробуйте позже."
                ) from exc
            raise ImageGenerationError("Не удалось выполнить генерацию.") from exc

        return self._extract_image(response)

    async def _request(
        self, contents: list[str | types.Part]
    ) -> types.GenerateContentResponse:
        return await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                ),
            ),
            timeout=self._timeout,
        )

    @staticmethod
    def _extract_image(response: types.GenerateContentResponse) -> ImageData:
        refused = GenerationRefusedError(
            "Модель не смогла обработать это фото. "
            "Попробуйте другое фото или измените пожелания."
        )

        if not response.candidates:
            logger.warning("Gemini без кандидатов: %s", response.prompt_feedback)
            raise refused

        candidate = response.candidates[0]
        parts = candidate.content.parts if candidate.content else None

        for part in parts or []:
            if part.inline_data and part.inline_data.data:
                return ImageData(
                    data=part.inline_data.data,
                    mime_type=part.inline_data.mime_type or "image/png",
                )

        text = " ".join(part.text for part in parts or [] if part.text)
        logger.warning(
            "Gemini без изображения: finish_reason=%s, текст=%r",
            candidate.finish_reason,
            text,
        )
        raise refused


@lru_cache
def get_image_generator() -> ImageGenerator:
    return GeminiImageService()
