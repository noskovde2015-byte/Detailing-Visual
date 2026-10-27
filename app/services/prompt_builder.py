import enum
from collections.abc import Callable, Collection, Sequence

from app.models.generation_image import ImageRole
from app.schemas.generation import FilmFinish, GenerationParams
from app.services.colors import describe_color, parse_hex


class InputSlot(enum.StrEnum):
    """Картинка, которую получает модель.

    Отличается от ImageRole: образец цвета не загружается пользователем
    и не хранится, а рисуется из параметров перед отправкой в модель.
    """

    CAR = "car"
    FILM = "film"
    COLOR_SWATCH = "color_swatch"
    WHEEL = "wheel"


# Порядок, в котором картинки передаются в модель. От него зависит нумерация в промпте.
# FILM и COLOR_SWATCH взаимоисключающие, поэтому образец занимает место плёнки.
INPUT_ORDER: tuple[InputSlot, ...] = (
    InputSlot.CAR,
    InputSlot.FILM,
    InputSlot.COLOR_SWATCH,
    InputSlot.WHEEL,
)

UPLOADED_SLOTS: dict[ImageRole, InputSlot] = {
    ImageRole.CAR: InputSlot.CAR,
    ImageRole.FILM: InputSlot.FILM,
    ImageRole.WHEEL: InputSlot.WHEEL,
}

ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}

IMAGE_DESCRIPTIONS: dict[InputSlot, str] = {
    InputSlot.CAR: "a photo of a car",
    InputSlot.FILM: "a sample of a car wrap film",
    InputSlot.COLOR_SWATCH: "a flat swatch of the target wrap color",
    InputSlot.WHEEL: "a photo of car wheels",
}

