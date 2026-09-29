"""Preflight orchestration uses dummy processes: no nested checks or network calls."""

import contextlib
import io
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import preflight  # noqa: E402


class PreflightTests(unittest.TestCase):
    def setUp(self):
        # main() prints platform.system()/release(). On Windows (Python 3.14) a cold
        # platform cache can shell out ("ver") through subprocess.run, which these tests
        # mock, whenever the WMI query fails. Filling the cache first keeps the mock for
        # preflight's own checks only.
        platform.uname()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "tests").mkdir()
        for name in ("test_one.py", "test_two.py"):
            (self.root / "tests" / name).write_text("", encoding="utf-8")
        (self.root / "outside.py").write_text("", encoding="utf-8")
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for manager in (
            patch.object(preflight, "ROOT", self.root),
            contextlib.redirect_stdout(self.stdout),
            contextlib.redirect_stderr(self.stderr),
        ):
            manager.__enter__()
            self.addCleanup(manager.__exit__, None, None, None)
        self.calls = []

    def runner(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    def test_default_runs_all_checks_with_this_checkout_and_no_cache_or_shell(self):
        inherited = {
            "PYTHONPATH": "wrong-checkout",
            "PYTEST_ADDOPTS": "--collect-only",
            "PYTEST_PLUGINS": "unrelated",
        }
        with (
            patch.dict(os.environ, inherited),
            patch.object(preflight.subprocess, "run", self.runner),
        ):
            self.assertEqual(0, preflight.main([]))
            self.assertEqual("wrong-checkout", os.environ["PYTHONPATH"])
        self.assertEqual(6, len(self.calls))
        self.assertIn("--no-cache", self.calls[0][0])
        self.assertIn("--no-fix", self.calls[0][0])
        self.assertIn("--check", self.calls[1][0])
        # The same paths CI type-checks and scans (quality.yml).
        self.assertEqual(["mypy", "src", "scripts"], self.calls[2][0][3:])
        self.assertEqual(["bandit", "-q", "-r", "src", "scripts"], self.calls[3][0][3:])
        self.assertEqual("scripts/check_reports.py", self.calls[4][0][-1])
        self.assertEqual(["pytest", "-p", "no:cacheprovider", "--", "tests"], self.calls[5][0][3:])
        for command, options in self.calls:
            self.assertEqual([sys.executable, "-B"], command[:2])
            self.assertEqual(self.root, options["cwd"])
            self.assertFalse(options["shell"])
            self.assertFalse(options["check"])
            self.assertEqual(str(self.root / "src"), options["env"]["PYTHONPATH"])
            self.assertEqual("1", options["env"]["PYTHONDONTWRITEBYTECODE"])
            self.assertEqual("1", options["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"])
            self.assertNotIn("PYTEST_ADDOPTS", options["env"])
            self.assertNotIn("PYTEST_PLUGINS", options["env"])
        self.assertIn("full pytest suite", self.stdout.getvalue())
        self.assertIn(f"Interpreter: Python {sys.version.split()[0]}", self.stdout.getvalue())

    def test_an_interpreter_below_the_floor_stops_before_any_check(self):
        with (
            patch.object(preflight.sys, "version_info", (3, 11, 15, "final", 0)),
            patch.object(preflight.subprocess, "run", self.runner),
        ):
            self.assertEqual(2, preflight.main([]))
        self.assertEqual([], self.calls)
        self.assertIn("below the project floor 3.12", self.stderr.getvalue())

    def test_a_newer_interpreter_runs_but_says_it_is_not_ci_evidence(self):
        with (
            patch.object(preflight.sys, "version_info", (3, 14, 0, "final", 0)),
            patch.object(preflight.subprocess, "run", self.runner),
        ):
            self.assertEqual(0, preflight.main([]))
        self.assertEqual(6, len(self.calls))
        self.assertIn("not CI evidence", self.stdout.getvalue())

    def test_the_floor_matches_pyproject(self):
        text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
        floor = ".".join(map(str, preflight.FLOOR))
        self.assertIn(f'requires-python = ">={floor}"', text)
        self.assertIn(f'python_version = "{floor}"', text)

    def test_focused_files_are_normalized_deduplicated_and_labeled(self):
        with patch.object(preflight.subprocess, "run", self.runner):
            self.assertEqual(
                0,
                preflight.main(
                    [
                        "--tests",
                        "tests/test_one.py",
                        str(self.root / "tests" / "test_two.py"),
                        "tests/test_one.py",
                    ]
                ),
            )
        self.assertEqual(["--", "tests/test_one.py", "tests/test_two.py"], self.calls[-1][0][-3:])
        self.assertIn("NOT the full suite or full CI", self.stdout.getvalue())
        self.assertIn("full-suite validation", self.stdout.getvalue())

    def test_bad_selectors_fail_before_any_check(self):
        invalid = (
            [],
            [""],
            [" "],
            ["tests"],
            ["tests/missing.py"],
            ["outside.py"],
            ["../test_outside.py"],
            ["tests/../tests/test_one.py"],
            ["tests/test_one.py::test_x"],
            ["tests/*.py"],
            ["tests/test_one.py", "outside.py"],
        )
        for selected in invalid:
            with (
                self.subTest(selected=selected),
                patch.object(preflight.subprocess, "run", self.runner),
            ):
                with self.assertRaises(SystemExit) as raised:
                    preflight.main(["--tests", *selected])
                self.assertEqual(2, raised.exception.code)
                self.assertEqual([], self.calls)
        with self.assertRaises(ValueError):
            preflight.test_files(self.root, [])

    def test_resolved_escape_is_rejected_before_checks(self):
        # Model a symlink resolving outside tests without needing Windows link privilege.
        original = Path.resolve

        def resolve(path, *args, **kwargs):
            if path.name == "test_escape.py":
                return self.root / "outside.py"
            return original(path, *args, **kwargs)

        with (
            patch.object(Path, "resolve", resolve),
            patch.object(preflight.subprocess, "run", self.runner),
            self.assertRaises(SystemExit),
        ):
            preflight.main(["--tests", "tests/test_escape.py"])
        self.assertEqual([], self.calls)

    def test_failure_stops_later_checks_and_preserves_exit_code(self):
        def failed(command, **kwargs):
            self.calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 7 if len(self.calls) == 2 else 0)

        with patch.object(preflight.subprocess, "run", failed):
            self.assertEqual(7, preflight.main([]))
        self.assertEqual(2, len(self.calls))
        self.assertIn("Format check FAILED (exit 7)", self.stderr.getvalue())

    def test_process_start_error_is_reported_and_stops(self):
        with patch.object(preflight.subprocess, "run", side_effect=OSError("unavailable")) as run:
            self.assertEqual(1, preflight.main([]))
        self.assertEqual(1, run.call_count)
        self.assertIn("Lint could not start", self.stderr.getvalue())
