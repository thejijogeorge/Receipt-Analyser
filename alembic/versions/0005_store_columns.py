"""add store_key/store_name, widen gift_cards.last_four

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("receipts", sa.Column("store_key", sa.String(100), nullable=True))
    op.add_column("receipts", sa.Column("store_name", sa.String(255), nullable=True))

    # all receipts processed so far were Coles -- backfill them
    op.execute("UPDATE receipts SET store_key = 'coles', store_name = 'Coles' WHERE store_key IS NULL")

    op.alter_column(
        "gift_cards", "last_four",
        existing_type=sa.String(10),
        type_=sa.String(30),
        existing_nullable=False,
    )
    op.add_column("gift_cards", sa.Column("store_key", sa.String(100), nullable=True))
    op.execute("UPDATE gift_cards SET store_key = 'coles' WHERE store_key IS NULL")


def downgrade():
    op.drop_column("gift_cards", "store_key")
    op.alter_column(
        "gift_cards", "last_four",
        existing_type=sa.String(30),
        type_=sa.String(10),
        existing_nullable=False,
    )
    op.drop_column("receipts", "store_name")
    op.drop_column("receipts", "store_key")
