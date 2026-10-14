"""The committed V3.1 prepare config, ``config/v3_1_prepare.json`` (Ruling P1).

It must be exactly the owner's plan (``owner_plan.OWNER_PLAN``), pin each file it names by
the SHA-256 of the committed bytes, and name manifests that list every archive month
prepare requests for every window coin. The coverage tests run the driver's own planning
on the committed file: ``plan_prepare`` (every pin, V3's registered inventory, the
snapshots that inventory records, an ok 1m archive for every minute month of every window
coin), then ``build_coin`` for every window coin with the archive decoders stood in by
each manifest entry's own status. So ``packs.build_coin_inputs`` refuses any spot, futures
or funding month the pinned inventory does not list, and ``venues.venue_rules`` any coin
a pinned snapshot lacks: a month missing from the committed manifests fails here, not in
the GitHub run.

Only committed files are read: the config, the files it pins and, at the head, the trial
register and V3's run configuration. No archive is read, and the network is blocked.
"""

import hashlib
import json
import socket
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.driver.decode import DecodedV31Month
from crypto_grid_bot.combined.driver.owner_plan import OWNER_PLAN, owner_plan_errors
from crypto_grid_bot.combined.driver.packs import CoinInputs
from crypto_grid_bot.combined.driver.registration import (
    PREPARE_SCHEMA,
    PrepareConfig,
    load_prepare_config,
)
from crypto_grid_bot.combined.driver.run_baselines import MINUTE_MANIFEST_PATH, MINUTE_PAIRS

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import v31_driver  # noqa: E402

INVENTORY = "config/datasets/v3-20261009/inventory.manifest.json"
# What prepare reads, and from which committed manifest (scripts/v31_driver.py):
# - V3's registered inventory (``v3_registered_inputs``: the spec-v3 completion pins it):
#   every window coin's spot, futures and funding months;
# - the legacy dataset (``plan_prepare`` requires ``MINUTE_MANIFEST_PATH``): the minute
#   baselines' dataset, and BTC, ETH and XRP's 1m months;
# - the V3.1 minute bars, 2021-06 to 2024-12 and 2020-02 to 2021-05: the other coins' 1m
#   months (``minute_sources``), W1's seven and W0's five.
MANIFESTS = (
    MINUTE_MANIFEST_PATH,
    "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.manifest.json",
    "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.manifest.json",
    INVENTORY,
)
# The filter snapshots the inventory records (``plan_prepare`` checks they are its own).
SNAPSHOTS = {
    "spot": "config/datasets/v3-20261009/snapshots/spot.json",
    "futures": "config/datasets/v3-20261009/snapshots/futures.json",
}


