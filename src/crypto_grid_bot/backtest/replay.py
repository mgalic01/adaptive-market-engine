"""Historical replay of the paper engine on verified Binance klines.

Kline-to-quote adapter (the explicit, tested adapter BACKTEST_PLAN.md requires):

* Each 1m bar becomes four quotes (open, first extreme, second extreme, close) at
  +0/+9/+19/+29 s, all under one epoch, so an order created inside a bar cannot fill
  until a later bar. ``high_first`` visits the high before the low; ``low_first`` the
  reverse. The true order is unknown, so both are reported.
* Klines have no bid/ask, and OHLC does not reveal whether an extreme was buyer- or
  seller-initiated. The adapter *assumes* the high lifted the ask (ask = high, bid one
  assumed spread lower) and the low hit the bid (bid = low, ask one spread higher);
  open and close are mid prices. Every price rounds outward to today's tick. The
  engine still requires a limit to be crossed by slippage, so touching never fills.
* Liquidity: taker-sell volume can fill resting buys and taker-buy volume resting
  sells. Each side's bar volume is split evenly over the four quotes and the engine's
  participation cap applies to each share, so a bar's volume is never spent twice.
  An even split is an assumption, not observed volume at those prices.
* These are scenarios, not proven bounds: the two paths are not a worst case, and
  the +0/9/19/29 s stamps compress a minute into 29 s, which can affect recovery and
  range timers. They are simulation times, not observations.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections import Counter, deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from pathlib import Path
from typing import Any, Protocol

from crypto_grid_bot.backtest.dataset import funding_local_path, is_funding, local_path
from crypto_grid_bot.backtest.features import FEATURE_VERSION, FeatureEngine, Inputs
from crypto_grid_bot.backtest.funding import (
    FIRST_ARCHIVE_MONTH,
    FundingRecord,
    FundingSignal,
    read_funding_archive,
)
from crypto_grid_bot.backtest.klines import Kline, aggregate, read_archive, read_archive_repaired
from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals, RiskDecision
from crypto_grid_bot.market_data.parsing import DataError
from crypto_grid_bot.simulation.execution import exit_state
from crypto_grid_bot.simulation.inventory_cap import mark as unit_mark
from crypto_grid_bot.simulation.models import (
    ONE,
    ZERO,
    Account,
    LimitOrder,
    MarketRules,
    Quote,
    floor_step,
    timestamp,
)
from crypto_grid_bot.simulation.runner import Frame, PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.trend_switch import MINIMUM_DAILY_WARMUP, TrendSchedule
from crypto_grid_bot.strategy.cycle import CycleSchedule, CycleSignal
from crypto_grid_bot.strategy.order_flow import FLOW_BARS, taker_buy_share
from crypto_grid_bot.strategy.volume_exit import VolumeHistory

PATH_MODES = ("high_first", "low_first")
# Scorer context lines that precede its actual failure reasons.
_CONTEXT = ("base quality", "regime fit", "news multiplier")
POINT_OFFSETS_S = (0, 9, 19, 29)
# How long each quote's observation stands within its minute: until the next quote, the
# last until the minute ends.
POINT_SPANS_MS = tuple(
    1000 * (end - start)
    for start, end in zip(POINT_OFFSETS_S, (*POINT_OFFSETS_S[1:], 60), strict=True)
)
QUARTER = Decimal("0.25")
HOUR_MS = 3_600_000
# Revolut X allows 1,000 order-placement requests per day. Cancellations are counted
# too, which is conservative if the exchange meters them separately.
DAILY_REQUEST_BUDGET = 1000


@dataclass(frozen=True)
class RunConfig:
    symbol: str
    path_mode: str
    gated: bool  # False = same grid mechanics with the regime/eligibility gate removed
    rules: MarketRules
    initial_quote: Decimal
    spread: Decimal  # fraction, e.g. 0.0005 for 0.05%


def _round(value: Decimal, tick: Decimal, rounding: str) -> Decimal:
    return (value / tick).to_integral_value(rounding=rounding) * tick


def bar_quotes(
    kline: Kline, symbol: str, path_mode: str, spread: Decimal, tick: Decimal
) -> list[Quote]:
    if path_mode not in PATH_MODES:
        raise ValueError("unknown path mode")
    extremes = ("high", "low") if path_mode == "high_first" else ("low", "high")
    half = spread / 2
    points: list[tuple[Decimal, Decimal]] = []
    for kind in ("open", *extremes, "close"):
        if kind == "high":
            ask = _round(kline.high, tick, ROUND_CEILING)
            bid = _round(kline.high * (ONE - spread), tick, ROUND_FLOOR)
        elif kind == "low":
            bid = _round(kline.low, tick, ROUND_FLOOR)
            ask = _round(kline.low * (ONE + spread), tick, ROUND_CEILING)
        else:
            price = kline.open if kind == "open" else kline.close
            bid = _round(price * (ONE - half), tick, ROUND_FLOOR)
            ask = _round(price * (ONE + half), tick, ROUND_CEILING)
        bid = max(bid, tick)
        ask = max(ask, bid + tick)
        points.append((bid, ask))
    taker_sell = (kline.volume - kline.taker_buy_base) * QUARTER
    taker_buy = kline.taker_buy_base * QUARTER
    quotes = []
    for index, ((bid, ask), offset) in enumerate(zip(points, POINT_OFFSETS_S, strict=True)):
        when = datetime.fromtimestamp(kline.open_ms / 1000 + offset, UTC).isoformat()
        event_id = f"{symbol}/{kline.open_ms}/{index}"
        quotes.append(Quote(event_id, symbol, when, when, bid, ask, taker_buy, taker_sell))
    return quotes


def reason_key(decision: str, reason: str) -> str:
    """Group decision reasons by cause: drop scorer context, mask numbers."""
    clauses = [c.strip() for c in reason.split(";") if c.strip()]
    causes = [c for c in clauses if not c.startswith(_CONTEXT)] or clauses[:1]
    return decision + ": " + re.sub(r"\d+(\.\d+)?", "#", "; ".join(causes))[:120]


def depth_multiple(
    minute_quote_volume: float, account: Account, rules: MarketRules, bid: Decimal
) -> float:
    """Per-minute quote volume over the largest buy the engine could place in this step.

    ``_open_grid`` spreads 80% of unprotected cash over the passive buy pairs below
    price; with a single pair that one order takes it all. Within one step the engine
    can first sell, settle and then reopen, so the bound counts every cash source that
    step could release: all resting sells filled at their limits and all unreserved
    inventory sold at the current ``bid`` (no fee deducted, so it stays an upper
    bound). Pending reserve is excluded; secured reserve has already left cash.
    Only the current quote is used, never later prices in the bar. Traded volume is
    a liquidity proxy, not observed book depth.
    """
    resting_sells = sum(
        (o.price * o.remaining for o in account.orders.values() if o.side == "sell"), ZERO
    )
    unreserved = max(ZERO, account.inventory - account.reserved_base())
    releasable = account.cash - account.pending + resting_sells + unreserved * bid
    largest_order = max(Decimal("0.8") * releasable, rules.minimum_notional)
    return minute_quote_volume / float(largest_order)


def signals_for(inputs: Inputs, observed_at: datetime, *, gated: bool) -> MarketSignals:
    if not gated:
        # Ungated baseline: a quiet, fully trusted range, so only risk limits intervene.
        # Degenerate history still vetoes entries through zero data quality.
        return MarketSignals(
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            10.0,
            data_quality=0.0 if inputs.degenerate else 1.0,
            observed_at=observed_at,
        )
    return MarketSignals(
        inputs.trend,
        inputs.breadth,
        inputs.momentum,
        inputs.volatility_health,
        inputs.liquidity_health,
        inputs.adx,
        data_quality=inputs.market_quality,
        news_risk=0.0,  # ABSENT: no historical news source; reported, not assumed safe
        emergency=False,
        structure_alignment=inputs.structure_alignment,
        observed_at=observed_at,
    )


def candidate_for(
    inputs: Inputs, symbol: str, spread_pct: float, depth: float, *, gated: bool
) -> CandidateMetrics:
    if not gated:
        return CandidateMetrics(symbol, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, spread_pct, 1e9)
    return CandidateMetrics(
        symbol,
        inputs.range_quality,
        inputs.net_grid_edge,
        inputs.liquidity_quality,
        inputs.downside_quality,
        inputs.pair_quality,
        0.0,  # ABSENT news component
        spread_pct,
        depth,
    )


@dataclass
class Metrics:
    bars: int = 0
    warmup_bars: int = 0
    frames: int = 0
    buys: int = 0
    sells: int = 0
    buy_notional: Decimal = ZERO
    sell_notional: Decimal = ZERO
    buy_fees: Decimal = ZERO
    sell_fees: Decimal = ZERO
    bought: Decimal = ZERO
    sold: Decimal = ZERO
    grids_opened: int = 0
    range_exits: int = 0
    bars_with_inventory: int = 0
    bars_with_orders: int = 0
    exposure_sum: Decimal = ZERO
    peak_equity: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    final_equity: Decimal = ZERO
    halted_at: str = ""
    halt_reason: str = ""
    transient_pauses: int = 0
    first_bar_ms: int = 0
    last_bar_ms: int = 0
    hold_final: Decimal = ZERO
    hold_max_drawdown: Decimal = ZERO
    regimes: Counter[str] = field(default_factory=Counter)
    decisions: Counter[str] = field(default_factory=Counter)
    reasons: Counter[str] = field(default_factory=Counter)
    # (hour open ms, strategy total equity, buy-and-hold value) at each hour's first bar.
    hourly_equity: list[tuple[int, str, str]] = field(default_factory=list)
    # Exchange order requests (placements + cancellations) per UTC day, e.g. "2024-01-05".
    requests_by_day: Counter[str] = field(default_factory=Counter)
    # Average-cost attribution of realised profit (after fees) by kind of sell.
    cost_basis: Decimal = ZERO  # quote paid, fees included, for inventory still held
    grid_sell_pnl: Decimal = ZERO  # resting grid sells (maker)
    exit_pnl: Decimal = ZERO  # marketable exits and liquidation (taker)
    exit_sells: int = 0
    # Realised P&L of exit/ sells by the engine's exit reason (range_exit, drain, liquidation).
    exit_pnl_by_reason: dict[str, Decimal] = field(default_factory=dict)
    # Completed cycles: grid sells (child ".../sell" orders) that filled completely.
    completed_cycles: int = 0
    cycles_by_week: Counter[str] = field(default_factory=Counter)
    # Active equity against the engine's reserve-adjusted risk high-water mark, sampled at
    # every risk evaluation (the basis of the runtime's soft/hard drawdown breakers).
    active_max_drawdown: Decimal = ZERO
    risk_evaluations: int = 0
    hard_drawdown_halts: int = 0  # halt instances of category drawdown, not evaluations
    # Spec v1 amendment 1: committed soft-drawdown rebases and automatic restarts, and
    # (D7) the episodes that closed without a rebase because the account had recovered.
    rebases: int = 0
    closes: int = 0
    restarts: int = 0
    # Frames whose marketable exit was refused because the order would be below the
    # exchange minimum notional ("depth": this frame's participation chunk; "dust": the
    # whole unreserved position). A refusal sells nothing, so it is invisible in the
    # fill journal; without these counters a permanently stalled exit looks like a
    # quiet account. ``final_*`` come from the account at the run's last quote
    # (execution.exit_state), not from the last refusal, so a partial fill or an idle
    # frame at the end cannot hide an unfinished exit or a held remainder.
    exit_blocked_frames: int = 0
    exit_blocked_by_kind: Counter[str] = field(default_factory=Counter)
    exit_blocked_streak: int = 0
    max_exit_blocked_streak: int = 0
    max_exit_blocked_notional: Decimal = ZERO
    final_exit_blocked: str = ""
    final_blocked_notional: Decimal = ZERO
    # Spec v1 §3's "Reported" values of variants E, G and H, as row fields
    # (``VariantReport``); empty in any other run, whose rows keep their exact layout.
    variant: dict[str, Any] = field(default_factory=dict)
    # Spec v1 §5 rule 1's per-run mask report (``MaskCounts``); zero in a run with no mask,
    # whose rows keep their exact layout.
    masked_hours: int = 0
    days_skipped_for_masks: int = 0
    fills_after_masked_span: int = 0


def record_exit_block(metrics: Metrics, blocked: str, notional: Decimal) -> None:
    """Record one frame's exit refusal (``blocked`` empty means the exit was not refused)."""
    if not blocked:
        metrics.exit_blocked_streak = 0
        return
    metrics.exit_blocked_frames += 1
    metrics.exit_blocked_by_kind[blocked] += 1
    metrics.exit_blocked_streak += 1
    metrics.max_exit_blocked_streak = max(
        metrics.max_exit_blocked_streak, metrics.exit_blocked_streak
    )
    metrics.max_exit_blocked_notional = max(metrics.max_exit_blocked_notional, notional)


