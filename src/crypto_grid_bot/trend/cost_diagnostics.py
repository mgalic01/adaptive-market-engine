"""Frozen reported-only costs and minimum-capital scaling from retained evidence."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.account import FuturesAccount
from crypto_grid_bot.trend.runner import TrendRunner

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class CostDiagnostics:
    fill_count: int
    fees: Decimal
    funding_paid: Decimal
    funding_received: Decimal
    slippage_cost: Decimal
    traded_notional: Decimal


def cost_diagnostics(account: FuturesAccount) -> CostDiagnostics:
    """Traded notional is gross absolute filled quantity times slipped price.

    Slippage is descriptive: it is already embedded in fill prices and must not
    be deducted again from net PnL. Partial accounts are reportable; this function
    does not replace accounting validation or certify a run's completion.
    """
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        fills = account.fills
        paid = received = ZERO
        for event in account.funding:
            for payment in event.payments:
                if payment.payment > 0:
                    paid += payment.payment
                else:
                    received -= payment.payment
        return CostDiagnostics(
            len(fills),
            sum((fill.fee for fill in fills), ZERO),
            paid,
            received,
            sum((fill.quantity * (fill.price - fill.open_price) for fill in fills), ZERO),
            sum((abs(fill.quantity) * fill.price for fill in fills), ZERO),
        )


@dataclass(frozen=True, slots=True)
class MinimumAccountSize:
    required_usdt: Decimal
    symbol: str
    timestamp_ms: int
    intended_quantity: Decimal
    intended_notional: Decimal
    binding_filter: str


def minimum_account_size(runner: TrendRunner) -> MinimumAccountSize | None:
    """Scale every main-test intended increase, even refused/zero-rounded orders.

    The maximum ratio is rounded up to 10 USDT. None means no intended increase.
    This is not a rerun: it ignores how changed filters/rounding at another capital
    size alter the subsequent path. The enclosing report validates run evidence.
    """
    if runner.multiple != 2 or runner.account.cost_multiple != 1 or runner.account.initial != 10000:
        raise ValueError("minimum capital requires the base-cost 10000-USDT m=2 main account")
    selected = None
    largest = ZERO
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        for stamp, _, hour in runner.hours:
            for symbol, plan in hour.plans:
                quantity = plan.intended_increase_quantity
                if quantity is None:
                    if (
                        plan.intended_increase_notional != ZERO
                        or any(not order.reduce_only for order in plan.orders)
                        or plan.refusals
                    ):
                        raise ValueError("missing or inconsistent intention evidence")
                    continue
                notional = plan.intended_increase_notional
                if (
                    notional is None
                    or not notional.is_finite()
                    or notional <= 0
                    or not quantity.is_finite()
                    or quantity == 0
                ):
                    raise ValueError("missing or invalid intended notional/quantity evidence")
                filters = runner.filters[symbol]
                ratios = {
                    "minimum_notional": filters.min_notional / notional,
                    "quantity_step": filters.step_size / abs(quantity),
                    "minimum_quantity": filters.min_quantity / abs(quantity),
                }
                binding = max(ratios, key=lambda name: ratios[name])
                required = ratios[binding] * runner.account.initial
                if selected is None or required > largest:
                    largest = required
                    selected = MinimumAccountSize(
                        (required / 10).to_integral_value(rounding=ROUND_CEILING) * 10,
                        symbol,
                        stamp,
                        quantity,
                        notional,
                        binding,
                    )
    return selected
