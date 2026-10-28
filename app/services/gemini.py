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
    OutageReason,
)

try:
    # google-genai ходит через aiohttp, если он установлен (в проекте он есть
    # как зависимость aiobotocore), иначе через httpx. Ловим ошибки обоих.
    from aiohttp import ClientConnectionError as _AiohttpConnectionError
except ImportError:  # pragma: no cover
    _AiohttpConnectionError = httpx.TransportError

logger = logging.getLogger(__name__)

NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    _AiohttpConnectionError,
)
"""Нет связи: недоступен прокси, оба узла, или соединение оборвалось."""

CHECK_TIMEOUT_SECONDS = 20
DETAIL_MAX_LENGTH = 500

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


def _is_api_key_invalid(exc: errors.APIError) -> bool:
    for item in _error_details(exc):
        if item.get("reason") == "API_KEY_INVALID":
            return True
    return "api key not valid" in (exc.message or "").lower()


def outage_reason(exc: BaseException) -> OutageReason | None:
    """Ошибка касается всех генераций (а не этого фото)? Тогда — её причина.

    Такие ошибки бессмысленно повторять по каждой задаче: следующий запрос
    упадёт так же, а запросы из неподдерживаемого региона ещё и привлекают
    внимание Google к аккаунту. Очередь ставится на паузу до устранения.
    """
    if isinstance(exc, NETWORK_ERRORS):
        return OutageReason.NETWORK
    if not isinstance(exc, errors.APIError):
        return None

    message = (exc.message or "").lower()
    match exc.code:
        case 402:
            # Кончилась предоплата (Prepay) — Google отвечает именно 402.
            return OutageReason.BILLING
        case 400 if _is_api_key_invalid(exc):
            return OutageReason.AUTH
        case 400 if exc.status == "FAILED_PRECONDITION":
            # «User location is not supported for the API use.» — запрос пришёл
            # из страны, где Gemini API не работает (или без оплаты недоступен).
            if "billing" in message:
                return OutageReason.BILLING
            if any(word in message for word in ("location", "country", "region")):
                return OutageReason.REGION
            return None
        case 401:
            return OutageReason.AUTH
        case 403:
            return OutageReason.BILLING if "billing" in message else OutageReason.AUTH
        case 404:
            return OutageReason.MODEL
        case 429 if not is_retryable(exc):
            # Дневная квота, лимит расходов (spend cap) или пауза больше разумной.
            return OutageReason.QUOTA
    return None


def error_detail(exc: BaseException) -> str:
    """Короткое описание ошибки для администратора."""
    if isinstance(exc, errors.APIError):
        text = f"HTTP {exc.code} {exc.status or ''}: {exc.message or ''}"
    else:
        text = f"{type(exc).__name__}: {exc}"
    return " ".join(text.split())[:DETAIL_MAX_LENGTH]


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, *NETWORK_ERRORS)):
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
    # Сначала причина «для всех»: сетевые ошибки тоже повторяемые, но если они
    # не прошли и после повторов внутри запроса, дело не в этой задаче.
    reason = outage_reason(exc)
    if reason is not None:
        return GenerationUnavailableError(
            UNAVAILABLE_MESSAGE, reason=reason, detail=error_detail(exc)
        )
    if is_retryable(exc):
        return GenerationTemporaryError(TEMPORARY_MESSAGE)
    return ImageGenerationError(GENERIC_MESSAGE)


class GeminiImageGenerator(ImageGenerator):
    def __init__(self) -> None:
        config = settings.gemini
        if config.api_key is None:
            raise RuntimeError("Не задан APP_CONFIG__GEMINI__API_KEY")
        self._client = genai.Client(api_key=config.api_key.get_secret_value())
        self._timeout = config.timeout_seconds
        self._max_attempts = config.max_attempts
        self._image_size = config.image_size
        self.name = config.model

    async def generate(
        self,
        prompt: str,
        images: Sequence[ImageData],
        *,
        aspect_ratio: str | None = None,
    ) -> ImageData:
        contents: list[str | types.Part] = [
            prompt,
            *(
                types.Part.from_bytes(data=image.data, mime_type=image.mime_type)
                for image in images
            ),
        ]

        try:
            try:
                response = await self._request_with_retries(contents, aspect_ratio)
            except errors.APIError as exc:
                # 400 при заданном соотношении — скорее всего, модель перестала его
                # принимать. Лучше результат без него (пропорции всё равно подгоним
                # после генерации), чем отказ пользователю.
                if (
                    exc.code != 400
                    or aspect_ratio is None
                    or outage_reason(exc) is not None
                ):
                    raise
                logger.warning(
                    "Gemini отклонил aspect_ratio=%s (%s), повторяю без него",
                    aspect_ratio,
                    exc.message,
                )
                response = await self._request_with_retries(contents, None)
        except Exception as exc:
            domain_error = to_domain_error(exc)
            if isinstance(domain_error, GenerationUnavailableError):
                logger.error(
                    "Gemini недоступен (модель %s), причина %s: %s",
                    self.name,
                    domain_error.reason,
                    domain_error.detail,
                )
            else:
                logger.exception("Ошибка запроса к Gemini (модель %s)", self.name)
            raise domain_error from exc

        return self._extract_image(response)

    async def check(self) -> None:
        """Запрос описания модели: бесплатный и без генерации. Проходит тот же
        путь (прокси → узел → Google) и с тем же ключом, что и генерация."""
        try:
            await asyncio.wait_for(
                self._client.aio.models.get(model=self.name),
                timeout=CHECK_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            reason = outage_reason(exc)
            if reason is None and isinstance(exc, TimeoutError):
                reason = OutageReason.NETWORK
            if reason is not None:
                raise GenerationUnavailableError(
                    UNAVAILABLE_MESSAGE, reason=reason, detail=error_detail(exc)
                ) from exc
            # Любой другой ответ Google значит, что связь есть: этого и ждём.
            logger.info("Проверка Gemini: ответ с ошибкой, но связь есть: %s", exc)

    async def _request_with_retries(
        self, contents: list[str | types.Part], aspect_ratio: str | None
    ) -> types.GenerateContentResponse:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=2, max=20),
            retry=retry_if_exception(is_retryable),
            reraise=True,
        ):
            with attempt:
                return await self._request(contents, aspect_ratio)
        raise AssertionError("unreachable: AsyncRetrying с reraise=True")

    async def _request(
        self, contents: list[str | types.Part], aspect_ratio: str | None
    ) -> types.GenerateContentResponse:
        return await asyncio.wait_for(
            self._client.aio.models.generate_content(
                model=self.name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=aspect_ratio, image_size=self._image_size
                    ),
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
