"""add gift card deductions table

Revision ID: 0007
Revises: adc8f89f7492
Create Date: 2026-07-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = 'adc8f89f7492'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gift_card_deductions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gift_card_id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("amount_redeemed", sa.Float(), nullable=False),
        sa.Column("balance", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["gift_card_id"], ["gift_cards.id"], name="fk_deductions_gift_card"),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], name="fk_deductions_receipt"),
        sa.PrimaryKeyConstraint("id")
    )


def downgrade():
    op.drop_table("gift_card_deductions")
