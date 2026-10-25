import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

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
