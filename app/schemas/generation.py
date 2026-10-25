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
    used_bonus: bool
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result_url: str | None


class GenerationList(BaseModel):
    items: list[GenerationRead]
    total: int
    limit: int
    offset: int


class GenerationQuota(BaseModel):
    plan: str
    daily_limit: int
    daily_used: int
    daily_remaining: int
    bonus_remaining: int
    remaining: int
    window_hours: int
    resets_at: datetime | None
