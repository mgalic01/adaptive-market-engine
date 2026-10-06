"""The uptrend engine's arithmetic (experiment spec v2, section 5): limits, stops and the position.

Pure Decimal functions and one record; nothing here reads a quote, a file or the clock. The market
buy that spends these limits is ``execution.market_buy``, and the per-frame decisions (when an entry
starts, when a close is processed, when an exit begins) belong to the simulator.

Budget. An entry's two limits are set once, when it starts: a cash cap of ``CAPITAL_CAP`` of the
active capital, and a risk allowance of ``RISK_FRACTION`` of the active equity, the most the entry
may lose if its stop is reached, before fees and slippage. Both are rounded down, so neither is
ever above its exact value.

Stop. The stop starts ``ATR_MULTIPLE`` daily ATRs below the last completed daily close and trails
that distance below the highest close, and it never moves down.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal, localcontext

from crypto_grid_bot.simulation.models import ZERO, D

RISK_FRACTION = D("0.04")
CAPITAL_CAP = D("0.60")
ATR_MULTIPLE = D(3)

# The simulator's precision, as in ``execution``: these run at it whatever the ambient context is.
_WORKING = Context(prec=50)
_LIMITS = Context(prec=50, rounding=ROUND_DOWN)


def entry_limits(active_capital: Decimal, active_equity: Decimal) -> tuple[Decimal, Decimal]:
    """The cash cap and the risk allowance of an entry, in USDT, set once when it starts."""
    with localcontext(_LIMITS):
        return CAPITAL_CAP * active_capital, RISK_FRACTION * active_equity


def stop_distance(price: Decimal, stop: Decimal) -> Decimal:
    """``s = (price - stop) / price``. No entry starts when it is zero or below."""
    with localcontext(_WORKING):
        return (price - stop) / price


def initial_stop(close: Decimal, atr: Decimal) -> Decimal:
    """The first stop, from the last completed daily close and that day's ATR."""
    with localcontext(_WORKING):
        return close - ATR_MULTIPLE * atr


def trailed_stop(stop: Decimal, highest_close: Decimal, atr: Decimal) -> Decimal:
    """The stop after a daily close: ``max(stop, highest_close - 3 * atr)``, never lower."""
    with localcontext(_WORKING):
        return max(stop, highest_close - ATR_MULTIPLE * atr)


@dataclass(kw_only=True)
class UptrendPosition:
    """One pair's uptrend entry and the position it bought. Built by keyword, so no limit or
    price can be mistaken for another.

    * ``cash_cap`` and ``risk_allowance``: the two limits, as ``entry_limits`` set them.
    * ``spent``: the USDT paid so far, taker fees included, against the cash cap.
    * ``risk_used``: the sum of each buy's quantity x (price - stop), against the risk allowance.
    * ``quantity``: what the entry has bought.
    * ``stop``, ``highest_close`` and ``stop_day_ms``: the trailing stop, the highest daily close
      it trails, and the open time of the last daily bar processed into them. They start at
      ``initial_stop(c0, atr)`` and ``c0``, with ``c0`` the last completed daily close before entry.
    * ``entered_at``: the observation at which the entry started.
    * ``phase``: "entering" while it still buys, "holding" once it has stopped buying, and
      "exiting" from the moment an exit begins.
    * ``exit_reason``: "" until an exit begins, and then why.
    """

    cash_cap: Decimal
    risk_allowance: Decimal
    spent: Decimal = ZERO
    risk_used: Decimal = ZERO
    exit_reason: str = ""
    quantity: Decimal = ZERO
    stop: Decimal
    highest_close: Decimal
    stop_day_ms: int
    entered_at: str
    phase: str = "entering"
