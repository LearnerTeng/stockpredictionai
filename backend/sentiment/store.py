from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from math import ceil
from statistics import pstdev
from typing import Any, Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from database.models import (
    AppSetting,
    IngestionRun,
    Instrument,
    NewsCoverage,
    NewsItem,
    NewsItemInstrument,
    Position,
    SentimentAlert,
    SentimentDailyFeature,
    StockPreference,
)
from database.session import create_database_engine, session_factory
from market_data.store import normalize_symbol
from sentiment.providers import PRIMARY_DOMAINS, utc_now


DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "interval_minutes": 30,
    "markets": ["US", "JP"],
    "primary_domains": sorted(PRIMARY_DOMAINS),
    "alpha_vantage_daily_budget": 20,
    "max_articles_per_symbol": 40,
    "email_enabled": False,
    "email_recipients": [],
    "notification_language": "zh-CN",
    "digest_time": "08:00",
    "alert_statuses": ["holding", "wanted"],
    "negative_threshold": -0.45,
    "severe_threshold": -0.75,
    "dedupe_hours": 12,
    "last_digest_date": None,
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> str | None:
    return _aware(value).isoformat() if isinstance(value, datetime) else value.isoformat() if value is not None else None


MARKET_CLOCKS = {
    "US": (ZoneInfo("America/New_York"), time(16, 0)),
    "JP": (ZoneInfo("Asia/Tokyo"), time(15, 30)),
}


def news_trade_date(published_at: datetime, market: str) -> date:
    """Assign news to the first weekday close at which it can be acted on."""
    zone, close_time = MARKET_CLOCKS.get(market, MARKET_CLOCKS["US"])
    local = (_aware(published_at) or published_at.replace(tzinfo=timezone.utc)).astimezone(zone)
    trade_day = local.date()
    if local.time().replace(tzinfo=None) > close_time:
        trade_day += timedelta(days=1)
    while trade_day.weekday() >= 5:
        trade_day += timedelta(days=1)
    return trade_day


def _market_close_utc(trade_day: date, market: str) -> datetime:
    zone, close_time = MARKET_CLOCKS.get(market, MARKET_CLOCKS["US"])
    return datetime.combine(trade_day, close_time, zone).astimezone(timezone.utc)


