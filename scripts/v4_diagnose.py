"""V4.0's diagnosis of the diagnostic run: the market regime per month, and each cell's results
broken down by year and month, by side, by exit reason, by coin and by cost.

The owner asked (2026-10-22) why V4 lost money in particular years, 2021 and 2023 among them.
The ``diagnose`` job of ``.github/workflows/v4-cells.yml`` runs this after the cells of a
pre-2025 data run (plan ``docs/superpowers/plans/2026-10-23-v4-diagnostic-run.md``, Task 3). It
adds no trading rule: it reads what the spec's "Records" and "Reports" write, and its timing
section is the "Verification" bullet's timing run (cell times, memory and output sizes).

``--data D --cells C --planned IDS --out O``:

1. refuses an ``O`` that already holds ``diagnosis.json`` or ``diagnosis.md``, and a ``--planned``
   that is not a comma-separated list of distinct cell ids of ``all_cells()`` (the plan job's
   ``cell_ids``, the cells the dispatch asked for);
2. runs ``v4_cells_guard``'s own check on ``D`` (owner decision v4-d03: no market data from
   2025-01 on) before any pack is read, then loads the packs (``Market.load``) and refuses an
   ``end_month`` after the guard's ``LATEST_ALLOWED``;
3. takes every subfolder of ``C`` holding a ``summary.json`` (the workflow puts each cell in
   ``C/v4-cell-<cell id>/``; the cell's id is its summary's ``cell``, never the folder's name).
   For each one: ``summary.json`` must be canonical JSON; ``receipt.json`` is read with
   ``read_receipt``; ``verify_summary`` rebuilds the summary from ``records.jsonl``, streamed
   to the end through ``read_records``, and requires equality; the summary's ``data`` pins and
   ``window`` must be those of ``D``'s packs (the regime is computed from them); and a
   ``timing.json``, when there is one, must be the cell's, with the records' size. A full cell's
   records are then streamed once more, to the end, keeping only the aggregates below, never a
   record; its years must equal the verified summary's. Last, the cell must be one of
   ``--planned``. A cell that fails any of these checks,
   or whose records have a shape the pass refuses, is refused alone: it is listed under the
   missing cells with the step that failed and the exception's type (never its text), and the
   other cells are diagnosed;
4. computes the market regime per month and per year from the packs alone;
5. creates ``O/diagnosis.json`` and ``O/diagnosis.md``, both exclusively; if the second cannot
   be written, the first is removed again, so a failed run leaves no file. They hold results and
   stay on the owner's PC (the workflow uploads them as a 1-day artifact).

The diagnosis also names what is missing: every subfolder of ``C`` without a ``summary.json``,
every cell folder it refused (its folder's name, step and exception type), and every cell of
``--planned`` with no diagnosed cell (one that failed, timed out or was refused), in run order.
A cell folder of a cell the dispatch did not ask for is refused (step 3), so it is listed with
the refused folders and never as a missing cell.

**Exit status.** 0 once both files are written and no cell was refused; 1 when a cell was
refused, after both files were written with the other cells (partial results, never none), and
for any other refusal or failure, with nothing written; 2 for bad arguments (argparse's own).

**Output.** Standard output carries the guard's line (the end month and the config pin), one
line per diagnosed cell (its id and its record, year and month counts) and a last line of counts
(cells, folders, folders without a summary, refused cells, missing cells, regime months): never a
price, an equity, a return or a cell's outcome, all of them results (owner rule: public logs;
Codex P2 on #294). A refused cell, and a failure, is one line on standard error naming the step
and the exception's type, never its text.

**The page** (``diagnosis.md``) opens with a headline that answers "what did the bot do in year
X": one table of every cell's return and largest drawdown per year beside BTCUSDT's yearly return
and the median yearly return of the universe's coins, then each stopped cell's last year beside
BTCUSDT and the median coin over the same span (to the stop), each cell's losing years, and one
plain line per arm, made from ``arms.ARMS``. A glossary follows, then the timing, the missing
cells, the market regime and one section per cell.

**Periods** (Review Focus 3). A cell's months and years are summary.py's periods: each starts at
the open mark of its first simulated hour and ends at the open mark of the hour that starts the
next period, or at the final equity when there is none (at the window's end for a complete cell,
at the stop for a stop), and its return is ``end / start - 1`` under ``CONTEXT``. They are
computed by summary.py's own ``_Ending.period``, over the open marks at the first hour and at
each month's first hour (the only ones a period reads). A period's ``max_drawdown`` is
``trend.metrics.maximum_drawdown`` over the open marks inside it and then its end equity, computed
one mark at a time with the same steps. Months and years run from the first simulated hour's to
the last one's, as the summary's years do.

**What counts where.** A fill or funding record, and an event, counts in the period of its
``hour_ms``; a daily record in the year of its ``decision_ms``; a lifecycle opens in the period of
its ``entry_ms`` and counts, with its figures, in the period and year of its ``exit_ms``.

* Lifecycles: opened and closed by side; ``wins``, those whose net P&L (``gross_pnl - fees +
  funding``) is above 0, and the win rate over those closed; ``gross_pnl`` and its positive
  (``gross_profit``) and negative (``gross_loss``) parts; ``fees``, ``funding`` (positive when
  the wallet received it), ``net_pnl`` and ``given_back`` (``best_unrealised - gross_pnl``, how
  far the gross P&L fell from its best point, before fees and funding).
* The return against the trades: ``equity_change`` (end equity minus start equity, USDT) and
  ``open_trades_pnl``, that change minus the net P&L of the lifecycles closed in the period: the
  profit or loss on trades still open at the period's start or end (a trade counts where it
  closes, with all its P&L).
* Exposure (``exposure``): ``hours`` (the hourly records of the period, by ``open_ms``),
  ``mean_gross_exposure`` (the mean of the hourly ``gross``, gross notional over equity, over the
  hours that have one), ``in_market_share`` (the share of hours whose ``gross`` is at least
  ``IN_MARKET``, 1% of equity, so unsellable dust alone does not count), ``decisions`` (the daily
  decisions, by ``decision_ms``) and ``mean_long_weight`` and ``mean_short_weight``: at each
  decision, after its ``daily_coin`` records, the sum of the coins' positive targets and of their
  negative targets' sizes, each coin keeping its last target when it gets none (a dead market's
  is dropped, a target of 0 drops it), averaged over the decisions. A hold arm has no daily
  record, so those are null.
* Costs, from the fill, funding and synthetic-close records: ``fills``, ``traded_notional``
  (quantity x price), ``fees``, ``slippage`` (|price - unslipped price| x quantity, so 0 for a
  synthetic close), ``synthetic_close_penalty`` (over the legs of the ``synthetic_closes``
  events, dead market and funding month alike: |last close - penalised price| x |held|, the 10%
  penalty), ``funding_records`` and ``funding`` (the records' signed amounts). The fees and
  funding here are the lifecycles' fees and funding booked when paid rather than when the trade
  ended: the same money seen two ways, never to be added together.
* Counts, from the events: ``margin_cuts`` and ``ceiling_cuts`` (one per cut event);
  ``dead_market_closes`` and ``funding_month_closes`` (the legs of the synthetic closes booked,
  by reason: a batch whose own liquidation check stopped the cell, an outcome with ``check``
  ``synthetic_closes`` at the batch's hour, booked no fill, so its legs count in neither, though
  its penalty stays in the costs, since the stop's equity and the censored trades are valued at
  the penalised prices); ``deferrals`` (a daily order, ``signal`` or a hold arm's
  ``rebalance``, that did not fill in its first fill hour, the decision's hour plus one: counted
  when it fills later, is superseded or is cancelled); ``refused_orders`` (an order event's legs
  with a refusal);
  ``cash_clip_cuts`` (``increase_cut`` events) and ``band_skips`` (orders the band kept).
* By side, exit reason and coin, per year: lifecycles, wins, win rate (side only), gross P&L,
  fees, funding, net P&L and given back. Both sides are listed every year; exit reasons
  and coins only when they occur. A coin's row also holds ``coin_return``, the coin's own price
  change over the cell's year (below).
* The bot's own trades, per year of ``exit_ms``: ``losing_trades``, the ``LOSERS_PER_YEAR``
  lifecycles with the most negative net P&L (below 0), most negative first and the earlier record
  first on a tie, kept in a bounded heap per year, each with its coin, side, ``entry_ms``,
  ``exit_ms``, ``opened`` and ``closed`` (UTC days), ``hours_held`` (``exit_ms - entry_ms`` in
  hours), ``net_pnl``, ``exit_reason`` and ``given_back``; and ``holding_times``, the lifecycles
  of each ``HOLDING_TIMES`` bucket (under 1 week, 1 to 4 weeks, 1 to 3 months, over 3 months:
  under 7, 28 and 91 days, and the rest) with their wins, win rate and net P&L.
* Signals, per year, over the coin-days (the ``daily_coin`` records): for each speed the share
  up, down and warming (no reading, warming up, or an exact tie: the engine's ``None``) and its
  flips (a vote opposite to the coin's last up or down vote; a no-bar day repeats the last
  reading, so it never flips); the shares with no reading, with a confirmed downtrend, with
  S > 0 and with L at 0, 1/3, 2/3 and 1; and the mean number of coins with a nonzero target per
  decision, counted at each decision after its ``daily_coin`` records as the weights are: a coin
  keeps its last target when it gets none, a dead market's is dropped and a target of 0 drops
  it. A hold arm has none.

Money is summed exactly in Fractions and written as exact Decimals; shares, rates, returns and
the regime's figures are computed under ``CONTEXT``.

**The market regime per month**, from ``Market.daily`` (daily bars of unmasked hours) and only
from bars of the month and before it, for every month from the window's first to the packs'
``end_month``:

* ``btc_return``: BTCUSDT's last daily close of the month over its last close before it, minus 1;
* ``btc_vs_sma200`` (``above``, ``below`` or ``equal``) and ``btc_close_over_sma200`` (minus 1):
  the month's last close against the mean of the last 200 daily closes up to it;
* ``btc_volatility_30d_annualised``: the sample standard deviation of the daily returns of the
  30 days ending with the month's last bar (each against the bar before it), times sqrt(365);
* ``btc_sma20_crossings``: the month's bars whose close is on the other side of the SMA20 from
  the last bar before them that was not on it (choppiness);
* ``universe_coins``, ``universe_coins_with_return`` and ``universe_median_return``: the month's
  universe and the median of their monthly returns, as BTCUSDT's is computed.

**The market per year** (``market_years``), for every year from the window's first to
``end_month``'s, over the part of the year inside the window (from the window's start in its
first year): ``btc_return``, BTCUSDT's last daily close in that span over its last close before
the span, minus 1 (over the coin's own span, from its first close in it, when it has no bar
before); and ``universe_coins``, ``universe_coins_with_return`` and ``universe_median_return``
for the coins in the universe in any month of that span, each coin's return computed as
BTCUSDT's. A coin with fewer than two bars in the span, and none before it, has no return.

**The market beside a cell's own periods.** Each of a cell's months holds ``btc_return`` and each
of its years ``btc_return`` and ``universe_median_return``, and each by-coin row ``coin_return``
(over that coin's year of the cell), all over the period's own span, ``start_ms`` to ``end_ms``,
from the daily closes made by ``end_ms`` (a bar whose close comes after it is not read): a
month's as the regime's month, a year's as ``market_years``' year, the median over the coins in
the universe in any month the span touches. Over a whole month or year these are the regime's
and ``market_years``' figures; over a stopped cell's last month and year they end at the stop,
so no price after the stop is compared with the cell.

A figure without the bars it needs is null, and so is every BTCUSDT figure of packs without it.
"""

