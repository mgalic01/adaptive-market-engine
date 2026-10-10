"""Spec v2's mode switcher inside the paper simulator (§4-§7), one test per rule.

Frames are built from stub ``Snapshot``s and ``Quote``s: the snapshot's daily part is read the way
``Perception.at`` reads it (the bar due, and the latest bar closed), so a test can drop a daily bar
or skip days of quotes. Prices, sizes and states are constructed to hit each rule; nothing here is
backtest evidence. A few tests force one risk evaluation (``Run.forced``) to place a drain or a
hard stop at a chosen point of a frame, where no price path could put it.

The rules in these tests use a tick of 0.01, a lot of 0.001, a minimum notional of 5, no slippage,
a maker fee of 0 and a taker fee of 0.0009. So a buy at an ask of 100 pays 100.09 a unit, and a
stop at 97 or 94 comes from a daily close of 100 with an ATR of 1 or 2.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from crypto_grid_bot.backtest.jobs import variant_name, variant_policy
from crypto_grid_bot.backtest.replay import (
    Metrics,
    RequestCountingOrders,
    _record_fills,
    check_accounting,
    order_requests,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals, RiskAction, RiskDecision
from crypto_grid_bot.simulation import runner
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import exit_state
from crypto_grid_bot.simulation.models import LimitOrder, MarketRules, Quote
from crypto_grid_bot.simulation.runner import VARIANTS, Frame, PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.store import encode
from crypto_grid_bot.simulation.uptrend import UptrendPosition
from crypto_grid_bot.strategy.mode_selector import Mode
from crypto_grid_bot.strategy.perception import DailyPoint, Snapshot, TrendState

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(ROOT / "config" / "default.toml")
RULES = MarketRules(
    symbol="BTCUSDT",
    tick_size=D("0.01"),
    quantity_step=D("0.001"),
    minimum_notional=D("5"),
    fee_rate=D("0"),
    slippage_rate=D("0"),
    participation=D("0.10"),
    taker_fee_rate=D("0.0009"),
)
MS = SimulationPolicy(mode_switch=True, flow_block_entry=True)
MINUTE, HOUR, DAY = 60_000, 3_600_000, 86_400_000
DAY0 = int(datetime(2024, 3, 1, tzinfo=UTC).timestamp()) * 1000  # daily bar 0 opens here
UP, DOWN = TrendState.UP, TrendState.DOWN
RANGE, UNAVAILABLE = TrendState.RANGE, TrendState.UNAVAILABLE
# V0's classifier: a quiet market is RANGE; an ADX of 30 with no direction is TRANSITION, which
# Uptrend allows but V0's opportunity score does not (0.95 x 0.35 is below its 0.70).
QUIET = (0.02, -0.01, 0.01, 0.02, 0.01, 14.0)
UNDIRECTED = (0.02, -0.01, 0.01, 0.02, 0.01, 30.0)
CANDIDATE = CandidateMetrics("BTCUSDT", 0.95, 0.95, 0.95, 0.95, 1, 0, 0.01, 100)


def at(day: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    return DAY0 + day * DAY + hour * HOUR + minute * MINUTE + second * 1000


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat()


def days(*bars: tuple[Any, ...]) -> tuple[DailyPoint, ...]:
    """Daily points from day 0: (close, atr) or (close, atr, state), Up by default."""
    return tuple(
        DailyPoint(DAY0 + i * DAY, bar[2] if len(bar) > 2 else UP, D(str(bar[0])), D(str(bar[1])))
        for i, bar in enumerate(bars)
    )


# c0 = 100 with an ATR of 1: an entry's stop starts at 97.
POINTS = days((100, 1))


def snapshot(
    ms: int, points: tuple[DailyPoint, ...], *, h4: TrendState = UP, d1_rsi: str = "60"
) -> Snapshot:
    """What ``Perception.at`` shows at ``ms``: the daily bar due (opening a day before today's
    midnight) or UNAVAILABLE, and the latest bar closed. The 1h inputs are Grid's band."""
    due = ms // DAY * DAY - DAY
    latest = bisect_right([p.open_ms for p in points], ms - DAY) - 1
    index = latest if latest >= 0 else None
    bar = points[index] if index is not None and points[index].open_ms == due else None
    return Snapshot(
        h1_available=True,
        h1_rsi=D(50),
        h1_adx=D(15),
        h1_width=D(1),
        h1_width_median=D(2),
        h4_state=h4,
        d1_state=UNAVAILABLE if bar is None else bar.state,
        d1_rsi=None if bar is None else D(d1_rsi),
        d1_close=None if bar is None else bar.close,
        d1_atr=None if bar is None else bar.atr,
        d1_open_ms=None if index is None else points[index].open_ms,
        d1_points=points,
        d1_index=index,
    )


def frame(
    ms: int,
    *,
    bid: str | None = None,
    ask: str | None = None,
    bid_size: str = "100",
    ask_size: str = "100",
    points: tuple[DailyPoint, ...] = POINTS,
    h4: TrendState = UP,
    signals: tuple[float, ...] = QUIET,
    share: D | None = D("0.5"),
    late: int = 0,
) -> Frame:
    """One quote at ``ms``, a tick wide: give the bid or the ask. ``late`` delays its receipt by
    that many seconds (31 makes it stale). A share of 0.5 lifts F's block."""
    if bid is None:
        ask_price = D(ask or "100")
        bid_price = ask_price - D("0.01")
    else:
        bid_price = D(bid)
        ask_price = D(ask) if ask is not None else bid_price + D("0.01")
    when = datetime.fromtimestamp(ms / 1000, UTC)
    quote = Quote(
        f"q/{ms}",
        "BTCUSDT",
        when.isoformat(),
        iso(ms + late * 1000),
        bid_price,
        ask_price,
        D(bid_size),
        D(ask_size),
    )
    return Frame(
        quote,
        MarketSignals(*signals, observed_at=when),
        CANDIDATE,
        bid_price,
        D(1),
        flow_share=share,
        perception=snapshot(ms, points, h4=h4),
    )


class Run:
    """One replay account under the mode switcher. ``forced`` holds the next risk evaluations'
    actions, one per evaluation, None meaning the real one."""

    def __init__(self, policy: SimulationPolicy = MS) -> None:
        self.sim = PaperSimulator(Path(":memory:"), CONFIG, RULES, D(100), policy)
        self.account = self.sim.store.read()
        self.sim.close()  # step() uses no store
        self.forced: list[RiskAction | None] = []
        real = self.sim.risk.evaluate

        def evaluate(portfolio: Any) -> RiskDecision:
            action = self.forced.pop(0) if self.forced else None
            return real(portfolio) if action is None else RiskDecision(action, (f"{action}",))

        self.sim.risk.evaluate = evaluate  # type: ignore[method-assign]
        self.reports: list[dict[str, Any]] = []

    def step(self, item: Frame) -> dict[str, Any]:
        report = self.sim.step(self.account, item)
        self.reports.append(report)
        return report


def entered(
    run: Run, ms: int | None = None, *, points: tuple[DailyPoint, ...] = POINTS
) -> UptrendPosition:
    """Enter at a decision with a deep ask at 100 (0.599 bought), then end the entry by its
    budget on the next quote, a minute later."""
    ms = at(1, 10) if ms is None else ms
    first = run.step(frame(ms, ask="100", points=points))
    assert first["mode_decision"] == "uptrend" and bought(first) == [D("0.599")]
    run.step(frame(ms + MINUTE, ask="100", points=points))
    position = run.account.uptrend
    assert position is not None and position.phase == "holding"
    return position


def bought(report: dict[str, Any]) -> list[D]:
    return [f["quantity"] for f in report["fills"] if f["order_id"].startswith("uptrend/")]


def sold(report: dict[str, Any]) -> list[D]:
    return [f["quantity"] for f in report["fills"] if f["order_id"].startswith("exit/")]


