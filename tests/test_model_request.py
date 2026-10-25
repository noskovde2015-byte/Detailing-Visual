from app.models.generation_image import ImageRole
from app.schemas.generation import GenerationParams, WheelParams
from app.services.colors import render_swatch
from app.services.image_generator import ImageData
from app.services.model_request import build_model_request

CAR = ImageData(data=b"car", mime_type="image/jpeg")
FILM = ImageData(data=b"film", mime_type="image/jpeg")
WHEEL = ImageData(data=b"wheel", mime_type="image/jpeg")


def test_images_follow_prompt_order() -> None:
    params = GenerationParams(wheels=WheelParams(current_size=18, new_size=20))
    request = build_model_request(
        params, {ImageRole.WHEEL: WHEEL, ImageRole.FILM: FILM, ImageRole.CAR: CAR}
    )
    assert request.images == [CAR, FILM, WHEEL]
    assert "third image is a photo of car wheels" in request.prompt


def test_color_swatch_is_rendered_in_film_slot() -> None:
    params = GenerationParams(
        film_color="#1F0101", wheels=WheelParams(current_size=18, new_size=20)
    )
    request = build_model_request(params, {ImageRole.CAR: CAR, ImageRole.WHEEL: WHEEL})

    assert len(request.images) == 3
    assert request.images[0] == CAR
    assert request.images[1] == ImageData(
        data=render_swatch("#1F0101"), mime_type="image/png"
    )
    assert request.images[2] == WHEEL
    assert "second image is a flat swatch" in request.prompt
