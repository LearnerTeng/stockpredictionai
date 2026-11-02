"""Transactional paper execution events and cash ledger."""
from alembic import op
import sqlalchemy as sa

revision = "20261004_0005"
down_revision = "20261004_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("execution_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("order_id", sa.String(64), sa.ForeignKey("paper_orders.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False))
    op.create_index("ix_execution_events_order_id", "execution_events", ["order_id"])
    op.create_table("fills",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("order_id", sa.String(64), sa.ForeignKey("paper_orders.id"), nullable=False, unique=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("cash_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("portfolio_id", sa.String(64), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("fill_id", sa.String(64), sa.ForeignKey("fills.id"), unique=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_cash_ledger_portfolio_id", "cash_ledger", ["portfolio_id"])


def downgrade():
    op.drop_table("cash_ledger")
    op.drop_table("fills")
    op.drop_table("execution_events")
