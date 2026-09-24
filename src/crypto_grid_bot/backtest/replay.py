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
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.dataset import local_path
from crypto_grid_bot.backtest.features import FEATURE_VERSION, FeatureEngine, Inputs
from crypto_grid_bot.backtest.klines import Kline, aggregate, read_archive
from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals, RiskDecision
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

PATH_MODES = ("high_first", "low_first")
# Scorer context lines that precede its actual failure reasons.
_CONTEXT = ("base quality", "regime fit", "news multiplier")
POINT_OFFSETS_S = (0, 9, 19, 29)
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
    hard_drawdown_halts: int = 0  # halt events, not evaluations


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


def _record_fills(
    metrics: Metrics, fills: Sequence[dict[str, Any]], exit_reason: str | None = None
) -> None:
    for fill in fills:
        quantity, fee = Decimal(fill["quantity"]), Decimal(fill["fee"])
        notional = Decimal(fill["price"]) * quantity
        held = metrics.bought - metrics.sold
        if fill["side"] == "buy":
            metrics.buys += 1
            metrics.buy_notional += notional
            metrics.buy_fees += fee
            metrics.bought += quantity
            metrics.cost_basis += notional + fee
        else:
            cost = metrics.cost_basis * quantity / held if held > ZERO else ZERO
            metrics.cost_basis -= cost
            pnl = notional - fee - cost
            if str(fill["order_id"]).startswith("exit/"):
                metrics.exit_pnl += pnl
                metrics.exit_sells += 1
                reason = exit_reason or "unlabelled"
                metrics.exit_pnl_by_reason[reason] = (
                    metrics.exit_pnl_by_reason.get(reason, ZERO) + pnl
                )
            else:
                metrics.grid_sell_pnl += pnl
            metrics.sells += 1
            metrics.sell_notional += notional
            metrics.sell_fees += fee
            metrics.sold += quantity


class _BuyAndHold:
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

    def mark(self, bid: Decimal) -> None:
        """Mark at a quote's bid, sampled at the same quotes as the strategy (P2)."""
        rules = self.run.rules
        exit_value = bid * (ONE - rules.slippage_rate) * (ONE - rules.taker_fee)
        self.value = self.cash + self.quantity * exit_value
        self.peak = max(self.peak, self.value)
        self.max_drawdown = max(self.max_drawdown, (self.peak - self.value) / self.peak)


