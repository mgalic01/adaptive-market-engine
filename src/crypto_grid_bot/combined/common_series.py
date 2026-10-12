"""Comparable hourly observations selected by the approved economic policy.

No interpolation, native timestamp relabeling or historical execution. This series
is for cross-version comparisons; it never replaces the native intrabar risk
series. Adapter/source authenticity remains a reviewed registration obligation.
Owner decisions of 2026-10-11 (docs/V3_1_SOURCE_INVENTORY.md): an hour some
registered source has no bar for is skipped for every arm alike, and a baseline
that stopped under its own rules holds its stop equity, labelled frozen (since
2026-10-12 only a liquidation is such a stop: ``baseline_records.NATIVE_STOPS``).
"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .observation_policy import PolicyEvidence, validate_boundaries
from .report import EquityPoint

_HOUR = 3_600_000
# Source reference labelling a frozen baseline's held equity after its native stop;
# the stop's name follows the colon (owner decision 2026-10-11).
FROZEN_REF = "frozen_after_native_stop:"


@dataclass(frozen=True, slots=True)
class CommonSeries:
    policy_id: str
    adapter_pin: str
    points: tuple[EquityPoint, ...]
    net_return: Fraction
    max_drawdown: Fraction
    skipped_hours: tuple[int, ...] = ()
    frozen_hours: tuple[int, ...] = ()  # compared hours holding a frozen stop equity
    native_stop: str | None = None


def skipped_hours_valid(skipped_hours: object, start_ms: int, end_ms: int) -> bool:
    """Sorted unique hour stamps strictly inside the window, never its first hour or
    its last (whose close is the terminal mark); the one rule for every caller."""
    return (
        isinstance(skipped_hours, tuple)
        and all(
            type(hour) is int and not hour % _HOUR and start_ms < hour < end_ms - _HOUR
            for hour in skipped_hours
        )
        and list(skipped_hours) == sorted(set(skipped_hours))
    )


def _frozen_stop(point: EquityPoint) -> str | None:
    """The native stop named by a point's frozen label, if it has one."""
    stops = {
        ref.removeprefix(FROZEN_REF)
        for ref in point.source_refs
        if isinstance(ref, str) and ref.startswith(FROZEN_REF)
    }
    if len(stops) > 1 or "" in stops:
        raise ValueError("a frozen mark names exactly one native stop")
    return stops.pop() if stops else None


def common_hourly_series(
    points: tuple[EquityPoint, ...],
    policy: PolicyEvidence,
    *,
    start_ms: int,
    end_ms: int,
    skipped_hours: tuple[int, ...] = (),
) -> CommonSeries:
    """Require every scheduled hourly boundary, including before-cost opening equity.

    The schedule is every window hour except the registered skipped hours, which
    never include the window's first hour or its last (whose close is the terminal
    mark). A scheduled hour without its boundary refuses the series; a mark at a
    skipped hour stays native evidence only. Frozen points (labelled FROZEN_REF) must
    end the series with one stop's equity; they are compared, and reported as frozen.
    Fractions keep ratios independent of Decimal context. Nonpositive subsequent
    equity remains measurable evidence of exhaustion, including drawdown above 1.
    Every native point is validated, even when not selected for the common series.
    """
    if (
        type(start_ms) is not int
        or type(end_ms) is not int
        or not 0 <= start_ms < end_ms
        or start_ms % _HOUR
        or end_ms % _HOUR
        or not isinstance(points, tuple)
        or not points
        or any(
            not isinstance(point, EquityPoint)
            or not isinstance(point.equity, Decimal)
            or not point.equity.is_finite()
            for point in points
        )
        or points[0].timestamp_ms != start_ms
        or points[-1].timestamp_ms != end_ms
        or points[0].equity <= 0
    ):
        raise ValueError("finite identified observations at exact hourly window endpoints required")
    if not skipped_hours_valid(skipped_hours, start_ms, end_ms):
        raise ValueError("skipped hours must be sorted hours inside, never first or last")
    boundaries = validate_boundaries(policy, tuple((p.timestamp_ms, p.id) for p in points))
    skipped = frozenset(skipped_hours)
    scheduled = [boundary for time, boundary in boundaries.items() if time not in skipped]
    # Walk the schedule without allocating a caller-sized range of hours.
    expected = start_ms
    for boundary in scheduled:
        while expected in skipped:
            expected += _HOUR
        if boundary.timestamp_ms != expected:
            raise ValueError("every hourly economic boundary on the schedule is required")
        expected += _HOUR
    stops = tuple(_frozen_stop(point) for point in points)
    first_frozen = next((i for i, stop in enumerate(stops) if stop is not None), len(points))
    frozen = points[first_frozen:]
    if len(set(stops[first_frozen:])) > 1 or len({point.equity for point in frozen}) > 1:
        raise ValueError("frozen marks must end the series holding one stop's equity")
    indexed = {p.id: p for p in points}
    selected = tuple(indexed[boundary.selected_equity_id] for boundary in scheduled)
    frozen_ids = {point.id for point in frozen}
    peak = Fraction(selected[0].equity)
    drawdown = Fraction(0)
    for point in selected:
        equity = Fraction(point.equity)
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
    return CommonSeries(
        policy.policy_id,
        policy.adapter_pin,
        selected,
        Fraction(selected[-1].equity) / Fraction(selected[0].equity) - 1,
        drawdown,
        skipped_hours,
        tuple(point.timestamp_ms for point in selected if point.id in frozen_ids),
        stops[first_frozen] if frozen else None,
    )
