"""Comparison evidence for frozen baselines on the approved common-hourly schedule.

Owner decisions of 2026-10-11 (docs/V3_1_SOURCE_INVENTORY.md) name the matched
baselines and accept two native timing differences, disclosed here. A frozen
baseline's trading logic, outputs and timestamps are never changed: every native
mark stays in its labelled diagnostics, and the comparison report uses only the
marks a baseline records exactly at UTC hour boundaries (proposal point 5). A
missing hourly mark leaves that boundary absent, so the comparison is incomplete,
never a pass, unless the registration skips that hour for every arm. A baseline
liquidated under its own rules is a finished result: its stop equity is held to the
window end, each such mark labelled frozen. Only that real market event counts (owner,
2026-10-12): any other stop leaves the comparison incomplete. Outputs are never scaled.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .common_series import FROZEN_REF
from .observation_policy import POLICY_ID, Boundary, PolicyEvidence
from .report import (
    CapitalObservation,
    Contribution,
    EquityPoint,
    Report,
    UtilizationInterval,
    analyze,
    skipped_hours_disclosures,
    span_text,
)

HOUR = 3_600_000
DAY = 24 * HOUR
_RESERVED = 1_735_689_600_000  # 2025-01-01T00:00Z; data from here on stays sealed
# Stops that end a frozen baseline under its own rules, a finished result: only a real
# market event, a liquidation (owner, 2026-10-11, narrowed 2026-10-12). Only frozen V3
# stops this way: the minute replays (V0-V2 grids, D) and the hold run to the window end
# (a grid halt restarts by itself; D never halts). V3's no_tradable_position and
# leverage_not_restored come from masked or untradable coins (terminal invalid-run
# outcomes in the frozen ``trend.execution``); they, an engine or parity failure, a
# missing input, V3's unavailable exclusion close and a selector without a pick are not
# native stops: the cell stays incomplete and keeps its stop reason.
NATIVE_STOPS = frozenset({"liquidation"})


def refuse_sealed(stamps: Iterable[object], what: str) -> None:
    """Data at or after the reserved boundary stays sealed: refuse it, never ignore it."""
    if any(type(stamp) is not int or stamp >= _RESERVED for stamp in stamps):
        raise ValueError(f"{what}: input at or after the reserved boundary is refused")


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
    status: str | None  # None: the frozen run completed; otherwise why it stopped
    liquidations: int
    accounting_residual: Decimal
    accounting_explained: bool
    wallet_quantity_exact: bool | None
    disclosures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeDiagnostics:
    """A frozen baseline's own marks under its native version label; never compared.

    Return and lifetime maximum drawdown over every native mark in the baseline's own
    timing (intrabar and off-hour marks included), from the registered opening capital.
    Diagnostics only: acceptance compares the common hourly series. None when the
    baseline recorded no native mark.
    """

    arm: str
    native_label: str
    mark_count: int
    first_ms: int | None
    last_ms: int | None
    net_return: Fraction | None
    max_drawdown: Fraction | None
    status: str | None  # None: the frozen run completed; otherwise why it ended


def native_diagnostics(evidence: BaselineEvidence) -> NativeDiagnostics:
    """The diagnostics of a baseline's native marks, labelled with its native version."""
    marks, opening = evidence.native, Fraction(evidence.report.initial_equity)
    if not marks:
        return NativeDiagnostics(
            evidence.arm, evidence.native_label, 0, None, None, None, None, evidence.status
        )
    peak, worst = opening, Fraction(0)
    for mark in marks:
        equity = Fraction(mark.equity)
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return NativeDiagnostics(
        evidence.arm,
        evidence.native_label,
        len(marks),
        marks[0].timestamp_ms,
        marks[-1].timestamp_ms,
        Fraction(marks[-1].equity) / opening - 1,
        worst,
        evidence.status,
    )


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
    native_stop: str | None = None,
    skipped_hours: tuple[int, ...] = (),
    disclosures: tuple[str, ...] = (),
    capital_label: str | None = None,
) -> Report:
    """Analyze the hour-stamped marks under the approved settlement policy.

    Each boundary lists every hour-stamped mark at its time in native order; the
    opening selects the first (before costs), later boundaries the last. Marks
    between hours remain native diagnostics only. The terminal boundary is the
    window end. Contributions must come from the baseline's own accounting.
    With a native stop the last mark is the account at the stop: every later hour
    to the window end holds its equity, labelled frozen, with nothing deployed.
    ``skipped_hours`` are the registered window's: a daily return may span them.
    The report discloses the adapter's ``disclosures``, the skipped hours and the
    frozen span; ``capital_label`` names the registered capital scenario.
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
    if native_stop is not None and native_stop not in NATIVE_STOPS:
        raise ValueError("unknown native stop")
    if not isinstance(disclosures, tuple):
        raise ValueError("disclosures must be a tuple of nonempty strings")
    notes = [*disclosures, *skipped_hours_disclosures(skipped_hours)]
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
    if native_stop is not None and marks:
        stop, label = marks[-1], f"{FROZEN_REF}{native_stop}"
        after_stop = max(start_ms, stop.timestamp_ms // HOUR * HOUR + HOUR)
        frozen = range(after_stop, end_ms + HOUR, HOUR)
        for hour in frozen:
            identity = f"{arm}:frozen:{hour}"
            points.append(EquityPoint(hour, stop.equity, identity, (*source_refs, label)))
            groups.setdefault(hour, []).append(identity)
            capital[identity] = NativeMark(hour, "frozen", stop.equity, Decimal(0), Decimal(0))
        if frozen:
            notes.append(f"{label}: {span_text('hours', frozen)}")
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
        skipped_hours=skipped_hours,
        disclosures=tuple(notes),
        capital_label=capital_label,
    )
