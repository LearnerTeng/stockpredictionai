"""Auditable local daily replay. No live orders or automatic model promotion."""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from math import isfinite, isclose

from sqlalchemy import select, text
from database.models import PaperCycle
from market_data.point_in_time import aware
from market_data.calendar import available_session, next_session, session_close
from .portfolio_backtest import PortfolioBacktestConfig, run_portfolio_backtest


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def dataset_at(dataset, day):
    result = deepcopy(dataset)
    def date_of(row):
        return row.get('trade_date') or row['date']
    result['benchmark'] = [r for r in result['benchmark'] if date_of(r) <= day]
    for asset in result['assets'].values():
        asset['bars'] = [r for r in asset['bars'] if date_of(r) <= day]
    for key in ('actions', 'signals'):
        if key in result:
            result[key] = [r for r in result[key] if r['date'] <= day]
    result['memberships'] = [r for r in result.get('memberships', []) if r['valid_from'] <= day]
    return result


def validate_model_signals(dataset):
    """Require frozen-model provenance and a strictly out-of-sample signal date."""
    seen = set()
    for row in dataset.get('signals', []):
        key = row['security_id'], row['date']
        if key in seen or row['security_id'] not in dataset['assets']:
            raise ValueError('duplicate or unknown model signal')
        seen.add(key)
        if not row.get('model_run_id') or not row.get('trained_until') or row['trained_until'] >= row['date']:
            raise ValueError('model signals require model_run_id and strictly earlier trained_until')
        date.fromisoformat(row['date'])
        date.fromisoformat(row['trained_until'])
        if aware(row['model_available_at']) > aware(row['available_at']):
            raise ValueError('signal predates model availability')
        if not isfinite(float(row['score'])):
            raise ValueError('nonfinite score')


def archived_signals(root, assets, horizon=5):
    """Bridge actual forward archives to replay. Never invent historical availability."""
    from .research import read_run
    symbols = {asset['symbol']: sid for sid, asset in assets.items()}
    if len(symbols) != len(assets):
        raise ValueError('asset symbols must map to unique permanent IDs')
    result, seen = [], set()
    for path in sorted((root / 'predictions').glob('*.json')):
        archive = json.loads(path.read_text(encoding='utf-8'))
        if archive['symbol'] not in symbols:
            continue
        prediction = archive['prediction']
        if not prediction.get('model_run_id') or prediction.get('fallback_used'):
            continue
        _, manifest = read_run(root, prediction['model_run_id'])
        if manifest['symbol'] != archive['symbol'] or not manifest['validation']['eligible']:
            raise ValueError('archive model provenance mismatch')
        recorded = aware(archive['recorded_at'])
        cutoff = date.fromisoformat(prediction['data_cutoff'])
        signal_day = available_session(recorded)
        if recorded < session_close(cutoff) or signal_day > next_session(cutoff):
            raise ValueError('retrospective or pre-data prediction archive')
        matching = [r for r in prediction['forecasts'] if r['horizon_days'] == horizon]
        if len(matching) != 1:
            raise ValueError('archive forecast horizon missing or ambiguous')
        row = dict(security_id=symbols[archive['symbol']], date=signal_day.isoformat(),
            available_at=recorded.isoformat(), model_run_id=manifest['run_id'],
            trained_until=manifest['trained_until'], model_available_at=manifest['created_at'],
            score=float(matching[0]['excess_return_pct']) / 100)
        fingerprint = digest(row)
        if fingerprint not in seen:
            result.append(row)
            seen.add(fingerprint)
    validate_model_signals({'assets': assets, 'signals': result})
    if not result:
        raise ValueError('no usable forward model archives; refusing an empty AI comparison')
    return result


def reconcile_portfolio(dataset, result):
    cash = result['config']['initial_cash']
    shares = {sid: 0.0 for sid in dataset['assets']}
    prices = {sid: {r.get('trade_date') or r['date']: float(r['close']) for r in asset['bars']}
              for sid, asset in dataset['assets'].items()}
    for row in result['equity_curve']:
        day = row['date']
        for action in dataset.get('actions', []):
            if action['date'] == day:
                if action['type'] == 'split':
                    shares[action['security_id']] *= float(action['value'])
                elif action['type'] == 'delisting':
                    shares[action['security_id']] = 0
        cash += sum(e['cash_delta'] for e in result['cash_events'] if e['date'] == day)
        for fill in result['fills']:
            if fill['date'] == day:
                quantity = fill['quantity'] * (1 if fill['side'] == 'buy' else -1)
                shares[fill['security_id']] += quantity
                cash -= quantity * fill['price'] + fill['fee']
        nav = cash + sum(quantity * prices[sid][day] for sid, quantity in shares.items() if quantity > 1e-10)
        if not isclose(cash, row['cash'], abs_tol=1e-6) or not isclose(nav, row['equity'], abs_tol=1e-6):
            raise ValueError('daily cash or NAV reconciliation failed')
        if any(not isclose(q, row['holdings'].get(sid, 0), abs_tol=1e-8) for sid, q in shares.items()):
            raise ValueError('daily holdings reconciliation failed')
    return {'status': 'matched', 'sessions': len(result['equity_curve'])}


def run_paper_cycle(sessions, dataset, *, strategy='research', config=None):
    if not isinstance(strategy, str) or not 1 <= len(strategy) <= 64:
        raise ValueError('strategy must contain 1 to 64 characters')
    cfg = config or PortfolioBacktestConfig()
    validate_model_signals(dataset)
    result = run_portfolio_backtest(dataset, cfg)
    day = result['equity_curve'][-1]['date']
    if day > datetime.now(timezone.utc).date().isoformat():
        raise ValueError('future paper session')
    frozen = dataset_at(dataset, day)
    version = digest({'dataset': frozen, 'config': result['config']})
    identity = digest({'strategy': strategy, 'day': day})
    report = {'strategy': strategy, 'date': day, 'dataset': frozen, 'result': result,
              'status': 'local-replay', 'dataset_hash': version}
    report['reconciliation'] = reconcile_portfolio(frozen, result)
    baseline = deepcopy(dataset)
    baseline.pop('signals', None)
    report['momentum_baseline'] = run_portfolio_backtest(baseline, cfg)['metrics']
    report['model_runs'] = sorted({r['model_run_id'] for r in dataset.get('signals', [])})
    with sessions.begin() as session:
        if session.bind.dialect.name == 'postgresql':
            lock_id = int.from_bytes(sha256(strategy.encode()).digest()[:8], 'big', signed=True)
            session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_id})
        elif session.bind.dialect.name == 'sqlite':
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        previous = session.scalars(select(PaperCycle).where(
            PaperCycle.report['strategy'].as_string() == strategy)).all()
        for saved in previous:
            prior = saved.report
            if prior['date'] > day:
                raise ValueError('paper sessions must not move backwards')
            old = digest({'dataset': dataset_at(frozen, prior['date']), 'config': result['config']})
            if old != saved.dataset_hash:
                raise ValueError('historical inputs or configuration changed; use a new strategy version')
            if run_portfolio_backtest(dataset_at(frozen, prior['date']), cfg) != prior['result']:
                raise ValueError('engine replay changed; use a new strategy version')
        existing = session.get(PaperCycle, identity)
        if existing:
            if existing.report != report:
                raise ValueError('replay differs from saved ledger')
            return existing.report
        session.add(PaperCycle(id=identity, created_at=datetime.now(timezone.utc), dataset_hash=version, report=report))
    return report
