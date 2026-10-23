from collections.abc import Collection

from app.models.generation_image import ImageRole
from app.schemas.generation import GenerationParams


class GenerationInputError(ValueError):
    """Входные данные генерации не прошли проверку."""


def validate_generation_input(
    params: GenerationParams,
    roles: Collection[ImageRole],
) -> None:
    present = set(roles)

    if ImageRole.CAR not in present:
        raise GenerationInputError("Нужно загрузить фото автомобиля")

    has_wheel_photo = ImageRole.WHEEL in present
    if has_wheel_photo and params.wheels is None:
        raise GenerationInputError("Для фото дисков нужно указать размер")
    if params.wheels is not None and not has_wheel_photo:
        raise GenerationInputError("Размер дисков указан без фото дисков")

    if params.film_finish is not None and ImageRole.FILM not in present:
        raise GenerationInputError("Тип покрытия указан без фото плёнки")

    has_changes = any(
        (
            ImageRole.FILM in present,
            has_wheel_photo,
            params.antichrome,
            params.tint,
            bool(params.comment and params.comment.strip()),
        )
    )
    if not has_changes:
        raise GenerationInputError("Не выбрано ни одного изменения")
