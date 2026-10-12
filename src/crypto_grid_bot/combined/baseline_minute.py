"""Frozen minute-replay baselines: the V0, V1 and V2 grids and comparator D.

Owner decisions of 2026-10-11 (docs/V3_1_SOURCE_INVENTORY.md): these are matched
baselines; each native path mode is its own arm; the frozen code takes capital as a
setting, so each pair receives an equal share; the final minute's close is the
window-end value (disclosed native timing). A share is floored to 8 decimals when the
capital does not split exactly; the remainder stays uninvested cash in every equity
mark, never traded, and is disclosed. Trading logic is never changed:

- grids run the frozen ``backtest.replay.replay`` with a read-only recorder that
  substitutes the simulator by a subclass whose ``step`` returns its parent's
  report unchanged and only remembers the hour-opening and the latest frame;
- comparator D runs the frozen ``replay_trend`` and is rebuilt from its own fill
  journal, with exact parity checks against its final equity, drawdown and hourly
  samples; any mismatch leaves the comparison incomplete.

An hour boundary is the account after that hour's opening quote (the quote stamped
exactly at the hour). A missing opening minute leaves that boundary absent, so the
comparison is incomplete, never a pass, unless the registration skips that hour.
A grid halt restarts by itself and D never halts: these replays have no native early
stop, so a stopped minute baseline is a failure (``baseline_records.NATIVE_STOPS``).
The registered job preparation owns the data, the path mode, the version's policy
and its declared doubled-cost rules. Every input is checked before any frozen code runs:
a minute outside the registered window, or any record at or after the reserved boundary,
is refused (never ignored).
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, localcontext
from fractions import Fraction
from threading import Lock
from typing import Any

from crypto_grid_bot.backtest import replay as minute_replay
from crypto_grid_bot.backtest.features import FeatureEngine
from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, bar_quotes, check_accounting, replay
from crypto_grid_bot.backtest.trend_benchmark import (
    _PRECISION,
    check_trend_accounting,
    exit_value,
    replay_trend,
)
from crypto_grid_bot.config import BotConfig
from crypto_grid_bot.simulation.runner import SimulationPolicy
from crypto_grid_bot.strategy.daily_sma import DailyCloses

from .baseline_records import BaselineEvidence, NativeMark, comparison_report, refuse_sealed
from .report import RESIDUAL_TOLERANCE, SAVED_FILTERS_DISCLOSURE, Contribution

HOUR = 3_600_000
_RECORDER_LOCK = Lock()
_PairMarks = tuple[dict[int, tuple[Decimal, Decimal]], tuple[int, Decimal, Decimal] | None]


@dataclass(frozen=True, slots=True)
class MinuteJob:
    """One pair's frozen grid replay inputs, as the registered job prepares them."""

    config: BotConfig
    run: RunConfig
    minutes: Sequence[Kline]
    features: FeatureEngine
    policy: SimulationPolicy | None = None
    daily: Sequence[Kline] | None = None
    hourly: Sequence[Kline] | None = None
    funding: Sequence[FundingRecord] | None = None
    window: tuple[int, int] | None = None
    masked: frozenset[int] = frozenset()
    days_skipped_for_masks: int = 0


@dataclass(frozen=True, slots=True)
class TrendJob:
    """One pair's frozen comparator-D inputs, as the registered job prepares them."""

    run: RunConfig
    minutes: Sequence[Kline]
    closes: DailyCloses
    evaluated: Callable[[int], bool]
    window: tuple[int, int] | None = None
    masked: frozenset[int] = frozenset()
    days_skipped_for_masks: int = 0


@dataclass
class _Frames:
    hours: dict[int, tuple[Decimal, Decimal]]
    last: tuple[int, Decimal, Decimal] | None = None


def _ms(observed_at: str) -> int:
    return int(datetime.fromisoformat(observed_at).timestamp() * 1000)


@contextmanager
def recorded_frames() -> Iterator[_Frames]:
    """Remember the hour-opening and latest frames of one frozen grid replay.

    Read-only: the subclass returns the frozen simulator's own report unchanged.
    The substitution is process-wide while active, so one replay at a time holds it.
    """
    frames = _Frames({})
    parent = vars(minute_replay)["PaperSimulator"]

    class RecordingSimulator(parent):  # type: ignore[misc, valid-type]
        def step(self, account: Any, frame: Any) -> dict[str, Any]:
            report: dict[str, Any] = super().step(account, frame)
            total = report.get("total_equity")
            if isinstance(total, Decimal):
                stamp = _ms(frame.quote.observed_at)
                # Frozen cash includes the pending reserve; active equity excludes it.
                spot = report["active_equity"] - report["cash"] + report["pending_reserve"]
                frames.last = (stamp, total, spot)
                if stamp % HOUR == 0 and frame.quote.event_id.endswith("/0"):
                    frames.hours[stamp] = (total, spot)
            return report

    with _RECORDER_LOCK:
        namespace = vars(minute_replay)
        namespace["PaperSimulator"] = RecordingSimulator
        try:
            yield frames
        finally:
            namespace["PaperSimulator"] = parent


