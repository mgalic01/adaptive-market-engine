"""Causal local decision funnel: qualification, geometry, one shared reservation.

No live exchange orders are produced. Successful submissions return a replay
queue item. A grid item is ONE reserved basket plus three equal-risk geometry
weights; replay must allocate/round children within that basket, enforce each
child's venue minimums, and release unused capacity through acknowledged cancel.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from threading import RLock

from crypto_grid_bot.combined.account import FillEvent
from crypto_grid_bot.combined.components import ComponentPlan, component_plan
from crypto_grid_bot.combined.engine import (
    EngineSnapshot,
    PortfolioEngine,
    Quote,
    SettlementObservation,
)
from crypto_grid_bot.combined.evidence import DecisionEvent, DecisionRecord, Evidence
from crypto_grid_bot.combined.execution import VenueRules, _decimal
from crypto_grid_bot.combined.models import Assessment, assessment_source_reasons
from crypto_grid_bot.combined.risk import Admission, Intent, planned_price
from crypto_grid_bot.combined.routing import Qualification, RoutingContext, qualify


@dataclass(frozen=True, slots=True)
class Costs:
    fee_rate: Decimal
    slippage_rate: Decimal
    round_trip_cost_rate: Decimal

    def __post_init__(self) -> None:
        for value in (self.fee_rate, self.slippage_rate, self.round_trip_cost_rate):
            if not isinstance(value, Decimal) or not value.is_finite() or not 0 <= value < 1:
                raise ValueError("finite cost rates in [0, 1) required")


@dataclass(frozen=True, slots=True)
class FundingEstimate:
    rate: Decimal
    published_ms: int
    interval_ms: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rate, Decimal)
            or not self.rate.is_finite()
            or self.rate.copy_abs() > 1
            or type(self.published_ms) is not int
            or self.published_ms < 0
            or type(self.interval_ms) is not int
            or self.interval_ms <= 0
        ):
            raise ValueError("invalid published funding estimate")


@dataclass(frozen=True, slots=True)
class VenueInputs:
    rules: VenueRules
    costs: Costs
    funding: FundingEstimate | None = None
    funding_admission: bool = True
    quote: Quote | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rules, VenueRules)
            or not isinstance(self.costs, Costs)
            or (self.funding is not None and not isinstance(self.funding, FundingEstimate))
            or type(self.funding_admission) is not bool
            or (self.quote is not None and not isinstance(self.quote, Quote))
        ):
            raise ValueError("invalid venue inputs")


@dataclass(frozen=True, slots=True)
class DecisionResult:
    qualification: Qualification
    plan: ComponentPlan | None
    intent: Intent | None
    admission: Admission | None
    events: tuple[DecisionEvent, ...]
    venue_inputs: VenueInputs | None = None
    record: DecisionRecord | None = None


@dataclass(frozen=True, slots=True)
class _Exposure:
    """The symbol's held and reserved quantity and notional, and its group's gross."""

    held_quantity: Decimal
    held_notional: Decimal
    reserved_quantity: Decimal
    reserved_notional: Decimal
    group: str
    group_gross: Decimal


def _exposure(
    engine: PortfolioEngine, symbol: str, groups: tuple[tuple[str, str], ...]
) -> _Exposure:
    """Read the engine's current inventory and reservations without observing anything."""
    mapping = dict(groups)
    group = mapping.get(symbol, "unknown")
    held_quantity = held_notional = reserved_quantity = reserved_notional = gross = Decimal(0)
    for position, *_ in engine.held_execution_terms():
        notional = abs(position.quantity) * position.mark
        if position.symbol == symbol:
            held_quantity, held_notional = position.quantity, notional
        if mapping.get(position.symbol, "unknown") == group:
            gross += notional
    for intent, admission in engine.reserved_intents:
        if intent.symbol == symbol:
            reserved_quantity += admission.quantity
            reserved_notional += admission.notional
        if mapping.get(intent.symbol, "unknown") == group:
            gross += admission.notional
    return _Exposure(
        held_quantity, held_notional, reserved_quantity, reserved_notional, group, gross
    )


