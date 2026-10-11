"""Allocate three grid limit instructions inside ONE admitted basket.

No reservations, submissions, cancels or fills occur here. Buy LIMITS round down
to avoid paying above their planned level; this is not favorable market execution
rounding. Replay still fills touched limits without favorable gap-price credit.
Exact inverse-risk weights precede quantity flooring. Actual child risk differs
after steps and is reported separately; no exact equal-risk execution is claimed.
Unused budget remains reserved until the engine receives an acknowledgment.
"""

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.combined.decisions import DecisionResult


def _decimal(value: Fraction) -> Decimal:
    # Every conversion here is a terminating price/quantity/cost; weights stay rational.
    precision = len(str(abs(value.numerator))) + 4 * len(str(value.denominator)) + 10
    with localcontext(Context(prec=precision)):
        return Decimal(value.numerator) / Decimal(value.denominator)


@dataclass(frozen=True, slots=True)
class GridChild:
    child_id: str
    limit: Decimal
    quantity: Decimal
    weight: Fraction
    risk_bound: Decimal
    actual_stop_risk: Decimal
    cash: Decimal
    notional: Decimal


@dataclass(frozen=True, slots=True)
class GridAllocation:
    accepted: bool
    reason: str
    basket_id: str
    children: tuple[GridChild, ...]
    quantity: Decimal
    risk: Decimal
    cash: Decimal
    notional: Decimal
    unused_quantity: Decimal
    unused_risk: Decimal
    unused_cash: Decimal
    unused_notional: Decimal


def allocate_grid(result: DecisionResult) -> GridAllocation:
    """Return all three executable children or refuse the entire frozen basket.

    The quote, common stop, quantity/cash/risk/notional budgets and execution
    context come only from the admitted decision. Tick rounding can collapse
    levels or cross the stop; those cases refuse rather than silently drop levels.
    """
    plan, intent, admission, venue = (
        result.plan,
        result.intent,
        result.admission,
        result.venue_inputs,
    )
    if (
        plan is None
        or intent is None
        or admission is None
        or venue is None
        or not admission.accepted
        or not result.qualification.allowed
        or plan.owner != "spot_grid"
        or intent.owner != "spot_grid"
        or plan.venue != "spot"
        or intent.venue != "spot"
        or plan.side != 1
        or intent.side != 1
        or len(plan.levels) != 3
        or plan.symbol != intent.symbol
        or admission.intent_id != intent.intent_id
        or plan.stop != intent.stop
        or plan.reference_price != intent.price
    ):
        raise ValueError("approved coherent spot grid basket required")
    rule, costs = venue.rules, venue.costs
    if (rule.step, rule.min_qty, rule.max_qty, rule.min_notional) != (
        intent.step,
        intent.min_quantity,
        intent.max_quantity,
        intent.min_notional,
    ) or (costs.fee_rate, costs.slippage_rate) != (intent.fee_rate, intent.slippage_rate):
        raise ValueError("grid execution context differs from admission")
    budgets = (admission.quantity, admission.risk, admission.cash, admission.notional)
    if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in budgets):
        raise ValueError("finite positive basket budgets required")
    total_quantity, total_risk, total_cash, total_notional = map(Fraction, budgets)

    def finish(reason: str, children: tuple[GridChild, ...] = ()) -> GridAllocation:
        values = tuple(
            sum((Fraction(getattr(child, field)) for child in children), Fraction(0))
            for field in ("quantity", "risk_bound", "cash", "notional")
        )
        unused = tuple(
            Fraction(budget) - used for budget, used in zip(budgets, values, strict=True)
        )
        return GridAllocation(
            bool(children),
            reason,
            intent.intent_id,
            children,
            *(_decimal(value) for value in values),
            *(_decimal(value) for value in unused),
        )

    tick, step = Fraction(rule.tick), Fraction(rule.step)
    reference, stop = Fraction(plan.reference_price), Fraction(plan.stop)
    prices = tuple((Fraction(level.price) // tick) * tick for level in plan.levels)
    if (
        len(set(prices)) != 3
        or any(not stop < price < reference for price in prices)
        or not prices[0] > prices[1] > prices[2]
    ):
        return finish("invalid_rounded_levels")
    cost_bound = reference * Fraction(costs.round_trip_cost_rate)
    inverse = tuple(1 / (price - stop + cost_bound) for price in prices)
    denominator = sum(inverse)
    weights = tuple(value / denominator for value in inverse)
    fee, slip = Fraction(costs.fee_rate), Fraction(costs.slippage_rate)
    # Match adverse sell execution: slippage first, then floor to the venue tick.
    exit_price = (stop * (1 - slip) // tick) * tick
    if exit_price <= 0:
        return finish("invalid_stop_execution_price")
    children = []
    for index, (price, weight) in enumerate(zip(prices, weights, strict=True), start=1):
        quantity = (total_quantity * weight // step) * step
        if (
            quantity <= 0
            or quantity < Fraction(rule.min_qty)
            or quantity > Fraction(rule.max_qty)
            or quantity * price < Fraction(rule.min_notional)
        ):
            return finish("child_below_minimum")
        fees = (price + exit_price) * fee
        execution_cost = stop - exit_price + fees
        if execution_cost > cost_bound:
            return finish("round_trip_cost_understated")
        children.append(
            GridChild(
                f"{intent.intent_id}:level:{index}",
                _decimal(price),
                _decimal(quantity),
                weight,
                _decimal(quantity * (price - stop + cost_bound)),
                _decimal(quantity * (price - stop + execution_cost)),
                _decimal(quantity * (price + execution_cost)),
                _decimal(quantity * price),
            )
        )
    answer = finish("allocated", tuple(children))
    if (
        Fraction(answer.quantity) > total_quantity
        or Fraction(answer.risk) > total_risk
        or Fraction(answer.cash) > total_cash
        or Fraction(answer.notional) > total_notional
    ):
        return finish("basket_budget_exceeded")
    return answer
