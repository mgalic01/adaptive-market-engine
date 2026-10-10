"""Run the frozen supplied-input menu; historical authorization stays upstream."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.evidence_writer import AttemptRecorder, replay_spot_recorded
from crypto_grid_bot.trend.experiment_report import ExperimentReport, build_experiment_report
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.full_size_hold_evidence import replay_full_size_hold_recorded
from crypto_grid_bot.trend.orchestration import (
    replay_fixed_rules,
    replay_sensitivities,
    run_walk_forward,
)
from crypto_grid_bot.trend.spot_benchmark import HoldDecisions


def run_experiment(
    *,
    directory: Path,
    spot_bars: Mapping[str, Sequence[Kline]],
    first_months: Mapping[str, str],
    spot_hourly: Mapping[str, Sequence[Kline]],
    hold_hourly: Mapping[str, Sequence[Kline]],
    futures_hourly: Mapping[str, Sequence[Kline]],
    spot_filters: Mapping[str, OrderFilters],
    futures_filters: Mapping[str, OrderFilters],
    funding: Mapping[int, Mapping[str, Decimal]],
    futures_exclusions: Mapping[str, frozenset[str]] | None = None,
    spot_exclusions: Mapping[str, frozenset[str]] | None = None,
) -> ExperimentReport:
    """Journal each attempt and return the existing, explicitly uncertified report.

    Caller owns prevalidated input provenance and all registration/data-access
    gates. This function performs no input file access, fetch or authorization.
    Each invocation requires a new evidence directory, retained on all failures;
    it does not resume or retry failed experiments. Strategy-invalid outcomes
    stay in the menu; engine or evidence failures abort before report assembly.
    hold_hourly is the dedicated unmasked full-size price stream; it must not be
    substituted with eligible-only strategy prices. Final certification is upstream.
    """
    universe = set(first_months)
    if "BTCUSDT" not in universe or any(
        set(values) != universe
        for values in (
            spot_bars,
            spot_hourly,
            hold_hourly,
            futures_hourly,
            spot_filters,
            futures_filters,
        )
    ):
        raise ValueError("all experiment inputs require the same BTC-containing universe")
    if not (set(futures_exclusions or {}) | set(spot_exclusions or {})) <= universe:
        raise ValueError("unknown exclusion symbol")
    union = {
        symbol: (futures_exclusions or {}).get(symbol, frozenset())
        | (spot_exclusions or {}).get(symbol, frozenset())
        for symbol in universe
    }
    decisions = DailyDecisions(spot_bars, first_months, union)
    hold_decisions = HoldDecisions(spot_bars, first_months, union)
    directory.mkdir(parents=True, exist_ok=False)
    recorder = AttemptRecorder(directory)
    walk = run_walk_forward(decisions, futures_filters, futures_hourly, funding, record=recorder)
    # Exclusive boundary only: never requests a 2025 bar.
    end = month_bounds_ms("2025-01")[0]
    sensitivities = replay_sensitivities(
        decisions, futures_filters, futures_hourly, funding, walk.picks, end, record=recorder
    )
    fixed = replay_fixed_rules(
        decisions, futures_filters, futures_hourly, funding, walk.picks, end, record=recorder
    )
    prefix = uuid4().hex
    holds = {
        cost: replay_spot_recorded(
            directory,
            f"{prefix}-hold-cost{cost}",
            hold_decisions,
            spot_filters,
            spot_hourly,
            min(walk.picks),
            end,
            cost_multiple=cost,
        )
        for cost in (1, 2)
    }
    full_size = replay_full_size_hold_recorded(
        directory,
        f"{prefix}-full-size-hold",
        hold_hourly,
        first_months,
        spot_filters,
        min(walk.picks),
        end,
    )
    return build_experiment_report(
        walk,
        sensitivities,
        fixed,
        holds,
        spot_bars=spot_bars,
        first_months=first_months,
        futures_exclusions=futures_exclusions,
        spot_exclusions=spot_exclusions,
        full_size_hold=full_size,
    )
