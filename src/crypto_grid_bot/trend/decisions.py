"""Connect continuous spot signals and frozen sizing to daily target decisions."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.exclusions import ExclusionCalendar
from crypto_grid_bot.trend.signals import RULES, signal_series
from crypto_grid_bot.trend.sizing import SizingResult, daily_returns, size_portfolio

DAY = 86400000
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class DailyDecision:
    targets: dict[str, Decimal]
    signals: dict[str, Decimal]
    exit_reasons: dict[str, frozenset[str]]
    sizing: SizingResult | None


class DailyDecisions:
    """One precomputed signal history, shared by fresh training and OOS accounts.

    Input spot bars have already passed manifest integrity and exclusion masking.
    No files are read here. Missing daily bars retain recursive signal state.
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
        self._signals = {symbol: signal_series(bars) for symbol, bars in spot_bars.items()}
        self._days = {
            symbol: tuple(p.day_ms for p in points) for symbol, points in self._signals.items()
        }
        self._returns = {symbol: daily_returns(bars) for symbol, bars in spot_bars.items()}
        self._return_days = {
            symbol: tuple(p.day_ms for p in points) for symbol, points in self._returns.items()
        }
        self._exclusions = ExclusionCalendar(excluded_months or {})

    def at(
        self,
        decision_ms: int,
        rule: str | None,
        *,
        multiple: int = 2,
        pick_changed: bool = False,
    ) -> DailyDecision:
        forced = self._exclusions.zero_symbols(decision_ms)
        if rule is not None and rule not in RULES:
            raise ValueError("unknown frozen rule")
        if type(multiple) is not int or multiple not in (1, 2, 3):
            raise ValueError("invalid size multiple")
        month = datetime.fromtimestamp(decision_ms // 1000, UTC).strftime("%Y-%m")
        day = decision_ms - DAY
        eligible = sorted(symbol for symbol, first in self._first.items() if first <= month)
        signals = {}
        available = set()
        returns = {}
        for symbol in eligible:
            index = bisect_right(self._days[symbol], day) - 1
            point = self._signals[symbol][index] if index >= 0 else None
            signals[symbol] = point.rule(rule) if point is not None and rule is not None else ZERO
            if point is not None and point.day_ms == day:
                available.add(symbol)
            end = bisect_right(self._return_days[symbol], day)
            # Last 60 observations also contain every available return in the
            # last 60 calendar days (at most one return per day).
            returns[symbol] = self._returns[symbol][max(0, end - 60) : end]
        sizing = (
            None
            if rule is None
            else size_portfolio(signals, returns, day, excluded=forced, multiple=multiple)
        )
        weights = dict.fromkeys(eligible, ZERO) if sizing is None else sizing.weights
        targets = {
            symbol: weights[symbol]
            for symbol in eligible
            if symbol in available or symbol in forced or rule is None
        }
        reasons = {}
        for symbol in targets:
            why = set()
            if symbol in forced:
                why.add("excluded_month")
            if pick_changed or rule is None:
                why.add("pick_change")
            if rule is not None:
                if signals[symbol] == ZERO:
                    why.add("signal_zero")
                elif weights[symbol] == ZERO:
                    why.add("sizing")
            reasons[symbol] = frozenset(why)
        return DailyDecision(targets, signals, reasons, sizing)