FINISH_DESCRIPTIONS: dict[FilmFinish, str] = {
    # «Mirror-like» давало эффект леденца: описываем глянец как заводскую краску
    # и отдельно запрещаем перебор с блеском.
    FilmFinish.GLOSSY: (
        "GLOSSY: like fresh factory paint with a clear coat: a smooth surface with "
        "natural reflections of the surroundings. Keep it realistic: not wet-looking, "
        "not candy-like and not chrome-like. Do not make the surface matte or satin."
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

# Цвет кузова — главное, за что платит клиент. Без этой оговорки громкие
# формулировки других задач (антихром, диски) «перетягивали» оттенок и блеск.
# Других задач по имени не называем: упоминание выключенной опции модель может
# принять за просьбу её выполнить.
BODY_COLOR_PRIORITY = (
    "The body color is the priority of this edit: no other change in this edit may "
    "alter the body color, its brightness or its finish."
)

# Если пользователь выбрал цвет, но не тип покрытия, рисуем как заводскую краску.
DEFAULT_COLOR_FINISH = FilmFinish.GLOSSY

RULES = """Rules:
- Change only the car. Do not alter anything that is not part of the car.
- Keep unchanged: the background, the lighting, the camera angle, the car's shape and proportions, the license plate and everything else not mentioned in the tasks above.
- Keep the body color exactly as set in the tasks above, or as in the original photo if no body color is set: do not lighten, darken, desaturate or shift its hue. The only exception is a customer wish below that explicitly asks to change the body color.
- Do not crop, zoom or re-frame the image.
- The result must look like a realistic photograph of the same car."""

COMMENT_DELIMITER = '"""'

TaskBuilder = Callable[[GenerationParams, dict[InputSlot, str]], str | None]


def input_slots(
    params: GenerationParams, roles: Collection[ImageRole]
) -> list[InputSlot]:
    """Картинки для модели в том порядке, в котором их нужно передать."""
    present = {UPLOADED_SLOTS[role] for role in roles if role in UPLOADED_SLOTS}
    if params.film_color is not None:
        present.add(InputSlot.COLOR_SWATCH)
    return [slot for slot in INPUT_ORDER if slot in present]


def _intro(slots: Sequence[InputSlot]) -> str:
    lines = [f"You are given {len(slots)} image(s)."]
    for index, slot in enumerate(slots, start=1):
        lines.append(f"The {ORDINALS[index]} image is {IMAGE_DESCRIPTIONS[slot]}.")
    lines.append("Edit the first image (the car photo) according to the tasks below.")
    return " ".join(lines)


def _film_task(params: GenerationParams, refs: dict[InputSlot, str]) -> str | None:
    if InputSlot.FILM not in refs:
        return None
    text = (
        f"Recolor the car's painted body panels so they look wrapped in the film shown "
        f"in the {refs[InputSlot.FILM]} image. Match the film's color, texture and "
        f"any visible pattern as closely as possible. {BODY_COLOR_PRIORITY}"
    )
    if params.film_finish is not None:
        text += f" The film finish is {FINISH_DESCRIPTIONS[params.film_finish]}"
    return text


def _color_task(params: GenerationParams, refs: dict[InputSlot, str]) -> str | None:
    if InputSlot.COLOR_SWATCH not in refs or params.film_color is None:
        return None
    rgb = parse_hex(params.film_color)
    finish = params.film_finish or DEFAULT_COLOR_FINISH
    return (
        f"Recolor the car's painted body panels so they look wrapped in a solid "
        f"{describe_color(rgb)} film (HEX {rgb.hex}, RGB {rgb.red}, {rgb.green}, "
        f"{rgb.blue}). The exact color is shown in the {refs[InputSlot.COLOR_SWATCH]} "
        f"image. The swatch shows only the base color under neutral light: render it "
        f"with the scene's real lighting, shading and reflections, so darker and "
        f"brighter areas of the body vary naturally around this color. Do not add any "
        f"pattern or texture. The film finish is {FINISH_DESCRIPTIONS[finish]} "
        f"{BODY_COLOR_PRIORITY}"
    )


def _antichrome_task(
    params: GenerationParams, refs: dict[InputSlot, str]
) -> str | None:
    if not params.antichrome:
        return None
    # Модель понимает «и тому подобное» узко (так пропала решётка), поэтому
    # перечисляем детали явно, а исключения — отдельно, чтобы не зачернить лишнее.
    return (
        "Apply a full chrome delete: every chrome or polished bright-metal part of the "
        "car becomes gloss black, like piano-black trim, with no chrome left anywhere "
        "on the body. This "
        "includes, wherever present: window surrounds and window line trim, pillar "
        "trim, the front grille (its frame, slats, mesh and any chrome inserts), "
        "roof rails, bumper trim and inserts, fog light surrounds, side moldings, "
        "door handle trim, mirror cap trim, tailgate and trunk lid trim, and chrome "
        "badges and lettering. Keep the exact shape, size and position of every part "
        "(badges stay legible); only the finish changes. The black applies only to "
        "these trim parts and must not affect the body color. Do not change the "
        "wheels, the headlights, the taillights, the exhaust tips or the license plate."
    )


def _tint_task(params: GenerationParams, refs: dict[InputSlot, str]) -> str | None:
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


def _wheels_task(params: GenerationParams, refs: dict[InputSlot, str]) -> str | None:
    if InputSlot.WHEEL not in refs or params.wheels is None:
        return None
    wheels = params.wheels
    ref = refs[InputSlot.WHEEL]
    # Модель склонна «додумывать» диск: упрощать спицы, менять их число и форму.
    # Поэтому отдельно и подробно запрещаем менять рисунок.
    return (
        f"The car currently has {wheels.current_size}-inch wheels. Replace all visible "
        f"wheels with the wheels shown in the {ref} image, sized as "
        f"{wheels.new_size}-inch wheels. "
        f"{_wheel_size_hint(wheels.current_size, wheels.new_size)} "
        f"Copy the wheel design from the {ref} image exactly: the same number of "
        f"spokes, the same spoke shape, thickness and pattern, the same center cap and "
        f"lug nut layout, the same color and finish. Do not simplify, redesign, mix "
        f"with the original wheels or invent details. Only the size and the viewing "
        f"angle may differ from the {ref} image. Keep the tires as black rubber "
        f"tires. Keep the overall height of the wheel with tire close to the original, "
        f"so the car's stance and ride height do not change. Fit the wheels "
        f"realistically to the car's perspective, lighting and shadows."
    )


TASK_BUILDERS: tuple[TaskBuilder, ...] = (
    _film_task,
    _color_task,
    _antichrome_task,
    _tint_task,
    _wheels_task,
)


def _sanitize_comment(comment: str) -> str:
    return comment.replace(COMMENT_DELIMITER, "'").strip()


def build_prompt(params: GenerationParams, roles: Collection[ImageRole]) -> str:
    slots = input_slots(params, roles)
    refs = {slot: ORDINALS[index] for index, slot in enumerate(slots, start=1)}

    tasks = [
        task for builder in TASK_BUILDERS if (task := builder(params, refs)) is not None
    ]

    parts = [_intro(slots)]
    if tasks:
        numbered = "\n".join(f"{i}. {task}" for i, task in enumerate(tasks, start=1))
        parts.append(f"Tasks:\n{numbered}")
    parts.append(RULES)

    comment = _sanitize_comment(params.comment) if params.comment else ""
    if comment:
        parts.append(
            # Без этих оговорок пожелание вроде «накладки чёрным глянцем» модель
            # понимала как повод перерисовать всю окраску — кузов светлел.
            "Additional wishes from the customer. Follow them only if they concern the "
            "car and do not conflict with the rules above. Apply each wish only to the "
            "parts it names. A wish about trim, accents or other details (for example, "
            "making some parts black) changes only those parts: the body color, its "
            "brightness, saturation and finish stay exactly as described above. Change "
            "the body color only if a wish explicitly asks to change the body color "
            "itself:\n"
            f"{COMMENT_DELIMITER}{comment}{COMMENT_DELIMITER}"
        )

    return "\n\n".join(parts)