def _decision_record(
    record_id: str,
    opportunity_id: str,
    assessment: Assessment,
    last: DecisionEvent,
    qualification: Qualification | None,
    admission: Admission | None,
    spot: VenueInputs | None,
    futures: VenueInputs | None,
    exposure: _Exposure,
) -> DecisionRecord:
    """The record of a funnel whose last recorded event is ``last``; no signal without
    a qualification."""
    accepted = last.accepted and last.phase == "submitted"
    quantity: Decimal | None = None
    if accepted and admission is not None:
        quantity, unavailable = admission.quantity, None
    elif qualification is None:
        unavailable = "no_signal"
    else:
        unavailable = "unqualified" if admission is None else "risk_refused"
    funding = None if futures is None else futures.funding
    return DecisionRecord(
        record_id,
        opportunity_id,
        assessment.assessment_id,
        assessment.symbol,
        assessment.decision_ms,
        assessment.decision_ms,
        accepted,
        last.phase,
        last.reasons,
        None if qualification is None else qualification.owner,
        0 if qualification is None else qualification.side,
        None if spot is None else spot.costs.fee_rate,
        None if spot is None else spot.costs.slippage_rate,
        None if spot is None else spot.costs.round_trip_cost_rate,
        None if futures is None else futures.costs.fee_rate,
        None if futures is None else futures.costs.slippage_rate,
        None if futures is None else futures.costs.round_trip_cost_rate,
        None if funding is None else funding.rate,
        None if funding is None else funding.published_ms,
        None if funding is None else funding.interval_ms,
        quantity,
        unavailable,
        exposure.held_quantity,
        exposure.held_notional,
        exposure.reserved_quantity,
        exposure.reserved_notional,
        exposure.group,
        exposure.group_gross,
        last.source_refs,
    )


@dataclass(frozen=True, slots=True)
class OpeningExecution:
    fill: FillEvent | None
    before: EngineSnapshot | None
    observations: tuple[SettlementObservation, ...]
    failure: str | None


