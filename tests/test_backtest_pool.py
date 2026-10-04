"""The CLI's pool jobs must be importable by a spawned worker.

``python -m crypto_grid_bot.backtest`` runs the package ``__main__`` as ``__main__``.
A spawned worker does not re-run it, so a job function defined there cannot be
unpickled and the pool breaks (``BrokenProcessPool``) before any check runs. Spawn is
the default on Windows and macOS; CI runs Linux, so these tests force it.
"""

import contextlib
import io
import json
import multiprocessing
import os
import pickle
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from unittest.mock import patch

from test_backtest_cli import CLEAN, SPEC, Done, good_result
from test_backtest_loaders import JAN_2024_MS, FakeArchive, hour_rows, minute_rows

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest.dataset import fetch_dataset, load_spec, write_manifest

ROOT = Path(__file__).resolve().parents[1]
DEC_2023_MS = 1701388800000  # 2023-12-01T00:00:00Z


class Recorder:
    """Stand-in for ProcessPoolExecutor that records every function submitted."""

    submitted: list = []

    def __init__(self, max_workers, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        self.submitted.append(fn)
        if fn.__name__ == "cross_check_job":
            return Done({"symbol": args[2], **CLEAN})
        return Done(good_result(*args[3:6]))


class PoolJobReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        Recorder.submitted = []
        patches = [
            patch.object(cli, "ProcessPoolExecutor", Recorder),
            patch.object(cli, "load_manifest", lambda path: {"created_at": "t"}),
            patch.object(cli, "verify_dataset", lambda *a: None),
            patch.object(cli, "_identity", lambda *a: {}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, cli.main(["run", "--spec", SPEC, "--out", self.temp.name]))
        self.jobs = {fn.__name__: fn for fn in Recorder.submitted}

    def test_every_pool_job_is_defined_outside_a_main_module(self):
        self.assertEqual({"cross_check_job", "run_job"}, set(self.jobs))
        for name, fn in self.jobs.items():
            with self.subTest(job=name):
                self.assertNotEqual("__main__", fn.__module__.rpartition(".")[2])
                self.assertIs(fn, pickle.loads(pickle.dumps(fn)))

    def test_a_spawned_worker_refuses_other_sources(self):
        # Codex review of #160: the initializer runs in the worker before any job.
        from concurrent.futures.process import BrokenProcessPool

        from crypto_grid_bot.backtest import jobs

        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            1, mp_context=context, initializer=jobs.check_sources, initargs=(jobs.SOURCE_IDENTITY,)
        ) as pool:
            self.assertEqual("run_job", pool.submit(getattr, jobs.run_job, "__name__").result())
        with (
            self.assertRaises(BrokenProcessPool),
            ProcessPoolExecutor(
                1, mp_context=context, initializer=jobs.check_sources, initargs=("other",)
            ) as pool,
        ):
            pool.submit(getattr, jobs.run_job, "__name__").result()

    def test_the_check_uses_the_identity_taken_at_import(self):
        # Codex review of #160: a fresh read of the disk could already be back to the
        # expected sources while the worker runs other code it imported earlier.
        from crypto_grid_bot.backtest import jobs

        with patch.object(jobs, "source_identity", lambda: "restored"):
            jobs.check_sources(jobs.SOURCE_IDENTITY)  # the import-time identity: accepted
            with self.assertRaises(RuntimeError):
                jobs.check_sources("restored")
        # Importing jobs loads every job module before the identity is taken.
        probe = (
            "import sys, crypto_grid_bot.backtest.jobs as j; "
            "print('crypto_grid_bot.backtest.trend_benchmark' in sys.modules)"
        )
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        out = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, env=env, check=True
        )
        self.assertEqual("True", out.stdout.strip())

    def test_a_spawned_worker_can_unpickle_every_pool_job(self):
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(1, mp_context=context) as pool:
            names = {pool.submit(getattr, fn, "__qualname__").result() for fn in self.jobs.values()}
        self.assertEqual({"cross_check_job", "run_job"}, names)


