"""Versioned research evidence and PostgreSQL vector retrieval."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "20261016_0006"
down_revision = "20261004_0005"
branch_labels = depends_on = None


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("research_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("article_id", sa.String(64), sa.ForeignKey("news_items.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()), sa.Column("source", sa.String(128), nullable=False),
        sa.Column("language", sa.String(16)), sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("article_id", "revision", name="uq_research_revision"))
    op.create_index("ix_research_documents_article_id", "research_documents", ["article_id"])
    op.create_index("ix_research_documents_available_at", "research_documents", ["available_at"])
    op.create_table("document_embeddings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(64), sa.ForeignKey("research_documents.id"), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("vector", Vector(1536) if postgres else sa.JSON()),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("error", sa.Text()),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("document_id", "model", name="uq_document_embedding"))
    op.create_index("ix_document_embeddings_document_id", "document_embeddings", ["document_id"])
    op.create_index("ix_document_embeddings_status", "document_embeddings", ["status"])
    # Exact search is the correctness baseline; add ANN only after measured need.
    op.create_table("sentiment_observations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("relation_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.ForeignKey("news_item_instruments.id"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("article_json", sa.JSON(), nullable=False), sa.Column("analysis_json", sa.JSON(), nullable=False))
    for field in ("relation_id", "symbol", "available_at"):
        op.create_index("ix_sentiment_observations_" + field, "sentiment_observations", [field])
    op.create_table("research_answers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False), sa.Column("response_json", sa.JSON(), nullable=False))
    op.create_table("paper_cycles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False), sa.Column("report", sa.JSON(), nullable=False))


def downgrade():
    for table in ("paper_cycles", "research_answers", "sentiment_observations", "document_embeddings", "research_documents"):
        op.drop_table(table)
    # Extension may be shared by other applications; never drop it here.
