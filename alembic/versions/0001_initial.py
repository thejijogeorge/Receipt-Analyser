"""initial tables

Revision ID: 0001
Revises:
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "receipts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("receipt_date", sa.Date, nullable=True),
        sa.Column("store", sa.String(255), nullable=True),
        sa.Column("processed_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("filename", name="uq_receipt_filename"),
    )
    op.create_table(
        "receipt_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("receipt_id", sa.Integer, sa.ForeignKey("receipts.id"), nullable=False),
        sa.Column("item_name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=True),
        sa.Column("unit_price", sa.Float, nullable=True),
        sa.Column("line_total", sa.Float, nullable=True),
        sa.Column("discount", sa.Float, nullable=True),
    )


def downgrade():
    op.drop_table("receipt_items")
    op.drop_table("receipts")
