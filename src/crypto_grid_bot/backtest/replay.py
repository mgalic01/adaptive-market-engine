"""Historical replay of the paper engine on verified Binance klines.

Kline-to-quote adapter (the explicit, tested adapter BACKTEST_PLAN.md requires):

* Each 1m bar becomes four quotes (open, first extreme, second extreme, close) at
  +0/+9/+19/+29 s, all under one epoch, so an order created inside a bar cannot fill
  until a later bar. ``high_first`` visits the high before the low; ``low_first`` the
  reverse. The true order is unknown, so both are reported.
* Klines have no bid/ask. At the high a trade lifted the ask (ask = high, bid one
  assumed spread lower); at the low a trade hit the bid (bid = low, ask one spread
  higher); open and close are mid prices. Prices round outward to the tick. The engine
  still requires a limit to be crossed by slippage, so touching a level never fills.
* Liquidity: taker-sell volume can fill resting buys and taker-buy volume resting
  sells. Each side's bar volume is split evenly over the four quotes and the engine's
  participation cap applies to each share, so a bar's volume is never spent twice.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.dataset import local_path
from crypto_grid_bot.backtest.features import FEATURE_VERSION, FeatureEngine, Inputs
from crypto_grid_bot.backtest.klines import Kline, aggregate, read_archive
from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals
from crypto_grid_bot.simulation.models import ONE, ZERO, Account, MarketRules, Quote, floor_step
from crypto_grid_bot.simulation.runner import Frame, PaperSimulator, SimulationPolicy

PATH_MODES = ("high_first", "low_first")
# Scorer context lines that precede its actual failure reasons.
_CONTEXT = ("base quality", "regime fit", "news multiplier")
POINT_OFFSETS_S = (0, 9, 19, 29)
QUARTER = Decimal("0.25")


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
            ask = kline.high
            bid = _round(kline.high * (ONE - spread), tick, ROUND_FLOOR)
        elif kind == "low":
            bid = kline.low
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


def signals_for(inputs: Inputs, observed_at: datetime, *, gated: bool) -> MarketSignals:
    if not gated:
        # Ungated baseline: a quiet, fully trusted range, so only risk limits intervene.
        return MarketSignals(0.0, 0.0, 0.0, 0.0, 0.0, 10.0, observed_at=observed_at)
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
    inputs: Inputs, symbol: str, spread_pct: float, *, gated: bool
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
        inputs.depth_multiple,
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


def _record_fills(metrics: Metrics, fills: Sequence[dict[str, Any]]) -> None:
    for fill in fills:
        quantity, fee = Decimal(fill["quantity"]), Decimal(fill["fee"])
        notional = Decimal(fill["price"]) * quantity
        if fill["side"] == "buy":
            metrics.buys += 1
            metrics.buy_notional += notional
            metrics.buy_fees += fee
            metrics.bought += quantity
        else:
            metrics.sells += 1
            metrics.sell_notional += notional
            metrics.sell_fees += fee
            metrics.sold += quantity


class _BuyAndHold:
    """Buy once at the first evaluated bar (ask + slippage + fee); conservative marks."""

    def __init__(self, run: RunConfig, first: Kline) -> None:
        rules = run.rules
        ask = _round(first.open * (ONE + run.spread / 2), rules.tick_size, ROUND_CEILING)
        price = ask * (ONE + rules.slippage_rate)
        self.quantity = floor_step(
            run.initial_quote / (price * (ONE + rules.fee_rate)), rules.quantity_step
        )
        self.cash = run.initial_quote - self.quantity * price * (ONE + rules.fee_rate)
        self.run = run
        self.peak = self.value = run.initial_quote
        self.max_drawdown = ZERO

    def mark(self, kline: Kline) -> None:
        rules = self.run.rules
        bid = _round(kline.close * (ONE - self.run.spread / 2), rules.tick_size, ROUND_FLOOR)
        exit_value = bid * (ONE - rules.slippage_rate) * (ONE - rules.fee_rate)
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
    metrics = Metrics(peak_equity=run.initial_quote, final_equity=run.initial_quote)
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
        candidate = candidate_for(inputs, run.symbol, spread_pct, gated=run.gated)
        epoch = f"{run.symbol}/{kline.open_ms}"
        report: dict[str, Any] = {}
        for quote in bar_quotes(kline, run.symbol, run.path_mode, run.spread, run.rules.tick_size):
            frame = Frame(quote, signals, candidate, inputs.fair_value, inputs.atr, True, epoch)
            report = simulator.step(account, frame)
            metrics.frames += 1
            _record_fills(metrics, report["fills"])
            metrics.grids_opened += int(bool(report["opened"]))
            exiting = bool(report.get("range_exit"))
            metrics.range_exits += int(exiting and not was_range_exit)
            was_range_exit = exiting
            metrics.transient_pauses += int("regime" not in report)
            if account.halt and not metrics.halted_at:
                metrics.halted_at, metrics.halt_reason = quote.observed_at, account.halt
            if "total_equity" in report:
                total = Decimal(report["total_equity"])
                metrics.final_equity = total
                metrics.peak_equity = max(metrics.peak_equity, total)
                drawdown = (metrics.peak_equity - total) / metrics.peak_equity
                metrics.max_drawdown = max(metrics.max_drawdown, drawdown)
        hold.mark(kline)
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


def load_minutes(data_dir: Path, manifest: dict[str, Any], symbol: str) -> Iterator[Kline]:
    months = sorted(
        e["month"]
        for e in manifest["files"]
        if e["symbol"] == symbol and e["interval"] == "1m" and e["status"] == "ok"
    )
    for month in months:
        rows, _ = read_archive(local_path(data_dir, symbol, "1m", month), symbol, "1m", month)
        yield from rows


def cross_check_hourly(minutes: Iterable[Kline], hourly: Sequence[Kline]) -> dict[str, int]:
    """Compare 1m bars aggregated to hours against Binance's own 1h archive."""
    official = {k.open_ms: k for k in hourly}
    compared = mismatched = missing = 0
    for candle in aggregate(minutes):
        reference = official.get(candle.open_ms)
        if reference is None:
            missing += 1
            continue
        compared += 1
        ours = (candle.open, candle.high, candle.low, candle.close, candle.volume)
        theirs = (reference.open, reference.high, reference.low, reference.close, reference.volume)
        mismatched += int(ours != theirs)
    return {"hours_compared": compared, "hours_mismatched": mismatched, "hours_missing": missing}


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
        "rules": {key: str(value) for key, value in asdict(run.rules).items()},
        "assumed_spread_pct": str(run.spread * 100),
        "hourly_equity": metrics.hourly_equity,
    }


def rules_for(
    symbol: str,
    instrument: dict[str, str],
    spec_fee: Decimal,
    spec_slippage: Decimal,
    participation: Decimal,
) -> MarketRules:
    return MarketRules(
        symbol=symbol,
        tick_size=Decimal(instrument["tick_size"]),
        quantity_step=Decimal(instrument["quantity_step"]),
        minimum_notional=Decimal(instrument["min_notional"]),
        fee_rate=spec_fee,
        slippage_rate=spec_slippage,
        participation=participation,
    )