def grid(run: Run, *, buy: bool = True) -> None:
    """Grid mode with a grid whose two sells rest at 100.50 and 101.50 over 0.2 held, and
    (unless ``buy`` is False) one untouched buy at 98.00."""
    account = run.account
    account.mode = "grid"
    account.cash = D("80")  # 0.1 bought at 99.50 and 0.1 at 100.50, maker fee 0
    account.inventory = D("0.2")
    account.grid_lower, account.grid_upper = D("98"), D("102")
    orders = [
        LimitOrder("g/1/sell", "sell", D("100.50"), D("0.1"), D("0.1"), reentry=D("99.50")),
        LimitOrder("g/2/sell", "sell", D("101.50"), D("0.1"), D("0.1"), reentry=D("100.50")),
    ]
    if buy:
        orders.append(LimitOrder("g/0", "buy", D("98.00"), D("0.1"), D("0.1"), target=D("99")))
    for order in orders:
        account.orders[order.order_id] = order


# --- The policy, the frame and the paper account ------------------------------------------------


def test_policy_mode_switch_requires_f_alone_and_is_named_ms():
    policy = SimulationPolicy(mode_switch=True, flow_block_entry=True)
    assert (policy.variant, "MS" in VARIANTS) == ("MS", True)
    assert policy.identity()["mode_switch"] is True
    assert "mode_switch" not in SimulationPolicy().identity()
    message = "spec v2's mode switcher runs with F's block and nothing else"
    with pytest.raises(ValueError, match=message):
        SimulationPolicy(mode_switch=True)  # F's block is part of it
    for flag in (
        {"trend_switch": True},
        {"inventory_cap": D("0.40")},
        {"volume_exit": True},
        {"funding_gate": True},
        {"cycle_gate": True},
        {"structure": True},
    ):
        with pytest.raises(ValueError, match=message):
            SimulationPolicy(mode_switch=True, flow_block_entry=True, **flag)
    with pytest.raises(ValueError, match="mode_switch must be a boolean"):
        SimulationPolicy(mode_switch=1, flow_block_entry=True)  # type: ignore[arg-type]


def test_payload_without_perception_is_unchanged():
    frames = demo_frames(2)
    full = replace(frames[0], epoch="DEMOUSDT/0", flow_share=D("0.5"), funding_blocks=False)
    text = "\n".join(encode(item.payload()) for item in [*frames, full])
    # The SHA-256 of these payloads, recorded before Frame.perception existed.
    expected = "ccf363e10219a25b44105ad1a467b098d0c2bf8acbc9f29c97ba0c45ee85bd5d"
    assert hashlib.sha256(text.encode()).hexdigest() == expected
    assert "perception" not in frames[0].payload()
    seen = replace(frames[0], perception=snapshot(at(1), POINTS))
    assert seen.payload()["perception"]["d1_index"] == 0


def test_paper_account_refuses_mode_switch(tmp_path):
    simulator = PaperSimulator(tmp_path / "paper.db", CONFIG, RULES, D(100), MS)
    try:
        with pytest.raises(ValueError, match="mode switcher runs in historical replay only"):
            simulator.process(frame(at(1, 10)))
    finally:
        simulator.close()


# --- Entry: when, how much, at what stop --------------------------------------------------------


def test_cash_to_uptrend_enters_with_its_limits_and_initial_stop():
    run = Run()
    points = days((100, 2))  # c0 = 100, ATR 2: the stop is 100 - 3 x 2 = 94
    report = run.step(frame(at(1, 10), ask="100", points=points))
    account, position = run.account, run.account.uptrend
    assert (report["mode_decision"], account.mode, account.mode_switches) == (
        "uptrend",
        "uptrend",
        1,
    )
    assert position is not None
    # Equity 100: a cash cap of 0.60 x 100 and a risk allowance of 0.04 x 100.
    assert (position.cash_cap, position.risk_allowance) == (D(60), D(4))
    assert (position.stop, position.highest_close, position.stop_day_ms) == (D(94), D(100), DAY0)
    assert (position.entered_at, position.phase) == (iso(at(1, 10)), "entering")
    # The cash bound, 60 / 100.09 = 0.5994..., binds before the risk bound, 4 / 6 = 0.666...
    fill = report["fills"][0]
    assert [f["order_id"] for f in report["fills"]] == [f"uptrend/buy/q/{at(1, 10)}"]
    assert (fill["price"], fill["quantity"], fill["fee"]) == (D(100), D("0.599"), D("0.05391"))
    assert (position.quantity, position.spent) == (D("0.599"), D("59.95391"))
    assert position.risk_used == D("0.599") * 6
    assert (account.inventory, account.cash) == (D("0.599"), D("40.04609"))
    # What is left of the cap (0.04609) buys less than the minimum notional: the entry ends.
    report = run.step(frame(at(1, 10, 1), ask="100", points=points))
    assert (bought(report), position.phase, account.uptrend_stopped_ms) == ([], "holding", None)


def test_thin_depth_waits_and_an_exhausted_budget_ends_the_entry():
    run = Run()
    # An ask size of 0.4 lets the participation limit buy 0.04, 4 USDT: below the minimum.
    report = run.step(frame(at(1, 10), ask="100", ask_size="0.4"))
    position = run.account.uptrend
    assert position is not None and (bought(report), position.phase) == ([], "entering")
    assert position.quantity == 0
    report = run.step(frame(at(1, 10, 1), ask="100"))  # a deep ask: the entry buys at once
    assert (bought(report), position.phase) == ([D("0.599")], "entering")
    report = run.step(frame(at(1, 10, 2), ask="100"))  # the budget is spent: the entry ends
    assert (bought(report), position.phase, position.quantity) == ([], "holding", D("0.599"))


def test_entry_continues_across_quotes_under_participation():
    run = Run()
    reports = [run.step(frame(at(1, 10, i), ask="100", ask_size="2")) for i in range(4)]
    # 0.2 a quote (10% of 2) until the cash cap is nearly spent: 60 - 2 x 20.018 = 19.964
    # buys 0.199 at 100.09 a unit, and the 0.04609 left buys nothing.
    assert [bought(report) for report in reports] == [
        [D("0.2")],
        [D("0.2")],
        [D("0.199")],
        [],
    ]
    position = run.account.uptrend
    assert position is not None
    assert (position.phase, position.quantity, position.spent) == (
        "holding",
        D("0.599"),
        D("59.95391"),
    )
    assert reports[1].get("mode_decision") is None  # the entry went on without a decision


def test_uptrend_buys_are_in_the_report_and_reconcile():
    run = Run()
    first = run.step(frame(at(1, 10), ask="100", ask_size="3"))  # 0.3, then 0.299
    second = run.step(frame(at(1, 10, 1), ask="100", ask_size="3"))
    assert (bought(first), bought(second)) == ([D("0.3")], [D("0.299")])
    metrics = Metrics(peak_equity=D(100), final_equity=D(100))
    for report in run.reports:
        _record_fills(metrics, report["fills"], report.get("exit_reason"))
        metrics.frames += 1
        metrics.final_equity = D(report["total_equity"])
    assert (metrics.buys, metrics.bought) == (2, D("0.599"))
    assert metrics.buy_notional == D("59.9")
    assert metrics.buy_fees == D("59.9") * D("0.0009")
    assert check_accounting(SimpleNamespace(initial_quote=D(100)), metrics, run.account) == []


def test_uptrend_buys_count_as_order_requests():
    run = Run()
    orders = run.account.orders = RequestCountingOrders()
    requests = 0
    for i in range(3):
        since = orders.requests
        report = run.step(frame(at(1, 10, i), ask="100", ask_size="2"))
        requests += order_requests(orders, since, report["fills"])
    assert requests == 3  # one off-book request per entry buy, as for an exit/ sell


