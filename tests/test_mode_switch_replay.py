"""Spec v2's mode switcher through ``replay()`` (build plan Task 6): the perception at each minute,
the time in each mode, the switches, the round trips with their stops and fades, the rows, and the
end of a run (spec v2 sections 3-8).

Two synthetic markets, each a price path with its hourly, daily and minute bars:

* ``rising_market``: 300 days of a rise with down days, then a 15% fall over four UTC days, built to
  enter Uptrend and to leave it by the trailing stop;
* ``flat_market``: a 1% swing every four hours, which V0's classifier reads as RANGE and the Grid
  row as a quiet hourly band.

Where a test is about replay's bookkeeping rather than the selector, it scripts the hourly decision
(``decisions``) or sets the mode after a chosen quote (``modes_after``), through the simulator's own
code. Nothing here is market data or evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_CEILING
from decimal import Decimal as D
from functools import cache
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import test_backtest_masked_checks as mc
from test_backtest_replay import SUMMARY_FIELDS, candle, engine_for

from crypto_grid_bot.backtest import acceptance_v2
from crypto_grid_bot.backtest.__main__ import result_failures
from crypto_grid_bot.backtest.features import FeatureEngine
from crypto_grid_bot.backtest.jobs import run_job, variant_policy
from crypto_grid_bot.backtest.klines import Kline, aggregate
from crypto_grid_bot.backtest.replay import (
    MODE_SWITCH_STRATEGY,
    POINT_SPANS_MS,
    Metrics,
    ModeDecisions,
    RunConfig,
    bar_quotes,
    check_accounting,
    replay,
    summarise,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import RiskAction, RiskDecision
from crypto_grid_bot.simulation import runner
from crypto_grid_bot.simulation.execution import exit_state
from crypto_grid_bot.simulation.inventory_cap import mark
from crypto_grid_bot.simulation.models import (
    ONE,
    Account,
    LimitOrder,
    MarketRules,
    Quote,
    floor_step,
)
from crypto_grid_bot.simulation.runner import PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.uptrend import UptrendPosition, initial_stop
from crypto_grid_bot.strategy.mode_selector import Mode
from crypto_grid_bot.strategy.perception import Perception

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config/default.toml")
MS = SimulationPolicy(mode_switch=True, flow_block_entry=True)
MINUTE, HOUR, DAY = 60_000, 3_600_000, 86_400_000
START = int(datetime(2023, 1, 1, tzinfo=UTC).timestamp()) * 1000
# Spec v2's primary fees (maker 0, taker 0.0009), and v1's slippage and participation.
RULES = MarketRules(
    symbol="TESTUSDT",
    tick_size=D("0.0001"),
    quantity_step=D("0.01"),
    minimum_notional=D("5"),
    fee_rate=D("0"),
    slippage_rate=D("0.0005"),
    participation=D("0.10"),
    taker_fee_rate=D("0.0009"),
)
SPREAD = D("0.0005")
CASH, GRID, UPTREND = Mode.CASH.value, Mode.GRID.value, Mode.UPTREND.value
# A minute's quote sizes are a quarter of its taker volumes, and the participation limit takes a
# tenth of that: so a side's taker volume of 40 x q lets each quote trade q.
PER_QUOTE = D("0.025")


def at(day: int, hour: int = 0, minute: int = 0) -> int:
    return START + day * DAY + hour * HOUR + minute * MINUTE


class Market:
    """A price path and its bars. Each bar opens and closes on the path, with a wick of ``wick``
    beyond its open and close on either side. The hourly and daily bars feed V0's features and the
    perception, and the minutes are the quotes. A minute's taker-buy share is 0.5 unless a test
    says otherwise, so F's block stays off."""

    def __init__(self, price: Callable[[int], float], days: int, wick: float) -> None:
        self.price, self.wick = price, wick
        self.hourly = [self.bar(START + i * HOUR) for i in range(days * 24)]
        self.daily = list(aggregate(self.hourly, DAY))
        self.engine: FeatureEngine = engine_for(self.hourly)

    def bar(self, open_ms: int, length: int = HOUR, volume: D = D(1_000_000)) -> Kline:
        o, c = self.price(open_ms), self.price(open_ms + length)
        high, low = max(o, c) * (1 + self.wick), min(o, c) * (1 - self.wick)
        return candle(open_ms, o, high, low, c, volume=str(volume), taker=str(volume / 2))

    def minutes(self, start: int, end: int) -> list[Kline]:
        return [self.bar(t, MINUTE) for t in range(start, end, MINUTE)]


def minute(open_ms: int, price: D, *, each: D, low: D | None = None, share: D = D("0.5")) -> Kline:
    """A crafted minute at ``price``, dipping to ``low`` if given, whose taker-buy share is
    ``share``. The smaller of its two taker volumes lets each quote trade ``each`` (``PER_QUOTE``);
    at a share of 0.5 that holds on both sides."""
    volume = each / PER_QUOTE / min(share, 1 - share)
    low = price if low is None else low
    return Kline(open_ms, price, price, low, price, volume, volume * price, volume * share)


