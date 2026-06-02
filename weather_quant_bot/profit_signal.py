from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import Position


@dataclass
class ProfitSignal:
    position: Position
    gain_percent: float
    action: str
    rationale: str
    created_at: datetime


class ProfitSignalEngine:
    def __init__(
        self,
        levels: list[int] | None = None,
        de_risk_price: float = 0.70,
        exit_price: float = 0.90,
        stop_loss_price: float = 0.35,
        max_loss_percent: float = 55.0,
        hard_stop_price: float = 0.18,
    ) -> None:
        self.levels = sorted(levels or [200, 400, 900])
        self.de_risk_price = de_risk_price
        self.exit_price = exit_price
        self.stop_loss_price = stop_loss_price
        self.max_loss_percent = max_loss_percent
        self.hard_stop_price = hard_stop_price

    def evaluate(self, position: Position, current_price: float, uncertainty_c: float | None = None) -> ProfitSignal | None:
        if position.entry_price <= 0:
            return None
        gain = (current_price - position.entry_price) / position.entry_price * 100
        hit_level = next((level for level in reversed(self.levels) if gain >= level), None)
        position.current_price = current_price
        if current_price <= self.hard_stop_price:
            return ProfitSignal(
                position,
                gain,
                "HARD STOP LOSS",
                f"price fell to {current_price:.0%}; preserve remaining capital and reassess thesis manually",
                datetime.now(timezone.utc),
            )
        if current_price <= self.stop_loss_price and gain <= -self.max_loss_percent:
            return ProfitSignal(
                position,
                gain,
                "STOP LOSS",
                f"loss reached {gain:.0f}% and price is below {self.stop_loss_price:.0%}; thesis likely deteriorated",
                datetime.now(timezone.utc),
            )
        if current_price >= self.exit_price:
            return ProfitSignal(
                position,
                gain,
                "SELL/EXIT CHOICE",
                f"market price reached {current_price:.0%}; bank asymmetric payout unless near-lock is verified",
                datetime.now(timezone.utc),
            )
        if current_price >= self.de_risk_price and (uncertainty_c is None or uncertainty_c > 0.6):
            return ProfitSignal(
                position,
                gain,
                "DE-RISK",
                f"price reached {current_price:.0%} while uncertainty remains; sell enough to recover stake",
                datetime.now(timezone.utc),
            )
        if hit_level:
            return ProfitSignal(
                position,
                gain,
                "TAKE PROFIT",
                f"+{hit_level}% level hit; small-stake convex trades should avoid round-tripping gains",
                datetime.now(timezone.utc),
            )
        return None