class RequestCountingOrders(dict[str, LimitOrder]):
    """An account's order book that counts what an exchange would be sent.

    Every new order is one placement. Removing an order that still has quantity left
    is one cancellation; removing a fully filled order costs nothing. Counting at the
    operation catches orders placed and cancelled within one step, which before/after
    snapshots cannot see (for example a reentry buy cancelled when the account goes
    flat).
    """

    requests: int = 0

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.requests = 0
        # IDs of orders removed because they filled completely, in removal order.
        self.completed: list[str] = []

    def __setitem__(self, key: str, order: LimitOrder) -> None:
        self.requests += int(key not in self)
        super().__setitem__(key, order)

    def __delitem__(self, key: str) -> None:
        if self[key].remaining > ZERO:
            self.requests += 1
        else:
            self.completed.append(key)
        super().__delitem__(key)

    def clear(self) -> None:
        self.requests += sum(1 for order in self.values() if order.remaining > ZERO)
        super().clear()

    def pop(self, *args: Any) -> Any:
        raise NotImplementedError("remove orders with del so cancellations are counted")

    def popitem(self) -> tuple[str, LimitOrder]:
        raise NotImplementedError("remove orders with del so cancellations are counted")


def order_requests(
    orders: RequestCountingOrders, since: int, fills: Sequence[dict[str, Any]]
) -> int:
    """Requests sent during one step: book operations since ``since`` plus marketable
    exits, which are placed and filled at once without entering the book."""
    exits = sum(1 for fill in fills if str(fill["order_id"]).startswith("exit/"))
    return orders.requests - since + exits


class FillJournal(Protocol):
    """The fill totals the grid replay and variant D both keep (``Metrics``, ``TrendMetrics``)."""

    buys: int
    sells: int
    buy_notional: Decimal
    sell_notional: Decimal
    buy_fees: Decimal
    sell_fees: Decimal
    bought: Decimal
    sold: Decimal
    cost_basis: Decimal


def journal_fill(
    journal: FillJournal, side: str, price: Decimal, quantity: Decimal, fee: Decimal
) -> Decimal | None:
    """Add one fill to an average-cost journal; the realised P&L (after fees) of a sell,
    None for a buy. Call it at the simulator's precision 50 (see ``_record_fills``)."""
    notional = price * quantity
    if side == "buy":
        journal.buys += 1
        journal.buy_notional += notional
        journal.buy_fees += fee
        journal.bought += quantity
        journal.cost_basis += notional + fee
        return None
    held = journal.bought - journal.sold
    cost = journal.cost_basis * quantity / held if held > ZERO else ZERO
    journal.cost_basis -= cost
    journal.sells += 1
    journal.sell_notional += notional
    journal.sell_fees += fee
    journal.sold += quantity
    return notional - fee - cost


