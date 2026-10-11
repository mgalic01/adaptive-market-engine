"""Synthetic boundary funding and protective exits before strategy opening fills.

The registered input adapter must prove the due-funding calendar and source records.
This module does not infer that missing funding is zero or authorize any data run.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .account import FillEvent, FundingEvent
from .engine import EngineSnapshot, PortfolioEngine, Quote, SettlementObservation
from .execution import (
    VenueRules,
    _decimal,
    adverse_price,
    executable_reduction,
    executable_trim,
    funding_cashflow,
)


@dataclass(frozen=True, slots=True)
class FundingFixing:
    event_id: str
    symbol: str
    timestamp_ms: int
    rate: Decimal
    mark: Decimal


@dataclass(frozen=True, slots=True)
class BoundaryExecution:
    funding: tuple[FundingEvent, ...]
    fills: tuple[FillEvent, ...]
    observations: tuple[SettlementObservation, ...]
    final: EngineSnapshot | None
    failure: str | None
    source_refs: tuple[str, ...]
    # Close obligations left only on inventory no legal order can reduce at fresh marks.
    retained_dust: tuple[str, ...] = ()


class BoundaryExecutor:
    def __init__(self, engine: PortfolioEngine) -> None:
        self._engine = engine

    def settle(
        self,
        batch_id: str,
        timestamp_ms: int,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        *,
        due_funding: tuple[str, ...],
        fixings: tuple[FundingFixing, ...],
        source_refs: tuple[str, ...],
        unpriced: tuple[str, ...] = (),
    ) -> BoundaryExecution:
        """Book pre-boundary holdings' funding, then drain protective reductions.

        Use genuine current opening or closing quotes of each HELD venue, never
        renamed intrabar marks or a new candidate's venue quote. Terminal callers
        must supply the previous interval's verified endpoint and no next-window
        funding. The reserved endpoint is not supported yet.
        Every attempt is retained on the engine's account, so neither a corrected
        attempt nor a new executor instance can retry a failed boundary.
        Verified unsellable dust keeps its close obligation but is not a failure.
        Holdings named in ``unpriced`` have no bar at this boundary and so no quote:
        nothing executes for them and their obligations are carried, not a failure.
        Any other held symbol without a current quote is an input defect.
        """
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("boundary identity required")
        prefix = f"boundary:{len(batch_id)}:{batch_id}"
        with self._engine.exclusive():
            identity = (
                timestamp_ms,
                tuple(sorted(quotes.items())),
                tuple(sorted(rules.items())),
                due_funding,
                fixings,
                source_refs,
                unpriced,
            )
            prior = self._engine.retained_attempt(prefix, identity)
            if prior is not None:
                if not isinstance(prior, BoundaryExecution):
                    raise ValueError("attempt identity belongs to another frame kind")
                return prior
            self._engine.begin_attempt(prefix, identity)
            result = self._settle(
                prefix, timestamp_ms, quotes, rules, due_funding, fixings, source_refs, unpriced
            )
            self._engine.finish_attempt(prefix, result)
            return result

    def _settle(
        self,
        prefix: str,
        timestamp_ms: int,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        due_funding: tuple[str, ...],
        fixings: tuple[FundingFixing, ...],
        source_refs: tuple[str, ...],
        unpriced: tuple[str, ...],
    ) -> BoundaryExecution:
        fills: list[FillEvent] = []
        observations: list[SettlementObservation] = []
        final = None
        failure = None
        dust: tuple[str, ...] = ()
        funding_ids: list[str] = []
        try:
            held = {p.symbol: p for p, *_ in self._engine.held_execution_terms()}
            valid = (
                type(timestamp_ms) is int
                and 0 <= timestamp_ms < 1735689600000
                and timestamp_ms >= self._engine.clock
                and isinstance(due_funding, tuple)
                and all(isinstance(s, str) and s.strip() for s in due_funding)
                and len(set(due_funding)) == len(due_funding)
                and isinstance(fixings, tuple)
                and all(isinstance(f, FundingFixing) for f in fixings)
                and isinstance(source_refs, tuple)
                and bool(source_refs)
                and all(isinstance(s, str) and s.strip() for s in source_refs)
                and isinstance(unpriced, tuple)
                and all(isinstance(s, str) for s in unpriced)
                and len(set(unpriced)) == len(unpriced)
            )
            if valid:
                valid = (
                    len(fixings) == len(due_funding)
                    and {f.symbol for f in fixings} == set(due_funding)
                    and len({f.event_id for f in fixings}) == len(fixings)
                    and all(
                        isinstance(f.event_id, str)
                        and bool(f.event_id.strip())
                        and type(f.timestamp_ms) is int
                        and f.timestamp_ms == timestamp_ms
                        and isinstance(f.rate, Decimal)
                        and f.rate.is_finite()
                        and abs(f.rate) <= 1
                        and isinstance(f.mark, Decimal)
                        and f.mark.is_finite()
                        and 0 < f.mark <= Decimal("1e36")
                        for f in fixings
                    )
                    and set(unpriced) <= set(held)
                    and not set(unpriced) & set(quotes)
                    and all(
                        isinstance(quotes.get(s), Quote)
                        and quotes[s].timestamp_ms == timestamp_ms
                        and isinstance(rules.get(s), VenueRules)
                        for s in held
                        if s not in unpriced
                    )
                )
            if not valid:
                failure = "invalid_boundary_inputs"
            else:
                payments: list[FundingEvent] = []
                for fixing in sorted(fixings, key=lambda f: f.symbol):
                    if self._engine.booked_funding(fixing.event_id) is not None:
                        raise ValueError("funding identity already booked")
                    position = held.get(fixing.symbol)
                    # Only surviving futures holdings pay or receive; spot never does.
                    if position is not None and position.venue == "futures":
                        funding_ids.append(fixing.event_id)
                        payments.append(
                            FundingEvent(
                                fixing.event_id,
                                timestamp_ms,
                                fixing.symbol,
                                funding_cashflow(position, fixing.rate, fixing.mark),
                            )
                        )
                funding_batch = f"{prefix}:funding"
                try:
                    final = self._engine.settle(
                        funding_batch, timestamp_ms, quotes, rules, funding=tuple(payments)
                    )
                finally:
                    observations.extend(self._engine.settlement_observations(funding_batch))
                final = self._drain(
                    prefix, timestamp_ms, quotes, rules, final, fills, observations, unpriced
                )
                active = {a.intent_id for a in self._engine.reservations}
                dust = self._engine.close_dust(rules)
                if set(final.close_required) - set(dust) - set(unpriced) or any(
                    k not in active for k in final.unresolved_execution
                ):
                    failure = "unresolved_boundary_obligations"
                if any(
                    o.snapshot.liquidation
                    or not o.snapshot.account.integrity_ok
                    or "execution_integrity_failure" in o.snapshot.reasons
                    for o in observations
                ):
                    failure = "boundary_safety_failure"
        except (ValueError, ArithmeticError, TypeError, AttributeError) as exc:
            failure = f"boundary_execution_failure:{type(exc).__name__}"
            final = None  # Last successful mark may precede a booked event.
            dust = ()
        booked_payments = tuple(
            event for key in funding_ids if (event := self._engine.booked_funding(key)) is not None
        )
        return BoundaryExecution(
            booked_payments, tuple(fills), tuple(observations), final, failure, source_refs, dust
        )

    def _drain(
        self,
        prefix: str,
        timestamp_ms: int,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
        final: EngineSnapshot,
        fills: list[FillEvent],
        observations: list[SettlementObservation],
        unpriced: tuple[str, ...],
    ) -> EngineSnapshot:
        """Execute every legal held-venue reduction at the boundary quote, in symbol order.

        Full closes come first; cut-back obligations then reduce to their targets.
        Unpriced holdings have no quote, so their obligations wait.
        """
        while final.close_required or final.reduce_to:
            progressed = False
            targets = {s: k for s, k in final.reduce_to if s not in final.close_required}
            for symbol in (*sorted(final.close_required), *sorted(targets)):
                terms = {
                    p.symbol: (p, fee, slip)
                    for p, _, fee, slip in self._engine.held_execution_terms()
                }
                if symbol not in terms or symbol in unpriced:
                    continue
                position, fee, slip = terms[symbol]
                side = -1 if position.quantity > 0 else 1
                price = quotes[symbol].price
                if symbol in targets:
                    reduction = executable_trim(
                        abs(position.quantity),
                        targets[symbol],
                        price,
                        rules[symbol],
                        side=side,
                        slippage=slip,
                    )
                else:
                    reduction = executable_reduction(
                        abs(position.quantity), price, rules[symbol], side=side, slippage=slip
                    )
                if not reduction.quantity:
                    continue
                if len(fills) >= 10000:
                    raise ValueError("boundary fill budget exhausted")
                execution_id = f"{prefix}:close:{len(fills)}:{symbol}"
                if self._engine.booked_fill(execution_id) is not None:
                    raise ValueError("boundary execution identity already booked")
                actual = adverse_price(
                    _decimal(Fraction(price) * (1 + side * Fraction(slip))), side, rules[symbol]
                )
                fill = FillEvent(
                    execution_id,
                    timestamp_ms,
                    symbol,
                    position.owner,
                    position.venue,
                    side,
                    reduction.quantity,
                    actual,
                    _decimal(Fraction(reduction.quantity) * Fraction(actual) * Fraction(fee)),
                )
                try:
                    final = self._engine.settle(
                        execution_id, timestamp_ms, quotes, rules, reductions=(fill,)
                    )
                finally:
                    booked = self._engine.booked_fill(execution_id)
                    if booked is not None:
                        fills.append(booked)
                    observations.extend(self._engine.settlement_observations(execution_id))
                progressed = True
            if not progressed:
                break
        return final