def _refuse_minutes(symbol: str, minutes: Sequence[Kline], start_ms: int, end_ms: int) -> None:
    """Refuse a minute outside ``[start_ms, end_ms)`` or at or after the reserved boundary.

    The frozen replay plays, and trades on, every minute it is given. It needs none
    before the window: its warm-up is the hourly and daily history behind the feature
    engine (the frozen ``replayed_minutes`` drops earlier minutes as "warm-up and not
    played"), and its taker-flow window starts empty at the first played minute. So no
    minute before ``start_ms`` is allowed, and none from ``end_ms`` on.
    """
    refuse_sealed((bar.open_ms for bar in minutes), f"{symbol} minutes")
    if any(not start_ms <= bar.open_ms < end_ms for bar in minutes):
        raise ValueError(f"{symbol} minutes: a minute outside the registered window is refused")


def _refuse_grid_inputs(jobs: Mapping[str, MinuteJob], start_ms: int, end_ms: int) -> None:
    for symbol in sorted(jobs):
        job = jobs[symbol]
        _refuse_minutes(symbol, job.minutes, start_ms, end_ms)
        refuse_sealed((bar.open_ms for bar in job.daily or ()), f"{symbol} daily")
        refuse_sealed((bar.open_ms for bar in job.hourly or ()), f"{symbol} hourly")
        refuse_sealed((row.calc_time_ms for row in job.funding or ()), f"{symbol} funding")
        # The frozen engine has no accessor for the history it was built from.
        engine = job.features
        for series in (engine.pair, engine.market, *engine.basket):
            refuse_sealed(series.opens, f"{symbol} feature series {series.symbol}")
        refuse_sealed(engine._daily_opens, f"{symbol} feature daily bars")


def _refuse_trend_inputs(jobs: Mapping[str, TrendJob], start_ms: int, end_ms: int) -> None:
    for symbol in sorted(jobs):
        job = jobs[symbol]
        _refuse_minutes(symbol, job.minutes, start_ms, end_ms)
        refuse_sealed(job.closes._closes, f"{symbol} daily closes")  # no accessor either


def _shares(initial: Decimal, symbols: Sequence[str]) -> tuple[Decimal, Decimal]:
    """Each pair's equal share, and the remainder the pairs leave as uninvested cash.

    An exact split at 8 decimals or fewer is used as it is; otherwise the share is
    floored to 8 decimals and the rest of the capital stays cash, never traded.
    """
    count = len(symbols)
    with localcontext() as context:
        context.prec = 60
        share = initial / count
        if share * count != initial or share.as_tuple().exponent < -8:  # type: ignore[operator]
            share = share.quantize(Decimal("1e-8"), rounding=ROUND_FLOOR)
        remainder = initial - share * count
    if share <= 0:
        raise ValueError("capital must give each pair a positive share")
    return share, remainder


def _remainder_disclosures(remainder: Decimal) -> tuple[str, ...]:
    return (f"minute_baseline_capital_remainder_cash:{remainder:f}",) if remainder else ()


