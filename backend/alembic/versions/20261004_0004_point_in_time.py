"""Append-only point-in-time observations and security identities."""
from alembic import op
import sqlalchemy as sa

revision = "20261004_0004"
down_revision = "20260903_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("securities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("provisional", sa.Boolean(), nullable=False))
    op.create_table("security_aliases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("security_id", sa.String(64), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_security_aliases_security_id", "security_aliases", ["security_id"])
    op.create_index("ix_security_aliases_symbol", "security_aliases", ["symbol"])
    op.create_table("universe_memberships",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("universe", sa.String(64), nullable=False),
        sa.Column("security_id", sa.String(64), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_universe_memberships_universe", "universe_memberships", ["universe"])
    op.create_table("bar_revisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("security_id", sa.String(64), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_status", sa.String(32), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("security_id", "trade_date", "source", "revision", name="uq_bar_revision"))
    for field in ("security_id", "trade_date", "available_at"):
        op.create_index("ix_bar_revisions_" + field, "bar_revisions", [field])


def downgrade():
    for table in ("bar_revisions", "universe_memberships", "security_aliases", "securities"):
        op.drop_table(table)
