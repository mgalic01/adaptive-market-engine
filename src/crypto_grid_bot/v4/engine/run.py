"""The hour loop of the V4 arms: one cell replayed over the market, hour by hour, into its
hash-chained records.

Implements the spec's "Account and execution" ("Order of events in an hour", "Timing", "Window
end"), the 00:00 decision of "Signals" (from completed daily bars; the no-bar rule and its two
overrides) and of "Sizing" (steps 1 to 3), "Universe" (point-in-time perpetual eligibility;
leaving the top 10), "Data" (the funding-month exit), the "Accounting" bullet of "Safety",
"Records" and the outcomes of "Reports". ``run.py`` composes the engine's modules and holds no
trading rule of its own; the few small rules no module has are private functions here, each
citing the spec (``_month_end``, ``_audit_failure`` and the decided-coins rule in
``_V4Cell._decide``).

**The hour.** ``run_v4_cell`` runs every hour ``h`` from ``market.window_start_ms`` to
``market.window_end_ms``, in the spec's order of events:

1. the synthetic closes due at this instant, as one batch (Task 12c);
2. the open mark, kept in ``open_marks`` with its completeness flag, then the pre-fill
   liquidation check;
3. at 00:00, the daily decision (below);
4. the fills due this hour (Task 12b);
5. the post-fill mark and its liquidation, cushion and ceiling checks (Task 12c);
6. each funding event and its checks (Task 12c);
7. the liquidation check at the adverse extremes (Task 12c);

then, at the last hour, the window-end close (Task 12b), and last of all

8. the audit, the ``hourly`` record and, when the cell ends, the ``outcome`` record.

A phase that stops the cell (a liquidation or an unrestorable limit) skips the rest of the hour
up to step 8. The phases of Tasks 12b and 12c do nothing yet, so no position arises; they exist
in the loop order, each a method of the cell state with its contract in its docstring.

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
  order, who ``entered`` and who ``left``, and ``perpetuals``: for each universe coin with a
  perpetual, its ``coin``, ``perpetual``, ``multiplier``, the funding ``status`` of the month and
  the ``next_status`` of ``next_month``, which the funding-month exit reads.
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
* ``event``: ``order_superseded`` (an older pending order a decision replaced) and
  ``replacement_superseded`` (a replacement buy it cancelled), each with ``hour_ms`` and
  ``coin``.
* ``hourly``, once per hour after step 8: ``open_ms``, ``open_equity`` and ``complete`` (null if
  the hour stopped before its open mark), and at the end of the hour ``equity``,
  ``gross_notional``, ``gross`` (null when equity is at or below 0), ``margin_ratio`` (null with
  no futures position, read as +infinity, spec "Safety") and ``equity_residual``, the audit's.
* ``lifecycle``: every field of a ``Lifecycle``.
* ``outcome``, last: ``outcome``, ``reason``, ``stop_ms``, ``hours``, ``final_equity``,
  ``equity_2025``, ``final_after_close`` and the last ``audit``; plus ``values`` (the residuals)
  for ``accounting_failure``, ``check`` and ``mark`` for a stop, and ``type``, ``message`` and
  ``hour_ms`` for ``engine_error``.

**Outcomes.** ``complete``; ``liquidated`` (reason null, the record's ``check`` names the check
that stopped it); ``limit_unrestorable`` (reason ``ceiling`` or ``margin_cushion``, Task 12c);
``accounting_failure`` (reason ``wallet``, ``quantity`` or ``equity``: the first identity that
failed, in that order); ``engine_error`` (reason ``"<Type>: <message>"``).

The loop does O(coins) work an hour: bars by bisection, each coin's daily bars and returns
built once, on its first decision, and fed or sliced from a cursor.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.sizing import DailyReturn
from crypto_grid_bot.v4.engine.arms import (
    ARMS,
    COVARIANCE_DAYS,
    SIGMA_RETURNS,
    ArmSpec,
    CellSpec,
    Lookbacks,
)
from crypto_grid_bot.v4.engine.ledger import Audit, Ledger, Mark, Venue
from crypto_grid_bot.v4.engine.lifecycle import Lifecycle, Lifecycles
from crypto_grid_bot.v4.engine.market import COMPLETE, HOUR_MS, HourBar, Market, SeriesStore
from crypto_grid_bot.v4.engine.numbers import to_decimal, to_fraction
from crypto_grid_bot.v4.engine.pending import Decided, PendingBook
from crypto_grid_bot.v4.engine.records import Receipt, RecordWriter, write_receipt
from crypto_grid_bot.v4.engine.safety import liquidated
from crypto_grid_bot.v4.engine.signals import CoinSignals, SignalReading
from crypto_grid_bot.v4.engine.sizing import CoinSizing, SizingResult, daily_returns, size_book

DAY_MS = 24 * HOUR_MS
RECORDS_FILE = "records.jsonl"
RECEIPT_FILE = "receipt.json"
# Spec "Pass rule", condition 4: equity at the open of 2025-01-01 00:00 UTC.
EQUITY_2025_MS = month_bounds_ms("2025-01")[0]
# Spec "Safety", accounting: the equity-change residual may be at most this, in USDT.
EQUITY_RESIDUAL_LIMIT = Decimal("1e-18")

_Key = tuple[Venue, str]
_ZERO = Decimal(0)
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
        self._writer: RecordWriter | None = None
        # Every ledger key the market knows: its store and its coin (the spot symbol).
        self._stores: dict[_Key, SeriesStore] = {}
        self._coin_of: dict[_Key, str] = {}
        for symbol in market.symbols:
            coin = market.coin(symbol)
            self._stores["spot", symbol] = coin.spot
            self._coin_of["spot", symbol] = symbol
            if coin.perpetual is not None:
                self._stores["futures", coin.perpetual.symbol] = coin.perpetual.store
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

    def _synthetic_closes(self, h: int) -> None:
        """Step 1 (Task 12c): the dead-market and synthetic funding-month closes due at ``h``,
        as one batch with one liquidation check at the penalised prices, booked together."""

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
            self._stop_at("liquidated", None, "open_mark", prices, mark)

    def _window_end(self, h: int) -> None:
        """At the last hour, after its other events (Task 12b): every position closes at the
        hour's close (its carried mark without a bar) with costs, unsellable dust stays and is
        censored, and ``self._prices`` becomes the close prices. Until then nothing is held."""
        if self._ledger.positions():
            raise NotImplementedError("closing held positions at the window end is Task 12b's")

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
        reason = "liquidation" if stop.outcome == "liquidated" else "limit_unrestorable"
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
        # The latest decision's answers, for the fill phase (Task 12b).
        self._targets: dict[str, Decimal] = {}  # each coin's latest target
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
        """After ``decide`` (Task 12b): for each universe exit and each funding-month exit
        (``view.funding_exit``), ``PendingBook.cancel(coin)``, recording what it removed, then
        ``schedule_exit`` for each leg it closes: both held legs for a universe exit, the
        futures leg for a funding-month exit, each from ``h + 1 h``."""

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
        return {
            "month": month,
            "open_ms": h,
            "universe": list(self._universe),
            "entered": [coin for coin in self._universe if coin not in previous],
            "left": [coin for coin in previous if coin not in self._universe],
            "perpetuals": perpetuals,
        }

    # ---- steps 4 to 7 (Tasks 12b and 12c) ------------------------------------------------

    def _fills(self, h: int) -> None:
        """Step 4 (Task 12b): the mandatory exits, daily orders and replacement buys due at
        ``h``; the band at this hour's opens, the deferrals, the allocation, the leg orders,
        reductions then the clipped increases, and the lifecycles' ``after_batch``."""

    def _post_fill(self, h: int) -> None:
        """Step 5 (Task 12c): the post-fill mark, the liquidation check, then the cushion and
        the ceiling checks, each cut filled at this open and followed by a new mark."""

    def _funding_events(self, h: int) -> None:
        """Step 6 (Task 12c): each funding event of ``h`` in time order on a held perpetual,
        each followed by a mark and the liquidation, cushion and ceiling checks."""

    def _adverse_extremes(self, h: int) -> None:
        """Step 7 (Task 12c): the liquidation check at the bars' adverse extremes, all at once."""


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
