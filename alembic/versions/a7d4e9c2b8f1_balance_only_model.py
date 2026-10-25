"""balance-only model: welcome grant, charged generations, no plans

Revision ID: a7d4e9c2b8f1
Revises: f1c3a8d2e6b7
Create Date: 2026-10-25 18:10:00.000000

Дневной лимит и планы убраны: генерации есть только на балансе.
- generations.used_bonus переименована в charged. Смысл тот же: генерация
  списала единицу с баланса. Старые генерации по дневному лимиту остаются
  charged = false и не уменьшают баланс задним числом.
- users.plan удалена.
- credit_grants.kind: welcome / admin / purchase, приветственное начисление
  одно на пользователя (уникальный частичный индекс).
- Пользователи, созданные до этой миграции, получают приветственную генерацию.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d4e9c2b8f1"
down_revision: str | Sequence[str] | None = "f1c3a8d2e6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WELCOME_INDEX = "uq_credit_grants_welcome_per_user"


def upgrade() -> None:
    op.alter_column("generations", "used_bonus", new_column_name="charged")
    op.drop_column("users", "plan")

    op.add_column(
        "credit_grants",
        sa.Column(
            "kind",
            sa.String(length=20),
            nullable=False,
            server_default="admin",
        ),
    )
    op.create_index(
        WELCOME_INDEX,
        "credit_grants",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'welcome'"),
    )

    op.execute(
        """
        INSERT INTO credit_grants (id, user_id, kind, amount, reason, created_at)
        SELECT gen_random_uuid(), u.id, 'welcome', 1, 'Подарок при регистрации', now()
        FROM users AS u
        WHERE NOT EXISTS (
            SELECT 1 FROM credit_grants AS g
            WHERE g.user_id = u.id AND g.kind = 'welcome'
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM credit_grants WHERE kind = 'welcome'")
    op.drop_index(WELCOME_INDEX, table_name="credit_grants")
    op.drop_column("credit_grants", "kind")

    op.add_column(
        "users",
        sa.Column(
            "plan",
            sa.String(length=20),
            nullable=False,
            server_default="free",
        ),
    )
    op.alter_column("generations", "charged", new_column_name="used_bonus")
