"""A marketable exit that cannot meet the minimum notional must say so, not stall silently.

Prices and depths are constructed fixtures, never backtest evidence. Two distinct
refusals are pinned here:

* ``depth`` - the per-frame participation chunk is worth less than the minimum
  notional although the position is not. A real exchange rejects the order, so the
  engine must keep waiting, but the wait has to be visible.
* ``dust`` - the whole unreserved position is worth less than the minimum notional at
  the current bid. No later frame and no extra depth can clear it: it is terminal
  until price rises, and it must not silently retire the account's lifecycle.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from crypto_grid_bot.backtest.__main__ import result_failures
from crypto_grid_bot.backtest.replay import Metrics, record_exit_block, summarise
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import (
    exit_state,
    liquidate,
    place,
    reduce_unreserved,
)
from crypto_grid_bot.simulation.models import Account, D, LimitOrder, MarketRules, Quote
from crypto_grid_bot.simulation.runner import PaperSimulator

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=UTC)
# Defaults: participation 10%, minimum notional 5, slippage 0.05%, step 1, tick 0.00001.
RULES = MarketRules()


def quote(index=0, bid="0.02300", size="2000"):
    when = (START + timedelta(seconds=index)).isoformat()
    return Quote(
        f"q/{index}", RULES.symbol, when, when, D(bid), D(bid) + D("0.00001"), D(size), D(size)
    )


def holding(inventory, cash="10"):
    """An account holding ``inventory`` with its risk baselines already at ``cash``, so
    the drawdown breakers are quiet and only the exit path is under test."""
    account = Account.start(D("100"))
    account.cash, account.inventory = D(cash), D(inventory)
    account.reserve_high = account.risk_high = account.day_start = D(cash)
    account.last_equity = D(cash)
    return account


class RefusalReasonTests(TestCase):
    def test_thin_book_refuses_and_names_the_depth_shortfall(self):
        account = holding("5000")
        result = reduce_unreserved(account, quote(), RULES)
        # 2000 * 0.10 * 0.02298 = 4.596 < 5: no order an exchange would accept.
        self.assertEqual([], result.fills)
        self.assertEqual("depth", result.blocked)
        self.assertEqual(D("200"), result.quantity)
        self.assertEqual(D("4.596"), result.notional)
        self.assertEqual(D("5000"), result.unreserved)
        self.assertEqual(D("114.90"), result.unreserved_notional)
        self.assertEqual(D("5000"), account.inventory)

    def test_thin_book_never_progresses_and_never_raises(self):
        account = holding("5000")
        blocked = [reduce_unreserved(account, quote(i), RULES).blocked for i in range(50)]
        self.assertEqual({"depth"}, set(blocked))
        self.assertEqual(D("5000"), account.inventory)

    def test_position_below_the_minimum_is_named_dust_however_deep_the_book(self):
        account = holding("200")
        result = reduce_unreserved(account, quote(size="10000000"), RULES)
        self.assertEqual([], result.fills)
        self.assertEqual("dust", result.blocked)
        self.assertEqual(D("4.596"), result.unreserved_notional)

    def test_a_liquidation_that_can_trade_reports_no_block(self):
        account = holding("5000")
        result = liquidate(account, quote(size="100000"), RULES)
        self.assertEqual("", result.blocked)
        self.assertEqual(D("5000"), result.fills[0].quantity)

    def test_inventory_reserved_by_a_resting_sell_is_not_a_minimum_notional_block(self):
        account = holding("500", cash="100")
        place(account, LimitOrder("s", "sell", D("0.02400"), D("500"), D("500")), RULES)
        result = reduce_unreserved(account, quote(size="10000000"), RULES)
        self.assertEqual(("reserved", []), (result.blocked, result.fills))
        self.assertEqual(D("0"), result.unreserved)

    def test_a_full_liquidation_leaves_dust_and_says_so(self):
        account = holding("5000")
        # 300 units per frame: 5000 -> 200 left, worth 4.596 < 5 and unsellable forever.
        results = [liquidate(account, quote(i, size="3000"), RULES) for i in range(40)]
        self.assertEqual(D("200"), account.inventory)
        self.assertEqual("dust", results[-1].blocked)


class StepReportTests(TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.sim = PaperSimulator(Path(":memory:"), self.config, RULES, D("100"))
        self.sim.close()  # step() below uses no store

    def frame(self, index, size="2000", bid="0.02300"):
        template = demo_frames(1)[0]
        when = START + timedelta(seconds=index)
        return replace(
            template,
            quote=replace(
                template.quote,
                event_id=f"thin/{index}",
                observed_at=when.isoformat(),
                received_at=when.isoformat(),
                bid=D(bid),
                ask=D(bid) + D("0.00001"),
                bid_size=D(size),
                ask_size=D(size),
            ),
            signals=replace(template.signals, observed_at=when),
            allow_new_grid=False,
        )

    def halted(self, inventory="5000"):
        account = holding(inventory)
        account.halt = "hard drawdown breach"
        account.liquidating = True
        return account

    def test_a_stalled_liquidation_is_reported_on_every_frame(self):
        account = self.halted()
        reports = [self.sim.step(account, self.frame(i)) for i in range(5)]
        for report in reports:
            self.assertEqual([], report["fills"])
            self.assertEqual("depth", report["exit_blocked"])
            self.assertEqual(D("114.90"), report["exit_blocked_notional"])
        self.assertEqual(D("5000"), account.inventory)

    def test_a_progressing_liquidation_reports_no_block(self):
        account = self.halted()
        report = self.sim.step(account, self.frame(0, size="100000"))
        self.assertEqual("", report["exit_blocked"])
        self.assertEqual("liquidation", report["exit_reason"])

    def test_dust_does_not_keep_a_range_exit_open_forever(self):
        account = holding("200")
        account.range_exit, account.range_exit_since = True, START.isoformat()
        account.grid_lower, account.grid_upper = D("0.02000"), D("0.02500")
        account.draining = True
        reports = [self.sim.step(account, self.frame(i, size="10000000")) for i in range(5)]
        self.assertEqual("dust", reports[0]["exit_blocked"])
        self.assertFalse(account.range_exit)
        self.assertEqual("returned inside", reports[0]["range_exit_cleared"])
        # The exit is settled, so the profit vault can harvest again.
        self.assertIsNotNone(reports[0]["allocation"])
        # The dust is still held and still marked; it must not be silently dropped.
        self.assertEqual(D("200"), account.inventory)


class MeasurementTests(TestCase):
    def test_blocked_exits_reach_the_counters(self):
        metrics = Metrics()
        for _ in range(3):
            record_exit_block(metrics, "depth", D("114.90"))
        record_exit_block(metrics, "", D("0"))
        record_exit_block(metrics, "dust", D("4.596"))
        self.assertEqual(4, metrics.exit_blocked_frames)
        self.assertEqual({"depth": 3, "dust": 1}, dict(metrics.exit_blocked_by_kind))
        self.assertEqual(3, metrics.max_exit_blocked_streak)
        self.assertEqual(D("114.90"), metrics.max_exit_blocked_notional)
        # The final state is not the last refusal: it comes from the account at the end.
        self.assertEqual("", metrics.final_exit_blocked)

    def test_a_run_that_ends_with_an_exit_incomplete_fails_acceptance(self):
        result = {
            "symbol": "DEMOUSDT",
            "path_mode": "high_first",
            "strategy": "gated grid (price-only-v1)",
            "accounting_problems": [],
            "transient_pauses": 0,
            "bars": 10,
            "final_exit_blocked": "incomplete",
            "final_unsellable_notional": "91.92",
        }
        (failure,) = result_failures([result])
        self.assertIn("exit still incomplete", failure)
        self.assertIn("91.92", failure)
        # Terminal dust is an exchange fact, reported but not a validity failure.
        dust = dict(result, final_exit_blocked="dust", final_unsellable_notional="4.596")
        self.assertEqual([], result_failures([dust]))

    def test_summary_publishes_the_final_state(self):
        from crypto_grid_bot.backtest.replay import RunConfig

        metrics = Metrics(peak_equity=D("100"), final_equity=D("100"), frames=1, bars=1)
        record_exit_block(metrics, "dust", D("4.596"))
        metrics.final_exit_blocked, metrics.final_blocked_notional = "dust", D("4.596")
        run = RunConfig("DEMOUSDT", "high_first", True, RULES, D("100"), D("0.0005"))
        summary = summarise(run, metrics, holding("200"), [])
        self.assertEqual("dust", summary["final_exit_blocked"])
        self.assertEqual("4.596", summary["final_unsellable_notional"])
        self.assertEqual({"dust": 1}, summary["exit_blocked_frames_by_kind"])


class FinalExitStateTests(TestCase):
    """``exit_state`` judges the end of a run from the account, not the last refusal."""

    def test_a_partial_fill_on_the_last_frame_leaves_the_exit_incomplete(self):
        account = holding("5000")
        account.halt, account.liquidating = "hard drawdown", True
        # 3000 * 0.10 = 300 units, 6.894 quote: one legal chunk sells, 4700 remain.
        result = liquidate(account, quote(size="3000"), RULES)
        self.assertEqual(("", D("300")), (result.blocked, result.fills[0].quantity))
        state, value = exit_state(account, quote(size="3000"), RULES)
        self.assertEqual("incomplete", state)
        self.assertEqual(D("4700") * D("0.02298"), value)

    def test_a_stalled_range_exit_is_incomplete(self):
        account = holding("5000")
        account.range_exit = True
        self.assertEqual("incomplete", exit_state(account, quote(), RULES)[0])

    def test_dust_stays_reported_while_a_new_grid_rests(self):
        account = holding("200")
        place(account, LimitOrder("grid/1", "buy", D("0.02200"), D("300"), D("300")), RULES)
        # An idle grid frame attempts no exit; the remainder is still held and reported.
        self.assertEqual(("dust", D("200") * D("0.02298")), exit_state(account, quote(), RULES))

    def test_the_filled_part_of_a_resting_buy_is_not_an_unfinished_exit(self):
        account = holding("0", cash="100")
        order = LimitOrder("grid/1", "buy", D("0.02300"), D("400"), D("100"))
        account.orders[order.order_id] = order
        account.inventory = D("300")  # filled so far; its own sell is placed when it completes
        self.assertEqual(("", D("0")), exit_state(account, quote(), RULES))

    def test_a_flat_account_owes_nothing(self):
        self.assertEqual(("", D("0")), exit_state(holding("0"), quote(), RULES))