def test_entry_starts_only_on_a_decision_frame():
    # A grid that becomes flat mid-hour enters at the next decision, and not before.
    run = Run()
    grid(run, buy=False)
    run.account.decision_hour_ms = at(1, 9)
    report = run.step(frame(at(1, 10), bid="100"))
    assert (report["mode_decision"], bought(report)) == ("uptrend", [])  # sells still rest
    run.step(frame(at(1, 10, 10), bid="100.60"))  # the sell at 100.50 fills
    run.step(frame(at(1, 10, 20), bid="101.60"))  # and the one at 101.50: flat
    assert (run.account.orders, run.account.inventory) == ({}, 0)
    for minute in (21, 40, 59):
        assert bought(run.step(frame(at(1, 10, minute), bid="101.60"))) == []
    report = run.step(frame(at(1, 11), bid="101.60"))
    assert report["mode_decision"] == "uptrend" and len(bought(report)) == 1
    # A start refused at a decision (s <= 0: an ask at the stop) is not retried before the next.
    run = Run()
    report = run.step(frame(at(1, 10), ask="97"))
    assert (report["mode_decision"], run.account.uptrend) == ("uptrend", None)
    assert bought(run.step(frame(at(1, 10, 5), ask="100"))) == []
    assert len(bought(run.step(frame(at(1, 11), ask="100")))) == 1
    # Likewise a start the risk layer refuses (REDUCE), even once its recovery has ended.
    run = Run()
    run.forced = [RiskAction.REDUCE]
    report = run.step(frame(at(1, 10), ask="100"))
    assert (report["mode_decision"], run.account.uptrend) == ("uptrend", None)
    for minute in (1, 2, 3):
        assert bought(run.step(frame(at(1, 10, minute), ask="100"))) == []
    assert not run.account.risk_recovery
    assert len(bought(run.step(frame(at(1, 11), ask="100")))) == 1


def test_no_entry_when_price_at_or_below_initial_stop():
    for ask in ("97", "96"):  # the buy price at the stop (s = 0) or below it
        run = Run()
        report = run.step(frame(at(1, 10), ask=ask))
        assert (report["mode_decision"], run.account.uptrend) == ("uptrend", None)
        assert run.account.uptrend_stopped_ms is None  # not a stop-out: no pause
        # The next decision may try again.
        assert len(bought(run.step(frame(at(1, 11), ask="100")))) == 1


def test_no_entry_when_the_spread_straddles_the_initial_stop():
    run = Run()
    # The buy price, 97.01, is above the stop of 97, but the bid is at it.
    report = run.step(frame(at(1, 10), bid="97.00", ask="97.01"))
    assert (report["mode_decision"], bought(report)) == ("uptrend", [])
    assert (run.account.uptrend, run.account.uptrend_stopped_ms) == (None, None)
    # A tick higher, the next decision enters.
    assert len(bought(run.step(frame(at(1, 11), bid="97.01", ask="97.02")))) == 1


def test_flat_ignores_dust_and_fragments_but_not_resting_orders():
    # Dust: 0.001 held, 0.1 USDT at the bid.
    run = Run()
    run.account.cash -= D("0.1")
    run.account.inventory = D("0.001")
    assert len(bought(run.step(frame(at(1, 10), ask="100")))) == 1
    # Two of F's held fragments, 0.03 each, 3.03 and 3.06 at their targets, and 6 USDT
    # together at the bid, which is sellable: still flat, as v1's unpaired exit exempts them.
    run = Run()
    run.account.cash -= D("6")
    run.account.inventory = D("0.06")
    run.account.flow_fragments = {D("101"): D("0.03"), D("102"): D("0.03")}
    report = run.step(frame(at(1, 10), ask="100", share=None))  # F's block stays on
    assert len(bought(report)) == 1 and sold(report) == []
    assert run.sim.held_fragments(run.account) == D("0.06")
    # The same 0.06 without F's hold is sellable inventory: not flat.
    run = Run()
    run.account.cash -= D("6")
    run.account.inventory = D("0.06")
    report = run.step(frame(at(1, 10), ask="100"))
    assert (report["mode_decision"], bought(report)) == ("uptrend", [])
    # A resting order, a sell or a buy alone, is not flat.
    for orders in (
        [LimitOrder("s", "sell", D("101"), D("0.06"), D("0.06"))],
        [LimitOrder("b", "buy", D("90"), D("0.06"), D("0.06"), target=D("91"))],
    ):
        run = Run()
        if orders[0].side == "sell":
            run.account.cash -= D("6")
            run.account.inventory = D("0.06")
        run.account.orders = {order.order_id: order for order in orders}
        report = run.step(frame(at(1, 10), ask="100", share=None))
        assert (report["mode_decision"], bought(report)) == ("uptrend", [])


def test_uptrend_enters_during_a_range_exit_cooldown_which_leaves_it_alone():
    run = Run()
    account = run.account
    # A grid timed out of its band an hour ago and has been sold: v1's 24-hour re-centring
    # cooldown runs, and the price is still outside the old band.
    account.range_exit, account.range_exit_since = True, iso(at(1, 9))
    account.grid_lower, account.grid_upper = D("90"), D("95")
    account.pause, account.draining = "outside-range timeout: exit to cash", True
    report = run.step(frame(at(1, 10), ask="100"))
    assert report["mode_decision"] == "uptrend" and bought(report) == [D("0.599")]
    assert sold(report) == [] and "exit_blocked" not in report
    for minute in (1, 2, 3):
        report = run.step(frame(at(1, 10, minute), ask="100"))
        assert (bought(report), sold(report)) == ([], [])
    assert (account.range_exit, account.inventory) == (True, D("0.599"))


def test_range_exit_branch_with_only_the_position_does_not_crash():
    run = Run()
    position = entered(run)
    account = run.account
    account.range_exit, account.range_exit_since = True, iso(at(1, 10, 2))
    account.grid_lower, account.grid_upper = D("90"), D("95")
    with (
        patch.object(runner, "liquidate", wraps=runner.liquidate) as liquidate,
        patch.object(runner, "reduce_unreserved", wraps=runner.reduce_unreserved) as reduce,
    ):
        for minute in (3, 4, 5):
            report = run.step(frame(at(1, 10, minute), bid="100"))
            assert sold(report) == [] and "exit_blocked" not in report
    assert (liquidate.call_count, reduce.call_count) == (0, 0)
    assert (position.quantity, account.inventory, account.range_exit) == (
        D("0.599"),
        D("0.599"),
        True,
    )


# --- Staying in Uptrend, the trailing stop and the exits ----------------------------------------


def test_staying_in_uptrend_when_4h_turns_range():
    run = Run()
    position = entered(run)
    for hour, h4 in ((11, RANGE), (12, DOWN)):
        report = run.step(frame(at(1, hour), bid="100", h4=h4))
        assert "mode_decision" not in report and sold(report) == []
        assert (run.account.mode, run.account.uptrend) == ("uptrend", position)
        assert (run.account.decision_hour_ms, run.account.range_decisions) == (at(1, hour), 0)


def test_trailing_stop_starts_its_high_at_the_pre_entry_close():
    run = Run()
    points = days((100, 2), (99, 1))
    position = entered(run, points=points)
    assert (position.stop, position.highest_close) == (D(94), D(100))
    report = run.step(frame(at(2), bid="99", points=points))
    # The high stays at c0 = 100, so the stop is 100 - 3 x 1 = 97; from the entry's own
    # closes only it would be 99 - 3 = 96.
    assert (position.highest_close, position.stop, position.stop_day_ms) == (
        D(100),
        D(97),
        DAY0 + DAY,
    )
    assert (position.phase, sold(report)) == ("holding", [])


def test_trend_fade_exit_at_daily_close():
    run = Run()
    points = days((100, 1), (101, 1, DOWN))
    position = entered(run, points=points)
    report = run.step(frame(at(2), bid="100", points=points))
    assert (report["uptrend_exit"], position.exit_reason) == ("fade", "fade")
    assert (sold(report), report["exit_reason"]) == ([D("0.599")], "uptrend_fade")
    assert report["uptrend_ended"] and run.account.uptrend is None
    assert run.account.uptrend_stopped_ms is None  # a fade starts no pause


