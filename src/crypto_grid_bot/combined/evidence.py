"""Immutable, deterministic entry-funnel evidence; not an execution authorization.

The caller persists the serialized journal through the reviewed replay writer.
This component performs no file IO and cannot overwrite prior saved evidence.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal

from crypto_grid_bot.combined.risk import Intent
from crypto_grid_bot.market_data.parsing import symbol_name

PHASES = ("detected", "qualified", "risk_approved", "executable_size", "submitted", "filled")
# Why a decision has no executable size: refused at qualification, refused by risk
# admission, or an unavailable assessment with no signal.
SIZE_UNAVAILABLE = ("unqualified", "risk_refused", "no_signal")


def _refs(source_refs: object) -> None:
    if (
        not isinstance(source_refs, tuple)
        or not source_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in source_refs)
    ):
        raise ValueError("nonempty immutable source references required")


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    event_id: str
    opportunity_id: str
    timestamp_ms: int
    symbol: str
    phase: str
    accepted: bool
    reasons: tuple[str, ...]
    details: tuple[tuple[str, str], ...]
    source_refs: tuple[str, ...]
    schema: str = "combined-v1"

    def __post_init__(self) -> None:
        symbol_name(self.symbol)
        if (
            not isinstance(self.event_id, str)
            or not self.event_id
            or not isinstance(self.opportunity_id, str)
            or not self.opportunity_id
            or type(self.timestamp_ms) is not int
            or self.timestamp_ms < 0
            or self.phase not in PHASES
            or type(self.accepted) is not bool
            or self.schema != "combined-v1"
        ):
            raise ValueError("invalid decision event")
        _refs(self.source_refs)
        if (
            not isinstance(self.reasons, tuple)
            or any(not isinstance(r, str) or not r for r in self.reasons)
            or (not self.accepted and not self.reasons)
        ):
            raise ValueError("refusal requires immutable reasons")
        if not isinstance(self.details, tuple) or any(
            not isinstance(p, tuple)
            or len(p) != 2
            or not all(isinstance(v, str) for v in p)
            or not p[0]
            for p in self.details
        ):
            raise ValueError("immutable string details required")
        if len({p[0] for p in self.details}) != len(self.details):
            raise ValueError("duplicate detail key")


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One entry decision's disposition and the context it was judged in.

    Accepted and refused decisions alike carry both venues' costs (None without that
    venue's inputs), the futures funding estimate, the executable size or why there is
    none, the symbol's existing holdings and reservations, and its correlation group
    with that group's gross held and reserved notional, this symbol's included, all
    before the decision. ``phase`` is the last funnel phase recorded: the refusing one
    unless accepted. An unavailable assessment with no signal is one record per
    contiguous episode of a symbol, ``first_ms`` to ``last_ms``, in its first hour's
    context; a bundle keeps identical refusals in consecutive hours the same way, while
    the funnel journal keeps every hour. Evidence only: nothing reads it back into a
    decision.
    """

    record_id: str
    opportunity_id: str
    assessment_id: str
    symbol: str
    first_ms: int
    last_ms: int
    accepted: bool
    phase: str
    reasons: tuple[str, ...]
    owner: str | None
    side: int
    spot_fee_rate: Decimal | None
    spot_slippage_rate: Decimal | None
    spot_round_trip_cost_rate: Decimal | None
    futures_fee_rate: Decimal | None
    futures_slippage_rate: Decimal | None
    futures_round_trip_cost_rate: Decimal | None
    funding_rate: Decimal | None
    funding_published_ms: int | None
    funding_interval_ms: int | None
    executable_quantity: Decimal | None
    size_unavailable: str | None
    held_quantity: Decimal
    held_notional: Decimal
    reserved_quantity: Decimal
    reserved_notional: Decimal
    correlation_group: str
    group_gross_exposure: Decimal
    source_refs: tuple[str, ...]
    schema: str = "combined-v1"

    def __post_init__(self) -> None:
        symbol_name(self.symbol)
        _refs(self.source_refs)
        if (
            any(
                not isinstance(text, str) or not text
                for text in (
                    self.record_id,
                    self.opportunity_id,
                    self.assessment_id,
                    self.correlation_group,
                )
            )
            or type(self.first_ms) is not int
            or type(self.last_ms) is not int
            or not 0 <= self.first_ms <= self.last_ms
            or type(self.accepted) is not bool
            or self.phase not in PHASES[:5]
            or type(self.side) is not int
            or self.side not in (-1, 0, 1)
            or self.schema != "combined-v1"
        ):
            raise ValueError("invalid decision record")
        if (
            not isinstance(self.reasons, tuple)
            or any(not isinstance(r, str) or not r for r in self.reasons)
            or self.accepted != (not self.reasons)
            or self.accepted != (self.phase == "submitted")
            or (self.executable_quantity is None) == (self.size_unavailable is None)
            or self.accepted != (self.executable_quantity is not None)
            or (self.size_unavailable is not None and self.size_unavailable not in SIZE_UNAVAILABLE)
        ):
            raise ValueError("a refusal needs reasons and why it has no size; an approval a size")


@dataclass(frozen=True, slots=True)
class IntentRecord:
    """An entry intent with its protective stop, linked to its decision and assessment."""

    opportunity_id: str
    assessment_id: str
    timestamp_ms: int
    intent: Intent
    source_refs: tuple[str, ...]
    schema: str = "combined-v1"

    def __post_init__(self) -> None:
        _refs(self.source_refs)
        if (
            not isinstance(self.opportunity_id, str)
            or not self.opportunity_id
            or not isinstance(self.assessment_id, str)
            or not self.assessment_id
            or type(self.timestamp_ms) is not int
            or self.timestamp_ms < 0
            or not isinstance(self.intent, Intent)
            or self.schema != "combined-v1"
        ):
            raise ValueError("invalid intent record")

    @property
    def record_id(self) -> str:
        return self.intent.intent_id


class Evidence:
    def __init__(self) -> None:
        self._events: dict[str, DecisionEvent] = {}
        self._last: dict[str, DecisionEvent] = {}
        self._clock = -1

    @property
    def events(self) -> tuple[DecisionEvent, ...]:
        return tuple(self._events.values())

    def record(self, event: DecisionEvent) -> None:
        if event.event_id in self._events:
            if self._events[event.event_id] != event:
                raise ValueError("conflicting duplicate event")
            return
        if event.timestamp_ms < self._clock:
            raise ValueError("evidence time moved backwards")
        prior = self._last.get(event.opportunity_id)
        if prior is None:
            if event.phase != "detected":
                raise ValueError("first phase must detect opportunity")
        else:
            if not prior.accepted:
                raise ValueError("refused opportunity is terminal")
            if prior.symbol != event.symbol:
                raise ValueError("opportunity symbol changed")
            expected = min(PHASES.index(prior.phase) + 1, len(PHASES) - 1)
            if PHASES.index(event.phase) != expected:
                raise ValueError("entry phase skipped or moved backwards")
        self._events[event.event_id] = event
        self._last[event.opportunity_id] = event
        self._clock = event.timestamp_ms

    def json_lines(self) -> str:
        previous = "0" * 64
        rows = []
        for event in self._events.values():
            payload = {"event": asdict(event), "previous_hash": previous}
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            rows.append(
                json.dumps(
                    {**payload, "hash": digest},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
            )
            previous = digest
        return "".join(row + "\n" for row in rows)