def block_network(patch: pytest.MonkeyPatch) -> None:
    """Make every name lookup and every connection raise."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("the network is blocked in tests")

    patch.setattr(socket, "getaddrinfo", refuse)
    patch.setattr(socket, "create_connection", refuse)
    patch.setattr(socket.socket, "connect", refuse)
    patch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture(scope="module", autouse=True)
def module_network_blocked() -> Iterator[None]:
    """The network is blocked for the whole module, its module-scoped fixtures included."""
    with pytest.MonkeyPatch.context() as patch:
        block_network(patch)
        yield


def sha256_of(path: str) -> str:
    return hashlib.sha256((REPO / path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def prepare() -> PrepareConfig:
    return load_prepare_config(REPO / v31_driver.PREPARE_CONFIG)


@pytest.fixture(scope="module")
def plan(prepare: PrepareConfig) -> v31_driver.Plan:
    """The driver's plan of the committed config, from the repository's pinned files."""
    return v31_driver.plan_prepare(REPO, v31_driver.head_commit(REPO), prepare)


def test_the_prepare_config_is_the_owners_plan(prepare: PrepareConfig) -> None:
    assert owner_plan_errors(prepare) == []
    for mode in ("prepare-only", "timing"):  # the real modes that read it unregistered
        v31_driver.plan_gate(mode, prepare)
    assert [(w.id, w.start_ms, w.end_ms, w.symbols) for w in prepare.windows] == [
        (w.id, w.start_ms, w.end_ms, tuple(sorted(w.symbols))) for w in OWNER_PLAN.windows
    ]


def test_the_file_is_the_canonical_json_of_the_plan_and_its_pins() -> None:
    """Sorted keys, no spaces, ASCII, one newline (as the run-manifest is written): the
    owner's windows in plan order, coins sorted, and each pinned file by the SHA-256 of
    its bytes. Rebuilding it from the plan and the files gives the same bytes."""
    document = {
        "schema": PREPARE_SCHEMA,
        "windows": [
            {"id": w.id, "start_ms": w.start_ms, "end_ms": w.end_ms, "symbols": sorted(w.symbols)}
            for w in OWNER_PLAN.windows
        ],
        "data_manifests": {path: sha256_of(path) for path in MANIFESTS},
        "filter_snapshots": {
            market: {"path": path, "sha256": sha256_of(path)} for market, path in SNAPSHOTS.items()
        },
    }
    expected = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert (REPO / v31_driver.PREPARE_CONFIG).read_bytes() == (expected + "\n").encode("ascii")


def test_every_pinned_file_hashes_to_its_pin_in_every_checkout(prepare: PrepareConfig) -> None:
    """Each pin is the SHA-256 of the working tree's bytes, and .gitattributes keeps those
    bytes the blob's whatever core.autocrlf says (LF, or no text conversion at all)."""
    pins = (*prepare.data_manifests, prepare.spot_filters, prepare.futures_filters)
    assert sorted(pin.path for pin in pins) == sorted((*MANIFESTS, *SNAPSHOTS.values()))
    for pin in pins:
        assert sha256_of(pin.path) == pin.sha256, pin.path
        attributes = subprocess.run(
            ["git", "-C", str(REPO), "check-attr", "text", "eol", "--", pin.path],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.splitlines()
        assert attributes in (
            [f"{pin.path}: text: set", f"{pin.path}: eol: lf"],
            [f"{pin.path}: text: unset", f"{pin.path}: eol: unspecified"],
        ), attributes


def test_prepare_plans_every_minute_month_from_the_committed_manifests(
    prepare: PrepareConfig, plan: v31_driver.Plan
) -> None:
    """``plan_prepare`` passes on the committed files with no network: the pins, V3's
    registered inventory and its snapshots, the legacy dataset pinned, and one ok 1m
    archive for every minute month (from 15 minutes before the start) of every window
    coin; BTC, ETH and XRP from the legacy dataset, the others from the V3.1 minute bars."""
    assert (plan.inventory_path, plan.inventory_sha) == (INVENTORY, sha256_of(INVENTORY))
    wanted = {
        (symbol, month)
        for window in prepare.windows
        for symbol in window.symbols
        for month in v31_driver.window_months(window).minutes
    }
    assert set(plan.minute_sources) == wanted
    for (symbol, month), (entry, family) in plan.minute_sources.items():
        assert (entry["symbol"], entry["month"], entry["interval"]) == (symbol, month, "1m")
        assert family == ("legacy" if symbol in MINUTE_PAIRS else "minutes"), (symbol, month)
    first = {w.id: v31_driver.window_months(w).minutes[0] for w in prepare.windows}
    assert first == {"w1": "2021-06", "w0": "2020-02"}  # the 15 minutes before each start


def test_every_month_prepare_requests_is_listed(
    prepare: PrepareConfig,
    plan: v31_driver.Plan,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``build_coin`` for every window coin, each archive month stood in by its manifest
    entry (its kind, coin, month and status, no rows): the packs' own rules then refuse an
    absent spot month from the coin's history start (365 days back, or after its last
    excluded month), an excluded one in that range, an absent futures or funding month
    from the month before the start, or an excluded futures month inside the window. Every
    coin has spot and futures rules in the pinned snapshots, and every minute month the
    flow schedule reads is requested from the planned source."""
    requested: dict[tuple[str, str], list[str]] = {}

    def decode_month(entry: Mapping[str, Any], content: bytes) -> DecodedV31Month:
        kind, symbol, month = entry["kind"], entry["symbol"], entry["month"]
        requested.setdefault((symbol, kind), []).append(month)
        return DecodedV31Month(kind, symbol, month, entry["status"])

    def decode_minute_month(entry: Mapping[str, Any], content: bytes) -> Iterator[Kline]:
        requested.setdefault((entry["symbol"], "1m"), []).append(entry["month"])
        return iter(())

    monkeypatch.setattr(v31_driver, "decode_month", decode_month)
    monkeypatch.setattr(v31_driver, "decode_minute_month", decode_minute_month)
    monkeypatch.setattr(v31_driver, "_cached", lambda root, entry: b"")
    for window in prepare.windows:
        months = v31_driver.window_months(window)
        for symbol in window.symbols:
            requested.clear()
            coin = v31_driver.build_coin(plan, tmp_path, window, symbol)
            assert isinstance(coin, CoinInputs) and coin.futures_rules is not None
            assert requested[(symbol, "1m")] == list(months.minutes), (window.id, symbol)
            assert requested[(symbol, "futures")] == list(months.futures), (window.id, symbol)
            assert requested[(symbol, "funding")] == list(months.futures), (window.id, symbol)
