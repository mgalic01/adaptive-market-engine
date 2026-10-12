"""Frozen V3 baselines: the selector and its six fixed long-only rules.

Owner decisions of 2026-10-11 (docs/V3_1_SOURCE_INVENTORY.md): both are matched
baselines; ~EUR100 runs use a capital adapter that only sets the starting capital;
V3's funding, booked a few milliseconds after the hour and after that hour's fills,
is native timing and is disclosed. The frozen V3 modules run unchanged: no trading
rule, cost, size multiple, output or timestamp is altered here. Every input record
is checked before any frozen code runs: an hourly bar or a funding stamp at or after
the reserved boundary is refused, never ignored, in a replay and in training. (The
frozen daily decisions refuse such a daily bar when they are built.)
"""

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from threading import Lock, local

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.trend import replay as v3_replay
from crypto_grid_bot.trend.account import FuturesAccount
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orchestration import Attempt, run_walk_forward
from crypto_grid_bot.trend.replay import ReplayExecutionError, ReplayResult, replay_window
from crypto_grid_bot.trend.runner import TrendRunner

from .baseline_records import (
    NATIVE_STOPS,
    BaselineEvidence,
    NativeMark,
    comparison_report,
    refuse_sealed,
)
from .report import Contribution

LONG_RULES = {f"unchanged_v3_r{index}_long_only": f"R{index}L" for index in range(1, 7)}
SELECTOR = "unchanged_v3_selector"
V3_MULTIPLE = 2  # the frozen main test's size multiple
V3_TOLERANCE = Decimal("1e-18")  # the frozen strict audit's equity bound
_CAPITAL_LOCK = Lock()
_HOLDER = local()  # per thread: whether this thread holds _CAPITAL_LOCK


@dataclass(frozen=True, slots=True)
class V3Inputs:
    """The registered frozen V3 inputs; source validation happens upstream."""

    decisions: DailyDecisions
    filters: Mapping[str, OrderFilters]
    hourly: Mapping[str, Sequence[Kline]]
    funding: Mapping[int, Mapping[str, Decimal]]


def _refuse_sealed(inputs: V3Inputs) -> None:
    """Refuse any record the replays or the training read at or after the boundary."""
    for symbol, rows in inputs.hourly.items():
        refuse_sealed((row.open_ms for row in rows), f"{symbol} hourly")
    refuse_sealed(inputs.funding, "funding")


@contextmanager
def _exclusive(what: str) -> Iterator[None]:
    """Hold the process-wide lock that keeps capital runs and selector training apart.

    Both depend on which ``TrendRunner`` the frozen replay module holds, so only one
    runs at a time. A thread already holding the lock would wait for itself: refused.
    """
    if getattr(_HOLDER, "held", False):
        raise RuntimeError(f"{what} cannot start inside another capital run or training")
    with _CAPITAL_LOCK:
        _HOLDER.held = True
        try:
            yield
        finally:
            _HOLDER.held = False


@contextmanager
def v3_capital(initial: Decimal) -> Iterator[None]:
    """Run unchanged V3 code with another starting capital (owner, 2026-10-11).

    Substitutes ``trend.replay.TrendRunner`` by a subclass whose only change is the
    account's starting capital and the matching starting peak; it gives identical
    results at 10,000 USDT. The substitution is process-wide while active, so one
    replay at a time holds it, and selector training waits for it (``selector_picks``
    takes the same lock), so training never sees another capital.
    """
    if not isinstance(initial, Decimal) or not initial.is_finite() or initial <= 0:
        raise ValueError("finite positive starting capital required")

    class CapitalTrendRunner(TrendRunner):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self.account = FuturesAccount(initial=initial, cost_multiple=self.account.cost_multiple)
            self.peak = self.account.initial

    with _exclusive("a capital run"):
        namespace = vars(v3_replay)  # the frozen module's own globals, not its source
        original = namespace["TrendRunner"]
        namespace["TrendRunner"] = CapitalTrendRunner
        try:
            yield
        finally:
            namespace["TrendRunner"] = original


def selector_picks(
    inputs: V3Inputs, *, record: Callable[[Attempt], None]
) -> tuple[dict[int, str | None], ReplayResult]:
    """The frozen walk-forward picks at research capital and base cost.

    Training holds the capital adapter's lock, so it never runs while any thread has
    another starting capital in force: the selection is V3's own, at 10,000. The
    continuous out-of-sample account is returned as native evidence.
    """
    _refuse_sealed(inputs)
    with _exclusive("selector training"):
        result = run_walk_forward(
            inputs.decisions, inputs.filters, inputs.hourly, inputs.funding, record=record
        )
    return dict(result.picks), result.out_of_sample


def window_picks(
    picks: Mapping[int, str | None], start_ms: int, end_ms: int
) -> dict[int, str | None] | None:
    """The frozen picks in force over a registered window, or None before any pick."""
    prior = [stamp for stamp in picks if stamp <= start_ms]
    if not prior:
        return None
    return {
        start_ms: picks[max(prior)],
        **{stamp: rule for stamp, rule in picks.items() if start_ms < stamp < end_ms},
    }


