"""add psychologist formats

Revision ID: b7f1c2d3e4a5
Revises: 904fb16197da
Create Date: 2026-10-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7f1c2d3e4a5"
down_revision: str | None = "904fb16197da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "psychologist_profiles",
        sa.Column("formats", postgresql.ARRAY(sa.String(length=32)), nullable=True),
    )
    op.execute(
        "UPDATE psychologist_profiles "
        "SET formats = ARRAY['online']::varchar[] "
        "WHERE formats IS NULL"
    )
    op.alter_column("psychologist_profiles", "formats", nullable=False)


def downgrade() -> None:
    op.drop_column("psychologist_profiles", "formats")
