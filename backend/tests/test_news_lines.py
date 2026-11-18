from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.models import Base, Instrument, ResearchDocument, NewsModelRun
from sentiment.store import SentimentStore
from sentiment.model_lines import NewsModelLines, symbol_scores
from stock_ai.news_comparison import run_comparison
from stock_ai.portfolio_backtest import PortfolioBacktestConfig
from llm_gateway import StructuredClient
from sqlalchemy import select


class NewsLinesTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = SentimentStore(f'sqlite:///{Path(self.temp.name) / "lines.db"}')
        Base.metadata.create_all(self.store.engine)
        self.now = datetime(2026, 8, 31, 19, tzinfo=timezone.utc)
        with self.store.sessions.begin() as session:
            session.add(Instrument(symbol='AAPL', name='Apple', market='US', exchange='NASDAQ', sector='Technology',
                currency='USD', status='active', created_at=self.now, updated_at=self.now))
        with patch('sentiment.store.utc_now', return_value=self.now):
            self.store.upsert_article(dict(id='one', content_hash='one', title='Revenue increased.', provider='fixture',
                provider_item_id='one', source='fixture', published_at=self.now,
                symbols=[dict(symbol='AAPL', relevance_score=1, provider_sentiment_score=.5)]))
        self.lines = NewsModelLines(self.store.sessions)

    def tearDown(self):
        self.store.engine.dispose()
        self.temp.cleanup()

    def test_independent_models_do_not_bypass_provider_and_cache_inputs(self):
        self.assertEqual(self.lines.enqueue(['deepseek', 'ultra']), 2)
        self.assertEqual(self.lines.enqueue(['deepseek', 'ultra']), 0)
        inputs = []
        def factory(line):
            def create(**kwargs):
                inputs.append((line, kwargs['input']))
                output = dict(scores=[dict(symbol='AAPL', score=.8 if line == 'deepseek' else -.2)], event='earnings', horizon='5 sessions', unknowns=[],
                    facts=[dict(symbol='AAPL', claim='Revenue increased', quote='Revenue increased.', date='', amount='', currency='', period='', basis='')])
                return SimpleNamespace(output_text=json.dumps(output), usage=SimpleNamespace(total_tokens=20))
            return SimpleNamespace(responses=SimpleNamespace(create=create))
        self.assertEqual(self.lines.process(factory=factory)['ready'], 2)
        self.assertEqual(len(inputs), 2)
        # 验证两个模型的输入彼此独立。
        # Verify that each model receives independent inputs.
        self.assertNotIn('"score"', inputs[0][1][1]['content'])
        with self.store.sessions() as session:
            jobs = session.scalars(select(NewsModelRun)).all()
            self.assertEqual({j.result['output']['scores'][0]['score'] for j in jobs}, {.8, -.2})
            self.assertTrue(all(j.payload['provider_scores']['AAPL'] == .5 for j in jobs))

    def test_missing_key_remains_pending_and_does_not_create_neutral_result(self):
        self.lines.enqueue(['deepseek'])
        self.lines.process(factory=lambda _: None)
        with self.store.sessions() as session:
            job = session.scalar(select(NewsModelRun))
            self.assertEqual(job.status, 'pending')
            self.assertIsNone(job.result)
            self.assertEqual(job.attempts, 0)

    def test_four_lines_selection_holding_baseline_and_no_time_leak(self):
        data = json.loads((Path(__file__).resolve().parents[2] / 'examples/portfolio-replay.json').read_text())
        config = PortfolioBacktestConfig(**data.pop('config'))
        sid = next(iter(data['assets']))
        data['assets'][sid]['symbol'] = 'AAPL'
        for key, asset in data['assets'].items():
            if key != sid:
                asset['symbol'] = 'MSFT'
        data['holding_snapshot'] = dict(as_of='2026-08-31T12:00:00Z', quantities={sid: 10})
        report = run_comparison(self.store.sessions, data, ['holdings', 'deepseek'], config)
        self.assertEqual(set(report['results']), {'holdings', 'deepseek'})
        self.assertEqual(report['results']['deepseek']['status'], 'insufficient-evidence')
        self.assertEqual(report['results']['holdings']['replay']['fills'], [])
        self.assertEqual(report['results']['holdings']['replay']['equity_curve'][-1]['holdings'][sid], 10)
        self.lines.enqueue(['deepseek', 'ultra'])
        with self.store.sessions.begin() as session:
            for job in session.scalars(select(NewsModelRun)):
                job.status = 'ready'
                job.completed_at = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)
                job.result = {'output': {'scores': [{'symbol':'AAPL','score': .8 if job.line == 'deepseek' else -.2}],
                    'facts': [{'symbol': 'AAPL', 'quote': 'Revenue increased.'}]}}
                if job.line == 'deepseek':
                    for field in ('model', 'version'):
                        payload = dict(job.payload)
                        payload[field] = 'other'
                        session.add(NewsModelRun(id=field, document_id=job.document_id, line=job.line,
                            model=payload['model'], payload=payload, status='ready', attempts=1,
                            retry_at=self.now, completed_at=datetime(2026,9,1,12,tzinfo=timezone.utc),
                            result={'output': {'scores': [{'symbol':'AAPL','score':-1}], 'facts':[{'symbol':'AAPL'}]}}))
        report = run_comparison(self.store.sessions, data, ['deepseek', 'ultra', 'experiment', 'holdings'], config)
        self.assertTrue(all(r['status'] == 'ready' for r in report['results'].values()))
        self.assertNotEqual(report['results']['deepseek']['replay']['fills'], report['results']['ultra']['replay']['fills'])
        self.assertEqual(len(report['results']['experiment']['evidence'][0]['run_ids']), 2)
        self.assertTrue(all(r['score'] == .8 for r in report['results']['deepseek']['evidence']))
        data['benchmark'].reverse()
        self.assertEqual(report, run_comparison(self.store.sessions, data, ['deepseek','ultra','experiment','holdings'], config))
        data['holding_snapshot']['as_of'] = '2026-09-09T12:00:00Z'
        with self.assertRaisesRegex(ValueError, 'backdated'):
            run_comparison(self.store.sessions, data, ['holdings'], config)

    def test_company_specific_scores_and_legacy_ambiguity(self):
        facts = [{'symbol':'AAPL'}, {'symbol':'MSFT'}]
        out = {'scores':[{'symbol':'AAPL','score':.9}, {'symbol':'MSFT','score':-.7}], 'facts': facts}
        self.assertEqual(symbol_scores(out,['AAPL','MSFT'],'news-event-v3'), {'AAPL':.9,'MSFT':-.7})
        self.assertEqual(symbol_scores({'score':.9,'facts':facts}, ['AAPL','MSFT'],'news-event-v2'), {})
        out['scores'].pop()
        with self.assertRaises(ValueError):
            symbol_scores(out,['AAPL','MSFT'],'news-event-v3')

    def test_chat_gateway_validates_schema_and_rejects_truncation(self):
        cfg = dict(provider='nvidia', key='fixture', model='fixture')
        schema = {'type': 'object', 'properties': {'n': {'type': 'number'}}, 'required': ['n']}
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='length', message=SimpleNamespace(content='{"n":1}'))], usage=None)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
        with patch('openai.OpenAI', return_value=client), patch('ai_runtime.reserve', return_value='fixture'), patch('ai_runtime.finish'):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                StructuredClient(cfg).create(input=[dict(role='user', content='test')], text={'format': {'type':'json_schema', 'name':'fixture', 'schema':schema}}, max_output_tokens=50)

    def test_enqueue_covers_more_than_one_page(self):
        with self.store.sessions.begin() as session:
            original = session.scalar(select(ResearchDocument))
            for n in range(105):
                session.add(ResearchDocument(id=f'page-{n}',article_id=original.article_id,revision=n+100,
                    checksum=f'checksum-{n}',title='News',body='Revenue increased.',source='fixture',
                    symbols=['AAPL'],published_at=self.now,available_at=self.now))
        total = sum(self.lines.enqueue(['deepseek'],limit=10) for _ in range(12))
        self.assertEqual(total,106)
        self.assertEqual(self.lines.enqueue(['deepseek'],limit=10),0)
