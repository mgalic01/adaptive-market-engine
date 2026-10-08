"""Risk-matched spot hold decisions for the frozen V3 comparison."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.decisions import DAY, DailyDecision
from crypto_grid_bot.trend.exclusions import ExclusionCalendar
from crypto_grid_bot.trend.sizing import daily_returns, size_portfolio


class HoldDecisions:
    """Constant long signals, with frozen m=1 sizing on closed spot history.

    Inputs must already be manifest-validated and exclusion-masked. Missing
    daily bars prevent replacement targets except for mandatory exclusions.
    """

    def __init__(
        self,
        spot_bars: Mapping[str, Sequence[Kline]],
        first_portfolio_month: Mapping[str, str],
        excluded_months: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        if set(spot_bars) != set(first_portfolio_month):
            raise ValueError("spot history and portfolio universe must agree")
        if not set(excluded_months or {}) <= spot_bars.keys():
            raise ValueError("unknown exclusion symbol")
        self._first = {}
        for symbol, month in first_portfolio_month.items():
            symbol_name(symbol)
            self._first[symbol] = development_month(month)
        self._returns = {symbol: daily_returns(bars) for symbol, bars in spot_bars.items()}
        self._return_days = {
            symbol: tuple(row.day_ms for row in rows) for symbol, rows in self._returns.items()
        }
        self._days = {
            symbol: frozenset(bar.open_ms for bar in bars) for symbol, bars in spot_bars.items()
        }
        self._exclusions = ExclusionCalendar(excluded_months or {})

    def at(self, decision_ms: int, *, run_end_ms: int | None = None) -> DailyDecision:
        forced = self._exclusions.zero_symbols(decision_ms, run_end_ms=run_end_ms)
        month = datetime.fromtimestamp(decision_ms // 1000, UTC).strftime("%Y-%m")
        day = decision_ms - DAY
        eligible = sorted(symbol for symbol, first in self._first.items() if first <= month)
        signals = {symbol: Decimal(0 if symbol in forced else 1) for symbol in eligible}
        returns = {}
        for symbol in eligible:
            end = bisect_right(self._return_days[symbol], day)
            returns[symbol] = self._returns[symbol][max(0, end - 60) : end]
        sizing = size_portfolio(signals, returns, day, excluded=forced, multiple=1)
        targets = {
            symbol: sizing.weights[symbol]
            for symbol in eligible
            if day in self._days[symbol] or symbol in forced
        }
        reasons = {
            symbol: frozenset(
                {"excluded_month"} if symbol in forced else {"sizing"} if weight == 0 else ()
            )
            for symbol, weight in targets.items()
        }
        return DailyDecision(targets, signals, reasons, sizing)
