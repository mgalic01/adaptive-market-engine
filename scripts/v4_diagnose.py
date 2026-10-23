"""V4.0's diagnosis of the diagnostic run: the market regime per month, and each cell's results
broken down by year and month, by side, by exit reason, by coin and by cost.

The owner asked (2026-10-22) why V4 lost money in particular years, 2021 and 2023 among them.
The ``diagnose`` job of ``.github/workflows/v4-cells.yml`` runs this after the cells of a
pre-2025 data run (plan ``docs/superpowers/plans/2026-10-23-v4-diagnostic-run.md``, Task 3). It
adds no trading rule: it reads what the spec's "Records" and "Reports" write, and its timing
section is the "Verification" bullet's timing run (cell times, memory and output sizes).

``--data D --cells C --out O``:

1. refuses an ``O`` that already holds ``diagnosis.json`` or ``diagnosis.md``;
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
   record; its years must equal the verified summary's. Any failure refuses the whole run;
4. computes the market regime per month from the packs alone;
5. creates ``O/diagnosis.json`` and ``O/diagnosis.md``, both exclusively. They hold results and
   stay on the owner's PC (the workflow uploads them as a 1-day artifact).

**Exit status.** 0 once both files are written; 1 for any refusal or failure, with nothing
written; 2 for bad arguments (argparse's own).

**Output.** Standard output carries the guard's line (the end month and the config pin), one
line per cell (its id, outcome and its record, year and month counts) and a last line of counts:
never a price, an equity or a return (owner rule: public logs). A failure is one line on standard
error naming the step and the exception's type, never its text.

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
  the wallet received it), ``net_pnl`` and ``given_back`` (profit given back from the peak).
* Costs, from the fill and funding records: ``fills``, ``traded_notional`` (quantity x price),
  ``fees``, ``slippage`` (|price - unslipped price| x quantity, so 0 for a synthetic close),
  ``funding_records`` and ``funding`` (the records' signed amounts).
* Counts, from the events: ``margin_cuts`` and ``ceiling_cuts`` (one per cut event);
  ``dead_market_closes`` and ``funding_month_closes`` (the legs of the synthetic closes, by
  reason); ``deferrals`` (a daily order, ``signal`` or a hold arm's ``rebalance``, that did not
  fill in its first fill hour, the decision's hour plus one: counted when it fills later, is
  superseded or is cancelled); ``refused_orders`` (an order event's legs with a refusal);
  ``cash_clip_cuts`` (``increase_cut`` events) and ``band_skips`` (orders the band kept).
* By side, exit reason and coin, per year: lifecycles, wins, win rate (side only), gross P&L,
  fees, funding, net P&L and profit given back. Both sides are listed every year; exit reasons
  and coins only when they occur.
* Signals, per year, over the coin-days (the ``daily_coin`` records): for each speed the share
  up, down and warming (no reading, warming up, or an exact tie: the engine's ``None``) and its
  flips (a vote opposite to the coin's last up or down vote; a no-bar day repeats the last
  reading, so it never flips); the shares with no reading, with a confirmed downtrend, with
  S > 0 and with L at 0, 1/3, 2/3 and 1; and the mean number of coins with a nonzero target per
  decision. A hold arm has none.

Money is summed exactly in Fractions and written as exact Decimals; shares, rates, returns and
the regime's figures are computed under ``CONTEXT``.

**The market regime per month**, from ``Market.daily`` (daily bars of unmasked hours) and only
from bars of the month and before it, for every month from the window's first to the packs'
``end_month``:

* ``btc_return``: BTCUSDT's last daily close of the month over its last close before it, minus 1;
* ``btc_vs_sma200`` (``above``, ``below`` or ``equal``) and ``btc_close_over_sma200`` (minus 1):
  the month's last close against the mean of the last 200 daily closes up to it;
* ``btc_volatility_30d``: the sample standard deviation of the daily returns of the 30 days
  ending with the month's last bar (each against the bar before it), times sqrt(365);
* ``btc_sma20_crossings``: the month's bars whose close is on the other side of the SMA20 from
  the last bar before them that was not on it (choppiness);
* ``universe_coins``, ``universe_coins_with_return`` and ``universe_median_return``: the month's
  universe and the median of their monthly returns, as BTCUSDT's is computed.

A figure without the bars it needs is null, and so is every BTCUSDT figure of packs without it.
"""

