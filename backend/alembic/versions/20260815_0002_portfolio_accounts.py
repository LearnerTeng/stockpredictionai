"""support multi-currency portfolio accounts and fund quote scales"""

from alembic import op
import sqlalchemy as sa


revision = "20260815_0002"
down_revision = "20260815_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("portfolios", sa.Column("currency", sa.String(length=8), server_default="USD", nullable=False))
    op.add_column("portfolios", sa.Column("account_type", sa.String(length=32), server_default="paper", nullable=False))
    op.add_column("positions", sa.Column("currency", sa.String(length=8), server_default="USD", nullable=False))
    op.add_column("positions", sa.Column("account_bucket", sa.String(length=32), nullable=True))
    op.add_column("positions", sa.Column("price_scale", sa.Integer(), server_default="1", nullable=False))
    op.add_column("positions", sa.Column("reported_market_value", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("reported_cost_basis", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("source", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "source")
    op.drop_column("positions", "reported_cost_basis")
    op.drop_column("positions", "reported_market_value")
    op.drop_column("positions", "price_scale")
    op.drop_column("positions", "account_bucket")
    op.drop_column("positions", "currency")
    op.drop_column("portfolios", "account_type")
    op.drop_column("portfolios", "currency")
