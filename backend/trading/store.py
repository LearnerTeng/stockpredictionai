from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any
from uuid import uuid4


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "storage" / "trading.db"
DEFAULT_PORTFOLIO_ID = "primary"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol or len(symbol) > 16:
        raise ValueError("symbol must contain 1 to 16 characters")
    return symbol


class TradingStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self._lock:
            with closing(self._connect()) as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS recommendations (
                        symbol TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        score REAL NOT NULL,
                        stance TEXT NOT NULL,
                        horizon TEXT NOT NULL,
                        latest_price REAL NOT NULL,
                        projected_return_pct REAL NOT NULL,
                        components_json TEXT NOT NULL,
                        thesis TEXT NOT NULL,
                        risks_json TEXT NOT NULL,
                        source TEXT NOT NULL,
                        generated_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS portfolios (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        cash REAL NOT NULL,
                        benchmark_symbol TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS positions (
                        portfolio_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        name TEXT NOT NULL,
                        quantity REAL NOT NULL,
                        average_cost REAL NOT NULL,
                        last_price REAL NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (portfolio_id, symbol),
                        FOREIGN KEY (portfolio_id) REFERENCES portfolios(id)
                    );

                    CREATE TABLE IF NOT EXISTS performance_points (
                        portfolio_id TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        portfolio_value REAL NOT NULL,
                        benchmark_value REAL NOT NULL,
                        PRIMARY KEY (portfolio_id, trade_date),
                        FOREIGN KEY (portfolio_id) REFERENCES portfolios(id)
                    );

                    CREATE TABLE IF NOT EXISTS paper_orders (
                        id TEXT PRIMARY KEY,
                        client_order_id TEXT NOT NULL UNIQUE,
                        portfolio_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        quantity REAL NOT NULL,
                        order_type TEXT NOT NULL,
                        limit_price REAL,
                        estimated_price REAL NOT NULL,
                        estimated_notional REAL NOT NULL,
                        status TEXT NOT NULL,
                        risk_result_json TEXT NOT NULL,
                        filled_price REAL,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        confirmed_at TEXT,
                        FOREIGN KEY (portfolio_id) REFERENCES portfolios(id)
                    );

                    CREATE TABLE IF NOT EXISTS stock_preferences (
                        symbol TEXT PRIMARY KEY,
                        wanted INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_paper_orders_created
                    ON paper_orders(created_at DESC);
                    """
                )
                conn.commit()

        self._seed_demo_data()

    def _seed_demo_data(self) -> None:
        now = utc_now_iso()
        recommendations = [
            ("NVDA", "NVIDIA", 86.0, "positive", "20 trading days", 134.20, 8.6,
             {"trend": 92, "fundamental": 84, "model": 81, "market": 88, "risk": 76},
             "Earnings momentum and relative strength remain constructive.",
             ["Elevated volatility", "Position concentration"], "demo-seed"),
            ("MSFT", "Microsoft", 81.0, "positive", "20 trading days", 432.60, 6.2,
             {"trend": 83, "fundamental": 91, "model": 77, "market": 79, "risk": 82},
             "Stable cash generation supports a favorable risk-adjusted profile.",
             ["Valuation sensitivity", "Cloud growth expectations"], "demo-seed"),
            ("AMZN", "Amazon", 76.0, "watch", "20 trading days", 218.40, 5.4,
             {"trend": 79, "fundamental": 78, "model": 75, "market": 77, "risk": 69},
             "Margin expansion offsets a moderately volatile trend profile.",
             ["Consumer slowdown", "High beta"], "demo-seed"),
            ("AAPL", "Apple", 69.0, "neutral", "20 trading days", 212.30, 3.1,
             {"trend": 68, "fundamental": 82, "model": 64, "market": 66, "risk": 74},
             "Quality remains high, while near-term momentum is less decisive.",
             ["Demand normalization", "Multiple compression"], "demo-seed"),
        ]

        with self._lock:
            with closing(self._connect()) as conn:
                if conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == 0:
                    for row in recommendations:
                        conn.execute(
                            """
                            INSERT INTO recommendations (
                                symbol, name, score, stance, horizon, latest_price,
                                projected_return_pct, components_json, thesis, risks_json,
                                source, generated_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (*row[:7], json.dumps(row[7]), row[8], json.dumps(row[9]), row[10], now, now),
                        )

                if conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0] == 0:
                    conn.execute(
                        "INSERT INTO portfolios VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (DEFAULT_PORTFOLIO_ID, "Core Growth", "paper", 18_500.0, "SPY", now, now),
                    )
                    positions = [
                        ("NVDA", "NVIDIA", 18.0, 118.40, 134.20),
                        ("MSFT", "Microsoft", 10.0, 408.10, 432.60),
                        ("SPY", "S&P 500 ETF", 12.0, 541.20, 561.30),
                        ("TSLA", "Tesla", 4.0, 255.00, 238.70),
                    ]
                    for symbol, name, quantity, average_cost, last_price in positions:
                        conn.execute(
                            "INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (DEFAULT_PORTFOLIO_ID, symbol, name, quantity, average_cost, last_price, now),
                        )

                    start = date.today() - timedelta(days=13)
                    values = [31_420, 31_710, 31_560, 31_990, 32_240, 32_110, 32_680, 32_940, 32_760, 33_210, 33_480, 33_320, 33_770, 33_944]
                    benchmark = [100.0, 100.4, 100.2, 100.8, 101.0, 100.9, 101.5, 101.8, 101.6, 102.1, 102.3, 102.2, 102.7, 102.9]
                    for index, value in enumerate(values):
                        conn.execute(
                            "INSERT INTO performance_points VALUES (?, ?, ?, ?)",
                            (DEFAULT_PORTFOLIO_ID, (start + timedelta(days=index)).isoformat(), value, benchmark[index]),
                        )
                conn.commit()

    def list_recommendations(self) -> list[dict[str, Any]]:
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute("SELECT * FROM recommendations ORDER BY score DESC, symbol").fetchall()
        return [self._serialize_recommendation(row) for row in rows]

    def get_recommendation_or_none(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT * FROM recommendations WHERE symbol = ?", (normalize_symbol(symbol),)
                ).fetchone()
        return self._serialize_recommendation(row) if row is not None else None

    def list_wanted_symbols(self) -> set[str]:
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute("SELECT symbol FROM stock_preferences WHERE wanted = 1").fetchall()
        return {str(row["symbol"]) for row in rows}

    def set_wanted(self, symbol: str, wanted: bool) -> dict[str, Any]:
        normalized = normalize_symbol(symbol)
        now = utc_now_iso()
        with self._lock:
            with closing(self._connect()) as conn:
                existing = conn.execute(
                    "SELECT created_at FROM stock_preferences WHERE symbol = ?", (normalized,)
                ).fetchone()
                created_at = existing["created_at"] if existing is not None else now
                conn.execute(
                    """
                    INSERT INTO stock_preferences (symbol, wanted, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET wanted = excluded.wanted, updated_at = excluded.updated_at
                    """,
                    (normalized, 1 if wanted else 0, created_at, now),
                )
                conn.commit()
        return {"symbol": normalized, "wanted": bool(wanted), "updated_at": now}

    def get_monitor_settings(self) -> dict[str, Any]:
        defaults = {"auto_refresh_enabled": False, "interval_minutes": 15}
        with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute("SELECT value_json, updated_at FROM app_settings WHERE key = 'monitor'").fetchone()
        if row is None:
            return {**defaults, "updated_at": None}
        try:
            stored = json.loads(row["value_json"])
        except (TypeError, json.JSONDecodeError):
            stored = {}
        return {
            "auto_refresh_enabled": bool(stored.get("auto_refresh_enabled", defaults["auto_refresh_enabled"])),
            "interval_minutes": int(stored.get("interval_minutes", defaults["interval_minutes"])),
            "updated_at": row["updated_at"],
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
        now = utc_now_iso()
        value = {"auto_refresh_enabled": enabled, "interval_minutes": interval}
        with self._lock:
            with closing(self._connect()) as conn:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value_json, updated_at) VALUES ('monitor', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                    """,
                    (json.dumps(value), now),
                )
                conn.commit()
        return {**value, "updated_at": now}

    def upsert_monitor_signals(self, signals: list[dict[str, Any]]) -> None:
        if not signals:
            return
        now = utc_now_iso()
        with self._lock:
            with closing(self._connect()) as conn:
                for signal in signals:
                    symbol = normalize_symbol(signal.get("symbol"))
                    indicators = signal.get("indicators") or {}
                    forecast = signal.get("forecast") or {}
                    volatility = float(indicators.get("volatility_30d_annualized") or 0)
                    trend_points = 50
                    if indicators.get("sma_7") is not None and indicators.get("sma_21") is not None:
                        trend_points += 20 if indicators["sma_7"] > indicators["sma_21"] else -20
                    fourier = indicators.get("fourier_trend") or {}
                    trend_points += 15 if fourier.get("direction") == "up" else -15 if fourier.get("direction") == "down" else 0
                    model_points = min(max(50 + float(forecast.get("delta_pct") or 0) * 4, 0), 100)
                    components = {
                        "trend": min(max(trend_points, 0), 100),
                        "fundamental": 50,
                        "model": round(model_points, 1),
                        "market": 50,
                        "risk": round(min(max(100 - volatility * 100, 0), 100), 1),
                    }
                    score = float(signal.get("score") or 0)
                    stance = "positive" if score >= 68 else "risk" if score <= 38 else "neutral"
                    alerts = signal.get("alerts") or []
                    conn.execute(
                        """
                        INSERT INTO recommendations (
                            symbol, name, score, stance, horizon, latest_price,
                            projected_return_pct, components_json, thesis, risks_json,
                            source, generated_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol) DO UPDATE SET
                            score = excluded.score,
                            stance = excluded.stance,
                            latest_price = excluded.latest_price,
                            projected_return_pct = excluded.projected_return_pct,
                            components_json = excluded.components_json,
                            thesis = excluded.thesis,
                            risks_json = excluded.risks_json,
                            source = excluded.source,
                            generated_at = excluded.generated_at,
                            updated_at = excluded.updated_at
                        """,
                        (
                            symbol,
                            symbol,
                            score,
                            stance,
                            "5 trading days",
                            float(signal.get("latest_close") or 0),
                            float(forecast.get("delta_pct") or 0),
                            json.dumps(components),
                            "Deterministic monitor score based on trend, forecast, and volatility.",
                            json.dumps(alerts),
                            "monitor-v1",
                            now,
                            now,
                        ),
                    )
                conn.commit()

    def get_recommendation(self, symbol: str) -> dict[str, Any]:
        with self._lock:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT * FROM recommendations WHERE symbol = ?", (normalize_symbol(symbol),)
                ).fetchone()
        if row is None:
            raise ValueError("recommendation not found")
        return self._serialize_recommendation(row)

    def get_portfolio(self, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> dict[str, Any]:
        with self._lock:
            with closing(self._connect()) as conn:
                portfolio = conn.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
                positions = conn.execute(
                    "SELECT * FROM positions WHERE portfolio_id = ? ORDER BY quantity * last_price DESC",
                    (portfolio_id,),
                ).fetchall()
        if portfolio is None:
            raise ValueError("portfolio not found")

        serialized = []
        market_value = 0.0
        cost_basis = 0.0
        for row in positions:
            value = row["quantity"] * row["last_price"]
            cost = row["quantity"] * row["average_cost"]
            pnl = value - cost
            market_value += value
            cost_basis += cost
            serialized.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "quantity": row["quantity"],
                    "average_cost": row["average_cost"],
                    "last_price": row["last_price"],
                    "market_value": round(value, 2),
                    "unrealized_pnl": round(pnl, 2),
                    "unrealized_pnl_pct": round(pnl / cost * 100, 2) if cost else 0.0,
                    "updated_at": row["updated_at"],
                }
            )
        cash = float(portfolio["cash"])
        equity = cash + market_value
        for item in serialized:
            item["weight_pct"] = round(item["market_value"] / equity * 100, 2) if equity else 0.0

        return {
            "id": portfolio["id"],
            "name": portfolio["name"],
            "mode": portfolio["mode"],
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "equity": round(equity, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_pnl": round(market_value - cost_basis, 2),
            "benchmark_symbol": portfolio["benchmark_symbol"],
            "positions": serialized,
            "updated_at": portfolio["updated_at"],
            "data_mode": "demo",
        }

    def get_performance(self, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> dict[str, Any]:
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT * FROM performance_points WHERE portfolio_id = ? ORDER BY trade_date",
                    (portfolio_id,),
                ).fetchall()
        if not rows:
            raise ValueError("portfolio performance not found")
        first_value = float(rows[0]["portfolio_value"])
        first_benchmark = float(rows[0]["benchmark_value"])
        points = [
            {
                "date": row["trade_date"],
                "portfolio_value": row["portfolio_value"],
                "portfolio_return_pct": round((row["portfolio_value"] / first_value - 1) * 100, 3),
                "benchmark_return_pct": round((row["benchmark_value"] / first_benchmark - 1) * 100, 3),
            }
            for row in rows
        ]
        return {"portfolio_id": portfolio_id, "points": points, "data_mode": "demo"}

    def get_dashboard(self) -> dict[str, Any]:
        portfolio = self.get_portfolio()
        performance = self.get_performance()
        recommendations = self.list_recommendations()
        points = performance["points"]
        current_return = points[-1]["portfolio_return_pct"]
        benchmark_return = points[-1]["benchmark_return_pct"]
        return {
            "portfolio": portfolio,
            "recommendations": recommendations[:4],
            "performance": performance,
            "summary": {
                "top_pick": recommendations[0] if recommendations else None,
                "portfolio_return_pct": current_return,
                "benchmark_return_pct": benchmark_return,
                "alpha_pct": round(current_return - benchmark_return, 3),
                "risk_posture": "balanced" if portfolio["cash"] / portfolio["equity"] >= 0.2 else "invested",
            },
            "generated_at": utc_now_iso(),
            "data_mode": "demo",
        }

    def list_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        normalized_limit = min(max(int(limit), 1), 200)
        with self._lock:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT * FROM paper_orders ORDER BY created_at DESC LIMIT ?", (normalized_limit,)
                ).fetchall()
        return [self._serialize_order(row) for row in rows]

    def create_order(self, payload: dict[str, Any], client_order_id: str | None = None) -> dict[str, Any]:
        symbol = normalize_symbol(payload.get("symbol"))
        side = str(payload.get("side", "")).strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        try:
            quantity = float(payload.get("quantity"))
        except (TypeError, ValueError) as err:
            raise ValueError("quantity must be a number") from err
        if quantity <= 0 or quantity > 10_000:
            raise ValueError("quantity must be greater than 0 and no more than 10000")
        order_type = str(payload.get("order_type", "market")).strip().lower()
        if order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        limit_price = float(payload["limit_price"]) if payload.get("limit_price") is not None else None
        if order_type == "limit" and (limit_price is None or limit_price <= 0):
            raise ValueError("limit_price is required for a limit order")

        portfolio = self.get_portfolio()
        positions = {item["symbol"]: item for item in portfolio["positions"]}
        try:
            recommendation = self.get_recommendation(symbol)
        except ValueError:
            recommendation = None
        estimated_price = limit_price or (
            positions.get(symbol, {}).get("last_price")
            or (recommendation or {}).get("latest_price")
        )
        if not estimated_price:
            raise ValueError("no reference price is available for this symbol")
        notional = quantity * float(estimated_price)

        checks = []
        checks.append({"code": "paper_only", "passed": portfolio["mode"] == "paper", "message": "Only paper trading is enabled."})
        checks.append({"code": "max_order_notional", "passed": notional <= 10_000, "message": "Order notional must not exceed $10,000."})
        if side == "buy":
            checks.append({"code": "available_cash", "passed": notional <= portfolio["cash"], "message": "Sufficient cash is required."})
            projected_position = positions.get(symbol, {}).get("market_value", 0) + notional
            checks.append({"code": "position_limit", "passed": projected_position <= portfolio["equity"] * 0.25, "message": "Projected position must not exceed 25% of equity."})
        else:
            checks.append({"code": "available_quantity", "passed": quantity <= positions.get(symbol, {}).get("quantity", 0), "message": "Sell quantity cannot exceed the current position."})
        approved = all(check["passed"] for check in checks)
        risk_result = {"approved": approved, "checks": checks, "policy_version": "paper-v1"}

        order_id = uuid4().hex
        normalized_client_id = str(client_order_id or payload.get("client_order_id") or uuid4().hex)
        now = utc_now_iso()
        with self._lock:
            with closing(self._connect()) as conn:
                existing = conn.execute(
                    "SELECT * FROM paper_orders WHERE client_order_id = ?", (normalized_client_id,)
                ).fetchone()
                if existing is not None:
                    return self._serialize_order(existing)
                conn.execute(
                    """
                    INSERT INTO paper_orders (
                        id, client_order_id, portfolio_id, symbol, side, quantity,
                        order_type, limit_price, estimated_price, estimated_notional,
                        status, risk_result_json, filled_price, error_message,
                        created_at, updated_at, confirmed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
                    """,
                    (order_id, normalized_client_id, DEFAULT_PORTFOLIO_ID, symbol, side, quantity,
                     order_type, limit_price, estimated_price, notional,
                     "awaiting_confirmation" if approved else "risk_rejected",
                     json.dumps(risk_result), now, now),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM paper_orders WHERE id = ?", (order_id,)).fetchone()
        return self._serialize_order(row)

    def confirm_order(self, order_id: str) -> dict[str, Any]:
        now = utc_now_iso()
        with self._lock:
            with closing(self._connect()) as conn:
                order = conn.execute("SELECT * FROM paper_orders WHERE id = ?", (order_id,)).fetchone()
                if order is None:
                    raise ValueError("order not found")
                if order["status"] != "awaiting_confirmation":
                    raise ValueError(f"order cannot be confirmed from status {order['status']}")

                portfolio = conn.execute("SELECT * FROM portfolios WHERE id = ?", (order["portfolio_id"],)).fetchone()
                position = conn.execute(
                    "SELECT * FROM positions WHERE portfolio_id = ? AND symbol = ?",
                    (order["portfolio_id"], order["symbol"]),
                ).fetchone()
                price = float(order["estimated_price"])
                notional = price * float(order["quantity"])
                if order["side"] == "buy":
                    if notional > portfolio["cash"]:
                        raise ValueError("available cash changed before confirmation")
                    old_quantity = float(position["quantity"]) if position else 0.0
                    old_cost = old_quantity * float(position["average_cost"]) if position else 0.0
                    new_quantity = old_quantity + float(order["quantity"])
                    new_average = (old_cost + notional) / new_quantity
                    name = position["name"] if position else order["symbol"]
                    conn.execute(
                        """
                        INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(portfolio_id, symbol) DO UPDATE SET
                            quantity = excluded.quantity,
                            average_cost = excluded.average_cost,
                            last_price = excluded.last_price,
                            updated_at = excluded.updated_at
                        """,
                        (order["portfolio_id"], order["symbol"], name, new_quantity, new_average, price, now),
                    )
                    cash = float(portfolio["cash"]) - notional
                else:
                    if position is None or float(position["quantity"]) < float(order["quantity"]):
                        raise ValueError("available quantity changed before confirmation")
                    remaining = float(position["quantity"]) - float(order["quantity"])
                    if remaining == 0:
                        conn.execute(
                            "DELETE FROM positions WHERE portfolio_id = ? AND symbol = ?",
                            (order["portfolio_id"], order["symbol"]),
                        )
                    else:
                        conn.execute(
                            "UPDATE positions SET quantity = ?, last_price = ?, updated_at = ? WHERE portfolio_id = ? AND symbol = ?",
                            (remaining, price, now, order["portfolio_id"], order["symbol"]),
                        )
                    cash = float(portfolio["cash"]) + notional

                conn.execute("UPDATE portfolios SET cash = ?, updated_at = ? WHERE id = ?", (cash, now, order["portfolio_id"]))
                conn.execute(
                    "UPDATE paper_orders SET status = 'paper_filled', filled_price = ?, updated_at = ?, confirmed_at = ? WHERE id = ?",
                    (price, now, now, order_id),
                )
                conn.commit()
                filled = conn.execute("SELECT * FROM paper_orders WHERE id = ?", (order_id,)).fetchone()
        return self._serialize_order(filled)

    @staticmethod
    def _serialize_recommendation(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "symbol": row["symbol"], "name": row["name"], "score": row["score"],
            "stance": row["stance"], "horizon": row["horizon"],
            "latest_price": row["latest_price"], "projected_return_pct": row["projected_return_pct"],
            "components": json.loads(row["components_json"]), "thesis": row["thesis"],
            "risks": json.loads(row["risks_json"]), "source": row["source"],
            "generated_at": row["generated_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _serialize_order(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"], "client_order_id": row["client_order_id"],
            "portfolio_id": row["portfolio_id"], "symbol": row["symbol"],
            "side": row["side"], "quantity": row["quantity"], "order_type": row["order_type"],
            "limit_price": row["limit_price"], "estimated_price": row["estimated_price"],
            "estimated_notional": row["estimated_notional"], "status": row["status"],
            "risk_result": json.loads(row["risk_result_json"]), "filled_price": row["filled_price"],
            "error_message": row["error_message"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "confirmed_at": row["confirmed_at"],
            "mode": "paper",
        }
