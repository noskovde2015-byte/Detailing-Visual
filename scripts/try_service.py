import argparse
import asyncio
import mimetypes
import time
from pathlib import Path
from uuid import uuid4

from app.models.generation_image import ImageRole
from app.schemas.generation import FilmFinish, GenerationParams, WheelParams
from app.services.generation_rules import validate_generation_input
from app.services.image_generator import ImageData, get_image_generator
from app.services.model_request import build_model_request
from app.services.storage import build_image_key, get_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Проверка цепочки генерации")
    parser.add_argument("--car", type=Path, required=True)
    parser.add_argument("--film", type=Path)
    parser.add_argument("--color", help="Цвет плёнки из палитры, например #1F0101")
    parser.add_argument("--finish", choices=[f.value for f in FilmFinish])
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--wheel-from", type=int)
    parser.add_argument("--wheel-to", type=int)
    parser.add_argument("--antichrome", action="store_true")
    parser.add_argument("--tint", action="store_true")
    parser.add_argument("--comment")
    return parser.parse_args()


def load(path: Path) -> ImageData:
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type is None or not mime_type.startswith("image/"):
        raise SystemExit(f"Не похоже на изображение: {path}")
    return ImageData(data=path.read_bytes(), mime_type=mime_type)


async def main() -> None:
    args = parse_args()

    wheels = None
    if args.wheel:
        if args.wheel_from is None or args.wheel_to is None:
            raise SystemExit("Для --wheel нужны --wheel-from и --wheel-to")
        wheels = WheelParams(current_size=args.wheel_from, new_size=args.wheel_to)

    params = GenerationParams(
        antichrome=args.antichrome,
        tint=args.tint,
        film_finish=FilmFinish(args.finish) if args.finish else None,
        film_color=args.color,
        wheels=wheels,
        comment=args.comment,
    )

    files: dict[ImageRole, ImageData] = {ImageRole.CAR: load(args.car)}
    if args.film:
        files[ImageRole.FILM] = load(args.film)
    if args.wheel:
        files[ImageRole.WHEEL] = load(args.wheel)

    validate_generation_input(params, files.keys())

    request = build_model_request(params, files)

    print("=== PROMPT ===")
    print(request.prompt)
    print("==============")

    started = time.perf_counter()
    result = await get_image_generator().generate(request.prompt, request.images)
    print(f"Готово за {time.perf_counter() - started:.1f} с")

    generation_id = uuid4()
    key = build_image_key(generation_id, ImageRole.RESULT, result.mime_type)
    await get_storage().save(key, result.data, result.mime_type)
    print(f"Сохранено в хранилище: {key}")


if __name__ == "__main__":
    asyncio.run(main())
