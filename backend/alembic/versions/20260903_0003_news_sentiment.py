"""add normalized news sentiment, coverage, features and alerts"""

from alembic import op
import sqlalchemy as sa


revision = "20260903_0003"
down_revision = "20260815_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("news_items") as batch:
        batch.alter_column("symbol", existing_type=sa.String(length=32), nullable=True)
        batch.add_column(sa.Column("provider", sa.String(length=64), server_default="legacy", nullable=False))
        batch.add_column(sa.Column("provider_item_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("canonical_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_domain", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("source_tier", sa.String(length=32), server_default="secondary", nullable=False))
        batch.add_column(sa.Column("language", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("first_fetched_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_news_items_provider", ["provider"])
        batch.create_index("ix_news_items_source_domain", ["source_domain"])
        batch.create_index("ix_news_items_source_tier", ["source_tier"])
        batch.create_index("ix_news_items_language", ["language"])
        batch.create_unique_constraint("uq_news_items_content_hash", ["content_hash"])

    op.execute("UPDATE news_items SET first_fetched_at = fetched_at WHERE first_fetched_at IS NULL")

    op.create_table(
        "news_item_instruments",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("news_item_id", sa.String(length=64), sa.ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(length=32), sa.ForeignKey("instruments.symbol"), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("provider_sentiment_score", sa.Float(), nullable=True),
        sa.Column("sentiment_label", sa.String(length=16), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("positive_probability", sa.Float(), nullable=True),
        sa.Column("neutral_probability", sa.Float(), nullable=True),
        sa.Column("negative_probability", sa.Float(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=True),
        sa.Column("impact_direction", sa.String(length=16), nullable=True),
        sa.Column("analysis_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("classifier", sa.String(length=128), nullable=True),
        sa.Column("classifier_version", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("news_item_id", "symbol", name="uq_news_item_instrument"),
    )
    for name, columns in (
        ("ix_news_item_instruments_news_item_id", ["news_item_id"]),
        ("ix_news_item_instruments_symbol", ["symbol"]),
        ("ix_news_item_instruments_sentiment_label", ["sentiment_label"]),
        ("ix_news_item_instruments_sentiment_score", ["sentiment_score"]),
        ("ix_news_item_instruments_event_type", ["event_type"]),
        ("ix_news_item_instruments_analysis_status", ["analysis_status"]),
    ):
        op.create_index(name, "news_item_instruments", columns)

    # Preserve legacy article-symbol relationships as analyzed rows.
    op.execute(
        """
        INSERT INTO news_item_instruments
            (news_item_id, symbol, relevance_score, provider_sentiment_score,
             sentiment_label, sentiment_score, analysis_status, classifier,
             created_at, updated_at)
        SELECT id, symbol, 1.0, sentiment_score,
               CASE WHEN sentiment_score > 0.05 THEN 'positive'
                    WHEN sentiment_score < -0.05 THEN 'negative'
                    WHEN sentiment_score IS NULL THEN NULL ELSE 'neutral' END,
               sentiment_score,
               CASE WHEN sentiment_score IS NULL THEN 'pending' ELSE 'analyzed' END,
               'legacy', fetched_at, fetched_at
        FROM news_items WHERE symbol IS NOT NULL
        """
    )

    op.create_table(
        "sentiment_daily_features",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=32), sa.ForeignKey("instruments.symbol"), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("score_1d", sa.Float()), sa.Column("score_3d", sa.Float()), sa.Column("score_7d", sa.Float()),
        sa.Column("negative_share", sa.Float()), sa.Column("dispersion", sa.Float()),
        sa.Column("news_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_change_7d", sa.Float()),
        sa.Column("negative_shock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.String(length=32), nullable=False, server_default="sentiment-v1"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "trade_date", "version", name="uq_sentiment_feature"),
    )
    op.create_index("ix_sentiment_daily_features_symbol", "sentiment_daily_features", ["symbol"])
    op.create_index("ix_sentiment_daily_features_trade_date", "sentiment_daily_features", ["trade_date"])
    op.create_index("ix_sentiment_daily_features_negative_shock", "sentiment_daily_features", ["negative_shock"])

    op.create_table(
        "news_coverage",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), sa.ForeignKey("instruments.symbol"), nullable=False),
        sa.Column("coverage_start", sa.DateTime(timezone=True)), sa.Column("coverage_end", sa.DateTime(timezone=True)),
        sa.Column("article_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("gaps", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("last_error", sa.Text()), sa.Column("last_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "symbol", name="uq_news_coverage_provider_symbol"),
    )
    op.create_index("ix_news_coverage_provider", "news_coverage", ["provider"])
    op.create_index("ix_news_coverage_symbol", "news_coverage", ["symbol"])
    op.create_index("ix_news_coverage_status", "news_coverage", ["status"])

    op.create_table(
        "sentiment_alerts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("symbol", sa.String(length=32), sa.ForeignKey("instruments.symbol"), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("alert_type", sa.String(length=32), nullable=False), sa.Column("score", sa.Float(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("recipient", sa.Text()), sa.Column("payload", sa.JSON()), sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sentiment_alerts_symbol", "sentiment_alerts", ["symbol"])
    op.create_index("ix_sentiment_alerts_alert_type", "sentiment_alerts", ["alert_type"])
    op.create_index("ix_sentiment_alerts_status", "sentiment_alerts", ["status"])
    op.create_index("ix_sentiment_alerts_created_at", "sentiment_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_table("sentiment_alerts")
    op.drop_table("news_coverage")
    op.drop_table("sentiment_daily_features")
    op.drop_table("news_item_instruments")
    with op.batch_alter_table("news_items") as batch:
        batch.drop_constraint("uq_news_items_content_hash", type_="unique")
        for column in ("first_fetched_at", "content_hash", "language", "source_tier", "source_domain", "summary", "canonical_url", "provider_item_id", "provider"):
            batch.drop_column(column)
        batch.alter_column("symbol", existing_type=sa.String(length=32), nullable=False)
