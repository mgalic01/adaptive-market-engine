"""Fail-closed portfolio risk engine."""

from __future__ import annotations

from math import isfinite

from crypto_grid_bot.domain import PortfolioSnapshot, RiskAction, RiskDecision


class RiskEngine:
    def __init__(
        self,
        *,
        daily_loss_pause_pct: float,
        soft_drawdown_pct: float,
        hard_drawdown_pct: float,
        maximum_data_age_seconds: int,
    ) -> None:
        if not 0 < daily_loss_pause_pct < soft_drawdown_pct < hard_drawdown_pct < 1:
            raise ValueError("risk limits must be ordered between zero and one")
        if maximum_data_age_seconds <= 0:
            raise ValueError("maximum data age must be positive")
        self._daily_loss_pause_pct = daily_loss_pause_pct
        self._soft_drawdown_pct = soft_drawdown_pct
        self._hard_drawdown_pct = hard_drawdown_pct
        self._maximum_data_age_seconds = maximum_data_age_seconds

    def evaluate(self, portfolio: PortfolioSnapshot) -> RiskDecision:
        equities = (portfolio.active_equity, portfolio.day_start_equity, portfolio.high_water_mark)
        if any(not isfinite(value) or value < 0 for value in equities) or min(equities[1:]) <= 0:
            return RiskDecision(RiskAction.PAUSE, ("invalid portfolio equity",))
        if not portfolio.balances_reconciled or not portfolio.orders_reconciled:
            return RiskDecision(
                RiskAction.PAUSE,
                ("exchange balances or orders are not reconciled",),
            )
        if not 0 <= portfolio.data_age_seconds <= self._maximum_data_age_seconds:
            return RiskDecision(RiskAction.PAUSE, ("market data age is invalid or stale",))
        if portfolio.emergency:
            return RiskDecision(RiskAction.EXIT, ("emergency flag is active",))

        daily_loss = max(
            0.0,
            (portfolio.day_start_equity - portfolio.active_equity) / portfolio.day_start_equity,
        )
        drawdown = max(
            0.0,
            (portfolio.high_water_mark - portfolio.active_equity) / portfolio.high_water_mark,
        )
        if drawdown >= self._hard_drawdown_pct:
            return RiskDecision(
                RiskAction.EXIT,
                (f"hard drawdown reached: {drawdown:.2%}",),
            )
        if daily_loss >= self._daily_loss_pause_pct:
            return RiskDecision(
                RiskAction.PAUSE,
                (f"daily loss limit reached: {daily_loss:.2%}",),
            )
        if drawdown >= self._soft_drawdown_pct:
            # No sizing: the paper engine answers REDUCE with pause and drain (spec v1
            # amendment 1).
            return RiskDecision(
                RiskAction.REDUCE,
                (f"soft drawdown reached: {drawdown:.2%}",),
            )
        return RiskDecision(RiskAction.ALLOW, ("risk checks passed",))
