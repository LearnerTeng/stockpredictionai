from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any


PROMPT_VERSION = "financial-news-sentiment-v1"
EVENT_TYPES = ["earnings", "guidance", "merger_acquisition", "regulatory", "macro", "product", "management", "legal", "analyst", "other"]


class StructuredSentimentClassifier:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5-mini")

    def classify(self, article: dict[str, Any], symbol: str, company_name: str | None, provider_score: float | None) -> dict[str, Any]:
        if provider_score is not None:
            score = max(-1.0, min(1.0, float(provider_score)))
            positive = max(score, 0.0)
            negative = max(-score, 0.0)
            neutral = max(0.0, 1.0 - positive - negative)
            return self._result(positive, neutral, negative, float(article.get("relevance_score") or 0), "other", "up" if score > 0.05 else "down" if score < -0.05 else "neutral", "Provider stock-level sentiment", "provider")
        if not self.api_key:
            return {"analysis_status": "pending", "classifier": None, "prompt_version": PROMPT_VERSION}

        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        prompt = (
            "Classify this financial news only for its likely short-term impact on the named stock. "
            "Do not infer facts absent from the headline or summary. Return calibrated probabilities.\n"
            f"Symbol: {symbol}\nCompany: {company_name or symbol}\nSource: {article.get('source')}\n"
            f"Headline: {article.get('title')}\nSummary: {article.get('summary') or ''}"
        )
        response = client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": prompt}],
            text={"format": {"type": "json_schema", "name": "news_sentiment", "strict": True, "schema": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "positive": {"type": "number", "minimum": 0, "maximum": 1},
                    "neutral": {"type": "number", "minimum": 0, "maximum": 1},
                    "negative": {"type": "number", "minimum": 0, "maximum": 1},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                    "event_type": {"type": "string", "enum": EVENT_TYPES},
                    "impact_direction": {"type": "string", "enum": ["up", "down", "neutral"]},
                    "explanation": {"type": "string", "maxLength": 240},
                },
                "required": ["positive", "neutral", "negative", "relevance", "event_type", "impact_direction", "explanation"],
            }}}, max_output_tokens=350,
        )
        data = json.loads(response.output_text)
        total = max(float(data["positive"]) + float(data["neutral"]) + float(data["negative"]), 1e-9)
        return self._result(
            float(data["positive"]) / total, float(data["neutral"]) / total, float(data["negative"]) / total,
            float(data["relevance"]), data["event_type"], data["impact_direction"], data["explanation"], self.model,
        )

    @staticmethod
    def _result(positive: float, neutral: float, negative: float, relevance: float, event_type: str, direction: str, explanation: str, classifier: str) -> dict[str, Any]:
        score = positive - negative
        label = "positive" if positive >= max(neutral, negative) else "negative" if negative >= max(positive, neutral) else "neutral"
        return {
            "analysis_status": "analyzed", "sentiment_label": label, "sentiment_score": score,
            "positive_probability": positive, "neutral_probability": neutral, "negative_probability": negative,
            "relevance_score": relevance, "event_type": event_type, "impact_direction": direction,
            "explanation": explanation, "classifier": classifier, "classifier_version": classifier,
            "prompt_version": PROMPT_VERSION, "analyzed_at": datetime.now(timezone.utc),
        }
