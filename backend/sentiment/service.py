from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any

from sentiment.classifier import StructuredSentimentClassifier
from sentiment.mailer import SmtpMailer
from sentiment.providers import AlphaVantageNewsProvider, GdeltNewsProvider, NewsProvider, utc_now
from sentiment.store import SentimentStore


TERMINAL_STATUSES = {"completed", "partial", "failed"}

MAIL_COPY = {
    "zh-CN": {
        "shock_subject": "[TradingAI] {symbol} 出现负面情绪突变",
        "shock_score": "过去 6 小时情绪分数",
        "sources": "独立来源数",
        "no_link": "无原文链接",
        "digest_subject": "[TradingAI] 每日市场情绪摘要",
        "market_score": "市场情绪分数",
        "articles": "新闻数量",
        "shocks": "负面突变",
    },
    "en": {
        "shock_subject": "[TradingAI] {symbol} negative sentiment shock",
        "shock_score": "Six-hour sentiment score",
        "sources": "Independent sources",
        "no_link": "no source link",
        "digest_subject": "[TradingAI] Daily market sentiment digest",
        "market_score": "Market score",
        "articles": "Articles",
        "shocks": "Negative shocks",
    },
    "ja": {
        "shock_subject": "[TradingAI] {symbol} ネガティブセンチメント急変",
        "shock_score": "過去6時間のセンチメントスコア",
        "sources": "独立した情報源数",
        "no_link": "元記事リンクなし",
        "digest_subject": "[TradingAI] 市場センチメント日次サマリー",
        "market_score": "市場センチメントスコア",
        "articles": "記事数",
        "shocks": "ネガティブ急変",
    },
}


def _mail_copy(language: str | None) -> dict[str, str]:
    normalized = str(language or "zh-CN")
    if normalized.lower().startswith("zh"):
        normalized = "zh-CN"
    elif normalized.lower().startswith("ja"):
        normalized = "ja"
    else:
        normalized = "en"
    return MAIL_COPY[normalized]