def _portfolio(
    arm: str,
    per_pair: Mapping[
        str, tuple[dict[int, tuple[Decimal, Decimal]], tuple[int, Decimal, Decimal] | None]
    ],
    *,
    initial: Decimal,
    remainder: Decimal,
    start_ms: int,
    end_ms: int,
) -> tuple[list[NativeMark], list[str]]:
    """The portfolio's marks: the pairs' totals plus the uninvested remainder cash."""

    def total(values: list[Decimal], cash: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 60
            return sum(values, Decimal(0)) + cash

    marks = [NativeMark(start_ms, "before_frames", initial, Decimal(0), Decimal(0))]
    issues: list[str] = []
    for hour in range(start_ms, end_ms, HOUR):
        values = [hours.get(hour) for hours, _ in per_pair.values()]
        if all(value is not None for value in values):
            marks.append(
                NativeMark(
                    hour,
                    "opening_quote",
                    total([v[0] for v in values if v is not None], remainder),
                    total([v[1] for v in values if v is not None], Decimal(0)),
                    Decimal(0),
                )
            )
    lasts = [last for _, last in per_pair.values()]
    if all(last is not None and end_ms - 60_000 <= last[0] < end_ms for last in lasts):
        marks.append(
            NativeMark(
                end_ms,
                "final_minute_close",
                total([last[1] for last in lasts if last is not None], remainder),
                total([last[2] for last in lasts if last is not None], Decimal(0)),
                Decimal(0),
            )
        )
    else:
        issues.append(f"{arm}:final_minute_unavailable")
    return marks, issues


def _evidence(
    arm: str,
    label: str,
    marks: list[NativeMark],
    contributions: list[Contribution],
    issues: list[str],
    *,
    initial: Decimal,
    start_ms: int,
    end_ms: int,
    source_refs: tuple[str, ...],
    adapter_pin: str,
    exact: bool,
    status: str | None,
    skipped_hours: tuple[int, ...],
    capital_label: str | None,
    remainder: Decimal,
) -> BaselineEvidence:
    report = comparison_report(
        arm,
        marks,
        contributions,
        initial=initial,
        start_ms=start_ms,
        end_ms=end_ms,
        source_refs=source_refs,
        adapter_pin=adapter_pin,
        producer_issues=tuple(issues),
        skipped_hours=skipped_hours,
        disclosures=(
            "minute_baseline_final_minute_close_is_window_end",
            "equal_capital_share_per_pair",
            *_remainder_disclosures(remainder),
            SAVED_FILTERS_DISCLOSURE,
        ),
        capital_label=capital_label,
    )
    residual = report.reconciliation_residual
    return BaselineEvidence(
        arm,
        label,
        tuple(marks),
        report,
        status,
        0,
        residual or Decimal(0),
        residual is not None and abs(Fraction(residual)) <= RESIDUAL_TOLERANCE,
        exact,
        report.disclosures,
    )


def replay_grid_baseline(
    arm: str,
    jobs: Mapping[str, MinuteJob],
    *,
    start_ms: int,
    end_ms: int,
    initial: Decimal,
    source_refs: tuple[str, ...],
    adapter_pin: str,
    skipped_hours: tuple[int, ...] = (),
    capital_label: str | None = None,
) -> BaselineEvidence:
    """Replay one frozen grid version and path mode per pair, as one portfolio."""
    if not jobs:
        raise ValueError("at least one pair job required")
    _refuse_grid_inputs(jobs, start_ms, end_ms)
    share, remainder = _shares(initial, sorted(jobs))
    per_pair: dict[str, _PairMarks] = {}
    contributions: list[Contribution] = []
    issues: list[str] = []
    exact = True
    status = None
    for symbol in sorted(jobs):
        job = jobs[symbol]
        run = replace(job.run, initial_quote=share)
        try:
            with recorded_frames() as frames:
                metrics, account = replay(
                    job.config,
                    run,
                    job.minutes,
                    job.features,
                    job.policy,
                    list(job.daily) if job.daily is not None else None,
                    list(job.hourly) if job.hourly is not None else None,
                    list(job.funding) if job.funding is not None else None,
                    window=job.window,
                    masked=job.masked,
                    days_skipped_for_masks=job.days_skipped_for_masks,
                )
        except (ValueError, ArithmeticError) as exc:
            issues.append(f"{arm}:{symbol}:engine_failure:{type(exc).__name__}")
            status = "engine_failure"
            per_pair[symbol] = ({}, None)
            continue
        per_pair[symbol] = (frames.hours, frames.last)
        exact = exact and not check_accounting(run, metrics, account)
        fees = metrics.buy_fees + metrics.sell_fees
        contributions.append(
            Contribution(
                f"{arm}:{symbol}",
                arm,
                symbol,
                "long",
                None,
                metrics.final_equity - share + fees,
                fees,
                Decimal(0),
                metrics.buy_notional + metrics.sell_notional,
                None,
                start_ms,
                "open_marked",
                source_refs=source_refs,
            )
        )
    marks, portfolio_issues = _portfolio(
        arm, per_pair, initial=initial, remainder=remainder, start_ms=start_ms, end_ms=end_ms
    )
    return _evidence(
        arm,
        "minute-grid-native",
        marks,
        contributions,
        issues + portfolio_issues,
        initial=initial,
        start_ms=start_ms,
        end_ms=end_ms,
        source_refs=source_refs,
        adapter_pin=adapter_pin,
        exact=exact,
        status=status,
        skipped_hours=skipped_hours,
        capital_label=capital_label,
        remainder=remainder,
    )


def replay_trend_baseline(
    arm: str,
    jobs: Mapping[str, TrendJob],
    *,
    start_ms: int,
    end_ms: int,
    initial: Decimal,
    source_refs: tuple[str, ...],
    adapter_pin: str,
    skipped_hours: tuple[int, ...] = (),
    capital_label: str | None = None,
) -> BaselineEvidence:
    """Replay frozen comparator D per pair and rebuild its marks from its journal."""
    if not jobs:
        raise ValueError("at least one pair job required")
    _refuse_trend_inputs(jobs, start_ms, end_ms)
    share, remainder = _shares(initial, sorted(jobs))
    per_pair: dict[str, _PairMarks] = {}
    contributions: list[Contribution] = []
    issues: list[str] = []
    exact = True
    for symbol in sorted(jobs):
        job = jobs[symbol]
        run = replace(job.run, initial_quote=share)
        metrics, account = replay_trend(
            run,
            job.minutes,
            job.closes,
            job.evaluated,
            window=job.window,
            masked=job.masked,
            days_skipped_for_masks=job.days_skipped_for_masks,
        )
        rebuilt = _rebuild_trend(run, job, metrics)
        if rebuilt is None:
            issues.append(f"{arm}:{symbol}:journal_parity_failed")
            per_pair[symbol] = ({}, None)
        else:
            per_pair[symbol] = rebuilt
        exact = exact and not check_trend_accounting(run, metrics, account)
        fees = metrics.buy_fees + metrics.sell_fees
        contributions.append(
            Contribution(
                f"{arm}:{symbol}",
                arm,
                symbol,
                "long",
                None,
                metrics.final_equity - share + fees,
                fees,
                Decimal(0),
                metrics.buy_notional + metrics.sell_notional,
                None,
                start_ms,
                "open_marked",
                source_refs=source_refs,
            )
        )
    marks, portfolio_issues = _portfolio(
        arm, per_pair, initial=initial, remainder=remainder, start_ms=start_ms, end_ms=end_ms
    )
    return _evidence(
        arm,
        "minute-trend-d-native",
        marks,
        contributions,
        issues + portfolio_issues,
        initial=initial,
        start_ms=start_ms,
        end_ms=end_ms,
        source_refs=source_refs,
        adapter_pin=adapter_pin,
        exact=exact,
        status=None,
        skipped_hours=skipped_hours,
        capital_label=capital_label,
        remainder=remainder,
    )


def _rebuild_trend(
    run: RunConfig, job: TrendJob, metrics: Any
) -> tuple[dict[int, tuple[Decimal, Decimal]], tuple[int, Decimal, Decimal] | None] | None:
    """Per-quote equity from D's own journal; None unless it matches D exactly."""
    journal: dict[str, list[Any]] = {}
    for observed_at, fill in metrics.fills:
        journal.setdefault(observed_at, []).append(fill)
    cash, inventory = run.initial_quote, Decimal(0)
    peak, drawdown = run.initial_quote, Decimal(0)
    hours: dict[int, tuple[Decimal, Decimal]] = {}
    hourly: list[tuple[int, str, str]] = []
    last: tuple[int, Decimal, Decimal] | None = None
    last_hour = -1
    total = run.initial_quote
    for kline in job.minutes:
        if not job.evaluated(kline.open_ms):
            continue
        for quote in bar_quotes(kline, run.symbol, run.path_mode, run.spread, run.rules.tick_size):
            with localcontext() as context:
                context.prec = _PRECISION
                for fill in journal.get(quote.observed_at, ()):
                    if not fill.order_id.endswith(quote.event_id):
                        continue
                    if fill.side == "buy":
                        cash -= fill.price * fill.quantity + fill.fee
                        inventory += fill.quantity
                    else:
                        cash += fill.price * fill.quantity - fill.fee
                        inventory -= fill.quantity
                spot = inventory * exit_value(quote, run.rules)
                total = cash + spot
                peak = max(peak, total)
                drawdown = max(drawdown, (peak - total) / peak)
            stamp = _ms(quote.observed_at)
            last = (stamp, total, spot)
            if stamp % HOUR == 0 and quote.event_id.endswith("/0"):
                hours[stamp] = (total, spot)
        hour = kline.open_ms // HOUR
        if hour != last_hour:
            hourly.append((kline.open_ms, str(total), ""))
            last_hour = hour
    frozen_hourly = [(stamp, total_text) for stamp, total_text, _ in metrics.hourly_equity]
    if (
        total != metrics.final_equity
        or drawdown != metrics.max_drawdown
        or [(stamp, text) for stamp, text, _ in hourly] != frozen_hourly
    ):
        return None
    return hours, last
