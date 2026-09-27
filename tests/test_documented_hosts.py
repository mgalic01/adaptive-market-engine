"""Every Binance host named in ``src/`` must be an exact entry in ``SECURITY.md``'s list.

The allowed-hosts line listed ``data-api.binance.vision`` and
``data-stream.binance.vision`` but not ``data.binance.vision``, the archive host
``backtest/dataset.py`` has always used. A security boundary that omits a host the code
actually contacts is worse than no list, because it reads as an exhaustive one.

What this checks, exactly:

- **Binance hostnames only**: subdomains of ``binance.vision`` or ``binance.com``, found
  anywhere in ``src/*.py`` text, comments and docstrings included. Any other host,
  another exchange's for example, is not looked for and passes unnoticed.
- **Exact membership** in the block between the ``allowed-hosts`` markers in
  ``SECURITY.md``. A host is not "listed" because it is a substring of a longer listed
  host (``api.binance.vision`` inside ``data-api.binance.vision``), nor because the
  document mentions it elsewhere, such as in a warning.
- **One direction only**: a host in ``src/`` missing from the list fails. The reverse, a
  listed host the code no longer contacts, is deliberately not checked: a stale entry
  makes the list over-broad, a weaker failure than an under-broad one, and a reverse
  check would fail legitimately during any refactor that briefly drops a host.

It is a string scan, not an egress filter: it cannot see a host assembled at runtime,
read from configuration, or reached through a redirect.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
POLICY = ROOT / "SECURITY.md"

# Deliberately broad within Binance: a trading host this project must never use has to
# surface here rather than pass silently.
HOSTNAME = re.compile(r"\b[a-z0-9][a-z0-9.-]*\.binance\.(?:vision|com)\b")
BEGIN = "<!-- allowed-hosts:begin"
END = "<!-- allowed-hosts:end -->"
LISTED = re.compile(r"^\s*- `([a-z0-9][a-z0-9.-]*)`", re.M)


def hosts_in(text: str) -> set[str]:
    return set(HOSTNAME.findall(text))


def hosts_in_source() -> set[str]:
    found: set[str] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        found |= hosts_in(path.read_text(encoding="utf-8"))
    return found


def allowed_hosts(policy: str) -> set[str]:
    """The exact hosts listed between the markers; anything else in the document is prose."""
    if policy.count(BEGIN) != 1 or policy.count(END) != 1:
        raise ValueError("SECURITY.md must contain exactly one allowed-hosts begin/end marker pair")
    block = policy.split(BEGIN, 1)[1].split(END, 1)[0]
    hosts = set(LISTED.findall(block))
    if not hosts:
        raise ValueError("the allowed-hosts block lists no hosts")
    return hosts


def undocumented(source_hosts: set[str], allowed: set[str]) -> list[str]:
    return sorted(source_hosts - allowed)


class DocumentedHostTests(unittest.TestCase):
    def test_every_contacted_host_is_documented(self):
        missing = undocumented(hosts_in_source(), allowed_hosts(POLICY.read_text(encoding="utf-8")))
        self.assertEqual(
            missing,
            [],
            f"{', '.join(missing)} appear(s) in src/ but not in SECURITY.md's allowed-hosts "
            "list. Either add the host there, with the constant and module that use it, or "
            "stop contacting it. An incomplete list reads as exhaustive.",
        )

    def test_the_source_actually_contains_hosts(self):
        # Guards the guard: a pattern that silently matched nothing would make the test
        # above pass no matter what SECURITY.md says. It does not prove completeness.
        self.assertNotEqual(hosts_in_source(), set(), "no Binance hostname found in src/ at all")


class ExactMembershipTests(unittest.TestCase):
    """The failure modes a whole-document substring test had, proven on synthetic text."""

    POLICY = (
        "Market data uses only these hosts. Never use `api.binance.com`.\n"
        "  <!-- allowed-hosts:begin -->\n"
        "  - `data-api.binance.vision` - REST\n"
        "  <!-- allowed-hosts:end -->\n"
        "Trading hosts such as api.binance.com are forbidden.\n"
    )

    def test_a_host_inside_a_longer_listed_host_is_not_listed(self):
        allowed = allowed_hosts(self.POLICY)
        self.assertIn("api.binance.vision", "data-api.binance.vision")  # the trap is real
        self.assertEqual(undocumented({"api.binance.vision"}, allowed), ["api.binance.vision"])

    def test_a_host_mentioned_only_in_a_warning_is_not_listed(self):
        allowed = allowed_hosts(self.POLICY)
        self.assertIn("api.binance.com", self.POLICY)  # mentioned twice, outside the list
        self.assertEqual(undocumented({"api.binance.com"}, allowed), ["api.binance.com"])

    def test_an_exact_listed_host_passes(self):
        allowed = allowed_hosts(self.POLICY)
        self.assertEqual(allowed, {"data-api.binance.vision"})
        self.assertEqual(undocumented({"data-api.binance.vision"}, allowed), [])

    def test_a_policy_without_markers_fails_loudly(self):
        with self.assertRaises(ValueError):
            allowed_hosts("- `data-api.binance.vision`\n")

    def test_an_empty_marker_block_fails_loudly(self):
        with self.assertRaises(ValueError):
            allowed_hosts("<!-- allowed-hosts:begin -->\n<!-- allowed-hosts:end -->\n")

    def test_the_scan_sees_comments_and_docstrings(self):
        text = '"""Uses stream.binance.vision."""\n# fallback: backup.binance.com\n'
        self.assertEqual(hosts_in(text), {"stream.binance.vision", "backup.binance.com"})
