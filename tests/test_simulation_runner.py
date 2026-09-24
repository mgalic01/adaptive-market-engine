import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.demo import demo_frames, run_demo
from crypto_grid_bot.simulation.models import D, MarketRules
from crypto_grid_bot.simulation.runner import PaperSimulator
from crypto_grid_bot.simulation.store import encode

CONFIG = Path(__file__).resolve().parents[1] / "config" / "default.toml"


class SimulatorTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "paper.db"
        self.config = load_config(CONFIG)
        self.rules = MarketRules()
        self.sim = self.open()
        self.addCleanup(lambda: self.sim.close())
        self.frames = demo_frames(2)

    def open(self, path=None, config=None):
        return PaperSimulator(path or self.path, config or self.config, self.rules)

    def restart(self):
        self.sim.close()
        self.sim = self.open()

    def test_restart_matches_uninterrupted_replay(self):
        other = self.open(Path(self.directory.name) / "baseline.db")
        self.addCleanup(other.close)
        for index, frame in enumerate(self.frames):
            expected = other.process(frame)
            actual = self.sim.process(frame)
            self.assertEqual(expected, actual)
            if index in [0, 1, 3, 5]:
                self.restart()
        self.assertEqual(
            encode(other.store.read().to_dict()), encode(self.sim.store.read().to_dict())
        )

    def test_duplicate_event_and_changed_payload(self):
        for frame in self.frames[:3]:
            first = self.sim.process(frame)
            before = encode(self.sim.store.read().to_dict())
            self.assertEqual(first, self.sim.process(frame))
            self.assertEqual(before, encode(self.sim.store.read().to_dict()))
        with self.assertRaisesRegex(ValueError, "different data"):
            self.sim.process(replace(self.frames[2], atr=D("0.001")))

    def test_atomic_rollback_when_execution_fails_after_mutation(self):
        self.sim.process(self.frames[0])
        before = encode(self.sim.store.read().to_dict())

        def crash(account, quote, rules, **kwargs):
            account.cash = D("1")
            account.inventory = D("999")
            raise RuntimeError("simulated failure before commit")

        with (
            patch("crypto_grid_bot.simulation.runner.match", side_effect=crash),
            self.assertRaises(RuntimeError),
        ):
            self.sim.process(self.frames[1])
        self.restart()
        self.assertEqual(before, encode(self.sim.store.read().to_dict()))
        self.assertTrue(self.sim.process(self.frames[1])["fills"])

    def test_profit_allocation_and_transfer_recover_atomically(self):
        self.sim.close()
        self.config = replace(self.config, minimum_transfer_quote=0.1)
        self.path = Path(self.directory.name) / "transfers.db"
        self.sim = self.open()
        for frame in self.frames[:3]:
            self.sim.process(frame)
        before = encode(self.sim.store.read().to_dict())
        with (
            patch.object(self.sim.vault, "confirm_transfer", side_effect=RuntimeError("crash")),
            self.assertRaises(RuntimeError),
        ):
            self.sim.process(self.frames[3])
        self.restart()
        self.assertEqual(before, encode(self.sim.store.read().to_dict()))
        report = self.sim.process(self.frames[3])
        state = self.sim.store.read()
        self.assertGreater(state.secured, D("0"))
        self.assertEqual(0, state.pending)
        self.assertEqual(state.cash - D("100"), state.secured)
        self.assertEqual(report, self.sim.process(self.frames[3]))
        self.assertEqual(state.secured, self.sim.store.read().secured)

    def test_stale_quote_cancels_entries_and_pause_survives_restart(self):
        self.sim.process(self.frames[0])
        bad = replace(
            self.frames[1],
            quote=replace(self.frames[1].quote, received_at="2026-01-01T00:02:00+00:00"),
        )
        report = self.sim.process(bad)
        self.assertEqual("pause", report["decision"])
        state = self.sim.store.read()
        self.assertEqual({}, state.orders)
        self.assertEqual(D("100"), state.cash)
        self.restart()
        self.assertEqual("pause", self.sim.process(self.frames[2])["decision"])
        self.assertEqual(0, self.sim.store.read().fill_count)

    def test_out_of_order_future_quote_and_old_signals_fail_closed(self):
        variants = [
            replace(
                self.frames[1],
                quote=replace(self.frames[1].quote, observed_at="2025-12-31T23:59:59+00:00"),
            ),
            replace(
                self.frames[1],
                quote=replace(self.frames[1].quote, observed_at="2026-01-01T00:00:02+00:00"),
            ),
            replace(
                self.frames[1],
                signals=replace(
                    self.frames[1].signals,
                    observed_at=self.frames[1].signals.observed_at.replace(year=2025),
                ),
            ),
        ]
        for index, frame in enumerate(variants):
            simulator = self.open(Path(self.directory.name) / f"bad-{index}.db")
            self.addCleanup(simulator.close)
            simulator.process(self.frames[0])
            self.assertEqual("pause", simulator.process(frame)["decision"])
            self.assertEqual(0, simulator.store.read().inventory)

    def test_crash_drawdown_exits_with_limited_liquidity(self):
        for frame in self.frames[:3]:
            self.sim.process(frame)
        crash = replace(
            self.frames[3],
            quote=replace(
                self.frames[3].quote, bid=D("0.01"), ask=D("0.01001"), bid_size=D("10000")
            ),
        )
        report = self.sim.process(crash)
        self.assertEqual("halt", report["decision"])
        self.assertTrue(self.sim.store.read().liquidating)
        self.assertEqual(D("1000"), D(report["fills"][0]["quantity"]))
        self.assertGreater(self.sim.store.read().inventory, 0)
        self.assertEqual(0, self.sim.store.read().pending)

    def test_changed_config_or_initial_balance_cannot_reinitialize_account(self):
        self.sim.process(self.frames[0])
        with self.assertRaisesRegex(ValueError, "settings differ"):
            self.open(config=replace(self.config, minimum_transfer_quote=1))
        with self.assertRaisesRegex(ValueError, "settings differ"):
            PaperSimulator(self.path, self.config, self.rules, D("200"))
        self.assertTrue(self.sim.store.read().orders)

    def test_invalid_persisted_balances_are_rejected_on_restart(self):
        state = self.sim.store.read().to_dict()
        state["cash"] = "-1"
        self.sim.store.connection.execute("UPDATE state SET data=?", (encode(state),))
        with self.assertRaises(ValueError):
            self.open()

    def test_demo_loops_and_is_repeatable(self):
        path = Path(self.directory.name) / "demo.db"
        first = run_demo(path, self.config)
        self.assertEqual(30, first["cycles"])
        self.assertIsNone(first["halt_reason"])
        self.assertGreater(first["secured_reserve"], 0)
        self.assertEqual(0, first["inventory"])
        self.assertEqual(first, run_demo(path, self.config))

    def test_ledger_journal_contains_each_event_once(self):
        for frame in self.frames:
            self.sim.process(frame)
            self.sim.process(frame)
        events = self.sim.store.connection.execute("SELECT payload, result FROM events").fetchall()
        self.assertEqual(len(self.frames), len(events))
        fills = sum(len(json.loads(result)["fills"]) for _, result in events)
        self.assertEqual(fills, self.sim.store.read().fill_count)

    def test_overnight_gap_is_not_reset_out_of_daily_loss(self):
        for frame in self.frames[:3]:
            self.sim.process(frame)
        frame = self.frames[3]
        tomorrow = replace(
            frame,
            quote=replace(
                frame.quote,
                observed_at="2026-01-02T00:00:00+00:00",
                received_at="2026-01-02T00:00:00+00:00",
                bid=D("0.0205"),
                ask=D("0.02051"),
            ),
            signals=replace(
                frame.signals, observed_at=frame.signals.observed_at.replace(day=2, second=0)
            ),
        )
        report = self.sim.process(tomorrow)
        self.assertEqual("pause", report["decision"])
        self.assertIn("daily loss", report["reason"])

    def test_cash_and_fees_reconcile_to_journal_and_profit_split(self):
        for frame in demo_frames(30):
            self.sim.process(frame)
        events = self.sim.store.connection.execute("SELECT result FROM events").fetchall()
        net_flows, fees = D("0"), D("0")
        for (raw,) in events:
            for fill in json.loads(raw)["fills"]:
                notional = D(fill["price"]) * D(fill["quantity"])
                fee = D(fill["fee"])
                fees += fee
                net_flows += (notional if fill["side"] == "sell" else -notional) - fee
        state = self.sim.store.read()
        self.assertEqual(state.initial_cash + net_flows, state.cash + state.secured)
        self.assertEqual(fees, state.fees)
        self.assertEqual(net_flows / 2, state.pending + state.secured)
        self.assertEqual(state.initial_cash + net_flows / 2, state.cash - state.pending)

    def test_new_cycle_never_budgets_pending_or_secured_reserve(self):
        for frame in self.frames[:4]:
            self.sim.process(frame)
        before = self.sim.store.read()
        self.assertGreater(before.pending, 0)
        self.sim.process(self.frames[4])
        after = self.sim.store.read()
        self.assertEqual(before.pending, after.pending)
        self.assertLessEqual(
            after.reserved_quote(self.rules), (before.cash - before.pending) * D("0.8")
        )
        self.assertGreaterEqual(after.available_quote(self.rules), 0)

    def test_news_veto_cancels_before_buying(self):
        self.sim.process(self.frames[0])
        frame = replace(self.frames[1], candidate=replace(self.frames[1].candidate, news_risk=0.9))
        report = self.sim.process(frame)
        self.assertEqual("pause", report["decision"])
        self.assertFalse(report["fills"])
        self.assertTrue(report["cancelled"])
        self.assertEqual(0, self.sim.store.read().inventory)

    def test_unaffordable_grid_stays_in_cash_without_partial_orders(self):
        path = Path(self.directory.name) / "small.db"
        simulator = PaperSimulator(path, self.config, self.rules, D("10"))
        self.addCleanup(simulator.close)
        report = simulator.process(self.frames[0])
        self.assertEqual("cash", report["decision"])
        self.assertEqual({}, simulator.store.read().orders)
        self.assertEqual(D("10"), simulator.store.read().cash)

    def test_actual_wide_spread_is_rejected_despite_good_candidate_metrics(self):
        self.sim.process(self.frames[0])
        frame = replace(
            self.frames[1], quote=replace(self.frames[1].quote, bid=D("0.02"), ask=D("0.022"))
        )
        report = self.sim.process(frame)
        self.assertEqual("pause", report["decision"])
        self.assertFalse(report["fills"])
        self.assertIn("spread", report["reason"])

    def test_multiple_connections_cannot_duplicate_events(self):
        other = self.open()
        self.addCleanup(other.close)
        for frame in self.frames:
            self.assertEqual(self.sim.process(frame), other.process(frame))
        count = self.sim.store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(len(self.frames), count)