def replay(
    config: BotConfig,
    run: RunConfig,
    minutes: Iterable[Kline],
    features: FeatureEngine,
    policy: SimulationPolicy | None = None,
) -> tuple[Metrics, Account]:
    # ":memory:" gives the simulator an in-memory SQLite store; replay never writes to it.
    simulator = PaperSimulator(Path(":memory:"), config, run.rules, run.initial_quote, policy)
    account = simulator.store.read()
    simulator.close()  # step() below uses no store
    if account.orders:
        raise ValueError("replay must start from an empty order book")
    orders = account.orders = RequestCountingOrders()
    metrics = Metrics(peak_equity=run.initial_quote, final_equity=run.initial_quote)

    def observe_risk(equity: Decimal, high: Decimal, decision: RiskDecision) -> None:
        metrics.risk_evaluations += 1
        if high > ZERO:
            metrics.active_max_drawdown = max(
                metrics.active_max_drawdown, max(ZERO, (high - equity) / high)
            )

    simulator.risk_observer = observe_risk
    spread_pct = float(run.spread * 100)
    hold: _BuyAndHold | None = None
    was_range_exit = False
    last_hour = -1
    for kline in minutes:
        inputs = features.at(kline.open_ms)
        if inputs is None:
            metrics.warmup_bars += 1
            continue
        if hold is None:
            hold = _BuyAndHold(run, kline)
            metrics.first_bar_ms = kline.open_ms
        metrics.bars += 1
        metrics.last_bar_ms = kline.open_ms
        bar_time = datetime.fromtimestamp(kline.open_ms / 1000, UTC)
        signals = signals_for(inputs, bar_time, gated=run.gated)
        # A flat history has zero ATR, which the engine rejects as corrupt input. The
        # entry veto above means this tick-sized placeholder can never size a grid.
        atr = inputs.atr if inputs.atr > ZERO else run.rules.tick_size
        epoch = f"{run.symbol}/{kline.open_ms}"
        report: dict[str, Any] = {}
        for quote in bar_quotes(kline, run.symbol, run.path_mode, run.spread, run.rules.tick_size):
            # Depth is re-bounded before every quote from the account at that moment.
            depth = depth_multiple(inputs.minute_quote_volume, account, run.rules, quote.bid)
            candidate = candidate_for(inputs, run.symbol, spread_pct, depth, gated=run.gated)
            frame = Frame(quote, signals, candidate, inputs.fair_value, atr, True, epoch)
            since, done = orders.requests, len(orders.completed)
            report = simulator.step(account, frame)
            metrics.requests_by_day[quote.observed_at[:10]] += order_requests(
                orders, since, report["fills"]
            )
            cycles = sum(1 for key in orders.completed[done:] if key.endswith("/sell"))
            if cycles:
                metrics.completed_cycles += cycles
                year, week, _ = timestamp(quote.observed_at).isocalendar()
                metrics.cycles_by_week[f"{year}-W{week:02d}"] += cycles
            metrics.frames += 1
            _record_fills(metrics, report["fills"], report.get("exit_reason"))
            metrics.grids_opened += int(bool(report["opened"]))
            # From the account, not the report: a rejected frame's report omits the flag.
            exiting = account.range_exit
            metrics.range_exits += int(exiting and not was_range_exit)
            was_range_exit = exiting
            metrics.transient_pauses += int("regime" not in report)
            if account.halt and not metrics.halted_at:
                metrics.halted_at, metrics.halt_reason = quote.observed_at, account.halt
                # The halt is latched, so a run has at most one; later evaluations that
                # still see the drawdown are not new halts.
                metrics.hard_drawdown_halts += int(account.halt.startswith("hard drawdown"))
            if "total_equity" in report:
                total = Decimal(report["total_equity"])
                metrics.final_equity = total
                metrics.peak_equity = max(metrics.peak_equity, total)
                drawdown = (metrics.peak_equity - total) / metrics.peak_equity
                metrics.max_drawdown = max(metrics.max_drawdown, drawdown)
            hold.mark(quote.bid)
        # Bar-level bookkeeping from the bar's closing quote.
        metrics.regimes[str(report.get("regime", "unavailable"))] += 1
        metrics.decisions[str(report["decision"])] += 1
        if report.get("reason"):
            metrics.reasons[reason_key(str(report["decision"]), str(report["reason"]))] += 1
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
            inventory_mark = account.last_equity - account.cash + account.pending
            unrealised = inventory_mark - metrics.cost_basis
            realised = metrics.grid_sell_pnl + metrics.exit_pnl
            change = metrics.final_equity - run.initial_quote
            if abs(realised + unrealised - change) > Decimal("1e-18"):
                problems.append(f"P&L reconciliation failed: {realised} + {unrealised} != {change}")
            if sum(metrics.exit_pnl_by_reason.values(), ZERO) != metrics.exit_pnl:
                problems.append("exit P&L by reason does not sum to the exit total")
    return problems


def load_hourly(data_dir: Path, manifest: dict[str, Any], symbol: str) -> list[Kline]:
    candles: list[Kline] = []
    for entry in manifest["files"]:
        if entry["symbol"] == symbol and entry["interval"] == "1h" and entry["status"] == "ok":
            month = entry["month"]
            rows, _ = read_archive(local_path(data_dir, symbol, "1h", month), symbol, "1h", month)
            candles.extend(rows)
    candles.sort(key=lambda k: k.open_ms)
    return candles


def load_daily(data_dir: Path, manifest: dict[str, Any], symbol: str) -> list[Kline]:
    candles: list[Kline] = []
    for entry in manifest["files"]:
        if entry["symbol"] == symbol and entry["interval"] == "1d" and entry["status"] == "ok":
            month = entry["month"]
            rows, _ = read_archive(local_path(data_dir, symbol, "1d", month), symbol, "1d", month)
            candles.extend(rows)
    candles.sort(key=lambda k: k.open_ms)
    return candles


DAY_MS = 86_400_000
MINIMUM_DAILY_WARMUP = 200


