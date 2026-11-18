from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select
from database.models import Base, AdviceJob
from database.session import session_factory
from advice import AdviceService, decision, validate_claims
from ai_runtime import save_settings, settings, QuotaWait, retry_seconds

class AdviceTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + str(Path(self.tmp.name)/'test.db'))
        Base.metadata.create_all(self.engine)
        self.sessions = session_factory(self.engine)
        self.service = AdviceService(self.sessions, None, None)
        self.snapshot = dict(symbol='AAPL', portfolio_id='primary', position=None, limit=.25, weight=None,
            long_term=False, quote={'trade_date': '2026-11-04'}, market='US', currency='USD', score=70,
            evidence=[dict(id='doc1',body='Revenue rose.',url='https://example.org',source='fixture')])
        self.mock_snapshot = patch.object(self.service,'snapshot',side_effect=lambda *_: dict(self.snapshot))
        self.mock_snapshot.start()
    def tearDown(self):
        self.mock_snapshot.stop(); self.engine.dispose(); self.tmp.cleanup()
    def test_idempotent_inputs_and_changed_snapshot_supersedes_pending(self):
        one=self.service.enqueue('AAPL')
        self.assertEqual(one['id'],self.service.enqueue('AAPL')['id'])
        self.snapshot['score']=20
        two=self.service.enqueue('AAPL')
        self.assertNotEqual(one['id'],two['id'])
        with self.sessions() as s:self.assertEqual(s.get(AdviceJob,one['id']).status,'superseded')
    def test_account_and_language_are_part_of_identity(self):
        one=self.service.enqueue('AAPL')
        self.assertNotEqual(one['id'],self.service.enqueue('AAPL',language='ja')['id'])
    def test_settings_reject_nan_and_excess_quota(self):
        for bad in ({'position_limit':float('nan')},{'target_rpm':41},{'concurrency':3},{'enabled':'yes'}):
            with self.assertRaises(ValueError): save_settings(bad,self.sessions)
        save_settings({'enabled':True,'position_limit':.15},self.sessions)
        self.assertEqual(settings(self.sessions)['position_limit'],.15)
    def test_missing_quotes_and_long_term_structure(self):
        self.snapshot['quote']=None
        self.assertEqual(decision(self.snapshot)['action'],'insufficient_evidence')
        self.snapshot.update(long_term=True,position={'quantity':10},weight=.5,limit=.3)
        self.assertEqual(decision(self.snapshot)['action'],'consider_reduce')
        self.assertFalse(decision(self.snapshot)['simulation_eligible'])
    def test_quotes_must_belong_to_frozen_evidence(self):
        with self.assertRaises(ValueError):validate_claims({'claims':[dict(evidence_id='doc1',quote='Invented')]},self.snapshot['evidence'])
    def test_missing_key_waits_without_consuming_attempts(self):
        row=self.service.enqueue('AAPL')
        with patch('advice.structured_client',return_value=None):self.service.process_one()
        with self.sessions() as s:
            job=s.get(AdviceJob,row['id']);self.assertEqual(job.status,'retry');self.assertEqual(job.attempts,0)
    def test_expired_lease_recovers_and_success_preserves_decision(self):
        row=self.service.enqueue('AAPL')
        with self.sessions.begin() as s:
            job=s.get(AdviceJob,row['id']);job.status='running';job.due_at=datetime.now(timezone.utc)-timedelta(minutes=5)
        response=SimpleNamespace(output_text=json.dumps(dict(summary='Evidence only',risks=[],conditions=[],claims=[dict(text='Revenue rose',evidence_id='doc1',quote='Revenue rose.')])),model='deepseek-ai/deepseek-v4.1-flash')
        client=SimpleNamespace(config={'model':response.model},responses=SimpleNamespace(create=lambda **_:response))
        with patch('advice.structured_client',return_value=client):self.service.process_one()
        with self.sessions() as s:
            job=s.get(AdviceJob,row['id']);self.assertEqual(job.status,'ready');self.assertEqual(job.result['input_hash'].__len__(),64)
    def test_reviews_require_matching_completed_parent(self):
        with self.assertRaises(ValueError):self.service.enqueue('AAPL',kind='review',parent_id='missing')
    def test_retry_after_seconds(self):
        self.assertEqual(retry_seconds(SimpleNamespace(response=SimpleNamespace(headers={'Retry-After':'17'}))),17)

    def test_api_validation_and_queued_response(self):
        from flask import Flask
        from advice import register_advice
        app=Flask(__name__)
        register_advice(app, lambda:(SimpleNamespace(sessions=self.sessions),None),None,None)
        with patch('advice.AdviceService.snapshot',return_value=self.snapshot):
            client=app.test_client()
            self.assertEqual(client.put('/ai/settings',json={'rpm':100}).status_code,400)
            response=client.post('/advice/jobs',json={'symbol':'AAPL'})
            self.assertEqual(response.status_code,202)
            self.assertEqual(client.get('/advice/jobs/'+response.json['id']).json['status'],'pending')
            self.assertEqual(client.get('/advice/jobs/missing').status_code,404)
            self.assertEqual(client.get('/advice').json['items'][0]['symbol'],'AAPL')

    def test_shared_quota_refuses_sqlite_fallback(self):
        from ai_runtime import reserve
        with self.assertRaisesRegex(RuntimeError,'PostgreSQL'):
            reserve('advice','fixture',self.sessions)

    def test_staleness_is_frozen_before_close_and_for_legacy_jobs(self):
        from advice import freshness
        for market, before, after in (
            ('US', '2026-11-04T20:59:00+00:00', '2026-11-04T21:00:00+00:00'),
            ('JP', '2026-11-04T06:29:00+00:00', '2026-11-04T06:30:00+00:00'),
        ):
            with self.subTest(market=market):
                prior = '2026-11-02' if market == 'JP' else '2026-11-03'
                snap = {**self.snapshot, 'market': market, 'quote': {'trade_date': prior}}
                before, after = datetime.fromisoformat(before), datetime.fromisoformat(after)
                self.assertFalse(freshness(snap, before)['quote_stale'])
                self.assertTrue(freshness(snap, after)['quote_stale'])
                if market == 'JP':
                    holiday = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
                    self.assertFalse(freshness(snap, holiday)['quote_stale'])
        self.snapshot.update(analysis_at='2026-11-04T20:59:00+00:00', quote={'trade_date': '2026-11-03'})
        job = self.service.enqueue('AAPL')
        with self.sessions() as session:
            snap = session.get(AdviceJob, job['id']).payload['snapshot']
        with patch('advice.now', return_value=datetime(2026, 11, 7, tzinfo=timezone.utc)):
            self.assertEqual(decision(snap)['action'], 'consider_buy')
            self.assertEqual(decision({**self.snapshot, 'freshness': False})['action'], 'consider_buy')

    def test_nisa_uses_holdings_coverage_and_dated_nav_separately(self):
        snap = {**self.snapshot, 'market': 'unknown', 'nisa': True, 'long_term': True, 'position': {'quantity': 100},
                'analysis_at': '2026-11-13T10:00:00+00:00', 'quote': {'trade_date': '2026-11-12'}}
        self.assertEqual(decision({**snap, 'holdings_through': '2026-10-28'})['reason'], 'nisa_holdings_stale')
        self.assertEqual(decision({**snap, 'holdings_through': '2026-11-05'})['action'], 'hold')
        self.assertEqual(decision({**snap, 'holdings_through': '2026-11-05', 'quote': None})['reason'], 'nav_missing_or_stale')

    def test_snapshot_excludes_unavailable_quotes_and_replay_api_does_not_call_model(self):
        from flask import Flask
        from advice import register_advice
        bar = {'trade_date': '2026-11-04', 'close': 100, 'available_at': '2026-11-04T21:20:00+00:00'}
        older = {'trade_date': '2026-11-03', 'close': 99, 'available_at': '2026-11-03T21:01:00+00:00'}
        market = SimpleNamespace(get_symbol=lambda _: {'market': 'US'}, list_daily_bars=lambda *_a, **_k: [bar, older])
        trading = SimpleNamespace(get_portfolio=lambda _: dict(positions=[], equity=0, account_type='paper'))
        app = Flask(__name__)
        register_advice(app, lambda: (SimpleNamespace(sessions=self.sessions), None), market, trading)
        client = app.test_client()
        with patch('advice.now', return_value=datetime(2026, 11, 4, 21, 5, tzinfo=timezone.utc)):
            job = client.post('/advice/jobs', json={'symbol': 'AAPL'})
        self.assertEqual(job.status_code, 202)
        with self.sessions() as session:
            snap = session.get(AdviceJob, job.json['id']).payload['snapshot']
        self.assertEqual(snap['quote']['trade_date'], '2026-11-03')
        self.assertTrue(snap['freshness']['quote_stale'])
        with patch('advice.structured_client', side_effect=AssertionError('replay must stay offline')):
            one = client.get('/advice/jobs/' + job.json['id'] + '/replay')
            two = client.get('/advice/jobs/' + job.json['id'] + '/replay')
        self.assertEqual(one.json, two.json)
        self.assertEqual(one.json['decision']['reason'], 'quote_missing_or_stale')


    def test_deepseek_advice_requests_final_json_without_reasoning(self):
        from llm_gateway import StructuredClient
        response = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content='{"summary":"Synthetic result"}'))], usage=None)
        with patch('openai.OpenAI') as openai:
            completions = openai.return_value.chat.completions
            completions.create.return_value = response
            client = StructuredClient(dict(provider='nvidia', model='deepseek-ai/deepseek-v4.1-flash',
                                           task='advice', key='fixture'))
            result = client._create(input=[dict(role='user', content='Synthetic question')],
                text={'format': {'type': 'json_schema', 'name': 'fixture',
                                 'schema': {'type': 'object', 'required': ['summary']}}}, max_output_tokens=100)
        self.assertEqual(json.loads(result.output_text)['summary'], 'Synthetic result')
        self.assertEqual(completions.create.call_args.kwargs['extra_body'], {'chat_template_kwargs': {'thinking': False}})
