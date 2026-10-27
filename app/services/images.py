import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.services.aspect_ratio import ImageSize, ratio_distance
from app.services.image_generator import ImageData

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
JPEG_QUALITY = 90


class InvalidImageError(ValueError):
    """Файл не является допустимым изображением. Текст безопасно показывать."""


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    data: bytes
    content_type: str
    width: int
    height: int


def process_upload(raw: bytes) -> ProcessedImage:
    """Проверяет и нормализует загруженное изображение.

    - тип определяется по содержимому, а не по имени или заголовку от клиента;
    - защита от «decompression bomb» (маленький файл, огромная картинка);
    - поворот по EXIF применяется к пикселям, после чего все метаданные
      (включая геолокацию) отбрасываются пересохранением;
    - слишком большие фото уменьшаются: меньше токенов и быстрее генерация;
    - картинки с прозрачностью сохраняются в PNG, остальные в JPEG.

    Функция блокирующая: из async-кода вызывать через asyncio.to_thread.
    """
    if not raw:
        raise InvalidImageError("Файл пустой")

    limits = settings.generation
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as opened:
                image_format = opened.format
                if image_format not in ALLOWED_FORMATS:
                    raise InvalidImageError("Поддерживаются только JPEG, PNG и WEBP")
                if opened.width * opened.height > limits.max_image_pixels:
                    raise InvalidImageError("Слишком большое разрешение изображения")
                opened.load()
                image = ImageOps.exif_transpose(opened)
    except InvalidImageError:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise InvalidImageError("Файл повреждён или не является изображением") from exc

    image.thumbnail(
        (limits.max_image_side, limits.max_image_side), Image.Resampling.LANCZOS
    )

    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )
    output = io.BytesIO()
    if has_alpha:
        image = image.convert("RGBA")
        image.save(output, format="PNG", optimize=True)
        content_type = "image/png"
    else:
        image = image.convert("RGB")
        image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        content_type = "image/jpeg"

    return ProcessedImage(
        data=output.getvalue(),
        content_type=content_type,
        width=image.width,
        height=image.height,
    )


def make_preview(data: bytes) -> ProcessedImage:
    """Уменьшенная копия для галереи: JPEG до preview_max_side пикселей по большей
    стороне. Результат модели бывает PNG на несколько мегабайт, а сетка из
    десятков таких картинок грузилась бы очень долго.

    Функция блокирующая: из async-кода вызывать через asyncio.to_thread.
    """
    limits = settings.generation
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
    image.thumbnail(
        (limits.preview_max_side, limits.preview_max_side), Image.Resampling.LANCZOS
    )
    output = io.BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=limits.preview_quality,
        optimize=True,
        progressive=True,
    )
    return ProcessedImage(
        data=output.getvalue(),
        content_type="image/jpeg",
        width=image.width,
        height=image.height,
    )


# Ниже этой разницы пропорции считаем совпавшими и картинку не пересохраняем.
_SAME_RATIO = 0.002

_SAVE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


def fit_aspect_ratio(result: ImageData, source: ImageSize) -> ImageData:
    """Подрезает результат модели до точных пропорций исходного фото.

    Модель принимает только фиксированные соотношения (5:4, 4:3, 16:9…), а фото
    бывают «почти» такими: 1600×1300 — это не ровно 5:4. Небольшую разницу
    срезаем поровну с двух сторон. Если разница больше допуска, оставляем как
    есть: такой срез мог бы отрезать часть машины.

    Функция блокирующая: из async-кода вызывать через asyncio.to_thread.
    """
    image_format = _SAVE_FORMATS.get(result.mime_type)
    if image_format is None:
        return result

    with Image.open(io.BytesIO(result.data)) as opened:
        opened.load()
        image = opened.copy()

    difference = ratio_distance(image.width / image.height, source.ratio)
    if (
        difference <= _SAME_RATIO
        or difference > settings.generation.aspect_crop_tolerance
    ):
        return result

    if image.width / image.height > source.ratio:
        width = round(image.height * source.ratio)
        left = (image.width - width) // 2
        box = (left, 0, left + width, image.height)
    else:
        height = round(image.width / source.ratio)
        top = (image.height - height) // 2
        box = (0, top, image.width, top + height)

    cropped = image.crop(box)
    output = io.BytesIO()
    if image_format == "JPEG":
        cropped.convert("RGB").save(output, format="JPEG", quality=95, optimize=True)
    else:
        cropped.save(output, format=image_format)
    return ImageData(data=output.getvalue(), mime_type=result.mime_type)
