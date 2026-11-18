"""用同一份冻结的起始持仓运行四条可独立选择的回放曲线。
Replay four independently selectable strategies from the same frozen starting portfolio.
"""
from copy import deepcopy
from datetime import date, timedelta
from math import isfinite
from dataclasses import replace

from sqlalchemy import select
from database.models import NewsModelRun, ResearchDocument
from market_data.calendar import session_close
from market_data.point_in_time import aware, utc
from .paper_cycle import digest
from .portfolio_backtest import PortfolioBacktestConfig, run_portfolio_backtest
from .contracts import normalize_bars
from llm_gateway import configuration
from sentiment.model_lines import VERSION, symbol_scores

LINES = ('deepseek', 'ultra', 'experiment', 'holdings')
RECIPE = 'news-comparison-v1:mean-sentiment:7d:positive-only:experiment-0.4D-0.4U-0.2provider'


def model_pins(selected, requested_pins):
    pins = {}
    for line in ('deepseek', 'ultra'):
        if line in selected or 'experiment' in selected:
            cfg_model = configuration(line)
            default = dict(model=cfg_model['model'], provider=cfg_model['provider'], version=VERSION)
            pin = requested_pins.get(line, default)
            if (not isinstance(pin, dict) or set(pin) != set(default)
                    or pin['version'] not in (VERSION, 'news-event-v2')
                    or not all(isinstance(value, str) and value for value in pin.values())):
                raise ValueError('model pin requires provider, model and supported prompt version')
            pins[line] = pin
    return pins


def news_observations(sessions, symbols):
    with sessions() as session:
        documents = session.scalars(select(ResearchDocument)).all()
        rows = session.execute(select(NewsModelRun, ResearchDocument).join(
            ResearchDocument, ResearchDocument.id == NewsModelRun.document_id).where(NewsModelRun.status == 'ready')).all()
    relevant = {doc.article_id for doc in documents if set(doc.symbols).intersection(symbols)}
    return [doc for doc in documents if doc.article_id in relevant], [
        (job, doc) for job, doc in rows if doc.article_id in relevant]


def news_as_of(documents, rows, pins, cutoff, line=None):
    latest = {}
    revisions = {}
    for document in documents:
        if utc(document.available_at) <= cutoff:
            revisions[document.article_id] = max(revisions.get(document.article_id, 0), document.revision)
    for job, doc in rows:
        pin = pins.get(job.line)
        if not pin or job.completed_at is None or (job.model, job.payload['provider'], job.payload['version']) != (pin['model'], pin['provider'], pin['version']):
            continue
        if (utc(job.completed_at) > cutoff or
            utc(doc.available_at) > cutoff or utc(doc.published_at) > cutoff or
            utc(doc.published_at) < cutoff - timedelta(days=7) or doc.revision != revisions.get(doc.article_id)):
            continue
        if line and line != 'experiment' and job.line != line:
            continue
        key = doc.article_id, job.line
        existing = latest.get(key)
        if existing is None or (doc.revision, utc(job.completed_at), job.id) > (existing[1].revision, utc(existing[0].completed_at), existing[0].id):
            latest[key] = job, doc
    return latest