def _record_fills(
    metrics: Metrics, fills: Sequence[dict[str, Any]], exit_reason: str | None = None
) -> Decimal:
    """Journal one frame's fills; the realised P&L of its marketable exits."""
    exits = ZERO
    if not fills:
        return exits
    # PaperSimulator.step updates balances at precision 50. Preserve the same fill
    # amounts here: the caller's default precision (28) can round valid 18-place
    # prices/quantities and make the independent cash/fee identities fail.
    with localcontext() as context:
        context.prec = 50
        for fill in fills:
            pnl = journal_fill(
                metrics,
                fill["side"],
                Decimal(fill["price"]),
                Decimal(fill["quantity"]),
                Decimal(fill["fee"]),
            )
            if pnl is None:
                continue
            if str(fill["order_id"]).startswith("exit/"):
                metrics.exit_pnl += pnl
                metrics.exit_sells += 1
                reason = exit_reason or "unlabelled"
                metrics.exit_pnl_by_reason[reason] = (
                    metrics.exit_pnl_by_reason.get(reason, ZERO) + pnl
                )
                exits += pnl
            else:
                metrics.grid_sell_pnl += pnl
    return exits


class MaskCounts(Protocol):
    """Spec v1 §5 rule 1's per-run mask report, which the grid replay and variant D both
    keep (``Metrics``, ``TrendMetrics``): "Each run reports its masked hours, skipped days
    (rule 3) and fills after a masked span (rule 4)"."""

    masked_hours: int
    days_skipped_for_masks: int
    fills_after_masked_span: int


def mask_report(counts: MaskCounts) -> dict[str, int]:
    """The mask report's row fields, each only when non-zero, so that a run with no mask
    keeps its exact row (spec v1 §6: the stage-1 identity check lets these fields differ
    only as empty or zero)."""
    fields = {
        "masked_hours": counts.masked_hours,
        "days_skipped_for_masks": counts.days_skipped_for_masks,
        "fills_after_masked_span": counts.fills_after_masked_span,
    }
    return {key: value for key, value in fields.items() if value}


class MaskedSpans:
    """The pair's masked hours as a replay meets them (spec v1 §5 rules 1 and 4).

    ``hours`` is the number of masked hours inside the evaluation ``window`` [start, end).
    ``first_after(open_ms)``, called once for each replayed minute in time order, says
    whether that minute is the first after a masked span: a masked hour lies after the
    previous replayed minute's hour and before this minute's, or is the hour just before
    this minute's. A gap that no masked hour explains, such as feature warm-up or minutes
    missing without a mask, is not a masked span, and a run's first replayed minute has no
    minute before it.
    """

    def __init__(self, masked: frozenset[int], window: tuple[int, int] | None) -> None:
        if masked and window is None:
            raise ValueError("masked hours are reported against the evaluation window")
        start, end = window or (0, 0)
        self.hours = sum(1 for hour in masked if start <= hour < end)
        self._masked = masked
        self._sorted = sorted(masked)
        self._previous: int | None = None

    def first_after(self, open_ms: int) -> bool:
        hour = open_ms // HOUR_MS * HOUR_MS
        previous, self._previous = self._previous, hour
        if previous is None or hour == previous:
            return False
        between = bisect_left(self._sorted, hour) - bisect_left(self._sorted, previous + HOUR_MS)
        return between > 0 or hour - HOUR_MS in self._masked


class BuyAndHold:
    """Buy once at the first evaluated bar (ask + slippage + taker fee); conservative marks."""

    def __init__(self, run: RunConfig, first: Kline) -> None:
        rules = run.rules
        ask = _round(first.open * (ONE + run.spread / 2), rules.tick_size, ROUND_CEILING)
        price = ask * (ONE + rules.slippage_rate)
        self.quantity = floor_step(
            run.initial_quote / (price * (ONE + rules.taker_fee)), rules.quantity_step
        )
        self.cash = run.initial_quote - self.quantity * price * (ONE + rules.taker_fee)
        self.run = run
        self.peak = self.value = run.initial_quote
        self.max_drawdown = ZERO

    def mark(self, quote: Quote) -> None:
        """Mark at a quote's bid, sampled at the same quotes as the strategy (P2)."""
        self.value = self.cash + self.quantity * unit_mark(quote, self.run.rules)
        self.peak = max(self.peak, self.value)
        self.max_drawdown = max(self.max_drawdown, (self.peak - self.value) / self.peak)


