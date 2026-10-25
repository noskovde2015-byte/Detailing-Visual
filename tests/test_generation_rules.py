import pytest
from pydantic import ValidationError

from app.models.generation_image import ImageRole
from app.schemas.generation import FilmFinish, GenerationParams, WheelParams
from app.services.generation_rules import (
    GenerationInputError,
    validate_generation_input,
)


def test_car_is_required() -> None:
    with pytest.raises(GenerationInputError):
        validate_generation_input(GenerationParams(antichrome=True), [ImageRole.FILM])


def test_at_least_one_change_required() -> None:
    with pytest.raises(GenerationInputError):
        validate_generation_input(GenerationParams(), [ImageRole.CAR])


def test_blank_comment_is_not_a_change() -> None:
    with pytest.raises(GenerationInputError):
        validate_generation_input(GenerationParams(comment="   "), [ImageRole.CAR])


@pytest.mark.parametrize(
    ("params", "roles"),
    [
        (GenerationParams(antichrome=True), [ImageRole.CAR]),
        (GenerationParams(tint=True), [ImageRole.CAR]),
        (GenerationParams(comment="make it lower"), [ImageRole.CAR]),
        (GenerationParams(), [ImageRole.CAR, ImageRole.FILM]),
        (
            GenerationParams(film_finish=FilmFinish.GLOSSY),
            [ImageRole.CAR, ImageRole.FILM],
        ),
        (
            GenerationParams(wheels=WheelParams(current_size=18, new_size=20)),
            [ImageRole.CAR, ImageRole.WHEEL],
        ),
        (GenerationParams(film_color="#1F0101"), [ImageRole.CAR]),
        (
            GenerationParams(film_color="#1F0101", film_finish=FilmFinish.MATTE),
            [ImageRole.CAR],
        ),
    ],
)
def test_valid_inputs(params: GenerationParams, roles: list[ImageRole]) -> None:
    validate_generation_input(params, roles)


def test_wheel_photo_without_sizes() -> None:
    with pytest.raises(GenerationInputError):
        validate_generation_input(GenerationParams(), [ImageRole.CAR, ImageRole.WHEEL])


def test_wheel_sizes_without_photo() -> None:
    params = GenerationParams(wheels=WheelParams(current_size=18, new_size=20))
    with pytest.raises(GenerationInputError):
        validate_generation_input(params, [ImageRole.CAR])


def test_finish_without_film() -> None:
    params = GenerationParams(antichrome=True, film_finish=FilmFinish.GLOSSY)
    with pytest.raises(GenerationInputError):
        validate_generation_input(params, [ImageRole.CAR])


def test_film_photo_and_color_are_exclusive() -> None:
    params = GenerationParams(film_color="#1F0101")
    with pytest.raises(GenerationInputError, match="что-то одно"):
        validate_generation_input(params, [ImageRole.CAR, ImageRole.FILM])


@pytest.mark.parametrize("value", ["#1f0101", " #1F0101 "])
def test_film_color_is_normalized(value: str) -> None:
    assert GenerationParams(film_color=value).film_color == "#1F0101"


@pytest.mark.parametrize(
    "value", ["1F0101", "#1F01", "#1F010", "#GGGGGG", "red", "#1F0101FF", ""]
)
def test_invalid_film_color_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        GenerationParams(film_color=value)