class SentimentStore:
    def __init__(self, database_url: str):
        self.engine = create_database_engine(database_url)
        self.sessions = session_factory(self.engine)

    def settings(self, *, smtp_configured: bool = False) -> dict[str, Any]:
        value = dict(DEFAULT_SETTINGS)
        with self.sessions() as session:
            row = session.get(AppSetting, "news_sentiment")
            if row:
                try:
                    stored = json.loads(row.value_json)
                    if isinstance(stored, dict):
                        value.update(stored)
                except json.JSONDecodeError:
                    pass
        value["smtp_configured"] = smtp_configured
        return value

    def update_settings(self, payload: dict[str, Any], *, smtp_configured: bool = False) -> dict[str, Any]:
        allowed = {
            "enabled", "interval_minutes", "markets", "primary_domains", "alpha_vantage_daily_budget",
            "max_articles_per_symbol", "email_enabled", "email_recipients", "notification_language",
            "digest_time", "alert_statuses", "negative_threshold", "severe_threshold", "dedupe_hours",
            "last_digest_date",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unsupported sentiment setting: {', '.join(sorted(unknown))}")
        current = self.settings(smtp_configured=smtp_configured)
        current.pop("smtp_configured", None)
        current.update(payload)
        interval = int(current["interval_minutes"])
        if interval < 5 or interval > 1440:
            raise ValueError("interval_minutes must be between 5 and 1440")
        current["interval_minutes"] = interval
        if current["notification_language"] not in {"zh-CN", "en", "ja"}:
            raise ValueError("notification_language must be zh-CN, en, or ja")
        recipients = current.get("email_recipients") or []
        if not isinstance(recipients, list) or any("@" not in str(item) for item in recipients):
            raise ValueError("email_recipients must be a list of email addresses")
        now = utc_now()
        with self.sessions.begin() as session:
            row = session.get(AppSetting, "news_sentiment")
            encoded = json.dumps(current, ensure_ascii=False)
            if row is None:
                session.add(AppSetting(key="news_sentiment", value_json=encoded, updated_at=now))
            else:
                row.value_json = encoded
                row.updated_at = now
        return self.settings(smtp_configured=smtp_configured)

    def universe(self, markets: list[str] | None = None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            query = select(Instrument).where(Instrument.status.in_(("active", "candidate")))
            if markets:
                query = query.where(Instrument.market.in_(markets))
            instruments = session.scalars(query.order_by(Instrument.symbol)).all()
            held = set(session.scalars(select(Position.symbol).where(Position.quantity > 0)).all())
            wanted = set(session.scalars(select(StockPreference.symbol).where(StockPreference.wanted.is_(True))).all())
        return [
            {
                "symbol": item.symbol, "name": item.name, "market": item.market,
                "priority": 0 if item.symbol in held else 1 if item.symbol in wanted else 2,
                "statuses": (["holding"] if item.symbol in held else []) + (["wanted"] if item.symbol in wanted else []),
            }
            for item in instruments
        ]

    def create_job(self, symbols: list[str], mode: str, markets: list[str] | None = None) -> dict[str, Any]:
        if mode not in {"incremental", "backfill"}:
            raise ValueError("mode must be incremental or backfill")
        normalized = list(dict.fromkeys(normalize_symbol(item) for item in symbols))
        if not normalized:
            raise ValueError("No sentiment symbols matched")
        now = utc_now()
        job = IngestionRun(
            id=uuid4().hex, source=f"news-{mode}", status="queued", requested_symbols=normalized,
            imported_symbols=[], records_received=0, records_written=0, attempts=0, max_attempts=3,
            request_payload={"kind": "news", "mode": mode, "markets": markets or []}, errors=[],
            notes="News sentiment ingestion", created_at=now, updated_at=now,
        )
        with self.sessions.begin() as session:
            active = session.scalar(select(func.count()).select_from(IngestionRun).where(
                IngestionRun.source.like("news-%"), IngestionRun.status.in_(("queued", "running", "retrying")),
            )) or 0
            if active:
                raise ValueError("A news sentiment job is already active")
            session.add(job)
        return self.job(job.id)

    def job(self, job_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(IngestionRun, job_id)
            if row is None or not row.source.startswith("news-"):
                raise ValueError("sentiment job not found")
            return self._job(row)

    def pending_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        stale_before = utc_now() - timedelta(minutes=15)
        with self.sessions.begin() as session:
            stale = session.scalars(select(IngestionRun).where(
                IngestionRun.source.like("news-%"), IngestionRun.status == "running",
                IngestionRun.updated_at < stale_before,
            )).all()
            for row in stale:
                row.status = "retrying"
                row.notes = "Recovered after an interrupted worker"
                row.updated_at = utc_now()
        with self.sessions() as session:
            rows = session.scalars(select(IngestionRun).where(
                IngestionRun.source.like("news-%"), IngestionRun.status.in_(("queued", "retrying")),
            ).order_by(IngestionRun.created_at).limit(limit)).all()
            return [self._job(row) for row in rows]

    def latest_completed_job(self) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.scalar(select(IngestionRun).where(
                IngestionRun.source == "news-incremental", IngestionRun.status.in_(("completed", "partial")),
            ).order_by(IngestionRun.finished_at.desc()).limit(1))
            return self._job(row) if row else None

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"status", "imported_symbols", "records_received", "records_written", "attempts", "errors", "started_at", "finished_at", "notes"}
        now = utc_now()
        with self.sessions.begin() as session:
            row = session.get(IngestionRun, job_id)
            if row is None:
                raise ValueError("sentiment job not found")
            for key, value in changes.items():
                if key not in allowed:
                    raise ValueError(f"Unsupported job field: {key}")
                setattr(row, key, value)
            row.updated_at = now
        return self.job(job_id)

    @contextmanager
    def worker_lock(self) -> Iterator[bool]:
        if self.engine.dialect.name != "postgresql":
            yield True
            return
        with self.engine.connect() as connection:
            acquired = bool(connection.execute(text("SELECT pg_try_advisory_lock(72190303)")).scalar())
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(72190303)"))

    def alpha_requests_today(self) -> int:
        key = f"news_provider_usage:{datetime.now(timezone.utc).date().isoformat()}"
        with self.sessions() as session:
            row = session.get(AppSetting, key)
            if row is None:
                return 0
            try:
                return int(json.loads(row.value_json).get("alpha_vantage", 0))
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                return 0

    def record_alpha_request(self) -> int:
        key = f"news_provider_usage:{datetime.now(timezone.utc).date().isoformat()}"
        now = utc_now()
        with self.sessions.begin() as session:
            row = session.get(AppSetting, key)
            count = 0
            if row:
                try:
                    count = int(json.loads(row.value_json).get("alpha_vantage", 0))
                except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                    count = 0
            value = json.dumps({"alpha_vantage": count + 1})
            if row is None:
                session.add(AppSetting(key=key, value_json=value, updated_at=now))
            else:
                row.value_json = value
                row.updated_at = now
        return count + 1

    def upsert_article(self, article: dict[str, Any]) -> tuple[int, list[int]]:
        now = utc_now()
        relation_ids: list[int] = []
        with self.sessions.begin() as session:
            row = session.scalar(select(NewsItem).where(NewsItem.content_hash == article["content_hash"]))
            if row is None:
                row = NewsItem(
                    id=article["id"], symbol=None, title=article["title"], url=article.get("url"), source=article["source"],
                    published_at=article["published_at"], fetched_at=now, content=None, sentiment_score=None,
                    payload=article.get("payload"), provider=article["provider"], provider_item_id=article.get("provider_item_id"),
                    canonical_url=article.get("canonical_url"), summary=article.get("summary"), source_domain=article.get("source_domain"),
                    source_tier=article.get("source_tier", "secondary"), language=article.get("language"),
                    content_hash=article["content_hash"], first_fetched_at=now,
                )
                session.add(row)
                session.flush()
            else:
                row.fetched_at = now
                if not row.summary and article.get("summary"):
                    row.summary = article["summary"]
            for item in article.get("symbols") or []:
                symbol = normalize_symbol(item["symbol"])
                relation = session.scalar(select(NewsItemInstrument).where(
                    NewsItemInstrument.news_item_id == row.id, NewsItemInstrument.symbol == symbol,
                ))
                if relation is None:
                    relation = NewsItemInstrument(
                        news_item_id=row.id, symbol=symbol, relevance_score=float(item.get("relevance_score") or 0),
                        provider_sentiment_score=item.get("provider_sentiment_score"), analysis_status="pending",
                        created_at=now, updated_at=now,
                    )
                    session.add(relation)
                    session.flush()
                else:
                    relation.relevance_score = max(relation.relevance_score, float(item.get("relevance_score") or 0))
                    if item.get("provider_sentiment_score") is not None:
                        relation.provider_sentiment_score = float(item["provider_sentiment_score"])
                    relation.updated_at = now
                relation_ids.append(relation.id)
        return 1, relation_ids

    def pending_relations(self, limit: int = 20, ids: list[int] | None = None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            query = select(NewsItemInstrument, NewsItem, Instrument).join(
                NewsItem, NewsItem.id == NewsItemInstrument.news_item_id,
            ).join(Instrument, Instrument.symbol == NewsItemInstrument.symbol).where(
                NewsItemInstrument.analysis_status == "pending",
            )
            if ids:
                query = query.where(NewsItemInstrument.id.in_(ids))
            rows = session.execute(query.order_by(NewsItem.published_at.desc()).limit(limit)).all()
            return [{
                "id": relation.id, "symbol": relation.symbol, "relevance_score": relation.relevance_score,
                "provider_sentiment_score": relation.provider_sentiment_score,
                "title": article.title, "summary": article.summary, "source": article.source,
                "source_tier": article.source_tier, "language": article.language, "name": instrument.name,
            } for relation, article, instrument in rows]

    def save_analysis(self, relation_id: int, result: dict[str, Any]) -> None:
        allowed = {
            "analysis_status", "sentiment_label", "sentiment_score", "positive_probability", "neutral_probability",
            "negative_probability", "relevance_score", "event_type", "impact_direction", "explanation", "classifier",
            "classifier_version", "prompt_version", "analyzed_at",
        }
        with self.sessions.begin() as session:
            row = session.get(NewsItemInstrument, relation_id)
            if row is None:
                return
            for key, value in result.items():
                if key in allowed:
                    setattr(row, key, value)
            row.updated_at = utc_now()

    def update_coverage(self, provider: str, symbol: str, start: datetime, end: datetime, count: int, error: str | None = None) -> None:
        now = utc_now()
        with self.sessions.begin() as session:
            row = session.scalar(select(NewsCoverage).where(NewsCoverage.provider == provider, NewsCoverage.symbol == symbol))
            if row is None:
                row = NewsCoverage(provider=provider, symbol=symbol, article_count=0, status="unknown", gaps=[], updated_at=now)
                session.add(row)
            row.coverage_start = min(filter(None, [_aware(row.coverage_start), start]), default=start)
            row.coverage_end = max(filter(None, [_aware(row.coverage_end), end]), default=end)
            row.article_count += count
            row.status = "partial" if error else "ok"
            row.last_error = error
            row.last_fetched_at = now
            row.updated_at = now

    def recompute_features(self, symbols: list[str], *, rebuild_history: bool = False) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        now = utc_now()
        for symbol in set(symbols):
            normalized = normalize_symbol(symbol)
            with self.sessions() as session:
                instrument = session.get(Instrument, normalized)
                market = instrument.market if instrument and instrument.market in MARKET_CLOCKS else "US"
                rows = session.execute(select(NewsItemInstrument, NewsItem).join(
                    NewsItem, NewsItem.id == NewsItemInstrument.news_item_id,
                ).where(
                    NewsItemInstrument.symbol == normalized,
                    NewsItemInstrument.analysis_status == "analyzed",
                    NewsItem.published_at >= now - timedelta(days=731),
                    NewsItem.published_at <= now,
                ).order_by(NewsItem.published_at)).all()
            current_trade_day = news_trade_date(now, market)
            trade_days = {current_trade_day}
            if rebuild_history:
                trade_days.update(news_trade_date(article.published_at, market) for _, article in rows)
            for trade_day in sorted(trade_days):
                as_of = min(_market_close_utc(trade_day, market), now)
                snapshot = self._snapshot_from_rows(normalized, rows, as_of)
                values = {
                    "score_1d": snapshot["score_1d"], "score_3d": snapshot["score_3d"], "score_7d": snapshot["score_7d"],
                    "negative_share": snapshot["negative_share"], "dispersion": snapshot["dispersion"],
                    "news_count": snapshot["news_count"], "source_count": snapshot["source_count"],
                    "score_change_7d": snapshot["score_change_7d"], "negative_shock": snapshot["negative_shock"],
                    "calculated_at": now,
                }
                with self.sessions.begin() as session:
                    row = session.scalar(select(SentimentDailyFeature).where(
                        SentimentDailyFeature.symbol == normalized,
                        SentimentDailyFeature.trade_date == trade_day,
                        SentimentDailyFeature.version == "sentiment-v1",
                    ))
                    if row is None:
                        session.add(SentimentDailyFeature(symbol=normalized, trade_date=trade_day, version="sentiment-v1", **values))
                    else:
                        for key, value in values.items():
                            setattr(row, key, value)
            results[normalized] = self._snapshot_from_rows(normalized, rows, now)
        return results

    def snapshot(self, symbol: str, hours: int = 24 * 7) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        now = utc_now()
        with self.sessions() as session:
            rows = session.execute(select(NewsItemInstrument, NewsItem).join(
                NewsItem, NewsItem.id == NewsItemInstrument.news_item_id,
            ).where(
                NewsItemInstrument.symbol == normalized,
                NewsItemInstrument.analysis_status == "analyzed",
                NewsItem.published_at >= now - timedelta(hours=hours),
            ).order_by(NewsItem.published_at.desc())).all()

        return self._snapshot_from_rows(normalized, rows, now)

    @staticmethod
    def _snapshot_from_rows(
        symbol: str,
        rows: list[tuple[NewsItemInstrument, NewsItem]],
        as_of: datetime,
    ) -> dict[str, Any]:
        known_rows = [
            (relation, article) for relation, article in rows
            if (_aware(article.published_at) or as_of) <= as_of
        ]

        def aggregate(window_hours: int) -> tuple[float | None, list[tuple[NewsItemInstrument, NewsItem]]]:
            selected = [
                (rel, article) for rel, article in known_rows
                if (_aware(article.published_at) or as_of) >= as_of - timedelta(hours=window_hours)
            ]
            weighted: list[tuple[float, float]] = []
            seen: set[str] = set()
            unique: list[tuple[NewsItemInstrument, NewsItem]] = []
            for relation, article in selected:
                cluster = article.content_hash or article.id
                if cluster in seen or relation.sentiment_score is None:
                    continue
                seen.add(cluster)
                unique.append((relation, article))
                age = max((as_of - (_aware(article.published_at) or as_of)).total_seconds() / 3600, 0)
                weight = max(relation.relevance_score, 0.05) * (1.0 if article.source_tier == "primary" else 0.7) * (0.5 ** (age / 24))
                weighted.append((float(relation.sentiment_score), weight))
            if not weighted:
                return None, unique
            return sum(score * weight for score, weight in weighted) / sum(weight for _, weight in weighted), unique

        score_1d, one_day = aggregate(24)
        score_3d, _ = aggregate(72)
        score_7d, seven_day = aggregate(168)
        scores = [float(rel.sentiment_score) for rel, _ in one_day if rel.sentiment_score is not None]
        severe = any(
            article.source_tier == "primary" and rel.relevance_score >= 0.8 and float(rel.sentiment_score or 0) <= -0.75
            for rel, article in one_day
        )
        six_hour_domains = {
            article.source_domain for rel, article in one_day
            if (_aware(article.published_at) or as_of) >= as_of - timedelta(hours=6) and article.source_domain
        }
        six_hour_score, _ = aggregate(6)
        shock = severe or (len(six_hour_domains) >= 2 and six_hour_score is not None and six_hour_score <= -0.45)
        return {
            "symbol": symbol, "score_1d": score_1d, "score_3d": score_3d, "score_7d": score_7d,
            "negative_share": (sum(score < 0 for score in scores) / len(scores)) if scores else None,
            "dispersion": pstdev(scores) if len(scores) > 1 else 0.0 if scores else None,
            "news_count": len(seven_day), "source_count": len({article.source_domain for _, article in seven_day if article.source_domain}),
            "score_change_7d": (score_1d - score_7d) if score_1d is not None and score_7d is not None else None,
            "negative_shock": shock, "six_hour_score": six_hour_score, "six_hour_source_count": len(six_hour_domains),
            "calculated_at": as_of.isoformat(), "version": "sentiment-v1",
        }

    def overview(self, filters: dict[str, Any]) -> dict[str, Any]:
        window = str(filters.get("window") or "24h")
        hours = {"24h": 24, "3d": 72, "7d": 168}.get(window)
        if hours is None:
            raise ValueError("window must be 24h, 3d, or 7d")
        market = str(filters.get("market") or "").upper()
        page = max(int(filters.get("page") or 1), 1)
        page_size = min(max(int(filters.get("page_size") or 30), 1), 100)
        cutoff = utc_now() - timedelta(hours=hours)
        with self.sessions() as session:
            query = select(NewsItemInstrument, NewsItem, Instrument).join(
                NewsItem, NewsItem.id == NewsItemInstrument.news_item_id,
            ).join(Instrument, Instrument.symbol == NewsItemInstrument.symbol).where(NewsItem.published_at >= cutoff)
            if market in {"US", "JP"}:
                query = query.where(Instrument.market == market)
            if filters.get("symbol"):
                query = query.where(NewsItemInstrument.symbol.ilike(f"%{str(filters['symbol']).strip()}%"))
            if filters.get("label"):
                query = query.where(NewsItemInstrument.sentiment_label == filters["label"])
            if filters.get("source_tier"):
                query = query.where(NewsItem.source_tier == filters["source_tier"])
            if filters.get("source"):
                query = query.where(NewsItem.source_domain.ilike(f"%{str(filters['source']).strip()}%"))
            if filters.get("event_type"):
                query = query.where(NewsItemInstrument.event_type == filters["event_type"])
            rows = session.execute(query.order_by(NewsItem.published_at.desc())).all()
        articles = [self._article(rel, article, instrument) for rel, article, instrument in rows]
        symbols = sorted({item["symbol"] for item in articles})
        snapshots = [self.snapshot(symbol, hours=hours) for symbol in symbols]
        score_key = {24: "score_1d", 72: "score_3d", 168: "score_7d"}[hours]
        scored = [float(item[score_key]) for item in snapshots if item[score_key] is not None]
        total = len(articles)
        start = (page - 1) * page_size
        coverage = self.coverage(symbols)
        with self.sessions() as session:
            trend_query = select(
                SentimentDailyFeature.trade_date,
                func.avg(SentimentDailyFeature.score_1d),
            ).join(Instrument, Instrument.symbol == SentimentDailyFeature.symbol).where(
                SentimentDailyFeature.trade_date >= date.today() - timedelta(days=30),
                SentimentDailyFeature.score_1d.is_not(None),
            )
            if market in {"US", "JP"}:
                trend_query = trend_query.where(Instrument.market == market)
            trend_rows = session.execute(trend_query.group_by(
                SentimentDailyFeature.trade_date,
            ).order_by(SentimentDailyFeature.trade_date)).all()
        return {
            "window": window, "market": market or "all",
            "summary": {
                "score": sum(scored) / len(scored) if scored else None,
                "positive": sum(item["sentiment_label"] == "positive" for item in articles),
                "neutral": sum(item["sentiment_label"] == "neutral" for item in articles),
                "negative": sum(item["sentiment_label"] == "negative" for item in articles),
                "articles": total, "symbols": len(symbols), "negative_shocks": sum(item["negative_shock"] for item in snapshots),
            },
            "symbols": sorted(snapshots, key=lambda item: (not item["negative_shock"], item[score_key] is None, item[score_key] or 0)),
            "articles": articles[start:start + page_size], "total": total, "page": page, "page_size": page_size,
            "pages": max(ceil(total / page_size), 1), "coverage": coverage, "generated_at": utc_now().isoformat(),
            "trend": [{"date": day.isoformat(), "score": float(value)} for day, value in trend_rows],
        }

    def stock_detail(self, symbol: str, window: str = "7d", page: int = 1, page_size: int = 30) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        hours = {"24h": 24, "3d": 72, "7d": 168}.get(window, 168)
        cutoff = utc_now() - timedelta(hours=hours)
        with self.sessions() as session:
            rows = session.execute(select(NewsItemInstrument, NewsItem, Instrument).join(
                NewsItem, NewsItem.id == NewsItemInstrument.news_item_id,
            ).join(Instrument, Instrument.symbol == NewsItemInstrument.symbol).where(
                NewsItemInstrument.symbol == normalized, NewsItem.published_at >= cutoff,
            ).order_by(NewsItem.published_at.desc())).all()
        articles = [self._article(rel, article, instrument) for rel, article, instrument in rows]
        start = (max(page, 1) - 1) * page_size
        return {
            "symbol": normalized, "window": window, "snapshot": self.snapshot(normalized, hours),
            "articles": articles[start:start + page_size], "total": len(articles),
            "coverage": self.coverage([normalized]), "generated_at": utc_now().isoformat(),
        }

    def coverage(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []
        with self.sessions() as session:
            rows = session.scalars(select(NewsCoverage).where(NewsCoverage.symbol.in_(symbols)).order_by(NewsCoverage.symbol, NewsCoverage.provider)).all()
            return [{
                "provider": row.provider, "symbol": row.symbol, "coverage_start": _iso(row.coverage_start),
                "coverage_end": _iso(row.coverage_end), "article_count": row.article_count, "status": row.status,
                "gaps": row.gaps or [], "last_error": row.last_error, "last_fetched_at": _iso(row.last_fetched_at),
            } for row in rows]

    def create_alert(self, symbol: str, snapshot: dict[str, Any], payload: dict[str, Any], recipient: str | None) -> dict[str, Any] | None:
        hours = int(self.settings().get("dedupe_hours") or 12)
        bucket = int(utc_now().timestamp() // (hours * 3600))
        cluster = sha256("|".join(sorted(str(item.get("url") or item.get("title")) for item in payload.get("articles", [])[:3])).encode("utf-8")).hexdigest()[:16]
        dedupe = f"{symbol}:{bucket}:{cluster}"
        now = utc_now()
        with self.sessions() as session:
            recent = session.scalars(select(SentimentAlert).where(
                SentimentAlert.symbol == symbol,
                SentimentAlert.created_at >= now - timedelta(hours=hours),
            )).all()
            if any(str(item.dedupe_key).endswith(cluster) for item in recent):
                return None
        alert_payload = dict(payload)
        alert_payload["email_attempts"] = 0
        row = SentimentAlert(
            id=uuid4().hex, symbol=symbol, dedupe_key=dedupe, alert_type="negative_shock",
            score=float(snapshot.get("six_hour_score") or snapshot.get("score_1d") or 0),
            source_count=int(snapshot.get("six_hour_source_count") or snapshot.get("source_count") or 0),
            status="pending", recipient=recipient, payload=alert_payload, created_at=now,
        )
        try:
            with self.sessions.begin() as session:
                session.add(row)
            return {"id": row.id, "dedupe_key": dedupe}
        except Exception:
            return None

    def update_alert(self, alert_id: str, status: str, error: str | None = None) -> None:
        with self.sessions.begin() as session:
            row = session.get(SentimentAlert, alert_id)
            if row:
                row.status = status
                row.error_message = error
                row.sent_at = utc_now() if status == "sent" else None
                payload = dict(row.payload or {})
                payload["email_attempts"] = int(payload.get("email_attempts") or 0) + 1
                row.payload = payload

    def retryable_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        cutoff = utc_now() - timedelta(hours=24)
        with self.sessions() as session:
            rows = session.scalars(select(SentimentAlert).where(
                SentimentAlert.status == "failed",
                SentimentAlert.created_at >= cutoff,
            ).order_by(SentimentAlert.created_at).limit(limit)).all()
            return [{
                "id": row.id,
                "symbol": row.symbol,
                "recipient": row.recipient,
                "payload": row.payload or {},
            } for row in rows if int((row.payload or {}).get("email_attempts") or 0) < 3]

    def recent_articles(self, symbol: str, hours: int = 6, limit: int = 5) -> list[dict[str, Any]]:
        return self.stock_detail(symbol, "24h", 1, limit)["articles"]

    @staticmethod
    def _article(relation: NewsItemInstrument, article: NewsItem, instrument: Instrument) -> dict[str, Any]:
        return {
            "id": article.id, "symbol": relation.symbol, "name": instrument.name, "market": instrument.market,
            "title": article.title, "summary": article.summary, "url": article.canonical_url or article.url,
            "source": article.source, "source_domain": article.source_domain, "source_tier": article.source_tier,
            "language": article.language, "published_at": _iso(article.published_at),
            "sentiment_label": relation.sentiment_label, "sentiment_score": relation.sentiment_score,
            "relevance_score": relation.relevance_score, "event_type": relation.event_type,
            "impact_direction": relation.impact_direction, "analysis_status": relation.analysis_status,
            "explanation": relation.explanation,
        }

    @staticmethod
    def _job(row: IngestionRun) -> dict[str, Any]:
        return {
            "id": row.id, "source": row.source, "status": row.status, "requested_symbols": row.requested_symbols or [],
            "imported_symbols": row.imported_symbols or [], "records_received": row.records_received,
            "records_written": row.records_written, "attempts": row.attempts, "max_attempts": row.max_attempts,
            "request_payload": row.request_payload or {}, "errors": row.errors or [], "notes": row.notes,
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at), "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
        }
