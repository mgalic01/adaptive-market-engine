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
import re
import shutil
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
from crypto_grid_bot.backtest.jobs import SymbolMask

ROOT = Path(__file__).resolve().parents[1]
DEC_2023_MS = 1701388800000  # 2023-12-01T00:00:00Z


def job_of(submitted):
    """The job function behind a submitted callable: the CLI submits every cross-check as a
    ``functools.partial`` that binds keywords (the config, and the symbol's mask)."""
    return getattr(submitted, "func", submitted)


class Recorder:
    """Stand-in for ProcessPoolExecutor that records every callable submitted."""

    submitted: list = []

    def __init__(self, max_workers, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        self.submitted.append(fn)
        if job_of(fn).__name__ == "mask_job":
            return Done(SymbolMask(args[2], None, ()))
        if job_of(fn).__name__ == "cross_check_job":
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
        self.jobs = {job_of(fn).__name__: job_of(fn) for fn in Recorder.submitted}

    def test_every_pool_job_is_defined_outside_a_main_module(self):
        # mask_job runs in the pool too, before any check (spec v1 section 5).
        self.assertEqual({"mask_job", "cross_check_job", "run_job"}, set(self.jobs))
        for name, fn in self.jobs.items():
            with self.subTest(job=name):
                self.assertNotEqual("__main__", fn.__module__.rpartition(".")[2])
                self.assertIs(fn, pickle.loads(pickle.dumps(fn)))
        # What the pool pickles is the submitted callable itself, a partial for a check.
        for submitted in Recorder.submitted:
            restored = pickle.loads(pickle.dumps(submitted))
            self.assertIs(job_of(submitted), job_of(restored))
            self.assertEqual(getattr(submitted, "keywords", {}), getattr(restored, "keywords", {}))

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

    def test_the_identity_is_of_the_source_each_module_compiled(self):
        # Codex review of #160: CPython's timestamp check accepts a stale .pyc for a source
        # rewritten with the same size in the same second, and a disk read after the
        # imports can see other sources than they did. Every module compiles from its
        # source, the identity hashes those bytes, and a stale package root is refused.
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp, "crypto_grid_bot")
            shutil.copytree(
                ROOT / "src" / "crypto_grid_bot",
                package,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            regime, init = package / "strategy" / "regime.py", package / "__init__.py"
            regime.write_text(
                regime.read_text(encoding="utf-8") + 'MARK = "old"\n', encoding="utf-8"
            )
            subprocess.run(
                [sys.executable, "-m", "compileall", "-q", "--invalidation-mode", "timestamp", tmp],
                check=True,
            )

            def rewrite(path, old, new):  # same size, same modification time
                stat, text = path.stat(), path.read_text(encoding="utf-8")
                path.write_text(text.replace(old, new), encoding="utf-8")
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

            def run(probe):
                env = {**os.environ, "PYTHONPATH": tmp}
                return subprocess.run(
                    [sys.executable, "-c", probe], capture_output=True, text=True, env=env
                )

            rewrite(regime, 'MARK = "old"', 'MARK = "new"')
            probe = (
                "import pathlib, crypto_grid_bot.backtest.jobs as j, "
                "crypto_grid_bot.strategy.regime as r; "
                f"p = pathlib.Path({str(regime)!r}); p.write_text(p.read_text() + '#'); "
                "print(r.MARK, j.source_identity() == j.SOURCE_IDENTITY)"
            )
            out = run(probe)
            self.assertEqual("new True", out.stdout.strip(), out.stderr)
            rewrite(init, '"0.8.0"', '"0.8.9"')
            out = run("import crypto_grid_bot")
            self.assertNotEqual(0, out.returncode)
            self.assertIn("is not the code that ran", out.stderr)

    def test_a_spawned_worker_can_unpickle_every_pool_job(self):
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(1, mp_context=context) as pool:
            names = {pool.submit(getattr, fn, "__qualname__").result() for fn in self.jobs.values()}
        self.assertEqual({"mask_job", "cross_check_job", "run_job"}, names)


class Timeline:
    """Stand-in pool that logs, in order, each submission and each wait on a result, with
    the job's name and its symbol."""

    events: list = []

    def __init__(self, max_workers, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        job = (job_of(fn).__name__, args[2])
        self.events.append(("submit", *job))
        if job_of(fn).__name__ == "mask_job":
            return Logged(self.events, job, SymbolMask(args[2], None, ()))
        return Logged(self.events, job, {"symbol": args[2], **CLEAN})


class Logged:
    def __init__(self, events, job, value):
        self.events, self.job, self.value = events, job, value

    def result(self):
        self.events.append(("result", *self.job))
        return self.value

    def add_done_callback(self, callback):
        callback(self)  # a finished future calls it at once; the timeline logs results only

    def cancelled(self):
        return False

    def exception(self):
        return None


class CrossCheckParallelismTests(unittest.TestCase):
    def test_every_cross_check_is_submitted_before_any_result_is_awaited(self):
        # Awaiting each check inside the submit loop ran them one at a time on the pool. The
        # masks come first, submitted the same way, since each check takes its symbol's.
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
        expected = []
        for job in ("mask_job", "cross_check_job"):
            expected += [("submit", job, s) for s in symbols]
            expected += [("result", job, s) for s in symbols]
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
        # What matters is that every mask and every check ran in a spawned worker, each
        # check with its symbol's mask (a pickled partial holding a frozenset). The
        # synthetic archives hold three hours a month, so every month's defects exceed 17%
        # and the 17% rule masks every hour: no hour is left to compare, and verify reports
        # the window invalid (2), with the masks in its comparison mask.
        self.assertEqual(2, done.returncode, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertEqual(["BTCUSDT", "ETHUSDT"], [c["symbol"] for c in report["checks"]])
        self.assertEqual(
            ["BTCUSDT: no hours compared", "ETHUSDT: no hours compared"], report["failures"]
        )
        self.assertEqual(
            {symbol: ["2023-12", "2024-01"] for symbol in ("BTCUSDT", "ETHUSDT")},
            {s: entry["excluded_months"] for s, entry in report["comparison_mask"].items()},
        )
        # The progress lines of a real pool, on stderr and never on stdout (parsed above as
        # the one report): each mask and each check is reported started as it is submitted
        # and done as its future finishes, in whatever order the workers finish them.
        self.assertNotIn("progress:", done.stdout)
        lines = "\n".join(x for x in done.stderr.splitlines() if x.startswith("progress: "))
        stamp = r"^progress: \[\d+:\d\d:\d\d\] "
        for phase in ("mask", "cross-check"):
            wanted = [
                rf"{phase} start \(2 jobs\)",
                rf"{phase} done in \d+:\d\d:\d\d",
                *(rf"{phase} \d/2 start {symbol}" for symbol in ("BTCUSDT", "ETHUSDT")),
                *(
                    rf"{phase} \d/2 done {symbol} in \d+:\d\d:\d\d"
                    for symbol in ("BTCUSDT", "ETHUSDT")
                ),
            ]
            for pattern in wanted:
                self.assertRegex(lines, re.compile(stamp + pattern + "$", re.M))


class PoolSizeTests(unittest.TestCase):
    """The backtest workflow runs the CLI with ``--jobs 4``, one job per CPU of the hosted
    runner. A pool must write exactly the results that one in-process job writes. The mode
    switcher's run with D submits every kind of replay job (the gated and ungated V0 rows,
    the mode switcher's and D's), so it stands for the workflow's runs; V0 with D and F
    were checked the same way when the workflow moved to a pool."""

    def test_a_pool_of_four_writes_the_results_of_one_job(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(sys.path.remove, str(ROOT / "scripts"))
        import byte_identity

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        work = root / "up"
        byte_identity.build_dataset(work, "up")
        runs = {"MS+D": ("--mode-switch", "--trend-benchmark")}
        for name, flags in runs.items():
            with self.subTest(run=name):
                one = byte_identity.run_cli(work, root / f"{name}-1", flags)
                # run_cli passes --jobs 1 before the flags; the last --jobs wins.
                pool = byte_identity.run_cli(work, root / f"{name}-4", (*flags, "--jobs", "4"))
                self.assertTrue(one["results"])
                self.assertEqual(byte_identity.set_aside(one), byte_identity.set_aside(pool), name)
