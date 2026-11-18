from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import uuid4
import re

from sqlalchemy import case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import aliased
from database.models import DocumentEmbedding, NewsItem, NewsItemInstrument, ResearchDocument
from market_data.point_in_time import aware
from .documents import snapshot_news, snapshot_analysis
from .embeddings import OpenAIEmbedder, validate_vector


class RetrievalStore:
    def __init__(self, sessions, embedder=None):
        self.sessions = sessions
        self.embedder = embedder or OpenAIEmbedder()

    def sync(self, limit=500):
        """Bootstrap previously stored articles at NOW, preserving uncertain availability."""
        count = 0
        with self.sessions.begin() as session:
            query = select(NewsItem).where(~select(ResearchDocument.id).where(
                ResearchDocument.article_id == NewsItem.id).exists()).order_by(NewsItem.id).limit(limit)
            for article in session.scalars(query.with_for_update(skip_locked=True)):
                now = datetime.now(timezone.utc)
                snapshot_news(session, article, now)
                for relation in session.scalars(select(NewsItemInstrument).where(NewsItemInstrument.news_item_id == article.id)):
                    snapshot_analysis(session, relation, article, now)
                count += 1
        return count

    def enqueue(self, limit=500):
        count = 0
        with self.sessions.begin() as session:
            missing = ~select(DocumentEmbedding.id).where(DocumentEmbedding.document_id == ResearchDocument.id,
                                                          DocumentEmbedding.model == self.embedder.version).exists()
            rows = session.scalars(select(ResearchDocument).where(missing).order_by(ResearchDocument.available_at)
                                   .limit(limit).with_for_update(skip_locked=True))
            for doc in rows:
                session.add(DocumentEmbedding(id=uuid4().hex, document_id=doc.id, model=self.embedder.version,
                    status="pending", attempts=0, retry_at=datetime.now(timezone.utc), token_count=0))
                count += 1
        return count

    def process(self, limit=20):
        # A bounded provider call holds a row lock. Crashes roll back; other workers skip it.
        report = {"ready": 0, "failed": 0, "tokens": 0}
        for _ in range(limit):
            with self.sessions.begin() as session:
                job = session.scalar(select(DocumentEmbedding).where(DocumentEmbedding.model == self.embedder.version,
                    DocumentEmbedding.status.in_(["pending", "retry"]), DocumentEmbedding.attempts < 5,
                    DocumentEmbedding.retry_at <= datetime.now(timezone.utc))
                    .order_by(DocumentEmbedding.retry_at, DocumentEmbedding.id).limit(1).with_for_update(skip_locked=True))
                if job is None:
                    break
                job.attempts += 1
                try:
                    document = session.get(ResearchDocument, job.document_id)
                    vectors, tokens = self.embedder.embed([document.body])
                    job.vector = validate_vector(vectors[0])
                    job.status, job.error = "ready", None
                    job.completed_at = datetime.now(timezone.utc)
                    job.token_count = tokens
                    report["ready"] += 1
                    report["tokens"] += tokens
                except Exception as error:
                    job.status = "failed" if job.attempts >= 5 else "retry"
                    job.error = type(error).__name__  # Provider errors can contain credentials/URLs.
                    job.retry_at = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 30 * 2 ** job.attempts))
                    report["failed"] += 1
        return report

    def retry_failed(self):
        with self.sessions.begin() as session:
            from sqlalchemy import update
            return session.execute(update(DocumentEmbedding).where(DocumentEmbedding.model == self.embedder.version,
                DocumentEmbedding.status == "failed").values(status="pending", attempts=0,
                error=None, retry_at=datetime.now(timezone.utc))).rowcount

    def status(self):
        with self.sessions() as session:
            return {"model": self.embedder.version, "dimensions": 1536,
                "documents": session.scalar(select(func.count()).select_from(ResearchDocument)),
                "jobs": dict(session.execute(select(DocumentEmbedding.status, func.count()).where(
                    DocumentEmbedding.model == self.embedder.version).group_by(DocumentEmbedding.status)).all()),
                "tokens": session.scalar(select(func.coalesce(func.sum(DocumentEmbedding.token_count), 0)).where(
                    DocumentEmbedding.model == self.embedder.version))}

    def search(self, query, *, symbol=None, as_of=None, mode="hybrid", limit=8):
        started = perf_counter()
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ValueError("query must contain 1 to 1000 characters")
        if mode not in {"keyword", "vector", "hybrid"} or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ValueError("invalid mode or limit")
        cutoff = aware(as_of) if as_of else datetime.now(timezone.utc)
        if cutoff > datetime.now(timezone.utc):
            raise ValueError("as_of cannot be in the future")
        symbol = symbol.strip().upper() if symbol else None
        if symbol and not re.fullmatch(r"[A-Z0-9.^=-]{1,32}", symbol):
            raise ValueError("invalid symbol")
        newer = aliased(ResearchDocument)
        filters = [ResearchDocument.available_at <= cutoff, ResearchDocument.published_at <= cutoff,
            ~select(newer.id).where(newer.article_id == ResearchDocument.article_id,
                newer.revision > ResearchDocument.revision, newer.available_at <= cutoff).exists()]
        query_tokens = 0
        with self.sessions() as session:
            if session.bind.dialect.name != "postgresql":
                raise RuntimeError("research retrieval requires PostgreSQL + pgvector")
            if symbol:
                filters.append(cast(ResearchDocument.symbols, JSONB).contains([symbol]))
            lists, documents, distances = [], {}, {}
            if mode in {"keyword", "hybrid"}:
                terms = list(dict.fromkeys(re.findall(r"\w+", query.lower())))[:24]
                matches = [func.lower(ResearchDocument.body).contains(term, autoescape=True) for term in terms]
                if matches:
                    score = sum(case((match, 1), else_=0) for match in matches)
                    rows = session.scalars(select(ResearchDocument).where(*filters, or_(*matches))
                        .order_by(score.desc(), ResearchDocument.id).limit(50)).all()
                    lists.append([row.id for row in rows])
                    documents.update({row.id: row for row in rows})
            if mode in {"vector", "hybrid"}:
                vector, query_tokens = self.embedder.embed([query])
                distance = DocumentEmbedding.vector.cosine_distance(validate_vector(vector[0]))
                rows = session.execute(select(ResearchDocument, distance.label("distance"))
                    .join(DocumentEmbedding, DocumentEmbedding.document_id == ResearchDocument.id)
                    .where(*filters, DocumentEmbedding.model == self.embedder.version,
                        DocumentEmbedding.status == "ready", DocumentEmbedding.completed_at <= cutoff,
                        distance <= .8).order_by(distance, ResearchDocument.id).limit(50)).all()
                lists.append([row.id for row, _ in rows])
                documents.update({row.id: row for row, _ in rows})
                distances.update({row.id: float(d) for row, d in rows})
            scores = {}
            for ids in lists:
                for rank, item in enumerate(ids, 1):
                    scores[item] = scores.get(item, 0) + 1 / (60 + rank)
            selected = sorted(scores, key=lambda item: (-scores[item], item))[:limit]
            items = [{"id": key, "article_id": documents[key].article_id, "revision": documents[key].revision,
                "title": documents[key].title, "text": documents[key].body[:6000], "url": documents[key].url,
                "source": documents[key].source, "symbols": documents[key].symbols,
                "available_at": documents[key].available_at.isoformat(), "score": scores[key],
                "cosine_distance": distances.get(key)} for key in selected]
        return {"query": query, "symbol": symbol, "as_of": cutoff.isoformat(), "mode": mode,
            "embedding_model": self.embedder.version, "items": items, "query_tokens": query_tokens,
            "elapsed_ms": round((perf_counter()-started)*1000, 2)}
