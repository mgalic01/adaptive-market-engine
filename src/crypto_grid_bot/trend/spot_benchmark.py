"""Risk-matched spot hold decisions for the frozen V3 comparison."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.decisions import DAY, DailyDecision
from crypto_grid_bot.trend.exclusions import CloseRequirement, ExclusionCalendar, UnavailableClose
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.pending import HOUR, DecisionDispatch, PendingDecision, PendingDecisions
from crypto_grid_bot.trend.runner import EquityState
from crypto_grid_bot.trend.sizing import daily_returns, size_portfolio
from crypto_grid_bot.trend.spot_account import SpotAccount, SpotAudit, _finite, _floor


@dataclass(frozen=True, slots=True)
class SpotDecisionInput:
    timestamp_ms: int
    targets: tuple[tuple[str, Decimal], ...]
    exit_reasons: tuple[tuple[str, frozenset[str]], ...]


@dataclass(frozen=True, slots=True)
class SpotRebalance:
    symbol: str
    timestamp_ms: int
    decision_ms: int
    target_weight: Decimal
    current_weight: Decimal
    requested_change: Decimal
    fill_start: int
    fill_end: int
    reason: str | None


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
        self.rebalances: list[SpotRebalance] = []
        self.close_requirements: tuple[CloseRequirement, ...] = ()
        self.exclusion_dust: list[tuple[int, str, Decimal, Decimal]] = []
        self.samples: list[tuple[int, Decimal]] = []
        self.daily_decisions: list[tuple[int, DailyDecision]] = []
        self._decision_inputs: list[SpotDecisionInput] = []
        self.equity_path: list[EquityState] = []
        self.peak = self.account.initial
        self.max_drawdown = Decimal(0)
        self.masked_held_hours: dict[str, int] = {}
        self._prices: dict[str, Decimal] = {}
        self._hour: int | None = None
        self.stopped: str | None = None

    @property
    def decision_inputs(self) -> tuple[SpotDecisionInput, ...]:
        """Immutable snapshots of the targets actually delivered to execution."""
        return tuple(self._decision_inputs)

    def _audit(self) -> None:
        audit = self.account.audit()
        self.audits.append(audit)
        if not audit.exact:
            raise ValueError(f"spot accounting identity failed: {audit}")

    def finish(
        self, last_unmasked_closes: Mapping[str, Decimal], *, reason: str = "completed"
    ) -> Decimal:
        """Adapter-proven in-window closes; no terminal trade or fee."""
        if self.stopped is not None:
            raise ValueError(f"runner stopped: {self.stopped}")
        try:
            if reason not in ("completed", "unavailable_exclusion_close"):
                raise ValueError("invalid terminal reason")
            if self._hour is None:
                raise ValueError("cannot finish before processing an hour")
            with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
                self._audit()
                stamp = self._hour + HOUR
                equity = self._mark(stamp, "terminal", last_unmasked_closes)
                self.samples.append((stamp, equity))
                self.stopped = reason
                return equity
        except Exception:
            self.stopped = "engine_failure"
            raise

    def missing_close_requires_fill(
        self, symbol: str, timestamp_ms: int, current_open: Decimal | None = None
    ) -> bool:
        """Classify retained quantity at its carried mark, without inventing a fill."""
        quantity = self.account.holdings.get(symbol, Decimal(0))
        if not quantity:
            return False
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            filters = self.filters[symbol]
            price = self._prices[symbol] if current_open is None else current_open
            _finite(price, positive=True)
            size = _floor(Fraction(quantity), filters.step_size)
            slipped = price * (1 - Decimal(".0005") * self.account.cost_multiple)
            if size < filters.min_quantity or size * slipped < filters.min_notional:
                self.exclusion_dust.append((timestamp_ms, symbol, quantity, price))
                return False
            return True

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
        self._decision_inputs.append(
            SpotDecisionInput(
                hour_ms,
                tuple(sorted(targets.items())),
                tuple(
                    sorted((symbol, frozenset(value)) for symbol, value in (reasons or {}).items())
                ),
            )
        )
        dispatch = self.pending.advance(hour_ms, targets, set(bars), reasons)
        self.dispatches.append((hour_ms, dispatch))
        for symbol, quantity in self.account.holdings.items():
            if quantity and symbol not in bars:
                self.masked_held_hours[symbol] = self.masked_held_hours.get(symbol, 0) + 1
        equity = self._mark(hour_ms, "open", prices)
        if hour_ms % DAY == HOUR:
            self.samples.append((hour_ms, equity))
        orders: list[tuple[str, Decimal, PendingDecision, Decimal, str | None]] = []
        for symbol, decision in dispatch.ready:
            held = self.account.holdings.get(symbol, Decimal(0))
            current = held * prices[symbol] / equity
            if decision.weight != 0 and abs(decision.weight - current) <= Decimal(".01"):
                orders.append((symbol, Decimal(0), decision, current, "inside_band"))
                continue
            step = self.filters[symbol].step_size
            target = _floor(Fraction(decision.weight * equity / prices[symbol]), step)
            change = target - held
            orders.append(
                (symbol, change, decision, current, "rounded_no_change" if not change else None)
            )
        for symbol, change, decision, current, reason in sorted(
            orders, key=lambda row: (row[1] > 0, row[0])
        ):
            first_fill = len(self.account.fills)
            if change:
                fills = self.account.execute(
                    symbol, change, prices[symbol], self.filters[symbol], hour_ms
                )
                reason = next((fill.reason for fill in fills if fill.reason is not None), None)
            self.rebalances.append(
                SpotRebalance(
                    symbol,
                    hour_ms,
                    decision.decision_ms,
                    decision.weight,
                    current,
                    change,
                    first_fill,
                    len(self.account.fills),
                    reason,
                )
            )
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
        self._excluded = {s: frozenset(months) for s, months in (excluded_months or {}).items()}

    @property
    def first_months(self) -> dict[str, str]:
        return dict(self._first)

    @property
    def excluded_months(self) -> dict[str, frozenset[str]]:
        return dict(self._excluded)

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


class SpotReplayExecutionError(RuntimeError):
    """Execution failure retaining the unfinished spot account as evidence."""

    def __init__(self, error: Exception, runner: SpotRunner) -> None:
        super().__init__(f"{type(error).__name__}: {error}")
        self.runner = runner


def replay_spot_benchmark(
    decisions: HoldDecisions,
    filters: Mapping[str, OrderFilters],
    hourly: Mapping[str, Sequence[Kline]],
    start_ms: int,
    end_ms_exclusive: int,
    *,
    cost_multiple: int = 1,
) -> SpotRunner:
    """Replay supplied, already validated/masked sources in a fresh spot account.

    This does not authorize historical dispatch or certify source provenance.
    Exclusions supplied to HoldDecisions must be the union of spot and futures
    exclusions. Retained dust keeps its last usable mark during excluded months.
    """
    runner = SpotRunner(filters, cost_multiple=cost_multiple)
    if set(hourly) != set(filters) or set(filters) != set(decisions.first_months):
        raise ValueError("replay input universes disagree")
    # The empty calendar validates the development-only daily window and hourly
    # inventory without importing futures' unavailable-close invalidity for dust.
    indexed = {}
    for symbol, rows in hourly.items():
        stamps = [row.open_ms for row in rows]
        if stamps != sorted(set(stamps)):
            raise ValueError("hourly rows must be unique and sorted")
        indexed[symbol] = {row.open_ms: row for row in rows}
    ExclusionCalendar({}).check_close_availability(
        start_ms,
        end_ms_exclusive,
        {symbol: frozenset(rows) for symbol, rows in indexed.items()},
    )
    first, excluded = decisions.first_months, decisions.excluded_months
    calendar = ExclusionCalendar(
        {
            symbol: frozenset(month for month in months if month >= first[symbol])
            for symbol, months in excluded.items()
        }
    )
    try:
        runner.close_requirements = calendar.check_close_availability(
            start_ms,
            end_ms_exclusive,
            {symbol: frozenset(rows) for symbol, rows in indexed.items()},
        )
    except UnavailableClose as exc:
        runner.close_requirements = exc.requirements
    try:
        closes: dict[str, Decimal] = {}
        for hour in range(start_ms, end_ms_exclusive, HOUR):
            if any(
                item.decision_ms == hour
                and item.fill_ms is None
                and runner.missing_close_requires_fill(
                    item.symbol,
                    hour,
                    indexed[item.symbol][hour].open if hour in indexed[item.symbol] else None,
                )
                for item in runner.close_requirements
            ):
                runner.finish(closes, reason="unavailable_exclusion_close")
                return runner
            month = datetime.fromtimestamp(hour // 1000, UTC).strftime("%Y-%m")
            bars = {}
            for symbol in sorted(filters):
                if first[symbol] > month or month in excluded.get(symbol, ()):
                    continue
                row = indexed[symbol].get(hour)
                if row is not None:
                    _finite(row.close, positive=True)
                    if not row.low <= row.close <= row.high:
                        raise ValueError("close outside hourly bar")
                    bars[symbol] = (row.open, row.low, row.high)
                    closes[symbol] = row.close
            targets = {}
            reasons = {}
            if hour % DAY == 0:
                decision = decisions.at(hour, run_end_ms=end_ms_exclusive)
                runner.daily_decisions.append((hour, decision))
                targets, reasons = decision.targets, decision.exit_reasons
            runner.step(hour, bars, targets, exit_reasons=reasons)
        runner.finish(closes)
    except Exception as exc:
        runner.stopped = "engine_failure"
        raise SpotReplayExecutionError(exc, runner) from exc
    return runner
