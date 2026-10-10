"""The spec v2 §4 mode selector: which mode a pair may enter at an hourly decision.

``select_mode`` is a pure function of its arguments. It keeps no state and reads no clock: the
caller counts the consecutive RANGE decisions and remembers when the last trailing-stop exit
triggered. Entering is decided here. Staying (an uptrend position, a grid winding down) is not, and
it belongs to the engines (§4, "Entering versus staying").

``explain_mode`` reports why: the same decision with every Uptrend and Grid condition that does not
hold, as fixed codes. It is for the report only (spec v2 §8, "Reported, not gating: Behaviour"),
and nothing reads it back to decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from crypto_grid_bot.domain import MarketRegime
from crypto_grid_bot.strategy.perception import Snapshot, TrendState

GRID_RSI_LOW = Decimal(35)  # the 1h RSI(14) band for Grid, inclusive at both ends
GRID_RSI_HIGH = Decimal(65)
ADX_RANGE = Decimal(20)  # Grid needs the 1h ADX(14) strictly below this
UPTREND_RSI_MAX = Decimal(75)  # Uptrend needs the daily RSI(14) strictly below this
RANGE_DECISIONS = 4  # consecutive hourly RANGE decisions, the current one included
REENTRY_PAUSE_MS = 86_400_000  # 24 h after a trailing-stop exit triggers


class Mode(StrEnum):
    GRID = "grid"
    UPTREND = "uptrend"
    CASH = "cash"


def select_mode(
    snapshot: Snapshot,
    regime: MarketRegime,
    input_quality_ok: bool,
    range_decisions: int,
    now_ms: int,
    stopped_at_ms: int | None,
) -> Mode:
    """The mode a pair may enter at this decision (spec v2 §4).

    The checks run in this order, and the first to hold decides:

    1. An unavailable 4h or daily state is ``CASH``, whatever else holds.
    2. ``UPTREND``: daily and 4h states Up; the daily RSI and ATR available with the RSI below
       ``UPTREND_RSI_MAX``; ``input_quality_ok`` and a regime that is neither BEAR nor STRESS;
       and no pause, meaning ``stopped_at_ms`` is None or at least ``REENTRY_PAUSE_MS`` before
       ``now_ms``. The 1h inputs are not read.
    3. ``GRID``: this decision's regime is RANGE and ``range_decisions`` is at least
       ``RANGE_DECISIONS``; the 4h state Range or Unclear; the daily state Up, Range or Unclear;
       the 1h timeframe available, with its RSI from ``GRID_RSI_LOW`` to ``GRID_RSI_HIGH``
       inclusive, its ADX below ``ADX_RANGE`` and its width at most its median.
    4. Otherwise ``CASH``.

    ``range_decisions`` counts the consecutive hourly decisions, this one included, whose regime
    was RANGE. ``input_quality_ok`` is the classifier's ``RegimeAssessment.input_quality_ok``. A
    RANGE regime already implies it, so Grid does not check it separately.

    The function cannot see a halt. The caller forces ``CASH`` while the account is halted
    (spec v2 §4 and §7).
    """
    if TrendState.UNAVAILABLE in (snapshot.h4_state, snapshot.d1_state):
        return Mode.CASH
    if _uptrend(snapshot, regime, input_quality_ok, now_ms, stopped_at_ms):
        return Mode.UPTREND
    if _grid(snapshot, regime, range_decisions):
        return Mode.GRID
    return Mode.CASH


def _uptrend(
    snapshot: Snapshot,
    regime: MarketRegime,
    input_quality_ok: bool,
    now_ms: int,
    stopped_at_ms: int | None,
) -> bool:
    if snapshot.d1_rsi is None or snapshot.d1_atr is None:
        return False
    return (
        snapshot.d1_state is TrendState.UP
        and snapshot.h4_state is TrendState.UP
        and snapshot.d1_rsi < UPTREND_RSI_MAX
        and input_quality_ok
        and regime not in (MarketRegime.BEAR, MarketRegime.STRESS)
        and (stopped_at_ms is None or now_ms - stopped_at_ms >= REENTRY_PAUSE_MS)
    )


def _grid(snapshot: Snapshot, regime: MarketRegime, range_decisions: int) -> bool:
    if (
        not snapshot.h1_available
        or snapshot.h1_rsi is None
        or snapshot.h1_adx is None
        or snapshot.h1_width is None
        or snapshot.h1_width_median is None
    ):
        return False
    return (
        regime is MarketRegime.RANGE
        and range_decisions >= RANGE_DECISIONS
        and snapshot.h4_state in (TrendState.RANGE, TrendState.UNCLEAR)
        and snapshot.d1_state in (TrendState.UP, TrendState.RANGE, TrendState.UNCLEAR)
        and GRID_RSI_LOW <= snapshot.h1_rsi <= GRID_RSI_HIGH
        and snapshot.h1_adx < ADX_RANGE
        and snapshot.h1_width <= snapshot.h1_width_median
    )


# Why a decision went as it did (``explain_mode``): one code for each condition of section 4's
# Uptrend and Grid rows. The not-Up and not-Range codes are for an available state; an
# Unavailable 4h or daily state gives ``H4_OR_D1_UNAVAILABLE`` and never those, in both rows.
# A missing daily bar also leaves the daily RSI and ATR missing, so Uptrend then lists
# ``D1_RSI_OR_ATR_MISSING`` beside it.
H4_OR_D1_UNAVAILABLE = "h4_or_d1_unavailable"
D1_RSI_OR_ATR_MISSING = "d1_rsi_or_atr_missing"
D1_NOT_UP = "d1_not_up"
H4_NOT_UP = "h4_not_up"
D1_RSI_OVERBOUGHT = "d1_rsi_overbought"  # the daily RSI at or above UPTREND_RSI_MAX
INPUT_QUALITY = "input_quality"
REGIME_BEAR_OR_STRESS = "regime_bear_or_stress"
REENTRY_PAUSE = "reentry_pause"
H1_UNAVAILABLE = "h1_unavailable"  # the 1h timeframe, or any of its four inputs, missing
REGIME_NOT_RANGE = "regime_not_range"
RANGE_DECISIONS_BELOW_4 = "range_decisions_below_4"
H4_NOT_RANGE_OR_UNCLEAR = "h4_not_range_or_unclear"
D1_NOT_UP_RANGE_OR_UNCLEAR = "d1_not_up_range_or_unclear"
H1_RSI_OUTSIDE_35_65 = "h1_rsi_outside_35_65"
H1_ADX_20_OR_ABOVE = "h1_adx_20_or_above"
H1_WIDTH_ABOVE_MEDIAN = "h1_width_above_median"
# Each row's codes in the order its conditions are checked, the order a list of them keeps.
UPTREND_CODES = (
    H4_OR_D1_UNAVAILABLE,
    D1_RSI_OR_ATR_MISSING,
    D1_NOT_UP,
    H4_NOT_UP,
    D1_RSI_OVERBOUGHT,
    INPUT_QUALITY,
    REGIME_BEAR_OR_STRESS,
    REENTRY_PAUSE,
)
GRID_CODES = (
    H4_OR_D1_UNAVAILABLE,
    H1_UNAVAILABLE,
    REGIME_NOT_RANGE,
    RANGE_DECISIONS_BELOW_4,
    H4_NOT_RANGE_OR_UNCLEAR,
    D1_NOT_UP_RANGE_OR_UNCLEAR,
    H1_RSI_OUTSIDE_35_65,
    H1_ADX_20_OR_ABOVE,
    H1_WIDTH_ABOVE_MEDIAN,
)


@dataclass(frozen=True, slots=True)
class ModeExplanation:
    """A decision and why: the mode, and every condition of each row that does not hold, as codes
    in the row's order. A row's failures are empty exactly when the row holds."""

    mode: Mode
    uptrend_failures: tuple[str, ...]
    grid_failures: tuple[str, ...]


def explain_mode(
    snapshot: Snapshot,
    regime: MarketRegime,
    input_quality_ok: bool,
    range_decisions: int,
    now_ms: int,
    stopped_at_ms: int | None,
) -> ModeExplanation:
    """``select_mode``'s decision on the same arguments, with the reasons for it, for the report
    only: the decision itself is ``select_mode``'s, and nothing reads this back.

    Each condition is checked on its own, so a decision can list several. A threshold is checked
    only on a value that is present; a missing value is ``D1_RSI_OR_ATR_MISSING`` or
    ``H1_UNAVAILABLE``. A regime that is not RANGE has restarted the count, so
    ``REGIME_NOT_RANGE`` always comes with ``RANGE_DECISIONS_BELOW_4``, and the second alone
    means RANGE for fewer than ``RANGE_DECISIONS`` consecutive decisions.
    """
    unavailable = TrendState.UNAVAILABLE in (snapshot.h4_state, snapshot.d1_state)
    uptrend = _uptrend_failures(
        snapshot, regime, input_quality_ok, now_ms, stopped_at_ms, unavailable
    )
    grid = _grid_failures(snapshot, regime, range_decisions, unavailable)
    if not uptrend:
        mode = Mode.UPTREND
    elif not grid:
        mode = Mode.GRID
    else:
        mode = Mode.CASH
    return ModeExplanation(mode, uptrend, grid)


def _uptrend_failures(
    snapshot: Snapshot,
    regime: MarketRegime,
    input_quality_ok: bool,
    now_ms: int,
    stopped_at_ms: int | None,
    unavailable: bool,
) -> tuple[str, ...]:
    rsi = snapshot.d1_rsi
    checks = (
        (H4_OR_D1_UNAVAILABLE, unavailable),
        (D1_RSI_OR_ATR_MISSING, rsi is None or snapshot.d1_atr is None),
        (D1_NOT_UP, snapshot.d1_state not in (TrendState.UP, TrendState.UNAVAILABLE)),
        (H4_NOT_UP, snapshot.h4_state not in (TrendState.UP, TrendState.UNAVAILABLE)),
        (D1_RSI_OVERBOUGHT, rsi is not None and rsi >= UPTREND_RSI_MAX),
        (INPUT_QUALITY, not input_quality_ok),
        (REGIME_BEAR_OR_STRESS, regime in (MarketRegime.BEAR, MarketRegime.STRESS)),
        (REENTRY_PAUSE, stopped_at_ms is not None and now_ms - stopped_at_ms < REENTRY_PAUSE_MS),
    )
    return tuple(code for code, failed in checks if failed)


def _grid_failures(
    snapshot: Snapshot, regime: MarketRegime, range_decisions: int, unavailable: bool
) -> tuple[str, ...]:
    rsi, adx = snapshot.h1_rsi, snapshot.h1_adx
    width, median = snapshot.h1_width, snapshot.h1_width_median
    missing = any(value is None for value in (rsi, adx, width, median))
    h4_allowed = (TrendState.RANGE, TrendState.UNCLEAR, TrendState.UNAVAILABLE)
    d1_allowed = (TrendState.UP, *h4_allowed)
    checks = (
        (H4_OR_D1_UNAVAILABLE, unavailable),
        (H1_UNAVAILABLE, not snapshot.h1_available or missing),
        (REGIME_NOT_RANGE, regime is not MarketRegime.RANGE),
        (RANGE_DECISIONS_BELOW_4, range_decisions < RANGE_DECISIONS),
        (H4_NOT_RANGE_OR_UNCLEAR, snapshot.h4_state not in h4_allowed),
        (D1_NOT_UP_RANGE_OR_UNCLEAR, snapshot.d1_state not in d1_allowed),
        (H1_RSI_OUTSIDE_35_65, rsi is not None and not GRID_RSI_LOW <= rsi <= GRID_RSI_HIGH),
        (H1_ADX_20_OR_ABOVE, adx is not None and adx >= ADX_RANGE),
        (H1_WIDTH_ABOVE_MEDIAN, width is not None and median is not None and width > median),
    )
    return tuple(code for code, failed in checks if failed)