from __future__ import annotations

import argparse
import contextlib
import heapq
import json
import sys
from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

import v4_cells_guard
from v4_cells_timing import TIMING_FILE

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.combined.artifacts import _canonical, _digest
from crypto_grid_bot.v4.data.config import months
from crypto_grid_bot.v4.engine.arms import (
    ARMS,
    HOLD_INVESTED,
    MAIN_LOOKBACKS,
    ArmSpec,
    all_cells,
)
from crypto_grid_bot.v4.engine.hold import REBALANCE
from crypto_grid_bot.v4.engine.lifecycle import EXIT_REASONS
from crypto_grid_bot.v4.engine.market import HOUR_MS, Market
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal, to_fraction
from crypto_grid_bot.v4.engine.records import Receipt, read_receipt, read_records
from crypto_grid_bot.v4.engine.run import (
    DELISTING,
    FUNDING_EXIT,
    OUTCOME_COMPLETE,
    RECEIPT_FILE,
    RECORDS_FILE,
    SIGNAL,
    data_record,
    window_record,
)
from crypto_grid_bot.v4.engine.signals import long_fraction
from crypto_grid_bot.v4.engine.summary import (
    FULL_OUTCOMES,
    SUMMARY_FILE,
    _Ending,
    _year_of,
    _year_start,
    verify_summary,
)

DIAGNOSIS_FORMAT = "v4-diagnosis-2"
JSON_FILE = "diagnosis.json"
MD_FILE = "diagnosis.md"
OUTPUT_FILES = (JSON_FILE, MD_FILE)

BTC = "BTCUSDT"
SMA_LONG = 200
SMA_SHORT = 20
VOLATILITY_DAYS = 30
DAYS_PER_YEAR = 365
DAY_MS = 24 * HOUR_MS

SIDES = ("long", "short")
SPEEDS = ("fast", "medium", "slow")
COUNT_NAMES = (
    "margin_cuts",
    "ceiling_cuts",
    "dead_market_closes",
    "funding_month_closes",
    "deferrals",
    "refused_orders",
    "cash_clip_cuts",
    "band_skips",
)
# The daily orders whose late fill is a deferral; a replacement buy or an exit has no decision.
_DAILY_SOURCES = (SIGNAL, REBALANCE)
_PERIOD_SUMS = ("gross_pnl", "gross_profit", "gross_loss", "fees", "funding", "net_pnl")
# A full cell's figures, in the order of its entry; all null for a failure summary.
FIGURE_NAMES = (
    "years",
    "months",
    "sides",
    "exit_reasons",
    "coins",
    "losing_trades",
    "holding_times",
    "signals",
)
_GROUP_SUMS = ("gross_pnl", "fees", "funding", "net_pnl", "given_back")
# The keys of a summary's year (summary.py), which the diagnosis' years must reproduce.
_YEAR_KEYS = ("year", "start_ms", "end_ms", "start_equity", "end_equity", "return")
_TIMING_KEYS = frozenset({"cell", "wall_seconds", "peak_rss_mb", "records_bytes"})
_MAX_TIMING_BYTES = 4096
_ZERO = Fraction(0)

# An hour is "in the market" when its gross exposure is at least 1% of equity, so the unsellable
# dust a sale leaves behind (below the exchange's minimum order, normally far below 1%) does not
# count as a position.
IN_MARKET = Fraction(1, 100)
# The losing trades kept per year, and the holding-time buckets with their upper bounds in days
# (the last bucket has none).
LOSERS_PER_YEAR = 10
HOLDING_TIMES = ("under 1 week", "1 to 4 weeks", "1 to 3 months", "over 3 months")
_HOLDING_DAYS = (7, 28, 91)

# L is the number of speeds up over 3 (signals.py), so it takes one of these four values.
_LONG_LEVELS: dict[Decimal, str] = {
    long_fraction(None, None, None): "0",
    long_fraction(1, None, None): "1/3",
    long_fraction(1, 1, None): "2/3",
    long_fraction(1, 1, 1): "1",
}


# ---- small readers ----------------------------------------------------------------------------