def ceil_step(value: D, step: D) -> D:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


RISE_DAYS, FALL_DAYS = 300, 4


def _rising_closes() -> list[float]:
    """Daily closes: a rise with down days, +3% and -1.5% in turn, so that the daily RSI stays
    near 66 (a steady rise holds it at 100, above Uptrend's 75); then a 15% fall, 4% a day. A
    position holds at most 60% of the capital (the cash cap), so a 4% day loses at most 2.4% of
    equity, under the 3% daily-loss pause: the trailing stop, three daily ATRs (about 7%) below
    the highest close, is reached before the risk layer acts."""
    closes = [1.0]
    for day in range(RISE_DAYS):
        closes.append(closes[-1] * (1.03 if day % 2 == 0 else 0.985))
    closes += [closes[-1] * 0.96**k for k in range(1, FALL_DAYS + 1)]
    return closes


RISING_CLOSES = _rising_closes()


def rising_price(t: int) -> float:
    day, into = divmod(t - START, DAY)
    if day >= len(RISING_CLOSES) - 1:
        return RISING_CLOSES[-1]
    first, last = RISING_CLOSES[day], RISING_CLOSES[day + 1]
    return first + (last - first) * into / DAY


@cache
def rising_market() -> Market:
    return Market(rising_price, RISE_DAYS + FALL_DAYS + 2, wick=0.001)


def flat_price(t: int) -> float:
    """A 1% swing every four hours. Five swings fill the 20-hour Bollinger band exactly, so the
    width equals its median, which the Grid row allows; the classifier reads RANGE. The fourth
    hour's decision, the first that can choose Grid, falls mid-swing, so the grid it opens has a
    buy the swing reaches."""
    return 1.0 + 0.01 * math.cos(2 * math.pi * (t - START) / (4 * HOUR))


@cache
def flat_market() -> Market:
    return Market(flat_price, 80, wick=0.004)


FLAT_DAY = 70  # the flat market's features, width median and daily ADX are warm by then
# The rising market's last hours before the fall: the entry decides at 22:00, two hours before
# day 299 closes at a new high, which raises the stop.
ENTRY = at(RISE_DAYS - 2, 22)


def run_ms(
    market: Market,
    minutes: list[Kline],
    window: tuple[int, int],
    *,
    masked: frozenset[int] = frozenset(),
) -> tuple[Metrics, Account, dict[str, Any]]:
    run = RunConfig("TESTUSDT", "high_first", True, RULES, D(100), SPREAD)
    metrics, account = replay(
        CONFIG,
        run,
        minutes,
        market.engine,
        MS,
        daily=market.daily,
        hourly=market.hourly,
        window=window,
        masked=masked,
    )
    return (
        metrics,
        account,
        summarise(run, metrics, account, check_accounting(run, metrics, account)),
    )


def quote_id(open_ms: int, index: int) -> str:
    return f"TESTUSDT/{open_ms}/{index}"


