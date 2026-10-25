import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import UserPlan
from app.schemas.generation import GenerationQuota

CREDIT_GRANT_MAX = 1000


class AdminUserRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    plan: str
    is_admin: bool
    is_blocked: bool
    created_at: datetime
    generations_total: int
    bonus_remaining: int


class AdminUserList(BaseModel):
    items: list[AdminUserRead]
    total: int
    limit: int
    offset: int


class AdminUserDetail(BaseModel):
    user: AdminUserRead
    quota: GenerationQuota


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: UserPlan | None = None
    is_blocked: bool | None = None


class CreditGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(
        ge=-CREDIT_GRANT_MAX,
        le=CREDIT_GRANT_MAX,
        description="Сколько генераций начислить; отрицательное число — списать",
    )
    reason: str | None = Field(default=None, max_length=255)

    @field_validator("amount")
    @classmethod
    def _not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Количество не может быть нулём")
        return value


class CreditGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: int
    reason: str | None
    granted_by_id: uuid.UUID | None
    created_at: datetime


class CreditGrantList(BaseModel):
    items: list[CreditGrantRead]
    total: int
    limit: int
    offset: int


class AdminStats(BaseModel):
    users_total: int
    users_new_24h: int
    users_blocked: int
    generations_total: int
    generations_24h: int
    generations_24h_by_status: dict[str, int]
    bonus_generations_24h: int
