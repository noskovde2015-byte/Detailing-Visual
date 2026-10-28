import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.credit_grant import CreditGrantKind
from app.services.image_generator import OutageReason

CREDIT_GRANT_MAX = 1000


class AdminUserRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    is_admin: bool
    is_blocked: bool
    created_at: datetime
    generations_total: int
    balance: int


class AdminUserList(BaseModel):
    items: list[AdminUserRead]
    total: int
    limit: int
    offset: int


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_blocked: bool


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


class GrantAuthor(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None


class CreditGrantRead(BaseModel):
    id: uuid.UUID
    kind: CreditGrantKind
    amount: int
    reason: str | None
    granted_by: GrantAuthor | None = Field(
        description="Кто начислил. null — система (подарок, покупка) "
        "или удалённый администратор"
    )
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


class GenerationControlRead(BaseModel):
    """Идут ли генерации. Если нет — почему и что делать."""

    supported: bool = Field(
        description="false — очередь в режиме разработки (background), паузы нет"
    )
    paused: bool
    reason: OutageReason | None = None
    title: str | None = None
    hint: str | None = Field(default=None, description="Что сделать администратору")
    detail: str | None = Field(default=None, description="Последняя ошибка Google")
    since: datetime | None = Field(default=None, description="Когда встали")
    last_error_at: datetime | None = None
    paused_by: str | None = None
    auto_resume: bool = Field(
        default=False, description="Возобновятся сами, когда вернётся связь"
    )
    pending_count: int = Field(description="Сколько генераций ждёт")
    oldest_pending_at: datetime | None = None
    pending_timeout_minutes: int = Field(
        description="Через сколько минут ожидания генерация вернётся на баланс"
    )


class GenerationPauseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=255)


class GenerationResumeRead(BaseModel):
    requeued: int = Field(description="Сколько ждущих генераций вернулось в очередь")
    status: GenerationControlRead