@contextmanager
def decisions(modes: dict[int, Mode]) -> Iterator[None]:
    """Script section 4's selector: the mode for each decision hour (its open, in ms), Cash for
    any other. The simulator still decides once an hour, and applies the mode itself."""

    def select_mode(
        snapshot: Any, regime: Any, quality: Any, count: Any, now_ms: int, _: Any
    ) -> Mode:
        return modes.get(now_ms // HOUR * HOUR, Mode.CASH)

    with patch.object(runner, "select_mode", select_mode):
        yield


@contextmanager
def modes_after(changes: dict[str, str]) -> Iterator[None]:
    """Set the mode after the step of each quote named (``quote_id``), through the one place the
    simulator assigns it (``_set_mode``), as a halt's Cash would within a minute."""
    real = PaperSimulator.step

    def step(simulator: PaperSimulator, account: Account, frame: Any) -> dict[str, Any]:
        report = real(simulator, account, frame)
        if frame.quote.event_id in changes:
            PaperSimulator._set_mode(account, changes[frame.quote.event_id])
        return report

    with patch.object(PaperSimulator, "step", step):
        yield


@dataclass(frozen=True)
class Step:
    """One frame as replay ran it: its quote, its report, the uptrend position and the order book
    after it."""

    quote: Quote
    report: dict[str, Any]
    position: UptrendPosition | None
    orders: tuple[LimitOrder, ...]


@contextmanager
def recorded() -> Iterator[list[Step]]:
    steps: list[Step] = []
    real = PaperSimulator.step

    def step(simulator: PaperSimulator, account: Account, frame: Any) -> dict[str, Any]:
        report = real(simulator, account, frame)
        position = None if account.uptrend is None else replace(account.uptrend)
        orders = tuple(replace(order) for order in account.orders.values())
        steps.append(Step(frame.quote, report, position, orders))
        return report

    with patch.object(PaperSimulator, "step", step):
        yield steps


def times(row: dict[str, Any]) -> dict[str, int]:
    return row["modes"]["time_ms"]


# The time in each mode.


def test_mode_time_is_weighted_by_quote_spans() -> None:
    # A minute's quotes stand 9, 10, 10 and 31 s. The mode changes during the third quote's step,
    # so the old mode has the first two spans and the new one the last two.
    assert POINT_SPANS_MS == (9_000, 10_000, 10_000, 31_000)
    market, t = flat_market(), at(FLAT_DAY)
    with modes_after({quote_id(t, 2): GRID}):
        _, account, row = run_ms(market, market.minutes(t, t + MINUTE), (t, t + MINUTE))
    assert account.mode == GRID
    assert times(row) == {CASH: 19_000, GRID: 41_000, UPTREND: 0}


def test_mode_time_counts_a_masked_gap_to_the_mode_before_it() -> None:
    # Hours 1-3 are masked: their minutes are absent, as run_job drops them. The Grid decided at
    # hour 0 stays in force through them, so it holds four hours, and the next decision's Cash one.
    market, t = flat_market(), at(FLAT_DAY)
    hours = frozenset(t + h * HOUR for h in (1, 2, 3))
    minutes = [k for k in market.minutes(t, t + 5 * HOUR) if k.open_ms // HOUR * HOUR not in hours]
    with decisions({t: Mode.GRID, t + 4 * HOUR: Mode.CASH}):
        metrics, _, row = run_ms(market, minutes, (t, t + 5 * HOUR), masked=hours)
    assert metrics.masked_hours == 3
    assert times(row) == {CASH: HOUR, GRID: 4 * HOUR, UPTREND: 0}
    assert sum(times(row).values()) == 5 * HOUR


def test_mode_time_covers_masked_spans_at_both_ends() -> None:
    # The window's first and last hours are masked. Before the first quote, the account is in Cash,
    # as every account starts; after the last, the last mode stays in force to the window's end.
    market, t = flat_market(), at(FLAT_DAY)
    first, last = t, t + 3 * HOUR
    minutes = market.minutes(t + HOUR, t + 3 * HOUR)
    with decisions({t + HOUR: Mode.GRID, t + 2 * HOUR: Mode.GRID}):
        _, _, row = run_ms(market, minutes, (t, t + 4 * HOUR), masked=frozenset({first, last}))
    assert times(row) == {CASH: HOUR, GRID: 3 * HOUR, UPTREND: 0}


def test_mode_switches_count_each_change_of_mode() -> None:
    market, t = flat_market(), at(FLAT_DAY)
    # Cash, the start (not a switch), then Grid, Uptrend and Cash: three switches.
    changes = {
        quote_id(t + 10 * MINUTE, 0): GRID,
        quote_id(t + 20 * MINUTE, 0): UPTREND,
        quote_id(t + 30 * MINUTE, 0): CASH,
    }
    with modes_after(changes):
        metrics, account, row = run_ms(
            market, market.minutes(t, t + 40 * MINUTE), (t, t + 40 * MINUTE)
        )
    assert metrics.mode_switches == account.mode_switches == row["modes"]["switches"] == 3
    assert times(row) == {CASH: 20 * MINUTE, GRID: 10 * MINUTE, UPTREND: 10 * MINUTE}
    # A decision that keeps the mode is not a switch: Cash to Grid at the first hour, and the next
    # hour's Grid keeps it.
    with decisions({t: Mode.GRID, t + HOUR: Mode.GRID}):
        _, _, row = run_ms(market, market.minutes(t, t + 2 * HOUR), (t, t + 2 * HOUR))
    assert row["modes"]["switches"] == 1
    assert times(row) == {CASH: 0, GRID: 2 * HOUR, UPTREND: 0}


# The two markets, as the selector reads them.


@cache
def rising_run() -> tuple[list[Kline], Metrics, Account, dict[str, Any], list[Step]]:
    """The rising market from ENTRY to the start of the fall's third day, with every frame
    recorded."""
    market = rising_market()
    minutes = market.minutes(ENTRY, at(RISE_DAYS + 2))
    with recorded() as steps:
        metrics, account, row = run_ms(market, minutes, (ENTRY, at(RISE_DAYS + 2)))
    return minutes, metrics, account, row, steps


def stop_trigger(steps: list[Step]) -> int:
    """The index of the frame on which exit 1 begins."""
    (index,) = [i for i, step in enumerate(steps) if step.report.get("uptrend_exit") == "stop"]
    return index


def test_rising_market_enters_uptrend_and_trails_out() -> None:
    _, metrics, _, row, steps = rising_run()
    assert row["accounting_problems"] == []
    assert result_failures([row]) == []
    # The decision at ENTRY enters, and its first quote buys.
    entry = steps[0]
    assert entry.report["mode_decision"] == UPTREND
    assert entry.position is not None and entry.position.quantity > 0
    first_stop = entry.position.stop
    # Day 299's close, a new high, raised the stop, and the fall's quotes reached the raised stop:
    # exit 1 sold above where the entry's own stop sat.
    trigger = stop_trigger(steps)
    before = steps[trigger - 1].position
    assert before is not None and before.stop > first_stop
    assert first_stop < steps[trigger].quote.bid <= before.stop
    modes = row["modes"]
    assert (modes["uptrend_trades"], modes["stops"], modes["fades"]) == (1, 1, 0)
    assert (metrics.uptrend_trades, metrics.uptrend_stops, metrics.uptrend_fades) == (1, 1, 0)
    assert "uptrend_stop" in row["realised_exit_pnl_by_reason"]
    assert times(row)[UPTREND] > 0 and times(row)[GRID] == 0
    assert sum(times(row).values()) == at(RISE_DAYS + 2) - ENTRY


def test_flat_market_runs_grids_in_grid_mode() -> None:
    market, t = flat_market(), at(FLAT_DAY)
    _, _, row = run_ms(market, market.minutes(t, t + 12 * HOUR), (t, t + 12 * HOUR))
    assert row["accounting_problems"] == []
    assert row["completed_cycles"] > 0
    assert times(row)[GRID] > 0 and times(row)[UPTREND] == 0
    assert row["modes"]["uptrend_trades"] == 0


# The end of a run (spec v2 section 6).


def last_quote(minutes: list[Kline]) -> Quote:
    return bar_quotes(minutes[-1], "TESTUSDT", "high_first", SPREAD, RULES.tick_size)[-1]


def test_run_ending_in_uptrend_is_valid_and_marked_at_exit_value() -> None:
    # A position still held is not an exit owed: the run is valid, the position is valued at v1's
    # exit mark in equity, and the row's exit fields leave it out.
    market = rising_market()
    minutes = market.minutes(ENTRY, ENTRY + 4 * HOUR)
    _, account, row = run_ms(market, minutes, (ENTRY, ENTRY + 4 * HOUR))
    position = account.uptrend
    assert position is not None and position.phase == "holding"
    assert account.inventory == position.quantity and not account.pending + account.secured
    value = position.quantity * mark(last_quote(minutes), RULES)
    assert result_failures([row]) == []  # valid: in particular, no exit left incomplete
    assert D(row["final_total_equity"]) == account.cash + value
    assert row["final_exit_blocked"] is None and row["final_unsellable_notional"] == "0"
    assert row["modes"]["uptrend_trades"] == 0
    assert row["modes"]["held_at_end"] == {"quantity": str(position.quantity), "value": str(value)}


def test_run_ending_in_a_blocked_grid_keeps_f_fragments_held() -> None:
    # A grid whose top buy has filled, so its sell rests, and whose next buy fills in part on thin
    # volume. F's block then cancels that buy, and its filled part, below the minimum notional at
    # its target, becomes a fragment. The run ends in Grid mode at a price where the fragment alone
    # is sellable: v1's exit exempts it while F holds it, so the run is not incomplete.
    market, t = flat_market(), at(FLAT_DAY)
    natural = market.minutes(t, t + 12 * HOUR)
    with recorded() as steps:
        run_ms(market, natural, (t, t + 12 * HOUR))

    def ready(step: Step) -> bool:
        sells = [o for o in step.orders if o.side == "sell"]
        buys = [o for o in step.orders if o.side == "buy" and o.remaining == o.quantity]
        return step.quote.event_id.endswith("/3") and len(sells) == 1 and len(buys) >= 2

    when = next(step for step in steps if ready(step))
    sell = next(o for o in when.orders if o.side == "sell")
    second = max((o for o in when.orders if o.side == "buy"), key=lambda o: o.price)
    assert second.target is not None and second.target < sell.price
    # Its fragment: the most the step allows below the minimum notional at its target.
    part = floor_step(RULES.minimum_notional / second.target, RULES.quantity_step)
    if part * second.target >= RULES.minimum_notional:
        part -= RULES.quantity_step
    assert part < second.quantity
    # The final price: the fragment is sellable there, and the resting sell does not fill.
    tick, kept = RULES.tick_size, (ONE - RULES.slippage_rate) * (ONE - SPREAD)
    low = RULES.minimum_notional / part / kept + 3 * tick
    high = sell.price / (ONE - RULES.slippage_rate) - 3 * tick
    assert low < high
    end_price = floor_step((low + high) / 2, tick)
    middle = floor_step((second.price + sell.price) / 2, tick)
    open_ms = int(when.quote.event_id.split("/")[1]) + MINUTE
    minutes = [k for k in natural if k.open_ms < open_ms]
    # The dip crosses the second buy alone, and its one crossing quote buys ``part`` of it.
    dip = floor_step(second.price * D("0.998"), tick)
    minutes.append(minute(open_ms, middle, each=part, low=dip))
    # The taker-buy share then falls to 0.1, under F's 0.40, over the 15 minutes F reads.
    block = {"each": D(10_000), "share": D("0.1")}
    minutes += [minute(open_ms + i * MINUTE, middle, **block) for i in range(1, 17)]
    minutes += [minute(open_ms + i * MINUTE, end_price, **block) for i in range(17, 20)]
    end = minutes[-1].open_ms + MINUTE
    _, account, row = run_ms(market, minutes, (t, end))
    assert row["accounting_problems"] == []
    assert account.mode == GRID and account.flow_block
    assert account.flow_fragments == {second.target: part}
    assert [o.side for o in account.orders.values()] == ["sell"]
    # Without F's exemption the fragment would be an exit owed.
    assert exit_state(account, last_quote(minutes), RULES)[0] == "incomplete"
    assert row["final_exit_blocked"] == "dust"
    assert result_failures([row]) == []


def stopped_at(each: Callable[[D], D]) -> tuple[Metrics, Account, dict[str, Any], D, D]:
    """The rising run up to exit 1's minute, which is replaced by the run's last minute: at a price
    just below the stop, where each quote can sell ``each(quantity)`` of the position. Returns the
    run, the position's quantity and that amount."""
    minutes, _, _, _, steps = rising_run()
    trigger = stop_trigger(steps)
    before = steps[trigger - 1].position
    assert before is not None
    open_ms = int(steps[trigger].quote.event_id.split("/")[1])
    amount = each(before.quantity)
    price = floor_step(before.stop * D("0.999"), RULES.tick_size)
    crafted = [k for k in minutes if k.open_ms < open_ms]
    crafted.append(minute(open_ms, price, each=amount))
    metrics, account, row = run_ms(rising_market(), crafted, (ENTRY, open_ms + MINUTE))
    return metrics, account, row, before.quantity, amount


def test_run_ending_mid_exit_is_incomplete_as_in_v1() -> None:
    # Exit 1 begins on the minute's first quote, and each quote sells a fifth of the position, so a
    # fifth is left at the end: an exit under way is owed, as v1 treats a drain.
    metrics, account, row, quantity, each = stopped_at(
        lambda q: floor_step(q / 5, RULES.quantity_step)
    )
    assert quantity - 4 * each >= each
    assert account.uptrend is not None and account.uptrend.phase == "exiting"
    assert account.inventory == quantity - 4 * each
    assert row["final_exit_blocked"] == "incomplete"
    assert any("exit still incomplete" in failure for failure in result_failures([row]))
    assert (metrics.uptrend_trades, metrics.uptrend_stops) == (0, 0)
    assert row["modes"]["held_at_end"] == {"quantity": "0", "value": "0"}


def test_exit_completing_on_the_last_quote_counts_the_trade() -> None:
    # Each quote sells a quarter of the position, so its last sale is on the run's last quote.
    metrics, account, row, quantity, each = stopped_at(
        lambda q: ceil_step(q / 4, RULES.quantity_step)
    )
    assert 3 * each < quantity <= 4 * each
    assert account.uptrend is None and account.inventory == 0
    assert (metrics.uptrend_trades, metrics.uptrend_stops) == (1, 1)
    assert row["modes"]["uptrend_trades"] == 1
    assert result_failures([row]) == []
    assert row["final_exit_blocked"] is None


def test_entry_that_bought_nothing_counts_no_round_trip() -> None:
    # Every quote's participation limit allows less than the minimum notional, so the entry buys
    # nothing; then the bid falls through the stop. Exit 1 ends the empty entry: no trade, and no
    # stop counted (spec v2 section 5, "An entry that bought nothing").
    market = rising_market()
    snapshot = Perception(market.hourly, market.daily).at(ENTRY)
    assert snapshot.d1_close is not None and snapshot.d1_atr is not None
    stop = initial_stop(snapshot.d1_close, snapshot.d1_atr)
    # 0.5 a quote, worth about 4.4 at an ask near 8.8.
    each, thin = D("0.5"), D("0.5") / PER_QUOTE
    entering = market.minutes(ENTRY, ENTRY + 30 * MINUTE)
    minutes = [replace(k, volume=2 * thin, taker_buy_base=thin) for k in entering]
    below = floor_step(stop * D("0.99"), RULES.tick_size)
    minutes.append(minute(ENTRY + 30 * MINUTE, below, each=each))
    with recorded() as steps:
        metrics, account, row = run_ms(market, minutes, (ENTRY, ENTRY + 31 * MINUTE))
    assert steps[0].report["mode_decision"] == UPTREND and metrics.buys == 0
    (stopped,) = [s.report for s in steps if s.report.get("uptrend_exit") == "stop"]
    assert stopped.get("uptrend_abandoned") and not stopped.get("uptrend_ended")
    assert account.uptrend is None and account.uptrend_stopped_ms is not None
    assert (metrics.uptrend_trades, metrics.uptrend_stops, metrics.uptrend_fades) == (0, 0, 0)
    assert row["modes"]["uptrend_trades"] == 0 and row["modes"]["stops"] == 0


# The rows.


def test_ms_rows_carry_their_own_strategy() -> None:
    market, t = flat_market(), at(FLAT_DAY)
    minutes = market.minutes(t, t + 10 * MINUTE)
    _, _, ms_row = run_ms(market, minutes, (t, t + 10 * MINUTE))
    assert (ms_row["strategy"], ms_row["variant"]) == (MODE_SWITCH_STRATEGY, "MS")
    assert MODE_SWITCH_STRATEGY == "mode switcher (spec-v2)"
    assert set(ms_row) == SUMMARY_FIELDS | {"variant", "modes"}
    assert set(ms_row["modes"]) == {
        "time_ms",
        "switches",
        "uptrend_trades",
        "stops",
        "fades",
        "held_at_end",
        "buy_and_hold_final",
        "decisions",
        "entries",
    }
    # Its grid cycles stay in the row's own completed_cycles, never copied into the readouts.
    assert "completed_cycles" not in ms_row["modes"]
    # The v2 scorer reads it as the candidate, and finds every field it reads.
    assert acceptance_v2.role_of(ms_row) == "MS"
    acceptance_v2.ms_fields(ms_row)
    # V0's rows keep their v1 labels and their exact layout, gated or ungated.
    for gated, label in ((True, "gated grid (price-only-v1)"), (False, "ungated grid baseline")):
        run = RunConfig("TESTUSDT", "high_first", gated, RULES, D(100), SPREAD)
        metrics, account = replay(
            CONFIG, run, minutes, market.engine, None, window=(t, t + 10 * MINUTE)
        )
        row = summarise(run, metrics, account, [])
        assert row["strategy"] == label and set(row) == SUMMARY_FIELDS


def test_ms_rows_record_buy_and_hold_exactly() -> None:
    market, t = flat_market(), at(FLAT_DAY)
    metrics, _, row = run_ms(market, market.minutes(t, t + 10 * MINUTE), (t, t + 10 * MINUTE))
    assert row["modes"]["buy_and_hold_final"] == str(metrics.hold_final)


def test_the_mode_switcher_needs_its_history_and_the_gated_features() -> None:
    market, t = flat_market(), at(FLAT_DAY)
    minutes = market.minutes(t, t + MINUTE)
    run = RunConfig("TESTUSDT", "high_first", True, RULES, D(100), SPREAD)
    for daily, hourly in ((None, market.hourly), (market.daily, None)):
        with pytest.raises(ValueError, match="needs the pair's hourly and daily history"):
            replay(
                CONFIG,
                run,
                minutes,
                market.engine,
                MS,
                daily=daily,
                hourly=hourly,
                window=(t, t + MINUTE),
            )
    with pytest.raises(ValueError, match="evaluation window"):
        replay(CONFIG, run, minutes, market.engine, MS, daily=market.daily, hourly=market.hourly)
    ungated = replace(run, gated=False)
    with pytest.raises(ValueError, match="gated"):
        replay(
            CONFIG,
            ungated,
            minutes,
            market.engine,
            MS,
            daily=market.daily,
            hourly=market.hourly,
            window=(t, t + MINUTE),
        )


def test_each_minute_reads_one_snapshot_at_its_start() -> None:
    # The four quotes of a minute see the same completed bars, so they share one snapshot, taken at
    # the minute's start: a later time in the minute would see nothing new.
    market, t = flat_market(), at(FLAT_DAY)
    seen: list[tuple[str, Any]] = []
    real = PaperSimulator.step

    def step(simulator: PaperSimulator, account: Account, frame: Any) -> dict[str, Any]:
        seen.append((frame.quote.event_id, frame.perception))
        return real(simulator, account, frame)

    with patch.object(PaperSimulator, "step", step):
        run_ms(market, market.minutes(t, t + 2 * MINUTE), (t, t + 2 * MINUTE))
    perception = Perception(market.hourly, market.daily)
    for open_ms in (t, t + MINUTE):
        snapshots = [p for event, p in seen if event.split("/")[1] == str(open_ms)]
        assert len(snapshots) == 4 and all(p is snapshots[0] for p in snapshots)
        assert snapshots[0] == perception.at(open_ms)


# Why each decision went as it did (``modes.decisions``, reporting only).


@contextmanager
def forced_exit(event_id: str) -> Iterator[None]:
    """A hard stop on the quote named: that quote's first risk evaluation says EXIT, as a 12%
    drawdown would, so the account halts (category drawdown) and restarts 24 hours later."""
    real = PaperSimulator.step

    def step(simulator: PaperSimulator, account: Account, frame: Any) -> dict[str, Any]:
        if frame.quote.event_id != event_id:
            return real(simulator, account, frame)
        evaluate = simulator.risk.evaluate
        pending = [RiskDecision(RiskAction.EXIT, ("forced hard stop",))]

        def forced(portfolio: Any) -> RiskDecision:
            return pending.pop() if pending else evaluate(portfolio)

        simulator.risk.evaluate = forced  # type: ignore[method-assign]
        try:
            return real(simulator, account, frame)
        finally:
            del simulator.risk.evaluate

    with patch.object(PaperSimulator, "step", step):
        yield


@cache
def flat_run() -> tuple[dict[str, Any], list[Step]]:
    """The flat market's first twelve hours from FLAT_DAY, every frame recorded."""
    market, t = flat_market(), at(FLAT_DAY)
    with recorded() as steps:
        _, _, row = run_ms(market, market.minutes(t, t + 12 * HOUR), (t, t + 12 * HOUR))
    return row, steps


HALT = at(FLAT_DAY, 5, 10)  # the hard stop's minute, in the flat market's sixth Grid-able hour


@cache
def halted_run() -> tuple[dict[str, Any], list[Step]]:
    """The flat market for 33 hours from FLAT_DAY, with a hard stop on HALT's second quote and
    so the restart 24 hours later, every frame recorded."""
    market, t = flat_market(), at(FLAT_DAY)
    end = t + 33 * HOUR
    with recorded() as steps, forced_exit(quote_id(HALT, 1)):
        _, _, row = run_ms(market, market.minutes(t, end), (t, end))
    return row, steps


def reasons_of(steps: list[Step]) -> list[dict[str, Any]]:
    return [step.report["mode_reasons"] for step in steps if "mode_reasons" in step.report]


def integers_with_sorted_keys(value: Any) -> bool:
    """Whether every leaf is an int (never a bool or a float) and every mapping's keys are
    sorted, so that a row's block is deterministic."""
    if isinstance(value, dict):
        return list(value) == sorted(value) and all(
            integers_with_sorted_keys(v) for v in value.values()
        )
    return type(value) is int


def made(hour: int, mode: str, uptrend: list[str], grid: list[str]) -> dict[str, Any]:
    return {
        "hour_ms": hour,
        "outcome": "made",
        "mode": mode,
        "uptrend_failures": uptrend,
        "grid_failures": grid,
    }


def test_decisions_count_each_hour_once_by_month_and_by_sole_blocker() -> None:
    jan = int(datetime(2024, 1, 31, 22, tzinfo=UTC).timestamp()) * 1000
    feb = jan + 2 * HOUR  # 2024-02-01 00:00 UTC
    decisions = ModeDecisions()
    for record in (
        made(jan, CASH, ["d1_rsi_overbought"], ["h4_not_range_or_unclear"]),
        {"hour_ms": jan + HOUR, "outcome": "halted"},
        {"hour_ms": jan + HOUR, "outcome": "halted"},  # a later frame of the same hour
        {"hour_ms": feb, "outcome": "halted"},
        made(feb, GRID, ["d1_not_up", "h4_not_up"], []),  # the halt ended within the hour
        made(feb + HOUR, UPTREND, [], ["h1_unavailable", "h4_not_range_or_unclear"]),
        {"hour_ms": feb + 2 * HOUR, "outcome": "skipped_holding"},
    ):
        decisions.record(record)
    block = decisions.report()
    assert block == {
        "by_mode": {CASH: 1, GRID: 1, UPTREND: 1},
        "by_month": {
            "2024-01": {
                "by_mode": {CASH: 1, GRID: 0, UPTREND: 0},
                "halted": 1,
                "made": 1,
                "skipped_holding": 0,
                "uptrend_blocked_by": {"d1_rsi_overbought": 1},
                "uptrend_sole_blocker": {"d1_rsi_overbought": 1},
            },
            "2024-02": {
                "by_mode": {CASH: 0, GRID: 1, UPTREND: 1},
                "halted": 0,
                "made": 2,
                "skipped_holding": 1,
                "uptrend_blocked_by": {"d1_not_up": 1, "h4_not_up": 1},
                "uptrend_sole_blocker": {},
            },
        },
        # Over the decisions where that mode was not chosen: Uptrend's Grid reasons count.
        "grid_blocked_by": {"h1_unavailable": 1, "h4_not_range_or_unclear": 2},
        "grid_sole_blocker": {"h4_not_range_or_unclear": 1},
        "halted": 1,
        "made": 3,
        "skipped_holding": 1,
        "uptrend_blocked_by": {"d1_not_up": 1, "d1_rsi_overbought": 1, "h4_not_up": 1},
        "uptrend_sole_blocker": {"d1_rsi_overbought": 1},
    }
    assert integers_with_sorted_keys(block)
    assert ModeDecisions().report()["by_month"] == {}
    with pytest.raises(RuntimeError, match="decided twice"):
        decisions.record({"hour_ms": feb + 2 * HOUR, "outcome": "skipped_holding"})


def test_rows_record_each_hours_decision_and_why() -> None:
    row, steps = flat_run()
    decisions, t = row["modes"]["decisions"], at(FLAT_DAY)
    reasons = reasons_of(steps)
    # One decision an hour, each the mode the simulator applied.
    assert [r["hour_ms"] for r in reasons] == [t + h * HOUR for h in range(12)]
    assert [r["mode"] for r in reasons] == [
        step.report["mode_decision"] for step in steps if "mode_decision" in step.report
    ]
    assert (decisions["made"], decisions["skipped_holding"], decisions["halted"]) == (12, 0, 0)
    assert decisions["by_mode"] == {
        mode: sum(r["mode"] == mode for r in reasons) for mode in (CASH, GRID, UPTREND)
    }
    assert decisions["by_mode"] == {CASH: 3, GRID: 9, UPTREND: 0}
    # The first three hours are RANGE, but not yet for four consecutive decisions, and Grid's
    # other conditions hold: that rule alone kept Grid out. Uptrend's two are the flat states.
    assert [r["grid_failures"] for r in reasons[:3]] == [["range_decisions_below_4"]] * 3
    assert decisions["grid_blocked_by"] == {"range_decisions_below_4": 3}
    assert decisions["grid_sole_blocker"] == {"range_decisions_below_4": 3}
    assert decisions["uptrend_blocked_by"] == {"d1_not_up": 12, "h4_not_up": 12}
    assert decisions["uptrend_sole_blocker"] == {}
    assert decisions["by_month"] == {
        "2023-03": {
            "by_mode": {CASH: 3, GRID: 9, UPTREND: 0},
            "halted": 0,
            "made": 12,
            "skipped_holding": 0,
            "uptrend_blocked_by": {"d1_not_up": 12, "h4_not_up": 12},
            "uptrend_sole_blocker": {},
        }
    }
    assert integers_with_sorted_keys(decisions)


def test_halted_hours_count_once_and_the_restart_hour_as_decided() -> None:
    row, steps = halted_run()
    assert (row["hard_drawdown_halts"], row["drawdown_restarts"]) == (1, 1)
    decisions, t = row["modes"]["decisions"], at(FLAT_DAY)
    # Decided from 00:00 to 05:00, the hard stop at 05:10, halted from 06:00 to the restart 24
    # hours on, whose hour decides once the halt has ended, as do the three after it.
    halted = {r["hour_ms"] for r in reasons_of(steps) if r["outcome"] == "halted"}
    assert halted == {t + h * HOUR for h in range(6, 30)}
    restarted = next(i for i, step in enumerate(steps) if "restart" in step.report)
    assert steps[restarted].quote.observed_at.startswith("2023-03-13T05:10")
    assert (decisions["made"], decisions["halted"], decisions["skipped_holding"]) == (10, 23, 0)
    assert decisions["by_month"]["2023-03"]["halted"] == 23


def test_rows_record_the_hours_skipped_while_holding_and_the_pause_after() -> None:
    _, _, _, row, steps = rising_run()
    decisions = row["modes"]["decisions"]
    # Every hour has its outcome: the entry's decision, the hours held, then Cash.
    hours = (at(RISE_DAYS + 2) - ENTRY) // HOUR
    assert len({r["hour_ms"] for r in reasons_of(steps)}) == hours
    assert decisions["made"] + decisions["skipped_holding"] == hours
    assert decisions["skipped_holding"] > 0 and decisions["by_mode"][UPTREND] == 1
    # The run ends within 24 hours of the stop, so the pause is among each later decision's
    # reasons, with the fall's 4h state and regime.
    assert decisions["uptrend_blocked_by"]["reentry_pause"] == decisions["by_mode"][CASH] > 0


# The SHA-256 of the three runs above, every frame's report and the row, recorded on main at
# 739ae6e before the decision reasons existed. With the reasons set aside, nothing moved.
NUMBERS_BEFORE_REASONS = "6db23ef73694c9063c80ba0660993aa8be28544566c83193b8f2466cfcb6ffc4"


def canonical(value: Any) -> Any:
    """``value`` in a form JSON writes the same way on any platform: a float to 6 significant
    digits, so a last-digit difference in a platform's libm cannot move the digest."""
    if isinstance(value, float):
        return format(value, ".6g")
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [canonical(item) for item in value]
    return value


def numbers_digest(runs: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> str:
    """The SHA-256 of each run's row without ``modes.decisions`` and its frames' reports without
    ``mode_reasons``."""
    payload = []
    for row, reports in runs:
        row = copy.deepcopy(row)
        row["modes"].pop("decisions", None)
        row["modes"].pop("entries", None)
        frames = [
            {k: v for k, v in report.items() if k not in ("mode_reasons", "uptrend_entry")}
            for report in reports
        ]
        payload.append({"row": row, "reports": frames})
    text = json.dumps(canonical(payload), sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_reasons_change_no_decision_and_no_number() -> None:
    _, _, _, rising_row, rising_steps = rising_run()
    runs = [(rising_row, rising_steps), flat_run(), halted_run()]
    digest = numbers_digest([(row, [step.report for step in steps]) for row, steps in runs])
    assert digest == NUMBERS_BEFORE_REASONS


class RunJobTests(mc.RunDataset):
    """The mode switcher through ``run_job``, on ``test_backtest_masked_checks``' DOGEUSDT window
    (evaluation 2020-03, whose first eight hours have minutes)."""

    def test_the_job_measures_the_mode_switcher_over_the_evaluation_window(self) -> None:
        # The job gives the replay the pair's hourly and daily bars and the evaluation window. A
        # masked hour drops its minutes, as in any run, and the hours after the last minute count
        # to the last mode, so the modes' times still sum to the whole of 2020-03.
        masked = mc.MAR_2020 + 2 * HOUR
        row = run_job(
            self.spec_path,
            mc.CONFIG,
            self.data,
            "ETHUSDT",
            "high_first",
            True,
            None,
            variant_policy("MS"),
            masks={"ETHUSDT": frozenset({masked})},
        )
        self.assertEqual((MODE_SWITCH_STRATEGY, "MS"), (row["strategy"], row["variant"]))
        self.assertEqual([], row["accounting_problems"])
        self.assertEqual(1, row["masked_hours"])
        self.assertEqual(mc.APR_2020 - mc.MAR_2020, sum(times(row).values()))
        self.assertEqual([], result_failures([row]))
