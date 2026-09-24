"""Regressions from Claude's review; prices are constructed, not backtest evidence."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.control import decode_frame, resume_paper
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import match, place, reduce_unreserved
from crypto_grid_bot.simulation.models import Account, D, LimitOrder, MarketRules, Quote
from crypto_grid_bot.simulation.runner import PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.store import encode

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=UTC)


def frame(index, bid="0.02300", *, ask=None, size="100000", eligible=True):
    template = demo_frames(1)[0]
    when = START + timedelta(seconds=index)
    return replace(
        template,
        quote=replace(
            template.quote,
            event_id=f"recovery/{index}",
            observed_at=when.isoformat(),
            received_at=when.isoformat(),
            bid=D(bid),
            ask=D(ask) if ask else D(bid) + D("0.00001"),
            bid_size=D(size),
            ask_size=D(size),
        ),
        signals=replace(template.signals, observed_at=when),
        candidate=replace(template.candidate, news_risk=0 if eligible else 0.9),
        allow_new_grid=True,
    )


class StrategyRecoveryTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "paper.db"
        self.config = replace(load_config(ROOT / "config/default.toml"), minimum_transfer_quote=0.1)
        self.policy = SimulationPolicy(outside_range_seconds=3)
        self.sim = self.open()
        self.addCleanup(lambda: self.sim.close())

    def open(self):
        return PaperSimulator(self.path, self.config, MarketRules(), policy=self.policy)

    def restart(self):
        self.sim.close()
        self.sim = self.open()

    def test_fifty_shallow_oscillations_keep_trading_and_harvesting(self):
        self.sim.process(frame(0))
        initial_lowest = min(o.price for o in self.sim.store.read().orders.values())
        self.assertLess(initial_lowest, D("0.02270"))
        for cycle in range(50):
            self.sim.process(frame(2 * cycle + 1, "0.02270"))
            report = self.sim.process(frame(2 * cycle + 2, "0.02330"))
            state = self.sim.store.read()
            self.assertEqual(0, state.inventory)
            self.assertGreaterEqual(state.available_quote(self.sim.rules), 0)
            self.assertTrue(report["allocation"])
            if cycle in (2, 20):
                self.restart()
        state = self.sim.store.read()
        self.assertGreaterEqual(state.fill_count, 100)
        self.assertGreater(state.secured, 0)
        self.assertEqual(sum(state.confirmed_transfers.values()), state.secured)
        self.assertEqual(
            state.cash - state.pending - state.initial_cash, state.pending + state.secured
        )
        self.assertGreater(len(state.confirmed_transfers), 1)
        self.assertEqual(len(state.confirmed_transfers), len(set(state.confirmed_transfers)))

    def test_stale_frame_cannot_fill_existing_sells_or_clear_pause(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        before = self.sim.store.read()
        self.assertGreater(before.inventory, 0)
        stale = frame(2, "0.02330")
        stale = replace(
            stale,
            quote=replace(stale.quote, received_at=(START + timedelta(seconds=100)).isoformat()),
        )
        report = self.sim.process(stale)
        self.assertEqual("pause", report["decision"])
        self.assertFalse(report["fills"])
        self.assertEqual(before.inventory, self.sim.store.read().inventory)
        self.assertTrue(all(o.side == "sell" for o in self.sim.store.read().orders.values()))
        self.restart()
        recovery = frame(3, "0.02330")
        report = self.sim.process(recovery)
        self.assertTrue(report["fills"])  # Fresh reduce-only sells may complete.
        self.assertFalse(report["opened"])
        self.assertEqual(1, self.sim.store.read().recovery_count)
        self.sim.process(recovery)
        self.assertEqual(1, self.sim.store.read().recovery_count)
        self.assertTrue(self.sim.process(frame(4))["opened"])
        self.assertFalse(self.sim.store.read().pause)

    def test_recovery_requires_consecutive_eligible_frames_and_rejects_duplicate_time(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, eligible=False))
        self.assertFalse(self.sim.process(frame(2))["opened"])
        duplicate_time = replace(frame(2), quote=replace(frame(2).quote, event_id="same-time"))
        self.assertEqual("pause", self.sim.process(duplicate_time)["decision"])
        self.assertEqual(0, self.sim.store.read().recovery_count)
        self.sim.process(frame(3))
        self.sim.process(frame(4, eligible=False))
        self.assertEqual(0, self.sim.store.read().recovery_count)
        self.sim.process(frame(5))
        self.sim.process(frame(50))  # A long gap also resets continuity.
        self.assertEqual(1, self.sim.store.read().recovery_count)
        self.assertTrue(self.sim.process(frame(51))["opened"])

    def test_outside_range_exits_to_cash_and_does_not_chase_price(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02500"))
        self.sim.process(frame(2, "0.02500"))
        self.restart()
        report = self.sim.process(frame(4, "0.02500"))
        self.assertEqual("pause", report["decision"])
        self.assertTrue(self.sim.store.read().range_exit)
        self.assertEqual({}, self.sim.store.read().orders)
        self.assertFalse(self.sim.process(frame(5, "0.02500"))["opened"])
        for i in (6, 7):
            self.assertFalse(self.sim.process(frame(i))["opened"])
        self.assertTrue(self.sim.process(frame(8))["opened"])

    def test_outside_range_timeout_liquidates_inventory_with_bounded_fills(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(frame(2, "0.02196"))
        self.assertGreater(self.sim.store.read().inventory, 0)
        report = self.sim.process(frame(4, "0.02196", size="10000"))
        self.assertTrue(self.sim.store.read().range_exit)
        self.assertEqual("pause", report["decision"])
        self.assertEqual(D(1000), D(report["fills"][0]["quantity"]))
        self.assertGreater(self.sim.store.read().inventory, 0)
        self.assertFalse(self.sim.store.read().orders)

    def test_invalid_frame_breaks_outside_range_confirmation(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02500"))
        invalid = replace(
            frame(2, "0.02500"),
            quote=replace(
                frame(2, "0.02500").quote, received_at=(START + timedelta(seconds=99)).isoformat()
            ),
        )
        self.sim.process(invalid)
        self.sim.process(frame(4, "0.02500"))
        self.assertFalse(self.sim.store.read().range_exit)
        self.assertEqual(frame(4).quote.observed_at, self.sim.store.read().outside_since)

    def test_gap_does_not_count_as_sustained_outside_range_time(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02500"))
        self.sim.process(frame(100, "0.02500"))
        self.assertFalse(self.sim.store.read().range_exit)
        self.assertEqual(frame(100).quote.observed_at, self.sim.store.read().outside_since)

    def test_daily_loss_pause_preserves_sell_management_and_blocks_reentry(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        report = self.sim.process(frame(2, "0.02050"))
        state = self.sim.store.read()
        self.assertEqual("pause", report["decision"])
        self.assertIn("daily loss", report["reason"])
        self.assertFalse(state.halt)
        self.assertTrue(all(o.side == "sell" for o in state.orders.values()))
        self.assertFalse(report["opened"])

    def test_hard_drawdown_stays_latched_and_resume_cannot_erase_loss(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        report = self.sim.process(frame(2, "0.01000"))
        self.assertEqual("halt", report["decision"])
        self.assertEqual(0, self.sim.store.read().inventory)
        before = self.sim.store.read()
        self.restart()
        self.assertEqual("halt", self.sim.process(frame(3))["decision"])
        with self.assertRaisesRegex(ValueError, "risk limits"):
            self.sim.resume(frame(4), event_id="loss-reset", reason="try recovery")
        after = self.sim.store.read()
        self.assertEqual(before.risk_high, after.risk_high)
        self.assertEqual(before.reserve_high, after.reserve_high)
        self.assertTrue(after.halt)

    def test_emergency_resume_is_logged_idempotent_and_requires_confirmation(self):
        self.sim.process(frame(0))
        emergency = replace(frame(1), signals=replace(frame(1).signals, emergency=True))
        self.sim.process(emergency)
        self.assertTrue(self.sim.store.read().halt)
        result = self.sim.resume(frame(2), event_id="operator-1", reason="emergency cleared")
        state = encode(self.sim.store.read().to_dict())
        self.assertEqual("resume_pending", result["decision"])
        self.assertEqual(
            result, self.sim.resume(frame(2), event_id="operator-1", reason="emergency cleared")
        )
        self.assertEqual(state, encode(self.sim.store.read().to_dict()))
        self.assertFalse(result["fills"])
        self.assertFalse(self.sim.process(frame(3))["opened"])
        self.assertTrue(self.sim.process(frame(4))["opened"])
        audit = self.sim.store.connection.execute(
            "SELECT payload FROM events WHERE event_id='control/resume/operator-1'"
        ).fetchone()[0]
        self.assertEqual("emergency cleared", json.loads(audit)["reason"])

    def test_resume_rejects_nonflat_bad_data_and_missing_reason(self):
        self.sim.process(frame(0))
        with self.assertRaises(ValueError):
            self.sim.resume(frame(1), event_id="not-halted", reason="test")
        with self.assertRaises(ValueError):
            self.sim.resume(frame(1), event_id="empty-reason", reason="")
        self.sim.process(frame(1, "0.02196"))
        emergency = replace(frame(2, size="0"), signals=replace(frame(2).signals, emergency=True))
        self.sim.process(emergency)
        with self.assertRaisesRegex(ValueError, "flat paper account"):
            self.sim.resume(frame(3), event_id="held-inventory", reason="test")

    def test_partial_cancelled_buy_is_managed_without_overselling(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02270", size="3000"))
        state = self.sim.store.read()
        self.assertGreater(state.inventory, 0)
        self.assertTrue(
            any(o.side == "buy" and o.remaining < o.quantity for o in state.orders.values())
        )
        report = self.sim.process(frame(2, eligible=False))
        self.assertTrue(report["fills"])
        self.assertEqual(0, self.sim.store.read().inventory)
        self.assertFalse(self.sim.store.read().orders)

    def test_exhausted_settlement_is_guarded_without_mutation(self):
        state = Account.start(D(100))
        state.cash = D(0)
        before = encode(state.to_dict())
        with self.assertRaisesRegex(ValueError, "exhausted"):
            self.sim._settle(state)
        self.assertEqual(before, encode(state.to_dict()))

    def test_schema_one_database_is_not_silently_reinterpreted(self):
        row = self.sim.store.connection.execute("SELECT identity FROM state").fetchone()[0]
        identity = json.loads(row)
        identity["schema"] = 1
        self.sim.store.connection.execute("UPDATE state SET identity=?", (encode(identity),))
        with self.assertRaisesRegex(ValueError, "settings differ"):
            self.open()

    def test_resume_cli_loads_saved_rules_and_requires_current_frame(self):
        emergency = replace(frame(0), signals=replace(frame(0).signals, emergency=True))
        self.sim.process(emergency)
        recent = frame(1)
        now = datetime.now(UTC)
        recent = replace(
            recent,
            quote=replace(recent.quote, observed_at=now.isoformat(), received_at=now.isoformat()),
            signals=replace(recent.signals, observed_at=now),
        )
        path = Path(self.temp.name) / "frame.json"
        path.write_text(encode(recent.payload()))
        self.assertEqual(recent.payload(), decode_frame(json.loads(path.read_text())).payload())
        report = resume_paper(self.path, self.config, path, event_id="cli", reason="reviewed")
        self.assertEqual("resume_pending", report["decision"])
        path.write_text(encode(frame(1).payload()))
        with self.assertRaisesRegex(ValueError, "current fresh"):
            resume_paper(self.path, self.config, path, event_id="old", reason="reviewed")


class ReentryTests(TestCase):
    def setUp(self):
        self.rules = MarketRules("TESTUSDT", D("0.01"), D(1), D(5))
        self.account = Account.start(D(100))

    def quote(self, i, bid, size="1000"):
        when = (START + timedelta(seconds=i)).isoformat()
        return Quote(str(i), "TESTUSDT", when, when, D(bid), D(bid) + D("0.01"), D(size), D(size))

    def test_reentry_continues_while_other_inventory_is_held(self):
        place(self.account, LimitOrder("upper", "buy", D(10), D(2), D(2), target=D(11)), self.rules)
        place(self.account, LimitOrder("lower", "buy", D(9), D(2), D(2), target=D(10)), self.rules)
        match(self.account, self.quote(0, "8.8"), self.rules)
        fills = match(self.account, self.quote(1, "10.2"), self.rules)
        self.assertEqual(["sell"], [f.side for f in fills])
        self.assertEqual(D(2), self.account.inventory)
        self.assertTrue(any(o.side == "buy" and o.price == 9 for o in self.account.orders.values()))
        self.assertEqual(
            ["buy"], [f.side for f in match(self.account, self.quote(2, "8.8"), self.rules)]
        )
        self.assertEqual(D(4), self.account.inventory)

    def test_partial_sell_waits_for_completion_and_reserve_cannot_fund_reentry(self):
        self.account.cash = D(80)
        self.account.inventory = D(2)
        place(
            self.account, LimitOrder("sell", "sell", D(11), D(2), D(2), reentry=D(10)), self.rules
        )
        match(self.account, self.quote(0, "11.2", "10"), self.rules)
        self.assertTrue(all(o.side == "sell" for o in self.account.orders.values()))
        self.account.pending = D(90)
        match(self.account, self.quote(1, "11.2", "10"), self.rules)
        self.assertEqual({}, self.account.orders)
        self.assertEqual(D(90), self.account.pending)

    def test_remaining_liquidity_and_reserved_inventory_are_respected(self):
        self.account.inventory = D(8)
        place(self.account, LimitOrder("sell", "sell", D(11), D(4), D(4)), self.rules)
        quote = self.quote(0, "11.2", "60")
        fills = match(self.account, quote, self.rules, recycle=False)
        exits = reduce_unreserved(
            self.account, quote, self.rules, consumed=sum((f.quantity for f in fills), D(0))
        )
        self.assertEqual(D(4), fills[0].quantity)
        self.assertEqual(D(2), exits[0].quantity)
        self.assertEqual(D(2), self.account.inventory)
