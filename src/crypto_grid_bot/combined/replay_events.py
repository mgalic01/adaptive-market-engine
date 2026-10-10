"""Finite settled-event replay, not a strategy simulator or experiment matrix.

Input order is authoritative. Validation occurs only on reaching each batch.
Failed settlement is not rolled back or retried: earlier cash flows may be booked.
"""

from dataclasses import dataclass

from crypto_grid_bot.combined.account import FillEvent, FundingEvent
from crypto_grid_bot.combined.engine import EngineSnapshot, PortfolioEngine, Quote
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.market_data.parsing import symbol_name


@dataclass(frozen=True, slots=True)
class SettledBatch:
    batch_id: str
    timestamp_ms: int
    quotes: tuple[tuple[str, Quote], ...]
    rules: tuple[tuple[str, VenueRules], ...]
    funding: tuple[FundingEvent, ...] = ()
    reductions: tuple[FillEvent, ...] = ()
    increases: tuple[tuple[str, FillEvent], ...] = ()
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchSnapshot:
    batch_id: str
    source_refs: tuple[str, ...]
    snapshot: EngineSnapshot


@dataclass(frozen=True, slots=True)
class ReplayFailure:
    batch_id: str
    index: int
    reason: str
    terminal_snapshot: EngineSnapshot | None
    terminal_unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    snapshots: tuple[BatchSnapshot, ...]
    duplicate_ids: tuple[str, ...]
    failure: ReplayFailure | None
    unprocessed_ids: tuple[str, ...]


def _validate(batch: SettledBatch, previous: int) -> None:
    if not isinstance(batch.batch_id, str) or not batch.batch_id.strip():
        raise ValueError("nonempty batch identity required")
    if type(batch.timestamp_ms) is not int or not previous <= batch.timestamp_ms < 1735689600000:
        raise ValueError("chronological pre-2025 timestamp required")
    if batch.timestamp_ms < 0:
        raise ValueError("nonnegative timestamp required")
    for rows, kind in ((batch.quotes, Quote), (batch.rules, VenueRules)):
        if not isinstance(rows, tuple):
            raise ValueError("immutable market records required")
        names = set()
        for pair in rows:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("market record pair required")
            name, value = pair
            if not isinstance(name, str):
                raise ValueError("market symbol must be a string")
            symbol_name(name)
            if name in names or not isinstance(value, kind):
                raise ValueError("duplicate or malformed market record")
            names.add(name)
    if (
        not isinstance(batch.source_refs, tuple)
        or not batch.source_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in batch.source_refs)
    ):
        raise ValueError("source references required")
    if not all(
        isinstance(events, tuple) for events in (batch.funding, batch.reductions, batch.increases)
    ):
        raise ValueError("immutable settled events required")
    if any(not isinstance(event, FundingEvent) for event in batch.funding) or any(
        not isinstance(event, FillEvent) for event in batch.reductions
    ):
        raise ValueError("invalid settled event type")
    for increase in batch.increases:
        if (
            not isinstance(increase, tuple)
            or len(increase) != 2
            or not isinstance(increase[0], str)
            or not increase[0]
            or not isinstance(increase[1], FillEvent)
        ):
            raise ValueError("admission identity and fill required")


def _identity(batch: object, index: int) -> str:
    """Label unavailable identities without inspecting unprocessed payloads."""
    if (
        isinstance(batch, SettledBatch)
        and isinstance(batch.batch_id, str)
        and batch.batch_id.strip()
    ):
        return batch.batch_id
    return f"<unavailable:{index}>"


def replay_events(engine: PortfolioEngine, batches: tuple[SettledBatch, ...]) -> ReplayResult:
    """Settle unique batches once, retaining failure evidence without automatic retry.

    Repeated IDs within this sequence are not additional observations. Engine
    settlement owns funding-before-reduction-before-increase ordering. Exceptions
    retain a terminal observation when possible, using existing engine quotes only.
    Source references are recorded, not fetched or verified. No completeness claim.
    """
    if not isinstance(batches, tuple):
        raise ValueError("finite immutable batch sequence required")
    snapshots: list[BatchSnapshot] = []
    duplicates: list[str] = []
    seen: dict[str, SettledBatch] = {}
    previous = -1
    for index, batch in enumerate(batches):
        attempted = False
        identity = _identity(batch, index)
        try:
            if not isinstance(batch, SettledBatch):
                raise ValueError("settled batch record required")
            if not isinstance(batch.batch_id, str) or not batch.batch_id.strip():
                raise ValueError("nonempty batch identity required")
            if batch.batch_id in seen:
                if seen[batch.batch_id] != batch:
                    raise ValueError("conflicting duplicate batch")
                duplicates.append(batch.batch_id)
                continue
            _validate(batch, previous)
            attempted = True
            state = engine.settle(
                batch.batch_id,
                batch.timestamp_ms,
                dict(batch.quotes),
                dict(batch.rules),
                funding=batch.funding,
                reductions=batch.reductions,
                increases=batch.increases,
            )
            snapshots.append(BatchSnapshot(batch.batch_id, batch.source_refs, state))
            seen[batch.batch_id] = batch
            previous = batch.timestamp_ms
            if (
                state.liquidation
                or not state.account.integrity_ok
                or any(
                    reason in state.reasons
                    for reason in ("execution_integrity_failure", "post_fill_risk_breach")
                )
            ):
                raise ValueError("settled snapshot reports engineering failure")
        except (ValueError, ArithmeticError, TypeError, AttributeError) as exc:
            terminal = None
            unavailable: str | None = "validation failed before settlement"
            if attempted:
                try:
                    terminal = engine.observe(batch.timestamp_ms, {}, dict(batch.rules))
                    unavailable = None
                except (ValueError, ArithmeticError, TypeError, AttributeError) as terminal_error:
                    unavailable = str(terminal_error)
            failure = ReplayFailure(identity, index, str(exc), terminal, unavailable)
            return ReplayResult(
                tuple(snapshots),
                tuple(duplicates),
                failure,
                tuple(
                    _identity(row, offset)
                    for offset, row in enumerate(batches[index + 1 :], start=index + 1)
                ),
            )
    return ReplayResult(tuple(snapshots), tuple(duplicates), None, ())
