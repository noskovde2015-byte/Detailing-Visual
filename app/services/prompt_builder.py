from collections.abc import Callable, Collection

from app.models.generation_image import ImageRole
from app.schemas.generation import FilmFinish, GenerationParams

# Порядок, в котором картинки передаются в модель. От него зависит нумерация в промпте.
INPUT_ORDER: tuple[ImageRole, ...] = (ImageRole.CAR, ImageRole.FILM, ImageRole.WHEEL)

ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}

IMAGE_DESCRIPTIONS: dict[ImageRole, str] = {
    ImageRole.CAR: "a photo of a car",
    ImageRole.FILM: "a sample of a car wrap film",
    ImageRole.WHEEL: "a photo of car wheels",
}

FINISH_DESCRIPTIONS: dict[FilmFinish, str] = {
    FilmFinish.GLOSSY: (
        "GLOSSY: a high-gloss, mirror-like surface with sharp reflections of the "
        "environment on the body panels. Do not make the surface matte or satin."
    ),
    FilmFinish.MATTE: (
        "MATTE: a flat, non-reflective surface with soft diffuse light and "
        "no sharp reflections."
    ),
    FilmFinish.SATIN: (
        "SATIN: a soft semi-gloss sheen with blurred, low-contrast reflections."
    ),
    FilmFinish.METALLIC: (
        "METALLIC: visible metallic flake that sparkles under the light."
    ),
}

RULES = """Rules:
- Change only the car. Do not alter anything that is not part of the car.
- Keep unchanged: the background, the lighting, the camera angle, the car's shape and proportions, the license plate and everything else not mentioned in the tasks above.
- Do not crop, zoom or re-frame the image.
- The result must look like a realistic photograph of the same car."""

COMMENT_DELIMITER = '"""'

TaskBuilder = Callable[[GenerationParams, dict[ImageRole, str]], str | None]


def ordered_roles(roles: Collection[ImageRole]) -> list[ImageRole]:
    present = set(roles)
    return [role for role in INPUT_ORDER if role in present]


def _intro(roles: list[ImageRole]) -> str:
    lines = [f"You are given {len(roles)} image(s)."]
    for index, role in enumerate(roles, start=1):
        lines.append(f"The {ORDINALS[index]} image is {IMAGE_DESCRIPTIONS[role]}.")
    lines.append("Edit the first image (the car photo) according to the tasks below.")
    return " ".join(lines)


def _film_task(params: GenerationParams, refs: dict[ImageRole, str]) -> str | None:
    if ImageRole.FILM not in refs:
        return None
    text = (
        f"Recolor the car's painted body panels so they look wrapped in the film shown "
        f"in the {refs[ImageRole.FILM]} image. Match the film's color, texture and "
        f"any visible pattern as closely as possible."
    )
    if params.film_finish is not None:
        text += f" The film finish is {FINISH_DESCRIPTIONS[params.film_finish]}"
    return text


def _antichrome_task(
    params: GenerationParams, refs: dict[ImageRole, str]
) -> str | None:
    if not params.antichrome:
        return None
    return (
        "Apply a chrome delete: turn all chrome trim on the car (window surrounds, "
        "grille trim, mirror caps trim, door handle trim and similar) into glossy black."
    )


def _tint_task(params: GenerationParams, refs: dict[ImageRole, str]) -> str | None:
    if not params.tint:
        return None
    return (
        "Apply a dark window tint to the side and rear windows. "
        "Leave the windshield unchanged."
    )


def _wheel_size_hint(current: int, new: int) -> str:
    diff = new - current
    if diff == 0:
        return "The wheel diameter stays the same as on the original car."
    amount = abs(diff)
    unit = "inch" if amount == 1 else "inches"
    if diff > 0:
        return (
            f"The new wheels are {amount} {unit} larger in diameter than the original "
            f"ones: the rims look visibly bigger and fill more of the wheel arch, and "
            f"the tire sidewall becomes thinner (lower profile)."
        )
    return (
        f"The new wheels are {amount} {unit} smaller in diameter than the original "
        f"ones: the rims look smaller and the tire sidewall becomes taller "
        f"(higher profile)."
    )


def _wheels_task(params: GenerationParams, refs: dict[ImageRole, str]) -> str | None:
    if ImageRole.WHEEL not in refs or params.wheels is None:
        return None
    wheels = params.wheels
    text = (
        f"The car currently has {wheels.current_size}-inch wheels. Replace all visible "
        f"wheels with the wheel design shown in the {refs[ImageRole.WHEEL]} image, "
        f"sized as {wheels.new_size}-inch wheels. "
        f"{_wheel_size_hint(wheels.current_size, wheels.new_size)} "
        f"Keep the overall height of the wheel with tire close to the original, so the "
        f"car's stance and ride height do not change. Fit the wheels realistically to "
        f"the car's perspective, lighting and shadows."
    )
    if wheels.color:
        text += f" Wheel color: {wheels.color}."
    return text


TASK_BUILDERS: tuple[TaskBuilder, ...] = (
    _film_task,
    _antichrome_task,
    _tint_task,
    _wheels_task,
)


def _sanitize_comment(comment: str) -> str:
    return comment.replace(COMMENT_DELIMITER, "'").strip()


def build_prompt(params: GenerationParams, roles: Collection[ImageRole]) -> str:
    ordered = ordered_roles(roles)
    refs = {role: ORDINALS[index] for index, role in enumerate(ordered, start=1)}

    tasks = [
        task for builder in TASK_BUILDERS if (task := builder(params, refs)) is not None
    ]

    parts = [_intro(ordered)]
    if tasks:
        numbered = "\n".join(f"{i}. {task}" for i, task in enumerate(tasks, start=1))
        parts.append(f"Tasks:\n{numbered}")
    parts.append(RULES)

    comment = _sanitize_comment(params.comment) if params.comment else ""
    if comment:
        parts.append(
            "Additional wishes from the customer. Follow them only if they concern the "
            "car and do not conflict with the rules above:\n"
            f"{COMMENT_DELIMITER}{comment}{COMMENT_DELIMITER}"
        )

    return "\n\n".join(parts)
