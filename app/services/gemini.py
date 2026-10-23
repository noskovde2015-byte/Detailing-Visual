import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.services.image_generator import (
    GenerationRefusedError,
    GenerationTemporaryError,
    GenerationUnavailableError,
    ImageData,
    ImageGenerationError,
    ImageGenerator,
)

logger = logging.getLogger(__name__)

REFUSED_MESSAGE = (
    "Модель не смогла обработать это фото. "
    "Попробуйте другое фото или измените пожелания."
)
TEMPORARY_MESSAGE = "Сервис генерации временно перегружен. Попробуйте позже."
UNAVAILABLE_MESSAGE = "Сервис генерации временно недоступен. Мы уже разбираемся."
GENERIC_MESSAGE = "Не удалось выполнить генерацию."


def _error_details(exc: errors.APIError) -> list[dict[str, Any]]:
    payload = exc.details if isinstance(exc.details, dict) else {}
    body = payload.get("error", payload)
    details = body.get("details") if isinstance(body, dict) else None
    return [item for item in details or [] if isinstance(item, dict)]


def retry_delay_seconds(exc: errors.APIError) -> float | None:
    """Достаёт из ответа Google рекомендованную паузу (RetryInfo.retryDelay)."""
    for item in _error_details(exc):
        if str(item.get("@type", "")).endswith("RetryInfo"):
            raw = str(item.get("retryDelay", "")).removesuffix("s")
            try:
                return float(raw)
            except ValueError:
                return None
    return None


def is_daily_quota_error(exc: errors.APIError) -> bool:
    for item in _error_details(exc):
        if str(item.get("@type", "")).endswith("QuotaFailure"):
            for violation in item.get("violations") or []:
                if "PerDay" in str(violation.get("quotaId", "")):
                    return True
    return False


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, httpx.TransportError)):
        return True
    if not isinstance(exc, errors.APIError):
        return False
    if exc.code >= 500:
        return True
    if exc.code == 429:
        if is_daily_quota_error(exc):
            return False
        delay = retry_delay_seconds(exc)
        return delay is None or delay <= settings.gemini.max_retry_delay_seconds
    return False


def to_domain_error(exc: BaseException) -> ImageGenerationError:
    if is_retryable(exc):
        return GenerationTemporaryError(TEMPORARY_MESSAGE)
    if isinstance(exc, errors.APIError) and exc.code in (401, 403, 404, 429):
        return GenerationUnavailableError(UNAVAILABLE_MESSAGE)
    return ImageGenerationError(GENERIC_MESSAGE)


class GeminiImageGenerator(ImageGenerator):
    def __init__(self) -> None:
        config = settings.gemini
        if config.api_key is None:
            raise RuntimeError("Не задан APP_CONFIG__GEMINI__API_KEY")
        self._client = genai.Client(api_key=config.api_key.get_secret_value())
        self._timeout = config.timeout_seconds
        self._max_attempts = config.max_attempts
        self.name = config.model

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
                retry=retry_if_exception(is_retryable),
                reraise=True,
            ):
                with attempt:
                    response = await self._request(contents)
        except Exception as exc:
            domain_error = to_domain_error(exc)
            if isinstance(domain_error, GenerationUnavailableError):
                logger.exception(
                    "Gemini недоступен (модель %s): квота, биллинг, ключ или модель",
                    self.name,
                )
            else:
                logger.exception("Ошибка запроса к Gemini (модель %s)", self.name)
            raise domain_error from exc

        return self._extract_image(response)

    async def _request(
        self, contents: list[str | types.Part]
    ) -> types.GenerateContentResponse:
        return await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=self.name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"]
                ),
            ),
            timeout=self._timeout,
        )

    @staticmethod
    def _extract_image(response: types.GenerateContentResponse) -> ImageData:
        if not response.candidates:
            logger.warning("Gemini без кандидатов: %s", response.prompt_feedback)
            raise GenerationRefusedError(REFUSED_MESSAGE)

        candidate = response.candidates[0]
        parts = (candidate.content.parts if candidate.content else None) or []

        for part in parts:
            if part.inline_data and part.inline_data.data:
                return ImageData(
                    data=part.inline_data.data,
                    mime_type=part.inline_data.mime_type or "image/png",
                )

        text = " ".join(part.text for part in parts if part.text)
        logger.warning(
            "Gemini без изображения: finish_reason=%s, текст=%r",
            candidate.finish_reason,
            text,
        )
        raise GenerationRefusedError(REFUSED_MESSAGE)
