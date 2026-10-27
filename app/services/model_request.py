from collections.abc import Mapping
from dataclasses import dataclass

from app.models.generation_image import ImageRole
from app.schemas.generation import GenerationParams
from app.services.aspect_ratio import ImageSize, nearest_aspect_ratio, read_size
from app.services.colors import render_swatch
from app.services.image_generator import ImageData
from app.services.prompt_builder import InputSlot, build_prompt, input_slots

SWATCH_MIME_TYPE = "image/png"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    prompt: str
    images: list[ImageData]
    # Размер фото машины: результат должен повторить его пропорции.
    source_size: ImageSize
    # Ближайшее к ним соотношение, которое понимает модель («5:4», «16:9»…).
    aspect_ratio: str


def build_model_request(
    params: GenerationParams, uploaded: Mapping[ImageRole, ImageData]
) -> ModelRequest:
    """Собирает промпт и картинки в том порядке, на который ссылается промпт.

    Порядок и нумерация берутся из одного места (input_slots), поэтому
    «second image» в тексте всегда совпадает со второй картинкой в запросе.

    Функция читает заголовок картинки (Pillow) — это быстро, но формально
    блокирующая операция; из async-кода её зовут через asyncio.to_thread.
    """
    images: list[ImageData] = []
    for slot in input_slots(params, uploaded.keys()):
        if slot is InputSlot.COLOR_SWATCH:
            assert params.film_color is not None
            images.append(
                ImageData(
                    data=render_swatch(params.film_color),
                    mime_type=SWATCH_MIME_TYPE,
                )
            )
        else:
            images.append(uploaded[ImageRole(slot.value)])

    source_size = read_size(uploaded[ImageRole.CAR].data)
    return ModelRequest(
        prompt=build_prompt(params, uploaded.keys()),
        images=images,
        source_size=source_size,
        aspect_ratio=nearest_aspect_ratio(source_size),
    )
