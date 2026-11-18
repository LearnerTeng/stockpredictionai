"""独立的新闻模型实验及其缓存。
Independent news-model experiments and their cache.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261103_0007'
down_revision = '20261016_0006'
branch_labels = depends_on = None


def upgrade():
    op.create_table('news_model_runs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('document_id', sa.String(64), sa.ForeignKey('research_documents.id'), nullable=False),
        sa.Column('line', sa.String(32), nullable=False), sa.Column('model', sa.String(128), nullable=False),
        sa.Column('status', sa.String(32), nullable=False), sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('retry_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)), sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON()), sa.Column('error', sa.String(128)))
    for column in ('document_id', 'line', 'status'):
        op.create_index('ix_news_model_runs_' + column, 'news_model_runs', [column])


def downgrade():
    op.drop_table('news_model_runs')