class DecisionCoordinator:
    """Serialize entry funnels; replay owns subsequent filled events and executions.

    Source references must cover the supplied assessment, quotes, costs, filters,
    funding and correlation snapshot. Source verification remains the adapter's
    responsibility. No caller-provided spot-executable Boolean authorizes fallback:
    only an actual normal-size spot preview refused as ``below_minimum`` can do so,
    meaning the size before committed cash or capacity misses the venue minimum
    (owner decision 2026-10-11). A spot size cut short by commitments is refused.
    Each VenueInputs must provide its own fresh quote. The separate quotes and
    position_rules mappings are authoritative HELD position marks and filters;
    candidate venue inputs never replace them, including during spot fallback.
    Every decision returns its DecisionRecord, read from the engine before any
    preview or reservation; the record never feeds a decision.
    """

    def __init__(self, engine: PortfolioEngine, evidence: Evidence) -> None:
        self._engine, self._evidence = engine, evidence
        self._lock = RLock()
        self._seen: dict[str, tuple[object, DecisionResult]] = {}

    def decide(
        self,
        opportunity_id: str,
        assessment: Assessment,
        routing: RoutingContext,
        quotes: Mapping[str, Quote],
        spot: VenueInputs | None,
        futures: VenueInputs | None,
        source_refs: tuple[str, ...],
        *,
        position_rules: Mapping[str, VenueRules] | None = None,
        groups: tuple[tuple[str, str], ...] = (),
    ) -> DecisionResult:
        with self._lock, localcontext(Context(prec=60)):
            prefix = f"{len(opportunity_id)}:{opportunity_id}"
            detected = DecisionEvent(
                f"{prefix}:detected",
                opportunity_id,
                assessment.decision_ms,
                assessment.symbol,
                "detected",
                True,
                (),
                (),
                source_refs,
            )
            held_rules = dict(position_rules or {})
            identity = (
                assessment,
                routing,
                tuple(sorted(quotes.items())),
                spot,
                futures,
                source_refs,
                tuple(sorted(held_rules.items())),
                groups,
            )
            if opportunity_id in self._seen:
                prior, result = self._seen[opportunity_id]
                if prior != identity:
                    raise ValueError("conflicting decision opportunity")
                return result
            exposure = _exposure(self._engine, assessment.symbol, groups)
            self._evidence.record(detected)
            events = [detected]

            def record(
                phase: str,
                accepted: bool,
                reasons: tuple[str, ...] = (),
                details: tuple[tuple[str, str], ...] = (),
            ) -> None:
                event = DecisionEvent(
                    f"{prefix}:{phase}",
                    opportunity_id,
                    assessment.decision_ms,
                    assessment.symbol,
                    phase,
                    accepted,
                    reasons,
                    details,
                    source_refs,
                )
                self._evidence.record(event)
                events.append(event)

            def prepare(
                context: RoutingContext,
            ) -> tuple[Qualification, ComponentPlan | None, Intent | None, dict[str, VenueRules]]:
                qualification = qualify(assessment, context)
                source_reasons = assessment_source_reasons(assessment)
                if source_reasons:
                    qualification = replace(
                        qualification,
                        allowed=False,
                        reasons=tuple(dict.fromkeys((*qualification.reasons, *source_reasons))),
                    )
                venue = futures if qualification.owner == "futures_trend" else spot
                plan = None
                reason = ""
                quote = None if venue is None else venue.quote
                if qualification.allowed:
                    if venue is None:
                        reason = "venue_inputs_unavailable"
                    elif (
                        quote is None
                        or not 0 <= assessment.decision_ms - quote.timestamp_ms <= 3_600_000
                    ):
                        reason = "venue_quote_unavailable"
                    else:
                        plan = component_plan(
                            assessment,
                            qualification,
                            quote.price,
                            quote.timestamp_ms,
                            venue.costs.round_trip_cost_rate,
                        )
                        if plan is None:
                            reason = "component_plan_unavailable"
                        else:
                            price, stop_price = plan.reference_price, plan.stop
                            fee, slip = venue.costs.fee_rate, venue.costs.slippage_rate
                            entry = planned_price(price, plan.side, slip, venue.rules.tick)
                            exit_price = planned_price(
                                stop_price, -plan.side, slip, venue.rules.tick
                            )
                            required_cost = (
                                plan.side * (entry - price + stop_price - exit_price)
                                + (entry + exit_price) * fee
                            )
                            if price * venue.costs.round_trip_cost_rate < required_cost:
                                reason = "round_trip_cost_understated"
                if reason:
                    qualification = replace(
                        qualification, allowed=False, reasons=(*qualification.reasons, reason)
                    )
                rules = dict(held_rules)
                if not qualification.allowed or plan is None or venue is None:
                    return qualification, plan, None, rules
                funding = venue.funding
                intent = Intent(
                    intent_id=f"{prefix}:intent:{plan.venue}",
                    symbol=plan.symbol,
                    owner=plan.owner,
                    venue=plan.venue,
                    side=plan.side,
                    price=plan.reference_price,
                    stop=plan.stop,
                    requested_quantity=venue.rules.max_qty,
                    fee_rate=venue.costs.fee_rate,
                    slippage_rate=venue.costs.slippage_rate,
                    step=venue.rules.step,
                    tick=venue.rules.tick,
                    min_quantity=venue.rules.min_qty,
                    max_quantity=venue.rules.max_qty,
                    min_notional=venue.rules.min_notional,
                    correlation_group=dict(groups).get(plan.symbol, "unknown"),
                    funding_rate=None if funding is None else funding.rate,
                    funding_age_ms=None
                    if funding is None
                    else assessment.decision_ms - funding.published_ms,
                    funding_interval_ms=None if funding is None else funding.interval_ms,
                    funding_admission=venue.funding_admission,
                    risk_multiplier=plan.risk_multiplier,
                )
                return qualification, plan, intent, rules

            context = replace(routing, spot_executable=True if spot is not None else None)
            qualification, plan, intent, rules = prepare(context)
            detail: tuple[tuple[str, str], ...] = ()
            if intent is not None and intent.owner == "spot_trend" and spot is not None:
                preview = self._engine.preview(
                    intent,
                    qualification,
                    quotes,
                    rules,
                    groups,
                    candidate_quote=spot.quote,
                    candidate_rules=spot.rules,
                )
                if preview.reason == "below_minimum" and routing.futures_trend:
                    detail = (("spot_refusal", "spot_normal_size_below_venue_minimum"),)
                    qualification, plan, intent, rules = prepare(
                        replace(context, spot_executable=False)
                    )
            record("qualified", qualification.allowed, qualification.reasons, detail)
            admission = None
            venue_inputs = futures if qualification.owner == "futures_trend" else spot
            if qualification.allowed and intent is not None and venue_inputs is not None:
                admission = self._engine.submit(
                    intent,
                    qualification,
                    quotes,
                    rules,
                    groups,
                    candidate_quote=venue_inputs.quote,
                    candidate_rules=venue_inputs.rules,
                )
                record("risk_approved", admission.accepted, admission.reasons)
                if admission.accepted:
                    record(
                        "executable_size",
                        True,
                        details=(
                            ("quantity", str(admission.quantity)),
                            (
                                "scope",
                                "aggregate_basket_only"
                                if intent.owner == "spot_grid"
                                else "single_intent",
                            ),
                        ),
                    )
                    record(
                        "submitted",
                        True,
                        details=(
                            ("destination", "replay_queue"),
                            ("intent_id", intent.intent_id),
                            (
                                "allocation",
                                "aggregate_grid_basket"
                                if intent.owner == "spot_grid"
                                else "single_intent",
                            ),
                        ),
                    )
            result = DecisionResult(
                qualification,
                plan,
                intent,
                admission,
                tuple(events),
                venue_inputs,
                _decision_record(
                    f"{prefix}:decision",
                    opportunity_id,
                    assessment,
                    events[-1],
                    qualification,
                    admission,
                    spot,
                    futures,
                    exposure,
                ),
            )
            self._seen[opportunity_id] = identity, result
            return result

    def record_unavailable(
        self,
        opportunity_id: str,
        assessment: Assessment,
        spot: VenueInputs | None,
        futures: VenueInputs | None,
        source_refs: tuple[str, ...],
        *,
        groups: tuple[tuple[str, str], ...] = (),
    ) -> DecisionRecord:
        """Record an unavailable assessment with no signal as a refused detection.

        Its reasons are the assessment's. Nothing is qualified, sized or reserved; the
        caller establishes that there is no signal and which hours one episode spans.
        """
        if not isinstance(assessment, Assessment) or assessment.available or not assessment.reasons:
            raise ValueError("an unavailable assessment with reasons required")
        with self._lock, localcontext(Context(prec=60)):
            prefix = f"{len(opportunity_id)}:{opportunity_id}"
            event = DecisionEvent(
                f"{prefix}:detected",
                opportunity_id,
                assessment.decision_ms,
                assessment.symbol,
                "detected",
                False,
                assessment.reasons,
                (("signal", "none"),),
                source_refs,
            )
            exposure = _exposure(self._engine, assessment.symbol, groups)
            self._evidence.record(event)
            return _decision_record(
                f"{prefix}:decision",
                opportunity_id,
                assessment,
                event,
                None,
                None,
                spot,
                futures,
                exposure,
            )

    def execute_opening(
        self,
        opportunity_id: str,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
    ) -> OpeningExecution:
        """Fill this coordinator's admitted trend at its same-boundary venue quote.

        The enclosing frame must settle due funding and protective exits BEFORE
        calling. This bridge does not execute grid limit baskets, infer finality,
        or authorize a historical run. Held-asset marks remain caller-authoritative;
        only the newly owned symbol adopts its admitted venue. Repeated identical
        calls return retained evidence, including failed prefixes, without retry.
        The attempt is registered on the engine's account, not on this coordinator.
        """
        batch_id = f"opening:{len(opportunity_id)}:{opportunity_id}"
        with self._lock, self._engine.exclusive():
            identity = (tuple(sorted(quotes.items())), tuple(sorted(rules.items())))
            if opportunity_id not in self._seen:
                raise ValueError("opening requires this coordinator's recorded decision")
            prior = self._engine.retained_attempt(batch_id, identity)
            if prior is not None:
                if not isinstance(prior, OpeningExecution):
                    raise ValueError("attempt identity belongs to another frame kind")
                return prior
            # Refusals here precede every mutation, so they are not attempts.
            decision = self._opening_terms(opportunity_id, batch_id)
            self._engine.begin_attempt(batch_id, identity)
            result = self._open(opportunity_id, decision, batch_id, quotes, rules)
            self._engine.finish_attempt(batch_id, result)
            return result

    def _opening_terms(self, opportunity_id: str, batch_id: str) -> DecisionResult:
        decision = self._seen[opportunity_id][1]
        intent, admission, venue = decision.intent, decision.admission, decision.venue_inputs
        if (
            intent is None
            or admission is None
            or not admission.accepted
            or intent.owner not in {"spot_trend", "futures_trend"}
            or venue is None
            or venue.quote is None
        ):
            raise ValueError("accepted trend admission required")
        now = decision.events[0].timestamp_ms
        if venue.quote.timestamp_ms != now or self._engine.clock != now:
            raise ValueError("opening execution requires the original decision boundary")
        if self._engine.booked_fill(batch_id) is not None:
            raise ValueError("opening execution identity already booked")
        return decision

    def _open(
        self,
        opportunity_id: str,
        decision: DecisionResult,
        batch_id: str,
        quotes: Mapping[str, Quote],
        rules: Mapping[str, VenueRules],
    ) -> OpeningExecution:
        intent, admission, venue = decision.intent, decision.admission, decision.venue_inputs
        if intent is None or admission is None or venue is None or venue.quote is None:
            raise ValueError("accepted trend admission required")
        now = decision.events[0].timestamp_ms
        if any(
            not isinstance(quotes.get(position.symbol), Quote)
            or quotes[position.symbol].timestamp_ms != now
            or not isinstance(rules.get(position.symbol), VenueRules)
            for position, *_ in self._engine.held_execution_terms()
        ):
            return OpeningExecution(None, None, (), "opening_current_held_market_required")
        before = None
        failure = None
        try:
            before = self._engine.observe(now, quotes, rules)
            active_ids = {a.intent_id for a in self._engine.reservations}
            if intent.intent_id not in active_ids:
                failure = "opening_admission_no_longer_active"
            elif (
                # Verified unsellable dust keeps its obligation but blocks no new asset.
                set(before.close_required) - set(self._engine.close_dust(rules))
                or any(key not in active_ids for key in before.unresolved_execution)
                or any(p.symbol == intent.symbol for p in before.account.positions)
            ):
                failure = "opening_protection_unresolved"
            else:
                price = planned_price(intent.price, intent.side, intent.slippage_rate, intent.tick)
                fill = FillEvent(
                    batch_id,
                    now,
                    intent.symbol,
                    intent.owner,
                    intent.venue,
                    intent.side,
                    admission.quantity,
                    price,
                    _decimal(
                        Fraction(admission.quantity) * Fraction(price) * Fraction(intent.fee_rate)
                    ),
                )
                active_quotes, active_rules = dict(quotes), dict(rules)
                active_quotes[intent.symbol] = venue.quote
                active_rules[intent.symbol] = venue.rules
                self._engine.settle(
                    batch_id,
                    now,
                    active_quotes,
                    active_rules,
                    increases=((intent.intent_id, fill),),
                )
        except (ValueError, ArithmeticError, TypeError, AttributeError) as exc:
            failure = f"opening_execution_failure:{type(exc).__name__}"
        booked = self._engine.booked_fill(batch_id)
        if booked is not None:
            try:
                self._evidence.record(
                    DecisionEvent(
                        f"{batch_id}:filled",
                        opportunity_id,
                        now,
                        intent.symbol,
                        "filled",
                        True,
                        (),
                        (
                            ("fill_id", booked.event_id),
                            ("quantity", str(booked.quantity)),
                            ("price", str(booked.price)),
                        ),
                        decision.events[-1].source_refs,
                    )
                )
            except (ValueError, TypeError, AttributeError) as exc:
                failure = f"opening_evidence_failure:{type(exc).__name__}"
        return OpeningExecution(
            booked, before, self._engine.settlement_observations(batch_id), failure
        )