def test_unavailable_daily_state_triggers_trend_fade_exit():
    run = Run()
    position = entered(run)  # day 1's daily bar never arrives
    view = snapshot(at(2), POINTS)
    assert (view.d1_state, view.d1_open_ms, view.d1_index) == (UNAVAILABLE, DAY0, 0)
    report = run.step(frame(at(2), bid="100"))  # the first frame of the new UTC day
    assert (report["uptrend_exit"], position.exit_reason) == ("fade", "fade")
    assert sold(report) == [D("0.599")] and run.account.uptrend is None


def test_daily_closes_missed_in_a_quote_gap_are_each_processed():
    # Three closes pass with no quote. The middle one is not Up: the first quote exits 2,
    # with the stop the first close raised (102 - 3 = 99) kept.
    run = Run()
    points = days((100, 1), (102, 1), (101, 1, DOWN), (103, 1))
    position = entered(run, points=points)
    report = run.step(frame(at(4, 10), bid="102", points=points))
    assert (report["uptrend_exit"], position.stop, position.stop_day_ms) == (
        "fade",
        D(99),
        DAY0 + DAY,
    )
    # All three Up: the stop trails the highest close in the gap, 106 - 3 = 103.
    run = Run()
    points = days((100, 1), (102, 1), (106, 1), (104, 1))
    position = entered(run, points=points)
    report = run.step(frame(at(4, 10), bid="105", points=points))
    assert "uptrend_exit" not in report and position.phase == "holding"
    assert (position.highest_close, position.stop, position.stop_day_ms) == (
        D(106),
        D(103),
        DAY0 + 3 * DAY,
    )


def test_raised_stop_is_checked_on_the_same_quote():
    run = Run()
    points = days((100, 2), (103, 2))
    position = entered(run, points=points)  # the stop starts at 94
    # The first quote after day 1's close: above the old stop, below the raised 103 - 6 = 97.
    report = run.step(frame(at(2), bid="96", points=points))
    assert (position.stop, report["uptrend_exit"]) == (D(97), "stop")
    assert run.account.uptrend_stopped_ms == at(2)


def test_missed_closes_recheck_the_stop_after_each():
    run = Run()
    points = days((100, 1), (104, 1), (95, 1, DOWN))
    position = entered(run, points=points)
    # Day 1 raises the stop to 104 - 3 = 101, above the bid; day 2 is not Up. The stop fires
    # first, so the exit is 1 and not 2.
    report = run.step(frame(at(3, 5), bid="99", points=points))
    assert (report["uptrend_exit"], position.stop, position.stop_day_ms) == (
        "stop",
        D(101),
        DAY0 + DAY,
    )
    assert run.account.uptrend_stopped_ms == at(3, 5)
    points = days((100, 1), (104, 1), (95, 1, DOWN), (99, 1))
    report = run.step(frame(at(4, 4), ask="100", points=points))  # its 24-hour pause runs
    assert (report["mode_decision"], bought(report)) == ("cash", [])


def test_entry_still_buying_at_a_daily_close_ends_there():
    run = Run()
    points = days((100, 1), (103, 1))
    run.step(frame(at(1, 23), ask="100", ask_size="2", points=points))
    run.step(frame(at(1, 23, 59), ask="100", ask_size="2", points=points))
    position = run.account.uptrend
    assert position is not None and (position.phase, position.quantity) == ("entering", D("0.4"))
    report = run.step(frame(at(2), bid="102.50", ask_size="2", points=points))
    # It holds what it bought, and day 1's close trails the stop: max(97, 103 - 3) = 100.
    assert (bought(report), position.phase, position.quantity) == ([], "holding", D("0.4"))
    assert (position.highest_close, position.stop) == (D(103), D(100))


def test_stop_exit_then_24h_reentry_pause():
    run = Run()
    points = days((100, 1), (100, 1))
    entered(run, points=points)
    report = run.step(frame(at(1, 12), bid="96.99", points=points))
    assert report["uptrend_exit"] == "stop" and report["uptrend_ended"]
    assert run.account.uptrend_stopped_ms == at(1, 12)
    report = run.step(frame(at(2, 11), ask="100", points=points))  # 23 hours later
    assert (report["mode_decision"], bought(report)) == ("cash", [])
    report = run.step(frame(at(2, 12), ask="100", points=points))  # exactly 24 hours: it may
    assert report["mode_decision"] == "uptrend" and len(bought(report)) == 1


def test_stop_before_any_fill_ends_the_entry_and_starts_the_pause():
    run = Run()
    run.step(frame(at(1, 10), ask="100", ask_size="0.4"))  # too thin to buy
    assert run.account.uptrend is not None and run.account.uptrend.quantity == 0
    report = run.step(frame(at(1, 10, 1), bid="96.99"))
    assert (report["uptrend_exit"], report.get("uptrend_abandoned")) == ("stop", True)
    assert "uptrend_ended" not in report and run.account.uptrend is None
    assert run.account.uptrend_stopped_ms == at(1, 10, 1)
    report = run.step(frame(at(1, 11), ask="100"))
    assert (report["mode_decision"], bought(report)) == ("cash", [])


def test_stop_pause_runs_from_the_first_trigger():
    run = Run()
    points = days((100, 1), (100, 1))
    entered(run, points=points)
    # The stop triggers at 12:00, and its sale takes three quotes (0.2 of a bid size of 2).
    for minute, bid in ((0, "96.99"), (1, "96.99"), (2, "96.99")):
        report = run.step(frame(at(1, 12, minute), bid=bid, bid_size="2", points=points))
    assert report["uptrend_ended"] and run.account.uptrend_stopped_ms == at(1, 12)
    # 24 hours after the trigger, though 23:58 after the last sale, a decision may enter.
    report = run.step(frame(at(2, 12), ask="100", points=points))
    assert report["mode_decision"] == "uptrend" and len(bought(report)) == 1


def test_exit_completing_on_a_frame_ends_the_position_there():
    run = Run()
    entered(run)
    report = run.step(frame(at(1, 10, 30), bid="96.99"))
    assert (sold(report), report["uptrend_ended"]) == ([D("0.599")], True)
    assert "uptrend_abandoned" not in report
    assert (run.account.uptrend, run.account.inventory) == (None, 0)


def test_exit_at_the_top_of_an_hour_leaves_the_next_decision_to_the_next_hour():
    run = Run()
    entered(run)
    report = run.step(frame(at(1, 12), bid="96.99"))  # the hour's first quote
    assert report["uptrend_ended"] and "mode_decision" not in report
    assert run.account.decision_hour_ms == at(1, 12)
    for minute in (10, 30, 59):
        report = run.step(frame(at(1, 12, minute), ask="100"))
        assert "mode_decision" not in report and bought(report) == []
        assert run.account.mode == "uptrend"
    report = run.step(frame(at(1, 13), ask="100"))
    assert report["mode_decision"] == "cash"  # the stop's pause


def test_exit_reason_labels_every_sale_until_the_end():
    run = Run()
    entered(run)
    labels = []
    for minute, bid in ((20, "96.99"), (21, "98"), (22, "98")):  # the bid recovers
        report = run.step(frame(at(1, 12, minute), bid=bid, bid_size="2"))
        labels.append((report["exit_reason"], sold(report)))
    assert labels == [
        ("uptrend_stop", [D("0.2")]),
        ("uptrend_stop", [D("0.2")]),
        ("uptrend_stop", [D("0.199")]),
    ]
    assert report["uptrend_ended"] and run.account.uptrend is None
    assert sum(r.get("uptrend_exit") == "stop" for r in run.reports) == 1


def test_uptrend_exit_pnl_has_its_own_labels():
    run = Run()
    entered(run)
    run.step(frame(at(1, 12), bid="96.99"))
    metrics = Metrics()
    for report in run.reports:
        _record_fills(metrics, report["fills"], report.get("exit_reason"))
    assert set(metrics.exit_pnl_by_reason) == {"uptrend_stop"}


