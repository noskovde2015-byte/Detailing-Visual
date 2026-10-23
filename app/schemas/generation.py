import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

WHEEL_SIZE_MIN = 13
WHEEL_SIZE_MAX = 24


class FilmFinish(enum.StrEnum):
    GLOSSY = "glossy"
    MATTE = "matte"
    SATIN = "satin"
    METALLIC = "metallic"


class WheelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_size: int = Field(ge=WHEEL_SIZE_MIN, le=WHEEL_SIZE_MAX)
    new_size: int = Field(ge=WHEEL_SIZE_MIN, le=WHEEL_SIZE_MAX)
    color: str | None = Field(default=None, max_length=50)


class GenerationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    antichrome: bool = False
    tint: bool = False
    film_finish: FilmFinish | None = None
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
    result_url: str | None


class GenerationList(BaseModel):
    items: list[GenerationRead]
    total: int
    limit: int
    offset: int


class GenerationQuota(BaseModel):
    plan: str
    limit: int
    used: int
    remaining: int
    window_hours: int
    resets_at: datetime | None