class VariantReport:
    """Spec v1 §3's "Reported" values of variants E, G and H, gathered bar by bar and
    frame by frame for the row fields of a run that has them (``fields``).

    * E: its decisions by outcome; the hours outside past each extended episode's
      6-hour mark, until the extension ended (its exit, a return inside, a halt or the
      run's end); and its extended exits' realised P&L next to the P&L the same sales
      would have had at the bid of the 6-hour mark (a diagnostic only: it ignores fees,
      liquidity and residual inventory).
    * G: the new grids it blocked, one for each run of frames on which it vetoed one;
      the hours its gate was closed, each quote's state standing until the next quote
      (the last until its minute ends), over the evaluated minutes; and the lag from
      each settlement to the first evaluated quote that used it.
    * H: the evaluated bars by phase, by the rule in force and with the ATH unavailable,
      each as at the bar's last quote, and the grids opened only because of H3, with their
      P&L: total equity from opening until the grid ended or was replaced (or the run
      ended), with the residue the account held at opening set aside, as it is not the
      grid's: its mark, and its proceeds once an exit sells it (exits sell it first).
    """

    def __init__(
        self, policy: SimulationPolicy, funding: Sequence[FundingRecord], rules: MarketRules
    ) -> None:
        self.volume, self.gate, self.cycle = (
            policy.volume_exit,
            policy.funding_gate,
            policy.cycle_gate,
        )
        self.rules = rules
        self.checks: Counter[str] = Counter()
        self.extra = timedelta(0)
        # E's running extension: (t0, its 6-hour mark, the bid there); then the bid of
        # that mark while the extended exit sells.
        self.extension: tuple[str, datetime, Decimal] | None = None
        self.exit_bid: Decimal | None = None
        self.exits, self.exit_pnl, self.exit_pnl_at_mark = 0, ZERO, ZERO
        records = sorted(funding, key=lambda record: record.calc_time_ms)
        self.calc_ms = [record.calc_time_ms for record in records]
        self.usable_ms = [record.usable_ms for record in records]
        self.applied: int | None = None  # records in effect at the previous quote
        self.lags_ms: list[int] = []
        self.blocked_grids, self.vetoing, self.closed_ms = 0, False, 0
        self.phases: Counter[str] = Counter()
        self.cycle_rules: Counter[str] = Counter()
        self.no_ath = 0
        self.h3_grids, self.h3_pnl = 0, ZERO
        # The open H3 grid's own total equity at opening, without the residue the account
        # held then, which counts as sold at each exit's proceeds; and what is left of it.
        self.h3_base: Decimal | None = None
        self.h3_residue = ZERO

    def observation(self, at_ms: int, span_ms: int, funding_blocks: bool | None) -> None:
        """One evaluated quote, before its frame: G's gate, closed or not for the
        ``span_ms`` its observation stands, and the settlements it uses from it on."""
        if self.gate:
            self.closed_ms += span_ms * int(funding_blocks is not False)
            if self.applied is None:  # those usable before the first quote act before it
                self.applied = bisect_left(self.usable_ms, at_ms)
            count = bisect_right(self.usable_ms, at_ms)
            self.lags_ms += [at_ms - calc for calc in self.calc_ms[self.applied : count]]
            self.applied = count

    def frame(
        self,
        report: dict[str, Any],
        account: Account,
        quote: Quote,
        equity: Decimal,
        exit_pnl: Decimal,
    ) -> None:
        """One frame's outcome; ``equity`` is total equity after it, ``exit_pnl`` the
        realised P&L of its marketable exits."""
        if "regime" not in report:
            return  # a rejected frame: nothing happened
        observed = timestamp(quote.observed_at)
        if self.volume:
            self._volume(report, account, quote, observed, exit_pnl)
        if self.gate:
            vetoed = report.get("entry_veto") == "G"
            self.blocked_grids += int(vetoed and not self.vetoing)
            self.vetoing = vetoed
        if self.cycle:
            with localcontext() as context:
                context.prec = 50  # the simulator's precision: these sums are exact
                self._h3(report, account, quote, equity)

    def _h3(self, report: dict[str, Any], account: Account, quote: Quote, equity: Decimal) -> None:
        """H3's grids: the residue an exit sells, the P&L of a grid that ended or was
        replaced, and a grid opened only because of H3."""
        if self.h3_base is not None:
            for fill in report["fills"]:
                if self.h3_residue and str(fill["order_id"]).startswith("exit/"):
                    quantity = Decimal(fill["quantity"])
                    sold = min(self.h3_residue, quantity)
                    fee = Decimal(fill["fee"]) * sold / quantity
                    self.h3_base += sold * Decimal(fill["price"]) - fee
                    self.h3_residue -= sold
            if report["opened"] or not account.grid_lower:
                self.h3_pnl += self._h3_pnl(self.h3_base, quote, equity)
                self.h3_base = None
        if report["cycle"].get("h3_only"):
            # The harvest that opened it left only a residue no order could sell.
            self.h3_grids += 1
            self.h3_residue = account.inventory
            self.h3_base = equity - self.h3_residue * unit_mark(quote, self.rules)

    def _h3_pnl(self, base: Decimal, quote: Quote, equity: Decimal) -> Decimal:
        """The open H3 grid's P&L at ``quote``: total equity, less the residue left at its
        mark, less the grid's own equity at opening (``base``)."""
        return equity - self.h3_residue * unit_mark(quote, self.rules) - base

    def _volume(
        self,
        report: dict[str, Any],
        account: Account,
        quote: Quote,
        observed: datetime,
        exit_pnl: Decimal,
    ) -> None:
        if "volume_check" in report:
            self.checks[report["volume_check"]] += 1
            if report["volume_check"] == "extended":
                self.extension = (account.volume_since, observed, quote.bid)
        if self.extension is not None:
            since, mark, bid = self.extension
            running = (
                account.volume_check == "extended"
                and account.volume_since == since
                and bool(account.outside_last)
                and not account.halt
            )
            if not running:
                self.extra += observed - mark
                self.extension = None
                if account.range_exit:  # ended by its own exit, at t0 + 12 h
                    self.exits += 1
                    self.exit_bid = bid
        if self.exit_bid is not None:
            if report.get("exit_reason") == "range_exit":
                with localcontext() as context:
                    context.prec = 50
                    self.exit_pnl += exit_pnl
                    self.exit_pnl_at_mark += exit_pnl + sum(
                        (
                            Decimal(fill["quantity"]) * (self.exit_bid - Decimal(fill["price"]))
                            + Decimal(fill["fee"])
                            for fill in report["fills"]
                            if str(fill["order_id"]).startswith("exit/")
                        ),
                        ZERO,
                    )
            if not account.range_exit:
                self.exit_bid = None

    def bar_end(self, report: dict[str, Any], cycle: CycleSignal | None) -> None:
        """One evaluated minute, after its quotes: H's phase, rule and ATH, from its last
        quote's report and signal."""
        if self.cycle and "cycle" in report:
            self.phases[str(report["cycle"]["phase"])] += 1
            self.cycle_rules[str(report["cycle"]["rule"])] += 1
        if self.cycle and cycle is not None:
            self.no_ath += int(cycle.discounted is None)

    def fields(self, last: Quote | None, equity: Decimal) -> dict[str, Any]:
        """The row fields, counting an extension or an H3 grid the run ended in up to its
        last quote."""
        if self.extension is not None and last is not None:
            self.extra += timestamp(last.observed_at) - self.extension[1]
        if self.h3_base is not None and last is not None:
            with localcontext() as context:
                context.prec = 50
                self.h3_pnl += self._h3_pnl(self.h3_base, last, equity)
        fields: dict[str, Any] = {}
        if self.volume:
            fields["volume_exit_checks"] = dict(self.checks)
            fields["volume_exit_extra_hours"] = self.extra / timedelta(hours=1)
            fields["volume_exit_extended_exits"] = {
                "exits": self.exits,
                "pnl": str(self.exit_pnl),
                "pnl_at_6h_bid": str(self.exit_pnl_at_mark),
            }
        if self.gate:
            lags = [lag / 1000 for lag in self.lags_ms]
            fields["funding_gate_blocked_grids"] = self.blocked_grids
            fields["funding_gate_blocked_hours"] = self.closed_ms / HOUR_MS
            fields["funding_gate_lag_seconds"] = {
                "settlements": len(lags),
                "min": min(lags, default=None),
                "mean": sum(lags) / len(lags) if lags else None,
                "max": max(lags, default=None),
            }
        if self.cycle:
            fields["cycle_phases_by_bar"] = dict(self.phases)
            fields["cycle_rules_by_bar"] = dict(self.cycle_rules)
            fields["cycle_ath_unavailable_bars"] = self.no_ath
            fields["cycle_h3_grids"] = {"opened": self.h3_grids, "pnl": str(self.h3_pnl)}
        return fields


