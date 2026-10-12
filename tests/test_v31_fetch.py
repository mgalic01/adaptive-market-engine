"""Checksum-verified archive fetch for the V3.1 prepare job.

The network is blocked for every test in this file (the autouse fixture below), and the
host is a fake that serves bytes from a dict. Nothing here reaches data.binance.vision.
"""

import hashlib
import http.client
import json
import re
import socket
import sys
from pathlib import Path

import pytest

from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v31_fetch  # noqa: E402
from fetch_v3_data import V3Transport  # noqa: E402
from v31_fetch import LegacyTransport, entries_for, fetch_entries  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "https://data.binance.vision"


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def inventory_entry(content, *, kind="spot", symbol="BTCUSDT", month="2020-01", status="eligible"):
    """An inventory entry shaped like config/datasets/v3-20261009/inventory.manifest.json."""
    paths = {
        "spot": f"/data/spot/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip",
        "futures": f"/data/futures/um/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip",
        "funding": (
            f"/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
        ),
    }
    return {
        "kind": kind,
        "symbol": symbol,
        "month": month,
        "path": paths[kind],
        "sha256": sha(content),
        "status": status,
    }


def legacy_entry(content, *, symbol="ADAUSDT", month="2020-02", interval="1m"):
    """A legacy file shaped like the ones in full-range-2017-2024.manifest.json."""
    name = f"{symbol}-{interval}-{month}.zip"
    return {
        "symbol": symbol,
        "month": month,
        "interval": interval,
        "url": f"{PREFIX}/data/spot/monthly/klines/{symbol}/{interval}/{name}",
        "sha256": sha(content),
        "status": "ok",
    }


class FakeHost:
    """A host that serves bytes from a dict, 404 (None) for the rest, and records requests."""

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.requests = []

    def archive(self, path):
        self.requests.append(path)
        return self.files.get(path)


