"""按美国和日本市场交易日滚动比较纯价格预测与价格加新闻预测。
Compare rolling price-only and price-plus-news forecasts on US and Japanese trading sessions.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from sqlalchemy import select

from database.models import BarRevision, Instrument
from market_data.calendar import calendar, session_close
from market_data.point_in_time import aware, utc
from sentiment.model_lines import symbol_scores
from .contracts import DEFAULT_HORIZONS, adjusted_bars, adjusted_price
from .ml_features import FEATURE_WINDOW, feature_vector
from .news_comparison import model_pins, news_as_of, news_observations
from .paper_cycle import digest
from .research import evaluation_cuts

BENCHMARKS = {"US": "SPY", "JP": "1306.T"}
RECIPE = "paired-ridge-v1:alpha10:60-train:20-news:3-paired:close-plus-30m"
MIN_TRAIN = 60
MIN_NEWS_TRAIN = 20
MIN_TEST = 3


def first_observations(sessions, symbols, first, last, as_of):
    with sessions() as session:
        rows = session.scalars(select(BarRevision).where(
            BarRevision.symbol.in_(symbols), BarRevision.trade_date.between(first, last),
            BarRevision.quality_status == "accepted", BarRevision.available_at <= as_of,
            BarRevision.ingested_at <= as_of).order_by(
                BarRevision.available_at, BarRevision.ingested_at, BarRevision.id)).all()
    bars = defaultdict(dict)
    for row in rows:
        known = max(utc(row.available_at), utc(row.ingested_at))
        previous = bars[row.symbol].get(row.trade_date)
        if previous is None or (known, row.id) < previous[:2]:
            bars[row.symbol][row.trade_date] = (
                known, row.id, {**row.payload, "trade_date": row.trade_date.isoformat()})
    return bars


def news_features(symbol, days, cutoffs, documents, rows, line, pins):
    result = {}
    for day, cutoff in zip(days, cutoffs):
        eligible = news_as_of(documents, rows, pins, cutoff, line)
        scores, ids = [], []
        for job, doc in eligible.values():
            value = symbol_scores(job.result["output"], doc.symbols, pins[line]["version"]).get(symbol)
            if value is not None:
                scores.append(value)
                ids.append(job.id)
        if scores:
            result[day] = (mean(scores), sorted(ids))
    return result


def paired_folds(symbol, days, cutoffs, stock, benchmark, news):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    features = {}
    for index, day in enumerate(days):
        cutoff = cutoffs[index]
        history = []
        for past in reversed(days[max(0, index + 1 - FEATURE_WINDOW):index + 1]):
            if past not in stock or stock[past][0] > cutoff:
                break
            history.append(stock[past][2])
        if day not in benchmark or benchmark[day][0] > cutoff:
            continue
        vector = feature_vector(adjusted_bars(history))
        if vector is not None:
            score, ids = news.get(day, (0.0, []))
            features[index] = (vector, [*vector, score, float(bool(ids))], ids)

    rows = defaultdict(list)
    for horizon in DEFAULT_HORIZONS:
        targets = {}
        for index in features:
            if index + horizon >= len(days):
                continue
            first, last = days[index], days[index + horizon]
            if last not in stock or last not in benchmark:
                continue
            start_stock, end_stock = stock[first], stock[last]
            start_bench, end_bench = benchmark[first], benchmark[last]
            actual = 100 * (adjusted_price(end_stock[2]) / adjusted_price(start_stock[2])
                            - adjusted_price(end_bench[2]) / adjusted_price(start_bench[2]))
            targets[index] = (actual, max(end_stock[0], end_bench[0]))
        # 按最长预测周期设置起点间隔，训练仅使用已实现的目标值。
        # Space forecast origins by the longest horizon and fit using realized labels only.
        for index in evaluation_cuts(len(days), MIN_TRAIN + 40, max(DEFAULT_HORIZONS), folds=60):
            if index not in targets or not features[index][2]:
                continue
            cutoff = cutoffs[index]
            training = [j for j, (_, known_at) in targets.items() if j + horizon <= index and known_at <= cutoff]
            if len(training) < MIN_TRAIN or sum(bool(features[j][2]) for j in training) < MIN_NEWS_TRAIN:
                continue
            predicted = {}
            for column, arm in enumerate(("baseline", "sentiment")):
                model = make_pipeline(StandardScaler(), Ridge(alpha=10))
                model.fit([features[j][column] for j in training], [targets[j][0] for j in training])
                predicted[arm] = float(model.predict([features[index][column]])[0])
            rows[horizon].append(dict(symbol=symbol, date=days[index].isoformat(), cutoff=cutoff.isoformat(),
                label_end=days[index + horizon].isoformat(), actual=targets[index][0], **predicted,
                news_run_ids=features[index][2], training_samples=len(training)))
    return rows


def evaluation_metrics(rows):
    def direction(value):
        return (value > 0) - (value < 0)

    if len(rows) < MIN_TEST:
        return dict(status="insufficient_data", samples=len(rows), baseline=None, sentiment=None)
    return dict(status="ready", samples=len(rows), **{
        arm: dict(mae_pct=mean(abs(row[arm] - row["actual"]) for row in rows),
                  direction_accuracy=mean(direction(row[arm]) == direction(row["actual"]) for row in rows))
        for arm in ("baseline", "sentiment")})


def evaluate_sentiment(sessions, payload, clock=None):
    now = clock or datetime.now(timezone.utc)
    as_of = aware(payload["as_of"]) if payload.get("as_of") else now
    first, last = date.fromisoformat(payload["start"]), date.fromisoformat(payload["end"])
    symbols = payload["symbols"]
    line = payload.get("line", "deepseek")
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 12 or any(not isinstance(s, str) for s in symbols):
        raise ValueError("Choose 1–12 stored US or JP symbols")
    if line not in ("deepseek", "ultra") or first >= last or (last - first).days > 365 * 7:
        raise ValueError("Choose a news model and an increasing date range of at most seven years")
    if as_of > now or last > as_of.date():
        raise ValueError("Evaluation dates must be in the past or today")
    symbols = sorted(set(symbol.upper().strip() for symbol in symbols))
    with sessions() as session:
        markets = dict(session.execute(select(Instrument.symbol, Instrument.market).where(
            Instrument.symbol.in_(symbols))).all())
    if set(markets) != set(symbols) or any(market not in BENCHMARKS for market in markets.values()):
        raise ValueError("All symbols must be stored US or JP instruments")
    pins = model_pins([line], payload.get("model_pins", {}))
    documents, news_rows = news_observations(sessions, symbols)
    bars = first_observations(sessions, set(symbols) | set(BENCHMARKS.values()), first, last, as_of)
    observations, metrics, coverage = {}, {}, {}
    for market, benchmark in BENCHMARKS.items():
        days = [day.date() for day in calendar(market, first.year).sessions_in_range(first.isoformat(), last.isoformat())]
        cutoffs = [session_close(day, market) + timedelta(minutes=30) for day in days]
        days = [day for day, cutoff in zip(days, cutoffs) if cutoff <= as_of]
        cutoffs = cutoffs[:len(days)]
        market_rows = defaultdict(list)
        for symbol in (symbol for symbol in symbols if markets[symbol] == market):
            scores = news_features(symbol, days, cutoffs, documents, news_rows, line, pins)
            coverage[symbol] = dict(market=market, stock_bars=len(bars[symbol]), benchmark_bars=len(bars[benchmark]),
                                    sessions_with_news=len(scores), exchange_sessions=len(days))
            for horizon, rows in paired_folds(symbol, days, cutoffs, bars[symbol], bars[benchmark], scores).items():
                market_rows[horizon].extend(rows)
        observations[market] = {str(horizon): market_rows[horizon] for horizon in DEFAULT_HORIZONS}
        metrics[market] = [dict(horizon=horizon, **evaluation_metrics(market_rows[horizon]))
                           for horizon in DEFAULT_HORIZONS]
    inputs = dict(start=first.isoformat(), end=last.isoformat(), symbols=symbols, line=line,
                  as_of=as_of.isoformat(), model_pins=pins)
    data_hash = digest({symbol: [(day.isoformat(), stamp.isoformat(), rid) for day, (stamp, rid, _) in sorted(rows.items())]
                        for symbol, rows in bars.items()})
    report = dict(inputs=inputs, recipe=RECIPE, benchmarks=BENCHMARKS, coverage=coverage,
                  metrics=metrics, observations=observations, bar_revision_hash=data_hash)
    return dict(id=digest(report), **report)
