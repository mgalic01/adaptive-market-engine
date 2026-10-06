"""The spec v2 §4 mode selector: which mode a pair may enter at an hourly decision.

``select_mode`` is a pure function of its arguments. It keeps no state and reads no clock: the
caller counts the consecutive RANGE decisions and remembers when the last trailing-stop exit
triggered. Entering is decided here. Staying (an uptrend position, a grid winding down) is not, and
it belongs to the engines (§4, "Entering versus staying").
"""

from __future__ import annotations

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
    3. ``GRID``: ``range_decisions`` at least ``RANGE_DECISIONS``; the 4h state Range or
       Unclear; the daily state Up, Range or Unclear; the 1h timeframe available, with its RSI
       from ``GRID_RSI_LOW`` to ``GRID_RSI_HIGH`` inclusive, its ADX below ``ADX_RANGE`` and its
       width at most its median.
    4. Otherwise ``CASH``.

    ``range_decisions`` counts the consecutive hourly decisions, this one included, whose regime
    was RANGE. ``input_quality_ok`` is the classifier's ``RegimeAssessment.input_quality_ok``.
    """
    if TrendState.UNAVAILABLE in (snapshot.h4_state, snapshot.d1_state):
        return Mode.CASH
    if _uptrend(snapshot, regime, input_quality_ok, now_ms, stopped_at_ms):
        return Mode.UPTREND
    if _grid(snapshot, range_decisions):
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


def _grid(snapshot: Snapshot, range_decisions: int) -> bool:
    if (
        not snapshot.h1_available
        or snapshot.h1_rsi is None
        or snapshot.h1_adx is None
        or snapshot.h1_width is None
        or snapshot.h1_width_median is None
    ):
        return False
    return (
        range_decisions >= RANGE_DECISIONS
        and snapshot.h4_state in (TrendState.RANGE, TrendState.UNCLEAR)
        and snapshot.d1_state in (TrendState.UP, TrendState.RANGE, TrendState.UNCLEAR)
        and GRID_RSI_LOW <= snapshot.h1_rsi <= GRID_RSI_HIGH
        and snapshot.h1_adx < ADX_RANGE
        and snapshot.h1_width <= snapshot.h1_width_median
    )
