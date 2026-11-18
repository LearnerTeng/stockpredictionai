"""One deterministic paper policy for both database implementations."""
from datetime import datetime, timezone
from math import isfinite


def positive_number(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number") from error
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def parse_order(payload):
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol or len(symbol) > 16:
        raise ValueError("symbol must contain 1 to 16 characters")
    side = str(payload.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    quantity = positive_number(payload.get("quantity"), "quantity")
    if quantity > 10_000:
        raise ValueError("quantity must not exceed 10000")
    order_type = str(payload.get("order_type") or "market").lower()
    if order_type not in {"market", "limit"}:
        raise ValueError("order_type must be market or limit")
    limit = positive_number(payload["limit_price"], "limit_price") if payload.get("limit_price") is not None else None
    if order_type == "limit" and limit is None:
        raise ValueError("limit_price is required for a limit order")
    if order_type == "market" and limit is not None:
        raise ValueError("market orders cannot specify limit_price")
    return {"symbol": symbol, "side": side, "quantity": quantity, "order_type": order_type, "limit_price": limit}


def same_request(existing, order):
    if any(existing[key] != value for key, value in order.items()):
        raise ValueError("Idempotency-Key was already used for a different order")


def reference_price(symbol, positions, recommendation):
    candidates = []
    position = next((item for item in positions if item["symbol"] == symbol), None)
    for item, field in ((position, "last_price"), (recommendation, "latest_price")):
        if item:
            candidates.append((str(item.get("updated_at") or ""), item[field]))
    if not candidates:
        raise ValueError("no reference price is available for this symbol")
    return positive_number(max(candidates, key=lambda item: item[0])[1], "reference price")


def evaluate_order(order, price, portfolio, positions, pending, halted=False):
    price = positive_number(price, "price")
    quantity = positive_number(order["quantity"], "quantity")
    notional = price * quantity
    symbol = order["symbol"]
    position = next((item for item in positions if item["symbol"] == symbol), {})
    equity = float(portfolio["cash"]) + sum(float(item["quantity"]) * (price if item["symbol"] == symbol else float(item["last_price"])) for item in positions)
    buys = [item for item in pending if item["side"] == "buy"]
    reserved_cash = sum(float(item["estimated_notional"]) for item in buys)
    reserved_position = sum(float(item["estimated_notional"]) for item in buys if item["symbol"] == symbol)
    reserved_quantity = sum(float(item["quantity"]) for item in pending if item["side"] == "sell" and item["symbol"] == symbol)
    checks = [
        {"code": "paper_only", "passed": portfolio["mode"] == "paper", "message": "Only paper trading is enabled."},
        {"code": "trading_enabled", "passed": not halted, "message": "Trading must not be halted."},
        {"code": "max_order_notional", "passed": isfinite(notional) and notional <= 10_000, "message": "Order notional must not exceed $10,000."},
    ]
    if order["side"] == "buy":
        projected = float(position.get("quantity", 0)) * price + reserved_position + notional
        checks.extend([
            {"code": "available_cash", "passed": notional + reserved_cash <= float(portfolio["cash"]) + 1e-8, "message": "Cash must cover this order and all pending buys."},
            {"code": "position_limit", "passed": projected <= equity * .25 + 1e-8, "message": "Position including pending buys must not exceed 25% of equity."},
        ])
    else:
        checks.append({"code": "available_quantity", "passed": quantity + reserved_quantity <= float(position.get("quantity", 0)) + 1e-8, "message": "Sell quantity including pending sells cannot exceed holdings."})
    return {"approved": all(item["passed"] for item in checks), "checks": checks, "policy_version": "paper-v2"}


def validate_confirmation(order, price, risk):
    created = datetime.fromisoformat(str(order["created_at"]).replace("Z", "+00:00"))
    created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
    if (datetime.now(timezone.utc) - created).total_seconds() > 900:
        raise ValueError("order draft expired; cancel it and create a new draft")
    if not risk["approved"]:
        raise ValueError("confirmation rejected: " + "; ".join(item["message"] for item in risk["checks"] if not item["passed"]))
    if order["order_type"] == "limit":
        limit = positive_number(order["limit_price"], "limit_price")
        if (order["side"] == "buy" and price > limit) or (order["side"] == "sell" and price < limit):
            raise ValueError("limit price has not been reached by the current reference price")


def record_event(risk, status, timestamp):
    risk.setdefault("events", []).append({"status": status, "at": str(timestamp)})
    return risk
