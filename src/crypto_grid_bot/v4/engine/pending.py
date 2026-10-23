"""The book of V4's pending daily decisions, mandatory exit legs and replacement spot buys.

Implements the spec's "Signals" (the no-bar day and the two overriding events), "Sizing" (the
band paragraph's deferral, mandatory-exit and replacement-buy bullets) and "Safety" (pending
orders are cancelled). The semantics are V3's ``trend.pending.PendingDecisions`` (copied, not
called: it reaches a 2024 guard), minus the walk-forward pick logic. The book knows hours and
coins only. It never sees a price, a venue's rules or equity; the hour loop answers "is the
coin usable this hour" through callbacks, and sizes every order itself.

* **Daily orders.** ``decide`` runs at 00:00 UTC. Each coin in ``targets`` gets a ``Pending``
  and replaces the coin's older one, which comes back as cancelled. A coin absent from
  ``targets`` (a day with no daily bar) keeps its older order. ``due`` returns the orders that
  may fill this hour: made at least an hour ago, and ``ready(coin)`` (the coin's fill-hour bars
  exist). So a new decision never fills in its own hour, while a kept order may fill at 00:00.
* **Mandatory exits.** One ``Exit`` per held leg: a universe exit schedules the coin's spot and
  futures legs, a funding-month exit only its futures leg. ``after_ms`` is the fill hour, the
  decision hour plus one hour. Each leg returns from ``due_exits`` at its own venue's first hour
  at or after ``after_ms`` that has a bar, independently of the coin's other leg.
* **Replacement spot buys.** A funding-month futures close is followed by a spot buy, placed at
  the first hour at or after the close's fill that has a spot bar. The book only times it; the
  hour loop sizes it from the coin's latest target. A decision whose targets include the coin
  supersedes it, so only the latest target ever produces the buy, whichever order the calls of
  that 00:00 hour come in: a replacement scheduled before ``decide`` is cancelled by it (and
  reported in ``Decided.cancelled_replacements``), and one scheduled after it in the same hour is
  refused by ``schedule_replacement``, which returns False.
* ``cancel`` is for the events that end a coin's deferred orders: a universe exit, a
  funding-month exit, a dead-market close and a dead market without a close (a waiting coin
  whose spot market has died). It removes the coin's pending order and its pending replacement,
  and leaves scheduled exits alone.
* **Three read-only queries,** ``exit_scheduled(coin, venue)``, ``replacement_pending(coin)``
  and ``waiting()`` (the coins with an order or a replacement buy pending), let the hour loop
  see what the book holds (so it never schedules a second exit for a leg, can record the
  replacement a ``cancel`` removes, and can find the waiting coins whose market has died)
  without keeping a copy of the book's state.

Order of calls in an hour, following the spec's "Order of events in an hour": first the
synthetic closes due at the hour's open (dead-market and synthetic funding-month closes), each
with its ``cancel(coin)`` and, for a futures close, its ``schedule_replacement``; then, at 00:00,
``decide``, followed by ``cancel(coin)`` for each universe or funding-month exit that decision
makes (so it drops that decision's own order for the coin); then, every hour, ``cancel(coin)``
for each ``waiting()`` coin whose spot market has died; then ``due``, ``due_exits``, the
booking of the fills (each futures close of a funding-month exit followed by
``schedule_replacement``), and then ``due_replacements``, so that a close filled in an hour can
be replaced in that same hour. A dead-market close's ``cancel`` must come before ``decide``:
after it, it would remove the order the new decision just made. Every call checks all its input
before it changes any state, so a refused call (or a callback that raises) leaves the book as it
was. Each ``due*`` method keeps its own clock and refuses an hour that is not after its previous
one.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import get_args

from crypto_grid_bot.v4.engine.ledger import Venue

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS

_VENUES: tuple[str, ...] = get_args(Venue)

# The V4 data layer's symbol pattern (ruling R7).
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")


@dataclass(frozen=True, slots=True)
class Pending:
    """A daily decision waiting to fill: the coin's target weight (a signed fraction of
    equity, ``|target| <= 1``) from the decision made at ``decision_ms``."""

    coin: str
    decision_ms: int
    target: Decimal

    def __post_init__(self) -> None:
        _symbol(self.coin, "coin")
        _hour(self.decision_ms, "decision_ms")
        _target(self.target)


@dataclass(frozen=True, slots=True)
class Exit:
    """One mandatory exit leg: close the coin's ``venue`` leg at the first hour at or after
    ``after_ms`` (the decision hour plus one hour) at which that venue has a bar."""

    coin: str
    venue: Venue
    reason: str
    after_ms: int

    def __post_init__(self) -> None:
        _symbol(self.coin, "coin")
        if self.venue not in _VENUES:
            raise ValueError(f"venue must be one of {_VENUES}, got {self.venue!r:.40}")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError(f"reason must be a non-empty string, got {self.reason!r:.40}")
        _hour(self.after_ms, "after_ms")


@dataclass(frozen=True, slots=True)
class Decided:
    """What one ``decide`` call superseded: the pending orders it replaced (``cancelled``, by
    coin) and the replacement buys it cancelled (``cancelled_replacements``, by coin)."""

    cancelled: tuple[Pending, ...]
    cancelled_replacements: tuple[str, ...]


class PendingBook:
    """One pending order per coin, the scheduled exit legs and the pending replacement buys."""

    def __init__(self) -> None:
        self._pending: dict[str, Pending] = {}
        self._exits: dict[tuple[str, str], Exit] = {}
        self._replacements: dict[str, int] = {}
        # The latest decision hour and the coins that decision gave a target.
        self._decided = -1
        self._decided_coins: frozenset[str] = frozenset()
        # The latest hour each due method served.
        self._clock_orders = -1
        self._clock_exits = -1
        self._clock_replacements = -1

    def decide(self, decision_ms: int, targets: Mapping[str, Decimal]) -> Decided:
        """Record the targets of the decision made at ``decision_ms`` (00:00 UTC).

        Each coin in ``targets`` replaces its older order and its pending replacement buy. A
        coin absent from ``targets`` keeps both. A decision hour must be after the previous
        decision and after every hour a ``due*`` method has served.
        """
        _hour(decision_ms, "decision_ms")
        if decision_ms % DAY_MS:
            raise ValueError(f"a decision is made at 00:00 UTC only, got {decision_ms}")
        if decision_ms <= self._decided:
            raise ValueError(f"decision hours must increase: {decision_ms} <= {self._decided}")
        served = max(self._clock_orders, self._clock_exits, self._clock_replacements)
        if decision_ms <= served:
            raise ValueError(
                f"a decision comes before the fills of its hour: {decision_ms} <= {served}"
            )
        if not isinstance(targets, Mapping):
            raise ValueError("targets must be a mapping of coin to target weight")
        # Building every order checks every coin and target before any state changes.
        built = {coin: Pending(coin, decision_ms, target) for coin, target in targets.items()}
        orders = {coin: built[coin] for coin in sorted(built)}
        cancelled = tuple(self._pending[coin] for coin in orders if coin in self._pending)
        cancelled_replacements = tuple(coin for coin in orders if coin in self._replacements)
        self._pending.update(orders)
        for coin in cancelled_replacements:
            del self._replacements[coin]
        self._decided = decision_ms
        self._decided_coins = frozenset(orders)
        return Decided(cancelled, cancelled_replacements)

    def due(self, hour_ms: int, ready: Callable[[str], bool]) -> tuple[Pending, ...]:
        """The orders that may fill at ``hour_ms``, by coin, removed from the book: made at
        least an hour ago, for a coin that ``ready`` says is usable this hour."""
        self._serve(hour_ms, self._clock_orders)
        due: list[Pending] = []
        for coin in sorted(self._pending):
            order = self._pending[coin]
            if hour_ms >= order.decision_ms + HOUR_MS and _flag(ready(coin), "ready"):
                due.append(order)
        self._clock_orders = hour_ms
        for order in due:
            del self._pending[order.coin]
        return tuple(due)

    def cancel(self, coin: str) -> Pending | None:
        """Drop the coin's pending order and its pending replacement buy, not its scheduled
        exits. Returns the order.

        For a universe exit, a funding-month exit, a dead-market close or a dead market without
        a close. A dead-market close calls it before that hour's ``decide``; a universe or
        funding-month exit, and a dead market without a close, call it after.
        """
        _symbol(coin, "coin")
        self._replacements.pop(coin, None)
        return self._pending.pop(coin, None)

    def schedule_exit(self, exit: Exit) -> None:
        """Schedule one mandatory exit leg. A second exit for the same coin and venue is
        refused, as is one for an hour ``due_exits`` has already served."""
        if not isinstance(exit, Exit):
            raise ValueError(f"an Exit is required, got {exit!r:.60}")
        if (exit.coin, exit.venue) in self._exits:
            raise ValueError(f"{exit.coin} already has an exit scheduled on {exit.venue}")
        _not_passed(exit.after_ms, self._clock_exits, "exit")
        self._exits[(exit.coin, exit.venue)] = exit

    def due_exits(self, hour_ms: int, has_bar: Callable[[str, Venue], bool]) -> tuple[Exit, ...]:
        """The exit legs to close at ``hour_ms``, by coin then venue, removed from the book:
        ``after_ms`` has come and ``has_bar(coin, venue)`` says the leg's venue has a bar."""
        self._serve(hour_ms, self._clock_exits)
        due: list[Exit] = []
        for key in sorted(self._exits):
            leg = self._exits[key]
            if hour_ms >= leg.after_ms and _flag(has_bar(leg.coin, leg.venue), "has_bar"):
                due.append(leg)
        self._clock_exits = hour_ms
        for leg in due:
            del self._exits[(leg.coin, leg.venue)]
        return tuple(due)

    def exit_scheduled(self, coin: str, venue: Venue) -> bool:
        """Whether an exit leg of the coin on ``venue`` is scheduled and ``due_exits`` has not
        returned it yet. Changes nothing."""
        _symbol(coin, "coin")
        if venue not in _VENUES:
            raise ValueError(f"venue must be one of {_VENUES}, got {venue!r:.40}")
        return (coin, venue) in self._exits

    def replacement_pending(self, coin: str) -> bool:
        """Whether the coin has a replacement buy scheduled that has not been placed, cancelled
        or superseded. Changes nothing."""
        _symbol(coin, "coin")
        return coin in self._replacements

    def waiting(self) -> tuple[str, ...]:
        """The coins with a pending order or a pending replacement buy, sorted. Changes
        nothing."""
        return tuple(sorted(self._pending.keys() | self._replacements.keys()))

    def schedule_replacement(self, coin: str, after_ms: int) -> bool:
        """Schedule the spot buy that replaces a funding-month futures close filled at
        ``after_ms``; it waits for its first spot bar from that hour on.

        Returns False, scheduling nothing, when the decision made in that very hour (a 00:00
        decision hour) gave the coin a newer target, which supersedes the buy. The caller
        records that as a cancelled replacement. A second replacement for a coin, or one for an
        hour ``due_replacements`` has already served, is refused.
        """
        _symbol(coin, "coin")
        _hour(after_ms, "after_ms")
        if coin in self._replacements:
            raise ValueError(f"{coin} already has a replacement buy pending")
        _not_passed(after_ms, self._clock_replacements, "replacement buy")
        if after_ms == self._decided and coin in self._decided_coins:
            return False
        self._replacements[coin] = after_ms
        return True

    def due_replacements(
        self, hour_ms: int, has_spot_bar: Callable[[str], bool]
    ) -> tuple[str, ...]:
        """The coins whose replacement buy is placed at ``hour_ms``, in order, removed from
        the book: the futures close has filled (``after_ms`` is this hour or earlier) and
        ``has_spot_bar(coin)`` says spot has a bar."""
        self._serve(hour_ms, self._clock_replacements)
        due: list[str] = []
        for coin in sorted(self._replacements):
            if hour_ms >= self._replacements[coin] and _flag(has_spot_bar(coin), "has_spot_bar"):
                due.append(coin)
        self._clock_replacements = hour_ms
        for coin in due:
            del self._replacements[coin]
        return tuple(due)

    def _serve(self, hour_ms: int, clock: int) -> None:
        """Check an hour a ``due*`` method is asked to serve: after its own previous hour, and
        not before the latest decision."""
        _hour(hour_ms, "hour_ms")
        if hour_ms <= clock:
            raise ValueError(f"hours must increase: {hour_ms} <= {clock}")
        if hour_ms < self._decided:
            raise ValueError(f"hour {hour_ms} is before the latest decision {self._decided}")


def _symbol(value: object, what: str) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"{what}: symbol must match [A-Z0-9]{{2,30}}, got {value!r:.40}")
    return value


def _hour(value: object, what: str) -> int:
    if type(value) is not int or value < 0 or value % HOUR_MS:
        raise ValueError(f"{what} must be a non-negative int on an hour (ms), got {value!r:.40}")
    return value


def _target(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value.copy_abs() > 1:
        raise ValueError(f"a target must be a finite Decimal with |target| <= 1, got {value!r:.40}")
    return value


def _flag(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{what} must return a bool, got {value!r:.40}")
    return value


def _not_passed(after_ms: int, clock: int, what: str) -> None:
    if after_ms <= clock:
        raise ValueError(f"a {what} for hour {after_ms} has passed: hours up to {clock} are served")
