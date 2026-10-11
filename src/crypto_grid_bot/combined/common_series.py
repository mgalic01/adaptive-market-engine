"""Comparable hourly observations selected by the approved economic policy.

No interpolation, native timestamp relabeling or historical execution. This series
is for cross-version comparisons; it never replaces the native intrabar risk
series. Adapter/source authenticity remains a reviewed registration obligation.
"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .observation_policy import PolicyEvidence, validate_boundaries
from .report import EquityPoint

_HOUR = 3_600_000


@dataclass(frozen=True, slots=True)
class CommonSeries:
    policy_id: str
    adapter_pin: str
    points: tuple[EquityPoint, ...]
    net_return: Fraction
    max_drawdown: Fraction


def common_hourly_series(
    points: tuple[EquityPoint, ...],
    policy: PolicyEvidence,
    *,
    start_ms: int,
    end_ms: int,
) -> CommonSeries:
    """Require every real hourly boundary, including before-cost opening equity.

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
    boundaries = validate_boundaries(policy, tuple((p.timestamp_ms, p.id) for p in points))
    # Compare counts and consecutive keys without allocating a caller-sized range.
    times = tuple(boundaries)
    if len(times) != (end_ms - start_ms) // _HOUR + 1 or any(
        later - earlier != _HOUR for earlier, later in zip(times, times[1:], strict=False)
    ):
        raise ValueError("every hourly economic boundary is required")
    indexed = {p.id: p for p in points}
    selected = tuple(indexed[boundary.selected_equity_id] for boundary in boundaries.values())
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
    )