def _native_marks(result: ReplayResult, inputs: V3Inputs, end_ms: int) -> tuple[NativeMark, ...]:
    runner = result.runner
    if runner is None:
        return ()
    flat = [mark for _, _, hour in runner.hours for _, mark in hour.marks]
    path = list(runner.equity_path)
    terminal = path[-1] if path and path[-1].kind == "terminal" else None
    states = path[:-1] if terminal is not None else path
    if len(states) != len(flat):
        raise ValueError("V3 marks and equity path disagree")
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        marks = [
            NativeMark(
                state.timestamp_ms,
                state.kind,
                state.equity,
                Decimal(0),
                mark.gross_notional / V3_MULTIPLE,
            )
            for state, mark in zip(states, flat, strict=True)
        ]
        if terminal is not None:
            closes = {
                symbol: max(
                    (row for row in rows if row.open_ms < terminal.timestamp_ms),
                    key=lambda row: row.open_ms,
                ).close
                for symbol, rows in inputs.hourly.items()
                if any(row.open_ms < terminal.timestamp_ms for row in rows)
            }
            gross = sum(
                (
                    abs(position.quantity) * closes[symbol]
                    for symbol, position in runner.account.positions.items()
                    if position.quantity
                ),
                Decimal(0),
            )
            marks.append(
                NativeMark(
                    terminal.timestamp_ms,
                    "terminal",
                    terminal.equity,
                    Decimal(0),
                    gross / V3_MULTIPLE,
                )
            )
    return tuple(marks)


def _contributions(arm: str, result: ReplayResult, refs: tuple[str, ...]) -> list[Contribution]:
    runner = result.runner
    if runner is None:
        return []
    rows = []
    lives = (*runner.lifecycles.completed, *runner.lifecycles.active.values())
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        for index, life in enumerate(lives):
            closed = life.end_ms is not None and not life.censored
            rows.append(
                Contribution(
                    f"{arm}:{index}:{life.symbol}:{life.start_ms}",
                    "unchanged_v3",
                    life.symbol,
                    life.side,
                    None,
                    life.realized + life.unrealized,
                    life.fees,
                    life.funding_received - life.funding_paid,
                    sum((abs(fill.quantity) * fill.price for fill in life.fills), Decimal(0)),
                    life.exit_reason if closed else None,
                    life.start_ms,
                    "closed" if closed else "open_marked",
                    life.end_ms if closed else None,
                    source_refs=refs,
                )
            )
    return rows


def replay_v3_baseline(
    arm: str,
    inputs: V3Inputs,
    *,
    start_ms: int,
    end_ms: int,
    initial: Decimal,
    cost_multiple: int,
    source_refs: tuple[str, ...],
    adapter_pin: str,
    picks: Mapping[int, str | None] | None = None,
    skipped_hours: tuple[int, ...] = (),
) -> BaselineEvidence:
    """Replay one frozen V3 baseline cell once and build its comparison evidence.

    A selector cell replays the frozen picks in force over the registered window;
    a window starting before the first out-of-sample pick has no selector cell and
    stays incomplete. A native stop (liquidation, no tradable position, leverage not
    restored) is a finished result whose stop equity is held, labelled frozen, to the
    window end (owner, 2026-10-11). An engine failure or unavailable exclusion close
    keeps its partial evidence and makes the comparison incomplete, never a pass.
    """
    _refuse_sealed(inputs)
    disclosures = ["v3_funding_after_fills_is_native_timing"]
    if arm in LONG_RULES:
        schedule: dict[int, str | None] | None = {start_ms: LONG_RULES[arm]}
    elif arm == SELECTOR:
        schedule = window_picks(picks or {}, start_ms, end_ms)
        disclosures.append("v3_selector_frozen_picks_on_registered_window")
    else:
        raise ValueError("unknown frozen V3 baseline arm")
    if initial != Decimal(10000):
        disclosures.append("v3_capital_adapter_sets_only_starting_capital")
    if schedule is None:
        report = comparison_report(
            arm,
            (),
            (),
            initial=initial,
            start_ms=start_ms,
            end_ms=end_ms,
            source_refs=source_refs,
            adapter_pin=adapter_pin,
            producer_issues=("v3_selector_has_no_pick_before_window",),
            skipped_hours=skipped_hours,
        )
        return BaselineEvidence(
            arm,
            "v3-native",
            (),
            report,
            "no_selector_pick",
            0,
            Decimal(0),
            False,
            None,
            tuple(disclosures),
        )
    try:
        with v3_capital(initial):
            result = replay_window(
                inputs.decisions,
                inputs.filters,
                inputs.hourly,
                inputs.funding,
                start_ms,
                end_ms,
                schedule,
                multiple=V3_MULTIPLE,
                cost_multiple=cost_multiple,
            )
    except ReplayExecutionError as exc:
        result = exc.partial_result
    marks = _native_marks(result, inputs, end_ms)
    contributions = _contributions(arm, result, source_refs)
    status = result.reason
    native_stop = status if status in NATIVE_STOPS else None
    if native_stop is not None:
        disclosures.append(f"baseline_native_stop_equity_frozen:{native_stop}")
    report = comparison_report(
        arm,
        marks,
        contributions,
        initial=initial,
        start_ms=start_ms,
        end_ms=end_ms,
        source_refs=source_refs,
        adapter_pin=adapter_pin,
        producer_issues=() if status is None or native_stop else (f"baseline_stop:{status}",),
        native_stop=native_stop,
        skipped_hours=skipped_hours,
    )
    runner = result.runner
    audits = runner.audits if runner is not None else []
    residual = report.reconciliation_residual or Decimal(0)
    return BaselineEvidence(
        arm,
        "v3-native",
        marks,
        report,
        status,
        1 if status == "liquidation" else 0,
        residual,
        abs(residual) <= V3_TOLERANCE and bool(audits) and all(a.accepted for a in audits),
        bool(audits)
        and all(
            a.wallet_residual == 0 and all(value == 0 for value in a.quantity_residuals.values())
            for a in audits
        ),
        tuple(disclosures),
    )