# --- The risk layer -----------------------------------------------------------------------------


def test_daily_loss_pause_and_soft_reduce_drain_the_uptrend_position_to_flat():
    # A daily-loss PAUSE: at 95, 0.599 bought at 100 has lost more than 3% of the day's 100.
    run = Run()
    position = entered(run, points=days((100, 2)))  # stop 94, below the 95
    report = run.step(frame(at(1, 10, 2), bid="95", bid_size="3", points=days((100, 2))))
    assert (position.phase, position.exit_reason, report["uptrend_exit"]) == (
        "exiting",
        "risk",
        "risk",
    )
    assert (sold(report), report["exit_reason"]) == ([D("0.3")], "uptrend_risk")
    assert run.account.uptrend is position and run.account.risk_recovery
    report = run.step(frame(at(1, 10, 3), bid="95", bid_size="3", points=days((100, 2))))
    assert (sold(report), report["uptrend_ended"]) == ([D("0.299")], True)
    assert (run.account.uptrend, run.account.inventory) == (None, 0)
    # A soft-drawdown REDUCE: more than 8% below an earlier high of 109.
    run = Run()
    position = entered(run)
    run.account.risk_high = run.account.measure_high = D("109")
    report = run.step(frame(at(1, 10, 2), bid="100"))
    assert (position.phase, report["uptrend_exit"], report["exit_reason"]) == (
        "exiting",
        "risk",
        "uptrend_risk",
    )
    assert report["uptrend_ended"] and run.account.uptrend is None
    assert run.account.episode_since and run.account.risk_recovery


def test_risk_drain_ends_a_partial_entry_at_once():
    run = Run()
    run.step(frame(at(1, 10), ask="100", ask_size="2"))
    run.step(frame(at(1, 10, 1), ask="100", ask_size="2"))
    position = run.account.uptrend
    assert position is not None and position.quantity == D("0.4")
    run.forced = [RiskAction.PAUSE]  # a daily-loss pause at the next quote, before any fill
    report = run.step(frame(at(1, 10, 2), ask="100", ask_size="2"))
    assert bought(report) == [] and sold(report) == [D("0.4")]
    assert (position.phase, report["uptrend_exit"], report["uptrend_ended"]) == (
        "exiting",
        "risk",
        True,
    )
    assert run.account.uptrend is None


def test_stop_on_the_same_quote_as_a_pre_fill_drain_keeps_its_pause():
    run = Run()
    points = days((100, 2))
    position = entered(run, points=points)
    # At 94 the bid reaches the stop, and the loss (3.7%) trips the daily-loss pause too.
    report = run.step(frame(at(1, 10, 2), bid="94", points=points))
    assert "daily loss limit reached" in report["reason"] and run.account.risk_recovery
    assert (report["uptrend_exit"], position.exit_reason) == ("stop", "stop")
    assert run.account.uptrend_stopped_ms == at(1, 10, 2)
    assert report["exit_reason"] == "uptrend_stop"


def test_stop_reason_survives_a_post_fill_drain():
    run = Run()
    position = entered(run)
    run.forced = [None, RiskAction.PAUSE]  # the stop's sale trips the post-fill check
    report = run.step(frame(at(1, 12), bid="96.99", bid_size="2"))
    assert run.account.draining and position.phase == "exiting"
    assert (report["uptrend_exit"], position.exit_reason) == ("stop", "stop")
    report = run.step(frame(at(1, 12, 1), bid="96.99", bid_size="2"))
    assert report["exit_reason"] == "uptrend_stop"


def test_entry_waits_for_recovery_after_a_drain_and_after_a_restart():
    # After a drain: a daily-loss pause on a flat account at 09:58.
    run = Run()
    run.forced = [RiskAction.PAUSE]
    run.step(frame(at(1, 9, 58)))
    assert run.account.risk_recovery
    # The first ALLOW frame is a decision for Uptrend, and starts nothing; V0 is ineligible.
    report = run.step(frame(at(1, 10), ask="100", signals=UNDIRECTED))
    assert (report["mode_decision"], bought(report)) == ("uptrend", [])
    assert run.account.pause and run.account.risk_recovery  # V0's own pause holds
    run.step(frame(at(1, 10, 1), ask="100", signals=UNDIRECTED))  # the second: recovered
    assert not run.account.risk_recovery
    report = run.step(frame(at(1, 11), ask="100", signals=UNDIRECTED))
    assert report["mode_decision"] == "uptrend" and len(bought(report)) == 1
    # A frame gap between the two ALLOW frames restarts the count.
    run = Run()
    run.forced = [RiskAction.PAUSE]
    run.step(frame(at(1, 9, 58)))
    run.step(frame(at(1, 10)))
    run.step(frame(at(1, 10, 5)))  # 5 minutes on, past the 180-second gap
    assert run.account.risk_recovery and run.account.risk_recovery_count == 1
    run.step(frame(at(1, 10, 6)))
    assert not run.account.risk_recovery
    # After a hard-stop restart.
    run = Run()
    points = days((100, 1), (100, 1))
    run.account.risk_high = D("120")  # an earlier high: 100 is a 16.7% drawdown
    run.step(frame(at(1, 9), points=points))
    assert run.account.halt_category == "drawdown"
    report = run.step(frame(at(2, 9), points=points))  # 24 hours on: the restart
    assert "restart" in report and run.account.risk_recovery
    report = run.step(frame(at(2, 10), ask="100", points=points))
    assert (report["mode_decision"], bought(report)) == ("uptrend", [])
    run.step(frame(at(2, 10, 1), ask="100", points=points))
    assert not run.account.risk_recovery
    report = run.step(frame(at(2, 11), ask="100", points=points))
    assert len(bought(report)) == 1


def test_eligibility_and_transient_pauses_do_not_sell_the_uptrend_position():
    run = Run()
    position = entered(run)
    for minute in range(2, 6):  # V0 ineligible: its pause drains, and leaves the position
        report = run.step(frame(at(1, 10, minute), bid="100", signals=UNDIRECTED))
        assert sold(report) == [] and run.account.pause and run.account.draining
    report = run.step(frame(at(1, 10, 6), bid="100", late=31))  # a stale quote: transient
    assert report["decision"] == "pause" and "regime" not in report
    for minute in range(7, 10):
        assert sold(run.step(frame(at(1, 10, minute), bid="100"))) == []
    assert (run.account.inventory, position.phase) == (D("0.599"), "holding")


def test_drain_and_range_exit_leave_the_uptrend_position_alone():
    run = Run()
    position = entered(run)
    account = run.account
    # A grid's leftover, 0.1 with no sell, beside the position: V0's eligibility drain sells
    # the leftover only.
    account.cash -= D("10")
    account.inventory += D("0.1")
    report = run.step(frame(at(1, 10, 2), bid="100", signals=UNDIRECTED))
    assert (sold(report), report["exit_reason"]) == ([D("0.1")], "drain")
    assert account.inventory == D("0.599")
    # A range exit sells the leftover only, never the position.
    account.cash -= D("10")
    account.inventory += D("0.1")
    account.range_exit, account.range_exit_since = True, iso(at(1, 10, 3))
    account.grid_lower, account.grid_upper = D("90"), D("95")
    report = run.step(frame(at(1, 10, 3), bid="100"))
    assert (sold(report), report["exit_reason"]) == ([D("0.1")], "range_exit")
    assert (account.inventory, position.quantity, position.phase) == (
        D("0.599"),
        D("0.599"),
        "holding",
    )
    # No settlement either: the harvest waits for the position.
    assert all(r["allocation"] is None for r in run.reports) and account.settlement_count == 0


