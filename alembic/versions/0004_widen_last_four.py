"""widen gift_cards.last_four column

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "gift_cards", "last_four",
        existing_type=sa.String(4),
        type_=sa.String(10),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "gift_cards", "last_four",
        existing_type=sa.String(10),
        type_=sa.String(4),
        existing_nullable=False,
    )