def replay(
    config: BotConfig,
    run: RunConfig,
    minutes: Iterable[Kline],
    features: FeatureEngine,
    policy: SimulationPolicy | None = None,
    daily: Sequence[Kline] | None = None,
    hourly: Sequence[Kline] | None = None,
    funding: Sequence[FundingRecord] | None = None,
    *,
    window: tuple[int, int] | None = None,
    masked: frozenset[int] = frozenset(),
    days_skipped_for_masks: int = 0,
) -> tuple[Metrics, Account]:
    """``daily`` is the traded pair's completed 1d history (P3), read only by variant A
    (``policy.trend_switch``) and variant H (``policy.cycle_gate``); ``hourly`` is its 1h
    history, read only by variant E (``policy.volume_exit``); ``funding`` is the BTCUSDT
    funding records, read only by variant G (``policy.funding_gate``). Each variant
    refuses to run without its history.

    ``window`` is the evaluation window [start, end) in ms; ``masked`` is the pair's own
    masked hours, whose minutes the caller has already dropped; ``days_skipped_for_masks``
    is how many days the pair's daily/hourly check skips for them, which the caller counts
    (``jobs.skipped_days_for_masks``). They change no decision: the metrics report the
    masked hours inside ``window`` and the fills on the first replayed minute after a masked
    span (spec v1 §5 rules 1 and 4; ``MaskedSpans``). A mask needs the window. With no mask
    the replay is exactly as without these arguments."""
    spans = MaskedSpans(masked, window) if masked else None
    schedule: TrendSchedule | None = None
    if policy is not None and policy.trend_switch:
        if daily is None:
            raise ValueError("variant A (trend switch) needs the pair's daily history")
        schedule = TrendSchedule(daily)
    cycle_schedule: CycleSchedule | None = None
    if policy is not None and policy.cycle_gate:
        if daily is None:
            raise ValueError("variant H (cycle context) needs the pair's daily history")
        cycle_schedule = CycleSchedule((k.open_ms, k.close) for k in daily)
    volumes: VolumeHistory | None = None
    if policy is not None and policy.volume_exit:
        if hourly is None:
            raise ValueError("variant E (volume exit) needs the pair's hourly history")
        volumes = VolumeHistory((k.open_ms, k.volume) for k in hourly)
    gate: FundingSignal | None = None
    if policy is not None and policy.funding_gate:
        if funding is None:
            raise ValueError("variant G (funding gate) needs the BTCUSDT funding history")
        gate = FundingSignal(funding)
    # Variant F: the bars before the current one, for its 15-minute taker-buy share.
    flow: deque[Kline] | None = (
        deque(maxlen=FLOW_BARS) if policy is not None and policy.flow_block_entry else None
    )
    reported = (
        VariantReport(policy, funding or (), run.rules)
        if policy is not None and (policy.volume_exit or policy.funding_gate or policy.cycle_gate)
        else None
    )
    # ":memory:" gives the simulator an in-memory SQLite store; replay never writes to it.
    simulator = PaperSimulator(Path(":memory:"), config, run.rules, run.initial_quote, policy)
    simulator.volumes = volumes
    account = simulator.store.read()
    simulator.close()  # step() below uses no store
    if account.orders:
        raise ValueError("replay must start from an empty order book")
    orders = account.orders = RequestCountingOrders()
    metrics = Metrics(peak_equity=run.initial_quote, final_equity=run.initial_quote)
    metrics.masked_hours = spans.hours if spans is not None else 0
    metrics.days_skipped_for_masks = days_skipped_for_masks

    def observe_risk(
        equity: Decimal, high: Decimal, reference: Decimal, decision: RiskDecision
    ) -> None:
        # C1(b): active equity against the measurement reference, which is scaled at
        # settlement exactly as risk_high is but never rebased (amendment 1); ``high`` is
        # the engine's own, rebased, breaker reference.
        metrics.risk_evaluations += 1
        if reference > ZERO:
            metrics.active_max_drawdown = max(
                metrics.active_max_drawdown, max(ZERO, (reference - equity) / reference)
            )

    simulator.risk_observer = observe_risk
    spread_pct = float(run.spread * 100)
    hold: BuyAndHold | None = None
    was_range_exit = False
    was_halted = False
    last_hour = -1
    last_quote: Quote | None = None
    for kline in minutes:
        inputs = features.at(kline.open_ms)
        if inputs is None:
            metrics.warmup_bars += 1
            continue
        if hold is None:
            if schedule is not None and schedule.completed_bars(kline.open_ms) < (
                MINIMUM_DAILY_WARMUP
            ):
                raise ValueError("variant A needs 200 completed daily bars before evaluation")
            hold = BuyAndHold(run, kline)
            metrics.first_bar_ms = kline.open_ms
        metrics.bars += 1
        metrics.last_bar_ms = kline.open_ms
        # Rule 4: orders stay open across a masked span; this minute's fills are flagged.
        after_span = spans is not None and spans.first_after(kline.open_ms)
        bar_time = datetime.fromtimestamp(kline.open_ms / 1000, UTC)
        signals = signals_for(inputs, bar_time, gated=run.gated)
        # A flat history has zero ATR, which the engine rejects as corrupt input. The
        # entry veto above means this tick-sized placeholder can never size a grid.
        atr = inputs.atr if inputs.atr > ZERO else run.rules.tick_size
        epoch = f"{run.symbol}/{kline.open_ms}"
        # Variant A: the state from the last daily bar closed at this minute's start.
        trend = schedule.at(kline.open_ms) if schedule is not None else None
        # Variant F likewise reads only the bars complete at this minute's start, for all
        # four quotes: the 15 before it.
        share = taker_buy_share(flow, kline.open_ms) if flow is not None else None
        report: dict[str, Any] = {}
        cycle: CycleSignal | None = None
        quotes = bar_quotes(kline, run.symbol, run.path_mode, run.spread, run.rules.tick_size)
        for quote, offset, span in zip(quotes, POINT_OFFSETS_S, POINT_SPANS_MS, strict=True):
            # Variants G and H at the quote's own instant: G the funding records usable by
            # then, H the last daily bar closed, so a record usable, or a halving, within
            # the minute counts from the first quote after it.
            at_ms = kline.open_ms + offset * 1000
            funding_blocks = gate.state(at_ms).blocks if gate is not None else None
            if cycle_schedule is not None:
                cycle = cycle_schedule.at(at_ms)
            if reported is not None:
                reported.observation(at_ms, span, funding_blocks)
            # Depth is re-bounded before every quote from the account at that moment.
            depth = depth_multiple(inputs.minute_quote_volume, account, run.rules, quote.bid)
            candidate = candidate_for(inputs, run.symbol, spread_pct, depth, gated=run.gated)
            frame = Frame(
                quote,
                signals,
                candidate,
                inputs.fair_value,
                atr,
                True,
                epoch,
                trend,
                inputs.resistance,
                flow_share=share,
                funding_blocks=funding_blocks,
                cycle=cycle,
            )
            since, done = orders.requests, len(orders.completed)
            report = simulator.step(account, frame)
            last_quote = quote
            metrics.requests_by_day[quote.observed_at[:10]] += order_requests(
                orders, since, report["fills"]
            )
            cycles = sum(1 for key in orders.completed[done:] if key.endswith("/sell"))
            if cycles:
                metrics.completed_cycles += cycles
                year, week, _ = timestamp(quote.observed_at).isocalendar()
                metrics.cycles_by_week[f"{year}-W{week:02d}"] += cycles
            metrics.frames += 1
            if after_span:
                metrics.fills_after_masked_span += len(report["fills"])
            exit_pnl = _record_fills(metrics, report["fills"], report.get("exit_reason"))
            # Only frames that attempted an exit carry the key. A rejected or halting
            # frame attempted none, and must not reset the streak or count as cleared.
            if "exit_blocked" in report:
                record_exit_block(
                    metrics, str(report["exit_blocked"]), report["exit_blocked_notional"]
                )
            metrics.grids_opened += int(bool(report["opened"]))
            # From the account, not the report: a rejected frame's report omits the flag.
            exiting = account.range_exit
            metrics.range_exits += int(exiting and not was_range_exit)
            was_range_exit = exiting
            metrics.transient_pauses += int("regime" not in report)
            if account.halt and not was_halted:
                # A halt instance starts on the not-halted to halted transition; later
                # evaluations that still see the drawdown are not new halts. A drawdown
                # halt may restart after H (amendment 1), so a run can have several.
                if not metrics.halted_at:
                    metrics.halted_at, metrics.halt_reason = quote.observed_at, account.halt
                metrics.hard_drawdown_halts += int(account.halt_category == "drawdown")
            was_halted = bool(account.halt)
            metrics.rebases += int("rebase" in report)
            metrics.closes += int("episode_closed" in report)
            metrics.restarts += int("restart" in report)
            if "total_equity" in report:
                total = Decimal(report["total_equity"])
                metrics.final_equity = total
                metrics.peak_equity = max(metrics.peak_equity, total)
                drawdown = (metrics.peak_equity - total) / metrics.peak_equity
                metrics.max_drawdown = max(metrics.max_drawdown, drawdown)
            if reported is not None:
                reported.frame(report, account, quote, metrics.final_equity, exit_pnl)
            hold.mark(quote)
        # Variants E and F may read this bar from the next minute on, once it has closed.
        if volumes is not None:
            volumes.record(kline.open_ms, kline.volume)
        if flow is not None:
            flow.append(kline)
        # Bar-level bookkeeping from the bar's closing quote.
        metrics.regimes[str(report.get("regime", "unavailable"))] += 1
        metrics.decisions[str(report["decision"])] += 1
        if report.get("reason"):
            metrics.reasons[reason_key(str(report["decision"]), str(report["reason"]))] += 1
        if reported is not None:
            reported.bar_end(report, cycle)
        total = metrics.final_equity
        if account.inventory > ZERO:
            metrics.bars_with_inventory += 1
            inventory_value = total - account.cash - account.secured
            metrics.exposure_sum += inventory_value / total if total else ZERO
        metrics.bars_with_orders += int(bool(account.orders))
        hour = kline.open_ms // 3_600_000
        if hour != last_hour:
            metrics.hourly_equity.append((kline.open_ms, str(total), str(hold.value)))
            last_hour = hour
    if hold is not None:
        metrics.hold_final, metrics.hold_max_drawdown = hold.value, hold.max_drawdown
    if last_quote is not None:
        # Variant F's held fragments are reported as dust, never as an exit owed.
        held = simulator.held_fragments(account) if flow is not None else ZERO
        metrics.final_exit_blocked, metrics.final_blocked_notional = exit_state(
            account, last_quote, run.rules, held
        )
    if reported is not None:
        metrics.variant = reported.fields(last_quote, metrics.final_equity)
    return metrics, account


