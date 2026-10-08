"""Frozen walk-forward orchestration over supplied, prevalidated in-memory inputs."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.metrics import summarize_runner
from crypto_grid_bot.trend.replay import ReplayResult, replay_window
from crypto_grid_bot.trend.walk_forward import RULES, choose_rule, windows

INVALID = frozenset(
    {"liquidation", "no_tradable_position", "leverage_not_restored", "unavailable_exclusion_close"}
)


@dataclass(frozen=True, slots=True)
class Attempt:
    run_id: str
    phase: str
    rule: str | None
    start_ms: int
    end_ms_exclusive: int
    result: ReplayResult | None
    error: str | None


@dataclass(frozen=True, slots=True)
class TrainingScore:
    run_id: str
    test_month: str
    rule: str
    sharpe: Decimal | None
    invalid_reason: str | None


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    training: tuple[TrainingScore, ...]
    picks: dict[int, str | None]
    out_of_sample: ReplayResult


def run_walk_forward(
    decisions: DailyDecisions,
    filters: Mapping[str, OrderFilters],
    hourly: Mapping[str, Sequence[Kline]],
    funding: Mapping[int, Mapping[str, Decimal]],
    *,
    record: Callable[[Attempt], None],
) -> WalkForwardResult:
    """Run the fixed m=2, base-cost picker and one continuous OOS account.

    The caller must persist each record before returning, including invalid/error
    evidence, and enforce registered dispatch before calling. Recording failure
    aborts this routine. Only compact scores remain in memory across training
    runs; recorders must serialize rather than accumulate full runner references.
    """
    first = decisions.first_months.get("BTCUSDT")
    if first is None:
        raise ValueError("BTCUSDT portfolio start is required")
    calendar = windows(first)
    prefix = uuid4().hex
    training = []
    picks = {}
    for window in calendar:
        start = month_bounds_ms(window.train_start)[0]
        end = month_bounds_ms(window.train_end_exclusive)[0]
        scores = {}
        for rule in RULES:
            run_id = f"{prefix}-train-{window.test_start}-{rule}"
            result = None
            try:
                result = replay_window(
                    decisions,
                    filters,
                    hourly,
                    funding,
                    start,
                    end,
                    {start: rule},
                    multiple=2,
                    cost_multiple=1,
                )
                if result.reason is not None:
                    if result.reason not in INVALID:
                        raise ValueError("unknown strategy-invalid outcome")
                    score = None
                else:
                    if result.runner is None:
                        raise ValueError("successful replay has no account evidence")
                    score = summarize_runner(result.runner).sharpe
            except Exception as exc:
                record(
                    Attempt(
                        run_id, "training", rule, start, end, result, f"{type(exc).__name__}: {exc}"
                    )
                )
                raise
            record(Attempt(run_id, "training", rule, start, end, result, None))
            scores[rule] = score
            training.append(TrainingScore(run_id, window.test_start, rule, score, result.reason))
        picks[end] = choose_rule(scores)
    start = min(picks)
    # This is only an exclusive timestamp boundary, not a requested 2025 price.
    end = month_bounds_ms(calendar[-1].test_end_exclusive)[0]
    run_id = f"{prefix}-out-of-sample-m2"
    result = None
    try:
        result = replay_window(
            decisions, filters, hourly, funding, start, end, picks, multiple=2, cost_multiple=1
        )
        if result.reason is not None and result.reason not in INVALID:
            raise ValueError("unknown strategy-invalid outcome")
    except Exception as exc:
        record(
            Attempt(
                run_id, "out_of_sample", None, start, end, result, f"{type(exc).__name__}: {exc}"
            )
        )
        raise
    record(Attempt(run_id, "out_of_sample", None, start, end, result, None))
    return WalkForwardResult(tuple(training), picks, result)
