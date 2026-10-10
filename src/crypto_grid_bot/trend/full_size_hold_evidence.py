"""Durable attempts for the reported-only supplied-input hold diagnostic."""

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.trend.evidence_writer import AttemptRecorder, _write_rows
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.full_size_hold import (
    FullSizeHoldExecutionError,
    FullSizeHoldResult,
    replay_full_size_hold,
)


def hold_rows(result: FullSizeHoldResult) -> Iterator[tuple[str, Any]]:
    yield (
        "full_size_hold",
        {
            "start_ms": result.start_ms,
            "end_ms_exclusive": result.end_ms_exclusive,
            "scheduled_ms": result.scheduled_ms,
            "attempt_times": result.purchase_times,
            "budgets": result.budgets,
            "reason": result.reason,
            "missing_symbols": result.missing_symbols,
            "initial": result.account.initial,
            "cash": result.account.cash,
            "holdings": result.account.holdings,
            "cost_multiple": result.account.cost_multiple,
            "masked_held_hours": result.masked_held_hours,
            "max_drawdown": result.max_drawdown,
        },
    )
    for kind, values in (
        ("spot_fill", result.account.fills),
        ("spot_audit", result.audits),
        ("equity", result.equity_path),
        ("sample", result.samples),
    ):
        for value in values:
            yield kind, value


def write_full_size_hold(
    directory: Path, run_id: str, result: FullSizeHoldResult
) -> dict[str, Any]:
    return _write_rows(directory, run_id, hold_rows(result))


def replay_full_size_hold_recorded(
    directory: Path,
    run_id: str,
    hourly: Mapping[str, Sequence[Kline]],
    first_months: Mapping[str, str],
    filters: Mapping[str, OrderFilters],
    start_ms: int,
    end_ms_exclusive: int,
) -> FullSizeHoldResult:
    """Record before replay; errors retain partial state and never trigger retry.

    A finished journal entry is not a usable diagnostic or an acceptance verdict:
    inspect the recorded outcome. Disk failure/interruption leaves a pending start.
    Historical provenance, registration and authorization remain upstream.
    """
    recorder = AttemptRecorder(directory)
    identity = {
        "phase": "full_size_hold",
        "start_ms": start_ms,
        "end_ms_exclusive": end_ms_exclusive,
        "cost_multiple": 1,
    }
    recorder.journal.record(run_id, "started", identity)
    try:
        result = replay_full_size_hold(hourly, first_months, filters, start_ms, end_ms_exclusive)
    except Exception as exc:
        evidence = (
            write_full_size_hold(recorder.journal.directory, run_id, exc.result)
            if isinstance(exc, FullSizeHoldExecutionError)
            else None
        )
        recorder.journal.record(
            run_id,
            "finished",
            {**identity, "error": f"{type(exc).__name__}: {exc}", "evidence": evidence},
        )
        raise
    evidence = write_full_size_hold(recorder.journal.directory, run_id, result)
    recorder.journal.record(run_id, "finished", {**identity, "error": None, "evidence": evidence})
    return result
