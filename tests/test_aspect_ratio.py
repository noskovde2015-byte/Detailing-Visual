import io
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from google.genai import errors, types
from PIL import Image

from app.services.aspect_ratio import ImageSize, nearest_aspect_ratio
from app.services.gemini import GeminiImageGenerator
from app.services.image_generator import (
    GenerationUnavailableError,
    ImageData,
    OutageReason,
)
from app.services.images import fit_aspect_ratio


def _png(width: int, height: int) -> ImageData:
    output = io.BytesIO()
    Image.new("RGB", (width, height), (120, 30, 30)).save(output, format="PNG")
    return ImageData(data=output.getvalue(), mime_type="image/png")


def _size(image: ImageData) -> tuple[int, int]:
    with Image.open(io.BytesIO(image.data)) as opened:
        return opened.size


# ---------- выбор соотношения ----------


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (2000, 1600, "5:4"),  # ровно 5:4
        (1600, 1300, "5:4"),  # «почти» 5:4
        (4032, 3024, "4:3"),  # обычное фото с телефона
        (3024, 4032, "3:4"),  # то же вертикально
        (6000, 4000, "3:2"),  # зеркальная камера
        (1920, 1080, "16:9"),
        (1080, 1350, "4:5"),  # вертикальный пост
        (1000, 1000, "1:1"),
        (2560, 1080, "21:9"),
    ],
)
def test_nearest_aspect_ratio(width: int, height: int, expected: str) -> None:
    assert nearest_aspect_ratio(ImageSize(width, height)) == expected


# ---------- подгонка результата ----------


def test_small_difference_is_cropped_to_exact_source_ratio() -> None:
    # Модель вернула ровно 5:4, а исходник 1600×1300 (≈ 1,231, разница ~1,5%).
    fitted = fit_aspect_ratio(_png(2000, 1600), ImageSize(1600, 1300))
    width, height = _size(fitted)
    assert height == 1600
    assert width == round(1600 * 1600 / 1300)
    assert fitted.mime_type == "image/png"


def test_taller_result_is_cropped_vertically() -> None:
    fitted = fit_aspect_ratio(_png(1600, 1300), ImageSize(2000, 1600))
    width, height = _size(fitted)
    assert width == 1600
    assert height == round(1600 / 1.25)


def test_same_ratio_is_returned_untouched() -> None:
    result = _png(2000, 1600)
    assert fit_aspect_ratio(result, ImageSize(1000, 800)) is result


def test_large_difference_is_left_as_is() -> None:
    # Скриншот телефона ~9:19,5 против выданного 9:16: срез отрезал бы машину.
    result = _png(1152, 2048)
    assert fit_aspect_ratio(result, ImageSize(1179, 2556)) is result


def test_unknown_format_is_left_as_is() -> None:
    result = ImageData(data=b"not-an-image", mime_type="image/heic")
    assert fit_aspect_ratio(result, ImageSize(1000, 800)) is result


# ---------- запрос к Gemini ----------


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeModels:
    def __init__(self, fail_with_400: bool, error: BaseException | None = None) -> None:
        self.configs: list[types.GenerateContentConfig] = []
        self._fail_with_400 = fail_with_400
        self._error = error
        self.get_calls = 0

    async def get(self, *, model: str) -> types.Model:
        self.get_calls += 1
        if self._error is not None:
            raise self._error
        return types.Model(name=model)

    async def generate_content(
        self,
        *,
        model: str,
        contents: Sequence[Any],
        config: types.GenerateContentConfig,
    ) -> types.GenerateContentResponse:
        self.configs.append(config)
        if self._error is not None:
            raise self._error
        if self._fail_with_400 and config.image_config.aspect_ratio is not None:
            raise errors.APIError(
                400, {"error": {"code": 400, "message": "bad ratio", "status": "X"}}
            )
        image = _png(10, 8)
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=image.data, mime_type=image.mime_type
                                )
                            )
                        ]
                    )
                )
            ]
        )


def _generator(models: _FakeModels) -> GeminiImageGenerator:
    generator = GeminiImageGenerator.__new__(GeminiImageGenerator)
    generator._client = type("C", (), {"aio": type("A", (), {"models": models})()})()
    generator._timeout = 5
    generator._max_attempts = 1
    generator._image_size = "2K"
    generator.name = "gemini-3-pro-image"
    return generator


@pytest.mark.anyio
async def test_gemini_receives_aspect_ratio_and_size() -> None:
    models = _FakeModels(fail_with_400=False)
    await _generator(models).generate("p", [_png(10, 8)], aspect_ratio="5:4")
    config = models.configs[0].image_config
    assert config.aspect_ratio == "5:4"
    assert config.image_size == "2K"


@pytest.mark.anyio
async def test_gemini_retries_without_ratio_on_400() -> None:
    models = _FakeModels(fail_with_400=True)
    result = await _generator(models).generate("p", [_png(10, 8)], aspect_ratio="5:4")
    assert result.mime_type == "image/png"
    assert [c.image_config.aspect_ratio for c in models.configs] == ["5:4", None]


REGION_ERROR = errors.APIError(
    400,
    {
        "error": {
            "code": 400,
            "message": "User location is not supported for the API use.",
            "status": "FAILED_PRECONDITION",
        }
    },
)


@pytest.mark.anyio
async def test_region_error_is_not_retried_without_ratio() -> None:
    # Повтор без aspect_ratio — только для «плохого параметра». Запрос из
    # неподдерживаемого региона нельзя слать второй раз.
    models = _FakeModels(fail_with_400=False, error=REGION_ERROR)
    with pytest.raises(GenerationUnavailableError) as caught:
        await _generator(models).generate("p", [_png(10, 8)], aspect_ratio="5:4")
    assert caught.value.reason is OutageReason.REGION
    assert len(models.configs) == 1


@pytest.mark.anyio
async def test_check_passes_when_google_answers() -> None:
    models = _FakeModels(fail_with_400=False)
    await _generator(models).check()
    assert models.get_calls == 1


@pytest.mark.anyio
async def test_check_passes_on_unrelated_google_error() -> None:
    # Google ответил хоть чем-то (500) — значит, связь через узлы есть.
    error = errors.APIError(500, {"error": {"code": 500, "message": "x"}})
    await _generator(_FakeModels(fail_with_400=False, error=error)).check()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx.ConnectError("proxy down"), OutageReason.NETWORK),
        (TimeoutError(), OutageReason.NETWORK),
        (REGION_ERROR, OutageReason.REGION),
    ],
)
async def test_check_reports_outage(error: BaseException, reason: OutageReason) -> None:
    with pytest.raises(GenerationUnavailableError) as caught:
        await _generator(_FakeModels(fail_with_400=False, error=error)).check()
    assert caught.value.reason is reason
