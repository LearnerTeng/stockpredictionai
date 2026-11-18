import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from database.models import Base, DocumentEmbedding, Instrument, ResearchDocument
from database.session import session_factory
from retrieval.documents import sentiment_rows_as_of
from retrieval.store import RetrievalStore
from retrieval.answers import answer_question
from sentiment.store import SentimentStore


class FakeEmbedder:
    version = 'fixture:1536:v1'

    def embed(self, texts):
        return [[1.0] + [0.0] * 1535 for _ in texts], len(texts)


class RetrievalTests(TestCase):
    postgres = False

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SentimentStore(os.environ['TEST_POSTGRES_URL'] if self.postgres else
                                   f'sqlite:///{Path(self.temp.name) / "test.db"}')
        if self.postgres:
            from sqlalchemy.schema import CreateSchema
            self.schema = 'retrieval_test_' + uuid4().hex
            with self.store.engine.begin() as conn:
                conn.execute(CreateSchema(self.schema))
            self.store.engine = self.store.engine.execution_options(schema_translate_map={None: self.schema})
            self.store.sessions = session_factory(self.store.engine)
        Base.metadata.create_all(self.store.engine)
        self.now = datetime.now(timezone.utc) - timedelta(hours=1)
        with self.store.sessions.begin() as session:
            session.add(Instrument(symbol='AAPL', name='Apple', market='US', exchange='NASDAQ',
                sector='Technology', currency='USD', status='active', created_at=self.now, updated_at=self.now))
        self.retrieval = RetrievalStore(self.store.sessions, FakeEmbedder())

    def tearDown(self):
        if self.postgres:
            from sqlalchemy.schema import DropSchema
            assert self.schema.startswith('retrieval_test_') and len(self.schema) == 47
            with self.store.engine.begin() as conn:
                conn.execute(DropSchema(self.schema, cascade=True))
        self.store.engine.dispose()
        self.temp.cleanup()

    def article(self, title='Apple earnings rise', at=None):
        item = dict(id='fixture', content_hash='fixture', provider='fixture', provider_item_id='one',
                    title=title, summary=title, source='Fixture', published_at=self.now - timedelta(days=1),
                    symbols=[dict(symbol='AAPL', relevance_score=1)])
        with patch('sentiment.store.utc_now', return_value=at or self.now):
            return self.store.upsert_article(item)[1][0]

    def test_revisions_are_immutable_and_identical_ingestion_is_idempotent(self):
        self.article()
        self.article()
        self.article('Apple earnings corrected', self.now + timedelta(minutes=10))
        with self.store.sessions() as session:
            docs = session.scalars(select(ResearchDocument).order_by(ResearchDocument.revision)).all()
        self.assertEqual([d.revision for d in docs], [1, 2])
        self.assertEqual(docs[0].title, 'Apple earnings rise')
        self.assertEqual(docs[1].title, 'Apple earnings corrected')

    def test_analysis_is_not_backdated_and_corrections_preserve_old_observations(self):
        relation = self.article()
        for minutes, score in ((10, .7), (20, -.5)):
            with patch('sentiment.store.utc_now', return_value=self.now + timedelta(minutes=minutes)):
                self.store.save_analysis(relation, dict(analysis_status='analyzed', sentiment_score=score,
                    analyzed_at=self.now - timedelta(days=10)))
        self.assertEqual(sentiment_rows_as_of(self.store.sessions, 'AAPL', self.now), [])
        rows = sentiment_rows_as_of(self.store.sessions, 'AAPL', self.now + timedelta(minutes=15))
        self.assertEqual(rows[0][0].sentiment_score, .7)
        rows = sentiment_rows_as_of(self.store.sessions, 'AAPL', self.now + timedelta(minutes=25))
        self.assertEqual(rows[0][0].sentiment_score, -.5)

    def test_worker_is_incremental_and_retries_without_leaking_errors(self):
        self.article()
        self.assertEqual(self.retrieval.enqueue(), 1)
        self.assertEqual(self.retrieval.enqueue(), 0)
        with patch.object(self.retrieval.embedder, 'embed', side_effect=RuntimeError('secret')):
            self.assertEqual(self.retrieval.process()['failed'], 1)
        with self.store.sessions.begin() as session:
            job = session.scalar(select(DocumentEmbedding))
            self.assertEqual(job.error, 'RuntimeError')
            self.assertEqual(job.status, 'retry')
            job.retry_at = self.now
        self.assertEqual(self.retrieval.process()['ready'], 1)
        self.assertEqual(self.retrieval.process()['ready'], 0)

    def test_answer_rejects_unknown_evidence_and_fabricated_quotes(self):
        evidence = {'as_of': self.now.isoformat(), 'items': [{'id': 'known', 'text': 'Revenue increased.'}]}
        for claim in (
            {'text': 'Growth', 'evidence_id': 'missing', 'quote': 'Revenue'},
            {'text': 'Growth', 'evidence_id': 'known', 'quote': 'Profit doubled'},
        ):
            import json
            client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs:
                SimpleNamespace(output_text=json.dumps({'claims': [claim]}))))
            with patch.object(self.retrieval, 'search', return_value=evidence):
                with self.assertRaisesRegex(ValueError, 'unverified'):
                    answer_question(self.retrieval, 'Growth?', client=client)

    def test_missing_evidence_never_invokes_generation(self):
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: self.fail('unexpected generation')))
        with patch.object(self.retrieval, 'search', return_value={'as_of': self.now.isoformat(), 'items': []}):
            result = answer_question(self.retrieval, 'Growth?', client=client)
        self.assertEqual(result['status'], 'insufficient-evidence')
        self.assertEqual(result['claims'], [])


@skipUnless(os.getenv('TEST_POSTGRES_URL'), 'set TEST_POSTGRES_URL for pgvector integration')
class PostgresRetrievalTests(RetrievalTests):
    postgres = True

    def test_real_vector_operator_filters_symbols_revisions_and_availability(self):
        self.article()
        self.article('Apple earnings corrected', self.now + timedelta(minutes=10))
        self.retrieval.enqueue()
        self.assertEqual(self.retrieval.process()['ready'], 2)
        for mode in ('keyword', 'vector', 'hybrid'):
            result = self.retrieval.search('earnings', symbol='AAPL', mode=mode)
            self.assertEqual([i['revision'] for i in result['items']], [2])
            self.assertEqual(self.retrieval.search('earnings', symbol='MSFT', mode=mode)['items'], [])
        historical = self.retrieval.search('earnings', mode='keyword', as_of=self.now + timedelta(minutes=5))
        self.assertEqual([i['revision'] for i in historical['items']], [1])
        self.assertEqual(self.retrieval.search('earnings', mode='vector', as_of=self.now)['items'], [])
