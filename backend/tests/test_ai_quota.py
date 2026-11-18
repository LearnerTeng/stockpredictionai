"""通过 TEST_POSTGRES_URL 在专用 PostgreSQL 测试库运行。
Run against a dedicated PostgreSQL database via TEST_POSTGRES_URL.
"""
import os
import sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase, skipUnless
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select
from sqlalchemy.schema import CreateSchema, DropSchema
from database.session import session_factory
from database.models import AppSetting, AiCall
from ai_runtime import reserve, finish, QuotaWait

@skipUnless(os.getenv('TEST_POSTGRES_URL'), 'set TEST_POSTGRES_URL for isolated account quota tests')
class PostgresQuotaTests(TestCase):
    def setUp(self):
        self.root=create_engine(os.environ['TEST_POSTGRES_URL'])
        self.schema='quota_test_'+uuid4().hex
        with self.root.begin() as c:c.execute(CreateSchema(self.schema))
        self.engine=self.root.execution_options(schema_translate_map={None:self.schema})
        AppSetting.__table__.create(self.engine)
        AiCall.__table__.create(self.engine)
        self.sessions=session_factory(self.engine)
    def tearDown(self):
        with self.root.begin() as c:c.execute(DropSchema(self.schema,cascade=True))
        self.root.dispose()
    def test_background_reserves_interactive_budget_and_all_attempts_count(self):
        for _ in range(28):
            identity=reserve('sentiment','fixture',self.sessions)
            finish(identity,'failed',factory=self.sessions)
        with self.assertRaises(QuotaWait):reserve('sentiment','fixture',self.sessions)
        for _ in range(8):
            identity=reserve('advice','fixture',self.sessions)
            finish(identity,'completed',factory=self.sessions)
        with self.assertRaises(QuotaWait):reserve('advice','fixture',self.sessions)
        with self.sessions.begin() as s:
            for row in s.scalars(select(AiCall)):
                row.started_at=datetime.now(timezone.utc)-timedelta(seconds=61)
        self.assertTrue(reserve('advice','fixture',self.sessions))
    def test_independent_clients_share_concurrency_and_retry_after(self):
        def attempt(_):
            try:return reserve('advice','fixture',session_factory(self.engine))
            except QuotaWait:return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted=[r for r in pool.map(attempt,range(8)) if r]
        self.assertEqual(len(admitted),2)
        finish(admitted[0],'RateLimitError',retry_after=30,factory=self.sessions)
        with self.assertRaises(QuotaWait):reserve('advice','fixture',self.sessions)
