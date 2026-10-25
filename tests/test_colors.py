import io

import pytest
from PIL import Image

from app.services.colors import Rgb, describe_color, parse_hex, render_swatch


def test_parse_hex() -> None:
    assert parse_hex("#1F0101") == Rgb(31, 1, 1)
    assert parse_hex("#1f0101").hex == "#1F0101"


@pytest.mark.parametrize("value", ["1F0101", "#1F01", "#XYZXYZ", ""])
def test_parse_hex_rejects_garbage(value: str) -> None:
    with pytest.raises(ValueError):
        parse_hex(value)


@pytest.mark.parametrize(
    ("hex_color", "expected"),
    [
        ("#1F0101", "very dark red"),
        ("#000000", "black"),
        ("#FFFFFF", "white"),
        ("#808080", "medium gray"),
        ("#36454F", "dark muted grayish blue"),
        ("#FF0000", "vivid red"),
        ("#0047AB", "vivid blue"),
        ("#00FF00", "vivid green"),
        ("#FFC0CB", "very light pink"),
        ("#5C3A1E", "dark brown"),
        ("#FFD700", "vivid yellow"),
        ("#2A2A2E", "very dark gray (anthracite)"),
        ("#800080", "dark purple"),
        ("#7B8C7A", "medium gray"),
    ],
)
def test_describe_color(hex_color: str, expected: str) -> None:
    assert describe_color(parse_hex(hex_color)) == expected


def test_swatch_is_solid_png_of_that_color() -> None:
    data = render_swatch("#1F0101")
    assert data.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(data)) as image:
        assert image.getcolors() == [(image.width * image.height, (31, 1, 1))]
