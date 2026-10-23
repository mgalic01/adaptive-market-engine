"""The two hold comparisons, ``hold_universe`` and ``hold_btc``: spot-only accounts that replay one
cell over the same packs and window as the V4 arms, into the same records and ``CellResult``.

Implements the spec's "Versions in the run" (the paragraph on the hold comparisons and its
bullets), with the rules it names from the rest of the spec: "Account and execution" ("Timing",
the cash clip's spot rule, "Exchange filters", "Reductions are never refused for size" and its
dust rule, "Window end"), "Safety" ("Delisting or a dead market", accounting) and "Records". A
hold arm has no signal and no futures, so it has no funding, no margin cushion, no 3x ceiling and
no liquidation check.

**The account is run.py's ``_CellState``:** the ledger, the lifecycles, the pending book, the
records, the synthetic closes, the open mark, the booking of a batch, the window-end close, the
audit and every error path. ``_HoldCell`` adds only the hold's decision and its fill phase. Its
hour follows the spec's order of events:

1. the dead-market closes due at this hour, as one batch (``_CellState._synthetic_closes``). A
   held spot leg whose venue has had no bar for 168 hours closes whole at its last close less
   10%, with the spot fee, no slippage and no filter, and the close cancels the coin's pending
   order (``_after_synthetic_close``). The batch's liquidation test, like the open mark's, needs
   futures maintenance, so on a cash and spot account it never stops the cell;
2. the open mark, kept in ``open_marks`` (``_CellState._open_mark``), complete only when every
   leg held at it and every leg step 1 closed has its bar at the hour;
3. at a month's first 00:00, the ``monthly`` record and the decision (below); then, every hour,
   the cancels of a dead market without a close (``_CellState._dead_market_cancels``, Codex
   review of PR #293): a coin whose order still waits, flat, while its spot market dies (a bar
   once, none in the 168 hours before the hour) loses the order, recorded as ``order_cancelled``
   with the reason ``dead market``, so the order never fills when the data comes back and the
   coin comes back only through a later month's decision. The month's selection leaves out a
   coin with no daily bar in the 7 days before it, so this is a coin that dies after the
   decision;
4. the fills due this hour (below).

Then each held leg's hour goes to ``DeadMarkets``. The last hour ends with the window-end close:
every holding is sold at the hour's close with the cell's costs, and unsellable dust stays and is
censored as ``window end (dust)``. Every hour ends with the audit and its ``hourly`` record, and
the last one with the ``outcome``.

**The decision.** ``hold_universe`` decides at each month's first 00:00. With n >= 1 coins in the
month's universe, each gets the weight ``0.99 / n``. Every coin held, or in the last month's
universe, that is not in this one gets 0, so an empty month gives 0 to every coin. ``hold_btc``
decides once, at the window's first hour, giving BTCUSDT 0.99, and holds it to the window end. A
market without BTCUSDT is a ValueError, so that cell ends as ``engine_error``. The targets go to
``PendingBook.decide``, which supersedes a coin's older order still deferred (recorded as
``order_superseded``). A weight ``0.99 / n``, and a notional below, that has no finite decimal
(n = 7) is cut toward zero at 60 digits, so it is never above the exact share.

**The fills.** From the decision's next hour, a coin's order waits for its own first hour with a
spot bar when the coin holds spot or its target is above 0 (V4's deferral rule; a flat coin with
a target of 0 needs no bar), unless its spot market dies first (step 3). At the coin's fill hour:

* **The target notional** is ``0.99 x equity / n``, with the equity of that hour's open mark,
  before the hour's fills, and the n of the order's own decision; a weight of 0 gives 0. There
  is no band: the spot leg is planned to the target's quantity at the open (``plan_leg``),
  floored to the step.
* **Sales first, then buys,** each group alphabetical by symbol (``_CellState._book_legs``). A
  buy larger than the cash then left is cut to what that cash pays for at its slipped price with
  its fee, ``n (1 + s)(1 + f) <= cash``, then floored to the step (``_book_increase``: on a
  spot-only account the cash clip's free cash is the wallet, with no margin and no maintenance).
  A buy below the minimum quantity or notional, before or after a cut, is skipped and recorded:
  the ``order`` event's ``refusal``, or the ``increase_cut`` event's.
* **Dust.** A sale leaves its unsellable remainder as dust. A holding that cannot be sold at the
  open is dust as a whole: valued at its mark, and sold by the first later order that can sell it
  (each month's decision gives a held coin outside the universe a target of 0 again).

Each fill's reason is ``rebalance``, or ``universe exit`` for an order with a target of 0. Each
coin's fills form one lifecycle batch with the reason ``universe exit``. A rebalance that only
resizes a holding never ends a lifecycle; the one that empties a holding applies the hold's
universe rule: a coin that left, an empty month, or a share smaller than one step. So a hold
arm's lifecycles end as ``universe exit``, ``delisting``, ``window end`` or ``window end (dust)``.

**Records,** in the V4 arms' shapes (run.py's module docstring): ``hourly``, ``monthly``,
``fill``, ``event`` and ``lifecycle``, and the ``outcome`` last. There is no ``daily_coin`` (a
hold arm has no signal) and no ``funding`` (no futures). A coin's ``order`` event at its fill hour
has the ``source`` ``rebalance``, its order's ``decision_ms`` and weight as ``target``,
``eligible`` false, no band (``current`` and ``band`` null) and no exits. Its ``split`` holds on
spot the target notional net of the coin's dust, as V4's split of a spot-only coin does.

A hold arm's hour costs O(legs held and orders waiting): the open mark, the dead-market checks,
the audit and the ``hourly`` record. It decides only at a month's first midnight and plans only
in an hour with an order due.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_DOWN, Context, Decimal
from fractions import Fraction
from pathlib import Path

from crypto_grid_bot.v4.engine.allocation import LegTargets, to_venue_quantity
from crypto_grid_bot.v4.engine.arms import ARMS, HOLD_INVESTED, CellSpec
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal, to_fraction
from crypto_grid_bot.v4.engine.orders import plan_leg
from crypto_grid_bot.v4.engine.pending import Pending
from crypto_grid_bot.v4.engine.run import (
    DAY_MS,
    DELISTING,
    UNIVERSE_EXIT,
    CellResult,
    _CellState,
    _Key,
    _Leg,
    _month_of,
    _order_record,
    _run,
)

HOLD_BTC_COIN = "BTCUSDT"
# The reason of a hold order's fills with a target above 0, and the source of its order event.
REBALANCE = "rebalance"

_ZERO = Decimal(0)
# A share with no finite decimal (0.99 / 7) is cut toward zero, never rounded up.
_TRUNCATE = Context(prec=CONTEXT.prec, rounding=ROUND_DOWN)


def run_hold_cell(market: Market, cell: CellSpec, out_dir: Path) -> CellResult:
    """Replay one hold cell over ``market`` into ``out_dir`` (module docstring) and return its
    result, as ``run_v4_cell`` does for a V4 cell. A V4 arm, ``hold_btc_trend`` (not run yet), or
    an ``out_dir`` that already holds a cell's files, is a ValueError and nothing is written."""
    if not isinstance(market, Market):
        raise ValueError(f"a Market is required, got {market!r:.60}")
    if not isinstance(cell, CellSpec):
        raise ValueError(f"a CellSpec is required, got {cell!r:.60}")
    if ARMS[cell.arm].family != "hold":
        raise ValueError(f"{cell.arm} is not a hold arm; the V4 arms run in run.py")
    # Registered before its loop exists (Task 4 of the arms plan): run as hold_universe it would
    # be a mislabelled cell, so it is refused.
    if cell.arm == "hold_btc_trend":
        raise ValueError(f"{cell.arm} is not run yet: the engine has no trend hold")
    only = HOLD_BTC_COIN if cell.arm == "hold_btc" else None
    return _run(_HoldCell(market, cell, only), Path(out_dir))


