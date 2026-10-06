"""Variant D, the trend benchmark (experiment spec v1, §3 D). Not a grid.

D holds the traded pair while its completed daily close is above its SMA50 and holds
cash otherwise. It is a comparison benchmark for the grid variants, deliberately kept
apart from them:

* It never goes through :class:`~crypto_grid_bot.simulation.runner.PaperSimulator`,
  the risk engine, the profit vault or the paper store. It is a replay-only
  calculation on the replay's quotes and never writes shared or persisted state.
* It is **exempt** from the §3 common risk rule: no daily-loss pause, no soft or hard
  drawdown halt and no emergency exit. Its return and drawdown are reported as they
  are, labelled as a benchmark with a different risk policy. D cannot be selected
  (spec §6).

What it shares with the grid replay, so the numbers are comparable (spec §3 D,
"Unchanged from A", and P2):

* the same quotes (:func:`~crypto_grid_bot.backtest.replay.bar_quotes`, both paths);
* the same evaluated minutes as V0: a minute the grid replay skips as warm-up is
  skipped here too, so both start at the same first evaluated bar;
* the same marks: ``bid × (1 − slippage) × (1 − taker)``, as ``Account.equity``;
* the same buy-and-hold benchmark object, marked at the same quotes;
* the same sampling: total equity after every quote's fills, and the hourly series
  at each hour's first evaluated bar.

Execution (spec §3 D): marketable at the effective observation, buys at
``ask × (1 + slippage)`` and sells at ``bid × (1 − slippage)``, both paying the taker
fee and both bounded by the 10% participation limit on the ask or bid size, as V0's
liquidation is. Prices are rounded to the tick against D (buys up, sells down); V0's
liquidation rounds its sell price down the same way.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.dataset import DatasetSpec
from crypto_grid_bot.backtest.jobs import (
    Masks,
    evaluation_window,
    exclusion_ranges,
    prepare_run,
    skipped_days_for_masks,
)
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import (
    DAILY_REQUEST_BUDGET,
    POINT_OFFSETS_S,
    BuyAndHold,
    MaskedSpans,
    RunConfig,
    bar_quotes,
    journal_fill,
    load_minutes,
    mask_report,
    utc_iso,
)
from crypto_grid_bot.simulation.execution import exit_price
from crypto_grid_bot.simulation.inventory_cap import mark as unit_mark
from crypto_grid_bot.simulation.models import ONE, ZERO, MarketRules, Quote, floor_step
from crypto_grid_bot.strategy.daily_sma import DailyCloses, close_above_sma, signal_day

VARIANT = "D"
SMA_LENGTH = 50
STRATEGY = "trend benchmark D (not a grid)"
RISK_POLICY = (
    "benchmark with a different risk policy: no daily-loss pause, no drawdown halt, "
    "no emergency exit, no profit vault or reserves (spec v1 §3 D)"
)
# The simulator settles fills at precision 50; the journal uses the same. Every price,
# sizing and settlement step below runs at this one explicit precision, never at the
# ambient context: a price computed at one precision and settled at another can spend
# more than the cash held (Codex's review of PR #112, a supported-input defect).
_PRECISION = 50


def buy_price(quote: Quote, rules: MarketRules) -> Decimal:
    """``ask × (1 + slippage)``, rounded up to the tick (never in D's favour).

    Convention, recorded beside the spec's price formula (Codex, PR #112, question 2):
    the spec writes the formula without a rounding rule; D rounds buys **up** and sells
    **down** to the tick, both against D, as V0's liquidation does for its sells.
    """
    with localcontext() as context:
        context.prec = _PRECISION
        raw = quote.ask * (ONE + rules.slippage_rate)
        ticks = (raw / rules.tick_size).to_integral_value(rounding=ROUND_CEILING)
        return ticks * rules.tick_size


def sell_price(quote: Quote, rules: MarketRules) -> Decimal:
    """``bid × (1 − slippage)``, rounded down to the tick: V0's liquidation price
    (``execution.exit_price``), at D's precision."""
    with localcontext() as context:
        context.prec = _PRECISION
        return exit_price(quote, rules)


def exit_value(quote: Quote, rules: MarketRules) -> Decimal:
    """Per-unit mark ``bid × (1 − slippage) × (1 − taker)`` as ``Account.equity``; the
    buy-and-hold's helper (``inventory_cap.mark``), at D's precision."""
    with localcontext() as context:
        context.prec = _PRECISION
        return unit_mark(quote, rules)


@dataclass(frozen=True)
class TrendFill:
    order_id: str
    side: str
    price: Decimal
    quantity: Decimal
    fee: Decimal


@dataclass
class TrendAccount:
    """D's one pot: cash and the pair, no reserves (spec §3 D)."""

    cash: Decimal
    inventory: Decimal = ZERO
    fees: Decimal = ZERO
    holding: bool = False  # the signal in force: True = hold the pair
    phase: str = "idle"  # "entering", "exiting" or "idle"
    last_mark: Decimal = ZERO  # per-unit exit value at the latest observation

    def equity(self) -> Decimal:
        with localcontext() as context:
            context.prec = _PRECISION
            return self.cash + self.inventory * self.last_mark


def entry_quantity(account: TrendAccount, quote: Quote, rules: MarketRules) -> Decimal:
    """The smallest of the participation limit and the remaining cash at the all-in unit
    cost ``price × (1 + taker)``, floored to the lot step (spec §3 D, entry residual).
    """
    with localcontext() as context:
        context.prec = _PRECISION
        unit_cost = buy_price(quote, rules) * (ONE + rules.taker_fee)
        affordable = floor_step(account.cash / unit_cost, rules.quantity_step)
        # Guard against a quotient rounded up at the last digit: never spend more than cash.
        while affordable > ZERO and affordable * unit_cost > account.cash:
            affordable -= rules.quantity_step
        capacity = floor_step(quote.ask_size * rules.participation, rules.quantity_step)
        return max(ZERO, min(capacity, affordable))


def enter(account: TrendAccount, quote: Quote, rules: MarketRules) -> TrendFill | None:
    """One observation of an entry. The entry ends when the quantity is below the minimum
    notional (spec §3 D: "The entry ends when that quantity is below the minimum
    notional"); see the handoff, question 1, for the reading used."""
    with localcontext() as context:
        context.prec = _PRECISION
        price, quantity = buy_price(quote, rules), entry_quantity(account, quote, rules)
        if price * quantity < rules.minimum_notional:
            account.phase = "idle"
            return None
        notional = price * quantity
        fee = notional * rules.taker_fee
        account.cash -= notional + fee
        account.inventory += quantity
        account.fees += fee
    return TrendFill("trend/buy/" + quote.event_id, "buy", price, quantity, fee)


def exit_step(account: TrendAccount, quote: Quote, rules: MarketRules) -> TrendFill | None:
    """One observation of an exit of the fixed base quantity held.

    Sells up to the participation limit. When the whole remainder is below the minimum
    notional the exit ends and the remainder stays as reported dust. A participation
    limit below the minimum with more inventory left sells nothing now and retries at
    the next observation, as V0's liquidation does.
    """
    with localcontext() as context:
        context.prec = _PRECISION
        price = sell_price(quote, rules)
        held = floor_step(account.inventory, rules.quantity_step)
        if price * held < rules.minimum_notional:
            account.phase = "idle"
            return None
        capacity = quote.bid_size * rules.participation
        quantity = floor_step(min(held, capacity), rules.quantity_step)
        if price * quantity < rules.minimum_notional:
            return None
        notional = price * quantity
        fee = notional * rules.taker_fee
        account.cash += notional - fee
        account.inventory -= quantity
        account.fees += fee
    return TrendFill("trend/sell/" + quote.event_id, "sell", price, quantity, fee)


@dataclass
class TrendMetrics:
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
    cost_basis: Decimal = ZERO  # quote paid, fees included, for inventory still held
    realised_pnl: Decimal = ZERO  # average-cost realised P&L of sells, after fees
    entries_started: int = 0
    exits_started: int = 0
    entries_abandoned: int = 0  # an entry still filling when the signal reversed
    exits_abandoned: int = 0  # an exit still filling when the signal reversed
    exits_ended_with_dust: int = 0  # an exit that ended with a remainder below the minimum
    peak_equity: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    final_equity: Decimal = ZERO
    first_bar_ms: int = 0
    last_bar_ms: int = 0
    hold_final: Decimal = ZERO
    hold_max_drawdown: Decimal = ZERO
    bars_with_inventory: int = 0
    # Signal in force at each evaluated bar's closing quote: hold, cash or undefined.
    signal_by_bar: Counter[str] = field(default_factory=Counter)
    # (hour open ms, strategy total equity, buy-and-hold value) at each hour's first bar,
    # exactly as the grid replay records it (P2).
    hourly_equity: list[tuple[int, str, str]] = field(default_factory=list)
    # Marketable orders sent per UTC day: each fill is one order placed and filled.
    requests_by_day: Counter[str] = field(default_factory=Counter)
    # Every fill with the time of the observation that produced it. D trades a few
    # times per signal change, so this stays small; it is not written to results.json.
    fills: list[tuple[str, TrendFill]] = field(default_factory=list)
    # Spec v1 §5 rule 1's per-run mask report, as the grid replay's (replay.MaskCounts).
    masked_hours: int = 0
    days_skipped_for_masks: int = 0
    fills_after_masked_span: int = 0


def _journal(metrics: TrendMetrics, fill: TrendFill, observed_at: str) -> None:
    metrics.fills.append((observed_at, fill))
    metrics.requests_by_day[observed_at[:10]] += 1
    with localcontext() as context:
        context.prec = _PRECISION
        pnl = journal_fill(metrics, fill.side, fill.price, fill.quantity, fill.fee)
        if pnl is not None:
            metrics.realised_pnl += pnl


def _label(signal: bool | None) -> str:
    return "undefined" if signal is None else "hold" if signal else "cash"


def replay_trend(
    run: RunConfig,
    minutes: Iterable[Kline],
    closes: DailyCloses,
    evaluated: Callable[[int], bool],
    *,
    window: tuple[int, int] | None = None,
    masked: frozenset[int] = frozenset(),
    days_skipped_for_masks: int = 0,
) -> tuple[TrendMetrics, TrendAccount]:
    """Replay D over ``minutes``. ``evaluated(open_ms)`` is False for a minute the grid
    replay skips as warm-up; D skips it too, so both share the first evaluated bar and
    the equity schedule. ``run.gated`` is not used by D.

    ``window``, ``masked`` and ``days_skipped_for_masks`` are the grid replay's
    (``replay.replay``): they change nothing D does, and its metrics report the pair's
    masked hours inside ``window`` and the fills on the first replayed minute after a
    masked span (spec v1 §5 rules 1 and 4). A mask needs the window.
    """
    spans = MaskedSpans(masked, window) if masked else None
    rules = run.rules
    account = TrendAccount(cash=run.initial_quote)
    metrics = TrendMetrics(peak_equity=run.initial_quote, final_equity=run.initial_quote)
    metrics.masked_hours = spans.hours if spans is not None else 0
    metrics.days_skipped_for_masks = days_skipped_for_masks
    signals: dict[int, bool | None] = {}
    hold: BuyAndHold | None = None
    last_hour = -1
    signal: bool | None = None
    for kline in minutes:
        if not evaluated(kline.open_ms):
            metrics.warmup_bars += 1
            continue
        if hold is None:
            hold = BuyAndHold(run, kline)
            metrics.first_bar_ms = kline.open_ms
        metrics.bars += 1
        metrics.last_bar_ms = kline.open_ms
        after_span = spans is not None and spans.first_after(kline.open_ms)
        quotes = bar_quotes(kline, run.symbol, run.path_mode, run.spread, rules.tick_size)
        for quote, offset in zip(quotes, POINT_OFFSETS_S, strict=True):
            quote.validate(rules)
            # Only the daily bar completed at this observation: never the current day's.
            day = signal_day(kline.open_ms + offset * 1000)
            if day not in signals:
                signals[day] = close_above_sma(closes, day, SMA_LENGTH)
            signal = signals[day]
            wanted = signal is True  # missing, undefined or non-positive means cash
            if wanted != account.holding:
                # The effective observation of a reversal: the unfinished side is
                # abandoned and the new side starts at this same observation.
                if account.phase == "entering":
                    metrics.entries_abandoned += 1
                elif account.phase == "exiting":
                    metrics.exits_abandoned += 1
                account.holding = wanted
                account.phase = "entering" if wanted else "exiting"
                metrics.entries_started += int(wanted)
                metrics.exits_started += int(not wanted)
            fill = None
            if account.phase == "entering":
                fill = enter(account, quote, rules)
            elif account.phase == "exiting":
                fill = exit_step(account, quote, rules)
                if account.phase == "idle" and account.inventory > ZERO:
                    metrics.exits_ended_with_dust += 1
            if fill is not None:
                _journal(metrics, fill, quote.observed_at)
                metrics.fills_after_masked_span += int(after_span)
            metrics.frames += 1
            # P2: total equity after this quote's fills; buy-and-hold at the same quote.
            with localcontext() as context:
                context.prec = _PRECISION
                account.last_mark = exit_value(quote, rules)
                total = account.equity()
                metrics.final_equity = total
                metrics.peak_equity = max(metrics.peak_equity, total)
                drawdown = (metrics.peak_equity - total) / metrics.peak_equity
                metrics.max_drawdown = max(metrics.max_drawdown, drawdown)
            hold.mark(quote)
        metrics.signal_by_bar[_label(signal)] += 1
        metrics.bars_with_inventory += int(account.inventory > ZERO)
        hour = kline.open_ms // 3_600_000
        if hour != last_hour:
            metrics.hourly_equity.append(
                (kline.open_ms, str(metrics.final_equity), str(hold.value))
            )
            last_hour = hour
    if hold is not None:
        metrics.hold_final, metrics.hold_max_drawdown = hold.value, hold.max_drawdown
    return metrics, account


def check_trend_accounting(
    run: RunConfig, metrics: TrendMetrics, account: TrendAccount
) -> list[str]:
    """Exact identities between D's fill journal and its final account, including P6."""
    problems = []
    with localcontext() as context:
        context.prec = 80
        cash = (
            run.initial_quote
            - metrics.buy_notional
            - metrics.buy_fees
            + metrics.sell_notional
            - metrics.sell_fees
        )
        if cash != account.cash:
            problems.append(f"cash identity failed: journal {cash} != account {account.cash}")
        if account.cash < ZERO:
            problems.append(f"negative cash: {account.cash}")
        if metrics.bought - metrics.sold != account.inventory:
            problems.append("inventory identity failed")
        if metrics.buy_fees + metrics.sell_fees != account.fees:
            problems.append("fee identity failed")
        if metrics.frames:
            if account.equity() != metrics.final_equity:
                problems.append(
                    f"final equity identity failed: account {account.equity()} "
                    f"!= sampled {metrics.final_equity}"
                )
            # P6: realised + unrealised on held inventory = total equity change.
            unrealised = account.inventory * account.last_mark - metrics.cost_basis
            change = metrics.final_equity - run.initial_quote
            if abs(metrics.realised_pnl + unrealised - change) > Decimal("1e-18"):
                problems.append(
                    f"P&L reconciliation failed: {metrics.realised_pnl} + {unrealised} != {change}"
                )
    return problems


def summarise_trend(
    run: RunConfig, metrics: TrendMetrics, account: TrendAccount, problems: list[str]
) -> dict[str, Any]:
    """A results.json row for D. Field names match the grid rows where the meaning is
    the same, so the scorer can read both; D-only fields are added, never repurposed."""
    initial = run.initial_quote
    drawdown_pct = float(metrics.max_drawdown * 100)
    return {
        "symbol": run.symbol,
        "path_mode": run.path_mode,
        "strategy": STRATEGY,
        "variant": VARIANT,
        "benchmark": True,
        "selectable": False,  # spec §6: D is excluded before ranking
        "risk_policy": RISK_POLICY,
        "signal": f"completed daily close > SMA{SMA_LENGTH} of the traded pair, else cash",
        "window": [utc_iso(metrics.first_bar_ms), utc_iso(metrics.last_bar_ms)],
        "initial_quote": str(initial),
        "final_total_equity": str(metrics.final_equity),
        "return_pct": float((metrics.final_equity / initial - 1) * 100),
        "max_drawdown_pct": drawdown_pct,
        # One pot, no reserves: C1(b) reduces to C1(a) against its own peak (spec §3 D).
        "active_max_drawdown_pct": drawdown_pct,
        "hard_drawdown_halts": 0,
        "buy_and_hold_return_pct": float((metrics.hold_final / initial - 1) * 100),
        "buy_and_hold_max_drawdown_pct": float(metrics.hold_max_drawdown * 100),
        "fees": str(metrics.buy_fees + metrics.sell_fees),
        "turnover": str(metrics.buy_notional + metrics.sell_notional),
        "realised_pnl": str(metrics.realised_pnl),
        # P7 counts grid sells only; D places none.
        "completed_cycles": 0,
        "buys": metrics.buys,
        "sells": metrics.sells,
        "entries_started": metrics.entries_started,
        "exits_started": metrics.exits_started,
        "entries_abandoned": metrics.entries_abandoned,
        "exits_abandoned": metrics.exits_abandoned,
        "exits_ended_with_dust": metrics.exits_ended_with_dust,
        "grids_opened": 0,
        "range_exits": 0,
        "order_requests": sum(metrics.requests_by_day.values()),
        "max_order_requests_per_day": max(metrics.requests_by_day.values(), default=0),
        "days_over_request_budget": sum(
            1 for n in metrics.requests_by_day.values() if n > DAILY_REQUEST_BUDGET
        ),
        "final_cash": str(account.cash),
        "final_inventory": str(account.inventory),
        "bars": metrics.bars,
        "warmup_bars_skipped": metrics.warmup_bars,
        "frames": metrics.frames,
        "time_with_inventory_pct": 100 * metrics.bars_with_inventory / max(metrics.bars, 1),
        "signal_by_bar": dict(metrics.signal_by_bar),
        "halted_at": None,
        "transient_pauses": 0,  # D has no engine frames to reject
        "accounting_problems": problems,
        "rules": {key: str(value) for key, value in run.rules.identity().items()},
        "assumed_spread_pct": str(run.spread * 100),
        **mask_report(metrics),
        "hourly_equity": metrics.hourly_equity,
    }


def daily_history_problems(spec: DatasetSpec) -> list[str]:
    """D cannot run without daily bars; say so in the run instead of silently holding cash."""
    if spec.daily_warmup_start is None:
        return ["variant D needs daily bars: the dataset spec has no daily_warmup_start (P3)"]
    return []


def trend_job(
    spec_path: Path,
    config_path: Path,
    data_dir: Path,
    symbol: str,
    path_mode: str,
    fees: tuple[Decimal, Decimal | None] | None = None,
    *,
    masks: Masks | None = None,
) -> dict[str, Any]:
    """One D run, for the backtest CLI's process pool (see ``jobs`` on why pool work
    lives outside ``__main__``). ``fees`` is (maker, taker); D pays only the taker fee,
    which defaults to the maker fee exactly as for the grid runs. ``masks`` is every
    symbol's mask, as for ``jobs.run_job``: the pair's and the proxy's shape the warm-up
    gate, and the pair's drops its masked minutes, so no masked minute reaches D. The
    pair's own mask is reported in D's row, as in the grid rows."""
    # V0's warm-up gate, built by the grid job's own setup: FeatureEngine.at is None
    # exactly when the pair's or the market proxy's latest completed hour is not ready
    # (FeatureEngine.warmed). The basket changes only the values, never that gate, so it
    # is not loaded, and D evaluates V0's minutes.
    prepared = prepare_run(
        spec_path,
        config_path,
        data_dir,
        symbol,
        path_mode,
        False,
        fees,
        basket=False,
        masks=masks,
    )
    spec, manifest, run = prepared.spec, prepared.manifest, prepared.run
    problems = daily_history_problems(spec)
    # The pair's daily bars, loaded by prepare_run whenever the spec has daily history.
    closes = DailyCloses((k.open_ms, k.close) for k in prepared.daily or ())
    mask = (masks or {}).get(symbol)
    minutes = load_minutes(
        data_dir,
        manifest,
        symbol,
        mask=mask,
        excluded=exclusion_ranges(spec, symbol),
    )
    masked = mask or frozenset()
    metrics, account = replay_trend(
        run,
        minutes,
        closes,
        prepared.features.warmed,
        window=evaluation_window(spec),
        masked=masked,
        days_skipped_for_masks=skipped_days_for_masks(spec, masked),
    )
    problems += check_trend_accounting(run, metrics, account)
    return summarise_trend(run, metrics, account, problems)
