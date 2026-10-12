"""Pure regime qualification. Admission still checks funding, cash and venue filters.

No result here is permission to submit an order; the shared portfolio reservation
must succeed using the same event snapshot. Protective reductions bypass routing.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import Context, Decimal, Inexact, InvalidOperation, Overflow, getcontext

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.models import Assessment
from crypto_grid_bot.strategy.perception import TrendState


@dataclass(frozen=True, slots=True)
class RoutingContext:
    spot_executable: bool | None = None
    flow_allowed: bool = False
    spot_trend: bool = True
    futures_trend: bool = True
    spot_grid: bool = True
    futures_long_only: bool = False
    continuation: bool = True
    short_qualification: bool = True

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "spot_executable" and value is None:
                continue
            if type(value) is not bool:
                raise ValueError("routing context requires exact Boolean flags")


@dataclass(frozen=True, slots=True)
class Qualification:
    symbol: str
    decision_ms: int
    allowed: bool
    owner: str | None
    side: int
    risk_multiplier: Decimal
    reasons: tuple[str, ...]
    schema: str = "combined-v1"


_FLOW_BLOCK = Decimal("0.40")  # below it, or unavailable, the gate blocks
_FLOW_OPEN = Decimal("0.45")  # at or above it the gate opens


class FlowGate:
    """Hysteresis on externally verified 15 completed one-minute flow bars."""

    def __init__(self) -> None:
        self.allowed = False

    def update(self, ratio: Decimal | None) -> bool:
        if not isinstance(ratio, Decimal) or not ratio.is_finite() or not _FLOW_BLOCK <= ratio <= 1:
            self.allowed = False
        elif ratio >= _FLOW_OPEN:
            self.allowed = True
        return self.allowed


def completed_flow(bars: Sequence[Kline], decision_ms: int) -> Decimal | None:
    """Volume-weighted taker buy share from the fifteen due completed minutes.

    Future values are never inspected; gaps, duplicates and zero volume are
    unavailable. This ratio must pass the hysteresis gate before a grid increase.
    """
    if type(decision_ms) is not int or decision_ms < 0:
        raise ValueError("nonnegative integer decision timestamp required")
    minute = 60_000
    end = decision_ms // minute * minute
    start = end - 15 * minute
    selected = [bar for bar in bars if start <= bar.open_ms < end]
    if [bar.open_ms for bar in selected] != list(range(start, end, minute)):
        return None
    for bar in selected:
        if (
            any(
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not 0 <= value <= Decimal("1e36")
                for value in (bar.volume, bar.taker_buy_base)
            )
            or bar.taker_buy_base > bar.volume
        ):
            return None
    total = sum((bar.volume for bar in selected), Decimal(0))
    if total == 0:
        return None
    return sum((bar.taker_buy_base for bar in selected), Decimal(0)) / total


_MINUTE = 60_000
_FLOW_BOUND = Decimal("1e36")  # completed_flow's bound on a minute's volumes
# Rolling sums stay exact or raise: an inexact step falls back to completed_flow.
_EXACT = Context(prec=60, traps=[Inexact, InvalidOperation, Overflow])


def _flow_bar_valid(bar: Kline) -> bool:
    """A minute ``completed_flow`` accepts: finite volumes, 0 <= taker <= volume <= 1e36."""
    volume, taker = bar.volume, bar.taker_buy_base
    return (
        isinstance(volume, Decimal)
        and isinstance(taker, Decimal)
        and volume.is_finite()
        and taker.is_finite()
        and 0 <= taker <= volume <= _FLOW_BOUND
    )


class RollingFlow:
    """``completed_flow`` at each successive minute from ``first_ms``, in O(1) per minute.

    The window is the fifteen completed minutes before the current one, read from
    ``bars`` (keyed by opening time). Exact sums of its volumes and taker-buy volumes are
    kept by adding the minute that enters and removing the one that leaves; a missing or
    invalid minute keeps the window unavailable until it has left. The share is the
    exact taker sum over the exact volume sum, divided in the current context, whenever
    both sums' coefficients fit that context's precision: a sum's exponent is at most the
    lowest of its terms' and its zero start's, so ``completed_flow``'s own running sums
    of nonnegative terms are then exact, and the value is the same. Otherwise, or after
    an inexact rolling step, ``completed_flow`` itself reads the window.
    """

    def __init__(self, bars: Mapping[int, Kline], first_ms: int) -> None:
        self._bars = bars
        self._next = first_ms
        self._window: deque[Kline | None] = deque()
        self._missing = 0  # missing or invalid minutes in the window
        self._volume = Decimal(0)
        self._taker = Decimal(0)
        self._exact = True
        for opened in range(first_ms - 15 * _MINUTE, first_ms, _MINUTE):
            self._enter(bars.get(opened))

    def _enter(self, bar: Kline | None) -> None:
        if bar is None or not _flow_bar_valid(bar):
            self._window.append(None)
            self._missing += 1
            return
        self._window.append(bar)
        if self._exact:
            try:
                self._volume = _EXACT.add(self._volume, bar.volume)
                self._taker = _EXACT.add(self._taker, bar.taker_buy_base)
            except (Inexact, InvalidOperation, Overflow):
                self._exact = False

    def _leave(self) -> None:
        bar = self._window.popleft()
        if bar is None:
            self._missing -= 1
        elif self._exact:
            try:
                self._volume = _EXACT.subtract(self._volume, bar.volume)
                self._taker = _EXACT.subtract(self._taker, bar.taker_buy_base)
            except (Inexact, InvalidOperation, Overflow):
                self._exact = False

    def _resum(self) -> None:
        """Recompute the sums from the window; they are exact again if no step rounds."""
        volume = taker = Decimal(0)
        try:
            for bar in self._window:
                if bar is not None:
                    volume = _EXACT.add(volume, bar.volume)
                    taker = _EXACT.add(taker, bar.taker_buy_base)
        except (Inexact, InvalidOperation, Overflow):
            return
        self._volume, self._taker, self._exact = volume, taker, True

    def _share(self, stamp: int) -> Decimal | None:
        if self._missing:
            return None
        if not self._exact:
            self._resum()
        if not self._exact:
            return completed_flow(tuple(bar for bar in self._window if bar is not None), stamp)
        volume, taker = self._volume, self._taker
        if not volume:
            return None
        precision = getcontext().prec
        if volume.adjusted() - int(volume.as_tuple().exponent) < precision and (
            not taker or taker.adjusted() - int(taker.as_tuple().exponent) < precision
        ):
            return taker / volume
        return completed_flow(tuple(bar for bar in self._window if bar is not None), stamp)

    def next(self) -> Decimal | None:
        """The share at the current minute; then the window moves one minute on."""
        stamp = self._next
        share = self._share(stamp)
        self._leave()
        self._enter(self._bars.get(stamp))
        self._next = stamp + _MINUTE
        return share


class MinuteFlowGate:
    """The flow gate fed every minute from ``first_ms`` on, in order, one at a time.

    Each minute's value is ``completed_flow`` of the fifteen completed minutes before
    it, read from ``bars`` (keyed by opening time), and passes ``FlowGate``'s
    hysteresis, which starts blocked. A minute without its fifteen bars is unavailable,
    so it blocks.
    """

    def __init__(self, bars: Mapping[int, Kline], first_ms: int) -> None:
        self._flow = RollingFlow(bars, first_ms) if bars else None
        self._gate = FlowGate()
        self._next = first_ms

    @property
    def allowed(self) -> bool:
        """The gate after the last minute fed."""
        return self._gate.allowed

    def advance(self, through_ms: int) -> bool:
        """Feed every minute up to and including ``through_ms``; True when the gate was
        blocked after any of them."""
        if self._next > through_ms:
            return False
        if self._flow is None:  # no bars: every minute is unavailable
            self._gate.update(None)
            self._next = through_ms // _MINUTE * _MINUTE + _MINUTE
            return True
        blocked = False
        while self._next <= through_ms:
            blocked = not self._gate.update(self._flow.next()) or blocked
            self._next += _MINUTE
        return blocked


def qualify(assessment: Assessment, context: RoutingContext) -> Qualification:
    """Return an explainable candidate; preserve independent price-side blockers."""
    reasons = list(assessment.reasons)
    if not assessment.available:
        reasons.append("assessment_unavailable")
    ratio, extension = assessment.volatility_ratio, assessment.extension
    if not isinstance(ratio, Decimal) or not ratio.is_finite() or ratio <= 0:
        reasons.append("volatility_unavailable")
    elif ratio >= 3:
        reasons.append("volatility_stress")
    owner: str | None = None
    side = 0
    multiplier = Decimal(1)
    up = assessment.daily == assessment.four_hour == TrendState.UP
    down = assessment.four_hour == TrendState.DOWN and (
        assessment.daily == TrendState.DOWN
        or (not context.short_qualification and assessment.daily == TrendState.UNCLEAR)
    )
    ranged = assessment.daily == assessment.four_hour == TrendState.RANGE
    if up or down:
        side = 1 if up else -1
        if assessment.structure not in {"breakout", "continuation", "pullback"}:
            reasons.append("structure_unqualified")
        if not isinstance(extension, Decimal) or not extension.is_finite() or extension < 0:
            reasons.append("extension_unavailable")
        elif extension > 3:
            reasons.append("extended_entry")
        elif extension > 2:
            multiplier = Decimal("0.5")
        if not context.continuation:
            # The restored frozen veto read the daily RSI(14) (mode_selector UPTREND_RSI_MAX).
            rsi = assessment.daily_rsi
            if not isinstance(rsi, Decimal) or not rsi.is_finite() or not 0 <= rsi <= 100:
                reasons.append("rsi_unavailable")
            elif (up and rsi >= 75) or (down and rsi <= 25):
                reasons.append("legacy_rsi_veto")
        if down:
            if context.futures_trend and not context.futures_long_only:
                owner = "futures_trend"
            else:
                reasons.append("short_component_disabled")
        elif context.spot_trend:
            if context.spot_executable is True:
                owner = "spot_trend"
            elif context.spot_executable is None:
                reasons.append("spot_executability_unknown")
            elif context.futures_trend:
                owner = "futures_trend"
            else:
                reasons.append("spot_unexecutable")
        elif context.futures_trend:
            owner = "futures_trend"
        else:
            reasons.append("trend_components_disabled")
    elif ranged:
        side = 1
        if not context.spot_grid:
            reasons.append("grid_component_disabled")
        else:
            owner = "spot_grid"
        if not context.flow_allowed:
            reasons.append("flow_blocked")
        if context.spot_executable is not True:
            reasons.append("spot_unexecutable")
    else:
        reasons.append("conflicting_direction")
    return Qualification(
        assessment.symbol,
        assessment.decision_ms,
        not reasons and owner is not None,
        owner,
        side,
        multiplier,
        tuple(dict.fromkeys(reasons)),
    )
