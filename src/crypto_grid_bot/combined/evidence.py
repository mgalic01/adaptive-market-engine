"""Immutable, deterministic entry-funnel evidence; not an execution authorization.

The caller persists the serialized journal through the reviewed replay writer.
This component performs no file IO and cannot overwrite prior saved evidence.
"""

import hashlib
import json
from dataclasses import asdict, dataclass

from crypto_grid_bot.market_data.parsing import symbol_name

PHASES = ("detected", "qualified", "risk_approved", "executable_size", "submitted", "filled")


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
