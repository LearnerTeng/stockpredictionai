"""Long-only, next-session portfolio replay with an explicit cash/share ledger.

Uses raw prices and explicit corporate actions. Adjusted closes are ONLY used for
momentum signals and benchmark returns. Orders expire at the end of each day.
"""
from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite, sqrt
from statistics import mean, pstdev

from market_data.calendar import calendar, session_close
from market_data.point_in_time import aware
from .contracts import adjusted_price, normalize_bars
from .backtesting import _max_drawdown_pct


@dataclass(frozen=True)
class PortfolioBacktestConfig:
    initial_cash: float = 100_000
    rebalance_sessions: int = 5
    lookback: int = 20
    top_n: int = 10
    max_weight: float = .20
    max_sector_weight: float = .40
    max_turnover: float = .40
    participation: float = .01
    commission_bps: float = 10
    slippage_bps: float = 5
    impact_bps: float = 20
    cash_rate: float = 0
    strict_point_in_time: bool = True

    def validate(self):
        if not isinstance(self.strict_point_in_time, bool):
            raise ValueError("strict_point_in_time must be a boolean")
        for key, value in asdict(self).items():
            if isinstance(value, (int, float)) and not isfinite(value):
                raise ValueError(f"{key} must be finite")
        for name in ("rebalance_sessions", "lookback", "top_n"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        for name in ("max_weight", "max_sector_weight", "max_turnover", "participation"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        if any(not 0 <= getattr(self, key) <= 1000 for key in ("commission_bps", "slippage_bps", "impact_bps")):
            raise ValueError("costs must be between 0 and 1000 bps")
        if not -.1 <= self.cash_rate <= 1:
            raise ValueError("cash_rate must be in [-0.1, 1]")


def run_portfolio_backtest(dataset, config=None):
    cfg = config or PortfolioBacktestConfig()
    cfg.validate()
    assets = dataset["assets"]
    if not assets or len(assets) > 500:
        raise ValueError("provide 1 to 500 assets keyed by permanent security_id")
    if any(a.get("currency") != "USD" or a.get("market") != "US" for a in assets.values()):
        raise ValueError("this backtest currently supports US equities in USD only")
    benchmark = normalize_bars(dataset["benchmark"])
    if len(benchmark) < cfg.lookback + 2:
        raise ValueError("insufficient benchmark history")
    days = [str(b.get("trade_date") or b.get("date")) for b in benchmark]
    for day in days:
        if not calendar("US", date.fromisoformat(day).year).is_session(day):
            raise ValueError(f"non-session benchmark date: {day}")
    # Calendar gaps cannot silently turn a 5-session target into 5 observed bars.
    expected = [d.date().isoformat() for d in calendar("US", date.fromisoformat(days[0]).year).sessions_in_range(days[0], days[-1])]
    if days != expected:
        raise ValueError("benchmark has missing sessions")
    bars = {sid: {str(b.get("trade_date") or b.get("date")): b for b in normalize_bars(a["bars"])} for sid, a in assets.items()}
    memberships = dataset.get("memberships", [])
    if cfg.strict_point_in_time and not memberships:
        raise ValueError("strict replay requires point-in-time memberships")
    for row in memberships:
        if row["security_id"] not in assets:
            raise ValueError("membership references unknown security")
        aware(row["available_at"])
        date.fromisoformat(row["valid_from"])
        if row.get("valid_to") and row["valid_to"] <= row["valid_from"]:
            raise ValueError("invalid membership interval")
    actions = {}
    seen_actions = set()
    for action in dataset.get("actions", []):
        if action["security_id"] not in assets or action["type"] not in {"split", "dividend", "delisting"}:
            raise ValueError("invalid corporate action")
        value = float(action["value"])
        if not isfinite(value) or value < 0 or (action["type"] == "split" and value == 0):
            raise ValueError("invalid corporate action value")
        key = action["date"], action["security_id"], action["type"]
        if action["date"] not in days or key in seen_actions:
            raise ValueError("corporate action must have a unique type/security/session in the replay window")
        seen_actions.add(key)
        actions.setdefault(action["date"], []).append(action)
    for security_bars in bars.values():
        for day, bar in security_bars.items():
            close = session_close(date.fromisoformat(day))
            if bar.get("available_at") and aware(bar["available_at"]) < close:
                raise ValueError("daily bar cannot be available before its session close")
    cash = cfg.initial_cash
    shares = {sid: 0.0 for sid in assets}
    marks = {}
    fills, equity, ledger = [], [], []
    pending = {}
    total_turnover = total_fees = total_slippage = 0.0
    for index, day in enumerate(days):
        if index:
            interest = cash * cfg.cash_rate * (date.fromisoformat(day) - date.fromisoformat(days[index-1])).days / 365
            cash += interest
        for action in actions.get(day, []):
            sid, value = action["security_id"], float(action["value"])
            if action["type"] == "split":
                shares[sid] *= value
                if sid in pending:
                    pending[sid] *= value
                if sid in marks:
                    marks[sid] /= value
            else:
                amount = shares[sid] * value
                cash += amount
                ledger.append({"date": day, "security_id": sid, "type": action["type"], "cash_delta": amount})
                if action["type"] == "delisting":
                    shares[sid] = 0
                    pending.pop(sid, None)
        if pending:
            # Target quantities were fixed at the preceding close, before seeing today's open.
            orders = []
            for sid, target in pending.items():
                bar = bars[sid].get(day)
                if not bar or bar.get("open") is None or not bar.get("volume"):
                    continue
                delta = target - shares[sid]
                orders.append((delta >= 0, sid, delta, bar))
            for _, sid, delta, bar in sorted(orders):  # sells release cash first
                quantity = min(abs(delta), float(bar["volume"]) * cfg.participation)
                if quantity <= 1e-10:
                    continue
                side = 1 if delta > 0 else -1
                participation = quantity / float(bar["volume"])
                slip = (cfg.slippage_bps + cfg.impact_bps * participation / cfg.participation) / 10000
                price = float(bar["open"]) * (1 + side * slip)
                fee_rate = cfg.commission_bps / 10000
                quantity = min(quantity, cash / (price * (1 + fee_rate))) if side > 0 else min(quantity, shares[sid])
                notional, fee = quantity * price, quantity * price * fee_rate
                cash -= side * notional + fee
                shares[sid] += side * quantity
                total_fees += fee
                total_slippage += quantity * abs(price - float(bar["open"]))
                total_turnover += notional
                fills.append({"date": day, "signal_date": days[index-1], "security_id": sid,
                    "side": "buy" if side > 0 else "sell", "quantity": quantity, "price": price, "fee": fee,
                    "unfilled_quantity": abs(delta) - quantity})
        pending = {}
        for sid in assets:
            if day in bars[sid]:
                marks[sid] = float(bars[sid][day]["close"])
            elif shares[sid] > 1e-8:
                raise ValueError(f"missing valuation for held security {sid} on {day}; provide halt or delisting data")
        nav = cash + sum(shares[sid] * marks.get(sid, 0) for sid in assets)
        if nav <= 0 or cash < -1e-6:
            raise ValueError("invalid portfolio ledger")
        equity.append({"date": day, "equity": nav, "cash": cash,
                       "holdings": {sid: q for sid, q in shares.items() if q > 1e-10}})
        if index < cfg.lookback or (index - cfg.lookback) % cfg.rebalance_sessions or index == len(days)-1:
            continue
        cutoff = session_close(date.fromisoformat(day))
        eligible = {m["security_id"] for m in memberships if m["valid_from"] <= day
                    and (not m.get("valid_to") or day < m["valid_to"]) and aware(m["available_at"]) <= cutoff} if memberships else set(assets)
        eligible -= {a["security_id"] for event_day, events in actions.items() if event_day <= day
                     for a in events if a["type"] == "delisting"}
        scores = {}
        for sid in eligible:
            history = [bars[sid][d] for d in days[:index+1] if d in bars[sid]]
            if cfg.strict_point_in_time:
                history = [b for b in history if b.get("available_at") and aware(b["available_at"]) <= cutoff]
            if len(history) <= cfg.lookback or str(history[-1].get("trade_date") or history[-1].get("date")) != day:
                continue
            scores[sid] = adjusted_price(history[-1]) / adjusted_price(history[-cfg.lookback-1]) - 1
        if "signals" in dataset:
            # Externally generated model scores must have been recorded by the cutoff.
            scores = {r["security_id"]: float(r["score"]) for r in dataset["signals"]
                if r["date"] == day and r["security_id"] in scores and aware(r["available_at"]) <= cutoff}
            if any(not isfinite(value) for value in scores.values()):
                raise ValueError("nonfinite model score")
        ranked = sorted((sid for sid, value in scores.items() if value > 0), key=lambda s: (-scores[s], s))[:cfg.top_n]
        targets, sector_weights = {}, {}
        for sid in ranked:
            sector = assets[sid].get("sector") or "unknown"
            weight = min(1 / len(ranked), cfg.max_weight, max(0, cfg.max_sector_weight - sector_weights.get(sector, 0)))
            targets[sid] = weight
            sector_weights[sector] = sector_weights.get(sector, 0) + weight
        deltas = {sid: nav * targets.get(sid, 0) - shares[sid] * marks.get(sid, 0) for sid in assets}
        gross = sum(abs(value) for value in deltas.values())
        scale = min(1, cfg.max_turnover * nav / gross) if gross else 1
        pending = {sid: max(0, shares[sid] + delta * scale / marks[sid]) for sid, delta in deltas.items()
                   if sid in marks and abs(delta) > 1e-8}
    values = [cfg.initial_cash] + [p["equity"] for p in equity]
    returns = [right / left - 1 for left, right in zip(values, values[1:])]
    volatility = pstdev(returns)
    losses = sorted(-r for r in returns)
    var = losses[min(len(losses)-1, int(.95 * len(losses)))]
    tail = [loss for loss in losses if loss >= var]
    return {"engine": "portfolio-next-session-v1", "config": asdict(cfg), "equity_curve": equity, "fills": fills,
        "cash_events": ledger, "metrics": {"return_pct": (values[-1] / cfg.initial_cash - 1) * 100,
        "benchmark_return_pct": (adjusted_price(benchmark[-1]) / adjusted_price(benchmark[0]) - 1) * 100,
        "sharpe": mean(returns) / volatility * sqrt(252) if volatility else None,
        "max_drawdown_pct": _max_drawdown_pct(values), "turnover": total_turnover / cfg.initial_cash,
        "var_95_pct": max(0, var) * 100, "es_95_pct": max(0, mean(tail)) * 100,
        "commission": total_fees, "slippage": total_slippage},
        "limitations": ["Pre-tax USD long-only research; not a broker execution model.",
            "Daily volume capacity is an end-of-day approximation; unfilled orders expire.",
            "Weight limits apply at signal time; opening gaps and limited liquidity can cause drift.",
            "Dividends are credited on the supplied event date; receivables and settlement are not modeled.",
            "Adjusted data must be point-in-time supplied; this engine cannot reconstruct missing vintages.",
            "No missing held-security valuations are silently forward-filled."]}
