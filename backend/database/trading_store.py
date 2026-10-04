from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from trading.policy import parse_order, same_request, reference_price, evaluate_order, validate_confirmation, record_event

from trading.store import DEFAULT_PORTFOLIO_ID, normalize_symbol
from .models import AppSetting, PaperOrder, PerformancePoint, Portfolio, Position, Recommendation, StockPreference
from .session import create_database_engine, session_factory


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class SqlAlchemyTradingStore:
    """PostgreSQL implementation of the existing paper-trading contract."""

    def __init__(self, database_url: str):
        self.engine = create_database_engine(database_url)
        self.sessions = session_factory(self.engine)
        self.db_path = database_url.split("@")[-1]

    def init_schema(self) -> None:
        return None

    def list_portfolios(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(select(Portfolio).order_by(Portfolio.name, Portfolio.id)).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "mode": row.mode,
                    "currency": row.currency,
                    "account_type": row.account_type,
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows
            ]

    def list_recommendations(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(select(Recommendation).order_by(Recommendation.score.desc(), Recommendation.symbol)).all()
            return [self._recommendation(row) for row in rows]

    def get_recommendation_or_none(self, symbol: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(Recommendation, normalize_symbol(symbol))
            return self._recommendation(row) if row is not None else None

    def get_recommendation(self, symbol: str) -> dict[str, Any]:
        item = self.get_recommendation_or_none(symbol)
        if item is None:
            raise ValueError("recommendation not found")
        return item

    def list_wanted_symbols(self) -> set[str]:
        with self.sessions() as session:
            return set(session.scalars(select(StockPreference.symbol).where(StockPreference.wanted.is_(True))).all())

    def set_wanted(self, symbol: str, wanted: bool) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        now = _now()
        with self.sessions.begin() as session:
            row = session.get(StockPreference, normalized)
            if row is None:
                session.add(StockPreference(symbol=normalized, wanted=wanted, created_at=now, updated_at=now))
            else:
                row.wanted = wanted
                row.updated_at = now
        return {"symbol": normalized, "wanted": wanted, "updated_at": now.isoformat()}

    def get_monitor_settings(self) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(AppSetting, "monitor")
            if row is None:
                return {"auto_refresh_enabled": False, "interval_minutes": 15, "updated_at": None}
            try:
                value = json.loads(row.value_json)
            except (TypeError, json.JSONDecodeError):
                value = {}
            return {
                "auto_refresh_enabled": bool(value.get("auto_refresh_enabled", False)),
                "interval_minutes": int(value.get("interval_minutes", 15)),
                "updated_at": _iso(row.updated_at),
            }

    def update_monitor_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get_monitor_settings()
        enabled = bool(payload.get("auto_refresh_enabled", current["auto_refresh_enabled"]))
        try:
            interval = int(payload.get("interval_minutes", current["interval_minutes"]))
        except (TypeError, ValueError) as err:
            raise ValueError("interval_minutes must be an integer") from err
        if interval < 1 or interval > 1440:
            raise ValueError("interval_minutes must be between 1 and 1440")
        now = _now()
        value = {"auto_refresh_enabled": enabled, "interval_minutes": interval}
        with self.sessions.begin() as session:
            row = session.get(AppSetting, "monitor")
            if row is None:
                session.add(AppSetting(key="monitor", value_json=json.dumps(value), updated_at=now))
            else:
                row.value_json = json.dumps(value)
                row.updated_at = now
        return {**value, "updated_at": now.isoformat()}

    def upsert_monitor_signals(self, signals: list[dict[str, Any]]) -> None:
        now = _now()
        with self.sessions.begin() as session:
            for signal in signals:
                symbol = normalize_symbol(signal.get("symbol"))
                indicators = signal.get("indicators") or {}
                forecast = signal.get("forecast") or {}
                volatility = float(indicators.get("volatility_30d_annualized") or 0)
                trend = 50
                if indicators.get("sma_7") is not None and indicators.get("sma_21") is not None:
                    trend += 20 if indicators["sma_7"] > indicators["sma_21"] else -20
                direction = (indicators.get("fourier_trend") or {}).get("direction")
                trend += 15 if direction == "up" else -15 if direction == "down" else 0
                components = {
                    "trend": min(max(trend, 0), 100), "fundamental": 50,
                    "model": round(min(max(50 + float(forecast.get("delta_pct") or 0) * 4, 0), 100), 1),
                    "market": 50, "risk": round(min(max(100 - volatility * 100, 0), 100), 1),
                }
                score = float(signal.get("score") or 0)
                row = session.get(Recommendation, symbol)
                if row is None:
                    row = Recommendation(
                        symbol=symbol, name=symbol, score=score, stance="neutral", horizon="5 trading days",
                        latest_price=0, projected_return_pct=0, components_json="{}", thesis="",
                        risks_json="[]", source="monitor-v1", generated_at=now, updated_at=now,
                    )
                    session.add(row)
                row.score = score
                row.stance = "positive" if score >= 68 else "risk" if score <= 38 else "neutral"
                row.latest_price = float(signal.get("latest_close") or 0)
                row.projected_return_pct = float(forecast.get("delta_pct") or 0)
                row.components_json = json.dumps(components)
                row.thesis = "Deterministic monitor score based on trend, forecast, and volatility."
                row.risks_json = json.dumps(signal.get("alerts") or [])
                row.source = "monitor-v1"
                row.generated_at = now
                row.updated_at = now

    def get_portfolio(self, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> dict[str, Any]:
        with self.sessions() as session:
            portfolio = session.get(Portfolio, portfolio_id)
            if portfolio is None:
                raise ValueError("portfolio not found")
            rows = session.scalars(select(Position).where(Position.portfolio_id == portfolio_id)).all()
            rows = sorted(
                rows,
                key=lambda item: item.reported_market_value
                if item.reported_market_value is not None
                else item.quantity * item.last_price / max(item.price_scale, 1),
                reverse=True,
            )
            positions: list[dict[str, Any]] = []
            market_value = 0.0
            cost_basis = 0.0
            for row in rows:
                scale = max(int(row.price_scale or 1), 1)
                value = (
                    float(row.reported_market_value)
                    if row.reported_market_value is not None
                    else row.quantity * row.last_price / scale
                )
                cost = (
                    float(row.reported_cost_basis)
                    if row.reported_cost_basis is not None
                    else row.quantity * row.average_cost / scale
                )
                market_value += value
                cost_basis += cost
                positions.append({
                    "symbol": row.symbol, "name": row.name, "quantity": row.quantity,
                    "currency": row.currency, "account_bucket": row.account_bucket,
                    "average_cost": row.average_cost, "last_price": row.last_price,
                    "price_scale": scale, "source": row.source,
                    "market_value": round(value, 2), "unrealized_pnl": round(value - cost, 2),
                    "unrealized_pnl_pct": round((value - cost) / cost * 100, 2) if cost else 0.0,
                    "updated_at": _iso(row.updated_at),
                })
            cash = float(portfolio.cash)
            equity = cash + market_value
            for item in positions:
                item["weight_pct"] = round(item["market_value"] / equity * 100, 2) if equity else 0.0
            return {
                "id": portfolio.id, "name": portfolio.name, "mode": portfolio.mode,
                "currency": portfolio.currency, "account_type": portfolio.account_type,
                "cash": round(cash, 2), "market_value": round(market_value, 2), "equity": round(equity, 2),
                "cost_basis": round(cost_basis, 2), "unrealized_pnl": round(market_value - cost_basis, 2),
                "benchmark_symbol": portfolio.benchmark_symbol, "positions": positions,
                "updated_at": _iso(portfolio.updated_at), "data_mode": "demo",
            }

    def get_performance(self, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> dict[str, Any]:
        with self.sessions() as session:
            rows = session.scalars(select(PerformancePoint).where(PerformancePoint.portfolio_id == portfolio_id).order_by(PerformancePoint.trade_date)).all()
            if not rows:
                raise ValueError("portfolio performance not found")
            first_value = rows[0].portfolio_value
            first_benchmark = rows[0].benchmark_value
            points = [{
                "date": row.trade_date.isoformat(), "portfolio_value": row.portfolio_value,
                "portfolio_return_pct": round((row.portfolio_value / first_value - 1) * 100, 3),
                "benchmark_return_pct": round((row.benchmark_value / first_benchmark - 1) * 100, 3),
            } for row in rows]
            return {"portfolio_id": portfolio_id, "points": points, "data_mode": "demo"}

    def get_dashboard(self) -> dict[str, Any]:
        portfolio = self.get_portfolio()
        performance = self.get_performance()
        recommendations = self.list_recommendations()
        current = performance["points"][-1]
        return {
            "portfolio": portfolio, "recommendations": recommendations[:4], "performance": performance,
            "summary": {
                "top_pick": recommendations[0] if recommendations else None,
                "portfolio_return_pct": current["portfolio_return_pct"],
                "benchmark_return_pct": current["benchmark_return_pct"],
                "alpha_pct": round(current["portfolio_return_pct"] - current["benchmark_return_pct"], 3),
                "risk_posture": "balanced" if portfolio["cash"] / portfolio["equity"] >= 0.2 else "invested",
            }, "generated_at": _now().isoformat(), "data_mode": "demo",
        }

    def list_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(select(PaperOrder).order_by(PaperOrder.created_at.desc()).limit(min(max(int(limit), 1), 200))).all()
            return [self._order(row) for row in rows]

    @contextmanager
    def _order_transaction(self):
        with self.sessions.begin() as session:
            # All mutations lock the account first; SQLite needs a database write lock.
            if self.engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            portfolio = session.scalar(select(Portfolio).where(Portfolio.id == DEFAULT_PORTFOLIO_ID).with_for_update())
            if portfolio is None:
                raise ValueError("portfolio not found")
            yield session, portfolio

    @staticmethod
    def _values(row):
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def _order_context(self, session, portfolio):
        positions = [self._values(row) for row in session.scalars(select(Position).where(Position.portfolio_id == portfolio.id))]
        pending = [self._values(row) for row in session.scalars(select(PaperOrder).where(PaperOrder.portfolio_id == portfolio.id, PaperOrder.status == "awaiting_confirmation"))]
        setting = session.get(AppSetting, "trading_halt")
        return self._values(portfolio), positions, pending, bool(json.loads(setting.value_json).get("halted")) if setting else False

    def get_trading_control(self):
        with self.sessions() as session:
            row = session.get(AppSetting, "trading_halt")
            return json.loads(row.value_json) if row else {"halted": False}

    def set_trading_halted(self, halted: bool):
        if not isinstance(halted, bool):
            raise ValueError("halted must be a boolean")
        now = _now()
        value = {"halted": halted, "updated_at": now.isoformat()}
        with self._order_transaction() as (session, _portfolio):
            row = session.get(AppSetting, "trading_halt")
            if row is None:
                session.add(AppSetting(key="trading_halt", value_json=json.dumps(value), updated_at=now))
            else:
                row.value_json, row.updated_at = json.dumps(value), now
        return value

    def create_order(self, payload: dict[str, Any], client_order_id: str | None = None) -> dict[str, Any]:
        order = parse_order(payload)
        client_id = str(client_order_id or payload.get("client_order_id") or uuid4().hex)
        now = _now()
        with self._order_transaction() as (session, portfolio):
            existing = session.scalar(select(PaperOrder).where(PaperOrder.client_order_id == client_id))
            if existing is not None:
                same_request(self._values(existing), order)
                return self._order(existing)
            context, positions, pending, halted = self._order_context(session, portfolio)
            recommendation = session.get(Recommendation, order["symbol"])
            price = reference_price(order["symbol"], positions, self._values(recommendation) if recommendation else None)
            estimated_price = order["limit_price"] if order["order_type"] == "limit" else price
            risk = evaluate_order(order, estimated_price, context, positions, pending, halted)
            status = "awaiting_confirmation" if risk["approved"] else "risk_rejected"
            record_event(risk, status, now)
            row = PaperOrder(id=uuid4().hex, client_order_id=client_id, portfolio_id=portfolio.id,
                **order, estimated_price=estimated_price, estimated_notional=estimated_price * order["quantity"],
                status=status, risk_result_json=json.dumps(risk), created_at=now, updated_at=now)
            session.add(row)
        return self._order(row)

    def cancel_order(self, order_id: str):
        with self._order_transaction() as (session, _portfolio):
            row = session.get(PaperOrder, order_id)
            if row is None:
                raise ValueError("order not found")
            if row.status == "cancelled":
                return self._order(row)
            if row.status != "awaiting_confirmation":
                raise ValueError("only pending orders can be cancelled")
            row.status, row.updated_at = "cancelled", _now()
            row.risk_result_json = json.dumps(record_event(json.loads(row.risk_result_json), "cancelled", row.updated_at))
        return self._order(row)

    def confirm_order(self, order_id: str) -> dict[str, Any]:
        now = _now()
        with self._order_transaction() as (session, portfolio):
            order = session.get(PaperOrder, order_id)
            if order is None:
                raise ValueError("order not found")
            if order.status == "paper_filled":
                return self._order(order)
            if order.status != "awaiting_confirmation":
                raise ValueError(f"order cannot be confirmed from status {order.status}")
            if order.portfolio_id != portfolio.id:
                raise ValueError("order account does not support paper execution")
            position = session.scalar(select(Position).where(Position.portfolio_id == order.portfolio_id, Position.symbol == order.symbol))
            context, positions, pending, halted = self._order_context(session, portfolio)
            recommendation = session.get(Recommendation, order.symbol)
            price = reference_price(order.symbol, positions, self._values(recommendation) if recommendation else None)
            pending = [item for item in pending if item["id"] != order_id]
            risk = evaluate_order(self._values(order), price, context, positions, pending, halted)
            validate_confirmation(self._values(order), price, risk)
            risk["events"] = json.loads(order.risk_result_json).get("events", [])
            order.risk_result_json = json.dumps(record_event(risk, "paper_filled", now))
            notional = price * order.quantity
            if order.side == "buy":
                if notional > portfolio.cash:
                    raise ValueError("available cash changed before confirmation")
                old_quantity = position.quantity if position else 0.0
                old_cost = old_quantity * position.average_cost if position else 0.0
                new_quantity = old_quantity + order.quantity
                if position is None:
                    position = Position(portfolio_id=order.portfolio_id, symbol=order.symbol, name=order.symbol, quantity=new_quantity, average_cost=(old_cost + notional) / new_quantity, last_price=price, updated_at=now)
                    session.add(position)
                else:
                    position.quantity = new_quantity
                    position.average_cost = (old_cost + notional) / new_quantity
                    position.last_price = price
                    position.updated_at = now
                portfolio.cash -= notional
            else:
                if position is None or position.quantity < order.quantity:
                    raise ValueError("available quantity changed before confirmation")
                position.quantity -= order.quantity
                portfolio.cash += notional
                if position.quantity == 0:
                    session.delete(position)
                else:
                    position.last_price = price
                    position.updated_at = now
            portfolio.updated_at = now
            order.status = "paper_filled"
            order.filled_price = price
            order.updated_at = now
            order.confirmed_at = now
        return self._order(order)

    @staticmethod
    def _recommendation(row: Recommendation) -> dict[str, Any]:
        return {
            "symbol": row.symbol, "name": row.name, "score": row.score, "stance": row.stance,
            "horizon": row.horizon, "latest_price": row.latest_price, "projected_return_pct": row.projected_return_pct,
            "components": json.loads(row.components_json), "thesis": row.thesis, "risks": json.loads(row.risks_json),
            "source": row.source, "generated_at": _iso(row.generated_at), "updated_at": _iso(row.updated_at),
        }

    @staticmethod
    def _order(row: PaperOrder) -> dict[str, Any]:
        return {
            "id": row.id, "client_order_id": row.client_order_id, "portfolio_id": row.portfolio_id,
            "symbol": row.symbol, "side": row.side, "quantity": row.quantity, "order_type": row.order_type,
            "limit_price": row.limit_price, "estimated_price": row.estimated_price,
            "estimated_notional": row.estimated_notional, "status": row.status,
            "risk_result": json.loads(row.risk_result_json), "filled_price": row.filled_price,
            "error_message": row.error_message, "created_at": _iso(row.created_at),
            "updated_at": _iso(row.updated_at), "confirmed_at": _iso(row.confirmed_at),
        }