def check_accounting(run: RunConfig, metrics: Metrics, account: Account) -> list[str]:
    """Exact Decimal identities between the fill journal and the final account."""
    problems = []
    with localcontext() as context:
        context.prec = 80
        cash = (
            run.initial_quote
            - metrics.buy_notional
            - metrics.buy_fees
            + metrics.sell_notional
            - metrics.sell_fees
            - account.secured
        )
        if cash != account.cash:
            problems.append(f"cash identity failed: journal {cash} != account {account.cash}")
        if metrics.bought - metrics.sold != account.inventory:
            problems.append("inventory identity failed")
        if metrics.buy_fees + metrics.sell_fees != account.fees:
            problems.append("fee identity failed")
        if sum(account.confirmed_transfers.values(), ZERO) != account.secured:
            problems.append("reserve transfer journal does not reconcile")
        # P6: realised (by sell type) + unrealised on held inventory = total equity change.
        if metrics.frames:
            # Account.equity = cash - pending + inventory * mark, so this is the inventory mark.
            inventory_mark = account.last_equity - account.cash + account.pending
            unrealised = inventory_mark - metrics.cost_basis
            realised = metrics.grid_sell_pnl + metrics.exit_pnl
            change = metrics.final_equity - run.initial_quote
            if abs(realised + unrealised - change) > Decimal("1e-18"):
                problems.append(f"P&L reconciliation failed: {realised} + {unrealised} != {change}")
            if sum(metrics.exit_pnl_by_reason.values(), ZERO) != metrics.exit_pnl:
                problems.append("exit P&L by reason does not sum to the exit total")
    return problems


def _archive_months(manifest: dict[str, Any], symbol: str, interval: str) -> list[str]:
    """Months of the pair's verified kline archives at one interval, in manifest order."""
    return [
        entry["month"]
        for entry in manifest["files"]
        if not is_funding(entry)
        and (entry["symbol"], entry["interval"], entry["status"]) == (symbol, interval, "ok")
    ]


def _read_month(data_dir: Path, symbol: str, interval: str, month: str) -> list[Kline]:
    rows, _ = read_archive(local_path(data_dir, symbol, interval, month), symbol, interval, month)
    return rows


