"""The mode selector (spec v2 §4): one assertion per boundary of the Uptrend, Grid and Cash rows.

Two base snapshots each satisfy exactly one row, and every test changes one thing with
``dataclasses.replace`` and checks which side of the boundary it lands on. Uptrend needs the 4h
state Up and Grid needs it Range or Unclear, so no snapshot satisfies both rows and the order of
the checks cannot change a result; the Cash row is whatever neither row accepts.

``explain_mode``, the reporting-only account of a decision, is checked last: each boundary names
its own code, and seeded random inputs show it agrees with ``select_mode`` and both rows.
"""

from __future__ import annotations

import dataclasses
import random
from collections import Counter
from collections.abc import Callable
from decimal import Decimal as D
from typing import Any

import pytest

from crypto_grid_bot.domain import MarketRegime
from crypto_grid_bot.strategy import mode_selector as ms
from crypto_grid_bot.strategy.mode_selector import (
    ADX_RANGE,
    GRID_RSI_HIGH,
    GRID_RSI_LOW,
    RANGE_DECISIONS,
    REENTRY_PAUSE_MS,
    UPTREND_RSI_MAX,
    Mode,
    explain_mode,
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


# The explanation (reporting only)


def explain(
    snapshot: Snapshot,
    *,
    regime: MarketRegime,
    input_quality_ok: bool = True,
    range_decisions: int,
    stopped_at_ms: int | None = None,
) -> ms.ModeExplanation:
    return explain_mode(snapshot, regime, input_quality_ok, range_decisions, NOW, stopped_at_ms)


def test_the_failure_codes_are_pinned_in_section_4_order() -> None:
    assert ms.UPTREND_CODES == (
        "h4_or_d1_unavailable",
        "d1_rsi_or_atr_missing",
        "d1_not_up",
        "h4_not_up",
        "d1_rsi_overbought",
        "input_quality",
        "regime_bear_or_stress",
        "reentry_pause",
    )
    assert ms.GRID_CODES == (
        "h4_or_d1_unavailable",
        "h1_unavailable",
        "regime_not_range",
        "range_decisions_below_4",
        "h4_not_range_or_unclear",
        "d1_not_up_range_or_unclear",
        "h1_rsi_outside_35_65",
        "h1_adx_20_or_above",
        "h1_width_above_median",
    )


def test_the_base_snapshots_explain_their_rows() -> None:
    up = explain(UPTREND_BASE, regime=MarketRegime.BULL, range_decisions=0)
    assert (up.mode, up.uptrend_failures) == (Mode.UPTREND, ())
    # The Grid row fails on every condition the Uptrend base leaves out, each named.
    assert up.grid_failures == (
        ms.H1_UNAVAILABLE,
        ms.REGIME_NOT_RANGE,
        ms.RANGE_DECISIONS_BELOW_4,
        ms.H4_NOT_RANGE_OR_UNCLEAR,
    )
    grid_base = explain(GRID_BASE, regime=MarketRegime.RANGE, range_decisions=4)
    assert (grid_base.mode, grid_base.grid_failures) == (Mode.GRID, ())
    assert grid_base.uptrend_failures == (ms.D1_NOT_UP, ms.H4_NOT_UP)


ARGUMENTS = ("regime", "input_quality_ok", "range_decisions", "stopped_at_ms")


def split(changes: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A test case's changes as the snapshot's fields and ``explain``'s arguments."""
    fields = {k: v for k, v in changes.items() if k not in ARGUMENTS}
    return fields, {k: v for k, v in changes.items() if k in ARGUMENTS}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"h4_state": TrendState.UNAVAILABLE}, ms.H4_OR_D1_UNAVAILABLE),
        ({"d1_state": TrendState.UNAVAILABLE}, ms.H4_OR_D1_UNAVAILABLE),
        ({"d1_rsi": None}, ms.D1_RSI_OR_ATR_MISSING),
        ({"d1_atr": None}, ms.D1_RSI_OR_ATR_MISSING),
        ({"d1_state": TrendState.RANGE}, ms.D1_NOT_UP),
        ({"h4_state": TrendState.DOWN}, ms.H4_NOT_UP),
        ({"d1_rsi": UPTREND_RSI_MAX}, ms.D1_RSI_OVERBOUGHT),
        ({"input_quality_ok": False}, ms.INPUT_QUALITY),
        ({"regime": MarketRegime.BEAR}, ms.REGIME_BEAR_OR_STRESS),
        ({"regime": MarketRegime.STRESS}, ms.REGIME_BEAR_OR_STRESS),
        ({"stopped_at_ms": NOW - REENTRY_PAUSE_MS + 1}, ms.REENTRY_PAUSE),
    ],
)
def test_each_uptrend_boundary_names_its_code(changes: dict[str, Any], expected: str) -> None:
    fields, arguments = split(changes)
    explained = explain(
        dataclasses.replace(UPTREND_BASE, **fields),
        **({"regime": MarketRegime.BULL, "range_decisions": 0} | arguments),
    )
    assert explained.mode is Mode.CASH
    assert explained.uptrend_failures == (expected,)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"h4_state": TrendState.UNAVAILABLE}, ms.H4_OR_D1_UNAVAILABLE),
        ({"d1_state": TrendState.UNAVAILABLE}, ms.H4_OR_D1_UNAVAILABLE),
        ({"h1_available": False}, ms.H1_UNAVAILABLE),
        ({"h1_rsi": None}, ms.H1_UNAVAILABLE),
        ({"h1_width_median": None}, ms.H1_UNAVAILABLE),
        ({"regime": MarketRegime.BULL}, ms.REGIME_NOT_RANGE),
        ({"range_decisions": 3}, ms.RANGE_DECISIONS_BELOW_4),
        ({"h4_state": TrendState.UP}, ms.H4_NOT_RANGE_OR_UNCLEAR),
        ({"d1_state": TrendState.DOWN}, ms.D1_NOT_UP_RANGE_OR_UNCLEAR),
        ({"h1_rsi": D("34.99")}, ms.H1_RSI_OUTSIDE_35_65),
        ({"h1_rsi": D("65.01")}, ms.H1_RSI_OUTSIDE_35_65),
        ({"h1_adx": ADX_RANGE}, ms.H1_ADX_20_OR_ABOVE),
        ({"h1_width": D("0.0301")}, ms.H1_WIDTH_ABOVE_MEDIAN),
    ],
)
def test_each_grid_boundary_names_its_code(changes: dict[str, Any], expected: str) -> None:
    fields, arguments = split(changes)
    explained = explain(
        dataclasses.replace(GRID_BASE, **fields),
        **({"regime": MarketRegime.RANGE, "range_decisions": 4} | arguments),
    )
    assert explained.mode is Mode.CASH
    assert explained.grid_failures == (expected,)


