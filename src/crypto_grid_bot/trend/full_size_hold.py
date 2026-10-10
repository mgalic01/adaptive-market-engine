"""Reported-only equal-cash spot hold over supplied unmasked hourly bars."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.runner import EquityState
from crypto_grid_bot.trend.spot_account import SpotAccount, SpotAudit, _finite, _floor

HOUR = 3600000
DAY = 24 * HOUR
END = month_bounds_ms("2025-01")[0]


@dataclass(slots=True)
class FullSizeHoldResult:
    start_ms: int
    end_ms_exclusive: int
    scheduled_ms: int
    budgets: dict[str, Decimal]
    account: SpotAccount = field(default_factory=SpotAccount)
    purchase_times: dict[str, int] = field(default_factory=dict)
    equity_path: list[EquityState] = field(default_factory=list)
    samples: list[tuple[int, Decimal]] = field(default_factory=list)
    audits: list[SpotAudit] = field(default_factory=list)
    masked_held_hours: dict[str, int] = field(default_factory=dict)
    missing_symbols: tuple[str, ...] = ()
    max_drawdown: Decimal = Decimal(0)
    reason: str | None = None


class FullSizeHoldExecutionError(ValueError):
    def __init__(self, cause: Exception, result: FullSizeHoldResult) -> None:
        super().__init__(str(cause))
        self.result = result


def replay_full_size_hold(
    hourly: Mapping[str, Sequence[Kline]],
    first_months: Mapping[str, str],
    filters: Mapping[str, OrderFilters],
    start_ms: int,
    end_ms_exclusive: int,
) -> FullSizeHoldResult:
    """Never sell, rebalance or add a later member; record delayed first attempts.

    Inputs are the separately validated full-size spot prices, including usable
    rows from excluded months. This does not read data or authorize dispatch.
    Filter-refused buys retain cash and their fill record; a missing price through
    the end makes the diagnostic unavailable. Engine failures retain partial state.
    """
    if (
        type(start_ms) is not int
        or type(end_ms_exclusive) is not int
        or start_ms % HOUR
        or end_ms_exclusive % HOUR
        or not 0 <= start_ms < end_ms_exclusive <= END
    ):
        raise ValueError("invalid development-only hourly boundaries")
    if set(hourly) != set(first_months) or set(filters) != set(first_months):
        raise ValueError("hold input universes differ")
    start_month = development_month(datetime.fromtimestamp(start_ms // 1000, UTC).strftime("%Y-%m"))
    first = {symbol: development_month(month) for symbol, month in first_months.items()}
    members = tuple(sorted(symbol for symbol, month in first.items() if month <= start_month))
    if not members:
        raise ValueError("no initial portfolio members")
    indexed = {}
    for symbol, rows in hourly.items():
        stamps = [row.open_ms for row in rows]
        if stamps != sorted(set(stamps)) or any(
            type(t) is not int or t < 0 or t >= END or t % HOUR for t in stamps
        ):
            raise ValueError("unique chronological development-only bars required")
        indexed[symbol] = {row.open_ms: row for row in rows}
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        result = FullSizeHoldResult(
            start_ms,
            end_ms_exclusive,
            start_ms + HOUR,
            dict.fromkeys(members, Decimal(10000) / len(members)),
        )
        prices: dict[str, Decimal] = {}
        closes: dict[str, Decimal] = {}
        peak = result.account.initial

        def audit() -> None:
            checked = result.account.audit()
            result.audits.append(checked)
            if not checked.exact:
                raise ValueError("full-size hold accounting identity failed")

        def mark(stamp: int, kind: str, values: Mapping[str, Decimal]) -> Decimal:
            nonlocal peak
            equity = result.account.mark(values)
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak
            result.max_drawdown = max(result.max_drawdown, drawdown)
            result.equity_path.append(EquityState(stamp, kind, equity, peak, drawdown))
            return equity

        try:
            for hour in range(start_ms, end_ms_exclusive, HOUR):
                bars = {s: indexed[s][hour] for s in members if hour in indexed[s]}
                for symbol, row in bars.items():
                    for value in (row.open, row.high, row.low, row.close):
                        _finite(value, positive=True)
                    if not row.low <= row.open <= row.high or not row.low <= row.close <= row.high:
                        raise ValueError("invalid full-size hold bar")
                    prices[symbol], closes[symbol] = row.open, row.close
                audit()
                for symbol, quantity in result.account.holdings.items():
                    if quantity and symbol not in bars:
                        result.masked_held_hours[symbol] = (
                            result.masked_held_hours.get(symbol, 0) + 1
                        )
                equity = mark(hour, "open", prices)
                if hour % DAY == HOUR:
                    result.samples.append((hour, equity))
                if hour >= result.scheduled_ms:
                    for symbol in members:
                        if symbol in result.purchase_times or symbol not in bars:
                            continue
                        # Floor the exact fee-inclusive budget to the market step.
                        unit_cost = prices[symbol] * Decimal("1.0005") * Decimal("1.001")
                        exact = Fraction(10000, len(members)) / Fraction(unit_cost)
                        quantity = _floor(exact, filters[symbol].step_size)
                        if quantity == 0:
                            # A positive sub-step intent lets SpotAccount record refusal.
                            with localcontext() as down:
                                down.rounding = ROUND_DOWN
                                quantity = Decimal(exact.numerator) / Decimal(exact.denominator)
                        result.account.execute(
                            symbol, quantity, prices[symbol], filters[symbol], hour
                        )
                        result.purchase_times[symbol] = hour
                mark(hour, "post_fill", prices)
                for kind, attribute in (("favourable", "high"), ("adverse", "low")):
                    mark(
                        hour + HOUR - 1,
                        kind,
                        {**prices, **{s: getattr(row, attribute) for s, row in bars.items()}},
                    )
                audit()
            terminal = mark(end_ms_exclusive, "terminal", closes)
            result.samples.append((end_ms_exclusive, terminal))
            audit()
            result.missing_symbols = tuple(s for s in members if s not in result.purchase_times)
            if result.missing_symbols:
                result.reason = "unavailable_first_purchase"
        except Exception as exc:
            result.reason = "engine_failure"
            raise FullSizeHoldExecutionError(exc, result) from exc
        return result
