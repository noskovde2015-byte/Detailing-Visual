"""drop wheels.color from generation params

Revision ID: e5a7c2d9b1f4
Revises: 9b3d5e1f8a42
Create Date: 2026-10-25 14:30:00.000000

Цвет дисков больше не задаётся текстом: он берётся с фото дисков.
Схема GenerationParams запрещает лишние поля, поэтому старые генерации
с wheels.color перестали бы читаться. Миграция убирает этот ключ из JSONB.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a7c2d9b1f4"
down_revision: str | Sequence[str] | None = "9b3d5e1f8a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE generations
        SET params = params #- '{wheels,color}'
        WHERE jsonb_typeof(params -> 'wheels') = 'object'
          AND params -> 'wheels' ? 'color'
        """
    )


def downgrade() -> None:
    # Удалённые значения не восстановить, а старому коду поле не обязательно.
    pass