def test_dust_sized_held_position_blocks_the_harvest():
    def held(run: Run) -> None:
        # 0.04 bought at 125 (5 USDT) now marks at 4 USDT, below the minimum notional; the
        # account also holds 20 USDT of a past grid's profit, not yet settled.
        account = run.account
        account.cash = D("100") - D("5") - D("0.0045") + D("20")
        account.inventory = D("0.04")
        account.mode = "uptrend"
        account.decision_hour_ms = at(1, 10)
        account.uptrend = UptrendPosition(
            cash_cap=D(60),
            risk_allowance=D(4),
            spent=D("5.0045"),
            risk_used=D("0.04") * 28,
            quantity=D("0.04"),
            stop=D(97),
            highest_close=D(100),
            stop_day_ms=DAY0,
            entered_at=iso(at(1, 10)),
            phase="holding",
        )

    run = Run()
    held(run)
    with patch.object(run.sim, "_harvest", wraps=run.sim._harvest) as harvest:
        report = run.step(frame(at(1, 10, 30), bid="100"))
    assert harvest.call_count == 0 and report["allocation"] is None
    assert (run.account.settlement_count, run.account.pending) == (0, 0)
    # The same account once the position has gone: the harvest settles the profit.
    run = Run()
    held(run)
    run.account.uptrend = None
    report = run.step(frame(at(1, 10, 30), bid="100"))
    assert report["allocation"] is not None and run.account.settlement_count == 1


def test_hard_stop_clears_uptrend_and_restart_redecides():
    run = Run()
    points = days((100, 1), (100, 1))
    run.step(frame(at(1, 10), ask="100", ask_size="2", points=points))  # 0.2 bought
    position = run.account.uptrend
    assert position is not None and position.phase == "entering"
    run.account.risk_high = D("120")  # a hard stop at the next quote, mid-entry
    report = run.step(frame(at(1, 10, 1), ask="100", bid_size="1", points=points))
    assert (run.account.mode, run.account.halt_category) == ("cash", "drawdown")
    assert (position.phase, position.exit_reason, report["uptrend_exit"]) == (
        "exiting",
        "risk",
        "risk",
    )
    # The liquidation sells 0.1 a quote; the position ends only once it has sold it all.
    assert (bought(report), sold(report), report["exit_reason"]) == (
        [],
        [D("0.1")],
        "uptrend_risk",
    )
    assert run.account.uptrend is position and "uptrend_ended" not in report
    report = run.step(frame(at(1, 10, 2), ask="100", bid_size="1", points=points))
    assert sold(report) == [D("0.1")] and report["uptrend_ended"]
    assert run.account.uptrend is None
    # 24 hours on, the restart; the first decision after it is made afresh, and no buy
    # resumes from the old budget.
    report = run.step(frame(at(2, 10, 3), ask="100", points=points))
    assert "restart" in report and bought(report) == []
    report = run.step(frame(at(2, 10, 4), ask="100", points=points))
    assert (report["mode_decision"], run.account.range_decisions, bought(report)) == (
        "uptrend",
        1,
        [],
    )
    run.step(frame(at(2, 10, 5), ask="100", points=points))
    active = run.account.cash - run.account.pending
    report = run.step(frame(at(2, 11), ask="100", points=points))
    fresh = run.account.uptrend
    assert len(bought(report)) == 1 and fresh is not None and fresh is not position
    # New limits from today's active capital, which the round trip's fees have lowered.
    assert fresh.cash_cap == D("0.60") * active < position.cash_cap
    assert fresh.spent == report["fills"][0]["price"] * fresh.quantity + report["fills"][0]["fee"]


def test_halt_before_any_fill_abandons_the_entry():
    run = Run()
    run.step(frame(at(1, 10), ask="100", ask_size="0.4"))
    assert run.account.uptrend is not None and run.account.uptrend.quantity == 0
    run.account.risk_high = D("120")
    report = run.step(frame(at(1, 10, 1), ask="100"))
    assert (report["decision"], run.account.mode) == ("halt", "cash")
    assert (report["uptrend_exit"], report.get("uptrend_abandoned")) == ("risk", True)
    assert "uptrend_ended" not in report and run.account.uptrend is None


def test_same_frame_mode_changes_both_count():
    run = Run()
    run.forced = [None, RiskAction.EXIT]  # the post-fill check, after the first buy
    report = run.step(frame(at(1, 10), ask="100"))
    assert (report["mode_decision"], bought(report)) == ("uptrend", [D("0.599")])
    assert (report["decision"], run.account.mode, run.account.mode_switches) == ("halt", "cash", 2)


def test_post_fill_halt_on_the_last_quote_owes_the_exit():
    run = Run()
    run.forced = [None, RiskAction.EXIT]
    report = run.step(frame(at(1, 10), ask="100"))  # the run's final quote
    position = run.account.uptrend
    assert run.account.mode == "cash" and position is not None
    assert (position.phase, position.exit_reason, report["uptrend_exit"]) == (
        "exiting",
        "risk",
        "risk",
    )
    held = run.sim.held_fragments(run.account) + run.sim.uptrend_held(run.account)
    quote = frame(at(1, 10)).quote
    assert exit_state(run.account, quote, RULES, held)[0] == "incomplete"


# --- Decisions, the RANGE count and the wind-down -----------------------------------------------


def test_transient_first_frame_defers_the_decision():
    run = Run()
    run.step(frame(at(1, 9), h4=DOWN))  # a RANGE decision for Cash
    assert (run.account.decision_hour_ms, run.account.range_decisions) == (at(1, 9), 1)
    report = run.step(frame(at(1, 10), h4=DOWN, late=31))  # stale: transient
    assert "mode_decision" not in report
    assert (run.account.decision_hour_ms, run.account.range_decisions) == (at(1, 9), 1)
    report = run.step(frame(at(1, 10, 0, 30), h4=DOWN))
    assert report["mode_decision"] == "cash"
    assert (run.account.decision_hour_ms, run.account.range_decisions) == (at(1, 10), 2)


def test_range_decisions_reset_after_a_missing_hour():
    run = Run()
    modes = {}
    for hour in (9, 10, 11, 13, 14, 15, 16):  # no frame in hour 12
        report = run.step(frame(at(1, hour), h4=RANGE))
        modes[hour] = (report["mode_decision"], run.account.range_decisions)
    assert modes == {
        9: ("cash", 1),
        10: ("cash", 2),
        11: ("cash", 3),
        13: ("cash", 1),
        14: ("cash", 2),
        15: ("cash", 3),
        16: ("grid", 4),
    }


def test_no_range_decisions_while_holding():
    run = Run()
    entered(run)
    for hour in range(11, 17):  # six RANGE-classified hours while holding
        report = run.step(frame(at(1, hour), bid="100", h4=RANGE))
        assert "mode_decision" not in report and run.account.range_decisions == 0
    assert run.step(frame(at(1, 16, 30), bid="96.99", h4=RANGE))["uptrend_ended"]
    modes = [run.step(frame(at(1, hour), h4=RANGE))["mode_decision"] for hour in range(17, 21)]
    assert modes == ["cash", "cash", "cash", "grid"]


def test_grid_to_uptrend_winds_down_without_reentry_and_waits_until_flat():
    run = Run()
    grid(run)
    report = run.step(frame(at(1, 10), bid="100"))
    assert (report["mode_decision"], run.account.winding_down) == ("uptrend", True)
    assert report["cancelled"] == ["g/0"]  # the resting buy goes, the sells stay
    assert set(run.account.orders) == {"g/1/sell", "g/2/sell"}
    report = run.step(frame(at(1, 10, 10), bid="100.60"))  # a sell fills: no re-entry buy
    assert [f["order_id"] for f in report["fills"]] == ["g/1/sell"]
    assert set(run.account.orders) == {"g/2/sell"} and bought(report) == []
    run.step(frame(at(1, 10, 20), bid="101.60"))  # the last sell: the grid has ended
    assert (run.account.orders, run.account.winding_down) == ({}, False)
    assert bought(run.step(frame(at(1, 10, 21), bid="101.60"))) == []
    report = run.step(frame(at(1, 11), bid="101.60"))  # the next decision, flat: it enters
    assert report["mode_decision"] == "uptrend" and len(bought(report)) == 1


