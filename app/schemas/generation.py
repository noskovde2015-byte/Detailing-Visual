import enum
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.services.colors import HEX_COLOR_PATTERN

WHEEL_SIZE_MIN = 13
WHEEL_SIZE_MAX = 24

HexColor = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=HEX_COLOR_PATTERN),
    AfterValidator(str.upper),
]
"""Цвет в формате #RRGGBB. Регистр нормализуется к верхнему: #1f0101 → #1F0101."""


class FilmFinish(enum.StrEnum):
    GLOSSY = "glossy"
    MATTE = "matte"
    SATIN = "satin"
    METALLIC = "metallic"


class WheelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_size: int = Field(ge=WHEEL_SIZE_MIN, le=WHEEL_SIZE_MAX)
    new_size: int = Field(ge=WHEEL_SIZE_MIN, le=WHEEL_SIZE_MAX)


class GenerationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    antichrome: bool = False
    tint: bool = False
    film_finish: FilmFinish | None = None
    film_color: HexColor | None = Field(
        default=None,
        description="Цвет плёнки из палитры, #RRGGBB. Взаимоисключающий с фото плёнки",
        examples=["#1F0101"],
    )
    wheels: WheelParams | None = None
    comment: str | None = Field(default=None, max_length=500)


class GenerationRead(BaseModel):
    id: uuid.UUID
    status: str
    params: GenerationParams
    input_roles: list[str]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    deleted_at: datetime | None = Field(
        default=None, description="Только в админке: пользователь удалил генерацию"
    )
    result_url: str | None
    preview_url: str | None = Field(
        description="Уменьшенная копия результата для галереи. Если null, "
        "а result_url есть — показывать result_url"
    )


class GenerationList(BaseModel):
    items: list[GenerationRead]
    total: int
    limit: int
    offset: int


class InsufficientBalanceDetail(BaseModel):
    message: str
    balance: int


class GenerationAvailability(BaseModel):
    available: bool
    message: str | None = Field(
        default=None, description="Почему недоступна. Показывать пользователю"
    )