def run_comparison(sessions, dataset, selected, config=None):
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected) or any(l not in LINES for l in selected):
        raise ValueError('select one or more distinct simulation lines')
    cfg = config or PortfolioBacktestConfig()
    base = deepcopy(dataset)
    base.pop('signals', None)
    base.pop('hold_only', None)
    base['benchmark'] = normalize_bars(base['benchmark'])
    if not base['benchmark']:
        raise ValueError('benchmark history is required')
    for asset in base['assets'].values():
        asset['bars'] = normalize_bars(asset['bars'])
    snapshot = base.get('holding_snapshot')
    if not snapshot or not isinstance(snapshot.get('quantities'), dict):
        raise ValueError('a dated holding_snapshot with quantities is required for a fair comparison')
    days = [r.get('trade_date') or r['date'] for r in base['benchmark']]
    if len(days) > 2500 or len(base['assets']) > 50:
        raise ValueError('comparison is limited to 2500 sessions and 50 assets')
    from market_data.calendar import calendar
    opening = calendar('US', date.fromisoformat(days[0]).year).session_open(days[0]).to_pydatetime()
    if aware(snapshot['as_of']) > opening:
        raise ValueError('holdings snapshot must be known before the first replay opening; current holdings cannot be backdated')
    base['initial_holdings'] = snapshot['quantities']
    if 'cash' in snapshot:
        cash = float(snapshot['cash'])
        if not isfinite(cash) or cash < 0:
            raise ValueError('snapshot cash must be finite and nonnegative')
        value = 0.0
        for sid, quantity in snapshot['quantities'].items():
            if sid not in base['assets'] or not isfinite(float(quantity)) or float(quantity) < 0:
                raise ValueError('invalid snapshot holdings')
            first_bar = next((r for r in base['assets'][sid]['bars'] if (r.get('trade_date') or r['date']) == days[0]), None)
            if first_bar is None:
                raise ValueError('snapshot holding missing first-session valuation')
            value += float(quantity) * float(first_bar['open'])
        cfg = replace(cfg, initial_cash=cash+value)
    cfg.validate()
    if any('symbol' not in asset for asset in base['assets'].values()):
        raise ValueError('each permanent security ID requires a symbol')
    symbols = {a['symbol']: sid for sid, a in base['assets'].items()}
    if len(symbols) != len(base['assets']):
        raise ValueError('ambiguous security symbols')
    pins = model_pins(selected, base.get('model_pins', {}))
    documents, rows = news_observations(sessions, symbols)
    results = {}
    for line in selected:
        local = deepcopy(base)
        audit, signals = [], []
        if line == 'holdings':
            local['hold_only'] = True
        else:
            local['signals'] = signals
            local['hold_on_missing_signals'] = True
            for day in days:
                cutoff = session_close(date.fromisoformat(day))
                latest = news_as_of(documents, rows, pins, cutoff, line)
                for symbol, sid in symbols.items():
                    groups = {}
                    for (article, model_line), (job, doc) in latest.items():
                        scores = symbol_scores(job.result['output'], doc.symbols, pins[model_line]['version'])
                        if symbol not in scores:
                            continue
                        groups.setdefault(article, {})[model_line] = (job, scores[symbol])
                    values, ids = [], []
                    for group in groups.values():
                        if line == 'experiment':
                            if 'deepseek' not in group or 'ultra' not in group:
                                continue
                            d, u = group['deepseek'][0], group['ultra'][0]
                            # 仅比较相同版本的新闻，避免将更正后的评分与原文混用。
                            # Match the news revision exactly to keep corrected scores paired with their source text.
                            if d.document_id != u.document_id:
                                continue
                            raw = d.payload.get('provider_scores', {}).get(symbol)
                            if raw is None:
                                continue
                            value = .4*group['deepseek'][1] + .4*group['ultra'][1] + .2*float(raw)
                            ids.extend([d.id, u.id])
                        else:
                            job, value = group[line]
                            ids.append(job.id)
                        if not isfinite(value):
                            raise ValueError('invalid experiment feature')
                        values.append(value)
                    if values:
                        signals.append(dict(date=day, security_id=sid, score=sum(values)/len(values), available_at=cutoff.isoformat()))
                        audit.append(dict(date=day, security_id=sid, score=signals[-1]['score'], run_ids=sorted(set(ids))))
            if not signals:
                results[line] = {'status': 'insufficient-evidence', 'reason': 'No eligible completed news evidence in this replay window'}
                continue
        replay = run_portfolio_backtest(local, cfg)
        results[line] = dict(status='ready', replay=replay, evidence=audit)
    return dict(id=digest({'dataset': base, 'selected': selected, 'config': cfg.__dict__, 'recipe': RECIPE,
                           'results': results, 'model_pins': pins}), recipe=RECIPE, selected=selected, results=results,
                model_pins=pins, period=[days[0], days[-1]], snapshot_as_of=snapshot['as_of'],
                dataset_hash=digest(base), initial_capital=cfg.initial_cash)