def test_every_failing_condition_is_listed_in_order() -> None:
    # Each condition is checked on its own: an overbought daily RSI, a STRESS regime and a stop
    # within 24 hours are three reasons, not the first of them.
    snapshot = dataclasses.replace(UPTREND_BASE, d1_rsi=D(80))
    explained = explain(snapshot, regime=MarketRegime.STRESS, range_decisions=0, stopped_at_ms=NOW)
    assert explained.uptrend_failures == (
        ms.D1_RSI_OVERBOUGHT,
        ms.REGIME_BEAR_OR_STRESS,
        ms.REENTRY_PAUSE,
    )
    # A regime that is not RANGE has restarted the count, so Grid names both.
    assert explained.grid_failures[1:3] == (ms.REGIME_NOT_RANGE, ms.RANGE_DECISIONS_BELOW_4)


def test_an_unavailable_state_is_its_own_code_alone() -> None:
    # An Unavailable state is not also "not Up": the not-Up codes are for an available state.
    snapshot = dataclasses.replace(UPTREND_BASE, h4_state=TrendState.UNAVAILABLE)
    explained = explain(snapshot, regime=MarketRegime.BULL, range_decisions=0)
    assert explained.uptrend_failures == (ms.H4_OR_D1_UNAVAILABLE,)
    assert ms.H4_OR_D1_UNAVAILABLE in explained.grid_failures
    assert ms.H4_NOT_RANGE_OR_UNCLEAR not in explained.grid_failures