def _read_month_masked(
    data_dir: Path,
    symbol: str,
    interval: str,
    month: str,
    mask: frozenset[int],
    excluded: Sequence[tuple[int, int]],
) -> list[Kline]:
    """The month's bars from the repairing reader (spec v1 §5 rule 1), less every bar in a
    masked hour, every bar in an hour the reader distrusts (``masked_hours``) and every
    bar inside a documented ``excluded`` [start, end) range.

    ``mask_job``'s masks already hold every distrusted hour of the month; dropping them
    here too keeps the reader's kept copy of a duplicated row out of a load whose mask was
    made by hand. The manifest lists the archive as ok, so an archive the reader cannot
    read is not masked here: it raises, fail-closed, as the strict reader does. Only a
    manifest entry that is not ok gives no bars, and ``_archive_months`` never lists one."""
    read = read_archive_repaired(
        local_path(data_dir, symbol, interval, month), symbol, interval, month
    )
    if read.unreadable:
        raise DataError(
            f"{symbol} {interval} {month}: the manifest lists the archive as ok, but it is "
            f"unreadable: {read.unreadable}"
        )
    dropped = mask | read.masked_hours
    bars = [kline for kline in read.bars if kline.open_ms // HOUR_MS * HOUR_MS not in dropped]
    if excluded:
        bars = [k for k in bars if not any(a <= k.open_ms < b for a, b in excluded)]
    return bars


def _month_bars(
    data_dir: Path,
    symbol: str,
    interval: str,
    month: str,
    mask: frozenset[int] | None,
    excluded: Sequence[tuple[int, int]],
) -> list[Kline]:
    """Today's strict read when ``mask`` is None; the masked read otherwise."""
    if mask is None:
        return _read_month(data_dir, symbol, interval, month)
    return _read_month_masked(data_dir, symbol, interval, month, mask, excluded)


def load_candles(
    data_dir: Path,
    manifest: dict[str, Any],
    symbol: str,
    interval: str,
    *,
    mask: frozenset[int] | None = None,
    excluded: Sequence[tuple[int, int]] = (),
) -> list[Kline]:
    """Every verified candle of the pair at one interval, sorted by open time.

    With ``mask`` None, the strict reader, which refuses an archive with a repaired or
    dropped row, and nothing is dropped: ``excluded`` is not read. With a mask, even an
    empty one, 1m and 1h archives are read by the repairing reader, and every bar in a
    masked hour, in an hour the reader distrusts, or inside an ``excluded`` [start, end)
    range, the symbol's documented absences, is dropped (spec v1 §4 and §5). Daily bars
    are never masked (rule 3): the repairing reader refuses them."""
    candles = [
        kline
        for month in _archive_months(manifest, symbol, interval)
        for kline in _month_bars(data_dir, symbol, interval, month, mask, excluded)
    ]
    candles.sort(key=lambda k: k.open_ms)
    return candles


def load_hourly(
    data_dir: Path,
    manifest: dict[str, Any],
    symbol: str,
    *,
    mask: frozenset[int] | None = None,
    excluded: Sequence[tuple[int, int]] = (),
) -> list[Kline]:
    return load_candles(data_dir, manifest, symbol, "1h", mask=mask, excluded=excluded)


def load_daily(data_dir: Path, manifest: dict[str, Any], symbol: str) -> list[Kline]:
    return load_candles(data_dir, manifest, symbol, "1d")


def load_funding(
    data_dir: Path, manifest: dict[str, Any], symbol: str, months: Iterable[str]
) -> list[FundingRecord]:
    """Variant G's history: the records of the perpetual ``symbol``'s monthly funding
    archives the manifest lists as present (spec v1 P8), whose checksums
    ``verify_dataset`` checks before any replay.

    Every one of ``months``, the run's evaluation months, from ``FIRST_ARCHIVE_MONTH``
    on needs its archive: without one, G would block every new grid that month whatever
    the funding was, a result that says nothing about funding, so the run is refused
    instead. Before that month no archive exists, so none is needed: G is unavailable
    there, without three usable records, and blocks every new grid (spec v1 §5 rule 9)."""
    present = [
        entry["month"]
        for entry in manifest["files"]
        if is_funding(entry) and entry["symbol"] == symbol and entry["status"] == "ok"
    ]
    expected = [month for month in months if month >= FIRST_ARCHIVE_MONTH]
    if absent := [month for month in expected if month not in present]:
        raise ValueError(
            f"variant G needs {symbol}'s funding archive for every evaluation month from "
            f"{FIRST_ARCHIVE_MONTH} in the manifest (spec v1 P8); it lists none for "
            f"{', '.join(absent)}"
        )
    return [
        record
        for month in present
        for record in read_funding_archive(
            funding_local_path(data_dir, symbol, month), symbol, month
        )
    ]


DAY_MS = 86_400_000


def cross_check_daily(
    daily: Sequence[Kline],
    hourly: Sequence[Kline],
    daily_window: tuple[int, int],
    hourly_window: tuple[int, int],
    evaluation_start_ms: int,
    volume_tolerance: Decimal | None = None,
    *,
    masked_days: frozenset[int] = frozenset(),
) -> dict[str, int]:
    """Spec v1 P3: daily bars must be complete, unique and agree with their hours.

    ``daily_window`` is the [start, end) span the 1d archives cover; every UTC day in it
    must appear exactly once. Over ``hourly_window`` each day must also equal the
    aggregation of its 24 unique contiguous 1h bars (an OHLCV match alone cannot show
    missing hours). The warm-up count is completed days before the evaluation start.

    ``masked_days`` are the day opens that hold a masked hour (spec v1 §5 rule 3): each in
    ``hourly_window`` is skipped in the 24-hour comparison and counted in
    ``daily_days_skipped_for_masks``, a key written only when non-zero. Its official 1d
    bar still counts: daily bars are never masked, so a missing or duplicated one stays
    a failure.
    """
    opens = [k.open_ms for k in daily]
    present = set(opens)
    days = range(daily_window[0], daily_window[1], DAY_MS)
    by_day: dict[int, list[Kline]] = {}
    for kline in hourly:
        if hourly_window[0] <= kline.open_ms < hourly_window[1]:
            by_day.setdefault(kline.open_ms // DAY_MS * DAY_MS, []).append(kline)
    official = {k.open_ms: k for k in daily}
    compared = mismatched = incomplete = drift = skipped = 0
    for day in range(hourly_window[0], hourly_window[1], DAY_MS):
        if day in masked_days:
            skipped += 1
            continue
        hours = by_day.get(day, [])
        if len({h.open_ms for h in hours}) != 24 or len(hours) != 24:
            incomplete += 1
            continue
        reference = official.get(day)
        if reference is None:
            continue  # counted as missing below
        compared += 1
        (merged,) = aggregate(sorted(hours, key=lambda h: h.open_ms), DAY_MS)
        outcome = compare_bars(merged, reference, volume_tolerance)
        mismatched += int(outcome == "mismatch")
        drift += int(outcome == "drift")
    warmup = sum(1 for o in opens if o + DAY_MS <= evaluation_start_ms)
    result = {
        "daily_days_compared": compared,
        "daily_days_mismatched": mismatched,
        "daily_days_volume_drift": drift,
        "daily_days_missing": sum(1 for d in days if d not in present),
        "daily_days_duplicated": len(opens) - len(present),
        "daily_days_hours_incomplete": incomplete,
        "daily_warmup_days": warmup,
        "daily_warmup_short": int(warmup < MINIMUM_DAILY_WARMUP),
    }
    if skipped:  # Written only when non-zero, so an unmasked record is today's.
        result["daily_days_skipped_for_masks"] = skipped
    return result


def load_minutes(
    data_dir: Path,
    manifest: dict[str, Any],
    symbol: str,
    *,
    mask: frozenset[int] | None = None,
    excluded: Sequence[tuple[int, int]] = (),
) -> Iterator[Kline]:
    """The pair's 1m bars in time order, read lazily one month archive at a time.

    ``mask`` and ``excluded`` as for ``load_candles``: None reads strictly and drops
    nothing; a mask reads with the repairing reader and drops the masked hours' minutes
    and those inside ``excluded``."""
    for month in sorted(_archive_months(manifest, symbol, "1m")):
        yield from _month_bars(data_dir, symbol, "1m", month, mask, excluded)


# Owner decision (2026-09-24): Binance archives sometimes disagree on volume only. With
# OHLC identical, a relative volume difference up to 0.1% is counted as drift, not as a
# failure. Larger differences, any price difference and any missing bar stay fatal.
# Results record INTEGRITY_RULES; ``--strict-volume`` restores exact matching (tolerance 0).
VOLUME_DRIFT_TOLERANCE = Decimal("0.001")
# Which engine produced a result. Bump it whenever a change moves replay results, so
# runs from before and after the change are never compared as one trial.
#   exit-residue-v1 (2026-09-27): a residue the exchange filters forbid selling no
#   longer blocks settlement or new grids; a validation halt holding inventory arms
#   liquidation; refused exits are counted. Runs without this field predate it.
#   drawdown-recovery-v1 (2026-09-28, spec v1 amendment 1): a soft-drawdown episode
#   rebases risk_high after a 24 h cool-off; a drawdown halt restarts by itself after
#   24 h; C1(b) is measured against a reference that is never rebased. No V0 result on
#   exit-residue-v1 was run or inspected.
#   drawdown-recovery-v2 (2026-10-05, owner decisions of 2026-10-02, spec v1): D7, a
#   soft-drawdown episode already back under the soft limit when its rebase falls due
#   closes without one; amendment 2 (D15), a flat account with no orders and no range
#   exit pending clears its grid bounds and outside-range clock at once; amendment 3
#   (D16), the outside-range clock stands still while halted; and the 3%, 8% and 12% risk
#   limits compare the balances exactly, not through floats (moved here from #159).
ENGINE_VERSION = "drawdown-recovery-v2"
INTEGRITY_RULES = "drift-tolerance-v1"
STRICT_INTEGRITY_RULES = "strict-v0"


def compare_bars(ours: Kline, theirs: Kline, tolerance: Decimal | None = None) -> str:
    """'match', 'drift' (OHLC identical, volume within tolerance) or 'mismatch'.

    ``tolerance`` defaults to VOLUME_DRIFT_TOLERANCE; zero means volume must match exactly.
    """
    tolerance = VOLUME_DRIFT_TOLERANCE if tolerance is None else tolerance
    prices = (ours.open, ours.high, ours.low, ours.close)
    if prices != (theirs.open, theirs.high, theirs.low, theirs.close):
        return "mismatch"
    if ours.volume == theirs.volume:
        return "match"
    if theirs.volume > ZERO and abs(ours.volume - theirs.volume) <= (theirs.volume * tolerance):
        return "drift"
    return "mismatch"


def cross_check_hourly(
    minutes: Iterable[Kline],
    hourly: Sequence[Kline],
    window: tuple[int, int],
    volume_tolerance: Decimal | None = None,
    *,
    masked: frozenset[int] = frozenset(),
) -> dict[str, int]:
    """Compare 1m bars aggregated to hours against Binance's own 1h archive.

    ``window`` is the [start, end) span the minute archives cover. Official hours in
    it with no minute data at all are counted too, so a wholly missing hour cannot
    pass the check silently.

    ``masked`` hours leave the expected set (spec v1 §5, "The post-mask expected set"):
    their minutes and 1h bars are set aside, and none of them is counted anywhere.
    """
    if masked:
        minutes = (k for k in minutes if k.open_ms // HOUR_MS * HOUR_MS not in masked)
        hourly = [k for k in hourly if k.open_ms // HOUR_MS * HOUR_MS not in masked]
    official = {k.open_ms: k for k in hourly}
    compared = mismatched = missing = drift = 0
    per_hour: dict[int, int] = {}

    def counted(source: Iterable[Kline]) -> Iterator[Kline]:
        for kline in source:
            hour = kline.open_ms // HOUR_MS * HOUR_MS
            per_hour[hour] = per_hour.get(hour, 0) + 1
            yield kline

    seen: set[int] = set()
    for candle in aggregate(counted(minutes)):
        seen.add(candle.open_ms)
        reference = official.get(candle.open_ms)
        if reference is None:
            missing += 1
            continue
        compared += 1
        outcome = compare_bars(candle, reference, volume_tolerance)
        mismatched += int(outcome == "mismatch")
        drift += int(outcome == "drift")
    in_window = range(window[0], window[1], HOUR_MS)
    absent = sum(1 for o in official if window[0] <= o < window[1] and o not in seen)
    absent_both = sum(
        1 for o in in_window if o not in official and o not in seen and o not in masked
    )
    # An exact OHLCV match cannot reveal missing zero-volume minutes, so count them.
    incomplete = [
        60 - n for hour, n in per_hour.items() if window[0] <= hour < window[1] and n < 60
    ]
    return {
        "hours_compared": compared,
        "hours_mismatched": mismatched,
        "hours_volume_drift": drift,
        "hours_missing": missing,
        "hours_absent_from_minutes": absent,
        "hours_absent_from_both": absent_both,
        "hours_incomplete": len(incomplete),
        "minutes_missing": sum(incomplete),
    }


def check_hourly_series(
    hourly: Sequence[Kline],
    window: tuple[int, int],
    excluded: Sequence[tuple[int, int]] = (),
    *,
    masked: frozenset[int] = frozenset(),
) -> dict[str, int]:
    """Completeness of an hourly series with no minute data behind it (an untraded market
    proxy or breadth-basket symbol): every hour in the [start, end) ``window`` exactly
    once, except hours inside a documented ``excluded`` [start, end) range and
    ``masked`` hours, which leave the expected set (spec v1 §5, "The post-mask expected
    set"): a masked hour's bars are set aside, and it is never missing."""
    opens = [
        k.open_ms
        for k in hourly
        if window[0] <= k.open_ms < window[1] and k.open_ms // HOUR_MS * HOUR_MS not in masked
    ]
    present = set(opens)
    hours = range(window[0], window[1], HOUR_MS)
    documented = {h for h in hours if any(a <= h < b for a, b in excluded)}
    return {
        "series_hours_present": len(present),
        "series_hours_missing": sum(
            1 for h in hours if h not in present and h not in documented and h not in masked
        ),
        "series_hours_duplicated": len(opens) - len(present),
        "series_hours_excluded": len(documented),
    }


def utc_iso(ms: int) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat() if ms else None


def summarise(
    run: RunConfig,
    metrics: Metrics,
    account: Account,
    problems: list[str],
    *,
    feature_version: str = FEATURE_VERSION,
) -> dict[str, Any]:
    """``feature_version`` names the features the run used (STRUCTURE_FEATURE_VERSION
    under SimulationPolicy.structure); a V0 row keeps its exact labels."""
    initial = run.initial_quote
    if run.gated:
        strategy = f"gated grid ({feature_version})"
    elif feature_version == FEATURE_VERSION:
        strategy = "ungated grid baseline"
    else:
        strategy = f"ungated grid baseline ({feature_version})"
    return {
        "symbol": run.symbol,
        "path_mode": run.path_mode,
        "strategy": strategy,
        "feature_version": feature_version,
        "engine_version": ENGINE_VERSION,
        "news_component": "ABSENT (news_risk fixed at 0; no historical source)",
        "window": [utc_iso(metrics.first_bar_ms), utc_iso(metrics.last_bar_ms)],
        "initial_quote": str(initial),
        "final_total_equity": str(metrics.final_equity),
        "return_pct": float((metrics.final_equity / initial - 1) * 100),
        "max_drawdown_pct": float(metrics.max_drawdown * 100),
        "buy_and_hold_return_pct": float((metrics.hold_final / initial - 1) * 100),
        "buy_and_hold_max_drawdown_pct": float(metrics.hold_max_drawdown * 100),
        "fees": str(metrics.buy_fees + metrics.sell_fees),
        "turnover": str(metrics.buy_notional + metrics.sell_notional),
        "realised_grid_sell_pnl": str(metrics.grid_sell_pnl),
        "realised_exit_pnl": str(metrics.exit_pnl),
        "exit_sells": metrics.exit_sells,
        "realised_exit_pnl_by_reason": {k: str(v) for k, v in metrics.exit_pnl_by_reason.items()},
        "completed_cycles": metrics.completed_cycles,
        "completed_cycles_by_week": dict(metrics.cycles_by_week),
        "active_max_drawdown_pct": float(metrics.active_max_drawdown * 100),
        "risk_evaluations": metrics.risk_evaluations,
        "hard_drawdown_halts": metrics.hard_drawdown_halts,
        "soft_drawdown_rebases": metrics.rebases,
        "soft_drawdown_closes": metrics.closes,
        "drawdown_restarts": metrics.restarts,
        "order_requests": sum(metrics.requests_by_day.values()),
        "max_order_requests_per_day": max(metrics.requests_by_day.values(), default=0),
        "days_over_request_budget": sum(
            1 for n in metrics.requests_by_day.values() if n > DAILY_REQUEST_BUDGET
        ),
        "buys": metrics.buys,
        "sells": metrics.sells,
        "grids_opened": metrics.grids_opened,
        "range_exits": metrics.range_exits,
        "exit_blocked_frames": metrics.exit_blocked_frames,
        "exit_blocked_frames_by_kind": dict(metrics.exit_blocked_by_kind),
        "max_exit_blocked_streak": metrics.max_exit_blocked_streak,
        "max_unsellable_notional": str(metrics.max_exit_blocked_notional),
        # "depth" here means the run ended still unable to exit; "dust" means the
        # residual is below one minimum notional and needs a higher price to sell.
        "final_exit_blocked": metrics.final_exit_blocked or None,
        "final_unsellable_notional": str(metrics.final_blocked_notional),
        "reserve_pending": str(account.pending),
        "reserve_secured": str(account.secured),
        "final_inventory": str(account.inventory),
        "bars": metrics.bars,
        "warmup_bars_skipped": metrics.warmup_bars,
        "frames": metrics.frames,
        "time_with_inventory_pct": 100 * metrics.bars_with_inventory / max(metrics.bars, 1),
        "time_with_orders_pct": 100 * metrics.bars_with_orders / max(metrics.bars, 1),
        "mean_exposure_when_invested_pct": float(
            metrics.exposure_sum / max(metrics.bars_with_inventory, 1) * 100
        ),
        "halted_at": metrics.halted_at or None,
        "halt_reason": metrics.halt_reason or None,
        "transient_pauses": metrics.transient_pauses,
        "regimes_by_bar": dict(metrics.regimes),
        "decisions_by_bar": dict(metrics.decisions),
        "top_reasons_by_bar": dict(metrics.reasons.most_common(8)),
        "accounting_problems": problems,
        "rules": {key: str(value) for key, value in run.rules.identity().items()},
        "assumed_spread_pct": str(run.spread * 100),
        **metrics.variant,
        **mask_report(metrics),
        "hourly_equity": metrics.hourly_equity,
    }


def rules_for(
    symbol: str,
    instrument: dict[str, str],
    spec_fee: Decimal,
    spec_slippage: Decimal,
    participation: Decimal,
    taker_fee: Decimal | None = None,
    fill_trigger: Decimal | None = None,
) -> MarketRules:
    """``fill_trigger`` (D9) is set only by a labelled missed-fill sensitivity run."""
    return MarketRules(
        symbol=symbol,
        tick_size=Decimal(instrument["tick_size"]),
        quantity_step=Decimal(instrument["quantity_step"]),
        minimum_notional=Decimal(instrument["min_notional"]),
        fee_rate=spec_fee,
        slippage_rate=spec_slippage,
        participation=participation,
        taker_fee_rate=taker_fee,
        fill_trigger_rate=fill_trigger,
    )
