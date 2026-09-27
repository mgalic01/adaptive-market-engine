"""Every Binance host named in ``src/`` must be an exact entry in ``SECURITY.md``'s list.

The allowed-hosts line listed ``data-api.binance.vision`` and
``data-stream.binance.vision`` but not ``data.binance.vision``, the archive host
``backtest/dataset.py`` has always used. A security boundary that omits a host the code
actually contacts is worse than no list, because it reads as an exhaustive one.

What this checks, exactly:

- **Binance hostnames only**: ``binance.vision`` or ``binance.com`` or any subdomain of
  either, in any letter case, found anywhere in ``src/**/*.py`` (every Python file under
  ``src/``, recursively) text, comments and docstrings included.
  Any other host, another exchange's for example, is not looked for and passes unnoticed.
- **Exact membership** in the block between the ``allowed-hosts`` markers in
  ``SECURITY.md``, compared lowercased, since hostnames are case-insensitive. A host is
  not "listed" because it is a substring of a longer listed host (``api.binance.vision``
  inside ``data-api.binance.vision``), nor because the document mentions it elsewhere,
  such as in a warning. Each marker must appear exactly once, begin before end;
  otherwise the check raises rather than guessing where the list is.
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
# Hostnames are case-insensitive, so both sides are matched in any case and lowercased.
# The subdomain is optional: an apex host such as binance.com is as reachable as
# api.binance.com, and a pattern requiring a subdomain let it through unnoticed.
HOSTNAME = re.compile(r"\b(?:[a-z0-9][a-z0-9.-]*\.)?binance\.(?:vision|com)\b", re.I)
BEGIN = "<!-- allowed-hosts:begin"
END = "<!-- allowed-hosts:end -->"
LISTED = re.compile(r"^\s*- `([a-z0-9][a-z0-9.-]*)`", re.M | re.I)


def hosts_in(text: str) -> set[str]:
    return {host.lower() for host in HOSTNAME.findall(text)}


def hosts_in_source() -> set[str]:
    found: set[str] = set()
    for path in sorted(SOURCE.rglob("*.py")):
        found |= hosts_in(path.read_text(encoding="utf-8"))
    return found


def allowed_hosts(policy: str) -> set[str]:
    """The exact hosts listed between the markers; anything else in the document is prose."""
    if policy.count(BEGIN) != 1 or policy.count(END) != 1:
        raise ValueError("SECURITY.md must contain exactly one allowed-hosts begin/end marker pair")
    start, end = policy.index(BEGIN), policy.index(END)
    if end < start:
        raise ValueError("the allowed-hosts end marker comes before the begin marker")
    block = policy[start + len(BEGIN) : end]
    hosts = {host.lower() for host in LISTED.findall(block)}
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
    """Failure modes of earlier versions of this check, proven on synthetic text."""

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

    def test_an_uppercase_host_in_source_is_found_and_not_listed(self):
        # DNS names are case-insensitive: the runtime would reach this host.
        text = 'ORDER_URL = "https://API.BINANCE.COM/api/v3/order"\n'
        self.assertEqual(hosts_in(text), {"api.binance.com"})
        missing = undocumented(hosts_in(text), allowed_hosts(self.POLICY))
        self.assertEqual(missing, ["api.binance.com"])

    def test_letter_case_is_ignored_on_both_sides(self):
        text = 'HOST = "Data-API.Binance.Vision"\n'
        self.assertEqual(undocumented(hosts_in(text), allowed_hosts(self.POLICY)), [])
        upper_policy = self.POLICY.replace("`data-api.binance.vision`", "`DATA-API.BINANCE.VISION`")
        self.assertEqual(allowed_hosts(upper_policy), {"data-api.binance.vision"})

    def test_an_apex_host_is_detected_like_a_subdomain(self):
        # A pattern that required a subdomain let https://binance.com/... through
        # unnoticed, although it is as reachable as api.binance.com.
        for text, host in (
            ('URL = "https://binance.com/api/v3/order"\n', "binance.com"),
            ('URL = "https://binance.vision/data"\n', "binance.vision"),
            ('URL = "https://api.binance.com/o"\n', "api.binance.com"),
        ):
            with self.subTest(host=host):
                self.assertEqual(hosts_in(text), {host})
                self.assertEqual(undocumented(hosts_in(text), set()), [host])

    def test_a_lookalike_domain_is_not_mistaken_for_binance(self):
        for text in ('x = "notbinance.com"\n', 'x = "mybinance.vision"\n'):
            with self.subTest(text=text):
                self.assertEqual(hosts_in(text), set())

    def test_reversed_markers_fail_loudly(self):
        # With the end marker first, a naive split reads to the end of the file, so a
        # bullet outside any valid block would count as listed.
        policy = (
            "  <!-- allowed-hosts:end -->\n"
            "  <!-- allowed-hosts:begin -->\n"
            "  - `api.binance.com` - not inside a valid block\n"
        )
        with self.assertRaisesRegex(ValueError, "end marker comes before"):
            allowed_hosts(policy)
