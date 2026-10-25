from collections.abc import Mapping
from dataclasses import dataclass

from app.models.generation_image import ImageRole
from app.schemas.generation import GenerationParams
from app.services.colors import render_swatch
from app.services.image_generator import ImageData
from app.services.prompt_builder import InputSlot, build_prompt, input_slots

SWATCH_MIME_TYPE = "image/png"


@dataclass(frozen=True, slots=True)
class ModelRequest:
    prompt: str
    images: list[ImageData]


def build_model_request(
    params: GenerationParams, uploaded: Mapping[ImageRole, ImageData]
) -> ModelRequest:
    """Собирает промпт и картинки в том порядке, на который ссылается промпт.

    Порядок и нумерация берутся из одного места (input_slots), поэтому
    «second image» в тексте всегда совпадает со второй картинкой в запросе.
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

    return ModelRequest(prompt=build_prompt(params, uploaded.keys()), images=images)