class ScriptedHost:
    """Answers each request with the next outcome: an exception is raised, bytes or None
    are returned."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def archive(self, path):
        self.requests.append(path)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def failed_by(cause):
    """The ValueError V3Transport raises from a transport error."""
    failure = ValueError("public data transport failed")
    failure.__cause__ = cause
    return failure


def never_sleep(seconds):
    pytest.fail(f"slept {seconds}s where no retry was expected")


def fetch(entries, cache, host, *, sleeps=None, logs=None):
    """Everything ``fetch_entries`` yields, with sleep and log recorded, never real."""
    sleeps = [] if sleeps is None else sleeps
    logs = [] if logs is None else logs
    return list(fetch_entries(entries, cache, transport=host, sleep=sleeps.append, log=logs.append))


def cached_file(cache, entry):
    return cache / entry["path"].lstrip("/")


# --- the network is blocked ---------------------------------------------------------------


def test_every_test_runs_with_the_network_blocked():
    # This test never asks for the fixture: it is autouse, so it is on for the whole file.
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("data.binance.vision", 443)
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("data.binance.vision", 443), timeout=1)
    with socket.socket() as sock, pytest.raises(NetworkBlocked):
        sock.connect(("127.0.0.1", 9))


def test_the_real_transports_stay_offline_and_their_failures_are_retried(tmp_path):
    # The two real transports, with no fake: each fails at the blocked socket, and the
    # failure each really raises is the one fetch_entries classifies as retryable.
    inventory = inventory_entry(b"x")
    legacy = legacy_entry(b"x")
    for entry, transport, error in (
        (inventory, V3Transport(), ValueError),
        (legacy, LegacyTransport(), FeedError),
    ):
        sleeps, logs = [], []
        with pytest.raises(error) as caught:
            fetch([entry], tmp_path, transport, sleeps=sleeps, logs=logs)
        assert isinstance(caught.value.__cause__, NetworkBlocked)
        assert sleeps == [1, 2, 4]
        assert len(logs) == 4
    assert not list(tmp_path.rglob("*"))


# --- verified bytes and the cache ---------------------------------------------------------


def test_verified_bytes_are_yielded_and_cached(tmp_path):
    content = b"synthetic spot archive"
    entry = inventory_entry(content)
    host = FakeHost({entry["path"]: content})

    fetched = fetch([entry], tmp_path, host)

    assert fetched == [(entry, content)]
    assert fetched[0][0] is entry
    assert host.requests == [entry["path"]]
    target = tmp_path / "data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2020-01.zip"
    assert target.read_bytes() == content
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [target]

    # A second pass is served from the cache: the host is not asked.
    offline = FakeHost()
    assert fetch([entry], tmp_path, offline) == [(entry, content)]
    assert offline.requests == []


def test_a_cached_file_with_a_wrong_hash_is_refetched_not_trusted(tmp_path):
    content = b"the real archive"
    entry = inventory_entry(content)
    target = cached_file(tmp_path, entry)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"a truncated download")
    host = FakeHost({entry["path"]: content})
    logs = []

    assert fetch([entry], tmp_path, host, logs=logs) == [(entry, content)]

    assert host.requests == [entry["path"]]
    assert target.read_bytes() == content
    # The replacement was atomic: no temporary file is left beside it.
    assert [p.name for p in target.parent.iterdir()] == [target.name]
    assert len(logs) == 1
    assert entry["path"] in logs[0]


def test_a_failed_replacement_leaves_the_old_file_and_no_temp_file(tmp_path, monkeypatch):
    content = b"the real archive"
    entry = inventory_entry(content)
    target = cached_file(tmp_path, entry)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"stale")

    def disk_full(source, destination):
        raise OSError("the replacement failed")

    monkeypatch.setattr(v31_fetch.os, "replace", disk_full)

    with pytest.raises(OSError, match="replacement failed"):
        fetch([entry], tmp_path, FakeHost({entry["path"]: content}))

    # The file is only ever replaced whole, never written in place.
    assert target.read_bytes() == b"stale"
    assert [p.name for p in target.parent.iterdir()] == [target.name]


def test_a_hash_mismatch_from_the_host_stops_before_decode(tmp_path):
    good, tampered = b"the pinned archive", b"some other bytes"
    entry = inventory_entry(good)
    host = FakeHost({entry["path"]: tampered})
    stream = fetch_entries([entry], tmp_path, transport=host, sleep=never_sleep, log=print)

    with pytest.raises(ValueError) as caught:
        next(stream)

    message = str(caught.value)
    assert entry["path"] in message
    assert sha(good) in message
    assert sha(tampered) in message
    assert host.requests == [entry["path"]]  # a mismatch is never retried
    assert not list(tmp_path.rglob("*"))  # nothing was written


def test_a_hash_mismatch_deletes_no_file_and_leaves_the_cache_alone(tmp_path):
    entry = inventory_entry(b"the pinned archive")
    target = cached_file(tmp_path, entry)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"stale")
    host = FakeHost({entry["path"]: b"also wrong"})

    with pytest.raises(ValueError, match="sha256"):
        fetch([entry], tmp_path, host)

    assert target.read_bytes() == b"stale"
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [target]


def test_entries_are_fetched_one_at_a_time(tmp_path):
    first, second = b"first month", b"second month"
    entries = [
        inventory_entry(first, month="2020-01"),
        inventory_entry(second, month="2020-02"),
    ]
    host = FakeHost({entries[0]["path"]: first, entries[1]["path"]: b"tampered"})

    stream = fetch_entries(entries, tmp_path, transport=host, sleep=never_sleep, log=print)
    assert host.requests == []  # nothing happens until the first entry is asked for
    assert next(stream) == (entries[0], first)
    assert host.requests == [entries[0]["path"]]
    with pytest.raises(ValueError, match="2020-02"):
        next(stream)

    # The failure on the second entry did not discard the first one's verified work.
    assert cached_file(tmp_path, entries[0]).read_bytes() == first
    assert not cached_file(tmp_path, entries[1]).exists()


def test_a_host_404_is_an_error_naming_the_path_and_is_not_retried(tmp_path):
    entry = inventory_entry(b"listed but absent")
    host = FakeHost()  # serves nothing: every request is a 404

    with pytest.raises(ValueError, match=re.escape(entry["path"])):
        fetch([entry], tmp_path, host)

    assert host.requests == [entry["path"]]
    assert not list(tmp_path.rglob("*"))


def test_the_legacy_entry_is_fetched_by_its_url_path(tmp_path):
    content = b"a legacy minute month"
    entry = legacy_entry(content)
    path = "/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip"
    host = FakeHost({path: content})

    assert fetch([entry], tmp_path, host) == [(entry, content)]

    assert host.requests == [path]
    assert (tmp_path / path.lstrip("/")).read_bytes() == content


def test_legacy_entries_go_through_the_adapter_to_archive_get(tmp_path, monkeypatch):
    content = b"a legacy minute month"
    entry = legacy_entry(content)
    host = FakeHost({"/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip": content})
    monkeypatch.setattr(v31_fetch, "archive_get", host.archive)

    assert fetch([entry], tmp_path, LegacyTransport()) == [(entry, content)]
    assert host.requests == ["/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip"]


def test_the_legacy_adapter_keeps_archive_gets_own_guards(tmp_path):
    # archive_get refuses a month in the reserved window before it opens a connection.
    with pytest.raises(DataError, match="reserved"):
        LegacyTransport().archive("/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2025-01.zip")
    with pytest.raises(DataError, match="not a monthly"):
        LegacyTransport().archive("/data/spot/monthly/klines/ADAUSDT/1h/../1m/x.zip")


def test_the_planned_paths_are_the_only_ones_requested(tmp_path):
    contents = [b"spot", b"funding", b"minutes"]
    entries = [
        inventory_entry(contents[0], kind="spot"),
        inventory_entry(contents[1], kind="funding"),
        legacy_entry(contents[2]),
    ]
    paths = [
        entries[0]["path"],
        entries[1]["path"],
        "/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip",
    ]
    host = FakeHost(dict(zip(paths, contents, strict=True)))

    fetch(entries, tmp_path, host)

    assert host.requests == paths


# --- refusals before any request ----------------------------------------------------------


def renamed(entry, old, new):
    return {**entry, "path": entry["path"].replace(old, new)}


SEALED = [
    pytest.param(inventory_entry(b"x", month="2025-01"), id="inventory-2025-01"),
    pytest.param(inventory_entry(b"x", month="2026-10"), id="inventory-2026-10"),
    pytest.param(legacy_entry(b"x", month="2025-03"), id="legacy-2025-03"),
    pytest.param(
        {**inventory_entry(b"x", month="2025-01"), "month": "2024-12"},
        id="path-month-only",
    ),
    pytest.param(
        {**inventory_entry(b"x", month="2024-12"), "month": "2025-01"},
        id="entry-month-only",
    ),
    pytest.param(
        {
            **legacy_entry(b"x", month="2024-12"),
            "url": legacy_entry(b"x", month="2025-01")["url"],
        },
        id="legacy-url-month-only",
    ),
]


@pytest.mark.parametrize("sealed", SEALED)
def test_2025_entries_are_refused_before_any_request(tmp_path, sealed):
    host = FakeHost()
    good = inventory_entry(b"fine", month="2024-12")
    host.files[good["path"]] = b"fine"

    # Even behind an entry that would fetch fine: the plan is checked as a whole first.
    for entries in ([sealed], [good, sealed]):
        with pytest.raises(ValueError, match="reserved boundary"):
            fetch(entries, tmp_path, host)

    assert host.requests == []
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(
            "http://data.binance.vision/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip",
            id="plain-http",
        ),
        pytest.param(
            "https://example.org/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip",
            id="other-host",
        ),
        pytest.param(
            "https://data.binance.vision.example.org/data/spot/monthly/klines/ADAUSDT/1m/"
            "ADAUSDT-1m-2020-02.zip",
            id="longer-host",
        ),
        pytest.param(
            "https://data.binance.vision@example.org/data/spot/monthly/klines/ADAUSDT/1m/"
            "ADAUSDT-1m-2020-02.zip",
            id="userinfo",
        ),
        pytest.param(
            "https://data.binance.vision:8443/data/spot/monthly/klines/ADAUSDT/1m/"
            "ADAUSDT-1m-2020-02.zip",
            id="port",
        ),
        pytest.param(
            "HTTPS://DATA.BINANCE.VISION/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip",
            id="not-the-exact-prefix",
        ),
        pytest.param(
            "/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-02.zip",
            id="no-host-at-all",
        ),
    ],
)
def test_a_legacy_url_on_another_host_is_refused_before_any_request(tmp_path, url):
    entry = {**legacy_entry(b"x"), "url": url}
    host = FakeHost()

    with pytest.raises(ValueError, match="data.binance.vision"):
        fetch([entry], tmp_path, host)

    assert host.requests == []
    assert not list(tmp_path.rglob("*"))


BASE = "/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2020-01.zip"


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(BASE.replace("/1h/", "/1h/../../../../"), id="traversal"),
        pytest.param("/data/spot/monthly/klines/BTCUSDT/./1h/BTCUSDT-1h-2020-01.zip", id="dot"),
        pytest.param(BASE.lstrip("/"), id="no-leading-slash"),
        pytest.param("//" + BASE.lstrip("/"), id="double-slash"),
        pytest.param(BASE + "?x=1", id="query"),
        pytest.param(BASE.replace("/1h/", "\\1h\\"), id="backslash"),
        pytest.param(BASE + ".CHECKSUM", id="checksum-path"),
        pytest.param("/etc/BTCUSDT-1h-2020-01.zip", id="outside-data"),
        pytest.param("/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2020-1.zip", id="month"),
        pytest.param("", id="empty"),
        pytest.param(None, id="none"),
        pytest.param(5, id="not-a-string"),
    ],
)
def test_a_path_outside_the_planned_shape_is_refused_before_any_request(tmp_path, path):
    entry = {**inventory_entry(b"x"), "path": path}
    host = FakeHost()

    with pytest.raises(ValueError):
        fetch([entry], tmp_path, host)

    assert host.requests == []
    assert not list(tmp_path.rglob("*"))


def test_an_entry_whose_path_month_differs_from_its_month_is_refused(tmp_path):
    entry = {**inventory_entry(b"x", month="2020-01"), "month": "2020-02"}
    host = FakeHost()

    with pytest.raises(ValueError, match="2020-02"):
        fetch([entry], tmp_path, host)

    assert host.requests == []


def test_an_entry_names_exactly_one_of_path_and_url(tmp_path):
    both = {**inventory_entry(b"x"), "url": legacy_entry(b"x")["url"]}
    neither = {k: v for k, v in inventory_entry(b"x").items() if k != "path"}
    host = FakeHost()

    for entry in (both, neither):
        with pytest.raises(ValueError, match="path"):
            fetch([entry], tmp_path, host)

    assert host.requests == []


@pytest.mark.parametrize(
    "unpinned",
    [
        pytest.param(
            {**inventory_entry(b"x"), "sha256": None, "status": "missing"},
            id="inventory-missing",
        ),
        pytest.param(
            {k: v for k, v in legacy_entry(b"x").items() if k != "sha256"} | {"status": "missing"},
            id="legacy-missing-without-sha256",
        ),
        pytest.param({**inventory_entry(b"x"), "status": "missing"}, id="missing-with-sha256"),
    ],
)
def test_an_entry_with_no_sha256_is_refused_naming_it(tmp_path, unpinned):
    good = inventory_entry(b"fine", month="2020-05")
    host = FakeHost({good["path"]: b"fine"})
    name = unpinned.get("path") or unpinned["url"]

    with pytest.raises(ValueError, match=re.escape(name)):
        fetch([good, unpinned], tmp_path, host)

    assert host.requests == []


@pytest.mark.parametrize(
    "digest",
    ["abc", sha(b"x").upper(), sha(b"x")[:-1], sha(b"x") + "0", 12, ""],
)
def test_a_malformed_sha256_is_refused_before_any_request(tmp_path, digest):
    entry = {**inventory_entry(b"x"), "sha256": digest}
    host = FakeHost({entry["path"]: b"x"})

    with pytest.raises(ValueError, match="sha256"):
        fetch([entry], tmp_path, host)

    assert host.requests == []


# --- bounded retries of transport failures ------------------------------------------------

RETRIED = {
    "connection-error": lambda: failed_by(ConnectionResetError("reset by peer")),
    "timeout": lambda: failed_by(TimeoutError("timed out")),
    "http-exception": lambda: failed_by(http.client.RemoteDisconnected("closed")),
    "http-503": lambda: ValueError("public data returned HTTP 503; redirects forbidden"),
    "legacy-transport": lambda: FeedError("archive transport failed for /data/x.zip"),
    "legacy-http-502": lambda: FeedError("archive returned HTTP 502 for /data/x.zip"),
}

NOT_RETRIED = {
    "http-403": ValueError("public data returned HTTP 403; redirects forbidden"),
    "redirect": ValueError("public data returned HTTP 301; redirects forbidden"),
    "size-limit": ValueError(
        "public response exceeded size limit of 67108864 bytes for "
        "https://data.binance.vision/data/x.zip; complete response size unknown"
    ),
    "path-guard": ValueError("noncanonical archive path"),
    "unrelated-cause": failed_by(KeyError("not a transport error")),
    "legacy-http-403": FeedError("archive returned HTTP 403 for /data/x.zip"),
    "legacy-http-429": FeedError("archive returned HTTP 429 for /data/x.zip"),
    "legacy-size-limit": FeedError("archive object exceeded the size limit"),
    "legacy-path-guard": DataError("not a monthly spot kline archive or USDT-M funding path"),
    "legacy-window": DataError("2025-01 is in the reserved window; audits stop at 2024-12"),
}


@pytest.mark.parametrize("failure", RETRIED.values(), ids=RETRIED.keys())
def test_a_transport_failure_is_retried_with_backoff_and_logged(tmp_path, failure):
    content = b"served on the third attempt"
    entry = inventory_entry(content)
    host = ScriptedHost([failure(), failure(), content])
    sleeps, logs = [], []

    assert fetch([entry], tmp_path, host, sleeps=sleeps, logs=logs) == [(entry, content)]

    assert host.requests == [entry["path"]] * 3
    assert sleeps == [1, 2]
    assert len(logs) == 2
    assert logs[0].startswith(f"RETRY attempt 1 of 4 for {entry['path']}")
    assert logs[1].startswith(f"RETRY attempt 2 of 4 for {entry['path']}")
    assert cached_file(tmp_path, entry).read_bytes() == content


def test_the_fourth_failed_attempt_is_the_last(tmp_path):
    entry = inventory_entry(b"never served")
    failures = [failed_by(ConnectionResetError(f"reset {i}")) for i in range(1, 6)]
    host = ScriptedHost(failures)
    sleeps, logs = [], []

    with pytest.raises(ValueError) as caught:
        fetch([entry], tmp_path, host, sleeps=sleeps, logs=logs)

    assert caught.value is failures[3]
    assert len(host.requests) == 4
    assert sleeps == [1, 2, 4]
    assert [line.split(":")[0] for line in logs] == [
        f"RETRY attempt {i} of 4 for {entry['path']}" for i in range(1, 5)
    ]
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("failure", NOT_RETRIED.values(), ids=NOT_RETRIED.keys())
def test_nothing_else_is_ever_retried(tmp_path, failure):
    entry = inventory_entry(b"x")
    host = ScriptedHost([failure, b"x"])
    sleeps, logs = [], []

    with pytest.raises(type(failure)) as caught:
        fetch([entry], tmp_path, host, sleeps=sleeps, logs=logs)

    assert caught.value is failure
    assert len(host.requests) == 1
    assert sleeps == []
    assert logs == []


def test_retried_bytes_are_still_verified_and_a_mismatch_is_not_retried(tmp_path):
    entry = inventory_entry(b"the pinned archive")
    host = ScriptedHost([failed_by(OSError("reset")), b"wrong bytes", b"the pinned archive"])
    sleeps = []

    with pytest.raises(ValueError, match="sha256"):
        fetch([entry], tmp_path, host, sleeps=sleeps)

    assert len(host.requests) == 2  # the retry fetched wrong bytes; no third attempt
    assert sleeps == [1]
    assert not list(tmp_path.rglob("*"))


def test_each_entry_gets_its_own_four_attempts(tmp_path):
    first, second = b"one", b"two"
    entries = [inventory_entry(first, month="2020-01"), inventory_entry(second, month="2020-02")]
    host = ScriptedHost(
        [failed_by(OSError("a"))] * 3 + [first] + [failed_by(OSError("b"))] * 3 + [second]
    )

    assert fetch(entries, tmp_path, host) == [(entries[0], first), (entries[1], second)]
    assert len(host.requests) == 8


# --- entries_for --------------------------------------------------------------------------


def inventory_manifest():
    entries = [
        inventory_entry(b"s1", kind="spot", month="2020-01"),
        inventory_entry(b"s2", kind="spot", month="2020-02"),
        inventory_entry(b"s3", kind="spot", month="2020-03"),
        inventory_entry(b"s4", kind="spot", month="2020-04"),
        inventory_entry(b"f2", kind="funding", month="2020-02"),
        inventory_entry(b"f3", kind="funding", month="2020-03"),
        inventory_entry(b"u2", kind="futures", month="2020-02"),
        inventory_entry(b"e2", kind="spot", symbol="ETHUSDT", month="2020-02"),
        {
            **inventory_entry(b"x", kind="spot", symbol="ETHUSDT", month="2020-03"),
            "sha256": None,
            "status": "missing",
        },
        inventory_entry(b"a2", kind="spot", symbol="ADAUSDT", month="2020-02"),
    ]
    return {"schema_version": 1, "entries": entries}


def keys(entries):
    return [(e["symbol"], e.get("kind") or e.get("interval"), e["month"]) for e in entries]


def test_entries_for_selects_inventory_entries_by_kind_symbol_and_inclusive_months():
    manifest = inventory_manifest()

    selected = entries_for(
        manifest,
        symbols=("ETHUSDT", "BTCUSDT"),
        kinds=("spot", "funding"),
        start_month="2020-02",
        end_month="2020-03",
    )

    assert keys(selected) == [
        ("BTCUSDT", "funding", "2020-02"),
        ("BTCUSDT", "funding", "2020-03"),
        ("BTCUSDT", "spot", "2020-02"),
        ("BTCUSDT", "spot", "2020-03"),
        ("ETHUSDT", "spot", "2020-02"),
        ("ETHUSDT", "spot", "2020-03"),
    ]
    # Missing entries come back too: the caller decides, and fetch_entries refuses them.
    assert [e["status"] for e in selected][-1] == "missing"


def test_entries_for_order_does_not_depend_on_the_manifest_order():
    manifest = inventory_manifest()
    reversed_manifest = {**manifest, "entries": manifest["entries"][::-1]}
    arguments = {
        "symbols": ("BTCUSDT", "ETHUSDT", "ADAUSDT"),
        "kinds": ("futures", "spot", "funding"),
        "start_month": "2020-01",
        "end_month": "2020-12",
    }

    forward = entries_for(manifest, **arguments)

    assert forward == entries_for(reversed_manifest, **arguments)
    assert keys(forward) == sorted(keys(forward))
    assert len(forward) == len(manifest["entries"])


def test_entries_for_returns_copies_the_caller_may_change():
    manifest = inventory_manifest()

    selected = entries_for(
        manifest,
        symbols=("BTCUSDT",),
        kinds=("futures",),
        start_month="2020-02",
        end_month="2020-02",
    )
    selected[0]["sha256"] = "changed"

    assert type(selected[0]) is dict
    assert all(e["sha256"] != "changed" for e in manifest["entries"])


def legacy_manifest():
    files = [
        legacy_entry(b"a", symbol="BTCUSDT", month="2019-02", interval="1m"),
        legacy_entry(b"b", symbol="BTCUSDT", month="2019-01", interval="1m"),
        legacy_entry(b"c", symbol="BTCUSDT", month="2019-01", interval="1h"),
        legacy_entry(b"d", symbol="BTCUSDT", month="2019-01", interval="1d"),
        legacy_entry(b"e", symbol="ADAUSDT", month="2019-03", interval="1m"),
        legacy_entry(b"f", symbol="ADAUSDT", month="2019-04", interval="1m"),
        {
            "symbol": "BTCUSDT",
            "month": "2020-01",
            "kind": "fundingRate",
            "url": (
                f"{PREFIX}/data/futures/um/monthly/fundingRate/BTCUSDT/"
                "BTCUSDT-fundingRate-2020-01.zip"
            ),
            "sha256": sha(b"funding"),
            "status": "ok",
        },
    ]
    return {"schema": 1, "files": files}


def test_entries_for_selects_legacy_files_by_interval():
    selected = entries_for(
        legacy_manifest(),
        symbols=("BTCUSDT", "ADAUSDT"),
        kinds=("1m",),
        start_month="2019-01",
        end_month="2019-03",
    )

    assert keys(selected) == [
        ("ADAUSDT", "1m", "2019-03"),
        ("BTCUSDT", "1m", "2019-01"),
        ("BTCUSDT", "1m", "2019-02"),
    ]
    assert all(e["url"].startswith(PREFIX) for e in selected)


def test_entries_for_never_selects_a_legacy_file_that_has_no_interval_unless_it_is_funding():
    manifest = legacy_manifest()
    # No interval and no fundingRate url: neither a kline nor a funding file.
    stray = legacy_entry(b"g", symbol="BTCUSDT")
    del stray["interval"]
    manifest["files"].append(stray)

    klines = entries_for(
        manifest,
        symbols=("BTCUSDT",),
        kinds=("1m", "1h", "1d"),
        start_month="2019-01",
        end_month="2024-12",
    )
    funding = entries_for(
        manifest,
        symbols=("BTCUSDT",),
        kinds=("fundingRate",),
        start_month="2019-01",
        end_month="2024-12",
    )

    assert all("interval" in e for e in klines)
    assert stray not in klines and stray not in funding
    assert [e["url"] for e in funding] == [manifest["files"][6]["url"]]


def test_entries_for_selects_legacy_funding_files(tmp_path):
    # A legacy funding file has no interval; its url names a fundingRate archive.
    manifest = legacy_manifest()
    manifest["files"].append(
        {
            **manifest["files"][6],
            "month": "2019-12",
            "url": manifest["files"][6]["url"].replace("2020-01", "2019-12"),
        }
    )

    selected = entries_for(
        manifest,
        symbols=("BTCUSDT",),
        kinds=("fundingRate",),
        start_month="2020-01",
        end_month="2024-12",
    )
    both = entries_for(
        manifest,
        symbols=("BTCUSDT", "ADAUSDT"),
        kinds=("1m", "fundingRate"),
        start_month="2019-02",
        end_month="2020-01",
    )

    assert keys(selected) == [("BTCUSDT", "fundingRate", "2020-01")]
    assert selected[0] == manifest["files"][6] and selected[0] is not manifest["files"][6]
    # Each file comes back under its own kind, in (symbol, kind, month) order.
    assert keys(both) == [
        ("ADAUSDT", "1m", "2019-03"),
        ("ADAUSDT", "1m", "2019-04"),
        ("BTCUSDT", "1m", "2019-02"),
        ("BTCUSDT", "fundingRate", "2019-12"),
        ("BTCUSDT", "fundingRate", "2020-01"),
    ]

    # The committed full-range manifest: BTCUSDT's 60 funding archives, fetched by their
    # url paths from the fake host (the network stays blocked).
    committed_funding = entries_for(
        committed("config/datasets/full-range-2017-2024.manifest.json"),
        symbols=("BTCUSDT", "ETHUSDT"),
        kinds=("fundingRate",),
        start_month="2018-06",
        end_month="2024-12",
    )
    assert len(committed_funding) == 60
    assert [e["month"] for e in committed_funding][::59] == ["2020-01", "2024-12"]
    expected = [e["url"].removeprefix(PREFIX) for e in committed_funding]
    assert all(
        path.startswith("/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-")
        for path in expected
    )
    served = {path: path.encode() for path in expected}
    pinned = [
        {**e, "sha256": sha(served[p])} for e, p in zip(committed_funding, expected, strict=True)
    ]
    host = FakeHost(served)

    fetch(pinned, tmp_path, host)

    assert host.requests == expected


@pytest.mark.parametrize("end_month", ["2025-01", "2025-02", "2026-10"])
def test_entries_for_refuses_an_end_month_in_the_reserved_window(end_month):
    with pytest.raises(ValueError, match="reserved boundary"):
        entries_for(
            inventory_manifest(),
            symbols=("BTCUSDT",),
            kinds=("spot",),
            start_month="2020-01",
            end_month=end_month,
        )


@pytest.mark.parametrize("month", ["2020-1", "2020-13", "2020", "20-01", "", None, 202001])
def test_entries_for_refuses_a_month_that_is_not_yyyy_mm(month):
    for arguments in ({"start_month": month}, {"end_month": month}):
        merged = {"start_month": "2020-01", "end_month": "2020-12"} | arguments
        with pytest.raises(ValueError, match="YYYY-MM"):
            entries_for(inventory_manifest(), symbols=("BTCUSDT",), kinds=("spot",), **merged)


def test_entries_for_accepts_the_last_development_month():
    manifest = {"entries": [inventory_entry(b"x", month="2024-12")]}

    selected = entries_for(
        manifest, symbols=("BTCUSDT",), kinds=("spot",), start_month="2024-12", end_month="2024-12"
    )

    assert keys(selected) == [("BTCUSDT", "spot", "2024-12")]


def test_entries_for_gives_nothing_when_the_range_is_backwards():
    assert (
        entries_for(
            inventory_manifest(),
            symbols=("BTCUSDT",),
            kinds=("spot",),
            start_month="2020-03",
            end_month="2020-01",
        )
        == []
    )


@pytest.mark.parametrize("names", [{"symbols": "BTCUSDT"}, {"kinds": "spot"}])
def test_entries_for_refuses_one_string_where_a_collection_of_names_belongs(names):
    arguments = {"symbols": ("BTCUSDT",), "kinds": ("spot",)} | names

    with pytest.raises(ValueError, match="collections"):
        entries_for(inventory_manifest(), start_month="2020-01", end_month="2020-02", **arguments)


@pytest.mark.parametrize(
    "manifest",
    [{}, {"entries": [], "files": []}, {"entries": "no"}, {"files": {"a": 1}}],
    ids=["neither", "both", "entries-not-a-list", "files-not-a-list"],
)
def test_entries_for_needs_exactly_one_list_of_entries(manifest):
    with pytest.raises(ValueError, match="entries"):
        entries_for(
            manifest,
            symbols=("BTCUSDT",),
            kinds=("spot",),
            start_month="2020-01",
            end_month="2020-02",
        )


# --- the committed manifests --------------------------------------------------------------


def committed(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_the_committed_inventory_gives_entries_that_fetch_by_their_own_path(tmp_path):
    manifest = committed("config/datasets/v3-20261009/inventory.manifest.json")

    selected = entries_for(
        manifest,
        symbols=("BTCUSDT",),
        kinds=("spot", "funding"),
        start_month="2020-01",
        end_month="2020-12",
    )

    assert len(selected) == 24
    assert {e["kind"] for e in selected} == {"spot", "funding"}
    # Substitute the fake host's hashes for the real ones: only the requested paths matter.
    served = {e["path"]: e["path"].encode() for e in selected}
    pinned = [{**e, "sha256": sha(served[e["path"]])} for e in selected]
    host = FakeHost(served)

    fetch(pinned, tmp_path, host)

    assert host.requests == [e["path"] for e in selected]


def test_the_committed_legacy_manifest_gives_entries_that_fetch_by_their_url_path(tmp_path):
    manifest = committed("config/datasets/full-range-2017-2024.manifest.json")

    selected = entries_for(
        manifest,
        symbols=("BTCUSDT",),
        kinds=("1m",),
        start_month="2019-01",
        end_month="2019-03",
    )

    assert [e["month"] for e in selected] == ["2019-01", "2019-02", "2019-03"]
    expected = [e["url"].removeprefix(PREFIX) for e in selected]
    assert all(path.startswith("/data/spot/monthly/klines/BTCUSDT/1m/") for path in expected)
    served = {path: path.encode() for path in expected}
    pinned = [{**e, "sha256": sha(served[p])} for e, p in zip(selected, expected, strict=True)]
    host = FakeHost(served)

    fetch(pinned, tmp_path, host)

    assert host.requests == expected