# Seeded random inputs: each field from a pool of boundaries, None and Unavailable.
POOLS: dict[str, tuple[Any, ...]] = {
    "h1_available": (True, False),
    "h1_rsi": (None, D(0), D("34.99"), D(35), D(50), D(65), D("65.01"), D(100)),
    "h1_adx": (None, D(0), D("19.99"), D(20), D("20.01"), D(45)),
    "h1_width": (None, D("0.02"), D("0.0299"), D("0.03"), D("0.0301")),
    "h1_width_median": (None, D("0.03")),
    "h4_state": tuple(TrendState),
    "d1_state": tuple(TrendState),
    "d1_rsi": (None, D(0), D(60), D("74.99"), D(75), D("75.01"), D(100)),
    "d1_atr": (None, D(0), D(2)),
}
ARGUMENT_POOLS: tuple[tuple[Any, ...], ...] = (
    tuple(MarketRegime),
    (True, False),
    (0, 1, 3, 4, 5, 100),
    (
        None,
        NOW + 1,
        NOW,
        NOW - REENTRY_PAUSE_MS + 1,
        NOW - REENTRY_PAUSE_MS,
        NOW - REENTRY_PAUSE_MS - 1,
        NOW - 10 * DAY,
    ),
)
# Bases that satisfy Uptrend, Grid and Grid on an Unclear 4h state, with their arguments.
BASES: tuple[tuple[Snapshot, tuple[Any, ...]], ...] = (
    (UPTREND_BASE, (MarketRegime.BULL, True, 0, None)),
    (GRID_BASE, (MarketRegime.RANGE, True, 4, None)),
    (
        dataclasses.replace(GRID_BASE, h4_state=TrendState.UNCLEAR),
        (MarketRegime.RANGE, True, 5, NOW - DAY),
    ),
)
SEEDED_INPUTS = 6000


def random_inputs(rng: random.Random) -> tuple[Snapshot, MarketRegime, bool, int, int | None]:
    """A base, with each field and argument replaced by a draw from its pool a third of the time,
    so that every mode, and every code as the one condition failing, occurs."""
    base, arguments = rng.choice(BASES)
    fields = {name: rng.choice(pool) for name, pool in POOLS.items() if rng.random() < 1 / 3}
    regime, quality, count, stopped = (
        rng.choice(pool) if rng.random() < 1 / 3 else kept
        for pool, kept in zip(ARGUMENT_POOLS, arguments, strict=True)
    )
    return dataclasses.replace(base, **fields), regime, quality, count, stopped


def test_explain_mode_agrees_with_select_mode_and_both_rows() -> None:
    rng = random.Random(20261007)
    modes: Counter[Mode] = Counter()
    sole: Counter[str] = Counter()
    for _ in range(SEEDED_INPUTS):
        snapshot, regime, quality, count, stopped = random_inputs(rng)
        explained = explain_mode(snapshot, regime, quality, count, NOW, stopped)
        assert explained.mode is select_mode(snapshot, regime, quality, count, NOW, stopped)
        uptrend_holds = ms._uptrend(snapshot, regime, quality, NOW, stopped)
        assert (not explained.uptrend_failures) is uptrend_holds
        assert (not explained.grid_failures) is ms._grid(snapshot, regime, count)
        # Codes from the fixed lists, in their order, each at most once.
        for failures, codes in (
            (explained.uptrend_failures, ms.UPTREND_CODES),
            (explained.grid_failures, ms.GRID_CODES),
        ):
            assert failures == tuple(code for code in codes if code in failures)
            if len(failures) == 1:
                sole[failures[0]] += 1
        modes[explained.mode] += 1
    # The draws reach every mode, and every code as the one condition that failed.
    assert set(modes) == set(Mode)
    assert set(sole) == set(ms.UPTREND_CODES) | set(ms.GRID_CODES)


def test_the_explanation_is_frozen() -> None:
    explained = explain(UPTREND_BASE, regime=MarketRegime.BULL, range_decisions=0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        explained.mode = Mode.CASH  # type: ignore[misc]
