"""SBI 导入台账、带日期的净值和待发通知。
SBI import ledger, dated NAVs and notification outbox.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261113_0009"
down_revision = "20261104_0008"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "sbi_records",
        sa.Column("portfolio_id", sa.String(64), sa.ForeignKey("portfolios.id"), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("sbi_records")
