"""Continuous V3 synthetic/data-adapter runner, with strict engine audits."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.account import AccountingAudit, AccountMark, FillEvent, FuturesAccount
from crypto_grid_bot.trend.execution import HourResult, execute_hour
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.lifecycles import LifecycleLedger
from crypto_grid_bot.trend.pending import DecisionDispatch, PendingDecisions

HOUR = 3600000


@dataclass(frozen=True, slots=True)
class EquityState:
    timestamp_ms: int
    kind: str
    equity: Decimal
    peak: Decimal
    drawdown: Decimal


class AccountingFailure(RuntimeError):
    def __init__(self, audit: AccountingAudit) -> None:
        super().__init__(f"strict accounting identity failed: {audit}")
        self.audit = audit


class TrendRunner:
    """Supply every hour, with absent bars denoting masked/missing observations.

    New targets are already computed by frozen signals/sizing. This adapter does
    not authorize data loading or implement walk-forward selection. Any exception
    poisons the run; a partially processed hour must never be retried as valid.
    """

    def __init__(
        self, filters: Mapping[str, OrderFilters], *, multiple: int = 2, cost_multiple: int = 1
    ) -> None:
        if type(multiple) is not int or multiple not in (1, 2, 3):
            raise ValueError("multiple must be 1, 2 or 3")
        self.filters = dict(filters)
        self.multiple = multiple
        self.account = FuturesAccount(cost_multiple=cost_multiple)
        self.pending = PendingDecisions()
        self.lifecycles = LifecycleLedger()
        self._prices: dict[str, Decimal] = {}
        self._hour: int | None = None
        self.stopped: str | None = None
        self.masked_held_hours: dict[str, int] = {}
        self.hours: list[tuple[int, DecisionDispatch, HourResult]] = []
        self.audits: list[AccountingAudit] = []
        self.peak = self.account.initial
        self.max_drawdown = Decimal(0)
        self.equity_path: list[EquityState] = []
        self.daily_samples: list[tuple[int, Decimal]] = []

    def finish(self, last_unmasked_closes: Mapping[str, Decimal]) -> AccountMark:
        """Mark supplied in-window closes; never request a subsequent open.

        The data adapter must prove each close is the last unmasked close at or
        before the final processed hour. No closing trade or extra funding occurs.
        """
        if self.stopped is not None:
            raise ValueError(f"runner stopped: {self.stopped}")
        try:
            if self._hour is None:
                raise ValueError("cannot finish before processing an hour")
            mark = self.account.mark(last_unmasked_closes)
            audit = self.account.audit(last_unmasked_closes)
            self.audits.append(audit)
            if not audit.accepted:
                raise AccountingFailure(audit)
            stamp = self._hour + HOUR
            with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
                self.peak = max(self.peak, mark.equity)
                drawdown = (self.peak - mark.equity) / self.peak
                self.max_drawdown = max(self.max_drawdown, drawdown)
                self.equity_path.append(
                    EquityState(stamp, "terminal", mark.equity, self.peak, drawdown)
                )
            self.daily_samples.append((stamp, mark.equity))
            self.lifecycles.censor(
                stamp, self.account.positions, last_unmasked_closes, "end_of_run"
            )
            self.stopped = "completed"
            return mark
        except Exception:
            self.stopped = "engine_failure"
            raise

    def step(
        self,
        hour_ms: int,
        bars: Mapping[str, tuple[Decimal, Decimal, Decimal]],
        new_targets: Mapping[str, Decimal],
        funding: Mapping[int, Mapping[str, Decimal]],
        *,
        exit_reasons: Mapping[str, frozenset[str]] | None = None,
    ) -> HourResult:
        """Bars are (open, low, high); excluded months must be handled upstream."""
        if self.stopped is not None:
            raise ValueError(f"runner stopped: {self.stopped}")
        try:
            return self._step(hour_ms, bars, new_targets, funding, exit_reasons)
        except Exception:
            self.stopped = "engine_failure"
            raise

    def _step(
        self,
        hour_ms: int,
        bars: Mapping[str, tuple[Decimal, Decimal, Decimal]],
        new_targets: Mapping[str, Decimal],
        funding: Mapping[int, Mapping[str, Decimal]],
        exit_reasons: Mapping[str, frozenset[str]] | None,
    ) -> HourResult:
        if self._hour is not None and hour_ms != self._hour + HOUR:
            raise ValueError("runner requires consecutive hours")
        if not set(bars) <= self.filters.keys() or not set(new_targets) <= self.filters.keys():
            raise ValueError("unknown bar or target symbol")
        if any(not set(rates) <= self.filters.keys() for rates in funding.values()):
            raise ValueError("unknown funding symbol")
        prices = dict(self._prices)
        extremes = {}
        for symbol, (opened, low, high) in bars.items():
            if any(not isinstance(v, Decimal) or not v.is_finite() for v in (opened, low, high)):
                raise ValueError("invalid bar")
            if not 0 < low <= opened <= high:
                raise ValueError("invalid bar")
            prices[symbol] = opened
            extremes[symbol] = (low, high)
        pre_audit = self.account.audit(prices)
        self.audits.append(pre_audit)
        if not pre_audit.accepted:
            raise AccountingFailure(pre_audit)
        dispatch = self.pending.advance(hour_ms, new_targets, set(bars), exit_reasons)
        for symbol, position in self.account.positions.items():
            if position.quantity != 0 and symbol not in bars:
                self.masked_held_hours[symbol] = self.masked_held_hours.get(symbol, 0) + 1
        result = execute_hour(
            self.account,
            hour_ms,
            prices,
            extremes,
            {symbol: self.filters[symbol] for symbol in bars},
            {symbol: decision.weight for symbol, decision in dispatch.ready},
            funding,
            multiple=self.multiple,
        )
        self._prices = prices
        reasons_by_symbol = {symbol: set(d.exit_reasons) for symbol, d in dispatch.ready}
        plans = dict(result.plans)
        delevered = {id(fill) for check in result.checkpoints for fill in check.fills}
        event_reasons = {}
        batch = self.account.events_since(self.lifecycles.event_count)
        for index, event in enumerate(batch.events, batch.start):
            if not isinstance(event, FillEvent) or event.after.quantity != 0:
                continue
            reasons = set(reasons_by_symbol.get(event.fill.symbol, ()))
            if id(event.fill) in delevered:
                reasons = {"delevering"}
            elif event.fill.symbol in plans:
                plan = plans[event.fill.symbol]
                decision = dict(dispatch.ready)[event.fill.symbol]
                if decision.weight * event.before.quantity < 0:
                    reasons.add("flip")
                if "quantity_rounded_to_zero" in plan.adjustments:
                    reasons.add("sizing")
                if (
                    "dust_close" in plan.adjustments
                    or "minimum_quantity_reduction" in plan.adjustments
                ):
                    reasons.add("minimum_quantity")
            event_reasons[index] = reasons
        self.lifecycles.consume_batch(batch, event_reasons)
        for kind, mark in result.marks:
            if kind in ("favourable", "adverse"):
                for symbol in self.lifecycles.active:
                    self.lifecycles.observe(
                        symbol, self.account.positions[symbol], mark.prices[symbol]
                    )
        if result.reason == "liquidation":
            if self.account.liquidation is None:
                raise ValueError("missing liquidation evidence")
            self.lifecycles.censor(
                self.account.liquidation.timestamp_ms,
                self.account.positions,
                result.marks[-1][1].prices,
                "liquidation",
            )
        self._hour = hour_ms
        self.hours.append((hour_ms, dispatch, result))
        if hour_ms % (24 * HOUR) == HOUR:
            self.daily_samples.append((hour_ms, result.marks[0][1].equity))
        funding_times = iter(sorted(funding))
        funding_stamp = hour_ms
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            for kind, mark in result.marks:
                stamp = hour_ms
                if kind == "funding":
                    funding_stamp = next(funding_times)
                if kind.startswith("funding"):
                    stamp = funding_stamp
                elif kind in ("favourable", "adverse"):
                    stamp = hour_ms + HOUR - 1
                self.peak = max(self.peak, mark.equity)
                drawdown = (self.peak - mark.equity) / self.peak
                self.max_drawdown = max(self.max_drawdown, drawdown)
                self.equity_path.append(EquityState(stamp, kind, mark.equity, self.peak, drawdown))
        if result.reason in ("no_tradable_position", "leverage_not_restored"):
            self.lifecycles.censor(
                self.equity_path[-1].timestamp_ms,
                self.account.positions,
                result.marks[-1][1].prices,
                result.reason,
            )
        audit = self.account.audit(result.marks[-1][1].prices)
        self.audits.append(audit)
        if not audit.accepted:
            raise AccountingFailure(audit)
        self.stopped = result.reason
        return result
