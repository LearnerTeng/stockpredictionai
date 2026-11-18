from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import delete, select


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database.models import PerformancePoint, Portfolio, Position  # noqa: E402
from database.session import configured_database_url, create_database_engine, session_factory  # noqa: E402


def _required_number(item: dict[str, Any], key: str) -> float:
    try:
        value = float(item[key])
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"{key} must be a number") from err
    if value < 0:
        raise ValueError(f"{key} must not be negative")
    return value


def import_portfolio(payload: dict[str, Any], database_url: str) -> dict[str, Any]:
    portfolio_data = payload.get("portfolio") or {}
    portfolio_id = str(portfolio_data.get("id") or "").strip()
    if not portfolio_id:
        raise ValueError("portfolio.id is required")

    items = payload.get("positions")
    if not isinstance(items, list) or not items:
        raise ValueError("positions must be a non-empty list")

    expected_market_value = round(sum(_required_number(item, "market_value") for item in items), 2)
    expected_cost_basis = round(sum(_required_number(item, "cost_basis") for item in items), 2)
    declared = payload.get("totals") or {}
    if declared:
        if expected_market_value != round(_required_number(declared, "market_value"), 2):
            raise ValueError("position market values do not match totals.market_value")
        if expected_cost_basis != round(_required_number(declared, "cost_basis"), 2):
            raise ValueError("position cost bases do not match totals.cost_basis")

    now = datetime.now(timezone.utc)
    as_of = date.fromisoformat(str(payload.get("as_of") or now.date().isoformat()))
    sessions = session_factory(create_database_engine(database_url))
    with sessions.begin() as session:
        portfolio = session.get(Portfolio, portfolio_id)
        if portfolio is None:
            portfolio = Portfolio(id=portfolio_id, created_at=now)
            session.add(portfolio)
        portfolio.name = str(portfolio_data.get("name") or portfolio_id)
        portfolio.mode = str(portfolio_data.get("mode") or "read_only")
        portfolio.currency = str(portfolio_data.get("currency") or "USD").upper()
        portfolio.account_type = str(portfolio_data.get("account_type") or "external")
        portfolio.cash = _required_number(portfolio_data, "cash") if "cash" in portfolio_data else 0.0
        portfolio.benchmark_symbol = str(portfolio_data.get("benchmark_symbol") or "")
        portfolio.updated_at = now
        session.flush()

        session.execute(delete(Position).where(Position.portfolio_id == portfolio_id))
        symbols: set[str] = set()
        for item in items:
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol or symbol in symbols:
                raise ValueError(f"position symbols must be present and unique: {symbol or '<empty>'}")
            symbols.add(symbol)
            scale = int(item.get("price_scale") or 1)
            if scale < 1:
                raise ValueError(f"price_scale must be at least 1: {symbol}")
            session.add(
                Position(
                    portfolio_id=portfolio_id,
                    symbol=symbol,
                    name=str(item.get("name") or symbol),
                    currency=str(item.get("currency") or portfolio.currency).upper(),
                    account_bucket=item.get("account_bucket"),
                    quantity=_required_number(item, "quantity"),
                    average_cost=_required_number(item, "average_cost"),
                    last_price=_required_number(item, "last_price"),
                    price_scale=scale,
                    reported_market_value=_required_number(item, "market_value"),
                    reported_cost_basis=_required_number(item, "cost_basis"),
                    source=str(item.get("source") or payload.get("source") or "manual-import"),
                    updated_at=now,
                )
            )

        point = session.scalar(
            select(PerformancePoint).where(
                PerformancePoint.portfolio_id == portfolio_id,
                PerformancePoint.trade_date == as_of,
            )
        )
        if point is None:
            point = PerformancePoint(portfolio_id=portfolio_id, trade_date=as_of)
            session.add(point)
        point.portfolio_value = expected_market_value + portfolio.cash
        point.benchmark_value = 100.0

    return {
        "portfolio_id": portfolio_id,
        "positions": len(items),
        "market_value": expected_market_value,
        "cost_basis": expected_cost_basis,
        "unrealized_pnl": round(expected_market_value - expected_cost_basis, 2),
        "as_of": as_of.isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an external portfolio snapshot into the configured database")
    parser.add_argument("input", type=Path)
    parser.add_argument("--database-url", default=configured_database_url())
    args = parser.parse_args()
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(import_portfolio(payload, args.database_url), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
