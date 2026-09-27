"""Every network host the code contacts must be named in ``SECURITY.md``.

The allowed-hosts line listed ``data-api.binance.vision`` and
``data-stream.binance.vision`` but not ``data.binance.vision``, the archive host
``backtest/dataset.py`` has always used. A security boundary that omits a host the code
actually contacts is worse than no list, because it reads as an exhaustive one. This
test fails when the two drift apart, in either direction.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
POLICY = ROOT / "SECURITY.md"

# Hostnames as they appear in string literals. Deliberately broad: a new Binance host,
# including a trading one this project must never use, has to surface here.
HOSTNAME = re.compile(r"\b[a-z0-9][a-z0-9.-]*\.binance\.(?:vision|com)\b")


def hosts_in_source() -> set[str]:
    found: set[str] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        found.update(HOSTNAME.findall(path.read_text(encoding="utf-8")))
    return found


class DocumentedHostTests(unittest.TestCase):
    def test_every_contacted_host_is_documented(self):
        policy = POLICY.read_text(encoding="utf-8")
        undocumented = sorted(h for h in hosts_in_source() if h not in policy)
        self.assertEqual(
            undocumented,
            [],
            f"{', '.join(undocumented)} appear(s) in src/ but not in SECURITY.md. Either "
            "add the host to the allowed-hosts list with the constant and module that "
            "use it, or stop contacting it. An incomplete list reads as exhaustive.",
        )

    def test_the_source_actually_contains_hosts(self):
        # Guards the guard: a regex that silently matches nothing would make the test
        # above pass no matter what SECURITY.md says.
        self.assertNotEqual(hosts_in_source(), set(), "no hostname found in src/ at all")
