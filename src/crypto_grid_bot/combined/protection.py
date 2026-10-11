"""Pure conservative OHLC protection, separate from fills, accounting and recovery.

The engine verifies bar completion, ATR source freshness and event identity. It also
retains close obligations across missing bars and partial fills. A BarExit is a price
instruction for that engine, not an assertion that an exchange filled a position.
"""

from dataclasses import dataclass, replace
from decimal import Decimal, localcontext

from crypto_grid_bot.backtest.klines import Kline


@dataclass(frozen=True, slots=True)
class ProtectionState:
    side: int
    entry: Decimal
    initial_stop: Decimal
    stop: Decimal
    best: Decimal
    trail_active: bool


@dataclass(frozen=True, slots=True)
class BarExit:
    reason: str
    price: Decimal


def _positive(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or not 0 < value <= Decimal("1e36"):
        raise ValueError("finite positive bounded Decimal required")


def _state_valid(state: ProtectionState) -> None:
    if type(state.side) is not int or state.side not in {-1, 1}:
        raise ValueError("side must be exactly +1 or -1")
    if type(state.trail_active) is not bool:
        raise ValueError("trail activation must be Boolean")
    for value in (state.entry, state.initial_stop, state.stop, state.best):
        _positive(value)
    if (
        (state.entry - state.initial_stop) * state.side <= 0
        or (state.stop - state.initial_stop) * state.side < 0
        or (state.best - state.entry) * state.side < 0
        or (state.best - state.stop) * state.side <= 0
    ):
        raise ValueError("inconsistent protection state or widened stop")


def initial_protection(side: int, entry: Decimal, completed_atr: Decimal) -> ProtectionState:
    """Initialize a two-ATR stop; caller has verified the completed four-hour ATR."""
    if type(side) is not int or side not in {-1, 1}:
        raise ValueError("side must be exactly +1 or -1")
    _positive(entry)
    _positive(completed_atr)
    with localcontext() as ctx:
        ctx.prec = 60
        stop = entry - side * 2 * completed_atr
        state = ProtectionState(side, entry, stop, stop, entry, False)
        _state_valid(state)
        return state


def manage_completed_bar(
    state: ProtectionState,
    bar: Kline | None,
    *,
    atr: Decimal | None = None,
    atr_fresh: bool = False,
    target: Decimal | None = None,
    slippage: Decimal = Decimal(0),
    trailing: bool = True,
) -> tuple[ProtectionState, BarExit | None]:
    """Honor the old stop before target and only then evaluate a completed-bar trail.

    Best completed price is the favorable high/low of a completed bar. A newly
    tightened stop NEVER executes retroactively at that bar's low/high. If the
    completed close is already beyond it, reduce at that actual close with adverse
    slippage (``trailing_at_close``), not at the better stop price. Otherwise the
    new stop applies to subsequent events. Targets receive no favorable gap credit.

    Missing/invalid/stale ATR prevents tightening, not old-stop protection. A missing
    bar returns no execution price and preserves state; it does not release any
    external close obligation or classify an asset as flat.
    """
    with localcontext() as ctx:
        ctx.prec = 60
        _state_valid(state)
        if type(trailing) is not bool:
            raise ValueError("trailing setting must be Boolean")
        if not isinstance(slippage, Decimal) or not slippage.is_finite() or not 0 <= slippage < 1:
            raise ValueError("finite slippage in [0, 1) required")
        if target is not None:
            _positive(target)
            if (target - state.entry) * state.side <= 0:
                raise ValueError("target must be favorable to entry")
        if bar is None:
            return state, None
        if not isinstance(bar, Kline) or type(bar.open_ms) is not int or bar.open_ms < 0:
            raise ValueError("valid completed bar required")
        for price in (bar.open, bar.high, bar.low, bar.close):
            _positive(price)
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
            raise ValueError("inconsistent OHLC prices")

        def exit_at(reason: str, price: Decimal) -> BarExit:
            return BarExit(reason, price * (1 - state.side * slippage))

        long = state.side == 1
        if (bar.low <= state.stop) if long else (bar.high >= state.stop):
            price = min(bar.open, state.stop) if long else max(bar.open, state.stop)
            return state, exit_at("stop", price)
        if target is not None and ((bar.high >= target) if long else (bar.low <= target)):
            return state, exit_at("target", target)

        best = max(state.best, bar.high) if long else min(state.best, bar.low)
        active = state.trail_active or (
            trailing
            and (best - state.entry) * state.side >= 2 * abs(state.entry - state.initial_stop)
        )
        after = replace(state, best=best, trail_active=active)
        usable_atr = (
            atr_fresh is True
            and isinstance(atr, Decimal)
            and atr.is_finite()
            and 0 < atr <= Decimal("1e36")
        )
        if trailing and active and usable_atr and atr is not None:
            candidate = best - state.side * 3 * atr
            stop = max(state.stop, candidate) if long else min(state.stop, candidate)
            after = replace(after, stop=stop)
            if (bar.close - stop) * state.side <= 0:
                return after, exit_at("trailing_at_close", bar.close)
        return after, None
