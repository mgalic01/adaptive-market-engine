"""Causal local decision funnel: qualification, geometry, one shared reservation.

No exchange orders or fills are produced. Successful submissions return a replay
queue item. A grid item is ONE reserved basket plus three equal-risk geometry
weights; replay must allocate/round children within that basket, enforce each
child's venue minimums, and release unused capacity through acknowledged cancel.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Context, Decimal, localcontext
from threading import RLock

from crypto_grid_bot.combined.components import ComponentPlan, component_plan
from crypto_grid_bot.combined.engine import PortfolioEngine, Quote
from crypto_grid_bot.combined.evidence import DecisionEvent, Evidence
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.combined.models import Assessment
from crypto_grid_bot.combined.risk import Admission, Intent
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

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rules, VenueRules)
            or not isinstance(self.costs, Costs)
            or (self.funding is not None and not isinstance(self.funding, FundingEstimate))
            or type(self.funding_admission) is not bool
        ):
            raise ValueError("invalid venue inputs")


@dataclass(frozen=True, slots=True)
class DecisionResult:
    qualification: Qualification
    plan: ComponentPlan | None
    intent: Intent | None
    admission: Admission | None
    events: tuple[DecisionEvent, ...]


class DecisionCoordinator:
    """Serialize entry funnels; replay owns subsequent filled events and executions.

    Source references must cover the supplied assessment, quotes, costs, filters,
    funding and correlation snapshot. Source verification remains the adapter's
    responsibility. No caller-provided spot-executable Boolean authorizes fallback:
    only an actual normal-size spot preview below the venue minimum can do so.
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
                venue = futures if qualification.owner == "futures_trend" else spot
                plan = None
                reason = ""
                quote = quotes.get(assessment.symbol)
                if qualification.allowed:
                    if venue is None:
                        reason = "venue_inputs_unavailable"
                    elif quote is None:
                        reason = "quote_unavailable"
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
                            entry = price * (1 + plan.side * slip)
                            exit_price = stop_price * (1 - plan.side * slip)
                            required_cost = (price + stop_price) * slip + (entry + exit_price) * fee
                            if price * venue.costs.round_trip_cost_rate < required_cost:
                                reason = "round_trip_cost_understated"
                if reason:
                    qualification = replace(
                        qualification, allowed=False, reasons=(*qualification.reasons, reason)
                    )
                rules = dict(held_rules)
                if not qualification.allowed or plan is None or venue is None:
                    return qualification, plan, None, rules
                rules[assessment.symbol] = venue.rules
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
            if intent is not None and intent.owner == "spot_trend":
                preview = self._engine.preview(intent, qualification, quotes, rules, groups)
                if preview.reason == "below_minimum" and routing.futures_trend:
                    detail = (("spot_refusal", "spot_normal_size_below_venue_minimum"),)
                    qualification, plan, intent, rules = prepare(
                        replace(context, spot_executable=False)
                    )
            record("qualified", qualification.allowed, qualification.reasons, detail)
            admission = None
            if qualification.allowed and intent is not None:
                admission = self._engine.submit(intent, qualification, quotes, rules, groups)
                record(
                    "risk_approved",
                    admission.accepted,
                    () if admission.accepted else (admission.reason,),
                )
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
            result = DecisionResult(qualification, plan, intent, admission, tuple(events))
            self._seen[opportunity_id] = identity, result
            return result
