from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import ceil
from typing import Any

from market_data.store import MarketDataStore, infer_market, normalize_symbol
from trading.store import TradingStore


AI_RECOMMENDATION_THRESHOLD = 50.0
VALID_VIEWS = {"all", "wanted", "holding", "ai"}
VALID_DIRECTIONS = {"up", "down"}
VALID_FRESHNESS = {"24h", "3d", "7d", "stale"}
SORT_FIELDS = {
    "symbol",
    "latest_price",
    "day_change_pct",
    "ai_score",
    "projected_return_pct",
    "market_value",
    "holding_pnl_pct",
    "updated_at",
}


class MonitorService:
    def __init__(self, market_store: MarketDataStore, trading_store: TradingStore):
        self.market_store = market_store
        self.trading_store = trading_store

    def query(self, filters: dict[str, Any] | None = None, *, paginate: bool = True) -> dict[str, Any]:
        normalized = self._normalize_filters(filters or {})
        all_items = self._build_items()
        facets = self._build_facets(all_items)
        items = [item for item in all_items if self._matches(item, normalized)]
        self._sort(items, normalized)

        total = len(items)
        page = normalized["page"]
        page_size = normalized["page_size"]
        if paginate:
            start = (page - 1) * page_size
            items = items[start : start + page_size]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(ceil(total / page_size), 1) if paginate else 1,
            "facets": facets,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_mode": "demo-delayed",
        }

    def detail(self, symbol: str) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        item = next((candidate for candidate in self._build_items() if candidate["symbol"] == normalized), None)
        if item is None:
            raise ValueError("monitor stock not found")
        return item

    def matching_symbols(self, filters: dict[str, Any] | None = None) -> list[str]:
        result = self.query({**(filters or {}), "page": 1, "page_size": 2000}, paginate=False)
        return [item["symbol"] for item in result["items"]]

    def _build_items(self) -> list[dict[str, Any]]:
        snapshots = {item["symbol"]: item for item in self.market_store.list_symbol_snapshots()}
        recommendations = {item["symbol"]: item for item in self.trading_store.list_recommendations()}
        portfolio = self.trading_store.get_portfolio()
        positions = {item["symbol"]: item for item in portfolio["positions"]}
        wanted = self.trading_store.list_wanted_symbols()
        symbols = sorted(set(snapshots) | set(recommendations) | set(positions) | wanted)

        items: list[dict[str, Any]] = []
        for symbol in symbols:
            snapshot = snapshots.get(symbol) or {}
            recommendation = recommendations.get(symbol)
            position = positions.get(symbol)
            latest_price = snapshot.get("latest_price")
            if latest_price is None and recommendation is not None:
                latest_price = recommendation.get("latest_price")
            if latest_price is None and position is not None:
                latest_price = position.get("last_price")
            previous_close = snapshot.get("previous_close")
            day_change_pct = None
            if latest_price is not None and previous_close:
                day_change_pct = round((float(latest_price) / float(previous_close) - 1) * 100, 3)

            statuses: list[str] = []
            if position is not None and float(position.get("quantity") or 0) > 0:
                statuses.append("holding")
            if symbol in wanted:
                statuses.append("wanted")
            if recommendation is not None and float(recommendation.get("score") or 0) > AI_RECOMMENDATION_THRESHOLD:
                statuses.append("ai_suggested")
            if not statuses:
                statuses.append("monitoring")

            timestamps = [
                value
                for value in (
                    snapshot.get("last_refreshed_at"),
                    snapshot.get("updated_at"),
                    recommendation.get("updated_at") if recommendation else None,
                    position.get("updated_at") if position else None,
                )
                if value
            ]
            items.append(
                {
                    "symbol": symbol,
                    "name": snapshot.get("name")
                    or (recommendation.get("name") if recommendation else None)
                    or (position.get("name") if position else None)
                    or symbol,
                    "market": snapshot.get("market") or infer_market(symbol),
                    "exchange": snapshot.get("exchange"),
                    "sector": snapshot.get("sector"),
                    "statuses": statuses,
                    "wanted": symbol in wanted,
                    "latest_price": round(float(latest_price), 4) if latest_price is not None else None,
                    "day_change_pct": day_change_pct,
                    "ai_score": float(recommendation["score"]) if recommendation is not None else None,
                    "projected_return_pct": float(recommendation["projected_return_pct"])
                    if recommendation is not None
                    else None,
                    "holding": position,
                    "market_value": float(position["market_value"]) if position is not None else None,
                    "holding_pnl_pct": float(position["unrealized_pnl_pct"]) if position is not None else None,
                    "latest_trade_date": snapshot.get("latest_trade_date"),
                    "last_refreshed_at": snapshot.get("last_refreshed_at"),
                    "updated_at": max(timestamps) if timestamps else None,
                    "recommendation": recommendation,
                }
            )
        return items

    @staticmethod
    def _normalize_filters(filters: dict[str, Any]) -> dict[str, Any]:
        view = str(filters.get("view", "all") or "all").strip().lower()
        if view not in VALID_VIEWS:
            raise ValueError("view must be one of: all, wanted, holding, ai")
        market = str(filters.get("market", "") or "").strip().upper()
        if market and market not in {"US", "JP", "HK"}:
            raise ValueError("market must be one of: US, JP, HK")
        direction = str(filters.get("forecast_direction", "") or "").strip().lower()
        if direction and direction not in VALID_DIRECTIONS:
            raise ValueError("forecast_direction must be up or down")
        freshness = str(filters.get("freshness", "") or "").strip().lower()
        if freshness and freshness not in VALID_FRESHNESS:
            raise ValueError("freshness must be one of: 24h, 3d, 7d, stale")
        sort = str(filters.get("sort", "") or "").strip().lower()
        if not sort:
            sort = "ai_score" if view in {"ai", "wanted"} else "market_value" if view == "holding" else "updated_at"
        if sort not in SORT_FIELDS:
            raise ValueError(f"sort must be one of: {', '.join(sorted(SORT_FIELDS))}")
        order = str(filters.get("order", "desc") or "desc").strip().lower()
        if order not in {"asc", "desc"}:
            raise ValueError("order must be asc or desc")

        def optional_float(key: str) -> float | None:
            value = filters.get(key)
            if value in {None, ""}:
                return None
            try:
                return float(value)
            except (TypeError, ValueError) as err:
                raise ValueError(f"{key} must be a number") from err

        try:
            page = max(int(filters.get("page", 1) or 1), 1)
            page_size = min(max(int(filters.get("page_size", 50) or 50), 1), 2000)
        except (TypeError, ValueError) as err:
            raise ValueError("page and page_size must be integers") from err

        return {
            "q": str(filters.get("q", "") or "").strip().lower(),
            "view": view,
            "market": market,
            "sector": str(filters.get("sector", "") or "").strip().lower(),
            "exchange": str(filters.get("exchange", "") or "").strip().lower(),
            "price_min": optional_float("price_min"),
            "price_max": optional_float("price_max"),
            "score_min": optional_float("score_min"),
            "score_max": optional_float("score_max"),
            "forecast_direction": direction,
            "freshness": freshness,
            "sort": sort,
            "order": order,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    def _matches(item: dict[str, Any], filters: dict[str, Any]) -> bool:
        query = filters["q"]
        if query and query not in item["symbol"].lower() and query not in str(item["name"]).lower():
            return False
        if filters["market"] and item["market"] != filters["market"]:
            return False
        status_map = {"wanted": "wanted", "holding": "holding", "ai": "ai_suggested"}
        required_status = status_map.get(filters["view"])
        if required_status and required_status not in item["statuses"]:
            return False
        if filters["sector"] and filters["sector"] != str(item.get("sector") or "").lower():
            return False
        if filters["exchange"] and filters["exchange"] != str(item.get("exchange") or "").lower():
            return False
        for key, operator in (
            ("price_min", lambda value, bound: value >= bound),
            ("price_max", lambda value, bound: value <= bound),
            ("score_min", lambda value, bound: value >= bound),
            ("score_max", lambda value, bound: value <= bound),
        ):
            bound = filters[key]
            if bound is None:
                continue
            source_key = "latest_price" if key.startswith("price") else "ai_score"
            value = item.get(source_key)
            if value is None or not operator(float(value), bound):
                return False
        direction = filters["forecast_direction"]
        projected = item.get("projected_return_pct")
        if direction == "up" and (projected is None or projected <= 0):
            return False
        if direction == "down" and (projected is None or projected >= 0):
            return False
        if filters["freshness"] and not MonitorService._matches_freshness(item.get("last_refreshed_at"), filters["freshness"]):
            return False
        return True

    @staticmethod
    def _matches_freshness(value: str | None, freshness: str) -> bool:
        if not value:
            return freshness == "stale"
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except ValueError:
            return freshness == "stale"
        age_hours = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 3600
        if freshness == "24h":
            return age_hours <= 24
        if freshness == "3d":
            return age_hours <= 72
        if freshness == "7d":
            return age_hours <= 168
        return age_hours > 168

    @staticmethod
    def _sort(items: list[dict[str, Any]], filters: dict[str, Any]) -> None:
        field = filters["sort"]
        descending = filters["order"] == "desc"
        items.sort(key=lambda item: item["symbol"])
        present = [item for item in items if item.get(field) is not None]
        missing = [item for item in items if item.get(field) is None]
        present.sort(key=lambda item: item[field], reverse=descending)
        items[:] = present + missing

    @staticmethod
    def _build_facets(items: list[dict[str, Any]]) -> dict[str, Any]:
        market_counts = Counter(item["market"] for item in items)
        status_counts = Counter(status for item in items for status in item["statuses"])
        sectors = Counter(item["sector"] for item in items if item.get("sector"))
        exchanges = Counter(item["exchange"] for item in items if item.get("exchange"))
        return {
            "markets": dict(sorted(market_counts.items())),
            "statuses": {
                "all": len(items),
                "wanted": status_counts["wanted"],
                "holding": status_counts["holding"],
                "ai": status_counts["ai_suggested"],
            },
            "sectors": dict(sorted(sectors.items())),
            "exchanges": dict(sorted(exchanges.items())),
        }