def month_of(ms: int) -> str:
    """The UTC month (``YYYY-MM``) of an instant in ms."""
    moment = datetime.fromtimestamp(ms // 1000, UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def _int(value: object, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _decimal(value: object, name: str) -> Decimal:
    if type(value) is not str:
        raise ValueError(f"{name} must be a Decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{name} is not a Decimal") from None
    if not number.is_finite():
        raise ValueError(f"{name} is not finite")
    return number


def _fraction(value: object, name: str) -> Fraction:
    return to_fraction(_decimal(value, name))


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _items(value: object, name: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return [_mapping(item, name) for item in value]


def _exact(value: Fraction) -> str:
    return str(to_decimal(value))


def _ratio(part: int, whole: int) -> str | None:
    if whole == 0:
        return None
    with localcontext(CONTEXT):
        return str(Decimal(part) / Decimal(whole))


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _mean(total: Fraction, count: int) -> str | None:
    """``total / count`` under ``CONTEXT``, or None without a count."""
    if count == 0:
        return None
    with localcontext(CONTEXT):
        return str(Decimal(total.numerator) / (Decimal(total.denominator) * count))


def day_of(ms: int) -> str:
    """The UTC day (``YYYY-MM-DD``) of an instant in ms."""
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%d")


def holding_time(held_ms: int) -> str:
    """The ``HOLDING_TIMES`` label of a trade held ``held_ms``."""
    # Not strict on purpose: four labels, three upper bounds; the last label has none.
    for label, days in zip(HOLDING_TIMES, _HOLDING_DAYS, strict=False):
        if held_ms < days * DAY_MS:
            return label
    return HOLDING_TIMES[-1]


# ---- the aggregates of one pass -----------------------------------------------------------------


@dataclass(slots=True)
class _Tally:
    """Counts and exact sums."""

    counts: Counter[str] = field(default_factory=Counter)
    sums: dict[str, Fraction] = field(default_factory=dict)

    def add(self, name: str, amount: Fraction) -> None:
        self.sums[name] = self.sums.get(name, _ZERO) + amount

    def merge(self, other: _Tally) -> None:
        self.counts.update(other.counts)
        for name, amount in other.sums.items():
            self.add(name, amount)

    def total(self, name: str) -> str:
        return _exact(self.sums.get(name, _ZERO))


@dataclass(slots=True)
class _Drawdown:
    """``trend.metrics.maximum_drawdown`` over the equities added, one at a time: the same steps
    under the same context, so the same value. None with no equity, or a first one that is not
    positive (``maximum_drawdown`` refuses that path)."""

    peak: Decimal | None = None
    worst: Decimal = Decimal(0)
    valid: bool = True

    def add(self, equity: Decimal) -> None:
        if self.peak is None:
            self.peak = equity
            self.valid = equity > 0
        if not self.valid:
            return
        with localcontext(CONTEXT):
            self.peak = max(self.peak, equity)
            self.worst = max(self.worst, (self.peak - equity) / self.peak)

    def value(self) -> str | None:
        return str(self.worst) if self.peak is not None and self.valid else None


@dataclass(slots=True)
class _Month:
    lifecycles: _Tally = field(default_factory=_Tally)
    costs: _Tally = field(default_factory=_Tally)
    events: _Tally = field(default_factory=_Tally)
    exposure: _Tally = field(default_factory=_Tally)
    drawdown: _Drawdown = field(default_factory=_Drawdown)

    def tallies(self) -> tuple[_Tally, _Tally, _Tally, _Tally]:
        return self.lifecycles, self.costs, self.events, self.exposure


@dataclass(frozen=True, slots=True)
class _Loser:
    """A losing lifecycle, as the per-year heap keeps it."""

    coin: str
    side: str
    entry_ms: int
    exit_ms: int
    net: Fraction
    exit_reason: str
    given_back: Fraction


class _Pass:
    """One pass over a cell's records, in order, keeping only aggregates: per month the tallies
    and the drawdown, per year the drawdown, the breakdowns, the holding times, the signal counts
    and at most ``LOSERS_PER_YEAR`` losing lifecycles (a heap), the open marks a period reads
    (the first hour's and each month's first hour's), and the little a reader needs across
    records (each coin's last up or down vote per speed and its last target, the last
    decision)."""

    def __init__(self) -> None:
        self.count = 0
        self.first_ms: int | None = None
        self.last_ms: int | None = None
        self.marks: dict[int, str] = {}
        self.months: dict[str, _Month] = {}
        self.year_drawdowns: dict[int, _Drawdown] = {}
        self.groups: dict[str, dict[tuple[int, str], _Tally]] = {
            "sides": {},
            "exit_reasons": {},
            "coins": {},
            "holding_times": {},
        }
        self.signals: dict[int, Counter[str]] = {}
        # Per year a min-heap of (-net, -order, loser): its top is the least bad loser kept, and
        # on a tie the later record, so the earlier one stays.
        self.losers: dict[int, list[tuple[Fraction, int, _Loser]]] = {}
        self.outcome: str | None = None
        self.final: str | None = None
        self._bounds: tuple[int, int, str] = (0, 0, "")
        self._marked_month: str | None = None
        self._marked_year: int | None = None
        self._decision: int | None = None
        self._votes: dict[tuple[str, str], int] = {}
        self._targets: dict[str, Fraction] = {}
        self._lifecycles = 0
        # The last synthetic-close batch's leg counts by reason, with its hour: counted once the
        # outcome shows the batch's own liquidation check did not stop the cell.
        self._closes: tuple[int, Counter[str]] | None = None

    def feed(self, kind: str, record: Mapping[str, object]) -> None:
        if self.outcome is not None:
            raise ValueError(f"a {kind} record follows the outcome record")
        self.count += 1
        if kind == "outcome":
            self._settle_closes(record)
        if kind == "hourly":
            self._hourly(record)
        elif kind == "fill":
            self._fill(record)
        elif kind == "funding":
            self._funding(record)
        elif kind == "lifecycle":
            self._lifecycle(record)
        elif kind == "event":
            self._event(record)
        elif kind == "daily_coin":
            self._daily(record)
        elif kind == "outcome":
            outcome = record.get("outcome")
            if type(outcome) is not str:
                raise ValueError("the outcome record has no outcome")
            self.outcome = outcome
            final = record.get("final_equity")
            self.final = None if final is None else str(_decimal(final, "final_equity"))

    def _month(self, ms: int) -> _Month:
        start, end, key = self._bounds
        if not start <= ms < end:
            key = month_of(ms)
            start, end = month_bounds_ms(key)
            self._bounds = (start, end, key)
        month = self.months.get(key)
        if month is None:
            month = self.months[key] = _Month()
        return month

    def _hourly(self, record: Mapping[str, object]) -> None:
        open_ms = _int(record.get("open_ms"), "an hourly record's open_ms")
        if self.last_ms is not None and open_ms != self.last_ms + HOUR_MS:
            raise ValueError("the hourly records are not consecutive hours")
        if self.first_ms is None:
            self.first_ms = open_ms
        self.last_ms = open_ms
        month = self._month(open_ms)
        exposure = month.exposure
        exposure.counts["hours"] += 1
        gross = record.get("gross")
        if gross is not None:  # null when equity is at or below zero
            value = _fraction(gross, "an hourly record's gross")
            exposure.counts["gross_hours"] += 1
            exposure.counts["in_market_hours"] += int(value >= IN_MARKET)
            exposure.add("gross", value)
        text = record.get("open_equity")
        if text is None:  # a stop before its open mark (only the last hour)
            return
        equity = _decimal(text, "an open mark")
        start, _, key = self._bounds
        if open_ms in (self.first_ms, start):
            self.marks[open_ms] = str(text)
        # An open mark that starts a period is the previous period's end equity as well.
        if key != self._marked_month:
            if self._marked_month is not None:
                self.months[self._marked_month].drawdown.add(equity)
            self._marked_month = key
        month.drawdown.add(equity)
        year = int(key[:4])
        if year != self._marked_year:
            if self._marked_year is not None:
                self.year_drawdowns[self._marked_year].add(equity)
            self._marked_year = year
            self.year_drawdowns[year] = _Drawdown()
        self.year_drawdowns[year].add(equity)

    def _fill(self, record: Mapping[str, object]) -> None:
        costs = self._month(_int(record.get("hour_ms"), "a fill's hour_ms")).costs
        quantity = _fraction(record.get("quantity"), "a fill's quantity")
        price = _fraction(record.get("price"), "a fill's price")
        unslipped = _fraction(record.get("unslipped_price"), "a fill's unslipped price")
        costs.counts["fills"] += 1
        costs.add("traded_notional", quantity * price)
        costs.add("fees", _fraction(record.get("fee"), "a fill's fee"))
        costs.add("slippage", abs(price - unslipped) * quantity)

    def _funding(self, record: Mapping[str, object]) -> None:
        costs = self._month(_int(record.get("hour_ms"), "a funding record's hour_ms")).costs
        costs.counts["funding_records"] += 1
        costs.add("funding", _fraction(record.get("amount"), "a funding amount"))

    def _lifecycle(self, record: Mapping[str, object]) -> None:
        side, coin, reason = record.get("side"), record.get("coin"), record.get("exit_reason")
        if side not in SIDES or type(coin) is not str or reason not in EXIT_REASONS:
            raise ValueError("a lifecycle record needs its side, coin and exit reason")
        entry = _int(record.get("entry_ms"), "a lifecycle's entry_ms")
        exit_ms = _int(record.get("exit_ms"), "a lifecycle's exit_ms")
        if exit_ms < entry:
            raise ValueError("a lifecycle ends before it opens")
        gross = _fraction(record.get("gross_pnl"), "a lifecycle's gross P&L")
        fees = _fraction(record.get("fees"), "a lifecycle's fees")
        funding = _fraction(record.get("funding"), "a lifecycle's funding")
        given_back = _fraction(record.get("given_back"), "a lifecycle's given back")
        net = gross - fees + funding
        win = int(net > 0)
        self._month(entry).lifecycles.counts[f"opened_{side}"] += 1
        tally = self._month(exit_ms).lifecycles
        tally.counts[f"closed_{side}"] += 1
        tally.counts["wins"] += win
        for name, amount in (
            ("gross_pnl", gross),
            ("gross_profit", max(gross, _ZERO)),
            ("gross_loss", min(gross, _ZERO)),
            ("fees", fees),
            ("funding", funding),
            ("net_pnl", net),
            ("given_back", given_back),
        ):
            tally.add(name, amount)
        year = _year_of(exit_ms)
        held = holding_time(exit_ms - entry)
        for group, key in (
            ("sides", side),
            ("exit_reasons", reason),
            ("coins", coin),
            ("holding_times", held),
        ):
            found = self.groups[group].setdefault((year, str(key)), _Tally())
            found.counts["lifecycles"] += 1
            found.counts["wins"] += win
            for name, amount in (
                ("gross_pnl", gross),
                ("fees", fees),
                ("funding", funding),
                ("net_pnl", net),
                ("given_back", given_back),
            ):
                found.add(name, amount)
        self._lifecycles += 1
        if net < 0:
            loser = _Loser(coin, str(side), entry, exit_ms, net, str(reason), given_back)
            heap = self.losers.setdefault(year, [])
            item = (-net, -self._lifecycles, loser)
            if len(heap) < LOSERS_PER_YEAR:
                heapq.heappush(heap, item)
            else:
                heapq.heappushpop(heap, item)

    def _event(self, record: Mapping[str, object]) -> None:
        kind = record.get("type")
        hour = _int(record.get("hour_ms"), "an event's hour_ms")
        month = self._month(hour)
        counts = month.events.counts
        if kind == "margin_cut":
            counts["margin_cuts"] += 1
        elif kind == "ceiling_cut":
            counts["ceiling_cuts"] += 1
        elif kind == "increase_cut":
            counts["cash_clip_cuts"] += 1
        elif kind == "synthetic_closes":
            # An earlier batch was booked: only the last one can be the batch that stopped.
            self._settle_closes(None)
            closed: Counter[str] = Counter()
            for leg in _items(record.get("legs"), "a synthetic close's legs"):
                held = _fraction(leg.get("held"), "a synthetic close's held quantity")
                last = _fraction(leg.get("last_close"), "a synthetic close's last close")
                price = _fraction(leg.get("price"), "a synthetic close's price")
                month.costs.add("synthetic_close_penalty", abs(last - price) * abs(held))
                if leg.get("reason") == DELISTING:
                    closed["dead_market_closes"] += 1
                elif leg.get("reason") == FUNDING_EXIT:
                    closed["funding_month_closes"] += 1
                else:
                    raise ValueError("a synthetic close's leg has an unknown reason")
            self._closes = (hour, closed)
        elif kind == "order":
            counts["band_skips"] += int(record.get("band") == "keep")
            legs = _items(record.get("legs"), "an order's legs")
            counts["refused_orders"] += sum(leg.get("refusal") is not None for leg in legs)
            if record.get("source") in _DAILY_SOURCES:
                counts["deferrals"] += int(self._deferred(record, hour))
        elif kind in ("order_superseded", "order_cancelled"):
            counts["deferrals"] += int(self._deferred(record, hour))

    def _settle_closes(self, outcome: Mapping[str, object] | None) -> None:
        """Count the last synthetic-close batch's legs, unless ``outcome`` (the outcome record;
        None for a later batch) stopped the cell at the batch's own liquidation check, its
        ``check`` ``synthetic_closes`` at the batch's hour: that batch booked no fill (run.py)."""
        if self._closes is None:
            return
        hour, legs = self._closes
        self._closes = None
        if (
            outcome is not None
            and outcome.get("check") == "synthetic_closes"
            and outcome.get("stop_ms") == hour
        ):
            return
        self._month(hour).events.counts.update(legs)

    @staticmethod
    def _deferred(record: Mapping[str, object], hour: int) -> bool:
        """Whether a daily order ended after its first fill hour, the decision's plus one."""
        return hour > _int(record.get("decision_ms"), "an order's decision_ms") + HOUR_MS

    def _daily(self, record: Mapping[str, object]) -> None:
        decision = _int(record.get("decision_ms"), "a daily record's decision_ms")
        coin = record.get("coin")
        if type(coin) is not str:
            raise ValueError("a daily record needs its coin")
        counts = self.signals.setdefault(_year_of(decision), Counter())
        if decision != self._decision:
            if self._decision is not None and decision < self._decision:
                raise ValueError("the daily records' decisions go back in time")
            self._close_decision()
            counts["decisions"] += 1
            self._decision = decision
        counts["coin_days"] += 1
        target = record.get("target")
        if target is not None:
            weight = _fraction(target, "a target")
            if weight == 0:
                self._targets.pop(coin, None)
            else:
                self._targets[coin] = weight
        elif record.get("dead_market") is True:  # its latest target is dropped (run.py)
            self._targets.pop(coin, None)
        speeds = record.get("speeds")
        if speeds is None:
            counts["no_reading"] += 1
            for speed in SPEEDS:
                counts[f"{speed}_warming"] += 1
            return
        votes = _mapping(speeds, "a reading's speeds")
        for speed in SPEEDS:
            vote = _mapping(votes.get(speed), f"the {speed} speed").get("vote")
            if vote is None:
                counts[f"{speed}_warming"] += 1
                continue
            if type(vote) is not int or vote not in (1, -1):
                raise ValueError(f"the {speed} vote must be 1, -1 or null")
            counts[f"{speed}_{'up' if vote == 1 else 'down'}"] += 1
            counts[f"{speed}_flips"] += int(self._votes.get((coin, speed)) == -vote)
            self._votes[coin, speed] = vote
        downtrend = _mapping(record.get("downtrend"), "a reading's downtrend")
        counts["confirmed_downtrend"] += int(downtrend.get("confirmed") is True)
        counts["short_positive"] += int(_decimal(record.get("S"), "S") > 0)
        level = _LONG_LEVELS.get(_decimal(record.get("L"), "L"))
        if level is None:
            raise ValueError("L is not 0, 1/3, 2/3 or 1")
        counts[f"long_{level}"] += 1

    def _close_decision(self) -> None:
        """The last decision's wanted long and short weights, after all its daily records:
        every coin's last target, positive ones and negative ones' sizes summed; and its coins
        with a nonzero target, those same coins (each kept target is nonzero)."""
        if self._decision is None:
            return
        self.signals[_year_of(self._decision)]["coins_with_target"] += len(self._targets)
        exposure = self._month(self._decision).exposure
        exposure.counts["decisions"] += 1
        exposure.add("long_weight", sum((w for w in self._targets.values() if w > 0), _ZERO))
        exposure.add("short_weight", sum((-w for w in self._targets.values() if w < 0), _ZERO))

    def finish(self) -> None:
        """The end of the records: the last decision's weights, and a full cell's final equity
        ends its last month and year."""
        self._close_decision()
        if self.outcome is None:
            raise ValueError("the records hold no outcome record")
        if self.outcome in FULL_OUTCOMES and self.final is not None:
            final = Decimal(self.final)
            if self._marked_month is not None:
                self.months[self._marked_month].drawdown.add(final)
            if self._marked_year is not None:
                self.year_drawdowns[self._marked_year].add(final)


# ---- the figures of one cell --------------------------------------------------------------------


def cell_figures(records_path: Path, receipt: Receipt) -> dict[str, Any]:
    """One pass over a full cell's records (``read_records``, to the end), and the cell's
    figures from it: ``record_count``, ``years``, ``months``, ``sides``, ``exit_reasons``,
    ``coins``, ``losing_trades``, ``holding_times`` and ``signals`` (module docstring)."""
    reader = _Pass()
    for kind, record in read_records(records_path, receipt):
        reader.feed(kind, record)
    reader.finish()
    if reader.outcome not in FULL_OUTCOMES:
        raise ValueError("only a full cell (complete or stopped) has figures")
    first, last, final = reader.first_ms, reader.last_ms, reader.final
    if first is None or last is None or final is None:
        raise ValueError("a full cell needs hourly records and a final equity")
    end_ms = last + HOUR_MS if reader.outcome == OUTCOME_COMPLETE else last
    ending = _Ending(first, last, reader.marks, final, end_ms)
    keys = months(month_of(first), month_of(last))
    stray = sorted(set(reader.months) - set(keys))
    if stray:
        raise ValueError("a record's hour lies outside the cell's hours")
    month_rows = []
    for key in keys:
        start, end = month_bounds_ms(key)
        month = reader.months.get(key, _Month())
        month_rows.append(
            _period_row({"month": key}, ending.period(start, end), month.drawdown, month)
        )
    years = list(range(_year_of(first), _year_of(last) + 1))
    year_rows = []
    for year in years:
        total = _Month()
        for key in keys:
            if key.startswith(f"{year:04d}-") and key in reader.months:
                for whole, part in zip(total.tallies(), reader.months[key].tallies(), strict=True):
                    whole.merge(part)
        period = ending.period(_year_start(year), _year_start(year + 1))
        drawdown = reader.year_drawdowns.get(year, _Drawdown())
        year_rows.append(_period_row({"year": year}, period, drawdown, total))
    groups = reader.groups
    return {
        "record_count": reader.count,
        "years": year_rows,
        "months": month_rows,
        "sides": [
            _group_row(year, "side", side, groups["sides"].get((year, side), _Tally()))
            for year in years
            for side in SIDES
        ],
        "exit_reasons": [
            _group_row(year, "exit_reason", reason, tally)
            for (year, reason), tally in sorted(
                groups["exit_reasons"].items(),
                key=lambda item: (item[0][0], EXIT_REASONS.index(item[0][1])),
            )
        ],
        "coins": [
            _group_row(year, "coin", coin, tally)
            for (year, coin), tally in sorted(groups["coins"].items())
        ],
        "losing_trades": [
            _loser_row(year, loser)
            for year in years
            for _, _, loser in sorted(reader.losers.get(year, []), reverse=True)
        ],
        "holding_times": [
            _holding_row(year, label, groups["holding_times"].get((year, label), _Tally()))
            for year in years
            for label in HOLDING_TIMES
        ],
        "signals": [_signal_row(year, reader.signals.get(year, Counter())) for year in years],
    }


def _period_row(
    head: dict[str, Any], period: Mapping[str, Any], drawdown: _Drawdown, month: _Month
) -> dict[str, Any]:
    """A month's or a year's row: its period, drawdown, return against the trades, exposure,
    lifecycles, costs and counts."""
    net = month.lifecycles.sums.get("net_pnl", _ZERO)
    start, end = period["start_equity"], period["end_equity"]
    change = (
        None
        if start is None or end is None
        else to_fraction(Decimal(end)) - to_fraction(Decimal(start))
    )
    return {
        **head,
        **period,
        "max_drawdown": drawdown.value(),
        "equity_change": None if change is None else _exact(change),
        "open_trades_pnl": None if change is None else _exact(change - net),
        "exposure": _exposure_row(month.exposure),
        **_period_tallies(month.lifecycles, month.costs, month.events),
    }


def _exposure_row(exposure: _Tally) -> dict[str, Any]:
    counts, sums = exposure.counts, exposure.sums
    return {
        "hours": counts["hours"],
        "mean_gross_exposure": _mean(sums.get("gross", _ZERO), counts["gross_hours"]),
        "in_market_share": _ratio(counts["in_market_hours"], counts["hours"]),
        "decisions": counts["decisions"],
        "mean_long_weight": _mean(sums.get("long_weight", _ZERO), counts["decisions"]),
        "mean_short_weight": _mean(sums.get("short_weight", _ZERO), counts["decisions"]),
    }


def _loser_row(year: int, loser: _Loser) -> dict[str, Any]:
    return {
        "year": year,
        "coin": loser.coin,
        "side": loser.side,
        "entry_ms": loser.entry_ms,
        "exit_ms": loser.exit_ms,
        "opened": day_of(loser.entry_ms),
        "closed": day_of(loser.exit_ms),
        "hours_held": (loser.exit_ms - loser.entry_ms) // HOUR_MS,
        "net_pnl": _exact(loser.net),
        "exit_reason": loser.exit_reason,
        "given_back": _exact(loser.given_back),
    }


def _holding_row(year: int, label: str, tally: _Tally) -> dict[str, Any]:
    return {
        "year": year,
        "holding_time": label,
        "lifecycles": tally.counts["lifecycles"],
        "wins": tally.counts["wins"],
        "win_rate": _ratio(tally.counts["wins"], tally.counts["lifecycles"]),
        "net_pnl": tally.total("net_pnl"),
    }


def _period_tallies(lifecycles: _Tally, costs: _Tally, events: _Tally) -> dict[str, Any]:
    closed = lifecycles.counts["closed_long"] + lifecycles.counts["closed_short"]
    return {
        "lifecycles": {
            "opened_long": lifecycles.counts["opened_long"],
            "opened_short": lifecycles.counts["opened_short"],
            "closed_long": lifecycles.counts["closed_long"],
            "closed_short": lifecycles.counts["closed_short"],
            "wins": lifecycles.counts["wins"],
            "win_rate": _ratio(lifecycles.counts["wins"], closed),
            **{name: lifecycles.total(name) for name in _PERIOD_SUMS},
            "given_back": lifecycles.total("given_back"),
        },
        "costs": {
            "fills": costs.counts["fills"],
            "traded_notional": costs.total("traded_notional"),
            "fees": costs.total("fees"),
            "slippage": costs.total("slippage"),
            "synthetic_close_penalty": costs.total("synthetic_close_penalty"),
            "funding_records": costs.counts["funding_records"],
            "funding": costs.total("funding"),
        },
        "counts": {name: events.counts[name] for name in COUNT_NAMES},
    }


def _group_row(year: int, label: str, key: str, tally: _Tally) -> dict[str, Any]:
    row: dict[str, Any] = {
        "year": year,
        label: key,
        "lifecycles": tally.counts["lifecycles"],
        "wins": tally.counts["wins"],
    }
    if label == "side":
        row["win_rate"] = _ratio(tally.counts["wins"], tally.counts["lifecycles"])
    row.update({name: tally.total(name) for name in _GROUP_SUMS})
    return row


def _signal_row(year: int, counts: Counter[str]) -> dict[str, Any]:
    days = counts["coin_days"]
    return {
        "year": year,
        "coin_days": days,
        "decisions": counts["decisions"],
        "no_reading": _ratio(counts["no_reading"], days),
        "speeds": {
            speed: {
                "up": _ratio(counts[f"{speed}_up"], days),
                "down": _ratio(counts[f"{speed}_down"], days),
                "warming": _ratio(counts[f"{speed}_warming"], days),
                "flips": counts[f"{speed}_flips"],
            }
            for speed in SPEEDS
        },
        "confirmed_downtrend": _ratio(counts["confirmed_downtrend"], days),
        "short_positive": _ratio(counts["short_positive"], days),
        "long_fraction": {
            label: _ratio(counts[f"long_{label}"], days) for label in _LONG_LEVELS.values()
        },
        "mean_coins_with_target": _ratio(counts["coins_with_target"], counts["decisions"]),
    }


# ---- one cell folder ----------------------------------------------------------------------------


_REPEATED = "the cell repeats the cell of another folder"
_UNPLANNED = "the cell is not one of --planned"
_FAILED = "the diagnosis of the cell failed"


class CellRefused(Exception):
    """A cell folder that cannot be diagnosed: the step that failed and the exception."""

    def __init__(self, step: str, cause: BaseException) -> None:
        super().__init__(step)
        self.step = step
        self.cause = cause


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _timing(folder: Path, cell_id: str) -> dict[str, Any]:
    """The cell's ``timing.json`` (``scripts/v4_cells_timing.py``), all null when there is none:
    it must be the cell's own, and its records' size the size of ``records.jsonl``."""
    path = folder / TIMING_FILE
    if not path.exists():
        return {"cell": cell_id, "wall_seconds": None, "peak_rss_mb": None, "records_bytes": None}
    raw = path.read_bytes()
    if len(raw) > _MAX_TIMING_BYTES:
        raise ValueError("timing.json is too large")
    document = json.loads(raw.decode("ascii"), parse_float=Decimal, object_pairs_hook=_unique_keys)
    if not isinstance(document, dict) or set(document) != _TIMING_KEYS:
        raise ValueError("timing.json does not hold exactly the timing helper's four keys")
    if document["cell"] != cell_id:
        raise ValueError("timing.json is of another cell")
    numbers = {}
    for key in ("wall_seconds", "peak_rss_mb"):
        value = document[key]
        if type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0:
            raise ValueError(f"timing.json's {key} is not a non-negative number")
        numbers[key] = str(value)
    size = document["records_bytes"]
    if type(size) is not int or size != (folder / RECORDS_FILE).stat().st_size:
        raise ValueError("timing.json's records_bytes is not the size of records.jsonl")
    return {"cell": cell_id, **numbers, "records_bytes": size}


class _Step:
    """Turns any exception inside it into a ``CellRefused`` naming ``step``."""

    def __init__(self, step: str) -> None:
        self.step = step

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: object, exc: BaseException | None, traceback: object) -> None:
        if isinstance(exc, Exception) and not isinstance(exc, CellRefused):
            raise CellRefused(self.step, exc) from None


def diagnose_cell(
    folder: Path, market: Market, prices: _Prices | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One cell folder, checked (module docstring, step 3), and its diagnosis: the cell's
    entry and its timing. Every refusal is a ``CellRefused``."""
    with _Step("reading summary.json failed"):
        raw = (folder / SUMMARY_FILE).read_bytes()
        summary = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_keys)
        if not isinstance(summary, dict):
            raise ValueError("summary.json is not a JSON object")
    with _Step("summary.json is not canonical JSON"):
        if _canonical(summary) != raw:
            raise ValueError("summary.json is not canonical JSON")
    with _Step("reading receipt.json failed"):
        receipt = read_receipt(folder / RECEIPT_FILE)
        receipt_sha256 = _digest((folder / RECEIPT_FILE).read_bytes())
    records = folder / RECORDS_FILE
    with _Step("the summary does not verify against the records and the receipt"):
        verify_summary(summary, records, receipt)
    cell = summary["cell"]
    with _Step("the cell was replayed on other packs than --data"):
        if summary["data"] != data_record(market.pins) or summary["window"] != window_record(
            market
        ):
            raise ValueError("the cell's data pins or window are not the packs'")
    with _Step("timing.json is not the cell's"):
        timing = _timing(folder, cell["id"])
    entry: dict[str, Any] = {
        "cell": cell,
        "outcome": summary["outcome"],
        "reason": summary.get("reason"),
        "stop_ms": summary.get("stop_ms"),
        "record_count": receipt.record_count,
        "receipt_sha256": receipt_sha256,
    }
    if summary["outcome"] not in FULL_OUTCOMES:
        return {**entry, **dict.fromkeys(FIGURE_NAMES)}, timing
    with _Step("reading the records for the diagnosis failed"):
        figures = cell_figures(records, receipt)
        if figures["record_count"] != receipt.record_count:
            raise ValueError("the pass did not read every record")
    with _Step("the diagnosis' years are not the summary's"):
        mine = [{key: year[key] for key in _YEAR_KEYS} for year in figures["years"]]
        if mine != summary["years"]:
            raise ValueError("the diagnosis' years are not the summary's")
    with _Step("the market's returns over the cell's periods could not be computed"):
        _beside_the_market(figures, prices or _Prices(market))
    return {**entry, **{name: figures[name] for name in FIGURE_NAMES}}, timing


def _beside_the_market(figures: Mapping[str, Any], prices: _Prices) -> None:
    """The market over each of the cell's own periods (module docstring): ``btc_return`` on its
    months and years, ``universe_median_return`` on its years and ``coin_return`` on its by-coin
    rows, each over the period's ``start_ms`` to ``end_ms``."""
    spans: dict[int, tuple[int, int]] = {}
    for label, month in (("months", True), ("years", False)):
        for row in figures[label]:
            start, end = row["start_ms"], row["end_ms"]
            if start is None or end is None:
                row["btc_return"] = None
                if not month:
                    row["universe_median_return"] = None
                continue
            row["btc_return"] = _text(prices.closed_return(BTC, start, end, month=month))
            if not month:
                row["universe_median_return"] = _text(prices.median_return(start, end))
                spans[row["year"]] = (start, end)
    for row in figures["coins"]:
        span = spans.get(row["year"])
        found = None if span is None else prices.closed_return(row["coin"], *span)
        row["coin_return"] = _text(found)


# ---- the market regime --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Daily:
    """One coin's daily bars as two columns, and the opens of the bars whose close crossed the
    SMA20 (from the side of the last bar before that was not on it)."""

    opens: list[int]
    closes: list[Decimal]
    crossings: list[int]

    @classmethod
    def of(cls, market: Market, symbol: str) -> _Daily:
        bars = market.daily(symbol)
        opens = [bar.open_ms for bar in bars]
        closes = [bar.close for bar in bars]
        crossings: list[int] = []
        last_side = 0
        total = Decimal(0)
        with localcontext(CONTEXT):
            for index, close in enumerate(closes):
                total += close
                if index >= SMA_SHORT:
                    total -= closes[index - SMA_SHORT]
                if index < SMA_SHORT - 1:
                    continue
                scaled = close * SMA_SHORT
                side = (scaled > total) - (scaled < total)
                if side and last_side and side != last_side:
                    crossings.append(opens[index])
                if side:
                    last_side = side
        return cls(opens, closes, crossings)

    def last_in(self, start: int, end: int) -> int | None:
        """The index of the month's last bar, or None without a bar in it."""
        last = bisect_left(self.opens, end) - 1
        return None if last < 0 or self.opens[last] < start else last

    def month_return(self, start: int, end: int) -> Decimal | None:
        last = self.last_in(start, end)
        before = bisect_left(self.opens, start) - 1
        if last is None or before < 0:
            return None
        with localcontext(CONTEXT):
            return self.closes[last] / self.closes[before] - 1

    def against_sma200(self, start: int, end: int) -> tuple[str | None, Decimal | None]:
        last = self.last_in(start, end)
        if last is None or last + 1 < SMA_LONG:
            return None, None
        close = self.closes[last]
        with localcontext(CONTEXT):
            total = sum(self.closes[last + 1 - SMA_LONG : last + 1], Decimal(0))
            scaled = close * SMA_LONG
            ratio = scaled / total - 1
        side = "above" if scaled > total else "below" if scaled < total else "equal"
        return side, ratio

    def volatility(self, start: int, end: int) -> Decimal | None:
        last = self.last_in(start, end)
        if last is None:
            return None
        first = max(bisect_left(self.opens, self.opens[last] - (VOLATILITY_DAYS - 1) * DAY_MS), 1)
        with localcontext(CONTEXT):
            changes = [
                self.closes[index] / self.closes[index - 1] - 1 for index in range(first, last + 1)
            ]
            if len(changes) < 2:
                return None
            mean = sum(changes, Decimal(0)) / len(changes)
            variance = sum(((change - mean) ** 2 for change in changes), Decimal(0)) / (
                len(changes) - 1
            )
            return variance.sqrt() * Decimal(DAYS_PER_YEAR).sqrt()

    def crossings_in(self, start: int, end: int) -> int | None:
        last = self.last_in(start, end)
        if last is None or last < SMA_SHORT - 1:
            return None
        return bisect_left(self.crossings, end) - bisect_left(self.crossings, start)

    def span_return(self, start: int, end: int) -> Decimal | None:
        """The span's last close over the last close before it, minus 1; from the span's first
        close for a coin with no bar before it; None with fewer than two closes to compare."""
        last = self.last_in(start, end)
        if last is None:
            return None
        base = bisect_left(self.opens, start) - 1
        if base < 0:
            base = bisect_left(self.opens, start)
            if base == last:
                return None
        with localcontext(CONTEXT):
            return self.closes[last] / self.closes[base] - 1


class _Prices:
    """Each coin's daily bars as ``_Daily``, built once per symbol, and the year spans the
    diagnosis measures a year's returns over: the part of the year inside the window."""

    def __init__(self, market: Market) -> None:
        self.market = market
        self._cache: dict[str, _Daily] = {}

    def daily(self, symbol: str) -> _Daily:
        if symbol not in self._cache:
            self._cache[symbol] = _Daily.of(self.market, symbol)
        return self._cache[symbol]

    def year_span(self, year: int) -> tuple[int, int]:
        return max(_year_start(year), self.market.window_start_ms), _year_start(year + 1)

    def year_return(self, symbol: str, year: int) -> Decimal | None:
        """``symbol``'s return over the year's span (module docstring), None without the coin."""
        if symbol not in self.market.symbols:
            return None
        return self.daily(symbol).span_return(*self.year_span(year))

    def closed_return(
        self, symbol: str, start: int, end: int, *, month: bool = False
    ) -> Decimal | None:
        """``symbol``'s return over ``start`` to ``end`` from the daily closes made by ``end``
        (a bar opening at or before ``end - DAY_MS``), as a month's (``month_return``) or a
        year's (``span_return``); None without the coin. Over a whole month or year, which ends
        at 00:00 UTC, these are the bars ``month_return`` and ``span_return`` read anyway."""
        if symbol not in self.market.symbols:
            return None
        daily, closed_by = self.daily(symbol), end - DAY_MS + 1
        if month:
            return daily.month_return(start, closed_by)
        return daily.span_return(start, closed_by)

    def median_return(self, start: int, end: int) -> Decimal | None:
        """The median of a year's ``closed_return`` over ``start`` to ``end`` of the coins in
        the universe in any month the span touches (``start``'s to ``end - 1``'s)."""
        keys = months(month_of(start), month_of(end - 1))
        coins = {coin for key in keys for coin in self.market.universe(key)}
        returns = [
            change
            for change in (self.closed_return(coin, start, end) for coin in sorted(coins))
            if change is not None
        ]
        return _median(returns)


def _median(values: Sequence[Decimal]) -> Decimal | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    with localcontext(CONTEXT):
        return (ordered[middle - 1] + ordered[middle]) / 2


def market_regime(market: Market, prices: _Prices | None = None) -> list[dict[str, Any]]:
    """The market regime of every month from the window's first to ``end_month`` (module
    docstring), each from daily bars of that month and before it."""
    daily = (prices or _Prices(market)).daily
    btc = daily(BTC) if BTC in market.symbols else None
    rows: list[dict[str, Any]] = []
    for key in months(month_of(market.window_start_ms), market.end_month):
        start, end = month_bounds_ms(key)
        side, ratio = btc.against_sma200(start, end) if btc is not None else (None, None)
        coins = market.universe(key)
        returns = [
            change
            for change in (daily(coin).month_return(start, end) for coin in coins)
            if change is not None
        ]
        rows.append(
            {
                "month": key,
                "btc_return": _text(None if btc is None else btc.month_return(start, end)),
                "btc_vs_sma200": side,
                "btc_close_over_sma200": _text(ratio),
                "btc_volatility_30d_annualised": _text(
                    None if btc is None else btc.volatility(start, end)
                ),
                "btc_sma20_crossings": None if btc is None else btc.crossings_in(start, end),
                "universe_coins": len(coins),
                "universe_coins_with_return": len(returns),
                "universe_median_return": _text(_median(returns)),
            }
        )
    return rows


def market_years(market: Market, prices: _Prices | None = None) -> list[dict[str, Any]]:
    """The market of every year from the window's first to ``end_month``'s (module docstring):
    BTCUSDT's return over the year's span, and the median return of the coins in the universe in
    any month of it."""
    prices = prices or _Prices(market)
    keys = months(month_of(market.window_start_ms), market.end_month)
    rows: list[dict[str, Any]] = []
    for year in range(_year_of(market.window_start_ms), int(market.end_month[:4]) + 1):
        coins = sorted(
            {
                coin
                for key in keys
                if key.startswith(f"{year:04d}-")
                for coin in market.universe(key)
            }
        )
        returns = [
            change
            for change in (prices.year_return(coin, year) for coin in coins)
            if change is not None
        ]
        rows.append(
            {
                "year": year,
                "btc_return": _text(prices.year_return(BTC, year)),
                "universe_coins": len(coins),
                "universe_coins_with_return": len(returns),
                "universe_median_return": _text(_median(returns)),
            }
        )
    return rows


# ---- the arms ---------------------------------------------------------------------------------


def _whole_percent(value: Decimal) -> str:
    with localcontext(CONTEXT):
        return f"{(value * 100).normalize():f}%"


def describe_arm(spec: ArmSpec, widest_universe: int) -> str:
    """One plain line on what an arm of ``arms.ARMS`` does, from its own figures."""
    invested = _whole_percent(HOLD_INVESTED)
    if spec.family == "v3":
        return (
            "V3's walk-forward selector, unchanged, on its own coins and inputs (V3's data end in "
            "2024), a comparison with V4."
        )
    if spec.family == "hold":
        if spec.name == "hold_btc":
            return (
                f"no signal, spot only: {invested} of the account in {BTC} from the first hour, "
                "held to the end."
            )
        if spec.name == "hold_btc_trend":
            return (
                f"spot only, with BTC's trend as its only signal: {invested} of the account in "
                f"{BTC} while its daily close is above its {MAIN_LOOKBACKS.slow}-day average, "
                "else cash; it trades only when that changes."
            )
        return (
            f"no signal, spot only: {invested} of the account split equally across the month's "
            f"universe (the top coins by trading volume, at most {widest_universe} in these "
            "packs), rebalanced at each month's start."
        )
    lookbacks, target = spec.lookbacks, spec.vol_target
    if lookbacks is None or target is None:
        raise ValueError(f"the V4 arm {spec.name} has no lookbacks or volatility target")
    sides = (
        "long only (on spot, never short)"
        if spec.long_only
        else "long and short (longs on spot first, shorts on futures)"
    )
    if lookbacks == MAIN_LOOKBACKS:
        windows = "the main trend windows"
    elif lookbacks.slow < MAIN_LOOKBACKS.slow:
        windows = "shorter trend windows than the main ones"
    else:
        windows = "longer trend windows than the main ones"
    rules = ""
    if spec.short_filter == "btc_sma200":
        rules += (
            f" It is short only while BTC is below its {lookbacks.slow}-day average (otherwise "
            "a short is closed; longs keep their signals, though their sizes can still change "
            "through the book's common scale and caps)."
        )
    if spec.confirm_readings is not None:
        rules += f" It acts on a new direction only after {spec.confirm_readings} days in a row."
    return (
        f"the trend bot, {sides}, sized to a {_whole_percent(target)} volatility target, with "
        f"{windows}: fast {lookbacks.fast} days, medium {lookbacks.ema_fast}/{lookbacks.ema_slow} "
        f"days, slow {lookbacks.slow} days.{rules}"
    )


def arm_rows(market: Market) -> list[dict[str, str]]:
    """Every arm of ``ARMS``, in order, with its plain line."""
    keys = months(month_of(market.window_start_ms), market.end_month)
    widest = max((len(market.universe(key)) for key in keys), default=0)
    return [{"arm": name, "description": describe_arm(spec, widest)} for name, spec in ARMS.items()]


# ---- the markdown -------------------------------------------------------------------------------


def _rounded(value: object, *, percent: bool = False, signed: bool = False) -> str:
    """Two decimals, half to even, with thousands separators (for reading only)."""
    if value is None:
        return "n/a"
    try:
        number = Decimal(str(value))
        with localcontext(CONTEXT):
            if percent:
                number *= 100
            shown = format(number.quantize(Decimal("0.01")), "+,f" if signed else ",f")
    except InvalidOperation:
        return str(value)
    return f"{shown}%" if percent else shown


def _pct(value: object) -> str:
    return _rounded(value, percent=True, signed=True)


def _share(value: object) -> str:
    return _rounded(value, percent=True)


def _table(head: Sequence[str], rows: Iterable[Sequence[object]], *, text: int = 1) -> list[str]:
    """A Markdown table; its first ``text`` columns align left and the rest, numbers, right."""
    lines = [
        "| " + " | ".join(head) + " |",
        "|" + "|".join([":---"] * text + ["---:"] * (len(head) - text)) + "|",
    ]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return [*lines, ""]


def _days(hours: object) -> str:
    """Hours as days, for reading."""
    if type(hours) is not int:
        return "n/a"
    with localcontext(CONTEXT):
        return _rounded(Decimal(hours) / 24)


def _period_tables(rows: Sequence[Mapping[str, Any]], label: str) -> list[str]:
    """A cell's tables for its years or for the months of one year, each row beside its own
    ``btc_return``."""
    head = label.capitalize()
    lines = [
        "Equity (USDT), beside BTCUSDT's own return over the same period (for a stopped cell's "
        "last period, up to the stop):",
        "",
    ]
    lines += _table(
        (head, "Start equity", "End equity", "Return", "BTC return", "Max drawdown"),
        (
            (
                row[label],
                _rounded(row["start_equity"]),
                _rounded(row["end_equity"]),
                _pct(row["return"]),
                _pct(row["btc_return"]),
                _share(row["max_drawdown"]),
            )
            for row in rows
        ),
    )
    lines += [
        "Return against the trades (USDT). A trade counts in the period it closed, with all its "
        "P&L, so the equity change and the net P&L of the trades closed in the period differ by "
        "the profit or loss on trades still open at the period's start or end.",
        "",
    ]
    lines += _table(
        (
            head,
            "Equity change",
            "Net P&L of trades closed",
            "P&L on trades still open at the start or end",
        ),
        (
            (
                row[label],
                _rounded(row["equity_change"]),
                _rounded(row["lifecycles"]["net_pnl"]),
                _rounded(row["open_trades_pnl"]),
            )
            for row in rows
        ),
    )
    lines += [
        "Exposure: how much the bot held (longs and shorts together, as a multiple of equity), "
        "how often it held anything, and the long and short weights it wanted at its daily "
        "decisions (shares of equity; n/a for a hold arm, which makes none):",
        "",
    ]
    lines += _table(
        (
            head,
            "Mean gross exposure (x equity)",
            "Hours in the market",
            "Mean long weight",
            "Mean short weight",
        ),
        (
            (
                row[label],
                _rounded(exposure["mean_gross_exposure"]),
                _share(exposure["in_market_share"]),
                _share(exposure["mean_long_weight"]),
                _share(exposure["mean_short_weight"]),
            )
            for row in rows
            for exposure in (row["exposure"],)
        ),
    )
    lines += [
        "Lifecycles (trades), each counted in the period it closed, with all its money (USDT). "
        "Net P&L = Gross profit + Gross loss - Fees + Funding (Gross loss is negative), and the "
        "win rate is the share of closed trades whose net P&L is above 0.",
        "",
    ]
    lines += _table(
        (
            head,
            "Opened long",
            "Opened short",
            "Closed long",
            "Closed short",
            "Win rate",
            "Gross profit",
            "Gross loss",
            "Fees",
            "Funding",
            "Net P&L",
            "Given back",
        ),
        (
            (
                row[label],
                lc["opened_long"],
                lc["opened_short"],
                lc["closed_long"],
                lc["closed_short"],
                _share(lc["win_rate"]),
                _rounded(lc["gross_profit"]),
                _rounded(lc["gross_loss"]),
                _rounded(lc["fees"]),
                _rounded(lc["funding"]),
                _rounded(lc["net_pnl"]),
                _rounded(lc["given_back"]),
            )
            for row in rows
            for lc in (row["lifecycles"],)
        ),
    )
    lines += [
        "Costs, counted in the period they were paid (USDT; funding received is positive). "
        "These fees and funding are the same money as the lifecycle table's, which books them "
        "when the trade closed: two views of one amount, so never add the two tables together. "
        "Slippage and the synthetic-close penalty are already inside the trades' gross P&L.",
        "",
    ]
    lines += _table(
        (
            head,
            "Fills",
            "Traded notional",
            "Fees",
            "Slippage",
            "Synthetic-close penalty",
            "Funding records",
            "Funding",
        ),
        (
            (
                row[label],
                costs["fills"],
                _rounded(costs["traded_notional"]),
                _rounded(costs["fees"]),
                _rounded(costs["slippage"]),
                _rounded(costs["synthetic_close_penalty"]),
                costs["funding_records"],
                _rounded(costs["funding"]),
            )
            for row in rows
            for costs in (row["costs"],)
        ),
    )
    lines += ["Events (the two close columns count legs, not coins):", ""]
    lines += _table(
        (
            head,
            "Margin cuts",
            "Ceiling cuts",
            "Dead-market closes",
            "Funding-month closes",
            "Deferrals",
            "Refused orders",
            "Cash-clip cuts",
            "Band skips",
        ),
        ((row[label], *(row["counts"][name] for name in COUNT_NAMES)) for row in rows),
    )
    return lines


def _group_table(rows: Sequence[Mapping[str, Any]], label: str, title: str) -> list[str]:
    if not rows:
        return ["No lifecycle ended.", ""]
    rate, coin = label == "side", label == "coin"
    head = ["Year", title, *(["Coin's own return"] if coin else []), "Lifecycles", "Wins"]
    head += [*(["Win rate"] if rate else []), "Gross P&L", "Fees", "Funding", "Net P&L"]
    head.append("Given back")
    return _table(
        head,
        (
            (
                row["year"],
                row[label],
                *([_pct(row["coin_return"])] if coin else []),
                row["lifecycles"],
                row["wins"],
                *([_share(row["win_rate"])] if rate else []),
                *(_rounded(row[name]) for name in _GROUP_SUMS),
            )
            for row in rows
        ),
        text=2,
    )


def _loser_tables(rows: Sequence[Mapping[str, Any]], years: Sequence[int]) -> list[str]:
    lines = [
        f"The {LOSERS_PER_YEAR} trades closed in each year with the largest net loss (fewer when "
        "fewer lost), the worst first. Opened and Closed are UTC days; Given back is how far the "
        "trade's gross P&L fell from its best point (glossary).",
        "",
    ]
    for year in years:
        mine = [row for row in rows if row["year"] == year]
        lines += [f"{year}:", ""]
        if not mine:
            lines += ["No trade closed at a loss.", ""]
            continue
        lines += _table(
            (
                "Coin",
                "Side",
                "Opened",
                "Closed",
                "Days held",
                "Net P&L",
                "Exit reason",
                "Given back",
            ),
            (
                (
                    row["coin"],
                    row["side"],
                    row["opened"],
                    row["closed"],
                    _days(row["hours_held"]),
                    _rounded(row["net_pnl"]),
                    row["exit_reason"],
                    _rounded(row["given_back"]),
                )
                for row in mine
            ),
            text=4,
        )
    return lines


def _holding_table(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [
        "The trades closed each year, by how long they were held. Many short trades losing "
        "money in a year point to back-and-forth trading: the trend readings flipping, and the "
        "bot buying and selling back again.",
        "",
    ]
    return lines + _table(
        ("Year", "Held", "Trades", "Win rate", "Net P&L"),
        (
            (
                row["year"],
                row["holding_time"],
                row["lifecycles"],
                _share(row["win_rate"]),
                _rounded(row["net_pnl"]),
            )
            for row in rows
        ),
        text=2,
    )


def _signal_tables(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not any(row["coin_days"] for row in rows):
        return ["No daily records: a hold arm has no signal.", ""]
    lines = ["Speeds, as shares of the coin-days (warming: no reading, warming up or a tie):", ""]
    lines += _table(
        ("Year", "Speed", "Up", "Down", "Warming", "Flips"),
        (
            (
                row["year"],
                speed,
                _share(row["speeds"][speed]["up"]),
                _share(row["speeds"][speed]["down"]),
                _share(row["speeds"][speed]["warming"]),
                row["speeds"][speed]["flips"],
            )
            for row in rows
            for speed in SPEEDS
        ),
        text=2,
    )
    lines += ["Levels, as shares of the coin-days:", ""]
    lines += _table(
        (
            "Year",
            "Coin-days",
            "Decisions",
            "No reading",
            "Confirmed downtrend",
            "S > 0",
            "L = 0",
            "L = 1/3",
            "L = 2/3",
            "L = 1",
            "Mean coins with a target",
        ),
        (
            (
                row["year"],
                row["coin_days"],
                row["decisions"],
                _share(row["no_reading"]),
                _share(row["confirmed_downtrend"]),
                _share(row["short_positive"]),
                *(_share(row["long_fraction"][label]) for label in _LONG_LEVELS.values()),
                _rounded(row["mean_coins_with_target"]),
            )
            for row in rows
        ),
    )
    return lines


def _negative(value: object) -> bool:
    return value is not None and Decimal(str(value)) < 0


def _headline(document: Mapping[str, Any]) -> list[str]:
    """The page's first section: every cell's year beside the market's, each cell's losing
    years, and one plain line per arm."""
    market = {row["year"]: row for row in document["market_years"]}
    cells = document["cells"]
    years = sorted({*market, *(y["year"] for cell in cells for y in cell["years"] or ())})
    lines = [
        "## Headline",
        "",
        "Each cell's return and largest fall from a high (max DD) in each calendar year, beside "
        "the market's: BTC is BTCUSDT's own price change over the year, and Median coin the "
        "middle yearly price change of the coins in the bot's universe that year. The window's "
        "first year is measured from the window's start, and a stopped cell's last year ends at "
        "the stop, while BTC and Median coin are the whole year's: the lines under the table "
        "compare a stopped cell's last year with the market over the same span. Trades count in "
        "the year they closed (glossary), so a year's return and its trades' P&L can differ; "
        "each cell's Years section reconciles the two.",
        "",
    ]
    head = ["Year", "BTC", "Median coin"]
    for cell in cells:
        head += [f"{cell['cell']['id']} return", f"{cell['cell']['id']} max DD"]
    body: list[list[object]] = []
    for year in years:
        shown = market.get(year, {})
        line: list[object] = [
            year,
            _pct(shown.get("btc_return")),
            _pct(shown.get("universe_median_return")),
        ]
        for cell in cells:
            found = {row["year"]: row for row in cell["years"] or ()}.get(year)
            line += (
                ["n/a", "n/a"]
                if found is None
                else [_pct(found["return"]), _share(found["max_drawdown"])]
            )
        body.append(line)
    lines += _table(head, body)
    # A stopped cell's last year with a period: a stop at 00:00 on 1 January before that hour's
    # open mark leaves the new year's row all null, and the year before ends at the stop.
    stopped: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for cell in cells:
        periods = [row for row in cell["years"] or () if row["start_ms"] is not None]
        if cell["stop_ms"] is not None and periods:
            stopped.append((cell, periods[-1]))
    if stopped:
        lines += [
            "Stopped cells: the last year to the stop, and the market over the same span:",
            "",
        ]
        for cell, last in stopped:
            lines.append(
                f"- {cell['cell']['id']} stopped at {_when(cell['stop_ms'])}: {last['year']} to "
                f"the stop {_pct(last['return'])}; BTC {_pct(last['btc_return'])}, median coin "
                f"{_pct(last['universe_median_return'])}."
            )
        lines.append("")
    lines += ["Losing years (a negative return):", ""]
    if not cells:
        lines.append("- No cell was diagnosed (see Missing cells).")
    for cell in cells:
        ident = cell["cell"]["id"]
        if cell["years"] is None:
            lines.append(f"- {ident}: no figures (outcome {cell['outcome']}).")
            continue
        losing = [row for row in cell["years"] if _negative(row["return"])]
        if not losing:
            lines.append(f"- {ident}: no losing year.")
            continue
        named = ", ".join(f"{row['year']} ({_pct(row['return'])})" for row in losing)
        lines.append(f"- {ident}: lost money in {named}.")
    lines += ["", "The arms (a cell is an arm at one starting capital and one cost level):", ""]
    lines += [f"- **{row['arm']}**: {row['description']}" for row in document["arms"]]
    return [*lines, ""]


GLOSSARY: tuple[str, ...] = (
    "## Glossary",
    "",
    "- **Period**: a calendar month or year (UTC). Its start equity is the account's value at "
    "the first hour of the period, its end equity the value at the first hour of the next period "
    "(the final value at the end of the run). Return = end / start - 1.",
    "- **Max drawdown** (max DD): the largest fall from a high to a later low inside the period, "
    "from the hourly values, as a share of that high.",
    "- **BTC, BTC return**: BTCUSDT's own price change over the same period, from its last daily "
    "close before the period to its last close in it (for a stopped cell's last period, its last "
    "daily close before the stop). **Median coin**: the middle yearly price change of the coins "
    "that were in the universe in any month of the year, each measured the same way (from its "
    "first close in the year when it started trading that year). **Coin's own return** (by "
    "coin): that coin's price change over the cell's year, measured the same way.",
    "- **Lifecycle** (a trade): one position in one coin on one side, long or short, from when "
    "it opens to when it is closed, over spot and futures together. A trade counts in the month "
    "and the year in which it closed, with all its profit, fees and funding, even if it opened "
    "earlier; only the Opened columns count it where it opened.",
    "- **Equity change**: end equity minus start equity, in USDT. **Net P&L of trades closed**: "
    "the net P&L of the trades that closed in the period. **P&L on trades still open at the "
    "start or end**: the difference between the two, the profit or loss on trades still open at "
    "the period's start or end. Because trades count when they close, a year can show a negative "
    "return and a positive trade P&L, or the reverse: a trade that gained in one year and closed "
    "in the next counts wholly in the next, while its gain was already in the first year's "
    "return.",
    "- **Gross profit, Gross loss**: the trades' price gains and losses before fees and funding, "
    "summed over the trades that gained and over those that lost (shown negative).",
    "- **Net P&L** = Gross profit + Gross loss - Fees + Funding. **Win rate**: the share of "
    "closed trades whose net P&L is above 0.",
    "- **Given back**: how far a trade's gross P&L fell from its best point before it ended: its "
    "best gross P&L along the way (realised plus unrealised, best_unrealised) minus its final "
    "gross P&L, summed over the trades. Like the gross P&L, it is before fees and funding.",
    "- **Mean gross exposure**: the average, over the period's hours, of everything held (longs "
    "and shorts together, at market value) divided by the account's value: 1.00 means positions "
    "as large as the account, 0 means all cash. **Hours in the market**: the share of hours in "
    "which that exposure was at least 1% of the account, so the unsellable remainders a sale "
    "leaves (dust) do not count.",
    "- **Mean long weight, Mean short weight**: the positions the bot wanted at its daily "
    "decisions, as shares of the account, summed over the coins (longs, and shorts as positive "
    "sizes) and averaged over the period's decisions. A coin with no new target that day keeps "
    "its last one. A hold arm makes no daily decision, so it shows n/a.",
    "- **Biggest losing trades**: per year, the 10 trades closed that year with the most "
    "negative net P&L. **Days held**: from the hour it opened to the hour it closed.",
    "- **Held** (holding time): the trades closed in a year grouped by how long they were held: "
    "under 1 week (under 7 days), 1 to 4 weeks (7 to 28 days), 1 to 3 months (28 to 91 days) and "
    "over 3 months (91 days or more).",
    "- **Fees** are the exchange's. **Funding** is the futures funding payment: positive when "
    "the account received money, negative when it paid. The lifecycle tables book fees and "
    "funding when a trade closes, the costs tables when they are paid: the same money seen two "
    "ways, so never add the two together.",
    "- **Slippage**: what each fill lost to the price moving against it, the gap between the "
    "price paid and the market's opening price, times the quantity.",
    "- **Synthetic-close penalty**: when a market stops trading (no price for 168 hours, a dead "
    "market), the position is closed at its last price less 10% (plus 10% for a short). A "
    "futures position whose next funding month is incomplete is normally closed before that "
    "month at normal costs; the penalty applies to it only when the perpetual had no bar before "
    "the month to close at. This is that 10%: the gap between the last price and the close "
    "price, times the quantity. Slippage and this penalty are already inside the trades' gross "
    "P&L.",
    "- **Traded notional**: the value of everything bought and sold.",
    "- **Dead-market closes, Funding-month closes**: how many positions were closed that way. "
    "They count legs, not coins: a coin held on both spot and futures counts twice. When the "
    "close prices themselves liquidate the account (its futures margin backing falls to the "
    "maintenance margin), the run ends before anything is closed, so those legs are not "
    "counted; their penalty still is, since the final value uses those prices.",
    "- **Margin cuts, Ceiling cuts**: times the account cut its positions because the futures "
    "margin ran low, or because the total exposure went above 3 times the equity.",
    "- **Deferrals**: daily orders that could not fill in the hour after their decision, "
    "counted when they end: filled later, replaced by a newer decision, or cancelled. So this "
    "report also counts orders kept over a day with no daily bar (the coin got no new "
    "decision) and orders cancelled because the coin's market died.",
    "- **Refused orders**: planned buys or position increases below the exchange's minimum "
    "size or value, so no order was sent (one per leg).",
    "- **Cash-clip cuts**: buys or increases made smaller, or dropped, because the free cash or "
    "margin did not cover them.",
    "- **Band skips**: daily orders not traded because the new target was close enough to the "
    "position held (inside the no-trade band), which saves costs.",
    "- **Speeds** (fast, medium, slow): the three trend readings of each coin from its daily "
    "closes. Up and Down are the shares of coin-days a reading pointed up or down; "
    "**Warming** means neither: not enough history yet, no reading at all, or an exact tie. "
    "**Flips**: how often a reading turned from up to down or back.",
    "- **Coin-day**: one coin at one daily decision. **Mean coins with a target**: how many "
    "coins the bot wanted a position in, on average per daily decision; as for the weights, a "
    "coin with no new target that day keeps its last one.",
    "- **L**: the long fraction, the number of speeds that are up divided by 3 (0, 1/3, 2/3 "
    "or 1). **S**: the short fraction, above 0 (0.25, 0.5 or 1) only when the medium speed is "
    "down and a downtrend is confirmed.",
    "- **Confirmed downtrend**: the close is below its trend average, that average is falling, "
    "and the recent highs and lows are both lower than the ones before.",
    "- **Market regime**: BTC return is BTCUSDT's change over the month. BTC vs SMA200 says "
    "whether the month's last close was above or below the average of its last 200 daily "
    "closes, and Close / SMA200 - 1 by how much. BTC volatility (30 days, annualised) is how "
    "much BTC's daily price moved over the last 30 days, scaled to a year. SMA20 crossings "
    "counts the times in the month the close crossed its 20-day average: many crossings mean "
    "a choppy market with no clear trend. Median coin return is the middle monthly return of "
    "the month's universe coins. Each month uses prices up to its own end only.",
    "",
)


def _missing_section(missing: Mapping[str, Any]) -> list[str]:
    """The folders without a summary, the cell folders refused and the planned cells with
    none."""
    lines = ["## Missing cells", ""]
    folders, refused, cells = (
        missing["folders_without_summary"],
        missing["refused"],
        missing["cells"],
    )
    if not folders and not refused and not cells:
        return [*lines, "None: every cell this run planned was diagnosed.", ""]
    if folders:
        lines += ["Folders of --cells without a summary.json:", ""]
        lines += [f"- `{name}`" for name in folders]
        lines.append("")
    if refused:
        lines += [
            "Cell folders refused, each with the check that failed and the type of the error "
            "(its text is never shown); the other cells are diagnosed:",
            "",
        ]
        lines += [f"- `{row['folder']}`: {row['step']} ({row['error']})" for row in refused]
        lines.append("")
    if cells:
        lines += [
            "Cells this run planned that have no diagnosis (failed, timed out or refused):",
            "",
        ]
        lines += [f"- {cell}" for cell in cells]
        lines.append("")
    return lines


def _when(ms: object) -> str:
    if type(ms) is not int:
        return "n/a"
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")


def render_markdown(document: Mapping[str, Any]) -> str:
    """``diagnosis.md``: the headline, the glossary, the timing, the missing cells, the market
    regime, then one section per cell (its years, its months year by year, its biggest losing
    trades and holding times, then the breakdowns and the signals), rounded for reading."""
    data, window = document["data"], document["window"]
    lines = [
        "# V4 diagnosis",
        "",
        f"Data: end month {data['end_month']}, config_sha256 `{data['config_sha256']}`. "
        f"Window: {_when(window['start_ms'])} to {_when(window['end_ms'])}. "
        f"Cells: {len(document['cells'])}.",
        "",
        "Rounded for reading; diagnosis.json holds the exact values. Fills, funding and events "
        "count in the hour they happen; a trade counts in the period it closed; signals in the "
        "year of the decision.",
        "",
        *_headline(document),
        *GLOSSARY,
        "## Timing",
        "",
    ]
    lines += _table(
        ("Cell", "Wall seconds", "Peak MB", "Records bytes"),
        (
            (
                row["cell"],
                "n/a" if row["wall_seconds"] is None else row["wall_seconds"],
                "n/a" if row["peak_rss_mb"] is None else row["peak_rss_mb"],
                "n/a" if row["records_bytes"] is None else f"{row['records_bytes']:,}",
            )
            for row in document["timing"]
        ),
    )
    lines += [
        "The diagnosis's own wall time and peak memory are in diagnose-timing.json beside this "
        "page (the workflow writes it after the diagnosis ends).",
        "",
    ]
    lines += _missing_section(document["missing"])
    lines += [
        "## Market regime",
        "",
        "By year: BTCUSDT's return, and the median yearly return of the coins in the universe "
        "in any month of the year:",
        "",
    ]
    lines += _table(
        ("Year", "BTC return", "Universe coins", "With a return", "Median coin return"),
        (
            (
                row["year"],
                _pct(row["btc_return"]),
                row["universe_coins"],
                row["universe_coins_with_return"],
                _pct(row["universe_median_return"]),
            )
            for row in document["market_years"]
        ),
    )
    lines += [
        "By month: BTCUSDT, and the median of the month's universe; each month from prices up to "
        "its end:",
        "",
    ]
    lines += _table(
        (
            "Month",
            "BTC return",
            "BTC vs SMA200",
            "Close / SMA200 - 1",
            "BTC volatility (30 days, annualised)",
            "SMA20 crossings",
            "Universe coins",
            "With a return",
            "Median coin return",
        ),
        (
            (
                row["month"],
                _pct(row["btc_return"]),
                row["btc_vs_sma200"] or "n/a",
                _pct(row["btc_close_over_sma200"]),
                _share(row["btc_volatility_30d_annualised"]),
                "n/a" if row["btc_sma20_crossings"] is None else row["btc_sma20_crossings"],
                row["universe_coins"],
                row["universe_coins_with_return"],
                _pct(row["universe_median_return"]),
            )
            for row in document["market_regime"]
        ),
    )
    for cell in document["cells"]:
        lines += [f"## Cell {cell['cell']['id']}", ""]
        outcome = f"Outcome: {cell['outcome']}"
        if cell["reason"] is not None:
            outcome += f" ({cell['reason']})"
        if cell["stop_ms"] is not None:
            outcome += f", stopped at {_when(cell['stop_ms'])}"
        lines += [f"{outcome}. Records: {cell['record_count']:,}.", ""]
        if cell["years"] is None:
            lines += ["A failure summary: the cell has no figures.", ""]
            continue
        lines += ["### Years", ""]
        lines += _period_tables(cell["years"], "year")
        for year in cell["years"]:
            inside = [row for row in cell["months"] if row["month"].startswith(f"{year['year']}-")]
            lines += [f"### Months of {year['year']}", ""]
            lines += _period_tables(inside, "month")
        lines += ["### Biggest losing trades", ""]
        lines += _loser_tables(cell["losing_trades"], [year["year"] for year in cell["years"]])
        lines += ["### Holding time", ""]
        lines += _holding_table(cell["holding_times"])
        lines += ["### By side", ""]
        lines += _group_table(cell["sides"], "side", "Side")
        lines += ["### By exit reason", ""]
        lines += _group_table(cell["exit_reasons"], "exit_reason", "Exit reason")
        lines += ["### By coin", ""]
        lines += _group_table(cell["coins"], "coin", "Coin")
        lines += ["### Signals", ""]
        lines += _signal_tables(cell["signals"])
    return "\n".join(lines)


# ---- the command --------------------------------------------------------------------------------


def _say(line: str) -> None:
    """A line of standard output: counts only."""
    print(line, flush=True)


def _fail(step: str, exc: BaseException | None = None) -> int:
    """One line of standard error, the failed ``step`` and the exception's type, never its
    message; returns the exit status 1."""
    kind = "" if exc is None else f": {type(exc).__name__}"
    print(f"v4_diagnose: {step}{kind}", file=sys.stderr, flush=True)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_diagnose.py", description="The V4 diagnostic run's diagnosis (see the docstring)."
    )
    parser.add_argument("--data", type=Path, required=True, help="the data directory")
    parser.add_argument(
        "--cells", type=Path, required=True, help="the cells: one subfolder per cell"
    )
    parser.add_argument(
        "--planned", required=True, help="the planned cells' ids, comma-separated (cell_ids)"
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="the folder for diagnosis.json and .md"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Diagnose the cells (module docstring); the exit status."""
    args = build_parser().parse_args(argv)
    out = Path(args.out)
    found = [name for name in OUTPUT_FILES if (out / name).exists()]
    if found:
        return _fail(f"refused: the out folder already holds {', '.join(found)}")
    order = {spec.cell_id: index for index, spec in enumerate(all_cells())}
    try:
        planned = planned_cells(args.planned, order)
    except ValueError as exc:
        return _fail("refused: --planned is not a list of distinct cell ids", exc)
    if v4_cells_guard.main(["--data", str(args.data)]) != 0:
        return _fail("refused: the data directory fails the reserved-window guard")
    try:
        market = Market.load(Path(args.data))
    except Exception as exc:
        return _fail("refused: loading the data directory failed", exc)
    if market.end_month > v4_cells_guard.LATEST_ALLOWED:
        return _fail("refused: the packs end after the reserved window opens")
    try:
        folders = sorted(path for path in Path(args.cells).iterdir() if path.is_dir())
    except OSError as exc:
        return _fail("refused: reading the cells folder failed", exc)
    cells = [folder for folder in folders if (folder / SUMMARY_FILE).is_file()]
    if not cells:
        return _fail("refused: no cell folder holds a summary.json")
    prices = _Prices(market)
    diagnosed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    refused: list[dict[str, str]] = []
    for folder in cells:
        try:
            entry, timing = diagnose_cell(folder, market, prices)
            if entry["cell"]["id"] not in planned:
                raise CellRefused(_UNPLANNED, ValueError("a cell the dispatch did not ask for"))
            if any(entry["cell"]["id"] == other["cell"]["id"] for other, _ in diagnosed):
                raise CellRefused(_REPEATED, ValueError("a cell of another folder"))
        except CellRefused as refusal:
            step, cause = refusal.step, refusal.cause
        except Exception as exc:
            step, cause = _FAILED, exc
        else:
            diagnosed.append((entry, timing))
            continue
        # Refused alone (M1): the step and the exception's type, never its text, on standard
        # error and under the missing cells; the other cells are still diagnosed.
        _fail(f"refused: the cell folder {folder.name!r:.80}: {step}", cause)
        refused.append({"folder": folder.name, "step": step, "error": type(cause).__name__})
    diagnosed.sort(key=lambda item: order[item[0]["cell"]["id"]])
    missing = _missing(folders, cells, [entry["cell"] for entry, _ in diagnosed], refused, planned)
    for entry, _ in diagnosed:
        years = 0 if entry["years"] is None else len(entry["years"])
        months_seen = 0 if entry["months"] is None else len(entry["months"])
        _say(
            f"v4_diagnose: {entry['cell']['id']}: {entry['record_count']} records, "
            f"{years} years, {months_seen} months"
        )
    try:
        regime = market_regime(market, prices)
        yearly = market_years(market, prices)
        arms = arm_rows(market)
    except Exception as exc:
        return _fail("computing the market regime failed", exc)
    document: dict[str, Any] = {
        "format": DIAGNOSIS_FORMAT,
        "data": data_record(market.pins),
        "window": window_record(market),
        "arms": arms,
        "timing": [timing for _, timing in diagnosed],
        "missing": missing,
        "market_regime": regime,
        "market_years": yearly,
        "cells": [entry for entry, _ in diagnosed],
    }
    try:
        _canonical(document)  # exact JSON only: strings, integers, booleans, null
        payload = (json.dumps(document, indent=1, ensure_ascii=True) + "\n").encode("ascii")
        page = render_markdown(document).encode("utf-8")
    except Exception as exc:
        return _fail("building the diagnosis failed", exc)
    made_out = not out.exists()
    created: list[Path] = []
    try:
        out.mkdir(parents=True, exist_ok=True)
        for target, data in ((out / JSON_FILE, payload), (out / MD_FILE, page)):
            _create(target, data)
            created.append(target)
    except Exception as exc:
        # Nothing is left behind: a diagnosis.json without its page is removed again.
        for target in created:
            target.unlink(missing_ok=True)
        if made_out:
            with contextlib.suppress(OSError):
                out.rmdir()
        return _fail("writing the diagnosis failed", exc)
    _say(
        f"v4_diagnose: {len(diagnosed)} cells from {len(folders)} folders "
        f"({len(missing['folders_without_summary'])} without summary.json, "
        f"{len(refused)} refused), {len(missing['cells'])} planned cells missing, "
        f"{len(regime)} regime months; wrote {JSON_FILE} and {MD_FILE}"
    )
    # A refused cell was named on standard error; the diagnosis of the others is written, and
    # the run still fails.
    return 1 if refused else 0


def _create(path: Path, data: bytes) -> None:
    """Create ``path`` exclusively with ``data``; a write that fails removes the file it made."""
    handle = path.open("xb")
    try:
        with handle:
            handle.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def planned_cells(text: str, order: Mapping[str, int]) -> list[str]:
    """The cell ids of ``--planned``, in run order: comma-separated, each a key of ``order``
    (``all_cells()``'s ids), none repeated; otherwise a ``ValueError``."""
    ids = [item.strip() for item in text.split(",")]
    if not all(item in order for item in ids):
        raise ValueError("an item is not a cell id")
    if len(set(ids)) != len(ids):
        raise ValueError("a cell id is repeated")
    return sorted(ids, key=order.__getitem__)


def _missing(
    folders: Sequence[Path],
    cells: Sequence[Path],
    present: Sequence[Mapping[str, Any]],
    refused: Sequence[Mapping[str, str]],
    planned: Sequence[str],
) -> dict[str, Any]:
    """The subfolders without a ``summary.json``, the cell folders refused (each with its step
    and exception type), and the ``planned`` cells absent from the diagnosis (in run order)."""
    found = {cell["id"] for cell in present}
    with_summary = set(cells)
    return {
        "folders_without_summary": [
            folder.name for folder in folders if folder not in with_summary
        ],
        "refused": [dict(row) for row in refused],
        "cells": [cell for cell in planned if cell not in found],
    }


if __name__ == "__main__":
    raise SystemExit(main())
