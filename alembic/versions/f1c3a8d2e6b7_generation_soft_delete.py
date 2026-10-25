"""generation soft delete and history index

Revision ID: f1c3a8d2e6b7
Revises: e5a7c2d9b1f4
Create Date: 2026-10-25 16:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1c3a8d2e6b7"
down_revision: Union[str, Sequence[str], None] = "e5a7c2d9b1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_generations_user_id_created_at",
        "generations",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_generations_user_id_created_at", table_name="generations")
    op.drop_column("generations", "deleted_at")
