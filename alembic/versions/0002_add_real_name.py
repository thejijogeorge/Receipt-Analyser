"""add real_name to receipt_items

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("receipt_items", sa.Column("real_name", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("receipt_items", "real_name")
