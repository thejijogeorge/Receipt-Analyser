"""add amount_redeemed, scope gift card uniqueness per store

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gift_cards", sa.Column("amount_redeemed", sa.Float, nullable=True))

    # drop the old global-uniqueness constraint on last_four alone --
    # different stores' cards can coincidentally share a masked suffix
    op.drop_constraint("uq_gift_card_last_four", "gift_cards", type_="unique")

    op.create_unique_constraint(
        "uq_giftcard_store_last_four", "gift_cards", ["store_key", "last_four"]
    )


def downgrade():
    op.drop_constraint("uq_giftcard_store_last_four", "gift_cards", type_="unique")
    op.create_unique_constraint("uq_gift_card_last_four", "gift_cards", ["last_four"])
    op.drop_column("gift_cards", "amount_redeemed")
