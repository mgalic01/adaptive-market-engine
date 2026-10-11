"""Comparison evidence for frozen baselines on the approved common-hourly schedule.

Owner decisions of 2026-10-11 (docs/V3_1_SOURCE_INVENTORY.md) name the matched
baselines and accept two native timing differences, disclosed here. A frozen
baseline's trading logic, outputs and timestamps are never changed: every native
mark stays in its labelled diagnostics, and the comparison report uses only the
marks a baseline records exactly at UTC hour boundaries (proposal point 5). A
missing hourly mark leaves that boundary absent, so the comparison is incomplete,
never a pass. Outputs are never scaled.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .observation_policy import POLICY_ID, Boundary, PolicyEvidence
from .report import (
    CapitalObservation,
    Contribution,
    EquityPoint,
    Report,
    UtilizationInterval,
    analyze,
)

HOUR = 3_600_000
DAY = 24 * HOUR


@dataclass(frozen=True, slots=True)
class NativeMark:
    """One mark exactly as the frozen baseline recorded it, with its capital split."""

    timestamp_ms: int
    kind: str
    equity: Decimal
    spot_value: Decimal
    futures_collateral: Decimal


@dataclass(frozen=True, slots=True)
class BaselineEvidence:
    arm: str
    native_label: str
    native: tuple[NativeMark, ...]
    report: Report
    status: str | None  # None: the frozen run completed; otherwise its native stop
    liquidations: int
    accounting_residual: Decimal
    accounting_explained: bool
    wallet_quantity_exact: bool | None
    disclosures: tuple[str, ...]


def comparison_report(
    arm: str,
    marks: Sequence[NativeMark],
    contributions: Sequence[Contribution],
    *,
    initial: Decimal,
    start_ms: int,
    end_ms: int,
    source_refs: tuple[str, ...],
    adapter_pin: str,
    producer_issues: tuple[str, ...] = (),
) -> Report:
    """Analyze the hour-stamped marks under the approved settlement policy.

    Each boundary lists every hour-stamped mark at its time in native order; the
    opening selects the first (before costs), later boundaries the last. Marks
    between hours remain native diagnostics only. The terminal boundary is the
    window end. Contributions must come from the baseline's own accounting.
    """
    if (
        not isinstance(arm, str)
        or not arm.strip()
        or type(start_ms) is not int
        or type(end_ms) is not int
        or start_ms % DAY
        or end_ms % DAY
        or not 0 <= start_ms < end_ms
    ):
        raise ValueError("identified UTC-day comparison window required")
    points: list[EquityPoint] = []
    groups: dict[int, list[str]] = {}
    capital: dict[str, NativeMark] = {}
    for index, mark in enumerate(marks):
        if mark.timestamp_ms % HOUR or not start_ms <= mark.timestamp_ms <= end_ms:
            continue
        identity = f"{arm}:{index}:{mark.kind}"
        points.append(
            EquityPoint(
                mark.timestamp_ms, mark.equity, identity, (*source_refs, f"native:{mark.kind}")
            )
        )
        groups.setdefault(mark.timestamp_ms, []).append(identity)
        capital[identity] = mark
    boundaries: list[Boundary] = []
    capitals: list[CapitalObservation] = []
    for hour in range(start_ms, end_ms + HOUR, HOUR):
        ids = tuple(groups.get(hour, ()))
        if not ids:
            continue  # absent: the comparison stays incomplete
        role = "opening" if hour == start_ms else "terminal" if hour == end_ms else "settled"
        last = capital[ids[-1]]
        capital_id = f"{arm}:capital:{hour}"
        capitals.append(
            CapitalObservation(
                hour,
                last.equity,
                last.spot_value,
                last.futures_collateral,
                capital_id,
                role,
                ids[-1],
                source_refs,
            )
        )
        start = hour - HOUR if role == "terminal" else hour
        boundaries.append(
            Boundary(
                hour,
                role,
                ids,
                ids[0] if role == "opening" else ids[-1],
                capital_id,
                source_refs,
                start,
                start + HOUR,
            )
        )
    by_id = {point.id: point for point in points}
    daily = tuple(
        by_id[boundary.selected_equity_id]
        for boundary in boundaries
        if boundary.timestamp_ms % DAY == 0
    )
    utilization = tuple(
        UtilizationInterval(
            boundary.timestamp_ms,
            following.timestamp_ms,
            observation.spot_value,
            observation.futures_collateral,
            observation.equity,
            f"{arm}:utilization:{boundary.timestamp_ms}",
            source_refs,
            observation.id,
        )
        for boundary, following, observation in zip(
            boundaries, boundaries[1:], capitals, strict=False
        )
    )
    policy = PolicyEvidence(POLICY_ID, adapter_pin, tuple(boundaries), "native")
    return analyze(
        initial,
        tuple(points),
        tuple(contributions),
        (),
        (),
        source_refs,
        metrics_start_ms=start_ms,
        daily_samples=daily,
        utilization=utilization,
        capital_observations=tuple(capitals),
        policy_evidence=policy,
        producer_issues=producer_issues,
    )
