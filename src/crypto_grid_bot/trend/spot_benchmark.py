"""Risk-matched spot hold decisions for the frozen V3 comparison."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.decisions import DAY, DailyDecision
from crypto_grid_bot.trend.exclusions import ExclusionCalendar
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.pending import HOUR, DecisionDispatch, PendingDecisions
from crypto_grid_bot.trend.runner import EquityState
from crypto_grid_bot.trend.sizing import daily_returns, size_portfolio
from crypto_grid_bot.trend.spot_account import SpotAccount, SpotAudit, _finite, _floor


class SpotRunner:
    """Continuous spot settlement on supplied, prevalidated hourly bars.

    The adapter supplies eligibility/exclusion targets. No data access or funding
    occurs here. An exception poisons the run, including a partial fill batch.
    """

    def __init__(self, filters: Mapping[str, OrderFilters], *, cost_multiple: int = 1) -> None:
        self.filters = dict(filters)
        self.account = SpotAccount(cost_multiple=cost_multiple)
        self.pending = PendingDecisions()
        self.audits: list[SpotAudit] = []
        self.dispatches: list[tuple[int, DecisionDispatch]] = []
        self.samples: list[tuple[int, Decimal]] = []
        self.equity_path: list[EquityState] = []
        self.peak = self.account.initial
        self.max_drawdown = Decimal(0)
        self._prices: dict[str, Decimal] = {}
        self._hour: int | None = None
        self.stopped: str | None = None

    def _audit(self) -> None:
        audit = self.account.audit()
        self.audits.append(audit)
        if not audit.exact:
            raise ValueError(f"spot accounting identity failed: {audit}")

    def finish(self, last_unmasked_closes: Mapping[str, Decimal]) -> Decimal:
        """Adapter-proven in-window closes; no terminal trade or fee."""
        if self.stopped is not None:
            raise ValueError(f"runner stopped: {self.stopped}")
        try:
            if self._hour is None:
                raise ValueError("cannot finish before processing an hour")
            with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
                self._audit()
                stamp = self._hour + HOUR
                equity = self._mark(stamp, "terminal", last_unmasked_closes)
                self.samples.append((stamp, equity))
                self.stopped = "completed"
                return equity
        except Exception:
            self.stopped = "engine_failure"
            raise

    def _mark(self, stamp: int, kind: str, prices: Mapping[str, Decimal]) -> Decimal:
        equity = self.account.mark(prices)
        self.peak = max(self.peak, equity)
        drawdown = (self.peak - equity) / self.peak
        self.max_drawdown = max(self.max_drawdown, drawdown)
        self.equity_path.append(EquityState(stamp, kind, equity, self.peak, drawdown))
        return equity

    def step(
        self,
        hour_ms: int,
        bars: Mapping[str, tuple[Decimal, Decimal, Decimal]],
        new_targets: Mapping[str, Decimal] | None = None,
        *,
        exit_reasons: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        if self.stopped is not None:
            raise ValueError(f"runner stopped: {self.stopped}")
        try:
            with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
                self._step(hour_ms, bars, new_targets or {}, exit_reasons)
        except Exception:
            self.stopped = "engine_failure"
            raise

    def _step(
        self,
        hour_ms: int,
        bars: Mapping[str, tuple[Decimal, Decimal, Decimal]],
        targets: Mapping[str, Decimal],
        reasons: Mapping[str, frozenset[str]] | None,
    ) -> None:
        if self._hour is not None and hour_ms != self._hour + HOUR:
            raise ValueError("runner requires consecutive hours")
        if not set(bars) <= self.filters.keys() or not set(targets) <= self.filters.keys():
            raise ValueError("unknown bar or target symbol")
        if any(not v.is_finite() or not 0 <= v <= 1 for v in targets.values()):
            raise ValueError("spot target must be long-only")
        prices = dict(self._prices)
        for symbol, (opened, low, high) in bars.items():
            for value in (opened, low, high):
                _finite(value, positive=True)
            if not low <= opened <= high:
                raise ValueError("invalid bar")
            prices[symbol] = opened
        self._audit()
        dispatch = self.pending.advance(hour_ms, targets, set(bars), reasons)
        self.dispatches.append((hour_ms, dispatch))
        equity = self._mark(hour_ms, "open", prices)
        if hour_ms % DAY == HOUR:
            self.samples.append((hour_ms, equity))
        orders = []
        for symbol, decision in dispatch.ready:
            held = self.account.holdings.get(symbol, Decimal(0))
            current = held * prices[symbol] / equity
            if decision.weight != 0 and abs(decision.weight - current) <= Decimal(".01"):
                continue
            step = self.filters[symbol].step_size
            target = _floor(Fraction(decision.weight * equity / prices[symbol]), step)
            change = target - held
            if change:
                orders.append((symbol, change))
        for symbol, change in sorted(orders, key=lambda row: (row[1] > 0, row[0])):
            self.account.execute(symbol, change, prices[symbol], self.filters[symbol], hour_ms)
        self._mark(hour_ms, "post_fill", prices)
        # Frozen conservative order: favourable followed by adverse. All holdings
        # are long, so low and high apply across the portfolio together.
        for kind, index in (("favourable", 2), ("adverse", 1)):
            marks = {**prices, **{symbol: bar[index] for symbol, bar in bars.items()}}
            self._mark(hour_ms + HOUR - 1, kind, marks)
        self._audit()
        self._prices = prices
        self._hour = hour_ms


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