def test_grid_to_cash_winds_down_without_reentry():
    run = Run()
    grid(run)
    report = run.step(frame(at(1, 10), bid="100", h4=DOWN))
    assert (report["mode_decision"], run.account.winding_down) == ("cash", True)
    assert report["cancelled"] == ["g/0"]
    report = run.step(frame(at(1, 10, 10), bid="100.60", h4=DOWN))
    assert [f["order_id"] for f in report["fills"]] == ["g/1/sell"]
    assert set(run.account.orders) == {"g/2/sell"}  # no re-entry buy


def test_return_to_grid_lifts_the_wind_down():
    run = Run()
    grid(run)
    run.account.range_decisions, run.account.decision_hour_ms = 4, at(1, 9)
    report = run.step(frame(at(1, 10), bid="100", h4=DOWN))  # an hour in Cash
    assert (report["mode_decision"], run.account.winding_down) == ("cash", True)
    report = run.step(frame(at(1, 11), bid="100", h4=RANGE))  # back to Grid
    assert (report["mode_decision"], run.account.winding_down) == ("grid", False)
    report = run.step(frame(at(1, 11, 10), bid="100.60", h4=RANGE))
    reentries = [key for key in run.account.orders if "/reentry/" in key]
    assert len(reentries) == 1 and run.account.orders[reentries[0]].price == D("99.50")
    assert "g/0" not in run.account.orders  # the cancelled buy is not restored


def test_no_new_grid_unless_mode_is_grid():
    run = Run()
    opened = {}
    # Cash; then Uptrend with a start refused (an ask at the stop); then RANGE hours to Grid.
    for hour, kwargs in (
        (9, {"h4": DOWN}),
        (10, {"ask": "97"}),
        (11, {"h4": RANGE}),
        (12, {"h4": RANGE}),
    ):
        report = run.step(frame(at(1, hour), **kwargs))
        later = run.step(frame(at(1, hour, 1), **kwargs))  # V0's recovery has nothing to wait on
        opened[hour] = (report["mode_decision"], bool(report["opened"] or later["opened"]))
    assert opened == {
        9: ("cash", False),
        10: ("uptrend", False),
        11: ("cash", False),
        12: ("grid", True),
    }


def test_halt_in_grid_mode_sets_cash_and_no_grid_opens_before_a_decision():
    run = Run()
    points = days((100, 1), (100, 1))
    grid(run)
    run.account.decision_hour_ms = at(1, 9)
    run.account.risk_high = D("120")  # an earlier high: a hard stop at the next quote
    report = run.step(frame(at(1, 9, 30), bid="100", h4=RANGE, points=points))
    assert (report["decision"], run.account.mode, run.account.mode_switches) == ("halt", "cash", 1)
    assert (run.account.winding_down, run.account.orders) == (False, {})
    assert run.account.inventory == 0  # the same frame's liquidation sold the grid's 0.2
    report = run.step(frame(at(2, 9, 32), bid="100", h4=RANGE, points=points))  # the restart
    assert "restart" in report and not run.account.halt and not report["opened"]
    opened = []
    for hour in (9, 10, 11, 12):
        for minute in (40, 41) if hour == 9 else (0, 1):
            report = run.step(frame(at(2, hour, minute), bid="100", h4=RANGE, points=points))
            opened.append((hour, minute, run.account.mode, bool(report["opened"])))
    # The halt broke the RANGE count: Grid needs four fresh decisions, from 09:40, though V0's
    # own recovery has allowed a grid since 09:41.
    assert [entry for entry in opened if entry[3]] == [(12, 0, "grid", True)]
    assert all(mode == "cash" for hour, _, mode, _ in opened if hour < 12)


def test_a_restart_mid_hour_decides_at_the_next_valid_frame():
    """Owner ruling 2026-10-07, "Restart: decide at once": when a halt clears mid-hour, the
    first valid frame after it decides, in that same hour; the mode switcher does not wait for
    the next hour boundary. The frame that restarts was halted, and decides nothing itself."""
    run = Run()
    points = days((100, 1), (100, 1))
    run.step(frame(at(1, 9), bid="100", h4=RANGE, points=points))  # 09:00 decided
    run.account.risk_high = D("120")  # an earlier high: a hard stop at the next quote
    run.step(frame(at(1, 9, 30), bid="100", h4=RANGE, points=points))
    assert run.account.halt_category == "drawdown"
    report = run.step(frame(at(2, 9, 32), bid="100", h4=RANGE, points=points))
    assert "restart" in report and not run.account.halt and "mode_decision" not in report
    assert run.account.decision_hour_ms == at(1, 9)
    report = run.step(frame(at(2, 9, 33), ask="100", points=points))  # 27 minutes before 10:00
    assert report["mode_decision"] == "uptrend" and report["mode_reasons"]["outcome"] == "made"
    assert run.account.decision_hour_ms == at(2, 9)


# --- Review fix round 1 ---------------------------------------------------------------------


def invalid(item: Frame) -> Frame:
    """The same frame with another market's candidate: an integrity halt."""
    return replace(item, candidate=replace(CANDIDATE, symbol="ETHUSDT"))


def test_variant_policy_builds_the_one_mode_switch_policy():
    # "MS" is a backtest job (Task 6): its policy is F's block and nothing else, and its rows
    # name it. With V2's structure features it is no declared policy, so it is refused.
    assert variant_policy("MS") == MS
    assert variant_name(MS) == "MS"
    with pytest.raises(ValueError, match="F's block and nothing else"):
        variant_policy("MS", structure=True)


def test_resume_refuses_mode_switch(tmp_path):
    simulator = PaperSimulator(tmp_path / "paper.db", CONFIG, RULES, D(100), MS)
    try:
        with pytest.raises(ValueError, match="mode switcher runs in historical replay only"):
            simulator.resume(frame(at(1, 10)), event_id="r1", reason="operator")
    finally:
        simulator.close()


def test_an_entering_position_without_allow_breaks_an_invariant():
    # A refusing action, or a recovery, always ends an entry earlier (a drain begins exit 3,
    # EXIT halts, and no position survives a restart); meeting one here is a defect.
    run = Run()
    account = run.account
    account.mode, account.decision_hour_ms = "uptrend", at(1, 10)
    account.uptrend = UptrendPosition(
        cash_cap=D(60),
        risk_allowance=D(4),
        stop=D(97),
        highest_close=D(100),
        stop_day_ms=DAY0,
        entered_at=iso(at(1, 10)),
    )
    account.risk_recovery = True
    with pytest.raises(RuntimeError, match="entering uptrend position"):
        run.step(frame(at(1, 10, 30), ask="100"))


def test_entry_reads_the_decision_not_the_report():
    # The report's "mode_decision" is output only: the decision reaches the entry as an
    # argument.
    run = Run()
    item = frame(at(1, 10), ask="100")
    report: dict[str, Any] = {"fills": [], "mode_decision": "uptrend"}
    run.sim._uptrend_step(run.account, item, RiskAction.ALLOW, report, decided=None)
    assert run.account.uptrend is None and report["fills"] == []
    report = {"fills": []}
    run.sim._uptrend_step(run.account, item, RiskAction.ALLOW, report, decided=Mode.UPTREND)
    assert run.account.uptrend is not None and bought(report) == [D("0.599")]


