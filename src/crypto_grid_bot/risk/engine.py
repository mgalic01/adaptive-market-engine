"""Fail-closed portfolio risk engine.

The limits are compared with the equities exactly, in Decimal: a float conversion of
the balances could put a drawdown or a daily loss a hair either side of a limit it sits
on. The reason texts keep their float formatting where a float can hold the base.
"""

from __future__ import annotations

from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, localcontext
from math import isfinite

from crypto_grid_bot.domain import PortfolioSnapshot, RiskAction, RiskDecision

# Enough digits for a limit times a prec-50 balance, and its difference, to stay exact,
# at any exponent a Decimal can have: no balance underflows or overflows the comparisons
# (Codex review of #159: 1e-1000119 compared as a 100% loss, 1e1000000 raised Overflow).
_CONTEXT = Context(prec=120, Emin=MIN_EMIN, Emax=MAX_EMAX)


def _exact(value: Decimal | float) -> Decimal | None:
    """``value`` as an exact Decimal (a float or int converts exactly); None unless finite."""
    number = value if isinstance(value, Decimal) else Decimal(value)
    return number if number.is_finite() else None


def _percent(base: Decimal, equity: Decimal) -> str:
    """The reason text's loss percentage, formatted from floats as it always was. A base
    a float cannot hold (``1e-1000`` becomes 0.0) is formatted in Decimal instead."""
    as_float = float(base)
    if as_float == 0 or not isfinite(as_float):
        with localcontext(_CONTEXT):
            return f"{(base - equity) / base:.2%}"
    return f"{(as_float - float(equity)) / as_float:.2%}"


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
        # The configured fractions as the exact Decimals they are written as.
        self._daily_loss_pause_pct = Decimal(str(daily_loss_pause_pct))
        self._soft_drawdown_pct = Decimal(str(soft_drawdown_pct))
        self._hard_drawdown_pct = Decimal(str(hard_drawdown_pct))
        self._maximum_data_age_seconds = maximum_data_age_seconds

    def evaluate(self, portfolio: PortfolioSnapshot) -> RiskDecision:
        equity = _exact(portfolio.active_equity)
        day_start = _exact(portfolio.day_start_equity)
        high = _exact(portfolio.high_water_mark)
        if (
            equity is None
            or day_start is None
            or high is None
            or equity < 0
            or min(day_start, high) <= 0
        ):
            return RiskDecision(RiskAction.PAUSE, ("invalid portfolio equity",))
        if not portfolio.balances_reconciled or not portfolio.orders_reconciled:
            return RiskDecision(
                RiskAction.PAUSE, ("exchange balances or orders are not reconciled",)
            )
        if not 0 <= portfolio.data_age_seconds <= self._maximum_data_age_seconds:
            return RiskDecision(RiskAction.PAUSE, ("market data age is invalid or stale",))
        if portfolio.emergency:
            return RiskDecision(RiskAction.EXIT, ("emergency flag is active",))

        with localcontext(_CONTEXT):
            # loss / base >= limit, compared as loss >= limit * base: no division, so an
            # equity exactly on a limit is on it. Both bases are positive (checked above).
            hard = high - equity >= self._hard_drawdown_pct * high
            daily = day_start - equity >= self._daily_loss_pause_pct * day_start
            soft = high - equity >= self._soft_drawdown_pct * high
        if hard:
            return RiskDecision(
                RiskAction.EXIT, (f"hard drawdown reached: {_percent(high, equity)}",)
            )
        if daily:
            return RiskDecision(
                RiskAction.PAUSE, (f"daily loss limit reached: {_percent(day_start, equity)}",)
            )
        if soft:
            # No sizing: the paper engine answers REDUCE with pause and drain (spec v1
            # amendment 1).
            return RiskDecision(
                RiskAction.REDUCE, (f"soft drawdown reached: {_percent(high, equity)}",)
            )
        return RiskDecision(RiskAction.ALLOW, ("risk checks passed",))
