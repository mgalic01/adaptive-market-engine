"""The suite must exercise this checkout's source, never an installed copy elsewhere.

A machine carrying an editable install of a second checkout puts that tree's ``src`` on
``sys.path``. Without ``pythonpath = ["src"]`` in ``[tool.pytest.ini_options]``, pytest
then collects this repository's tests and runs them against the other tree, so a fix
already present here looks like a live regression. This test fails loudly instead.

``pythonpath`` also makes the suite importable under *any* interpreter, including one
below the ``requires-python`` floor, where ``pip install -e .`` refuses outright. A green
run on such an interpreter says nothing about the supported one, so the floor is asserted
here too, read from ``pyproject.toml`` rather than restated.
"""

import sys
import tomllib
import unittest
from pathlib import Path

import crypto_grid_bot

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "src" / "crypto_grid_bot"


class ImportProvenanceTests(unittest.TestCase):
    def test_package_resolves_inside_this_checkout(self):
        actual = Path(crypto_grid_bot.__file__).resolve().parent
        self.assertEqual(
            actual,
            EXPECTED,
            f"crypto_grid_bot was imported from {actual}, not {EXPECTED}. Every result in "
            "this run describes that other source tree. Check for an editable-install "
            "'.pth' in site-packages pointing at another checkout, and confirm "
            'pythonpath = ["src"] is still set in [tool.pytest.ini_options].',
        )

    def test_interpreter_meets_the_declared_floor(self):
        spec = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        requires = spec["project"]["requires-python"]
        # Check the form before parsing it: another specifier (~=, >) would otherwise
        # raise ValueError here and hide the real problem behind a stack trace.
        self.assertTrue(requires.startswith(">="), f"unexpected requires-python form: {requires!r}")
        floor = tuple(int(part) for part in requires.removeprefix(">=").split("."))
        self.assertGreaterEqual(
            sys.version_info[: len(floor)],
            floor,
            f"running Python {'.'.join(map(str, sys.version_info[:3]))}, below this "
            f"project's requires-python {requires}. `pip install -e .` refuses this "
            "interpreter, so a passing run here does not describe a supported "
            "environment. Use a Python "
            f"{'.'.join(map(str, floor))}+ interpreter.",
        )
