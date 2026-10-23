import io

import pytest
from PIL import Image

from app.core.config import settings
from app.services.images import InvalidImageError, process_upload


def _image_bytes(
    size: tuple[int, int] = (400, 300),
    mode: str = "RGB",
    fmt: str = "JPEG",
    exif: Image.Exif | None = None,
) -> bytes:
    buffer = io.BytesIO()
    image = Image.new(mode, size, color=(200, 30, 30, 255)[: len(mode)])
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def test_jpeg_is_accepted() -> None:
    result = process_upload(_image_bytes())
    assert result.content_type == "image/jpeg"
    assert (result.width, result.height) == (400, 300)


def test_png_with_alpha_stays_png() -> None:
    result = process_upload(_image_bytes(mode="RGBA", fmt="PNG"))
    assert result.content_type == "image/png"


def test_large_image_is_downscaled() -> None:
    side = settings.generation.max_image_side
    result = process_upload(_image_bytes(size=(side * 2, side)))
    assert max(result.width, result.height) == side


def test_exif_orientation_applied_and_metadata_stripped() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # повернуть на 90°
    exif[0x010F] = "SecretCam"  # Make: любые метаданные должны исчезнуть
    result = process_upload(_image_bytes(size=(400, 300), exif=exif))

    assert (result.width, result.height) == (300, 400)
    with Image.open(io.BytesIO(result.data)) as image:
        assert not image.getexif()


@pytest.mark.parametrize(
    "payload",
    [b"", b"not an image at all", b"%PDF-1.7 fake pdf"],
)
def test_garbage_is_rejected(payload: bytes) -> None:
    with pytest.raises(InvalidImageError):
        process_upload(payload)


def test_unsupported_format_is_rejected() -> None:
    with pytest.raises(InvalidImageError):
        process_upload(_image_bytes(fmt="GIF", mode="P"))


def test_too_many_pixels_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.generation, "max_image_pixels", 100)
    with pytest.raises(InvalidImageError):
        process_upload(_image_bytes(size=(20, 20)))
