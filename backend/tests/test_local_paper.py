from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.models import Base
from database.session import create_database_engine, session_factory
from stock_ai.paper_cycle import run_paper_cycle, validate_model_signals, reconcile_portfolio, archived_signals
from stock_ai.portfolio_backtest import PortfolioBacktestConfig
from trading.local_sandbox import replay_events, reconcile_events


class LocalExecutionTests(TestCase):
    def test_archive_bridge_uses_actual_recorded_time_and_rejects_backfill(self):
        from stock_ai.research import write_json
        manifest = {'symbol': 'AAPL', 'run_id': 'frozen', 'trained_until': '2026-08-01',
                    'created_at': '2026-08-02T00:00:00Z', 'validation': {'eligible': True}}
        archive = {'symbol': 'AAPL', 'recorded_at': '2026-09-01T21:00:00Z', 'prediction': {
            'model_run_id': 'frozen', 'data_cutoff': '2026-09-01',
            'forecasts': [{'horizon_days': 5, 'excess_return_pct': 2}]}}
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'predictions' / 'forward.json'
            write_json(path, archive)
            with patch('stock_ai.research.read_run', return_value=(root, manifest)):
                rows = archived_signals(root, {'permanent-id': {'symbol': 'AAPL'}})
                self.assertEqual(rows[0]['date'], '2026-09-02')
                self.assertEqual(rows[0]['score'], .02)
                archive['recorded_at'] = '2026-09-10T21:00:00Z'
                write_json(path, archive)
                with self.assertRaisesRegex(ValueError, 'retrospective'):
                    archived_signals(root, {'permanent-id': {'symbol': 'AAPL'}})

    def test_partial_fill_duplicate_cancel_and_restart(self):
        events = [dict(event_id='1', type='submit', order_id='o', symbol='AAPL', side='buy', quantity=10),
                  dict(event_id='2', type='fill', order_id='o', quantity=3, price=100, fee=1),
                  dict(event_id='3', type='fill', order_id='o', quantity=2, price=101, fee=1),
                  dict(event_id='4', type='cancel', order_id='o')]
        first = replay_events(events)
        self.assertEqual(first['holdings'], {'AAPL': '5'})
        self.assertEqual(first['cash'], '99496')
        self.assertEqual(first['orders']['o']['status'], 'cancelled')
        self.assertEqual(first, replay_events(events + [events[1]]))
        restored = json.loads(json.dumps(events))
        self.assertEqual(first, reconcile_events(restored, first))
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            replay_events(events + [{**events[1], 'quantity': 4}])
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            reconcile_events(events, {**first, 'cash': '0'})
        with self.assertRaisesRegex(ValueError, 'closed'):
            replay_events(events + [dict(event_id='5', type='fill', order_id='o', quantity=1, price=100)])

    def test_cash_share_and_overfill_guards(self):
        submit = dict(event_id='1', type='submit', order_id='o', symbol='AAPL', side='buy', quantity=10)
        fill = dict(event_id='2', type='fill', order_id='o', quantity=11, price=100)
        with self.assertRaises(ValueError):
            replay_events([submit, fill])
        with self.assertRaises(ValueError):
            replay_events([submit, {**fill, 'quantity': 10}], initial_cash=10)
        with self.assertRaises(ValueError):
            replay_events([{**submit, 'side': 'sell'}, {**fill, 'quantity': 10}])

    def test_paper_cycle_is_idempotent_and_rejects_rewritten_history(self):
        dataset = json.loads((Path(__file__).resolve().parents[2] / 'examples/portfolio-replay.json').read_text())
        cfg = PortfolioBacktestConfig(**dataset.pop('config'))
        with TemporaryDirectory() as folder:
            engine = create_database_engine(f'sqlite:///{Path(folder) / "paper.db"}')
            Base.metadata.create_all(engine)
            sessions = session_factory(engine)
            first = run_paper_cycle(sessions, dataset, config=cfg)
            self.assertEqual(first['reconciliation']['status'], 'matched')
            altered = deepcopy(first['result'])
            altered['equity_curve'][-1]['cash'] += 1
            with self.assertRaisesRegex(ValueError, 'reconciliation'):
                reconcile_portfolio(dataset, altered)
            self.assertEqual(first, run_paper_cycle(sessions, dataset, config=cfg))
            modified = deepcopy(dataset)
            modified['description'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'historical'):
                run_paper_cycle(sessions, modified, config=cfg)
            engine.dispose()
            engine = create_database_engine(f'sqlite:///{Path(folder) / "paper.db"}')
            self.assertEqual(first, run_paper_cycle(session_factory(engine), dataset, config=cfg))
            engine.dispose()

    def test_model_provenance_and_training_cutoff_required(self):
        row = dict(security_id='id', date='2026-10-01', available_at='2026-10-01T19:00:00Z',
                   model_available_at='2026-09-30T19:00:00Z', model_run_id='frozen',
                   trained_until='2026-09-29', score=.1)
        dataset = {'assets': {'id': {}}, 'signals': [row]}
        validate_model_signals(dataset)
        row['trained_until'] = '2026-10-01'
        with self.assertRaisesRegex(ValueError, 'strictly earlier'):
            validate_model_signals(dataset)
