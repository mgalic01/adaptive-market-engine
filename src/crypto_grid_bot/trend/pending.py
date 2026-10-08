"""Frozen V3 daily decision replacement and masked-hour deferral."""

from collections.abc import Mapping, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name

HOUR = 3600000


@dataclass(frozen=True, slots=True)
class PendingDecision:
    decision_ms: int
    weight: Decimal
    exit_reasons: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class DecisionDispatch:
    ready: tuple[tuple[str, PendingDecision], ...]
    cancelled: tuple[tuple[str, PendingDecision], ...]


class PendingDecisions:
    """One pending target per coin; absence from new targets means no-bar day.

    The scheduler calls advance before any event in the hour, then executes ready
    targets using actual fill-hour equity. Refused/band-skipped attempts are consumed
    too. Any execution exception must abort the run, never retry this dispatch.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingDecision] = {}
        self._clock = -1

    def advance(
        self,
        hour_ms: int,
        new_targets: Mapping[str, Decimal],
        tradable: Set[str],
        exit_reasons: Mapping[str, frozenset[str]] | None = None,
    ) -> DecisionDispatch:
        if type(hour_ms) is not int or hour_ms < 0 or hour_ms % HOUR or hour_ms <= self._clock:
            raise ValueError("hours must be aligned and strictly increasing")
        development_month(datetime.fromtimestamp(hour_ms // 1000, UTC).strftime("%Y-%m"))
        if new_targets and hour_ms % (24 * HOUR):
            raise ValueError("new daily targets only at midnight")
        for symbol, weight in new_targets.items():
            symbol_name(symbol)
            if not isinstance(weight, Decimal) or not weight.is_finite() or weight.copy_abs() > 1:
                raise ValueError("invalid target weight")
        for symbol in tradable:
            symbol_name(symbol)
        cancelled = []
        for symbol in sorted(new_targets):
            reasons = frozenset((exit_reasons or {}).get(symbol, ()))
            if symbol in self._pending:
                previous = self._pending[symbol]
                cancelled.append((symbol, previous))
                # The newly selected rule has not had an execution attempt yet.
                # Keep that cause even for nonzero targets: rounding or minimum
                # quantity can turn their eventual reduction into a full close.
                reasons |= previous.exit_reasons & {"pick_change"}
            self._pending[symbol] = PendingDecision(hour_ms, new_targets[symbol], reasons)
        ready = []
        for symbol, decision in sorted(self._pending.items()):
            if symbol in tradable and hour_ms >= decision.decision_ms + HOUR:
                ready.append((symbol, decision))
        for symbol, _ in ready:
            del self._pending[symbol]
        self._clock = hour_ms
        return DecisionDispatch(tuple(ready), tuple(cancelled))
