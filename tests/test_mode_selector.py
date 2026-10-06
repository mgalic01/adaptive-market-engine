"""The mode selector (spec v2 §4): one assertion per boundary of the Uptrend, Grid and Cash rows.

Two base snapshots each satisfy exactly one row, and every test changes one thing with
``dataclasses.replace`` and checks which side of the boundary it lands on. Uptrend needs the 4h
state Up and Grid needs it Range or Unclear, so no snapshot satisfies both rows and the order of
the checks cannot change a result; the Cash row is whatever neither row accepts.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from decimal import Decimal as D

import pytest

from crypto_grid_bot.domain import MarketRegime
from crypto_grid_bot.strategy.mode_selector import (
    ADX_RANGE,
    GRID_RSI_HIGH,
    GRID_RSI_LOW,
    RANGE_DECISIONS,
    REENTRY_PAUSE_MS,
    UPTREND_RSI_MAX,
    Mode,
    select_mode,
)
from crypto_grid_bot.strategy.perception import Snapshot, TrendState

DAY = 86_400_000
NOW = 10 * DAY

# The 1h inputs of the Grid base: RSI inside 35..65, ADX under 20, width under its median.
GRID_BASE = Snapshot(
    h1_available=True,
    h1_rsi=D(50),
    h1_adx=D(15),
    h1_width=D("0.02"),
    h1_width_median=D("0.03"),
    h4_state=TrendState.RANGE,
    d1_state=TrendState.RANGE,
    d1_rsi=D(50),
    d1_close=D(100),
    d1_atr=D(2),
    d1_open_ms=NOW - DAY,
    d1_points=(),
    d1_index=None,
)

# Daily and 4h Up with a daily RSI under 75. The 1h inputs are absent, and they must not matter.
UPTREND_BASE = dataclasses.replace(
    GRID_BASE,
    h1_available=False,
    h1_rsi=None,
    h1_adx=None,
    h1_width=None,
    h1_width_median=None,
    h4_state=TrendState.UP,
    d1_state=TrendState.UP,
    d1_rsi=D(60),
)

# The same Uptrend snapshot with 1h inputs present that no Grid row would accept.
UPTREND_WITH_1H = dataclasses.replace(
    UPTREND_BASE,
    h1_available=True,
    h1_rsi=D(99),
    h1_adx=D(99),
    h1_width=D(9),
    h1_width_median=D(1),
)

NO_1H = {
    "h1_available": False,
    "h1_rsi": None,
    "h1_adx": None,
    "h1_width": None,
    "h1_width_median": None,
}


def grid(
    snapshot: Snapshot = GRID_BASE,
    *,
    regime: MarketRegime = MarketRegime.RANGE,
    input_quality_ok: bool = True,
    range_decisions: int = 4,
    stopped_at_ms: int | None = None,
) -> Mode:
    return select_mode(snapshot, regime, input_quality_ok, range_decisions, NOW, stopped_at_ms)


def uptrend(
    snapshot: Snapshot = UPTREND_BASE,
    *,
    regime: MarketRegime = MarketRegime.BULL,
    input_quality_ok: bool = True,
    range_decisions: int = 0,
    stopped_at_ms: int | None = None,
) -> Mode:
    return select_mode(snapshot, regime, input_quality_ok, range_decisions, NOW, stopped_at_ms)


def test_the_base_snapshots_each_satisfy_one_row() -> None:
    assert grid() is Mode.GRID
    assert uptrend() is Mode.UPTREND


def test_the_thresholds_are_pinned() -> None:
    assert D(35) == GRID_RSI_LOW
    assert D(65) == GRID_RSI_HIGH
    assert D(20) == ADX_RANGE
    assert D(75) == UPTREND_RSI_MAX
    assert RANGE_DECISIONS == 4
    assert REENTRY_PAUSE_MS == 86_400_000


def test_the_modes_have_stable_values() -> None:
    assert [m.value for m in Mode] == ["grid", "uptrend", "cash"]


# Grid


@pytest.mark.parametrize(
    ("rsi", "expected"),
    [
        (D("34.99"), Mode.CASH),
        (D(35), Mode.GRID),
        (D(65), Mode.GRID),
        (D("65.01"), Mode.CASH),
    ],
)
def test_grid_1h_rsi_is_inclusive_at_both_bounds(rsi: D, expected: Mode) -> None:
    assert grid(dataclasses.replace(GRID_BASE, h1_rsi=rsi)) is expected


@pytest.mark.parametrize(("adx", "expected"), [(D("19.99"), Mode.GRID), (D(20), Mode.CASH)])
def test_grid_1h_adx_must_be_below_20(adx: D, expected: Mode) -> None:
    assert grid(dataclasses.replace(GRID_BASE, h1_adx=adx)) is expected


@pytest.mark.parametrize(
    ("width", "expected"),
    [
        (D("0.0299"), Mode.GRID),
        (D("0.03"), Mode.GRID),  # equal to the median
        (D("0.0301"), Mode.CASH),
    ],
)
def test_grid_1h_width_may_equal_its_median(width: D, expected: Mode) -> None:
    assert grid(dataclasses.replace(GRID_BASE, h1_width=width)) is expected


@pytest.mark.parametrize(("count", "expected"), [(3, Mode.CASH), (4, Mode.GRID), (5, Mode.GRID)])
def test_grid_needs_four_consecutive_range_decisions(count: int, expected: Mode) -> None:
    assert grid(range_decisions=count) is expected


@pytest.mark.parametrize(
    ("regime", "expected"),
    [
        (MarketRegime.RANGE, Mode.GRID),
        (MarketRegime.BULL, Mode.CASH),
        (MarketRegime.BEAR, Mode.CASH),
        (MarketRegime.TRANSITION, Mode.CASH),
        (MarketRegime.STRESS, Mode.CASH),
    ],
)
def test_grid_needs_this_decisions_regime_to_be_range(regime: MarketRegime, expected: Mode) -> None:
    assert grid(regime=regime, range_decisions=4) is expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (TrendState.RANGE, Mode.GRID),
        (TrendState.UNCLEAR, Mode.GRID),
        (TrendState.UP, Mode.CASH),
        (TrendState.DOWN, Mode.CASH),
    ],
)
def test_grid_4h_state_is_range_or_unclear(state: TrendState, expected: Mode) -> None:
    assert grid(dataclasses.replace(GRID_BASE, h4_state=state)) is expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (TrendState.UP, Mode.GRID),
        (TrendState.RANGE, Mode.GRID),
        (TrendState.UNCLEAR, Mode.GRID),
        (TrendState.DOWN, Mode.CASH),
    ],
)
def test_grid_daily_state_is_up_range_or_unclear(state: TrendState, expected: Mode) -> None:
    assert grid(dataclasses.replace(GRID_BASE, d1_state=state)) is expected


def test_grid_needs_the_1h_timeframe_available() -> None:
    assert grid(dataclasses.replace(GRID_BASE, h1_available=False)) is Mode.CASH


@pytest.mark.parametrize("field", ["h1_rsi", "h1_adx", "h1_width", "h1_width_median"])
def test_grid_with_a_missing_1h_input_is_cash(field: str) -> None:
    assert grid(dataclasses.replace(GRID_BASE, **{field: None})) is Mode.CASH


def test_the_reentry_pause_does_not_touch_grid() -> None:
    assert grid(stopped_at_ms=NOW) is Mode.GRID


# Uptrend


@pytest.mark.parametrize(
    ("rsi", "expected"),
    [(D("74.99"), Mode.UPTREND), (D(75), Mode.CASH)],
)
def test_uptrend_daily_rsi_must_be_below_75(rsi: D, expected: Mode) -> None:
    assert uptrend(dataclasses.replace(UPTREND_BASE, d1_rsi=rsi)) is expected


@pytest.mark.parametrize(
    ("regime", "expected"),
    [
        (MarketRegime.BULL, Mode.UPTREND),
        (MarketRegime.TRANSITION, Mode.UPTREND),
        (MarketRegime.RANGE, Mode.UPTREND),
        (MarketRegime.BEAR, Mode.CASH),
        (MarketRegime.STRESS, Mode.CASH),
    ],
)
def test_uptrend_is_blocked_by_bear_and_stress_only(regime: MarketRegime, expected: Mode) -> None:
    assert uptrend(regime=regime) is expected


@pytest.mark.parametrize("regime", [MarketRegime.BULL, MarketRegime.TRANSITION])
def test_uptrend_needs_the_regime_inputs_to_be_sound(regime: MarketRegime) -> None:
    assert uptrend(regime=regime, input_quality_ok=False) is Mode.CASH


def test_uptrend_needs_the_daily_atr() -> None:
    assert uptrend(dataclasses.replace(UPTREND_BASE, d1_atr=None)) is Mode.CASH


def test_uptrend_needs_the_daily_rsi() -> None:
    assert uptrend(dataclasses.replace(UPTREND_BASE, d1_rsi=None)) is Mode.CASH


@pytest.mark.parametrize("state", [TrendState.RANGE, TrendState.UNCLEAR, TrendState.DOWN])
def test_uptrend_needs_the_daily_state_up(state: TrendState) -> None:
    assert uptrend(dataclasses.replace(UPTREND_BASE, d1_state=state)) is Mode.CASH


@pytest.mark.parametrize("state", [TrendState.RANGE, TrendState.UNCLEAR, TrendState.DOWN])
def test_uptrend_needs_the_4h_state_up(state: TrendState) -> None:
    assert uptrend(dataclasses.replace(UPTREND_BASE, h4_state=state)) is Mode.CASH


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (0, Mode.CASH),
        (86_399_999, Mode.CASH),
        (86_400_000, Mode.UPTREND),  # exactly 24 h later it may enter
        (86_400_001, Mode.UPTREND),
    ],
)
def test_uptrend_waits_24_hours_after_a_stop_out(elapsed: int, expected: Mode) -> None:
    assert uptrend(stopped_at_ms=NOW - elapsed) is expected


def test_uptrend_with_no_stop_out_is_not_paused() -> None:
    assert uptrend(stopped_at_ms=None) is Mode.UPTREND


def test_uptrend_does_not_read_the_1h_inputs() -> None:
    # The 1h inputs are the Grid row's alone (spec v2 §4, Cash): hostile values change nothing.
    assert uptrend(UPTREND_WITH_1H) is Mode.UPTREND


# Cash


@pytest.mark.parametrize("field", ["h4_state", "d1_state"])
@pytest.mark.parametrize(
    ("base", "call"),
    [(GRID_BASE, grid), (UPTREND_BASE, uptrend)],
    ids=["grid-base", "uptrend-base"],
)
def test_an_unavailable_4h_or_daily_state_is_cash(
    base: Snapshot, call: Callable[[Snapshot], Mode], field: str
) -> None:
    assert call(dataclasses.replace(base, **{field: TrendState.UNAVAILABLE})) is Mode.CASH


def test_a_missing_1h_timeframe_blocks_grid_but_not_uptrend() -> None:
    # Both snapshots start with the 1h inputs present, so removing them is a real change.
    assert grid(dataclasses.replace(GRID_BASE, h1_available=True)) is Mode.GRID
    assert grid(dataclasses.replace(GRID_BASE, **NO_1H)) is Mode.CASH
    assert uptrend(UPTREND_WITH_1H) is Mode.UPTREND
    assert uptrend(dataclasses.replace(UPTREND_WITH_1H, **NO_1H)) is Mode.UPTREND
