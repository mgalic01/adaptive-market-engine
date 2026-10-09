"""Frozen reporting groups on finalized lifecycles, not account certification."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from types import MappingProxyType

from crypto_grid_bot.trend.lifecycles import Lifecycle

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class TradeTotals:
    count: int
    censored_count: int
    realized: Decimal
    unrealized: Decimal
    fees: Decimal
    funding_paid: Decimal
    funding_received: Decimal
    net: Decimal


@dataclass(frozen=True, slots=True)
class TradeBreakdown:
    total: TradeTotals
    by_coin: Mapping[str, TradeTotals]
    by_side: Mapping[str, TradeTotals]
    by_coin_side: Mapping[tuple[str, str], TradeTotals]


def _totals(lives: Sequence[Lifecycle]) -> TradeTotals:
    return TradeTotals(
        len(lives),
        sum(life.censored for life in lives),
        sum((life.realized for life in lives), ZERO),
        sum((life.unrealized for life in lives), ZERO),
        sum((life.fees for life in lives), ZERO),
        sum((life.funding_paid for life in lives), ZERO),
        sum((life.funding_received for life in lives), ZERO),
        sum((life.net for life in lives), ZERO),
    )


def trade_breakdown(lives: Sequence[Lifecycle]) -> TradeBreakdown:
    """Include terminal-censored unrealized PnL and all costs exactly once.

    The caller supplies the complete reconciled lifecycle list. This helper
    cannot detect omitted/duplicated trades or certify account provenance. A
    fixed-rule account labels its whole report with that rule; a changing-pick
    account must not attribute an entire lifecycle to its opening rule.
    """
    for life in lives:
        values = (
            life.realized,
            life.unrealized,
            life.fees,
            life.funding_paid,
            life.funding_received,
        )
        if (
            life.side not in ("long", "short")
            or not life.symbol
            or type(life.start_ms) is not int
            or type(life.end_ms) is not int
            or life.start_ms < 0
            or life.end_ms < life.start_ms
            or type(life.censored) is not bool
            or not life.exit_reason
            or any(not value.is_finite() for value in values)
            or any(value < ZERO for value in values[2:])
        ):
            raise ValueError("need finite finalized lifecycle evidence")
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        coins = sorted({life.symbol for life in lives})
        pairs = sorted({(life.symbol, life.side) for life in lives})
        return TradeBreakdown(
            _totals(lives),
            MappingProxyType(
                {coin: _totals([x for x in lives if x.symbol == coin]) for coin in coins}
            ),
            MappingProxyType(
                {side: _totals([x for x in lives if x.side == side]) for side in ("long", "short")}
            ),
            MappingProxyType(
                {pair: _totals([x for x in lives if (x.symbol, x.side) == pair]) for pair in pairs}
            ),
        )
