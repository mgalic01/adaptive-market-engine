from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.combined.boundary_adapter import emit_boundary
from crypto_grid_bot.combined.engine import PortfolioEngine


def test_opening_samples_before_costs_and_capital_after_settlement():
    engine = PortfolioEngine(D(100))
    engine.settle("opening", 0, {}, {})
    records = emit_boundary(
        "opening",
        engine.settlement_observations("opening"),
        role="opening",
        interval_start_ms=0,
        interval_end_ms=3_600_000,
        source_refs=("synthetic-interval",),
    )
    assert records.boundary.selected_equity_id == records.equity[0].id
    assert records.boundary.capital_id == records.capital[-1].id
    assert records.boundary.observation_ids == tuple(point.id for point in records.equity)
    assert len(records.equity) == len(records.capital) == 2


def test_terminal_requires_actual_interval_end_identity():
    engine = PortfolioEngine(D(100))
    engine.settle("terminal", 3_600_000, {}, {})
    trace = engine.settlement_observations("terminal")
    records = emit_boundary(
        "terminal",
        trace,
        role="terminal",
        interval_start_ms=0,
        interval_end_ms=3_600_000,
        source_refs=("synthetic-interval",),
    )
    assert records.boundary.selected_equity_id == records.equity[-1].id
    with pytest.raises(ValueError):
        emit_boundary(
            "terminal",
            trace,
            role="terminal",
            interval_start_ms=3_600_000,
            interval_end_ms=7_200_000,
            source_refs=("synthetic-interval",),
        )


def test_missing_or_failed_settlement_has_no_complete_boundary():
    with pytest.raises(ValueError):
        emit_boundary(
            "missing",
            (),
            role="settled",
            interval_start_ms=0,
            interval_end_ms=3_600_000,
            source_refs=("source",),
        )


@pytest.mark.parametrize("phase", ["funding", "increase"])
def test_terminal_rejects_next_window_settlements(phase):
    engine = PortfolioEngine(D(100))
    engine.settle("terminal", 3_600_000, {}, {})
    trace = engine.settlement_observations("terminal")
    extra = replace(trace[-1], phase=phase, event_id="next-window-event")
    with pytest.raises(ValueError):
        emit_boundary(
            "terminal",
            (trace[0], extra, trace[-1]),
            role="terminal",
            interval_start_ms=0,
            interval_end_ms=3_600_000,
            source_refs=("source",),
        )


def test_terminal_cannot_promote_unfinished_protective_close():
    engine = PortfolioEngine(D(100))
    engine.settle("terminal", 3_600_000, {}, {})
    trace = engine.settlement_observations("terminal")
    unfinished = replace(
        trace[-1], snapshot=replace(trace[-1].snapshot, close_required=("BTCUSDT",))
    )
    with pytest.raises(ValueError, match="obligations"):
        emit_boundary(
            "terminal",
            (trace[0], unfinished),
            role="terminal",
            interval_start_ms=0,
            interval_end_ms=3_600_000,
            source_refs=("source",),
        )


def test_terminal_cannot_promote_unresolved_canceled_remainder():
    engine = PortfolioEngine(D(100))
    engine.settle("terminal", 3_600_000, {}, {})
    trace = engine.settlement_observations("terminal")
    unfinished = replace(
        trace[-1], snapshot=replace(trace[-1].snapshot, unresolved_execution=("canceled-order",))
    )
    with pytest.raises(ValueError, match="obligations"):
        emit_boundary(
            "terminal",
            (trace[0], unfinished),
            role="terminal",
            interval_start_ms=0,
            interval_end_ms=3_600_000,
            source_refs=("source",),
        )
