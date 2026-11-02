from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ManualOrderTicket:
    symbol: str
    side: str
    quantity: float
    reference_price: float
    reason: str
    status: str = "requires_human_order"
    created_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "reference_price": self.reference_price,
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
            "disclaimer": "Manual review and human order entry are required. No live brokerage order was sent.",
        }


class ManualExecutionPlanner:
    def create_ticket(self, signal: dict, quantity: float = 1.0) -> dict[str, object]:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        side = "buy" if signal.get("recommended") else "hold"
        ticket = ManualOrderTicket(
            symbol=str(signal["symbol"]),
            side=side,
            quantity=quantity,
            reference_price=float(signal["latest_close"]),
            reason=f"Score {signal['score']} with stance {signal['stance']}",
        )
        return ticket.to_dict()
