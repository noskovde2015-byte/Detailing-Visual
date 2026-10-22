import enum

from pydantic import BaseModel, Field

WHEEL_SIZE_MIN = 13
WHEEL_SIZE_MAX = 24


class FilmFinish(enum.StrEnum):
    GLOSSY = "glossy"
    MATTE = "matte"
    SATIN = "satin"
    METALLIC = "metallic"


class WheelParams(BaseModel):
    current_size: int = Field(ge=WHEEL_SIZE_MIN, le=WHEEL_SIZE_MAX)
    new_size: int = Field(ge=WHEEL_SIZE_MIN, le=WHEEL_SIZE_MAX)
    color: str | None = Field(default=None, max_length=50)


class GenerationParams(BaseModel):
    antichrome: bool = False
    tint: bool = False
    film_finish: FilmFinish | None = None
    wheels: WheelParams | None = None
    comment: str | None = Field(default=None, max_length=500)
