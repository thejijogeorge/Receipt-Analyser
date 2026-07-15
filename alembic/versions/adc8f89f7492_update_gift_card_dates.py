"""update_gift_card_dates

Revision ID: adc8f89f7492
Revises: 0006
Create Date: 2026-07-16 06:19:52.955806

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'adc8f89f7492'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    results = bind.execute(sa.text("SELECT filename, receipt_date FROM receipts WHERE receipt_date IS NOT NULL")).fetchall()
    for filename, receipt_date in results:
        bind.execute(
            sa.text("UPDATE gift_cards SET updated_at = :r_date WHERE last_receipt_filename = :filename"),
            {"r_date": receipt_date, "filename": filename}
        )


def downgrade():
    pass
