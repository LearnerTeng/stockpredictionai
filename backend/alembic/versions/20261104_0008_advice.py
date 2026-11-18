"""持久化分析报告和账户共享推理配额记录。
Persist advice reports and shared account inference quota records.
"""
from alembic import op
import sqlalchemy as sa
revision = '20261104_0008'
down_revision = '20261103_0007'
branch_labels = depends_on = None

def upgrade():
    op.create_table('ai_calls',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('task', sa.String(64), nullable=False),
        sa.Column('model', sa.String(128), nullable=False),
        sa.Column('background', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(64), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('tokens', sa.Integer(), nullable=False))
    op.create_index('ix_ai_calls_started_at', 'ai_calls', ['started_at'])
    op.create_table('advice_jobs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('symbol', sa.String(32), nullable=False),
        sa.Column('portfolio_id', sa.String(64), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_token', sa.String(64)),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON()), sa.Column('error', sa.String(128)))
    for col in ('symbol', 'status'):
        op.create_index('ix_advice_jobs_' + col, 'advice_jobs', [col])

def downgrade():
    op.drop_table('advice_jobs')
    op.drop_table('ai_calls')
