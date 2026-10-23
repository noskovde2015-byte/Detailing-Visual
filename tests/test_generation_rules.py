import pytest

from app.models.generation_image import ImageRole
from app.schemas.generation import FilmFinish, GenerationParams, WheelParams
from app.services.generation_rules import GenerationInputError, validate_generation_input


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
