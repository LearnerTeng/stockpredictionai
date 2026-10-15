from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
import re
from typing import Any, Protocol
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import requests


TRACKING_PARAMETERS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source",
}
PRIMARY_DOMAINS = {
    "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "ft.com",
    "marketwatch.com", "nikkei.com", "nhk.or.jp", "jiji.com", "47news.jp",
    "kyodonews.net",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return utc_now()
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return utc_now()


def canonicalize_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    query = [
        (key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def source_domain(url: str | None, fallback: str = "") -> str:
    host = urlsplit(url or "").netloc.lower().split(":")[0]
    return host.removeprefix("www.") or fallback.strip().lower()


def source_tier(domain: str, primary_domains: set[str] | None = None) -> str:
    allow = primary_domains or PRIMARY_DOMAINS
    return "primary" if any(domain == item or domain.endswith(f".{item}") for item in allow) else "secondary"


def content_hash(title: str, canonical_url: str | None, published_at: datetime) -> str:
    normalized_title = re.sub(r"\s+", " ", title.strip().lower())
    payload = f"{canonical_url or ''}|{normalized_title}|{published_at:%Y-%m-%dT%H}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderArticle:
    provider: str
    provider_item_id: str | None
    title: str
    url: str | None
    source: str
    published_at: datetime
    summary: str | None = None
    language: str | None = None
    symbols: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    def normalized(self, primary_domains: set[str] | None = None) -> dict[str, Any]:
        canonical = canonicalize_url(self.url)
        domain = source_domain(canonical, self.source)
        return {
            "id": content_hash(self.title, canonical, self.published_at)[:64],
            "provider": self.provider,
            "provider_item_id": self.provider_item_id,
            "title": self.title.strip(),
            "url": self.url,
            "canonical_url": canonical,
            "source": self.source.strip() or domain,
            "source_domain": domain,
            "source_tier": source_tier(domain, primary_domains),
            "published_at": self.published_at,
            "summary": (self.summary or "").strip() or None,
            "language": self.language,
            "content_hash": content_hash(self.title, canonical, self.published_at),
            "symbols": self.symbols,
            "payload": self.payload,
        }


class NewsProvider(Protocol):
    name: str

    def fetch(self, symbol: str, company_name: str | None, start: datetime, end: datetime, limit: int = 250) -> list[ProviderArticle]:
        ...


class JsonHttpClient:
    def get(self, url: str, timeout: int = 20) -> dict[str, Any]:
        response = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "TradingAI/1.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        return response.json()


class AlphaVantageNewsProvider:
    name = "alpha-vantage"

    def __init__(self, api_key: str | None = None, http: JsonHttpClient | None = None):
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
        self.http = http or JsonHttpClient()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def fetch(self, symbol: str, company_name: str | None, start: datetime, end: datetime, limit: int = 1000) -> list[ProviderArticle]:
        if not self.api_key:
            return []
        provider_symbol = symbol[:-2] if symbol.endswith(".T") else symbol
        params = {
            "function": "NEWS_SENTIMENT", "tickers": provider_symbol,
            "time_from": start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M"),
            "time_to": end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M"),
            "sort": "LATEST", "limit": str(min(max(limit, 1), 1000)), "apikey": self.api_key,
        }
        payload = self.http.get(f"https://www.alphavantage.co/query?{urlencode(params)}")
        if payload.get("Note") or payload.get("Information"):
            raise RuntimeError(str(payload.get("Note") or payload.get("Information")))
        articles: list[ProviderArticle] = []
        for item in payload.get("feed") or []:
            relations = []
            for relation in item.get("ticker_sentiment") or []:
                if str(relation.get("ticker", "")).upper() != provider_symbol.upper():
                    continue
                relations.append({
                    "symbol": symbol,
                    "relevance_score": float(relation.get("relevance_score") or 0),
                    "provider_sentiment_score": float(relation.get("ticker_sentiment_score") or 0),
                })
            if not relations:
                continue
            articles.append(ProviderArticle(
                provider=self.name,
                provider_item_id=str(item.get("url") or "") or None,
                title=str(item.get("title") or "").strip(),
                url=item.get("url"), source=str(item.get("source") or "Alpha Vantage"),
                published_at=parse_datetime(item.get("time_published")), summary=item.get("summary"),
                language="en", symbols=relations, payload=item,
            ))
        return [article for article in articles if article.title]


class GdeltNewsProvider:
    name = "gdelt"

    def __init__(self, http: JsonHttpClient | None = None):
        self.http = http or JsonHttpClient()

    def fetch(self, symbol: str, company_name: str | None, start: datetime, end: datetime, limit: int = 250) -> list[ProviderArticle]:
        plain_symbol = symbol.removesuffix(".T")
        terms = [f'"{company_name}"' if company_name else "", f'"{plain_symbol}"']
        query = " OR ".join(term for term in terms if term)
        params = {
            "query": query, "mode": "artlist", "format": "json",
            "maxrecords": str(min(max(limit, 1), 250)), "sort": "datedesc",
            "startdatetime": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
        }
        payload = self.http.get(f"https://api.gdeltproject.org/api/v2/doc/doc?{urlencode(params, quote_via=quote_plus)}")
        articles: list[ProviderArticle] = []
        for item in payload.get("articles") or []:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            articles.append(ProviderArticle(
                provider=self.name, provider_item_id=str(item.get("url") or "") or None,
                title=title, url=item.get("url"), source=str(item.get("domain") or "GDELT"),
                published_at=parse_datetime(item.get("seendate")),
                language=str(item.get("language") or "").lower() or None,
                symbols=[{"symbol": symbol, "relevance_score": 0.65, "provider_sentiment_score": None}],
                payload=item,
            ))
        return articles