class Timeline:
    """Stand-in pool that logs, in order, each submission and each wait on a result."""

    events: list = []

    def __init__(self, max_workers, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        self.events.append(("submit", args[2]))
        return Logged(self.events, args[2], {"symbol": args[2], **CLEAN})


class Logged:
    def __init__(self, events, symbol, value):
        self.events, self.symbol, self.value = events, symbol, value

    def result(self):
        self.events.append(("result", self.symbol))
        return self.value


class CrossCheckParallelismTests(unittest.TestCase):
    def test_every_cross_check_is_submitted_before_any_result_is_awaited(self):
        # Awaiting each check inside the submit loop ran them one at a time on the pool.
        Timeline.events = []
        patches = [
            patch.object(cli, "ProcessPoolExecutor", Timeline),
            patch.object(cli, "load_manifest", lambda path: {"created_at": "t"}),
            patch.object(cli, "verify_dataset", lambda *a: None),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, cli.main(["verify", "--spec", SPEC]))
        symbols = cli.checked_symbols(load_spec(Path(SPEC)))
        self.assertGreater(len(symbols), 1)
        expected = [("submit", s) for s in symbols] + [("result", s) for s in symbols]
        self.assertEqual(expected, Timeline.events)
        # Results are still reported in the symbols' order.
        self.assertEqual(symbols, [c["symbol"] for c in json.loads(out.getvalue())["checks"]])


# Runs the package exactly as ``python -m`` does, with spawn forced on every platform.
DRIVER = """
import multiprocessing, runpy
multiprocessing.set_start_method("spawn", force=True)
runpy.run_module("crypto_grid_bot.backtest", run_name="__main__", alter_sys=True)
"""


class SpawnedCliTests(unittest.TestCase):
    def test_verify_through_a_spawn_pool_on_a_tiny_synthetic_dataset(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        work = Path(temp.name)
        spec_path = work / "tiny.toml"
        spec_path.write_text(
            'name = "tiny"\npurpose = "spawn regression test"\ntraded = ["BTCUSDT"]\n'
            'market_proxy = "BTCUSDT"\nbreadth_basket = ["BTCUSDT", "ETHUSDT"]\n'
            'warmup_start = "2023-12"\nstart = "2024-01"\nend = "2024-01"\n'
            'initial_quote = "100"\nfee_rate = "0.001"\nslippage_rate = "0.0005"\n'
            'participation = "0.10"\nassumed_spread_pct = "0.05"\n'
        )
        archive = FakeArchive()
        archive.add("BTCUSDT", "1m", "2024-01", minute_rows(JAN_2024_MS, 120))
        for symbol in ("BTCUSDT", "ETHUSDT"):
            archive.add(symbol, "1h", "2023-12", hour_rows(DEC_2023_MS, 3))
            archive.add(symbol, "1h", "2024-01", hour_rows(JAN_2024_MS, 3))
        filters = {"base": "BTC", "quote": "USDT", "tick_size": "0.01"}
        filters |= {"quantity_step": "0.00001", "min_notional": "5"}
        manifest = fetch_dataset(
            load_spec(spec_path),
            work / "data",
            fetcher=archive,
            instruments=lambda symbol: filters,
        )
        write_manifest(work / "tiny.manifest.json", manifest)
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        command = [sys.executable, "-c", DRIVER, "verify", "--spec", str(spec_path)]
        command += ["--data-dir", str(work / "data"), "--jobs", "2"]
        done = subprocess.run(
            command, capture_output=True, text=True, env=env, timeout=300, check=False
        )
        self.assertNotIn("BrokenProcessPool", done.stderr)
        # The synthetic archives are deliberately incomplete, so verify reports them
        # invalid (2); what matters is that every check ran in a spawned worker.
        self.assertEqual(2, done.returncode, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertEqual(["BTCUSDT", "ETHUSDT"], [c["symbol"] for c in report["checks"]])