def test_range_exit_drops_sold_fragments_and_labels_the_last_chunk_as_the_uptrend_exit():
    run = Run()
    account = run.account
    # F's two held fragments (0.06, sellable together) leave the pair flat but keep an old
    # grid's band, which the price has left.
    account.cash -= D("6")
    account.inventory = D("0.06")
    account.flow_fragments = {D("101"): D("0.03"), D("102"): D("0.03")}
    account.grid_lower, account.grid_upper = D("90"), D("95")
    report = run.step(frame(at(1, 10), ask="100", share=None))
    assert bought(report) == [D("0.563")]  # 0.60 x 94 = 56.4 of cash cap
    run.step(frame(at(1, 10, 1), ask="100", share=None))
    position = account.uptrend
    assert position is not None and position.phase == "holding"
    # The band times out while the position is held: the range exit sells the fragments only.
    account.range_exit, account.range_exit_since = True, iso(at(1, 10, 2))
    account.pause, account.draining = "outside-range timeout: exit to cash", True
    report = run.step(frame(at(1, 10, 2), bid="100", share=None))
    assert (sold(report), report["exit_reason"]) == ([D("0.06")], "range_exit")
    assert account.flow_fragments == {}  # sold, so no longer booked as held
    # The stop then fires, and the pending range exit's liquidation sells the position in
    # three chunks, every one of them the uptrend exit's, the last included.
    labels = []
    for minute in (3, 4, 5):
        report = run.step(frame(at(1, 10, minute), bid="96.99", bid_size="2", share=None))
        labels.append((report["exit_reason"], sold(report), "uptrend_ended" in report))
    assert labels == [
        ("uptrend_stop", [D("0.2")], False),
        ("uptrend_stop", [D("0.2")], False),
        ("uptrend_stop", [D("0.163")], True),
    ]
    assert (account.uptrend, account.inventory) == (None, 0)


def test_range_exit_sells_an_exiting_position_under_its_uptrend_label():
    run = Run()
    position = entered(run)
    account = run.account
    account.range_exit, account.range_exit_since = True, iso(at(1, 10, 2))
    account.grid_lower, account.grid_upper = D("90"), D("95")
    report = run.step(frame(at(1, 10, 2), bid="96.99"))  # the stop: exit 1
    assert (report["uptrend_exit"], position.phase) == ("stop", "exiting")
    assert (sold(report), report["exit_reason"]) == ([D("0.599")], "uptrend_stop")
    assert report["uptrend_ended"] and account.uptrend is None


def test_invalid_frame_halt_ends_an_empty_entry_at_once():
    run = Run()
    run.step(frame(at(1, 10), ask="100", ask_size="0.4"))  # too thin to buy
    assert run.account.uptrend is not None and run.account.uptrend.quantity == 0
    report = run.step(invalid(frame(at(1, 10, 1), ask="100")))
    assert (report["decision"], run.account.halt_category, run.account.mode) == (
        "halt",
        "integrity",
        "cash",
    )
    assert (report["uptrend_exit"], report.get("uptrend_abandoned")) == ("risk", True)
    assert run.account.uptrend is None


def test_invalid_frame_halt_of_a_held_position_sells_it_next():
    run = Run()
    position = entered(run)
    report = run.step(invalid(frame(at(1, 10, 2), bid="100")))
    assert (report["decision"], report["uptrend_exit"], run.account.mode) == (
        "halt",
        "risk",
        "cash",
    )
    # The invalid frame's quote prices nothing: the position waits, exiting, for a valid one.
    assert run.account.uptrend is position and position.phase == "exiting"
    assert run.account.liquidating and sold(report) == []
    report = run.step(frame(at(1, 10, 3), bid="100"))
    assert (sold(report), report["exit_reason"], report["uptrend_ended"]) == (
        [D("0.599")],
        "uptrend_risk",
        True,
    )
    assert run.account.uptrend is None


def test_lookahead_daily_perception_fails_closed():
    points = days((100, 1), (100, 1))
    sound = snapshot(at(1, 10), points)
    assert (sound.d1_index, sound.d1_open_ms) == (0, DAY0)
    for bad in (
        replace(sound, d1_index=1, d1_open_ms=DAY0 + DAY),  # day 1 closes at day 2's midnight
        replace(sound, d1_open_ms=DAY0 + DAY),  # disagrees with the point it names
        replace(sound, d1_index=None),  # likewise
        replace(sound, d1_index=2, d1_open_ms=DAY0 + 2 * DAY),  # no such point
    ):
        run = Run()
        report = run.step(replace(frame(at(1, 10), ask="100", points=points), perception=bad))
        assert (report["decision"], run.account.halt_category) == ("halt", "integrity")
        assert "daily" in report["reason"] and bought(report) == []
    run = Run()
    report = run.step(frame(at(1, 10), ask="100", points=points))
    assert report["decision"] != "halt" and len(bought(report)) == 1


# --- Why each decision went as it did (reporting only) ------------------------------------------


def test_each_decision_reports_its_reasons():
    run = Run()
    # V0's classifier reads the quiet market as RANGE: the first RANGE hour, and the 4h state Up.
    report = run.step(frame(at(1, 10), ask="100"))
    assert report["mode_reasons"] == {
        "hour_ms": at(1, 10),
        "outcome": "made",
        "mode": "uptrend",
        "uptrend_failures": [],
        "grid_failures": ["range_decisions_below_4", "h4_not_range_or_unclear"],
    }
    assert "mode_reasons" not in run.step(frame(at(1, 10, 1), ask="100"))  # the hour is decided
    run = Run()
    report = run.step(frame(at(1, 9), h4=DOWN))
    assert report["mode_reasons"] == {
        "hour_ms": at(1, 9),
        "outcome": "made",
        "mode": "cash",
        "uptrend_failures": ["h4_not_up"],
        "grid_failures": ["range_decisions_below_4", "h4_not_range_or_unclear"],
    }


def test_a_decision_skipped_while_holding_is_its_own_outcome():
    run = Run()
    entered(run)
    report = run.step(frame(at(1, 11), bid="100", h4=RANGE))
    assert report["mode_reasons"] == {"hour_ms": at(1, 11), "outcome": "skipped_holding"}
    assert "mode_reasons" not in run.step(frame(at(1, 11, 1), bid="100", h4=RANGE))


def halted_hours(policy: SimulationPolicy) -> list[dict[str, Any]]:
    """A RANGE decision at 09:00, a hard stop at 09:30, an invalid frame at 11:00, and the
    restart 24 hours on, at 09:32 the next day, then a frame in that same hour."""
    run = Run(policy)
    points = days((100, 1), (100, 1))
    run.step(frame(at(1, 9), bid="100", h4=RANGE, points=points))
    run.account.risk_high = D("120")  # an earlier high: a hard stop at the next quote
    run.step(frame(at(1, 9, 30), bid="100", h4=RANGE, points=points))
    assert run.account.halt_category == "drawdown"
    run.step(frame(at(1, 10), bid="100", h4=RANGE, points=points))
    run.step(frame(at(1, 10, 1), bid="100", h4=RANGE, points=points))
    run.step(invalid(frame(at(1, 11), bid="100", h4=RANGE, points=points)))
    assert "restart" in run.step(frame(at(2, 9, 32), bid="100", h4=RANGE, points=points))
    run.step(frame(at(2, 9, 40), bid="100", h4=RANGE, points=points))
    return run.reports


def test_hours_held_back_by_a_halt_are_their_own_outcome():
    decided, stopped, *halted, invalid_frame, restart, after = [
        report.get("mode_reasons") for report in halted_hours(MS)
    ]
    assert decided is not None and decided["outcome"] == "made"
    assert stopped is None  # 09:00 was decided before the halt
    # Each valid frame of a halted account in an hour not yet decided carries it: replay counts
    # the hour once. An invalid frame decides nothing and carries nothing.
    assert halted == [{"hour_ms": at(1, 10), "outcome": "halted"}] * 2
    assert invalid_frame is None
    # The restart's frame was halted; the next frame decides the same hour after all.
    assert restart == {"hour_ms": at(2, 9), "outcome": "halted"}
    assert after is not None and (after["hour_ms"], after["outcome"]) == (at(2, 9), "made")
    # v1's runs never carry it.
    v1 = halted_hours(SimulationPolicy(flow_block_entry=True))
    assert not any("mode_reasons" in report for report in v1)
