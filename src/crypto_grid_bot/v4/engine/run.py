"""The hour loop of the V4 arms: one cell replayed over the market, hour by hour, into its
hash-chained records.

Implements the spec's "Account and execution" ("Longs on spot first" with its deferrals,
allocation and cash clip, "Shorts on futures" and its funding, "Exchange filters", "Reductions
are never refused for size", "Order of events in an hour", "Timing", "Window end"), the 00:00
decision of "Signals" (from completed daily bars; the no-bar rule and its two overrides) and of
"Sizing" (steps 1 to 3, and the band paragraph: the band at the fill hour, deferrals, mandatory
exits and replacement buys), "Universe" (point-in-time perpetual eligibility; leaving the top 10;
the monthly selection record), "Data" (the funding-month exit and its synthetic close), "Safety"
(the 3x ceiling, the margin cushion, liquidation, delisting or a dead market, how a cell that
stops early ends, accounting), "Records" and the outcomes of "Reports". ``run.py`` composes the
engine's modules and holds no trading rule of its own; the few small rules no module has are
private functions or methods here, each citing the spec (``_month_end``, ``_audit_failure``,
``_cut_quantity``, the decided-coins rule in ``_V4Cell._decide``; in the fill phase
``_V4Cell._ready``'s dust-offset case, ``_V4Cell._exit_skip`` and
``_V4Cell._schedule_replacement``'s universe guard; in the safety phases the rule of
``_CellState._synthetic_legs`` for a leg due on both counts, and the time stamp of a cut after a
funding record in ``_CellState._funding_events``).

**The hour.** ``run_v4_cell`` runs every hour ``h`` from ``market.window_start_ms`` to
``market.window_end_ms``, in the spec's order of events:

1. the synthetic closes due at this instant (dead markets, and at a month's first midnight the
   futures legs of an incomplete funding month), as one batch with one liquidation check;
2. the open mark, kept in ``open_marks`` with its completeness flag, then the pre-fill
   liquidation check;
3. at 00:00, the daily decision (below), then the mandatory exits it makes;
4. the fills due this hour (below);
5. the post-fill mark: its liquidation check, then the margin cushion and its cut, then the 3x
   ceiling and its cut, each cut filling at the open and followed by a new mark;
6. each funding record of the hour, in time order, on the positions then held, each followed by
   the checks of step 5;
7. the liquidation check at the adverse extremes, every leg at once;

then each held leg's hour is reported to ``DeadMarkets``; at the last hour comes the window-end
close (below), and last of all

8. the audit, the ``hourly`` record and, when the cell ends, the ``outcome`` record.

A phase that stops the cell (a liquidation or an unrestorable limit) skips the rest of the hour
up to step 8 (spec "How a cell that stops early ends"): no later event and no closing fill;
every open lifecycle is marked at the stopping check's prices and censored, and that mark is the
final equity. Steps 1 and 5 to 7 are ``_CellState`` methods, so ``hold.py`` (Task 13) can reuse
them, each with its contract in its docstring. Every threshold is compared on exact values
(``safety``), and every cut quantity is ``held x k`` (or ``k'``) computed in Fractions and
truncated to the step (``_cut_quantity``).

**The fills (step 4)** follow the pending book's call order (its module docstring): ``due``,
``due_exits`` (a funding-month futures close then schedules its replacement buy at this hour),
``due_replacements``; then one batch. A due order's coin takes the band test at this hour's
unslipped opens against the open mark's equity; the coins that trade (band-trading orders and
replacement buys, the latter spot-only from the coin's latest target) are re-targeted whole, and
every other held coin keeps its legs, a leg its mandatory exit closes counting as 0. Each coin's
dust is its whole spot holding when it cannot be sold. ``allocate`` runs once; each trading
coin's legs are planned to their split (spot plus its dust), and each exiting leg to 0. The
reductions fill first, then the increases, each alphabetical by coin and spot before futures; each
increase is clipped by ``clip_increases`` alone, on the account after every earlier real fill,
and re-planned to the step and the filters when it is cut. The lifecycles then see the batch.

**The window end.** At the last hour, after its other events, every position closes at the
hour's close (its carried mark without a bar) with costs; unsellable dust stays, and the
lifecycles still open are censored as ``window end`` or ``window end (dust)``.

**Prices.** A coin is keyed by its spot symbol everywhere; the perpetual's symbol is used only
for its ledger key ``("futures", perpetual)``. A held leg is marked at its venue's bar open at
``h``. Without a bar it takes its carried mark, the last close before ``h``
(``SeriesStore.last_close_before``, spec "Safety": carried at the last mark). An open mark is
complete when every leg held at it has its venue's bar at ``h``, so no carried mark is used; with
nothing held it is complete (spec "Pass rule": an arm uses a price source at an hour when it
holds or trades it). Each open lifecycle is marked at the open mark with the coin's unrealised
P&L over both venues (Ruling R6).

**The 00:00 decision** closes day ``d = h - 1 day``. On a month's first day the month's universe
is taken first (spec "Universe": the selection is made before that same decision). The coins
decided are the universe, every coin held on either venue, and, on a month's first day, every
coin that left the universe. A decided coin outside the universe is a universe exit, with target
0. Each decided coin's ``CoinSignals`` is fed its daily bars up to ``d``, never later; a coin with
no bar for ``d`` keeps its last reading and takes no new target (the no-bar rule), and one with
no reading at all is warming. The signal used is ``s`` (``L`` for ``v4_long_only``), and
``max(s, 0)`` when the coin has no eligible perpetual: ``Market.perpetual_eligible`` at ``h``,
and, at the decision on a month's last day, a complete funding status for the next month (spec
"Data": no futures exposure is held in an incomplete month). ``size_book`` sizes the book of every
decided coin (a universe exit with signal 0, so its sigma is still recorded) on each coin's
trailing returns, and ``PendingBook.decide`` takes the targets.

**Outputs** (rulings P3, P5). ``out_dir`` is the cell's own directory: created if missing, and
refused if ``records.jsonl`` or ``receipt.json`` is already there. Every record goes through
``RecordWriter``. Every path, a complete cell, a stop, an accounting failure or an exception, ends
with exactly one ``outcome`` record; the writer is then closed and ``receipt.json`` written. An
exception in the loop becomes the outcome ``engine_error``, with the result's other fields as of
the failure.

**Records written here** (Decimals as their exact strings, null where a value does not exist):

* ``monthly``, at a month's first decision: ``month``, ``open_ms``, the ``universe`` in rank
  order, who ``entered`` and who ``left``, ``perpetuals``: for each universe coin with a
  perpetual, its ``coin``, ``perpetual``, ``multiplier``, the funding ``status`` of the month and
  the ``next_status`` of ``next_month``, which the funding-month exit reads; and ``selection``,
  the month's whole selection record from the packs (``ranked`` rows ``[symbol, mean quote
  volume, bars]``, ``excluded`` pairs ``[symbol, reason]``, ``entered``, ``left``), or null for
  a market without one.
* ``daily_coin``, per decided coin: ``decision_ms``, ``day_ms``, ``coin``, ``in_universe``,
  ``universe_exit``, ``no_bar``; the reading (``reading_day_ms``, ``close``, ``speeds`` with each
  speed's values and vote, ``downtrend`` with its four parts' values and ``confirmed``, ``L``,
  ``S``, ``s``, ``s_long_only``), all null for a coin with no reading; ``perpetual``,
  ``perpetual_eligible`` (point in time), ``next_month`` and ``next_month_status`` (at a month's
  last day, else null), ``eligible``, ``funding_month_exit`` (the exit's precondition) and the
  ``signal`` used; the sizing (``sigma``, ``raw``, ``full``, ``scaled``, ``after_coin_cap``,
  ``after_total_cap``, ``capped_by``, ``scale``, ``common_days``, ``flat_reason``); and the
  ``target``, or ``no_target``: ``no_bar`` or ``warming``. The band result, the split and the
  order belong to the fill hour, as an ``event`` of type ``order`` (Task 12b).
* ``fill``, per fill: ``hour_ms``, ``timestamp_ms``, ``coin``, ``venue``, ``symbol``, ``side``,
  ``quantity`` (venue units), ``price`` (slipped), ``unslipped_price``, ``fee``, ``realised``
  and ``reason`` (``signal``, ``universe exit``, ``funding-month exit``, ``replacement buy``,
  ``margin cut``, ``ceiling cut``, ``delisting``, ``window end``). A synthetic close has no
  slippage: its ``price`` and ``unslipped_price`` are both the penalised price.
* ``funding``, per funding record charged: ``hour_ms``, ``timestamp_ms`` (the record's),
  ``coin``, ``perpetual``, ``quantity`` (the signed contracts held), ``rate``, ``price`` (the
  perpetual's open, or its carried mark), ``carried`` (whether it was the carried mark) and
  ``amount`` (``-quantity x rate x price``, positive when the wallet receives it).
* ``event``, each with its ``type``, ``hour_ms`` and ``coin`` (null for an event of the whole
  account):

  - ``order_superseded`` (an older pending order a decision replaced; ``decision_ms``,
    ``target``) and ``replacement_superseded`` (a replacement buy a decision of that hour
    superseded);
  - ``order_cancelled`` (``decision_ms``, ``target``, ``reason``) and ``replacement_cancelled``
    (``reason``), what a universe exit's, a funding-month exit's or a dead market's (reason
    ``delisting``) ``cancel`` removed;
  - ``exit_scheduled`` (``venue``, ``reason``, ``after_ms``), and ``exit_skipped`` (``venue``,
    ``reason``, ``why``: ``flat``, or ``in_universe`` for a universe exit of a coin that is back
    in the universe, whose newer decisions supersede it);
  - ``replacement_scheduled`` (only a long futures leg's funding-month close is replaced), and
    ``replacement_skipped`` (``why``: ``not_in_universe``);
  - ``synthetic_closes``, per batch (coin null): the ``legs`` closing (``coin``, ``venue``,
    ``symbol``, ``held``, ``last_close``, the penalised ``price``, ``reason``: ``delisting`` or
    ``funding-month exit``) and the ``mark`` of the batch's one liquidation check;
  - ``margin_cut`` and ``ceiling_cut``, per cut or per limit found with nothing to cut (coin
    null): the ``check`` point (``post_fill`` or ``funding``), the fills' ``timestamp_ms``, the
    mark's ``backing`` with the ``untradable_maintenance`` and ``tradable_maintenance`` (margin),
    or its ``equity`` with the ``untradable_gross`` and ``tradable_gross`` (ceiling), the
    ``factor`` k or k' (null when nothing can trade), the ``untradable`` legs as ``[venue,
    symbol]`` and the ``legs`` cut (``coin``, ``venue``, ``symbol``, ``held``, ``target``,
    ``orders``, ``dust``);
  - ``order``, per coin the fill phase handles: ``source`` (``signal``, ``replacement buy`` or
    ``exit``), ``decision_ms`` (the decision hour of the target used, for a replacement buy that
    of the coin's latest target), ``target``, ``eligible`` (as passed to the allocation, null for a
    coin keeping its legs), ``current`` and ``band`` (``trade`` or ``keep``) for a daily order,
    the ``exits`` due (``[venue, reason]``), ``equity``, the coin's ``state`` (``target_notional``,
    ``spot_notional``, ``dust``, ``dust_notional``, ``futures_notional``), the ``split``
    (``spot``, ``futures``, null for a band-kept coin) and the ``legs`` planned (``venue``,
    ``symbol``, ``held``, ``target``, ``orders`` as ``side``, ``quantity``, ``reduce_only``,
    ``refusal``, ``dust``): the order placed, or the reason none was;
  - ``increase_cut`` (``venue``, ``symbol``, ``wanted`` and ``admitted`` notionals, the
    ``quantity`` booked, and its ``refusal``: ``min_qty``, ``min_notional``, ``cash`` when nothing
    is left, or null).
* ``hourly``, once per hour after step 8: ``open_ms``, ``open_equity`` and ``complete`` (null if
  the hour stopped before its open mark), and at the end of the hour ``equity``,
  ``gross_notional``, ``gross`` (null when equity is at or below 0), ``margin_ratio`` (null with
  no futures position, read as +infinity, spec "Safety") and ``equity_residual``, the audit's.
* ``lifecycle``: every field of a ``Lifecycle``.
* ``outcome``, last: ``outcome``, ``reason``, ``stop_ms``, ``hours``, ``final_equity``,
  ``equity_2025``, ``final_after_close`` and the last ``audit``; plus ``values`` (the residuals)
  for ``accounting_failure``, ``check`` and ``mark`` for a stop, and ``type``, ``message`` and
  ``hour_ms`` for ``engine_error``.

**Outcomes.** ``complete``; ``liquidated`` (reason null); ``limit_unrestorable`` (reason
``margin_cushion`` or ``ceiling``); ``accounting_failure`` (reason ``wallet``, ``quantity`` or
``equity``: the first identity that failed, in that order); ``engine_error`` (reason
``"<Type>: <message>"``). A stop's ``check`` names the check that stopped it:
``synthetic_closes`` (the batch at its penalised prices), ``synthetic_closes_booked`` (equity at
or below zero after the batch), ``open_mark``, ``post_fill``, ``funding``, ``adverse_extremes``,
or the new mark after a cut, ``<point>_margin_cut`` or ``<point>_ceiling_cut``. A limit with
nothing tradable stops at its point (``post_fill`` or ``funding``); one a cut did not restore,
at the cut's new mark. The spec's third reason of ``limit_unrestorable``, ``required_fill`` (a
fill the rules require that cannot be made), has no path under V4's rules: every required
reduction can be made, since a futures reduction is reduce-only and ignores the minimum notional
and a spot remainder below the filters becomes dust. It exists for the summary's schema only.

The loop does O(coins) work an hour: bars by bisection, each coin's daily bars and returns
built once, on its first decision, and fed or sliced from a cursor. The fill phase does its
work only in an hour with an order, an exit or a replacement buy due, and then only for the
coins held or due.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.trend.sizing import DailyReturn
from crypto_grid_bot.v4.engine.allocation import (
    CoinState,
    LegTargets,
    allocate,
    clip_increases,
    to_venue_quantity,
)
from crypto_grid_bot.v4.engine.arms import (
    ARMS,
    COVARIANCE_DAYS,
    INITIAL_MARGIN_DIVISOR,
    MAINTENANCE_RATE,
    SIGMA_RETURNS,
    ArmSpec,
    CellSpec,
    Lookbacks,
)
from crypto_grid_bot.v4.engine.ledger import Audit, Fill, Ledger, Mark, Venue
from crypto_grid_bot.v4.engine.lifecycle import Lifecycle, Lifecycles
from crypto_grid_bot.v4.engine.market import COMPLETE, HOUR_MS, HourBar, Market, SeriesStore
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal, to_fraction
from crypto_grid_bot.v4.engine.orders import LegPlan, Order, fee, fill_price, plan_leg
from crypto_grid_bot.v4.engine.pending import Decided, Exit, Pending, PendingBook
from crypto_grid_bot.v4.engine.records import Receipt, RecordWriter, write_receipt
from crypto_grid_bot.v4.engine.safety import (
    DeadMarkets,
    adverse_prices,
    ceiling_breached,
    ceiling_factor,
    cushion_breached,
    cushion_factor,
    liquidated,
    penalised_price,
)
from crypto_grid_bot.v4.engine.signals import CoinSignals, SignalReading
from crypto_grid_bot.v4.engine.sizing import (
    CoinSizing,
    SizingResult,
    band_trades,
    daily_returns,
    size_book,
)

DAY_MS = 24 * HOUR_MS
RECORDS_FILE = "records.jsonl"
RECEIPT_FILE = "receipt.json"
# Spec "Pass rule", condition 4: equity at the open of 2025-01-01 00:00 UTC.
EQUITY_2025_MS = month_bounds_ms("2025-01")[0]
# Spec "Safety", accounting: the equity-change residual may be at most this, in USDT.
EQUITY_RESIDUAL_LIMIT = Decimal("1e-18")

# The reasons of the fills, and of the batches that end lifecycles (spec "Records").
SIGNAL = "signal"
UNIVERSE_EXIT = "universe exit"
FUNDING_EXIT = "funding-month exit"
REPLACEMENT_BUY = "replacement buy"
WINDOW_END = "window end"
DELISTING = "delisting"
MARGIN_CUT = "margin cut"
CEILING_CUT = "ceiling cut"

# The outcomes of a stop and the reasons of ``limit_unrestorable`` (spec "Reports").
LIQUIDATED = "liquidated"
LIMIT_UNRESTORABLE = "limit_unrestorable"
MARGIN_CUSHION = "margin_cushion"
CEILING = "ceiling"

_Key = tuple[Venue, str]
_VENUES: tuple[Venue, ...] = ("spot", "futures")
_ZERO = Decimal(0)
_MAINTENANCE = to_fraction(MAINTENANCE_RATE)
# The open futures' initial margin is rounded up, never down, at the engine's precision, so the
# cash clip never sees less margin than is open.
_CEILING = Context(prec=CONTEXT.prec, rounding=ROUND_CEILING)
# Sigma reads a coin's last 60 returns and the covariance the last 60 calendar days, which hold
# at most 60 returns; so the last 60 returns at or before the decision day are all size_book needs.
_RETURN_WINDOW = max(SIGMA_RETURNS, COVARIANCE_DAYS)
_NO_RESIDUALS: Mapping[_Key, Decimal] = MappingProxyType({})
# The residuals of a fresh ledger, before its first audit: nothing booked, so all exactly 0.
_START_AUDIT = Audit(_ZERO, _NO_RESIDUALS, _ZERO)


@dataclass(frozen=True, slots=True)
class CellResult:
    """What one cell's replay produced, for the summary (spec "Reports").

    ``open_marks`` holds ``(open_ms, equity, complete)`` for every hour simulated, before that
    hour's fills. ``equity_2025`` is the open mark at 2025-01-01 00:00 UTC, or None if the cell
    never reached that hour. ``final_after_close`` is the equity after the window-end close, and
    None for any other outcome. ``final_equity`` is that equity for a complete cell, a stop's mark
    for a stop, the end-of-hour mark for an accounting failure, and the last mark taken for an
    engine error. ``audit`` is the last audit run (a fresh ledger's zeros before the first).
    """

    outcome: str
    reason: str | None
    stop_ms: int | None
    open_marks: tuple[tuple[int, Decimal, bool], ...]
    final_equity: Decimal
    equity_2025: Decimal | None
    final_after_close: Decimal | None
    audit: Audit
    receipt: Receipt


def run_v4_cell(market: Market, cell: CellSpec, out_dir: Path) -> CellResult:
    """Replay one V4 cell over ``market`` into ``out_dir`` (module docstring) and return its
    result. A hold arm, or an ``out_dir`` that already holds a cell's files, is a ValueError and
    nothing is written."""
    if not isinstance(market, Market):
        raise ValueError(f"a Market is required, got {market!r:.60}")
    if not isinstance(cell, CellSpec):
        raise ValueError(f"a CellSpec is required, got {cell!r:.60}")
    arm = ARMS[cell.arm]
    if arm.family != "v4" or arm.vol_target is None or arm.lookbacks is None:
        raise ValueError(f"{cell.arm} is not a V4 arm; the hold arms have their own loop")
    return _run(_V4Cell(market, cell, arm, arm.vol_target, arm.lookbacks), Path(out_dir))


def _run(state: _CellState, out_dir: Path) -> CellResult:
    """Run ``state`` into the cell directory ``out_dir``: the records, then the receipt."""
    records, receipt_file = _cell_files(out_dir)
    with RecordWriter(records) as writer:
        try:
            state.run(writer)
        except Exception as exc:  # ruling P5: any exception in the loop is an engine_error
            state.fail(exc)
        receipt = writer.close()
    write_receipt(receipt_file, receipt)
    return state.result(receipt)


def _cell_files(out_dir: Path) -> tuple[Path, Path]:
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    records, receipt = folder / RECORDS_FILE, folder / RECEIPT_FILE
    for existing in (records, receipt):
        if existing.exists():
            raise ValueError(f"{existing} already exists; a cell's files are never replaced")
    return records, receipt


@dataclass(frozen=True, slots=True)
class _Stop:
    """A check that ended the cell: its outcome and reason, which check it was, and the prices
    and mark it judged (spec "Safety", how a cell that stops early ends)."""

    outcome: str
    reason: str | None
    check: str
    prices: Mapping[_Key, Decimal]
    mark: Mark


class _CellState:
    """One cell's account, lifecycles and records, and the parts of the hour that every arm
    shares: the prices, the open mark, the stop, the end of the hour and the outcome. The arm's
    own phases come from a subclass's ``_hour``; ``hold.py`` (Task 13) reuses this base."""

    def __init__(self, market: Market, cell: CellSpec) -> None:
        self.market = market
        self.cell = cell
        self._ledger = Ledger(Decimal(cell.capital))
        self._lifecycles = Lifecycles()
        self._dead = DeadMarkets()
        self._writer: RecordWriter | None = None
        self._costs: Mapping[Venue, Costs] = MappingProxyType(
            {venue: cell.costs(venue) for venue in _VENUES}
        )
        # Every ledger key the market knows: its store, its rules and its coin (the spot symbol).
        self._stores: dict[_Key, SeriesStore] = {}
        self._rules: dict[_Key, VenueRules] = {}
        self._coin_of: dict[_Key, str] = {}
        for symbol in market.symbols:
            coin = market.coin(symbol)
            self._stores["spot", symbol] = coin.spot
            self._rules["spot", symbol] = coin.spot_rules
            self._coin_of["spot", symbol] = symbol
            if coin.perpetual is not None:
                self._stores["futures", coin.perpetual.symbol] = coin.perpetual.store
                self._rules["futures", coin.perpetual.symbol] = coin.perpetual.rules
                self._coin_of["futures", coin.perpetual.symbol] = symbol
        # The hour being run.
        self._hour_ms = -1
        self._bars: dict[_Key, HourBar | None] = {}  # this hour's bars, looked up once
        self._prices: dict[_Key, Decimal] = {}  # this hour's marking price of each held leg
        self._carried: dict[_Key, Decimal] = {}  # each leg's carried mark, when it needed one
        self._open: tuple[Mark, bool] | None = None  # this hour's open mark and completeness
        self._stop: _Stop | None = None
        # The result.
        self._open_marks: list[tuple[int, Decimal, bool]] = []
        self._equity = Decimal(cell.capital)
        self._equity_2025: Decimal | None = None
        self._final_after_close: Decimal | None = None
        self._audit = _START_AUDIT
        self._outcome: str | None = None
        self._reason: str | None = None
        self._stop_ms: int | None = None

    # ---- the driver ----------------------------------------------------------------------

    def run(self, writer: RecordWriter) -> None:
        """Replay every hour of the window into ``writer``, up to the cell's outcome."""
        self._writer = writer
        end = self.market.window_end_ms
        hour = self.market.window_start_ms
        while hour <= end:
            self._begin_hour(hour)
            self._hour(hour)
            if self._stop is None and hour == end:
                self._window_end(hour)
            if self._end_hour(hour):
                return
            hour += HOUR_MS
        raise RuntimeError("the window ended without an outcome")  # the last hour writes one

    def fail(self, exc: Exception) -> None:
        """Record ``exc`` as the outcome ``engine_error`` (ruling P5)."""
        if self._outcome is not None:
            raise exc  # an outcome is written already; a second would contradict it
        name = type(exc).__name__
        hour = self._hour_ms if self._hour_ms >= 0 else None  # None: before the first hour
        self._final_after_close = None
        self._finish(
            "engine_error",
            f"{name}: {exc}",
            None,
            {"type": name, "message": str(exc), "hour_ms": hour},
        )

    def result(self, receipt: Receipt) -> CellResult:
        if self._outcome is None:
            raise RuntimeError("the cell has no outcome")
        return CellResult(
            outcome=self._outcome,
            reason=self._reason,
            stop_ms=self._stop_ms,
            open_marks=tuple(self._open_marks),
            final_equity=self._equity,
            equity_2025=self._equity_2025,
            final_after_close=self._final_after_close,
            audit=self._audit,
            receipt=receipt,
        )

    # ---- the hour ------------------------------------------------------------------------

    def _hour(self, h: int) -> None:
        """The arm's phases 1 to 7 at hour ``h``, stopping early once ``self._stop`` is set."""
        raise NotImplementedError

    def _begin_hour(self, h: int) -> None:
        self._hour_ms = h
        self._bars = {}
        self._open = None

    # ---- step 1: the synthetic closes -----------------------------------------------------

    def _synthetic_closes(self, h: int) -> None:
        """Step 1: the synthetic closes due at ``h``, as one batch, booked at the hour's open time
        before anything else (spec "Safety", "Delisting or a dead market" and its "Solvency at
        the penalised price"; spec "Data", the funding-month close when no bar comes).

        * The members (``_synthetic_legs``) are every held leg ``DeadMarkets.due(h)`` lists, and
          at 00:00 of a month's first day every held futures leg whose coin's funding month is
          not ``complete``: its funding-month exit found no perpetual bar before the month.
        * One liquidation check values every closing leg at ``penalised_price`` of its last close
          (the last close before ``h``; 10% against the leg) and every other held leg at its
          mark for ``h``, all at once. A liquidation there ends the cell with no fill.
        * Otherwise every close is booked together, stamped ``h``: the whole leg, dust included,
          whatever the filters say, at the penalised price with no slippage and the venue's fee
          on that notional (``_book_synthetic``).
        * Then, per coin: the lifecycle batch, reason ``delisting`` if any of the coin's closes
          is a dead market, else ``funding-month exit`` (``_close_batch`` forgets the closed
          legs), and the arm's own consequences (``_after_synthetic_close``: a dead-market
          close cancels the coin's pending orders, before this hour's decision).
        * Equity at or below zero after the batch ends the cell as liquidated."""
        closing = self._synthetic_legs(h)
        if not closing:
            return
        held = self._ledger.positions()
        prices = {key: self._open_price(key) for key in held}
        lasts: dict[_Key, Decimal] = {}
        for key in closing:
            last = self._stores[key].last_close_before(h)
            if last is None:
                raise ValueError(f"the {key[0]} leg {key[1]} has no close before {h}")
            lasts[key] = last
            prices[key] = penalised_price(last, 1 if held[key] > 0 else -1)
        mark = self._ledger.mark(prices)
        order = sorted(closing, key=self._leg_order)
        self._record(
            "event",
            {
                "type": "synthetic_closes",
                "hour_ms": h,
                "coin": None,
                "legs": [
                    {
                        "coin": self._coin_of[key],
                        "venue": key[0],
                        "symbol": key[1],
                        "held": held[key],
                        "last_close": lasts[key],
                        "price": prices[key],
                        "reason": closing[key],
                    }
                    for key in order
                ],
                "mark": _mark_record(mark),
            },
        )
        if liquidated(mark):
            self._stop_at(LIQUIDATED, None, "synthetic_closes", prices, mark)
            return
        self._prices = dict(prices)
        batches: dict[str, list[tuple[Fill, Decimal]]] = {}
        for key in order:
            coin = self._coin_of[key]
            booked = self._book_synthetic(h, coin, key, held[key], prices[key], closing[key])
            batches.setdefault(coin, []).append(booked)
        for coin in sorted(batches):
            closed = {key: (closing[key], held[key]) for key in order if self._coin_of[key] == coin}
            reasons = {reason for reason, _ in closed.values()}
            self._close_batch(
                h, coin, batches[coin], DELISTING if DELISTING in reasons else FUNDING_EXIT
            )
            self._after_synthetic_close(h, coin, closed)
        after = self._ledger.mark(self._prices)
        if after.equity <= 0:
            self._stop_at(LIQUIDATED, None, "synthetic_closes_booked", self._prices, after)

    def _synthetic_legs(self, h: int) -> dict[_Key, str]:
        """The legs to close synthetically at ``h``, each with its reason. ``DeadMarkets.due`` is
        asked here, once an hour and before any of the hour's observations, and only its held
        legs are taken (a flat leg is never closed). A futures leg held at 00:00 of a month's
        first day closes when its coin's funding status for the month is anything but
        ``complete`` (a missing status included, as at the decision before it). A leg due on
        both counts closes as a delisting."""
        held = self._ledger.positions()
        closing = {key: DELISTING for key in self._dead.due(h) if key in held}
        if h % DAY_MS == 0 and _month_of(h) != _month_of(h - DAY_MS):
            month = _month_of(h)
            for key in held:
                if (
                    key[0] == "futures"
                    and key not in closing
                    and self.market.funding_month(self._coin_of[key], month) != COMPLETE
                ):
                    closing[key] = FUNDING_EXIT
        return closing

    def _book_synthetic(
        self, h: int, coin: str, key: _Key, held: Decimal, price: Decimal, reason: str
    ) -> tuple[Fill, Decimal]:
        """Book one synthetic close: the whole ``held`` quantity, with no filter, at the
        penalised ``price`` and no slippage (the penalty replaces it), paying the venue's fee on
        that notional, stamped at the hour's open."""
        venue, symbol = key
        quantity = held.copy_abs()
        charged = fee(quantity, price, self._costs[venue])
        booked = Fill(h, venue, symbol, -1 if held > 0 else 1, quantity, price, charged, reason)
        realised = self._ledger.fill(booked)
        self._fill_record(h, coin, booked, price, realised)
        return booked, realised

    def _after_synthetic_close(
        self, h: int, coin: str, closed: Mapping[_Key, tuple[str, Decimal]]
    ) -> None:
        """What an arm does after the coin's synthetic closes at ``h`` (``closed`` maps each leg
        to its reason and the quantity it held). The base account has no pending orders."""

    def _open_mark(self, h: int) -> None:
        """Step 2: the open mark, kept in ``open_marks``, then the pre-fill liquidation check."""
        held = self._ledger.positions()
        prices = {key: self._open_price(key) for key in held}
        complete = all(self._bars[key] is not None for key in held)
        mark = self._ledger.mark(prices)
        self._prices = prices
        self._open = (mark, complete)
        self._equity = mark.equity
        self._open_marks.append((h, mark.equity, complete))
        if h == EQUITY_2025_MS:
            self._equity_2025 = mark.equity
        self._mark_lifecycles(h, held, prices)
        if liquidated(mark):
            self._stop_at(LIQUIDATED, None, "open_mark", prices, mark)

    def _window_end(self, h: int) -> None:
        """At the last hour, after its other events (spec "Window end"): every position closes
        at the hour's close, or at its carried mark, the last close before the hour, when its
        venue has no bar then, with the cell's slippage and fees, stamped at the hour's last
        millisecond. Spot sells through ``plan_leg`` with a target of 0, so an unsellable
        remainder stays as dust (no synthetic sale); futures close exactly their quantity
        (reduce-only). Every held coin's batch then goes to its lifecycle with the reason
        ``window end``, fills or none, so the dust flag is judged at the close. The lifecycles
        still open (dust) are marked at the close prices and censored, a dust-only one as
        ``window end (dust)``. ``self._prices`` becomes the close prices, so the hour's audit,
        its ``hourly`` record and ``final_after_close`` are taken after the close."""
        held = self._ledger.positions()
        if not held:
            return
        closes = {key: self._close_price(key) for key in held}
        self._prices = dict(closes)
        stamp = h + HOUR_MS - 1
        batches: dict[str, list[tuple[Fill, Decimal]]] = {self._coin_of[key]: [] for key in held}
        for key in sorted(held, key=self._leg_order):
            coin = self._coin_of[key]
            plan = plan_leg(key[0], held[key], _ZERO, closes[key], self._rules[key])
            for order in plan.orders:
                batches[coin].append(
                    self._book_fill(h, stamp, coin, key, order, closes[key], WINDOW_END)
                )
        for coin in sorted(batches):
            self._close_batch(h, coin, batches[coin], WINDOW_END)
        self._mark_lifecycles(h, self._ledger.positions(), closes)
        for lifecycle in self._lifecycles.censor(h, WINDOW_END):
            self._record("lifecycle", _lifecycle_record(lifecycle))

    def _close_price(self, key: _Key) -> Decimal:
        """The leg's close in this hour, or its carried mark, the last close before the hour."""
        bar = self._bar(key)
        if bar is not None:
            return bar.close
        carried = self._stores[key].last_close_before(self._hour_ms)
        if carried is None:
            raise ValueError(f"the {key[0]} leg {key[1]} has no bar and no close before it")
        return carried

    def _end_hour(self, h: int) -> bool:
        """Step 8 and the hour's records: the audit, the ``hourly`` record and, if the cell
        ends at ``h``, the ``outcome`` record. Returns whether it ended."""
        audit = self._ledger.audit(self._prices)
        mark = self._ledger.mark(self._prices)
        self._audit = audit
        self._equity = mark.equity
        self._record("hourly", _hourly_record(h, self._open, mark, audit))
        failure = _audit_failure(audit)
        if failure is not None:
            self._finish("accounting_failure", failure, h, {"values": _audit_record(audit)})
            return True
        if self._stop is not None:
            self._finish_stop(h, self._stop)
            return True
        if h == self.market.window_end_ms:
            self._final_after_close = mark.equity
            self._finish("complete", None, None, {})
            return True
        return False

    # ---- prices --------------------------------------------------------------------------

    def _bar(self, key: _Key) -> HourBar | None:
        """The leg's venue bar at this hour, or None if the hour is masked (looked up once)."""
        if key in self._bars:
            return self._bars[key]
        bar = self._stores[key].bar(self._hour_ms)
        self._bars[key] = bar
        return bar

    def _open_price(self, key: _Key) -> Decimal:
        """The leg's open at this hour, or its carried mark, the last close before the hour."""
        bar = self._bar(key)
        if bar is not None:
            return bar.open
        carried = self._stores[key].last_close_before(self._hour_ms)
        if carried is None:
            raise ValueError(f"the {key[0]} leg {key[1]} has no bar and no close before it")
        self._carried[key] = carried
        return carried

    def _held_coins(self) -> frozenset[str]:
        return frozenset(self._coin_of[key] for key in self._ledger.positions())

    def _mark_lifecycles(
        self, h: int, held: Mapping[_Key, Decimal], prices: Mapping[_Key, Decimal]
    ) -> None:
        """Mark each held coin's lifecycle with its unrealised P&L over both venues, summed
        exactly."""
        totals: dict[str, Fraction] = {}
        for venue, symbol in held:
            coin = self._coin_of[venue, symbol]
            value = to_fraction(self._ledger.unrealised(venue, symbol, prices[venue, symbol]))
            totals[coin] = totals.get(coin, Fraction(0)) + value
        for coin in sorted(totals):
            self._lifecycles.mark(h, coin, to_decimal(totals[coin]))

    # ---- the account: legs, fills, batches and dead markets (shared with the hold arms) ----

    def _key(self, coin: str, venue: Venue) -> _Key:
        """The ledger key of the coin's leg on ``venue``: its spot symbol, or its perpetual's."""
        if venue == "spot":
            return ("spot", coin)
        perpetual = self.market.coin(coin).perpetual
        if perpetual is None:
            raise ValueError(f"{coin} has no perpetual, so it has no futures leg")
        return ("futures", perpetual.symbol)

    def _legs(self, coin: str) -> tuple[_Key, ...]:
        """The coin's ledger keys, spot first."""
        perpetual = self.market.coin(coin).perpetual
        if perpetual is None:
            return (("spot", coin),)
        return (("spot", coin), ("futures", perpetual.symbol))

    def _leg_order(self, key: _Key) -> tuple[str, bool]:
        """Alphabetical by the coin's spot symbol, its spot leg before its futures leg."""
        return self._coin_of[key], key[0] != "spot"

    def _fill_open(self, key: _Key) -> Decimal:
        """The leg's bar open at this hour, the unslipped price of a fill there. A leg without
        a bar cannot trade (spec "Missing or stale data"), so asking is an engine error."""
        bar = self._bar(key)
        if bar is None:
            raise RuntimeError(
                f"the {key[0]} leg {key[1]} has no bar at {self._hour_ms}, so it cannot trade"
            )
        return bar.open

    def _dust(self, coin: str, price: Decimal) -> Decimal:
        """The coin's spot dust at ``price``: its whole spot holding when ``plan_leg`` cannot
        sell it (below the minimum quantity or notional, spec "Reductions are never refused for
        size"), else 0 (controller ruling, Task 12)."""
        held = self._ledger.quantity("spot", coin)
        if held == 0:
            return _ZERO
        sale = plan_leg("spot", held, _ZERO, price, self._rules["spot", coin])
        return _ZERO if sale.orders else held

    def _book_fill(
        self,
        h: int,
        timestamp_ms: int,
        coin: str,
        key: _Key,
        order: Order,
        price: Decimal,
        reason: str,
    ) -> tuple[Fill, Decimal]:
        """Book one order at the unslipped ``price`` moved by the cell's slippage, with the
        venue's fee on its own notional, write its ``fill`` record, and price the leg at
        ``price`` for the rest of the hour (``Ledger.mark`` and ``audit`` refuse an unpriced
        leg). Returns the fill and its realised P&L."""
        venue, symbol = key
        costs = self._costs[venue]
        paid = fill_price(price, order.side, costs)
        charged = fee(order.quantity, paid, costs)
        booked = Fill(
            timestamp_ms, venue, symbol, order.side, order.quantity, paid, charged, reason
        )
        realised = self._ledger.fill(booked)
        self._prices[key] = price
        self._fill_record(h, coin, booked, price, realised)
        return booked, realised

    def _fill_record(
        self, h: int, coin: str, booked: Fill, unslipped: Decimal, realised: Decimal
    ) -> None:
        self._record(
            "fill",
            {
                "hour_ms": h,
                "timestamp_ms": booked.timestamp_ms,
                "coin": coin,
                "venue": booked.venue,
                "symbol": booked.symbol,
                "side": booked.side,
                "quantity": booked.quantity,
                "price": booked.price,
                "unslipped_price": unslipped,
                "fee": booked.fee,
                "realised": realised,
                "reason": booked.reason,
            },
        )

    def _initial_margin(self) -> Decimal:
        """The open futures positions' initial margin, ``sum |quantity x price| / 3`` at this
        hour's marking prices, rounded up to the engine's precision, never down."""
        total = sum(
            (
                abs(to_fraction(quantity) * to_fraction(self._prices[key]))
                for key, quantity in self._ledger.positions().items()
                if key[0] == "futures"
            ),
            Fraction(0),
        )
        return _CEILING.divide(to_decimal(total), Decimal(INITIAL_MARGIN_DIVISOR))

    def _book_increase(
        self,
        h: int,
        coin: str,
        key: _Key,
        orders: Sequence[Order],
        price: Decimal,
        reason: str,
    ) -> list[tuple[Fill, Decimal]]:
        """Clip one increase (spec "Cash clip") on the account as it is now, after every earlier
        real fill of the batch (controller ruling, Task 8: one increase at a time), then book
        it: whole if it fits; otherwise the admitted notional is re-planned with ``plan_leg``
        from the held quantity, so the step and the filters apply, and the cut is recorded as
        an ``increase_cut`` event (an increase cut below the filters is skipped)."""
        venue, symbol = key
        side = orders[0].side
        quantity = sum((to_fraction(order.quantity) for order in orders), Fraction(0))
        wanted = to_decimal(side * quantity * to_fraction(price))
        mark = self._ledger.mark(self._prices)
        ((_, _, admitted),) = clip_increases(
            [(coin, venue, wanted)],
            self._ledger.cash,
            self._initial_margin(),
            mark.backing,
            mark.maintenance,
            self._costs,
        )
        booked: Sequence[Order] = orders
        if admitted != wanted:
            held = self._ledger.quantity(venue, symbol)
            change = to_venue_quantity(admitted, price)
            target = to_decimal(to_fraction(held) + to_fraction(change))
            plan = plan_leg(venue, held, target, price, self._rules[key])
            if any(order.reduce_only for order in plan.orders):
                raise RuntimeError(f"a cut increase of {coin} on {venue} would reduce the leg")
            booked = plan.orders
            refusal = plan.refusal
            if refusal is None and not booked:
                refusal = "cash"
            self._record(
                "event",
                {
                    "type": "increase_cut",
                    "hour_ms": h,
                    "coin": coin,
                    "venue": venue,
                    "symbol": symbol,
                    "wanted": wanted,
                    "admitted": admitted,
                    "quantity": to_decimal(
                        sum((to_fraction(order.quantity) for order in booked), Fraction(0))
                    ),
                    "refusal": refusal,
                },
            )
        return [self._book_fill(h, h, coin, key, order, price, reason) for order in booked]

    def _close_batch(
        self, h: int, coin: str, fills: Sequence[tuple[Fill, Decimal]], reason: str
    ) -> None:
        """After one batch of the coin's fills (spec "Records", per trade lifecycle):
        ``Lifecycles.after_batch`` with the legs left and their signed notional at this hour's
        marking prices, the ``lifecycle`` record of a lifecycle it ended, and
        ``DeadMarkets.forget`` for each leg now flat. ``dust_only`` holds only with spot held,
        futures flat and that spot unsellable."""
        legs = self._legs(coin)
        spot_key = legs[0]
        spot = self._ledger.quantity(*spot_key)
        futures = _ZERO
        notional = Fraction(0)
        if spot:
            notional += to_fraction(spot) * to_fraction(self._prices[spot_key])
        for key in legs[1:]:
            futures = self._ledger.quantity(*key)
            if futures:
                notional += to_fraction(futures) * to_fraction(self._prices[key])
        dust_only = spot > 0 and futures == 0 and self._dust(coin, self._prices[spot_key]) == spot
        ended = self._lifecycles.after_batch(
            h, coin, to_decimal(notional), spot, futures, dust_only, fills, reason
        )
        if ended is not None:
            self._record("lifecycle", _lifecycle_record(ended))
        for key in legs:
            if self._ledger.quantity(*key) == 0:
                self._dead.forget(*key)

    def _observe_markets(self, h: int) -> None:
        """Tell ``DeadMarkets`` whether each leg held at the end of the hour had a bar on its
        own venue in it, once per leg and hour (spec "Delisting or a dead market").
        ``_synthetic_legs`` asks ``due`` for the hour in step 1, before this."""
        for venue, symbol in self._ledger.positions():
            self._dead.observe(h, venue, symbol, self._bar((venue, symbol)) is not None)

    # ---- steps 5 to 7: the limits after the fills and after funding, the adverse extremes --

    def _post_fill(self, h: int) -> None:
        """Step 5: the post-fill mark, then its liquidation, cushion and ceiling checks, each cut
        filling at this open (``_limits``)."""
        self._limits(h, "post_fill", h)

    def _funding_events(self, h: int) -> None:
        """Step 6 (spec "Shorts on futures"): each funding record of the hour, in time order, on
        the positions then held. A flat leg (one closed by a synthetic close at this instant
        included) is not charged. A held perpetual pays ``-contracts x rate x price``: the
        signed contracts held, the published rate, and the perpetual's open at this hour, or
        its carried mark when the hour is masked, so a long pays a positive rate and a short
        receives it. Each payment goes to the wallet and the coin's lifecycle, and is followed
        by a mark and the checks of ``_limits``, whose cuts fill at this hour's open and are
        stamped at the record's time, so the account's clock never runs back."""
        for perpetual, time_ms, rate in self.market.funding_events(h):
            key: _Key = ("futures", perpetual)
            quantity = self._ledger.quantity("futures", perpetual)
            if quantity == 0:
                continue
            coin = self._coin_of[key]
            price = self._open_price(key)
            amount = to_decimal(-to_fraction(quantity) * to_fraction(rate) * to_fraction(price))
            self._ledger.funding(time_ms, perpetual, amount)
            self._lifecycles.funding(coin, amount)
            self._record(
                "funding",
                {
                    "hour_ms": h,
                    "timestamp_ms": time_ms,
                    "coin": coin,
                    "perpetual": perpetual,
                    "quantity": quantity,
                    "rate": rate,
                    "price": price,
                    "carried": self._bar(key) is None,
                    "amount": amount,
                },
            )
            self._limits(h, "funding", time_ms)
            if self._stop is not None:
                return

    def _adverse_extremes(self, h: int) -> None:
        """Step 7 (spec "Safety", liquidation): every held leg at its bar's extreme against it at
        once (``adverse_prices``: a long, spot included, at its low, a short at its high, a
        masked leg at its carried mark). Backing at or below maintenance there ends the cell at
        those prices. With no futures leg there is no maintenance, so nothing to check."""
        held = self._ledger.positions()
        if not any(venue == "futures" for venue, _ in held):
            return
        bars = {key: self._bar(key) for key in held}
        carried = {key: self._prices[key] for key in held if bars[key] is None}
        prices = adverse_prices(held, bars, carried)
        mark = self._ledger.mark(prices)
        if liquidated(mark):
            self._stop_at(LIQUIDATED, None, "adverse_extremes", prices, mark)

    def _limits(self, h: int, point: str, stamp: int) -> None:
        """The checks at one point of the hour (``post_fill``, or ``funding`` after a funding
        record), in the spec's order: a mark at this hour's marking prices and its liquidation
        check, then the margin cushion and its cut, then the 3x ceiling and its cut, the
        ceiling judged on the mark after the cushion's cut. ``stamp`` is the time the cuts'
        fills carry. Thresholds compare the marks' exact values (``safety``)."""
        mark = self._ledger.mark(self._prices)
        if liquidated(mark):
            self._stop_at(LIQUIDATED, None, point, self._prices, mark)
            return
        if cushion_breached(mark):
            mark = self._margin_cut(h, point, stamp, mark)
            if self._stop is not None:
                return
        if ceiling_breached(mark):
            self._ceiling_cut(h, point, stamp, mark)

    def _margin_cut(self, h: int, point: str, stamp: int, mark: Mark) -> Mark:
        """The cushion's cut (spec "Safety", margin cushion): the tradable futures legs (a bar at
        this hour) shrink to ``held x k``, ``k = cushion_factor(backing, untradable maintenance,
        tradable maintenance)``, by reduce-only orders at this open with slippage and fees,
        lifecycle reason ``margin cut``. With no tradable futures leg, or a ratio still below 3
        at the new mark, the cell ends ``limit_unrestorable`` with reason ``margin_cushion``.
        Returns the new mark (the old one when nothing could be cut)."""
        tradable: list[_Key] = []
        untradable: list[_Key] = []
        tradable_maintenance = untradable_maintenance = Fraction(0)
        for key, quantity in self._ledger.positions().items():
            if key[0] != "futures":
                continue
            value = _MAINTENANCE * abs(to_fraction(quantity) * to_fraction(self._prices[key]))
            if self._bar(key) is None:
                untradable.append(key)
                untradable_maintenance += value
            else:
                tradable.append(key)
                tradable_maintenance += value
        factor = cushion_factor(
            mark.backing, to_decimal(untradable_maintenance), to_decimal(tradable_maintenance)
        )
        legs = self._cut_legs(tradable, factor, MARGIN_CUT)
        self._record(
            "event",
            {
                "type": "margin_cut",
                "hour_ms": h,
                "coin": None,
                "check": point,
                "timestamp_ms": stamp,
                "backing": mark.backing,
                "untradable_maintenance": to_decimal(untradable_maintenance),
                "tradable_maintenance": to_decimal(tradable_maintenance),
                "factor": factor,
                "untradable": [list(key) for key in sorted(untradable, key=self._leg_order)],
                "legs": [_cut_leg_record(leg) for leg in legs],
            },
        )
        if factor is None:
            self._stop_at(LIMIT_UNRESTORABLE, MARGIN_CUSHION, point, self._prices, mark)
            return mark
        after = self._book_cut(h, stamp, legs, MARGIN_CUT)
        check = f"{point}_margin_cut"
        if liquidated(after):
            self._stop_at(LIQUIDATED, None, check, self._prices, after)
        elif cushion_breached(after):
            self._stop_at(LIMIT_UNRESTORABLE, MARGIN_CUSHION, check, self._prices, after)
        return after

    def _ceiling_cut(self, h: int, point: str, stamp: int, mark: Mark) -> None:
        """The 3x ceiling's cut (spec "Safety", the 3x ceiling): every tradable position, a spot
        leg by a sale and a futures leg by a reduce-only order, shrinks to ``held x k'``, ``k' =
        ceiling_factor(equity, untradable gross, tradable gross)``, at this open with slippage
        and fees, lifecycle reason ``ceiling cut``. Untradable are the legs without a bar at
        this hour and unsellable spot dust; a spot remainder the cut leaves below the filters
        becomes dust. With nothing tradable, or gross still above 3 at the new mark, the cell
        ends ``limit_unrestorable`` with reason ``ceiling``."""
        tradable: list[_Key] = []
        untradable: list[_Key] = []
        tradable_gross = untradable_gross = Fraction(0)
        for key, quantity in self._ledger.positions().items():
            price = self._prices[key]
            value = abs(to_fraction(quantity) * to_fraction(price))
            dust = key[0] == "spot" and self._dust(key[1], price) > 0
            if self._bar(key) is None or dust:
                untradable.append(key)
                untradable_gross += value
            else:
                tradable.append(key)
                tradable_gross += value
        factor = ceiling_factor(
            mark.equity, to_decimal(untradable_gross), to_decimal(tradable_gross)
        )
        legs = self._cut_legs(tradable, factor, CEILING_CUT)
        self._record(
            "event",
            {
                "type": "ceiling_cut",
                "hour_ms": h,
                "coin": None,
                "check": point,
                "timestamp_ms": stamp,
                "equity": mark.equity,
                "untradable_gross": to_decimal(untradable_gross),
                "tradable_gross": to_decimal(tradable_gross),
                "factor": factor,
                "untradable": [list(key) for key in sorted(untradable, key=self._leg_order)],
                "legs": [_cut_leg_record(leg) for leg in legs],
            },
        )
        if factor is None:
            self._stop_at(LIMIT_UNRESTORABLE, CEILING, point, self._prices, mark)
            return
        after = self._book_cut(h, stamp, legs, CEILING_CUT)
        check = f"{point}_ceiling_cut"
        if liquidated(after):
            self._stop_at(LIQUIDATED, None, check, self._prices, after)
        elif ceiling_breached(after):
            self._stop_at(LIMIT_UNRESTORABLE, CEILING, check, self._prices, after)

    def _cut_legs(self, keys: Sequence[_Key], factor: Decimal | None, reason: str) -> list[_Leg]:
        """The plans of a cut: each tradable leg to ``_cut_quantity(held, factor)`` at this
        hour's open, in coin order, spot first. None for ``factor`` (nothing tradable) plans
        nothing. Every order is a reduction."""
        if factor is None:
            return []
        legs: list[_Leg] = []
        for key in sorted(keys, key=self._leg_order):
            held = self._ledger.quantity(*key)
            price = self._fill_open(key)
            rules = self._rules[key]
            target = _cut_quantity(held, factor, rules.step)
            plan = plan_leg(key[0], held, target, price, rules)
            if not all(order.reduce_only for order in plan.orders):
                raise RuntimeError(f"a {reason} of the {key[0]} leg {key[1]} would increase it")
            legs.append(_Leg(self._coin_of[key], key, price, held, target, plan, reason))
        return legs

    def _book_cut(self, h: int, stamp: int, legs: Sequence[_Leg], reason: str) -> Mark:
        """Book a cut's orders (all reductions) at their open, stamped ``stamp``, then one
        lifecycle batch per coin with ``reason``; returns the new mark."""
        batches: dict[str, list[tuple[Fill, Decimal]]] = {}
        for leg in legs:
            for order in leg.plan.orders:
                booked = self._book_fill(h, stamp, leg.coin, leg.key, order, leg.price, reason)
                batches.setdefault(leg.coin, []).append(booked)
        for coin in sorted(batches):
            self._close_batch(h, coin, batches[coin], reason)
        return self._ledger.mark(self._prices)

    # ---- stops and outcomes --------------------------------------------------------------

    def _stop_at(
        self,
        outcome: str,
        reason: str | None,
        check: str,
        prices: Mapping[_Key, Decimal],
        mark: Mark,
    ) -> None:
        """End the cell at this hour (spec "Safety", how a cell that stops early ends): no later
        event; the end of the hour marks at the stopping check's ``prices``."""
        self._stop = _Stop(outcome, reason, check, MappingProxyType(dict(prices)), mark)
        self._prices = dict(prices)

    def _finish_stop(self, h: int, stop: _Stop) -> None:
        """Mark every open lifecycle at the stop's prices, censor them with the outcome, and
        write the outcome; the stop's mark is the final equity."""
        self._mark_lifecycles(h, self._ledger.positions(), stop.prices)
        reason = "liquidation" if stop.outcome == LIQUIDATED else LIMIT_UNRESTORABLE
        for lifecycle in self._lifecycles.censor(h, reason):
            self._record("lifecycle", _lifecycle_record(lifecycle))
        self._equity = stop.mark.equity
        self._finish(
            stop.outcome, stop.reason, h, {"check": stop.check, "mark": _mark_record(stop.mark)}
        )

    def _finish(
        self, outcome: str, reason: str | None, stop_ms: int | None, extra: Mapping[str, object]
    ) -> None:
        """Write the one ``outcome`` record; only once it is written is the outcome set."""
        self._record(
            "outcome",
            {
                "outcome": outcome,
                "reason": reason,
                "stop_ms": stop_ms,
                "hours": len(self._open_marks),
                "final_equity": self._equity,
                "equity_2025": self._equity_2025,
                "final_after_close": self._final_after_close,
                "audit": _audit_record(self._audit),
                **extra,
            },
        )
        self._outcome, self._reason, self._stop_ms = outcome, reason, stop_ms

    def _record(self, kind: str, record: Mapping[str, object]) -> None:
        if self._writer is None:
            raise RuntimeError("the cell has no record writer")
        self._writer.append(kind, record)


@dataclass(frozen=True, slots=True)
class _CoinView:
    """One decided coin at one 00:00 decision: its reading and the facts the decision used."""

    coin: str
    reading: SignalReading | None
    has_bar: bool
    in_universe: bool
    perpetual: str | None
    point_in_time: bool
    next_month: str | None
    next_status: str | None
    eligible: bool
    funding_exit: bool
    signal: Decimal

    @property
    def universe_exit(self) -> bool:
        return not self.in_universe


@dataclass(frozen=True, slots=True)
class _Holding:
    """One coin's legs at the fill hour, quantities in venue units and notionals at the
    marking prices: the spot holding with its ``dust`` (the whole holding, or 0), and the signed
    futures leg on ``futures_key`` (None without a perpetual)."""

    spot: Decimal
    dust: Decimal
    futures: Decimal
    futures_key: _Key | None
    spot_notional: Decimal  # dust excluded
    dust_notional: Decimal
    futures_notional: Decimal

    def state(
        self,
        coin: str,
        target_notional: Decimal,
        eligible: bool,
        keeps_legs: bool,
        exiting: frozenset[Venue] = frozenset(),
    ) -> CoinState:
        return CoinState(
            coin,
            target_notional,
            self.spot_notional,
            self.dust_notional,
            self.futures_notional,
            eligible,
            keeps_legs,
            exiting,
        )


@dataclass(frozen=True, slots=True)
class _Leg:
    """One leg's plan in an hour's batch: its unslipped fill price, the held quantity, the
    target quantity, the orders and the reason its fills carry."""

    coin: str
    key: _Key
    price: Decimal
    held: Decimal
    target: Decimal
    plan: LegPlan
    reason: str


class _V4Cell(_CellState):
    """A V4 arm's cell: the signals, the pending book and the 00:00 decision, on the shared
    account of ``_CellState``."""

    def __init__(
        self,
        market: Market,
        cell: CellSpec,
        arm: ArmSpec,
        vol_target: Decimal,
        lookbacks: Lookbacks,
    ) -> None:
        super().__init__(market, cell)
        self.arm = arm
        self._vol_target = vol_target
        self._lookbacks = lookbacks
        self._book = PendingBook()
        self._universe: tuple[str, ...] = ()
        # Per coin, built on its first decision: daily bars, signal state, returns, cursors.
        self._daily: dict[str, tuple[Kline, ...]] = {}
        self._fed: dict[str, int] = {}  # how many daily bars the signal state has seen
        self._signals: dict[str, CoinSignals] = {}
        self._readings: dict[str, SignalReading] = {}
        self._returns: dict[str, tuple[DailyReturn, ...]] = {}
        self._return_days: dict[str, list[int]] = {}
        # The latest decision's answers, for the fill phase. A coin's pending order always holds
        # its latest target, since the decision that gave the target made the order.
        self._targets: dict[str, Decimal] = {}  # each coin's latest target
        self._target_ms: dict[str, int] = {}  # the decision hour of each coin's latest target
        self._eligible: dict[str, bool] = {}  # each decided coin's eligibility, as decided

    def _hour(self, h: int) -> None:
        phases: tuple[Callable[[int], None], ...] = (
            self._synthetic_closes,
            self._open_mark,
            self._decide,
            self._fills,
            self._post_fill,
            self._funding_events,
            self._adverse_extremes,
            self._observe_markets,
        )
        for phase in phases:
            phase(h)
            if self._stop is not None:
                return

    # ---- step 3: the 00:00 decision ------------------------------------------------------

    def _decide(self, h: int) -> None:
        """Step 3, at 00:00 only: the month's universe and ``monthly`` record on its first day,
        then the decision for every decided coin (module docstring), ``PendingBook.decide`` and
        a ``daily_coin`` record per coin."""
        if h % DAY_MS:
            return
        day = h - DAY_MS
        month = _month_of(h)
        left: tuple[str, ...] = ()
        if month != _month_of(day):
            previous, self._universe = self._universe, self.market.universe(month)
            left = tuple(coin for coin in previous if coin not in self._universe)
            self._record("monthly", self._monthly_record(h, month, previous))
        universe = frozenset(self._universe)
        # Spec "Universe", leaving the top 10: a coin that left gets a target of 0 at the month's
        # first decision, held or not, so that no order made before it left can still fill.
        decided = sorted(universe | self._held_coins() | frozenset(left))
        month_end = _month_end(h, self.market.end_month)
        views = {coin: self._view(coin, h, day, universe, month_end) for coin in decided}
        sizing = size_book(
            {coin: view.signal for coin, view in views.items()},
            {coin: self._trailing_returns(coin, day) for coin in decided},
            day,
            vol_target=self._vol_target,
        )
        targets: dict[str, Decimal] = {}
        for coin, view in views.items():
            if view.universe_exit:
                targets[coin] = _ZERO  # overrides the no-bar rule
            elif view.has_bar:
                targets[coin] = sizing.weights[coin]
        self._record_superseded(h, self._book.decide(h, targets))
        self._targets.update(targets)
        self._target_ms.update(dict.fromkeys(targets, h))
        self._eligible.update({coin: view.eligible for coin, view in views.items()})
        self._mandatory_exits(h, views)
        for coin in decided:
            self._record(
                "daily_coin",
                _daily_record(h, day, views[coin], sizing, sizing.coins[coin], targets.get(coin)),
            )

    def _view(
        self, coin: str, h: int, day: int, universe: frozenset[str], month_end: str | None
    ) -> _CoinView:
        reading = self._feed(coin, day)
        perpetual = self.market.coin(coin).perpetual
        point_in_time = self.market.perpetual_eligible(coin, h)
        next_status: str | None = None
        blocked = False
        if perpetual is not None and month_end is not None:
            next_status = self.market.funding_month(coin, month_end)
            blocked = next_status != COMPLETE  # a missing status is not complete either
        eligible = point_in_time and not blocked
        holds_futures = (
            perpetual is not None and self._ledger.quantity("futures", perpetual.symbol) != 0
        )
        in_universe = coin in universe
        s = _ZERO
        if reading is not None:
            s = reading.s_long_only if self.arm.long_only else reading.s
        used = s if eligible else max(s, _ZERO)  # spot-only coins are long-only
        return _CoinView(
            coin=coin,
            reading=reading,
            has_bar=reading is not None and reading.day_ms == day,
            in_universe=in_universe,
            perpetual=None if perpetual is None else perpetual.symbol,
            point_in_time=point_in_time,
            next_month=None if perpetual is None else month_end,
            next_status=next_status,
            eligible=eligible,
            funding_exit=blocked and holds_futures,
            signal=used if in_universe else _ZERO,
        )

    def _feed(self, coin: str, day: int) -> SignalReading | None:
        """Feed the coin's signal state every daily bar up to ``day`` it has not seen, never a
        later one, and return its latest reading (None before its first bar)."""
        if coin not in self._signals:
            bars = self.market.daily(coin)
            returns = daily_returns(bars)
            self._daily[coin] = bars
            self._fed[coin] = 0
            self._signals[coin] = CoinSignals(self._lookbacks)
            self._returns[coin] = returns
            self._return_days[coin] = [row.day_ms for row in returns]
        bars, index, signals = self._daily[coin], self._fed[coin], self._signals[coin]
        while index < len(bars) and bars[index].open_ms <= day:
            self._readings[coin] = signals.update(bars[index])
            index += 1
        self._fed[coin] = index
        return self._readings.get(coin)

    def _trailing_returns(self, coin: str, day: int) -> tuple[DailyReturn, ...]:
        """The coin's last returns at or before ``day``: all ``size_book`` reads (see above)."""
        end = bisect_right(self._return_days[coin], day)
        return self._returns[coin][max(0, end - _RETURN_WINDOW) : end]

    def _mandatory_exits(self, h: int, views: Mapping[str, _CoinView]) -> None:
        """After ``decide``, in the pending book's call order: for each universe exit and each
        funding-month exit (``view.funding_exit``) the coin's pending order and replacement buy
        are cancelled (this drops the decision's own order for the coin), then each leg the exit
        closes is scheduled from ``h + 1 h`` (spec "Sizing", mandatory exits): every held leg
        for a universe exit, the futures leg for a funding-month exit. A universe exit takes
        precedence when both apply, and a leg whose exit is already scheduled keeps it."""
        for coin in sorted(views):
            view = views[coin]
            venues: tuple[Venue, ...]
            if view.universe_exit:
                reason = UNIVERSE_EXIT
                venues = tuple(key[0] for key in self._legs(coin) if self._ledger.quantity(*key))
            elif view.funding_exit:
                reason, venues = FUNDING_EXIT, ("futures",)
            else:
                continue
            self._cancel(h, coin, reason)
            for venue in venues:
                if self._book.exit_scheduled(coin, venue):
                    continue
                self._book.schedule_exit(Exit(coin, venue, reason, h + HOUR_MS))
                self._record(
                    "event",
                    {
                        "type": "exit_scheduled",
                        "hour_ms": h,
                        "coin": coin,
                        "venue": venue,
                        "reason": reason,
                        "after_ms": h + HOUR_MS,
                    },
                )

    def _cancel(self, h: int, coin: str, reason: str) -> None:
        """``PendingBook.cancel(coin)``, recording the order and the replacement it removed (the
        book's ``replacement_pending`` says whether there was one). The cancels are those of a
        universe exit and a funding-month exit, after the decision of their hour, and of a
        dead-market close, before it (``_after_synthetic_close``)."""
        replacing = self._book.replacement_pending(coin)
        order = self._book.cancel(coin)
        if order is not None:
            self._record(
                "event",
                {
                    "type": "order_cancelled",
                    "hour_ms": h,
                    "coin": coin,
                    "decision_ms": order.decision_ms,
                    "target": order.target,
                    "reason": reason,
                },
            )
        if replacing:
            self._record(
                "event",
                {"type": "replacement_cancelled", "hour_ms": h, "coin": coin, "reason": reason},
            )

    def _after_synthetic_close(
        self, h: int, coin: str, closed: Mapping[_Key, tuple[str, Decimal]]
    ) -> None:
        """After the coin's synthetic closes at ``h`` (step 1, before this hour's decision): a
        dead-market close cancels the coin's pending order and replacement buy (spec "Pending
        orders are cancelled": the coin re-enters only through a later decision); a synthetic
        funding-month close of a long futures leg schedules the replacement spot buy from this
        hour (spec "Data": a long's target moves to spot; a short's moves to 0, so it gets
        none). The stale funding-month exit of the closed leg later comes due on a flat leg and
        is skipped. A coin with both kinds of close takes the dead market's rule only."""
        reasons = {reason for reason, _ in closed.values()}
        if DELISTING in reasons:
            self._cancel(h, coin, DELISTING)
            return
        for (venue, _), (reason, held) in closed.items():
            if venue == "futures" and reason == FUNDING_EXIT and held > 0:
                self._schedule_replacement(h, coin)

    def _record_superseded(self, h: int, decided: Decided) -> None:
        for order in decided.cancelled:
            self._record(
                "event",
                {
                    "type": "order_superseded",
                    "hour_ms": h,
                    "coin": order.coin,
                    "decision_ms": order.decision_ms,
                    "target": order.target,
                },
            )
        for coin in decided.cancelled_replacements:
            self._record("event", {"type": "replacement_superseded", "hour_ms": h, "coin": coin})

    def _monthly_record(self, h: int, month: str, previous: Sequence[str]) -> dict[str, object]:
        following = _month_of(month_bounds_ms(month)[1])
        perpetuals: list[dict[str, object]] = []
        for coin in self._universe:
            perpetual = self.market.coin(coin).perpetual
            if perpetual is not None:
                perpetuals.append(
                    {
                        "coin": coin,
                        "perpetual": perpetual.symbol,
                        "multiplier": perpetual.multiplier,
                        "status": self.market.funding_month(coin, month),
                        "next_month": following,
                        "next_status": self.market.funding_month(coin, following),
                    }
                )
        record = self.market.selection(month)
        selection = None
        if record is not None:
            selection = {
                "ranked": [[symbol, mean, bars] for symbol, mean, bars in record.ranked],
                "excluded": [[symbol, why] for symbol, why in record.excluded],
                "entered": list(record.entered),
                "left": list(record.left),
            }
        return {
            "month": month,
            "open_ms": h,
            "universe": list(self._universe),
            "entered": [coin for coin in self._universe if coin not in previous],
            "left": [coin for coin in previous if coin not in self._universe],
            "perpetuals": perpetuals,
            "selection": selection,
        }

    # ---- step 4: the fills --------------------------------------------------------------

    def _fills(self, h: int) -> None:
        """Step 4: the daily orders, mandatory exit legs and replacement buys due at ``h``, as
        one batch (spec "Longs on spot first", "Sizing" band paragraph).

        The pending book is called in its docstring's order: ``due`` (each coin asked through
        ``_ready``), ``due_exits`` (each leg on its own venue), then, for each funding-month
        close of a long futures leg about to fill, ``schedule_replacement`` at this hour (a
        short's target moves to 0, so it is not replaced), and ``due_replacements``, so a close
        and its replacement buy can share this hour's batch.
        An exit for a flat leg, or a universe exit of a coin back in the universe, is skipped
        (``_exit_skip``). With nothing due the phase ends there; otherwise ``_trade`` books the
        batch.

        Contract for the batch: deferrals are settled first (``due``), the allocation is
        computed once, the reductions fill before the increases, each alphabetical by coin and
        spot before futures, and each increase is clipped alone on the account after every
        earlier real fill. Every leg a fill opens is added to ``self._prices`` at its fill's
        unslipped open, because ``Ledger.mark`` and ``Ledger.audit`` refuse an unpriced leg.
        A futures leg is opened only for a coin eligible at its latest decision
        (``self._eligible``), never from the decision an older kept order came from."""
        orders = self._book.due(h, self._ready)
        exits = self._book.due_exits(h, self._has_bar)
        closing: dict[str, dict[Venue, str]] = {}
        for leg in exits:
            why = self._exit_skip(leg)
            if why is not None:
                self._record(
                    "event",
                    {
                        "type": "exit_skipped",
                        "hour_ms": h,
                        "coin": leg.coin,
                        "venue": leg.venue,
                        "reason": leg.reason,
                        "why": why,
                    },
                )
                continue
            closing.setdefault(leg.coin, {})[leg.venue] = leg.reason
            if (
                leg.venue == "futures"
                and leg.reason == FUNDING_EXIT
                and self._ledger.quantity(*self._key(leg.coin, "futures")) > 0
            ):
                self._schedule_replacement(h, leg.coin)  # a long's only: a short's target is 0
        replacing = self._book.due_replacements(h, self._has_spot_bar)
        if orders or closing or replacing:
            self._trade(h, orders, closing, replacing)

    def _ready(self, coin: str) -> bool:
        """Whether every venue the coin's pending order needs has its bar at this hour (spec
        "Longs on spot first", deferrals): spot if the coin holds spot or its target is long;
        the perpetual if it holds futures, its target is short, or it is long with an eligible
        perpetual (eligibility as last decided). Also the perpetual when the target is 0, the
        perpetual eligible and the coin holds dust: the order then offsets the dust with a
        futures short. That case is the spec's general rule ("if any venue the coin's order
        needs ... the coin's whole order is deferred"), which its list does not name."""
        target = self._targets[coin]  # the pending order's target (see __init__)
        spot_key: _Key = ("spot", coin)
        spot = self._ledger.quantity("spot", coin)
        if (spot > 0 or target > 0) and self._bar(spot_key) is None:
            return False
        perpetual = self.market.coin(coin).perpetual
        if perpetual is None:
            return True
        key: _Key = ("futures", perpetual.symbol)
        eligible = self._eligible.get(coin, False)
        needs = (
            self._ledger.quantity(*key) != 0
            or target < 0
            or (eligible and target > 0)
            or (
                eligible
                and target == 0
                and spot > 0
                and self._dust(coin, self._prices[spot_key]) > 0
            )
        )
        return not needs or self._bar(key) is not None

    def _has_bar(self, coin: str, venue: Venue) -> bool:
        return self._bar(self._key(coin, venue)) is not None

    def _has_spot_bar(self, coin: str) -> bool:
        return self._bar(("spot", coin)) is not None

    def _exit_skip(self, leg: Exit) -> str | None:
        """Why a due exit leg makes no trade, or None. ``flat``: the leg is already closed (by
        a signal, a cut or a synthetic close; the stale exit is a no-op). ``in_universe``: a
        universe exit of a coin that has come back into the universe since it was scheduled;
        the decisions made since then supersede it (spec "Universe": the decision uses the
        new universe)."""
        if leg.reason == UNIVERSE_EXIT and leg.coin in self._universe:
            return "in_universe"
        if self._ledger.quantity(*self._key(leg.coin, leg.venue)) == 0:
            return "flat"
        return None

    def _schedule_replacement(self, h: int, coin: str) -> None:
        """The replacement spot buy of a funding-month close of a long futures leg filling at
        ``h``, by the fill phase or by the synthetic close at a month's first midnight (spec
        "Sizing": placed at the first hour at or after the close's fill with a spot bar).
        ``schedule_replacement`` refuses it when this hour's decision gave the coin a newer
        target; that is recorded as superseded. A coin outside the universe gets none: its
        spot leg is a universe exit's to close. That guard is defensive now: a funding-month
        exit is made only for a coin in the universe, and with the synthetic close at the
        month's first midnight it can no longer be pending when the universe changes."""
        if coin not in self._universe:
            self._record(
                "event",
                {
                    "type": "replacement_skipped",
                    "hour_ms": h,
                    "coin": coin,
                    "why": "not_in_universe",
                },
            )
        elif self._book.schedule_replacement(coin, h):
            self._record("event", {"type": "replacement_scheduled", "hour_ms": h, "coin": coin})
        else:
            self._record("event", {"type": "replacement_superseded", "hour_ms": h, "coin": coin})

    def _trade(
        self,
        h: int,
        orders: Sequence[Pending],
        closing: Mapping[str, Mapping[Venue, str]],
        replacing: Sequence[str],
    ) -> None:
        """Book the hour's batch (``_fills`` gives the contract).

        * A due order's coin takes the band test: ``current`` is its signed notional over both
          venues at this hour's unslipped opens over the open mark's equity, before the fills.
          A coin the band leaves alone keeps its legs.
        * The coins that trade are the band-trading ones, with their order's target and latest
          eligibility, and the replacement buys, with the coin's latest target as spot-only
          coins. Every other held coin keeps its legs, a leg its mandatory exit closes counting
          as 0, so a coin whose exits are all due trades to 0 with no futures offset.
        * ``allocate`` runs once. A trading coin's spot leg is planned to its spot share plus
          its dust, its futures leg to its futures share, both in venue units at the opens; an
          exiting leg is planned to 0.
        * A coin never has a daily order due with one of its mandatory exits or with its
          replacement buy: the decision that makes an exit cancels the coin's order, a decision
          with a target cancels the replacement, a universe exit of a coin back in the universe
          is skipped (``_exit_skip``), and a funding-month exit still pending at a month's first
          midnight is replaced by the synthetic close then, so it comes due on a flat leg. Such
          an hour would be an engine error.
        """
        if self._open is None:
            raise RuntimeError("the fills need this hour's open mark")
        equity = self._open[0].equity
        if equity <= 0:
            raise RuntimeError(f"equity {equity} at the open of {h}: nothing can be sized")
        due = {order.coin: order for order in orders}
        for coin in due:
            if coin in replacing or coin in closing:
                raise RuntimeError(
                    f"{coin} has a daily order due with a mandatory exit or a replacement buy at "
                    f"{h}, which the cancels and the synthetic funding-month close rule out"
                )
        coins = sorted(self._held_coins() | set(due) | set(closing) | set(replacing))
        holdings = {coin: self._holding(coin) for coin in coins}
        band: dict[str, tuple[Decimal, bool]] = {}
        trading: dict[str, tuple[Decimal, bool, str]] = {}  # weight, eligible, source
        for coin, order in due.items():
            current = _weight(holdings[coin], equity)
            trades = band_trades(order.target, current)
            band[coin] = (current, trades)
            if trades:
                trading[coin] = (order.target, self._eligible.get(coin, False), SIGNAL)
        # The decision hour behind each trading target: the order's, or for a replacement buy
        # that of the coin's latest target, which sizes it.
        decisions = {coin: order.decision_ms for coin, order in due.items()}
        for coin in replacing:
            trading[coin] = (self._targets.get(coin, _ZERO), False, REPLACEMENT_BUY)
            if coin in self._target_ms:
                decisions[coin] = self._target_ms[coin]
        states: dict[str, CoinState] = {}
        for coin, holding in holdings.items():
            if coin in trading:
                weight, eligible, _ = trading[coin]
                states[coin] = holding.state(coin, _product(weight, equity), eligible, False)
            else:
                exiting = frozenset(closing.get(coin, {}))
                states[coin] = holding.state(coin, _ZERO, False, True, exiting)
        split = allocate(equity, tuple(states.values()))
        plans: dict[str, list[_Leg]] = {}
        for coin, holding in holdings.items():
            if coin in trading:
                source = trading[coin][2]
                plans[coin] = self._trading_legs(coin, holding, split[coin], source, closing)
            elif coin in closing:
                plans[coin] = self._exit_legs(coin, holding, closing[coin])
        for coin in sorted(set(band) | set(trading) | set(closing)):
            self._record(
                "event",
                _order_record(
                    h,
                    coin,
                    equity,
                    due.get(coin),
                    decisions.get(coin),
                    band.get(coin),
                    trading.get(coin),
                    closing.get(coin, {}),
                    states[coin],
                    holdings[coin],
                    split[coin] if coin in plans else None,
                    plans.get(coin, []),
                ),
            )
        legs = [leg for coin in sorted(plans) for leg in plans[coin]]
        batches: dict[str, list[tuple[Fill, Decimal]]] = {}
        for leg in legs:  # the reductions first
            for item in leg.plan.orders:
                if item.reduce_only:
                    booked = self._book_fill(h, h, leg.coin, leg.key, item, leg.price, leg.reason)
                    batches.setdefault(leg.coin, []).append(booked)
        for leg in legs:  # then the increases, each clipped on the account as it now is
            increases = tuple(item for item in leg.plan.orders if not item.reduce_only)
            if increases:
                booked_all = self._book_increase(
                    h, leg.coin, leg.key, increases, leg.price, leg.reason
                )
                batches.setdefault(leg.coin, []).extend(booked_all)
        for coin in sorted(batches):
            reason = _batch_reason(trading.get(coin), closing.get(coin, {}))
            self._close_batch(h, coin, batches[coin], reason)

    def _holding(self, coin: str) -> _Holding:
        """The coin's legs at this hour's marking prices: spot (its dust apart) and futures."""
        legs = self._legs(coin)
        spot_key = legs[0]
        spot = self._ledger.quantity(*spot_key)
        dust = spot_notional = dust_notional = _ZERO
        if spot:
            price = self._prices[spot_key]
            dust = self._dust(coin, price)
            dust_notional = to_decimal(to_fraction(dust) * to_fraction(price))
            spot_notional = to_decimal((to_fraction(spot) - to_fraction(dust)) * to_fraction(price))
        futures_key = legs[1] if len(legs) > 1 else None
        futures = futures_notional = _ZERO
        if futures_key is not None:
            futures = self._ledger.quantity(*futures_key)
            if futures:
                price = self._prices[futures_key]
                futures_notional = to_decimal(to_fraction(futures) * to_fraction(price))
        return _Holding(
            spot, dust, futures, futures_key, spot_notional, dust_notional, futures_notional
        )

    def _trading_legs(
        self,
        coin: str,
        holding: _Holding,
        targets: LegTargets,
        source: str,
        closing: Mapping[str, Mapping[Venue, str]],
    ) -> list[_Leg]:
        """A trading coin's leg plans: spot to its share plus its dust (a spot-only coin holds
        its dust), futures to its signed share, each in the venue's units at its open."""
        legs: list[_Leg] = []
        spot_key: _Key = ("spot", coin)
        spot_target = to_decimal(to_fraction(targets.spot) + to_fraction(holding.dust_notional))
        if holding.spot or spot_target:
            price = self._fill_open(spot_key)
            target = to_venue_quantity(spot_target, price)
            plan = plan_leg("spot", holding.spot, target, price, self._rules[spot_key])
            reason = REPLACEMENT_BUY if source == REPLACEMENT_BUY else SIGNAL
            legs.append(_Leg(coin, spot_key, price, holding.spot, target, plan, reason))
        if holding.futures or targets.futures:
            key = holding.futures_key
            if key is None:
                raise RuntimeError(f"{coin} has no perpetual, yet its split holds futures")
            price = self._fill_open(key)
            target = to_venue_quantity(targets.futures, price)
            plan = plan_leg("futures", holding.futures, target, price, self._rules[key])
            reason = closing.get(coin, {}).get("futures", SIGNAL)
            legs.append(_Leg(coin, key, price, holding.futures, target, plan, reason))
        return legs

    def _exit_legs(self, coin: str, holding: _Holding, exits: Mapping[Venue, str]) -> list[_Leg]:
        """The plans of a coin's mandatory exit legs, each to 0 on its own venue: a spot sale
        whose remainder below the filters stays as dust, a futures close of exactly its
        quantity."""
        legs: list[_Leg] = []
        for venue in _VENUES:
            if venue in exits:
                key = self._key(coin, venue)
                held = holding.spot if venue == "spot" else holding.futures
                price = self._fill_open(key)
                plan = plan_leg(venue, held, _ZERO, price, self._rules[key])
                legs.append(_Leg(coin, key, price, held, _ZERO, plan, exits[venue]))
        return legs


# ---- small rules no module holds -------------------------------------------------------------


def _month_end(h: int, end_month: str) -> str | None:
    """The month M a decision at ``h`` must judge for the funding-month exit: at 00:00 of month
    M - 1's last day, the next month M, unless it is after ``end_month`` (the window end closes
    everything then). None at any other decision (spec "Data": the close is made at the daily
    decision of the previous month's last day)."""
    following = _month_of(h + DAY_MS)
    if following == _month_of(h) or following > end_month:
        return None
    return following


def _audit_failure(audit: Audit) -> str | None:
    """The first accounting identity the audit breaks, or None (spec "Safety", accounting: the
    wallet and quantity identities are exact, the equity residual at most 1e-18 USDT)."""
    if audit.wallet_residual != 0:
        return "wallet"
    if any(value != 0 for value in audit.quantity_residuals.values()):
        return "quantity"
    if audit.equity_residual.copy_abs() > EQUITY_RESIDUAL_LIMIT:
        return "equity"
    return None


def _month_of(ms: int) -> str:
    moment = datetime.fromtimestamp(ms // 1000, UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def _cut_quantity(held: Decimal, factor: Decimal, step: Decimal) -> Decimal:
    """A cut leg's new quantity (spec "Safety": the tradable positions are cut pro rata by k or
    k'): ``|held| x factor`` computed exactly in Fractions, never under the 60-digit context,
    and truncated toward zero to the venue's step, the rounding ``plan_leg`` gives any target,
    with the held sign. A factor above 1 is never applied, and one at or below 0 closes the leg
    (target 0)."""
    if factor <= 0:
        return _ZERO
    unit = to_fraction(step)
    exact = abs(to_fraction(held)) * min(to_fraction(factor), Fraction(1))
    kept = (exact // unit) * unit
    return to_decimal(kept if held > 0 else -kept)


def _weight(holding: _Holding, equity: Decimal) -> Decimal:
    """The band's ``current``: the coin's signed notional over both venues (dust included) at
    the fill hour's unslipped opens, over the open mark's equity, divided under ``CONTEXT``
    (spec "Sizing", fewer trades; controller ruling, Task 4)."""
    notional = (
        to_fraction(holding.spot_notional)
        + to_fraction(holding.dust_notional)
        + to_fraction(holding.futures_notional)
    )
    if notional == 0:
        return _ZERO
    with localcontext(CONTEXT):
        return to_decimal(notional) / equity


def _product(weight: Decimal, equity: Decimal) -> Decimal:
    """A target weight's notional at the open mark's equity, exact."""
    return to_decimal(to_fraction(weight) * to_fraction(equity))


def _batch_reason(trading: tuple[Decimal, bool, str] | None, exits: Mapping[Venue, str]) -> str:
    """The reason a coin's batch gives a lifecycle it ends (spec "Records"): a universe exit
    first, then a funding-month exit (its replacement buy included), else the signal."""
    reasons = set(exits.values())
    if UNIVERSE_EXIT in reasons:
        return UNIVERSE_EXIT
    if FUNDING_EXIT in reasons or (trading is not None and trading[2] == REPLACEMENT_BUY):
        return FUNDING_EXIT
    return SIGNAL


# ---- record shapes (shared with the hold arms) ---------------------------------------------


def _audit_record(audit: Audit) -> dict[str, object]:
    return {
        "wallet_residual": audit.wallet_residual,
        "equity_residual": audit.equity_residual,
        "quantity_residuals": [
            [venue, symbol, value] for (venue, symbol), value in audit.quantity_residuals.items()
        ],
    }


def _mark_record(mark: Mark) -> dict[str, object]:
    return {
        "equity": mark.equity,
        "cash": mark.cash,
        "spot_value": mark.spot_value,
        "futures_upnl": mark.futures_upnl,
        "backing": mark.backing,
        "maintenance": mark.maintenance,
        "margin_ratio": mark.ratio,
        "gross_notional": mark.gross_notional,
        "gross": mark.gross,
    }


def _hourly_record(
    h: int, open_: tuple[Mark, bool] | None, mark: Mark, audit: Audit
) -> dict[str, object]:
    return {
        "open_ms": h,
        "open_equity": None if open_ is None else open_[0].equity,
        "complete": None if open_ is None else open_[1],
        "equity": mark.equity,
        "gross_notional": mark.gross_notional,
        "gross": mark.gross,
        "margin_ratio": mark.ratio,  # null: no futures position, +infinity
        "equity_residual": audit.equity_residual,
    }


def _order_record(
    h: int,
    coin: str,
    equity: Decimal,
    order: Pending | None,
    decision_ms: int | None,
    band: tuple[Decimal, bool] | None,
    trading: tuple[Decimal, bool, str] | None,
    exits: Mapping[Venue, str],
    state: CoinState,
    holding: _Holding,
    split: LegTargets | None,
    legs: Sequence[_Leg],
) -> dict[str, object]:
    """The fill hour's half of a coin's daily record (spec "Records": the band, the split and
    the order placed, or the reason none was). ``decision_ms`` is the decision hour of the
    target used: the order's, or for a replacement buy that of the coin's latest target."""
    if order is not None:
        source, target = SIGNAL, order.target
    elif trading is not None:
        source, target = trading[2], trading[0]
    else:
        source, target = "exit", None
    return {
        "type": "order",
        "hour_ms": h,
        "coin": coin,
        "source": source,
        "decision_ms": decision_ms,
        "target": target,
        "eligible": None if trading is None else trading[1],
        "current": None if band is None else band[0],
        "band": None if band is None else ("trade" if band[1] else "keep"),
        "exits": [[venue, exits[venue]] for venue in _VENUES if venue in exits],
        "equity": equity,
        "state": {
            "target_notional": state.target_notional,
            "spot_notional": state.spot_notional,
            "dust": holding.dust,
            "dust_notional": state.dust_notional,
            "futures_notional": state.futures_notional,
        },
        "split": None if split is None else {"spot": split.spot, "futures": split.futures},
        "legs": [
            {
                "venue": leg.key[0],
                "symbol": leg.key[1],
                "held": leg.held,
                "target": leg.target,
                "orders": [
                    {"side": item.side, "quantity": item.quantity, "reduce_only": item.reduce_only}
                    for item in leg.plan.orders
                ],
                "refusal": leg.plan.refusal,
                "dust": leg.plan.dust,
            }
            for leg in legs
        ],
    }


def _cut_leg_record(leg: _Leg) -> dict[str, object]:
    return {
        "coin": leg.coin,
        "venue": leg.key[0],
        "symbol": leg.key[1],
        "held": leg.held,
        "target": leg.target,
        "orders": [
            {"side": item.side, "quantity": item.quantity, "reduce_only": item.reduce_only}
            for item in leg.plan.orders
        ],
        "dust": leg.plan.dust,
    }


def _lifecycle_record(lifecycle: Lifecycle) -> dict[str, object]:
    return {
        "coin": lifecycle.coin,
        "side": lifecycle.side,
        "entry_ms": lifecycle.entry_ms,
        "exit_ms": lifecycle.exit_ms,
        "exit_reason": lifecycle.exit_reason,
        "gross_pnl": lifecycle.gross_pnl,
        "fees": lifecycle.fees,
        "funding": lifecycle.funding,
        "best_unrealised": lifecycle.best_unrealised,
        "given_back": lifecycle.given_back,
        "holding_hours": lifecycle.holding_hours,
        "censored": lifecycle.censored,
        "unrealised": lifecycle.unrealised,
        "venues": lifecycle.venues,
    }


def _daily_record(
    h: int,
    day: int,
    view: _CoinView,
    sizing: SizingResult,
    coin: CoinSizing,
    target: Decimal | None,
) -> dict[str, object]:
    reading = view.reading
    capped_by = [
        step
        for step, changed in (
            ("coin_cap", coin.scaled != coin.after_coin_cap),
            ("total_cap", coin.after_coin_cap != coin.after_total_cap),
        )
        if changed
    ]
    no_target = None
    if target is None:
        no_target = "warming" if reading is None else "no_bar"
    return {
        "decision_ms": h,
        "day_ms": day,
        "coin": view.coin,
        "in_universe": view.in_universe,
        "universe_exit": view.universe_exit,
        "no_bar": not view.has_bar,
        **_reading_fields(reading),
        "perpetual": view.perpetual,
        "perpetual_eligible": view.point_in_time,
        "next_month": view.next_month,
        "next_month_status": view.next_status,
        "eligible": view.eligible,
        "funding_month_exit": view.funding_exit,
        "signal": view.signal,
        "sigma": coin.sigma,
        "raw": coin.raw,
        "full": coin.full,
        "scaled": coin.scaled,
        "after_coin_cap": coin.after_coin_cap,
        "after_total_cap": coin.after_total_cap,
        "capped_by": capped_by,
        "scale": sizing.scale,
        "common_days": sizing.common_days,
        "flat_reason": sizing.flat_reason,
        "target": target,
        "no_target": no_target,
    }


def _reading_fields(reading: SignalReading | None) -> dict[str, object]:
    """The reading's speeds (values and votes), downtrend parts, L, S and s; null without one."""
    if reading is None:
        return dict.fromkeys(
            ("reading_day_ms", "close", "speeds", "downtrend", "L", "S", "s", "s_long_only")
        )
    return {
        "reading_day_ms": reading.day_ms,
        "close": reading.close,
        "speeds": {
            "fast": {"sma": reading.sma_fast, "vote": reading.fast},
            "medium": {
                "ema_fast": reading.ema_fast,
                "ema_slow": reading.ema_slow,
                "donchian": reading.donchian,
                "vote": reading.medium,
            },
            "slow": {"sma": reading.sma_slow, "vote": reading.slow},
        },
        "downtrend": {
            "confirmed": reading.downtrend,
            "close_below_sma": [reading.close, reading.sma_trend],
            "sma_falling": [reading.sma_trend, reading.sma_trend_lagged],
            "lower_highs": [reading.high_recent, reading.high_prior],
            "lower_lows": [reading.low_recent, reading.low_prior],
        },
        "L": reading.L,
        "S": reading.S,
        "s": reading.s,
        "s_long_only": reading.s_long_only,
    }
