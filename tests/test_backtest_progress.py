"""Progress lines: what stage a long backtest is at and how far it has got.

They go to stderr, flushed, behind the prefix ``progress: ``; stdout, results.json and
summary.md are exactly what they were. Offline: the CLI tests below fake every job, except
two that run the real jobs on tiny synthetic windows built from a fake archive.
"""

import contextlib
import io
import json
import re
import sys
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import test_backtest_cli as base
import test_backtest_masked_checks as masked_checks

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest import jobs
from crypto_grid_bot.backtest import progress as progress_module
from crypto_grid_bot.backtest.dataset import load_spec
from crypto_grid_bot.backtest.progress import PREFIX, Progress, elapsed_text
from crypto_grid_bot.backtest.replay import PATH_MODES

ROOT = Path(__file__).resolve().parents[1]
SPEC = base.SPEC
LINE = re.compile(r"progress: \[(\d+:\d\d:\d\d)\] (.*)")
SPAN = re.compile(r"\b\d+:\d\d:\d\d\b")


def texts(stderr):
    """The text of every progress line (after the prefix and the elapsed time), with each
    duration replaced by ``T``. Every line of ``stderr`` must be a progress line."""
    found = []
    for line in stderr.splitlines():
        match = LINE.fullmatch(line)
        assert match, f"not a progress line: {line!r}"
        found.append(SPAN.sub("T", match.group(2)))
    return found


