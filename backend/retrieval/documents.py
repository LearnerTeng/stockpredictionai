from datetime import datetime, timezone
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from database.models import NewsItemInstrument, ResearchDocument, SentimentObservation
from market_data.point_in_time import utc


def snapshot_news(session, article, now):
    """Caller owns the article lock/transaction. Never backdate a new snapshot."""
    session.flush()
    symbols = sorted(session.scalars(select(NewsItemInstrument.symbol).where(
        NewsItemInstrument.news_item_id == article.id)).all())
    payload = {"title": article.title, "body": article.title + "\n" + (article.summary or ""),
               "url": article.canonical_url or article.url, "source": article.source,
               "language": article.language, "symbols": symbols,
               "published_at": utc(article.published_at).isoformat()}
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = session.scalar(select(ResearchDocument).where(ResearchDocument.article_id == article.id)
                              .order_by(ResearchDocument.revision.desc()).limit(1))
    if previous and previous.checksum == digest:
        return previous
    row = ResearchDocument(id=uuid4().hex, article_id=article.id,
        revision=previous.revision+1 if previous else 1, checksum=digest,
        **{k: v for k, v in payload.items() if k != "published_at"},
        published_at=article.published_at, available_at=max(utc(now), utc(article.published_at)))
    session.add(row)
    session.flush()
    return row


def snapshot_analysis(session, relation, article, now):
    if relation.analysis_status != "analyzed" or relation.sentiment_score is None:
        return
    published = utc(article.published_at)
    first_seen = utc(article.first_fetched_at or article.fetched_at)
    analysis = {key: getattr(relation, key) for key in (
        "sentiment_score", "relevance_score", "event_type", "classifier", "classifier_version", "prompt_version")}
    analysis.update(analyzed_at=utc(relation.analyzed_at or now).isoformat(), created_at=utc(relation.created_at).isoformat())
    article_data = {key: getattr(article, key) for key in ("id", "content_hash", "source_tier", "source_domain")}
    article_data.update(published_at=published.isoformat(), first_fetched_at=first_seen.isoformat())
    session.add(SentimentObservation(id=uuid4().hex, relation_id=relation.id, symbol=relation.symbol,
        available_at=max(utc(now), published, first_seen, utc(relation.analyzed_at or now)),
        article_json=article_data, analysis_json=analysis))


def sentiment_rows_as_of(sessions, symbol, cutoff):
    with sessions() as session:
        rows = session.scalars(select(SentimentObservation).where(
            SentimentObservation.symbol == symbol, SentimentObservation.available_at <= cutoff)
            .order_by(SentimentObservation.available_at, SentimentObservation.id)).all()
        latest = {r.relation_id: r for r in rows}
        return [(SimpleNamespace(**r.analysis_json), SimpleNamespace(**r.article_json)) for r in latest.values()]