def cross_check_daily(
    daily: Sequence[Kline],
    hourly: Sequence[Kline],
    daily_window: tuple[int, int],
    hourly_window: tuple[int, int],
    evaluation_start_ms: int,
) -> dict[str, int]:
    """Spec v1 P3: daily bars must be complete, unique and agree with their hours.

    ``daily_window`` is the [start, end) span the 1d archives cover; every UTC day in it
    must appear exactly once. Over ``hourly_window`` each day must also equal the
    aggregation of its 24 unique contiguous 1h bars (an OHLCV match alone cannot show
    missing hours). The warm-up count is completed days before the evaluation start.
    """
    opens = [k.open_ms for k in daily]
    present = set(opens)
    days = range(daily_window[0], daily_window[1], DAY_MS)
    by_day: dict[int, list[Kline]] = {}
    for kline in hourly:
        if hourly_window[0] <= kline.open_ms < hourly_window[1]:
            by_day.setdefault(kline.open_ms // DAY_MS * DAY_MS, []).append(kline)
    official = {k.open_ms: k for k in daily}
    compared = mismatched = incomplete = drift = 0
    for day in range(hourly_window[0], hourly_window[1], DAY_MS):
        hours = by_day.get(day, [])
        if len({h.open_ms for h in hours}) != 24 or len(hours) != 24:
            incomplete += 1
            continue
        reference = official.get(day)
        if reference is None:
            continue  # counted as missing below
        compared += 1
        (merged,) = aggregate(sorted(hours, key=lambda h: h.open_ms), DAY_MS)
        outcome = compare_bars(merged, reference)
        mismatched += int(outcome == "mismatch")
        drift += int(outcome == "drift")
    warmup = sum(1 for o in opens if o + DAY_MS <= evaluation_start_ms)
    return {
        "daily_days_compared": compared,
        "daily_days_mismatched": mismatched,
        "daily_days_volume_drift": drift,
        "daily_days_missing": sum(1 for d in days if d not in present),
        "daily_days_duplicated": len(opens) - len(present),
        "daily_days_hours_incomplete": incomplete,
        "daily_warmup_days": warmup,
        "daily_warmup_short": int(warmup < MINIMUM_DAILY_WARMUP),
    }


def load_minutes(data_dir: Path, manifest: dict[str, Any], symbol: str) -> Iterator[Kline]:
    months = sorted(
        e["month"]
        for e in manifest["files"]
        if e["symbol"] == symbol and e["interval"] == "1m" and e["status"] == "ok"
    )
    for month in months:
        rows, _ = read_archive(local_path(data_dir, symbol, "1m", month), symbol, "1m", month)
        yield from rows


# Owner decision (2026-09-24): Binance archives sometimes disagree on volume only. With
# OHLC identical, a relative volume difference up to 0.1% is counted as drift, not as a
# failure. Larger differences, any price difference and any missing bar stay fatal.
VOLUME_DRIFT_TOLERANCE = Decimal("0.001")


def compare_bars(ours: Kline, theirs: Kline) -> str:
    """'match', 'drift' (OHLC identical, volume within tolerance) or 'mismatch'."""
    prices = (ours.open, ours.high, ours.low, ours.close)
    if prices != (theirs.open, theirs.high, theirs.low, theirs.close):
        return "mismatch"
    if ours.volume == theirs.volume:
        return "match"
    if theirs.volume > ZERO and abs(ours.volume - theirs.volume) <= (
        theirs.volume * VOLUME_DRIFT_TOLERANCE
    ):
        return "drift"
    return "mismatch"


def cross_check_hourly(
    minutes: Iterable[Kline], hourly: Sequence[Kline], window: tuple[int, int]
) -> dict[str, int]:
    """Compare 1m bars aggregated to hours against Binance's own 1h archive.

    ``window`` is the [start, end) span the minute archives cover. Official hours in
    it with no minute data at all are counted too, so a wholly missing hour cannot
    pass the check silently.
    """
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
        outcome = compare_bars(candle, reference)
        mismatched += int(outcome == "mismatch")
        drift += int(outcome == "drift")
    in_window = range(window[0], window[1], HOUR_MS)
    absent = sum(1 for o in official if window[0] <= o < window[1] and o not in seen)
    absent_both = sum(1 for o in in_window if o not in official and o not in seen)
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


def _utc(ms: int) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat() if ms else None


def summarise(
    run: RunConfig, metrics: Metrics, account: Account, problems: list[str]
) -> dict[str, Any]:
    initial = run.initial_quote
    return {
        "symbol": run.symbol,
        "path_mode": run.path_mode,
        "strategy": "gated grid (price-only-v1)" if run.gated else "ungated grid baseline",
        "feature_version": FEATURE_VERSION,
        "news_component": "ABSENT (news_risk fixed at 0; no historical source)",
        "window": [_utc(metrics.first_bar_ms), _utc(metrics.last_bar_ms)],
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
        "order_requests": sum(metrics.requests_by_day.values()),
        "max_order_requests_per_day": max(metrics.requests_by_day.values(), default=0),
        "days_over_request_budget": sum(
            1 for n in metrics.requests_by_day.values() if n > DAILY_REQUEST_BUDGET
        ),
        "buys": metrics.buys,
        "sells": metrics.sells,
        "grids_opened": metrics.grids_opened,
        "range_exits": metrics.range_exits,
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
        "hourly_equity": metrics.hourly_equity,
    }


def rules_for(
    symbol: str,
    instrument: dict[str, str],
    spec_fee: Decimal,
    spec_slippage: Decimal,
    participation: Decimal,
    taker_fee: Decimal | None = None,
) -> MarketRules:
    return MarketRules(
        symbol=symbol,
        tick_size=Decimal(instrument["tick_size"]),
        quantity_step=Decimal(instrument["quantity_step"]),
        minimum_notional=Decimal(instrument["min_notional"]),
        fee_rate=spec_fee,
        slippage_rate=spec_slippage,
        participation=participation,
        taker_fee_rate=taker_fee,
    )