class Clock:
    """A clock the test moves."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ElapsedTextTests(unittest.TestCase):
    def test_hours_minutes_and_seconds_with_no_leading_zero_on_the_hours(self):
        for seconds, text in [
            (0, "0:00:00"),
            (59.9, "0:00:59"),
            (60, "0:01:00"),
            (3723, "1:02:03"),
            (41 * 60 + 10, "0:41:10"),
            (30 * 3600 + 5, "30:00:05"),  # past a day, still hours
            (-3, "0:00:00"),  # a clock never runs back; this keeps a line well formed
        ]:
            with self.subTest(seconds=seconds):
                self.assertEqual(text, elapsed_text(seconds))


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.out, self.err = io.StringIO(), io.StringIO()
        for manager in (contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err)):
            manager.__enter__()
            self.addCleanup(manager.__exit__, None, None, None)

    def test_a_line_has_the_prefix_and_the_time_since_the_command_began(self):
        progress = Progress(self.clock)
        self.clock.advance(4323)
        progress.note("replay start")
        self.assertEqual("progress: [1:12:03] replay start\n", self.err.getvalue())
        self.assertEqual("progress: ", PREFIX)

    def test_nothing_reaches_stdout(self):
        progress = Progress(self.clock)
        with progress.phase("replay", 2) as stage:
            stage.submit(_Pool(), "a", lambda: 1)
        self.assertEqual("", self.out.getvalue())
        self.assertTrue(self.err.getvalue())

    def test_a_phase_reports_its_start_and_its_end_with_its_duration(self):
        progress = Progress(self.clock)
        self.clock.advance(5)
        with progress.phase("manifest verification"):
            self.clock.advance(61)
        self.assertEqual(
            [
                "progress: [0:00:05] manifest verification start",
                "progress: [0:01:06] manifest verification done in 0:01:01",
            ],
            self.err.getvalue().splitlines(),
        )

    def test_a_phase_with_jobs_says_how_many(self):
        with Progress(self.clock).phase("replay", 8):
            pass
        self.assertEqual("replay start (8 jobs)", texts(self.err.getvalue())[0])

    def test_a_phase_that_raises_does_not_claim_to_be_done(self):
        with self.assertRaises(ZeroDivisionError), Progress(self.clock).phase("replay", 1):
            1 / 0  # noqa: B018
        self.assertEqual(["replay start (1 job)"], texts(self.err.getvalue()))

    def test_a_job_is_numbered_by_submission_and_again_by_completion(self):
        # Three jobs submitted together finish in the order 2, 3, 1: the done lines count
        # what has finished, whichever job it is, while the start lines count submissions.
        progress = Progress(self.clock)
        pool = _Pool(hold=True)
        with progress.phase("replay", 3) as stage:
            for label in ("one", "two", "three"):
                stage.submit(pool, label, lambda: None)
            self.clock.advance(10)
            pool.finish(1)
            self.clock.advance(20)
            pool.finish(2)
            self.clock.advance(30)
            pool.finish(0)
        self.assertEqual(
            [
                "replay start (3 jobs)",
                "replay 1/3 start one",
                "replay 2/3 start two",
                "replay 3/3 start three",
                "replay 1/3 done two in T",
                "replay 2/3 done three in T",
                "replay 3/3 done one in T",
                "replay done in T",
            ],
            texts(self.err.getvalue()),
        )
        durations = re.findall(r"done (\w+) in (\S+)", self.err.getvalue())
        self.assertEqual([("two", "0:00:10"), ("three", "0:00:30"), ("one", "0:01:00")], durations)

    def test_a_job_that_raised_is_reported_failed_not_done(self):
        pool = _Pool(hold=True)
        with Progress(self.clock).phase("replay", 1) as stage:
            stage.submit(pool, "boom", lambda: None)
            self.clock.advance(7)
            pool.fail(0, RuntimeError("worker died"))
        self.assertIn("replay 1/1 failed boom after 0:00:07", self.err.getvalue())
        self.assertNotIn("done boom", self.err.getvalue())

    def test_a_cancelled_job_is_reported_failed(self):
        pool = _Pool(hold=True)
        with Progress(self.clock).phase("replay", 1) as stage:
            stage.submit(pool, "gone", lambda: None)
            pool.futures[0].cancel()
        self.assertIn("replay 1/1 failed gone after", self.err.getvalue())

    def test_lines_from_two_threads_never_interleave(self):
        progress = Progress(self.clock)

        def write(name):
            for n in range(200):
                progress.note(f"{name} {n}")

        threads = [threading.Thread(target=write, args=(f"t{i}",)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        lines = self.err.getvalue().splitlines()
        self.assertEqual(800, len(lines))
        for line in lines:
            self.assertRegex(line, r"progress: \[0:00:00\] t\d \d+")

    def test_a_broken_stderr_does_not_stop_the_run(self):
        class Broken:
            def write(self, text):
                raise OSError("broken pipe")

            def flush(self):
                raise OSError("broken pipe")

        progress = Progress(self.clock)
        with contextlib.redirect_stderr(Broken()):
            progress.note("still running")
            with progress.phase("replay", 1) as stage:
                stage.submit(_Pool(), "a", lambda: None)

    def test_no_stderr_never_falls_back_to_stdout(self):
        # print(file=None) writes to stdout, which must stay what it was.
        with patch.object(sys, "stderr", None):
            Progress(self.clock).note("nowhere to go")
        self.assertEqual("", self.out.getvalue())

    def test_the_wall_clock_is_read_only_here(self):
        # The elapsed times exist only in progress lines: no other backtest module reads a
        # clock for them, so none can reach a result.
        package = Path(progress_module.__file__).parent
        readers = {
            path.name for path in package.glob("*.py") if "monotonic" in path.read_text("utf-8")
        }
        self.assertEqual({"progress.py"}, readers)


class _Pool:
    """A pool whose futures finish when the test says (``hold``), or at once."""

    def __init__(self, hold=False):
        self.hold, self.futures = hold, []

    def submit(self, fn, /, *args):
        future = Future()
        self.futures.append(future)
        if not self.hold:
            future.set_result(fn(*args))
        return future

    def finish(self, index):
        self.futures[index].set_result(None)

    def fail(self, index, error):
        self.futures[index].set_exception(error)


# --- The CLI, every job faked ---------------------------------------------------------------

GOOD_ROW = {
    key: value
    for key, value in base.good_result("X", "high_first", True).items()
    if key not in ("symbol", "path_mode", "strategy")
}


class FakeCliTests(unittest.TestCase):
    """``__main__`` with the manifest, the dataset and every job faked, as the other CLI
    tests do. ``--jobs 1`` runs the fakes in the CLI's own in-process executor; another
    count runs them through a stand-in pool."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.spec = load_spec(Path(SPEC))
        self.symbols = cli.checked_symbols(self.spec)
        self.symbol_masks = {}
        patches = [
            patch.object(cli, "ProcessPoolExecutor", base.Inline),
            patch.object(cli, "load_manifest", lambda path: {"created_at": "t"}),
            patch.object(cli, "verify_dataset", lambda *a: None),
            patch.object(cli, "code_commit", lambda: "0123abc"),
            patch.object(cli, "_identity", lambda *a: {}),
            patch.object(cli, "mask_job", self.fake_mask),
            patch.object(cli, "cross_check_job", self.fake_check),
            patch.object(cli, "quote_test_job", self.fake_quote),
            patch.object(cli, "run_job", self.fake_run),
            patch.object(cli, "trend_job", self.fake_trend),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def fake_mask(self, spec, data_dir, symbol):
        return self.symbol_masks.get(symbol, jobs.SymbolMask(symbol, None, ()))

    def fake_check(self, spec, data_dir, symbol, strict_volume=False, **kwargs):
        return {"symbol": symbol, **base.CLEAN}

    def fake_quote(self, spec, data_dir, config_path, mask):
        return {"tick_limit_quotes": 0}

    def fake_run(self, spec, config, data_dir, symbol, mode, gated, fees=None, policy=None, **kw):
        return base.good_result(symbol, mode, gated)

    def fake_trend(self, spec, config, data_dir, symbol, mode, fees=None, **kwargs):
        return {**base.good_result(symbol, mode, False), "variant": "D"}

    def run_cli(self, command, *extra, jobs="1", out=None):
        """(exit code, stdout, stderr) of the CLI."""
        root = out or self.temp.name
        argv = [command, "--spec", SPEC, "--out", root, "--jobs", jobs, *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def job_lines(self, phase, labels, total=None, span="T"):
        """The lines of ``phase`` run one job at a time: each job's start, then its done."""
        total = total or len(labels)
        lines = [f"{phase} start ({total} job{'s' if total != 1 else ''})"]
        for k, label in enumerate(labels, 1):
            lines += [f"{phase} {k}/{total} start {label}"]
            lines += [f"{phase} {k}/{total} done {label} in {span}"]
        return [*lines, f"{phase} done in {span}"]

    def replay_labels(self, gated="V0", extra=()):
        return [
            f"{symbol} {mode} {gated if arm else 'ungated'}"
            for symbol in self.spec.traded
            for mode in PATH_MODES
            for arm in (True, False)
        ] + [
            f"{symbol} {mode} {name}"
            for name in extra
            for symbol in self.spec.traded
            for mode in PATH_MODES
        ]

    def test_a_run_reports_every_phase_and_every_job_through_the_in_process_executor(self):
        code, _, stderr = self.run_cli("run")
        self.assertEqual(0, code)
        labels = self.replay_labels()
        self.assertEqual(8, len(labels))  # two pairs, two paths, gated and ungated
        self.assertEqual(
            [
                "manifest verification start",
                "manifest verification done in T",
                *self.job_lines("mask", self.symbols),
                *self.job_lines("cross-check", self.symbols),
                *self.job_lines("replay", labels),
                "write results start",
                "write results done in T",
            ],
            texts(stderr),
        )

    def test_a_pool_reports_the_same_lines(self):
        _, _, in_process = self.run_cli("run", out=str(Path(self.temp.name) / "a"))
        code, _, pooled = self.run_cli("run", jobs="4", out=str(Path(self.temp.name) / "b"))
        self.assertEqual(0, code)
        self.assertEqual(texts(in_process), texts(pooled))

    def test_a_pool_reports_a_start_per_submission_and_a_done_as_each_future_finishes(self):
        # Every job of a stage is submitted before any is awaited, so with a real pool the
        # starts come first and each done as its future finishes: here the last job first.
        with patch.object(cli, "ProcessPoolExecutor", self.reversing_pool()):
            code, _, stderr = self.run_cli("run", jobs="4")
        self.assertEqual(0, code)
        labels = self.replay_labels()
        total = len(labels)
        self.assertEqual(
            [f"replay {k}/{total} start {label}" for k, label in enumerate(labels, 1)]
            + [
                f"replay {k}/{total} done {label} in T"
                for k, label in enumerate(reversed(labels), 1)
            ],
            [t for t in texts(stderr) if re.match(r"replay \d+/\d+ ", t)],
        )

    def reversing_pool(self):
        """A stand-in pool whose futures finish only when the CLI first awaits one, which it
        does after submitting every job of a stage; they then finish last to first, as a
        pool's do when later jobs are quicker. Each job's work runs when it is submitted."""

        class Reversing:
            held: list = []

            def __init__(self, max_workers, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def submit(self, fn, /, *args):
                future = Awaited()
                Reversing.held.append((future, fn(*args)))
                return future

        class Awaited(Future):
            def result(self, timeout=None):
                held, Reversing.held = Reversing.held, []
                for future, value in reversed(held):
                    future.set_result(value)
                return super().result(timeout)

        return Reversing

    def test_verify_stops_after_the_checks(self):
        code, stdout, stderr = self.run_cli("verify")
        self.assertEqual(0, code)
        self.assertEqual(
            [
                "manifest verification start",
                "manifest verification done in T",
                *self.job_lines("mask", self.symbols),
                *self.job_lines("cross-check", self.symbols),
            ],
            texts(stderr),
        )
        self.assertEqual("valid", json.loads(stdout)["status"])

    def test_an_invalid_window_stops_before_any_replay(self):
        def failing_check(spec, data_dir, symbol, strict_volume=False, **kwargs):
            return {"symbol": symbol, **base.CLEAN, "hours_missing": 1}

        with patch.object(cli, "cross_check_job", failing_check):
            code, _, stderr = self.run_cli("run")
        self.assertEqual(2, code)
        found = texts(stderr)
        self.assertEqual("cross-check done in T", found[-1])
        self.assertFalse([t for t in found if t.startswith(("replay", "write"))])

    def test_a_mask_with_masked_hours_is_reported_after_the_mask_phase(self):
        self.symbol_masks = base.MASKED_WINDOW
        _, _, stderr = self.run_cli("verify")
        found = texts(stderr)
        at = found.index("mask done in T")
        n = len(self.symbols)
        self.assertEqual(
            f"mask found masked hours or excluded months in 2 of {n} symbols: ADAUSDT, BTCUSDT",
            found[at + 1],
        )
        self.assertEqual(f"cross-check start ({n} jobs)", found[at + 2])

    def test_no_mask_report_line_when_nothing_is_masked(self):
        _, _, stderr = self.run_cli("verify")
        self.assertFalse([t for t in texts(stderr) if t.startswith("mask found")])

    def test_mask_report_reports_its_masks_and_the_quote_test(self):
        with patch.object(cli, "quoted", lambda spec, symbol: True):
            code, stdout, stderr = self.run_cli("mask-report")
        self.assertEqual(0, code)
        self.assertEqual(
            [
                "manifest verification start",
                "manifest verification done in T",
                *self.job_lines("mask", self.symbols),
                "mask report start (1 job)",
                "mask report 1/1 start XRPUSDT quote test",
                "mask report 1/1 done XRPUSDT quote test in T",
                "mask report done in T",
            ],
            texts(stderr),
        )
        self.assertIn("xrp_quote_test", json.loads(stdout))

    def test_mask_report_without_a_quote_test_still_reports_the_phase(self):
        _, _, stderr = self.run_cli("mask-report")
        self.assertEqual(["mask report start", "mask report done in T"], texts(stderr)[-2:])

    def test_a_variant_run_names_its_arm_and_the_benchmark_its_own_rows(self):
        code, _, stderr = self.run_cli("run", "--mode-switch", "--trend-benchmark")
        self.assertEqual(0, code)
        labels = self.replay_labels("MS", extra=("D",))
        self.assertEqual(12, len(labels))
        replay = [t for t in texts(stderr) if t.startswith("replay ") and " start " in t]
        self.assertEqual(
            [f"replay {k}/12 start {label}" for k, label in enumerate(labels, 1)],
            replay[1:],  # the phase's own line comes first
        )

    def test_structure_runs_are_labelled_with_v2(self):
        _, _, stderr = self.run_cli("run", "--structure")
        self.assertIn("replay 1/8 start ADAUSDT high_first V0+V2", texts(stderr))
        self.assertIn("replay 2/8 start ADAUSDT high_first ungated", texts(stderr))

    def test_the_full_stack_is_labelled_with_v2_too(self):
        _, _, stderr = self.run_cli("run", "--variant-full")
        self.assertIn("replay 1/8 start ADAUSDT high_first C+F+G+H+V2", texts(stderr))

    def test_stdout_holds_no_progress_line_and_is_what_it_was_without_the_code(self):
        # Compared with the CLI run with the progress code replaced by one that does
        # nothing: stdout, results.json and summary.md byte for byte.
        root = Path(self.temp.name)
        _, with_stdout, with_stderr = self.run_cli("run", "--trend-benchmark", out=str(root / "a"))
        with patch.object(cli, "Progress", _Silent):
            _, without_stdout, without_stderr = self.run_cli(
                "run", "--trend-benchmark", out=str(root / "b")
            )
        self.assertTrue(with_stderr)
        self.assertEqual("", without_stderr)
        self.assertNotIn(PREFIX, with_stdout)

        def shown(text, name):  # the output directory and its time stamp differ by design
            return re.sub(
                r"\d{8}T\d{6}Z", "STAMP", text.replace(json.dumps(str(root / name))[1:-1], "OUT")
            )

        self.assertEqual(shown(without_stdout, "b"), shown(with_stdout, "a"))
        for name in ("results.json", "summary.md"):
            (first,) = (root / "a").rglob(name)
            (second,) = (root / "b").rglob(name)
            self.assertEqual(second.read_bytes(), first.read_bytes(), name)

    def test_the_documents_hold_no_progress_line(self):
        self.run_cli("run")
        for name in ("results.json", "summary.md"):
            (written,) = Path(self.temp.name).rglob(name)
            self.assertNotIn(PREFIX, written.read_text(encoding="utf-8"), name)


class _Silent:
    """The progress code replaced by one that prints nothing: the same interface, no output."""

    def __init__(self, *args, **kwargs):
        pass

    def note(self, text):
        pass

    @contextlib.contextmanager
    def phase(self, name, total=None):
        yield _SilentStage()


class _SilentStage:
    def submit(self, pool, label, fn, /, *args):
        return pool.submit(fn, *args)


# --- The CLI, the real jobs, a tiny synthetic window ----------------------------------------


class RealJobsTests(unittest.TestCase):
    def test_verify_on_a_clean_window_reports_every_symbol_of_both_phases(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            spec_path = masked_checks.build_clean(work)
            spec = load_spec(spec_path)
            symbols = cli.checked_symbols(spec)
            argv = ["verify", "--spec", str(spec_path), "--data-dir", str(work / "data")]
            argv += ["--config", str(ROOT / "config/default.toml"), "--jobs", "1"]
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(argv)
        found = texts(stderr.getvalue())
        n = len(symbols)
        self.assertEqual(3, n)
        for phase in ("mask", "cross-check"):
            for k, symbol in enumerate(symbols, 1):
                self.assertIn(f"{phase} {k}/{n} start {symbol}", found)
                self.assertIn(f"{phase} {k}/{n} done {symbol} in T", found)
        self.assertEqual("manifest verification start", found[0])
        self.assertEqual("cross-check done in T", found[-1])
        # stdout is still the one JSON document, whatever the window's verdict.
        report = json.loads(stdout.getvalue())
        self.assertEqual(2 if report["failures"] else 0, code)
        self.assertEqual([c["symbol"] for c in report["checks"]], symbols)

    def test_a_run_reports_each_of_its_four_replays(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            spec_path = base.build_masked_run(work)
            argv = ["run", "--spec", str(spec_path), "--data-dir", str(work / "data")]
            argv += ["--config", str(ROOT / "config/default.toml"), "--out", str(work / "out")]
            argv += ["--jobs", "1", "--maker-fee", "0", "--taker-fee", "0.0009"]
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(argv)
            (written,) = (work / "out").rglob("results.json")
            document = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(0, code)
        found = texts(stderr.getvalue())
        self.assertEqual(
            [
                "replay start (4 jobs)",
                "replay 1/4 start BTCUSDT high_first V0",
                "replay 1/4 done BTCUSDT high_first V0 in T",
                "replay 2/4 start BTCUSDT high_first ungated",
                "replay 2/4 done BTCUSDT high_first ungated in T",
                "replay 3/4 start BTCUSDT low_first V0",
                "replay 3/4 done BTCUSDT low_first V0 in T",
                "replay 4/4 start BTCUSDT low_first ungated",
                "replay 4/4 done BTCUSDT low_first ungated in T",
                "replay done in T",
            ],
            found[found.index("replay start (4 jobs)") : found.index("replay done in T") + 1],
        )
        self.assertIn(
            "mask found masked hours or excluded months in 1 of 1 symbols: BTCUSDT", found
        )
        self.assertEqual("write results done in T", found[-1])
        # stdout: the summary JSON, the table, the rows; none of it a progress line.
        self.assertNotIn(PREFIX, stdout.getvalue())
        self.assertTrue(document["valid"])


if __name__ == "__main__":
    unittest.main()
