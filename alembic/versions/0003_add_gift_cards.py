"""add gift_cards table

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gift_cards",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("last_four", sa.String(4), nullable=False),
        sa.Column("balance", sa.Float, nullable=True),
        sa.Column("last_receipt_filename", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("last_four", name="uq_gift_card_last_four"),
    )


def downgrade():
    op.drop_table("gift_cards")
