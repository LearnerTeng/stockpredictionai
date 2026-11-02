"""Events are appended in the same transaction as paper cash and holdings."""
from datetime import datetime, timezone
from math import isfinite
from uuid import uuid4
from sqlalchemy import func, select
from database.models import CashEntry, ExecutionEvent, Fill, Portfolio, Position


def append_event(session, order, status):
    session.flush()
    session.add(ExecutionEvent(id=uuid4().hex, order_id=order.id, status=status,
        created_at=datetime.now(timezone.utc), payload={"symbol": order.symbol, "quantity": order.quantity, "side": order.side}))


def append_fill(session, order, portfolio, opening_cash):
    if session.scalar(select(CashEntry.id).where(CashEntry.portfolio_id == portfolio.id).limit(1)) is None:
        session.add(CashEntry(id=uuid4().hex, portfolio_id=portfolio.id, amount=opening_cash,
            kind="opening-balance", created_at=datetime.now(timezone.utc)))
    fill = Fill(id=uuid4().hex, order_id=order.id, quantity=order.quantity, price=order.filled_price,
                fee=0, executed_at=order.confirmed_at)
    session.add(fill)
    session.flush()
    session.add(CashEntry(id=uuid4().hex, portfolio_id=portfolio.id, fill_id=fill.id,
        amount=portfolio.cash-opening_cash, kind="paper-fill", created_at=order.confirmed_at))
    append_event(session, order, "paper_filled")


def reconcile(sessions, portfolio_id="primary", statement=None):
    with sessions.begin() as session:
        portfolio = session.scalar(select(Portfolio).where(Portfolio.id == portfolio_id).with_for_update())
        if portfolio is None:
            raise ValueError("portfolio not found")
        balance = session.scalar(select(func.sum(CashEntry.amount)).where(CashEntry.portfolio_id == portfolio_id))
        positions = {p.symbol: p.quantity for p in session.scalars(select(Position).where(Position.portfolio_id == portfolio_id))}
        differences = []
        if balance is None:
            differences.append({"field": "cash_ledger", "reason": "no opening balance; ledger starts on first new fill"})
        elif abs(balance - portfolio.cash) > .005:
            differences.append({"field": "cash_ledger", "expected": balance, "actual": portfolio.cash})
        if statement is not None:
            cash = float(statement["cash"])
            if not isfinite(cash) or statement.get("currency") != portfolio.currency:
                raise ValueError("invalid statement cash or currency")
            if abs(cash - portfolio.cash) > .005:
                differences.append({"field": "statement_cash", "expected": cash, "actual": portfolio.cash})
            reported = {str(k): float(v) for k, v in statement["positions"].items()}
            if any(not isfinite(v) for v in reported.values()):
                raise ValueError("invalid statement quantity")
            for symbol in sorted(positions.keys() | reported.keys()):
                if abs(positions.get(symbol, 0) - reported.get(symbol, 0)) > 1e-8:
                    differences.append({"field": "position", "symbol": symbol, "expected": reported.get(symbol, 0),
                                        "actual": positions.get(symbol, 0)})
        return {"portfolio_id": portfolio_id, "status": "mismatch" if differences else "matched",
                "scope": "statement-snapshot" if statement is not None else "internal-cash-ledger", "differences": differences}
