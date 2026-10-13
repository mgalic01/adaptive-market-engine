"""Map retained engine settlement marks to the approved economic boundary.

No OHLC simulation or source authentication. The caller supplies the genuine
hourly interval identity and references; reviewed replay must establish those.
Every mark is retained, including equal values and zero-duration changes.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction

from .engine import SettlementObservation
from .observation_policy import Boundary
from .report import CapitalObservation, EquityPoint


@dataclass(frozen=True, slots=True)
class BoundaryRecords:
    interval_start_ms: int
    interval_end_ms: int
    boundary: Boundary
    equity: tuple[EquityPoint, ...]
    capital: tuple[CapitalObservation, ...]
    trace: tuple[SettlementObservation, ...]


def _decimal(value: Fraction) -> Decimal:
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + 4 * len(str(value.denominator)) + 10
        return Decimal(value.numerator) / Decimal(value.denominator)


def emit_boundary(
    batch_id: str,
    trace: tuple[SettlementObservation, ...],
    *,
    role: str,
    interval_start_ms: int,
    interval_end_ms: int,
    source_refs: tuple[str, ...],
) -> BoundaryRecords:
    """A terminal boundary cannot contain next-window funding or new entries.

    Opening return starts before costs; utilization uses the final settled capital.
    Intermediate snapshots are never dropped to simplify sampling. Failed prefixes
    remain engine evidence but cannot be promoted to a completed boundary here.
    """
    if (
        not isinstance(batch_id, str)
        or not batch_id.strip()
        or role not in ("opening", "settled", "terminal")
        or type(interval_start_ms) is not int
        or type(interval_end_ms) is not int
        or not 0 <= interval_start_ms < interval_end_ms <= 1_735_689_600_000
        or interval_start_ms % 3_600_000
        or interval_end_ms - interval_start_ms != 3_600_000
        or not isinstance(trace, tuple)
        or len(trace) < 2
        or not all(isinstance(row, SettlementObservation) for row in trace)
        or not isinstance(source_refs, tuple)
        or not source_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in source_refs)
    ):
        raise ValueError("identified completed pre-reserved hourly settlement required")
    timestamp = interval_end_ms if role == "terminal" else interval_start_ms
    ranks = {"before": 0, "funding": 1, "reduction": 2, "increase": 3, "settled": 4}
    if (
        trace[0].phase != "before"
        or trace[-1].phase != "settled"
        or trace[0].event_id != batch_id
        or trace[-1].event_id != batch_id
        or any(row.snapshot.timestamp_ms != timestamp or row.phase not in ranks for row in trace)
        or any(row.phase in ("before", "settled") for row in trace[1:-1])
        or any(ranks[a.phase] > ranks[b.phase] for a, b in zip(trace, trace[1:], strict=False))
        or (role == "terminal" and any(row.phase in ("funding", "increase") for row in trace))
    ):
        raise ValueError("settlement phases or interval boundary mismatch")
    opening = trace[0].snapshot.account
    final = trace[-1].snapshot
    # Current marks only: a persisting close reason from an earlier stale hour does
    # not make a later fresh boundary stale.
    if any(row.snapshot.stale for row in trace):
        raise ValueError("stale held marks cannot form a sourced boundary")
    if role == "terminal" and (
        final.close_required
        or final.unresolved_execution
        or final.liquidation
        or not final.account.integrity_ok
    ):
        raise ValueError("unresolved terminal obligations or integrity failure")
    if role == "opening" and (
        opening.positions or opening.fees or opening.funding or opening.realized_pnl
    ):
        raise ValueError("opening sample must precede first execution costs")
    points = []
    capitals = []
    for index, row in enumerate(trace):
        account = row.snapshot.account
        identity = f"{batch_id}:observation:{index}"
        refs = (*source_refs, f"event:{row.event_id}")
        points.append(EquityPoint(timestamp, account.equity, identity, refs))
        spot = sum(
            (
                Fraction(p.quantity) * Fraction(p.mark)
                for p in account.positions
                if p.venue == "spot"
            ),
            Fraction(0),
        )
        collateral = sum(
            (Fraction(p.collateral) for p in account.positions if p.venue == "futures"), Fraction(0)
        )
        capitals.append(
            CapitalObservation(
                timestamp,
                account.equity,
                _decimal(spot),
                _decimal(collateral),
                f"{batch_id}:capital:{index}",
                role if index == len(trace) - 1 else row.phase,
                identity,
                refs,
            )
        )
    boundary = Boundary(
        timestamp,
        role,
        tuple(f"{batch_id}:observation:{index}" for index in range(len(trace))),
        f"{batch_id}:observation:{0 if role == 'opening' else len(trace) - 1}",
        f"{batch_id}:capital:{len(trace) - 1}",
        source_refs,
        interval_start_ms,
        interval_end_ms,
    )
    return BoundaryRecords(
        interval_start_ms, interval_end_ms, boundary, tuple(points), tuple(capitals), trace
    )
