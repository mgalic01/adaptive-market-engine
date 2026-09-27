"""The suite must exercise this checkout's source, never an installed copy elsewhere.

A machine carrying an editable install of a second checkout puts that tree's ``src`` on
``sys.path``. Without ``pythonpath = ["src"]`` in ``[tool.pytest.ini_options]``, pytest
then collects this repository's tests and runs them against the other tree, so a fix
already present here looks like a live regression. This test fails loudly instead.
"""

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