from __future__ import annotations

import argparse
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
from crypto_grid_bot.v4.engine.arms import all_cells
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

DIAGNOSIS_FORMAT = "v4-diagnosis-1"
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
_GROUP_SUMS = ("gross_pnl", "fees", "funding", "net_pnl", "given_back")
# The keys of a summary's year (summary.py), which the diagnosis' years must reproduce.
_YEAR_KEYS = ("year", "start_ms", "end_ms", "start_equity", "end_equity", "return")
_TIMING_KEYS = frozenset({"cell", "wall_seconds", "peak_rss_mb", "records_bytes"})
_MAX_TIMING_BYTES = 4096
_ZERO = Fraction(0)

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
    drawdown: _Drawdown = field(default_factory=_Drawdown)


class _Pass:
    """One pass over a cell's records, in order, keeping only aggregates: per month the tallies
    and the drawdown, per year the drawdown, the breakdowns and the signal counts, the open
    marks a period reads (the first hour's and each month's first hour's), and the little a
    reader needs across records (each coin's last up or down vote per speed, the last
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
        }
        self.signals: dict[int, Counter[str]] = {}
        self.outcome: str | None = None
        self.final: str | None = None
        self._bounds: tuple[int, int, str] = (0, 0, "")
        self._marked_month: str | None = None
        self._marked_year: int | None = None
        self._decision: int | None = None
        self._votes: dict[tuple[str, str], int] = {}

    def feed(self, kind: str, record: Mapping[str, object]) -> None:
        if self.outcome is not None:
            raise ValueError(f"a {kind} record follows the outcome record")
        self.count += 1
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
        text = record.get("open_equity")
        if text is None:  # a stop before its open mark (only the last hour)
            return
        equity = _decimal(text, "an open mark")
        month = self._month(open_ms)
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
        for group, key in (("sides", side), ("exit_reasons", reason), ("coins", coin)):
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

    def _event(self, record: Mapping[str, object]) -> None:
        kind = record.get("type")
        hour = _int(record.get("hour_ms"), "an event's hour_ms")
        counts = self._month(hour).events.counts
        if kind == "margin_cut":
            counts["margin_cuts"] += 1
        elif kind == "ceiling_cut":
            counts["ceiling_cuts"] += 1
        elif kind == "increase_cut":
            counts["cash_clip_cuts"] += 1
        elif kind == "synthetic_closes":
            for leg in _items(record.get("legs"), "a synthetic close's legs"):
                if leg.get("reason") == DELISTING:
                    counts["dead_market_closes"] += 1
                elif leg.get("reason") == FUNDING_EXIT:
                    counts["funding_month_closes"] += 1
                else:
                    raise ValueError("a synthetic close's leg has an unknown reason")
        elif kind == "order":
            counts["band_skips"] += int(record.get("band") == "keep")
            legs = _items(record.get("legs"), "an order's legs")
            counts["refused_orders"] += sum(leg.get("refusal") is not None for leg in legs)
            if record.get("source") in _DAILY_SOURCES:
                counts["deferrals"] += int(self._deferred(record, hour))
        elif kind in ("order_superseded", "order_cancelled"):
            counts["deferrals"] += int(self._deferred(record, hour))

    @staticmethod
    def _deferred(record: Mapping[str, object], hour: int) -> bool:
        """Whether a daily order ended after its first fill hour, the decision's plus one."""
        return hour > _int(record.get("decision_ms"), "an order's decision_ms") + HOUR_MS

    def _daily(self, record: Mapping[str, object]) -> None:
        decision = _int(record.get("decision_ms"), "a daily record's decision_ms")
        counts = self.signals.setdefault(_year_of(decision), Counter())
        if decision != self._decision:
            counts["decisions"] += 1
            self._decision = decision
        counts["coin_days"] += 1
        target = record.get("target")
        if target is not None and _decimal(target, "a target") != 0:
            counts["nonzero_targets"] += 1
        speeds = record.get("speeds")
        if speeds is None:
            counts["no_reading"] += 1
            for speed in SPEEDS:
                counts[f"{speed}_warming"] += 1
            return
        coin = record.get("coin")
        if type(coin) is not str:
            raise ValueError("a daily record needs its coin")
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

    def finish(self) -> None:
        """The end of the records: a full cell's final equity ends its last month and year."""
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
    ``coins`` and ``signals`` (module docstring)."""
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
            {
                "month": key,
                **ending.period(start, end),
                "max_drawdown": month.drawdown.value(),
                **_period_tallies(month.lifecycles, month.costs, month.events),
            }
        )
    years = list(range(_year_of(first), _year_of(last) + 1))
    year_rows = []
    for year in years:
        tallies = (_Tally(), _Tally(), _Tally())
        for key in keys:
            if key.startswith(f"{year:04d}-") and key in reader.months:
                month = reader.months[key]
                for total, part in zip(
                    tallies, (month.lifecycles, month.costs, month.events), strict=True
                ):
                    total.merge(part)
        drawdown = reader.year_drawdowns.get(year, _Drawdown())
        year_rows.append(
            {
                "year": year,
                **ending.period(_year_start(year), _year_start(year + 1)),
                "max_drawdown": drawdown.value(),
                **_period_tallies(*tallies),
            }
        )
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
        "signals": [_signal_row(year, reader.signals.get(year, Counter())) for year in years],
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
        "mean_coins_with_target": _ratio(counts["nonzero_targets"], counts["decisions"]),
    }


# ---- one cell folder ----------------------------------------------------------------------------


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


def diagnose_cell(folder: Path, market: Market) -> tuple[dict[str, Any], dict[str, Any]]:
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
    names = ("years", "months", "sides", "exit_reasons", "coins", "signals")
    if summary["outcome"] not in FULL_OUTCOMES:
        return {**entry, **dict.fromkeys(names)}, timing
    with _Step("reading the records for the diagnosis failed"):
        figures = cell_figures(records, receipt)
        if figures["record_count"] != receipt.record_count:
            raise ValueError("the pass did not read every record")
    with _Step("the diagnosis' years are not the summary's"):
        mine = [{key: year[key] for key in _YEAR_KEYS} for year in figures["years"]]
        if mine != summary["years"]:
            raise ValueError("the diagnosis' years are not the summary's")
    return {**entry, **{name: figures[name] for name in names}}, timing


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


def _median(values: Sequence[Decimal]) -> Decimal | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    with localcontext(CONTEXT):
        return (ordered[middle - 1] + ordered[middle]) / 2


def market_regime(market: Market) -> list[dict[str, Any]]:
    """The market regime of every month from the window's first to ``end_month`` (module
    docstring), each from daily bars of that month and before it."""
    cache: dict[str, _Daily] = {}

    def daily(symbol: str) -> _Daily:
        if symbol not in cache:
            cache[symbol] = _Daily.of(market, symbol)
        return cache[symbol]

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
                "btc_volatility_30d": _text(None if btc is None else btc.volatility(start, end)),
                "btc_sma20_crossings": None if btc is None else btc.crossings_in(start, end),
                "universe_coins": len(coins),
                "universe_coins_with_return": len(returns),
                "universe_median_return": _text(_median(returns)),
            }
        )
    return rows


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


def _period_tables(rows: Sequence[Mapping[str, Any]], label: str) -> list[str]:
    head = label.capitalize()
    lines = ["Equity (USDT):", ""]
    lines += _table(
        (head, "Start equity", "End equity", "Return", "Max drawdown"),
        (
            (
                row[label],
                _rounded(row["start_equity"]),
                _rounded(row["end_equity"]),
                _pct(row["return"]),
                _share(row["max_drawdown"]),
            )
            for row in rows
        ),
    )
    lines += ["Lifecycles, by the period they end in (P&L in USDT):", ""]
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
    lines += ["Costs, from the fill and funding records (USDT; funding received is positive):", ""]
    lines += _table(
        (head, "Fills", "Traded notional", "Fees", "Slippage", "Funding records", "Funding"),
        (
            (
                row[label],
                costs["fills"],
                _rounded(costs["traded_notional"]),
                _rounded(costs["fees"]),
                _rounded(costs["slippage"]),
                costs["funding_records"],
                _rounded(costs["funding"]),
            )
            for row in rows
            for costs in (row["costs"],)
        ),
    )
    lines += ["Events:", ""]
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
    rate = label == "side"
    head = ["Year", title, "Lifecycles", "Wins", *(["Win rate"] if rate else [])]
    head += ["Gross P&L", "Fees", "Funding", "Net P&L", "Given back"]
    return _table(
        head,
        (
            (
                row["year"],
                row[label],
                row["lifecycles"],
                row["wins"],
                *([_share(row["win_rate"])] if rate else []),
                *(_rounded(row[name]) for name in _GROUP_SUMS),
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


def _when(ms: object) -> str:
    if type(ms) is not int:
        return "n/a"
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")


def render_markdown(document: Mapping[str, Any]) -> str:
    """``diagnosis.md``: the timing, the market regime, then one section per cell (its years,
    its months year by year, then the breakdowns and the signals), rounded for reading."""
    data, window = document["data"], document["window"]
    lines = [
        "# V4 diagnosis",
        "",
        f"Data: end month {data['end_month']}, config_sha256 `{data['config_sha256']}`. "
        f"Window: {_when(window['start_ms'])} to {_when(window['end_ms'])}. "
        f"Cells: {len(document['cells'])}.",
        "",
        "Rounded for reading; diagnosis.json holds the exact values. Fills, funding and events "
        "count in the hour they happen; a lifecycle counts in the period it ends; signals in "
        "the year of the decision.",
        "",
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
    lines += ["## Market regime", "", "BTCUSDT, and the median of the month's universe:", ""]
    lines += _table(
        (
            "Month",
            "BTC return",
            "BTC vs SMA200",
            "Close / SMA200 - 1",
            "BTC 30-day volatility",
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
                _share(row["btc_volatility_30d"]),
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
    order = {spec.cell_id: index for index, spec in enumerate(all_cells())}
    diagnosed: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for folder in cells:
        name = f"{folder.name!r:.80}"
        try:
            entry, timing = diagnose_cell(folder, market)
        except CellRefused as refusal:
            return _fail(f"refused: the cell folder {name}: {refusal.step}", refusal.cause)
        except Exception as exc:
            return _fail(f"refused: the cell folder {name} failed", exc)
        if any(entry["cell"]["id"] == other["cell"]["id"] for other, _ in diagnosed):
            return _fail(f"refused: the cell folder {name} repeats a cell of another folder")
        diagnosed.append((entry, timing))
    diagnosed.sort(key=lambda item: order[item[0]["cell"]["id"]])
    for entry, _ in diagnosed:
        years = 0 if entry["years"] is None else len(entry["years"])
        months_seen = 0 if entry["months"] is None else len(entry["months"])
        _say(
            f"v4_diagnose: {entry['cell']['id']}: outcome {entry['outcome']}, "
            f"{entry['record_count']} records, {years} years, {months_seen} months"
        )
    try:
        regime = market_regime(market)
    except Exception as exc:
        return _fail("computing the market regime failed", exc)
    document: dict[str, Any] = {
        "format": DIAGNOSIS_FORMAT,
        "data": data_record(market.pins),
        "window": window_record(market),
        "timing": [timing for _, timing in diagnosed],
        "market_regime": regime,
        "cells": [entry for entry, _ in diagnosed],
    }
    try:
        _canonical(document)  # exact JSON only: strings, integers, booleans, null
        payload = (json.dumps(document, indent=1, ensure_ascii=True) + "\n").encode("ascii")
        page = render_markdown(document).encode("utf-8")
        out.mkdir(parents=True, exist_ok=True)
        for target, data in ((out / JSON_FILE, payload), (out / MD_FILE, page)):
            with target.open("xb") as handle:  # created exclusively
                handle.write(data)
    except Exception as exc:
        return _fail("writing the diagnosis failed", exc)
    _say(
        f"v4_diagnose: {len(diagnosed)} cells from {len(folders)} folders, {len(regime)} regime "
        f"months; wrote {JSON_FILE} and {MD_FILE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
