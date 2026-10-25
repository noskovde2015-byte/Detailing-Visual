import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CreditGrantKind(enum.StrEnum):
    WELCOME = "welcome"
    """Подарок при регистрации. Не больше одного на пользователя."""
    ADMIN = "admin"
    """Начислил или списал администратор."""
    PURCHASE = "purchase"
    """Покупка пакета (появится вместе с оплатой)."""


class CreditGrant(Base):
    """Начисление (или списание, если amount < 0) генераций на баланс.

    Баланс не хранится отдельным счётчиком, а считается из журнала начислений
    и списанных генераций (Generation.charged): так видна вся история и нечему
    рассинхронизироваться.
    """

    __tablename__ = "credit_grants"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="amount_not_zero"),
        # Приветственное начисление одно на пользователя даже при гонке запросов.
        Index(
            "uq_credit_grants_welcome_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'welcome'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(
        String(20),
        default=CreditGrantKind.ADMIN.value,
        server_default=CreditGrantKind.ADMIN.value,
    )
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(255))
    granted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