class NewsIngestionService:
    def __init__(
        self,
        store: SentimentStore,
        providers: list[NewsProvider] | None = None,
        classifier: StructuredSentimentClassifier | None = None,
        mailer: SmtpMailer | None = None,
        sleeper=sleep,
    ):
        self.store = store
        self.providers = providers or [GdeltNewsProvider(), AlphaVantageNewsProvider()]
        self.classifier = classifier or StructuredSentimentClassifier()
        self.mailer = mailer or SmtpMailer()
        self.sleeper = sleeper

    def enqueue(self, *, mode: str = "incremental", symbols: list[str] | None = None, markets: list[str] | None = None) -> dict[str, Any]:
        settings = self.store.settings(smtp_configured=self.mailer.configured)
        selected_markets = markets or settings["markets"]
        universe = self.store.universe(selected_markets)
        requested = symbols or [item["symbol"] for item in universe]
        return self.store.create_job(requested, mode, selected_markets)

    def run(self, job_id: str) -> dict[str, Any]:
        job = self.store.job(job_id)
        if job["status"] in TERMINAL_STATUSES:
            return job
        with self.store.worker_lock() as acquired:
            if not acquired:
                return self.store.update_job(job_id, status="retrying", notes="Another sentiment worker owns the database lock")
            return self._run_locked(job)

    def _run_locked(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = job["id"]
        now = utc_now()
        self.store.update_job(job_id, status="running", started_at=now, attempts=int(job["attempts"] or 0) + 1)
        settings = self.store.settings(smtp_configured=self.mailer.configured)
        universe_by_symbol = {item["symbol"]: item for item in self.store.universe(settings["markets"])}
        mode = str(job["request_payload"].get("mode") or "incremental")
        imported: list[str] = []
        errors: list[dict[str, Any]] = []
        received = 0
        written = 0
        relation_ids: list[int] = []
        alpha_used = self.store.alpha_requests_today()
        alpha_budget = int(settings["alpha_vantage_daily_budget"])

        ordered = sorted(job["requested_symbols"], key=lambda item: universe_by_symbol.get(item, {}).get("priority", 3))
        for symbol in ordered:
            instrument = universe_by_symbol.get(symbol, {"symbol": symbol, "name": symbol, "statuses": []})
            symbol_ok = False
            for provider in self.providers:
                if isinstance(provider, AlphaVantageNewsProvider) and (not provider.configured or alpha_used >= alpha_budget):
                    continue
                windows = self._windows(mode, provider.name, now)
                for start, end in windows:
                    if isinstance(provider, AlphaVantageNewsProvider):
                        if alpha_used >= alpha_budget:
                            break
                    try:
                        articles = self._fetch_with_retry(
                            provider, symbol, instrument.get("name"), start, end,
                            int(settings["max_articles_per_symbol"]),
                            request_budget=alpha_budget if isinstance(provider, AlphaVantageNewsProvider) else None,
                        )
                        alpha_used = self.store.alpha_requests_today()
                        received += len(articles)
                        provider_written = 0
                        for article in articles:
                            normalized = article.normalized(set(settings["primary_domains"]))
                            count, ids = self.store.upsert_article(normalized)
                            provider_written += count
                            relation_ids.extend(ids)
                        written += provider_written
                        self.store.update_coverage(provider.name, symbol, start, end, provider_written)
                        symbol_ok = True
                    except Exception as err:  # noqa: BLE001 - persisted provider failure
                        message = str(err)
                        errors.append({"symbol": symbol, "provider": provider.name, "error": message})
                        self.store.update_coverage(provider.name, symbol, start, end, 0, message)
                        if "quota" in message.lower() or "limit" in message.lower():
                            break
            if symbol_ok:
                imported.append(symbol)

        self._analyze_pending(relation_ids)
        snapshots = self.store.recompute_features(imported, rebuild_history=mode == "backfill")
        for symbol, snapshot in snapshots.items():
            instrument = universe_by_symbol.get(symbol, {})
            if snapshot["negative_shock"] and set(instrument.get("statuses") or []) & set(settings["alert_statuses"]):
                self._send_shock_alert(symbol, snapshot, settings)

        status = "completed" if not errors else "partial" if imported else "failed"
        return self.store.update_job(
            job_id, status=status, imported_symbols=sorted(set(imported)), records_received=received,
            records_written=written, errors=errors, finished_at=utc_now(),
        )

    def _fetch_with_retry(
        self, provider: NewsProvider, symbol: str, name: str | None,
        start: datetime, end: datetime, limit: int, request_budget: int | None = None,
    ):
        error: Exception | None = None
        for attempt, wait_seconds in enumerate((0, 30, 120, 600), start=1):
            if wait_seconds:
                self.sleeper(wait_seconds)
            if request_budget is not None:
                if self.store.alpha_requests_today() >= request_budget:
                    raise RuntimeError("Alpha Vantage daily request budget exhausted; remaining work is deferred")
                self.store.record_alpha_request()
            try:
                return provider.fetch(symbol, name, start, end, limit)
            except Exception as err:  # noqa: BLE001
                error = err
        raise RuntimeError(str(error or "news provider failed after 3 retries"))

    @staticmethod
    def _windows(mode: str, provider: str, now: datetime) -> list[tuple[datetime, datetime]]:
        if mode == "incremental":
            return [(now - timedelta(hours=6), now)]
        if provider == "gdelt":
            return [(now - timedelta(days=89), now)]
        windows: list[tuple[datetime, datetime]] = []
        cursor = now - timedelta(days=730)
        while cursor < now:
            end = min(cursor + timedelta(days=31), now)
            windows.append((cursor, end))
            cursor = end
        return windows

    def _analyze_pending(self, relation_ids: list[int] | None = None) -> None:
        for item in self.store.pending_relations(limit=20, ids=relation_ids or None):
            try:
                result = self.classifier.classify(item, item["symbol"], item.get("name"), item.get("provider_sentiment_score"))
            except Exception as err:  # noqa: BLE001
                result = {"analysis_status": "pending", "explanation": f"Classifier retry required: {err}"}
            self.store.save_analysis(item["id"], result)

    def _send_shock_alert(self, symbol: str, snapshot: dict[str, Any], settings: dict[str, Any]) -> None:
        articles = self.store.recent_articles(symbol, 6, 5)
        recipients = settings.get("email_recipients") or []
        alert = self.store.create_alert(symbol, snapshot, {"articles": articles, "snapshot": snapshot}, ",".join(recipients))
        if not alert or not settings.get("email_enabled"):
            return
        subject, body = self._alert_message(symbol, snapshot, articles, settings.get("notification_language"))
        try:
            self.mailer.send(recipients, subject, body)
            self.store.update_alert(alert["id"], "sent")
        except Exception as err:  # noqa: BLE001
            self.store.update_alert(alert["id"], "failed", str(err))

    def retry_failed_alerts(self) -> int:
        settings = self.store.settings(smtp_configured=self.mailer.configured)
        if not settings.get("email_enabled") or not self.mailer.configured:
            return 0
        sent = 0
        for alert in self.store.retryable_alerts():
            payload = alert["payload"]
            recipients = [item.strip() for item in str(alert.get("recipient") or "").split(",") if item.strip()]
            subject, body = self._alert_message(
                alert["symbol"], payload.get("snapshot") or {}, payload.get("articles") or [],
                settings.get("notification_language"),
            )
            try:
                self.mailer.send(recipients, subject, body)
                self.store.update_alert(alert["id"], "sent")
                sent += 1
            except Exception as err:  # noqa: BLE001
                self.store.update_alert(alert["id"], "failed", str(err))
        return sent

    @staticmethod
    def _alert_message(
        symbol: str, snapshot: dict[str, Any], articles: list[dict[str, Any]], language: str | None,
    ) -> tuple[str, str]:
        copy = _mail_copy(language)
        links = "\n".join(f"- {item['title']} ({item.get('url') or copy['no_link']})" for item in articles)
        subject = copy["shock_subject"].format(symbol=symbol)
        body = (
            f"{symbol}\n{copy['shock_score']}: {snapshot.get('six_hour_score')}\n"
            f"{copy['sources']}: {snapshot.get('six_hour_source_count')}\n\n{links}"
        )
        return subject, body

    def send_daily_digest(self) -> bool:
        settings = self.store.settings(smtp_configured=self.mailer.configured)
        today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        if not settings.get("email_enabled") or settings.get("last_digest_date") == today:
            return False
        overview = self.store.overview({"window": "24h", "page_size": 10})
        recipients = settings.get("email_recipients") or []
        copy = _mail_copy(settings.get("notification_language"))
        lines = [
            f"{copy['market_score']}: {overview['summary']['score']}",
            f"{copy['articles']}: {overview['summary']['articles']}",
            f"{copy['shocks']}: {overview['summary']['negative_shocks']}",
            "",
        ]
        lines.extend(f"- {item['symbol']}: {item.get('score_1d')}" for item in overview["symbols"][:10])
        self.mailer.send(recipients, copy["digest_subject"], "\n".join(lines))
        self.store.update_settings({"last_digest_date": today}, smtp_configured=self.mailer.configured)
        return True

    def shadow(self, symbol: str, quant_forecast: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = self.store.snapshot(symbol)
        baseline = (quant_forecast or {}).get("forecasts") or []
        if snapshot["score_1d"] is None:
            return {
                "status": "insufficient_data", "model_id": "sentiment-factor-shadow-v1",
                "production_eligible": False, "features": snapshot, "forecasts": [],
            }
        composite = (
            0.6 * float(snapshot["score_1d"] or 0)
            + 0.3 * float(snapshot["score_3d"] or 0)
            + 0.1 * float(snapshot["score_7d"] or 0)
        )
        forecasts = []
        for item in baseline:
            horizon = int(item["horizon_days"])
            adjustment = max(-2.0, min(2.0, composite * (0.75 if horizon <= 5 else 1.25)))
            forecasts.append({
                "horizon_days": horizon, "baseline_excess_return_pct": item["excess_return_pct"],
                "sentiment_adjustment_pct": adjustment,
                "shadow_excess_return_pct": float(item["excess_return_pct"]) + adjustment,
            })
        return {
            "status": "shadow", "model_id": "sentiment-factor-shadow-v1", "production_eligible": False,
            "method": "unvalidated_factor_overlay", "features": snapshot, "forecasts": forecasts,
            "activation_gate": {"min_live_weeks": 4, "rank_ic_lift": 0.01, "sharpe_lift": 0.10, "max_drawdown_worsening_pct": 2.0},
        }