class _HoldCell(_CellState):
    """A hold arm's cell: the monthly (or single) decision and the fill phase, on the shared
    account of ``_CellState``. ``only`` is hold_btc's one coin, None for hold_universe."""

    def __init__(self, market: Market, cell: CellSpec, only: str | None) -> None:
        super().__init__(market, cell)
        self._only = only
        self._universe: tuple[str, ...] = ()
        # A coin's pending order always holds its latest weight: the decision that gave the
        # weight made the order. Each decision's n sizes its orders at their fill hours.
        self._targets: dict[str, Decimal] = {}
        self._sizes: dict[int, int] = {}

    def _hour(self, h: int) -> None:
        phases: tuple[Callable[[int], None], ...] = (
            self._synthetic_closes,
            self._open_mark,
            self._decide,
            self._dead_market_cancels,
            self._fills,
            self._observe_markets,
        )
        for phase in phases:
            phase(h)
            if self._stop is not None:
                return

    def _decide(self, h: int) -> None:
        """Step 3, at a month's first 00:00 only: the ``monthly`` record of the market's
        universe, then the hold's targets (module docstring) to ``PendingBook.decide``."""
        if h % DAY_MS or _month_of(h) == _month_of(h - DAY_MS):
            return
        month = _month_of(h)
        previous, self._universe = self._universe, self.market.universe(month)
        self._record("monthly", self._monthly_record(h, month, self._universe, previous))
        coins: tuple[str, ...]
        if self._only is not None:
            if h != self.market.window_start_ms:
                return  # hold_btc decides once
            if self._only not in self.market.symbols:
                raise ValueError(f"hold_btc holds {self._only}, which the market does not have")
            n, coins = 1, (self._only,)
        else:
            n, coins = len(self._universe), self._universe
        targets = dict.fromkeys(coins, _share(HOLD_INVESTED, n) if n else _ZERO)
        if self._only is None:
            left = (self._held_coins() | frozenset(previous)) - frozenset(coins)
            targets.update(dict.fromkeys(sorted(left), _ZERO))
        self._sizes[h] = n
        self._record_superseded(h, self._book.decide(h, targets))
        self._targets.update(targets)

    def _fills(self, h: int) -> None:
        """Step 4: the orders due at ``h`` (``PendingBook.due``, asking ``_ready``), as one
        batch (``_rebalance``)."""
        orders = self._book.due(h, self._ready)
        if orders:
            self._rebalance(h, orders)

    def _ready(self, coin: str) -> bool:
        """Whether the coin's order may fill this hour (spec "Longs on spot first", deferrals,
        as for V4): it needs a spot bar when the coin holds spot or its target is above 0."""
        if self._ledger.quantity("spot", coin) > 0 or self._targets[coin] > 0:
            return self._has_spot_bar(coin)
        return True

    def _rebalance(self, h: int, orders: Sequence[Pending]) -> None:
        """Book the hour's batch (module docstring, the fills): each due coin's spot leg is
        planned to its target notional at this hour's open mark's equity, and its ``order``
        event recorded, before any fill; ``_book_legs`` then fills the sales, then the buys,
        each buy cut to the cash; each coin's fills go to its lifecycle as one batch."""
        if self._open is None:
            raise RuntimeError("the fills need this hour's open mark")
        equity = self._open[0].equity
        if equity <= 0:
            raise RuntimeError(f"equity {equity} at the open of {h}: nothing can be sized")
        legs: list[_Leg] = []
        for order in orders:  # by coin, as PendingBook.due returns them
            coin = order.coin
            holding = self._holding(coin)
            notional = self._notional(order, equity)
            planned: list[_Leg] = []
            if holding.spot or notional:
                key: _Key = ("spot", coin)
                price = self._fill_open(key)
                target = to_venue_quantity(notional, price)
                plan = plan_leg("spot", holding.spot, target, price, self._rules[key])
                reason = REBALANCE if order.target > 0 else UNIVERSE_EXIT
                planned.append(_Leg(coin, key, price, holding.spot, target, plan, reason))
            net = to_fraction(notional) - to_fraction(holding.dust_notional)
            self._record(
                "event",
                _order_record(
                    h,
                    coin,
                    equity,
                    order,
                    order.decision_ms,
                    None,
                    (order.target, False, REBALANCE),
                    {},
                    holding.state(coin, notional, False, False),
                    holding,
                    LegTargets(to_decimal(max(net, Fraction(0))), _ZERO),
                    planned,
                ),
            )
            legs.extend(planned)
        batches = self._book_legs(h, legs)
        for coin in sorted(batches):
            self._close_batch(h, coin, batches[coin], UNIVERSE_EXIT)

    def _notional(self, order: Pending, equity: Decimal) -> Decimal:
        """The order's target notional, ``0.99 x equity / n`` with the n of its decision (cut
        toward zero at 60 digits), or 0 for a weight of 0."""
        if order.target <= 0:
            return _ZERO
        invested = to_decimal(to_fraction(HOLD_INVESTED) * to_fraction(equity))
        return _share(invested, self._sizes[order.decision_ms])

    def _after_synthetic_close(
        self, h: int, coin: str, closed: Mapping[_Key, tuple[str, Decimal]]
    ) -> None:
        """A dead-market close cancels the coin's pending order (spec "Pending orders are
        cancelled"): the coin comes back only through a later month's decision, and never for
        hold_btc, which decides once."""
        self._cancel(h, coin, DELISTING)


def _share(amount: Decimal, n: int) -> Decimal:
    """``amount / n``, exact when it has at most 60 digits and otherwise cut toward zero."""
    return _TRUNCATE.divide(amount, Decimal(n))
