"""V4 data step: verified archive fetch, the URL allowlist, retries and pinned re-fetch.

The network is blocked for every test in this file (the autouse fixture below). Fetches go
through fake transports that serve bytes from a dict or replay a script of outcomes; the one
real transport, ``HttpTransport``, is only ever driven up to the blocked socket.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import socket
import urllib.error
import urllib.request
import urllib.response
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from crypto_grid_bot.v4.data import archives
from crypto_grid_bot.v4.data.archives import (
    ATTEMPTS,
    HttpTransport,
    ManifestEntry,
    archive_path,
    fetch_pinned,
    fetch_verified,
)
from crypto_grid_bot.v4.data.config import DataConfig, load_data_config

ROOT = Path(__file__).resolve().parents[1]
HOST = "https://data.binance.vision"
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
KINDS = ("spot_1d", "spot_1h", "futures_1h", "funding")


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket; each attempt is counted."""
    attempts: list[str] = []

    def refuse(*args, **kwargs):
        attempts.append("socket")
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return attempts


@pytest.fixture
def config() -> DataConfig:
    return replace(load_data_config(ROOT / "config" / "v4_data.json"), end_month="2024-12")


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def url_of(kind: str, symbol: str = "BTCUSDT", month: str = "2020-01") -> str:
    return HOST + archive_path(kind, symbol, month)


def checksum_of(content: bytes, kind: str = "spot_1h", symbol="BTCUSDT", month="2020-01") -> bytes:
    name = archive_path(kind, symbol, month).rsplit("/", 1)[1]
    return f"{sha(content)}  {name}\n".encode("ascii")


class FakeTransport:
    """Serves bytes from a dict of URL -> bytes, 404 (None) for the rest, and records requests."""

    def __init__(self, files=None):
        self.files = dict(files or {})
        self.requests: list[str] = []

    def get(self, url):
        self.requests.append(url)
        return self.files.get(url)


class ScriptedTransport:
    """Answers each request with the next outcome: an exception is raised, bytes or None are
    returned."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[str] = []

    def get(self, url):
        self.requests.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class Recorder:
    """A sleep and a log that only record, so no test waits."""

    def __init__(self):
        self.sleeps: list[float] = []
        self.logs: list[str] = []

    @property
    def kwargs(self):
        return {"sleep": self.sleeps.append, "log": self.logs.append}


def served(content: bytes, **names) -> FakeTransport:
    """A host serving ``content`` and its correct checksum for one archive."""
    url = url_of(names.get("kind", "spot_1h"), names.get("symbol", "BTCUSDT"))
    return FakeTransport({url: content, url + ".CHECKSUM": checksum_of(content, **names)})


def caused_by(cause: BaseException, message="public data transport failed") -> ValueError:
    """The ValueError ``HttpTransport`` raises for a transport error."""
    failure = ValueError(message)
    failure.__cause__ = cause
    return failure


# --- the network is blocked ---------------------------------------------------------------


def test_every_test_runs_with_the_network_blocked():
    # This test never asks for the fixture's value: it is autouse, so it is on for the file.
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("data.binance.vision", 443)
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("data.binance.vision", 443), timeout=1)
    with socket.socket() as sock, pytest.raises(NetworkBlocked):
        sock.connect(("127.0.0.1", 9))
    with socket.socket() as sock, pytest.raises(NetworkBlocked):
        sock.connect_ex(("127.0.0.1", 9))


# --- the archive layout -------------------------------------------------------------------


def test_archive_paths_match_binance_layout():
    assert archive_path("spot_1d", "BTCUSDT", "2020-01") == (
        "/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip"
    )
    assert archive_path("spot_1h", "ETHUSDT", "2021-12") == (
        "/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2021-12.zip"
    )
    assert archive_path("futures_1h", "1000SHIBUSDT", "2023-06") == (
        "/data/futures/um/monthly/klines/1000SHIBUSDT/1h/1000SHIBUSDT-1h-2023-06.zip"
    )
    assert archive_path("funding", "SOLUSDT", "2025-01") == (
        "/data/futures/um/monthly/fundingRate/SOLUSDT/SOLUSDT-fundingRate-2025-01.zip"
    )


@pytest.mark.parametrize(
    ("kind", "symbol", "month"),
    [
        ("spot", "BTCUSDT", "2020-01"),
        ("spot_1m", "BTCUSDT", "2020-01"),
        ("", "BTCUSDT", "2020-01"),
        ("spot_1h", "btcusdt", "2020-01"),
        ("spot_1h", "B", "2020-01"),
        ("spot_1h", "A" * 31, "2020-01"),
        ("spot_1h", "BTC/USDT", "2020-01"),
        ("spot_1h", "BTC-USDT", "2020-01"),
        ("spot_1h", "BTCUSDT\n", "2020-01"),
        ("spot_1h", "..", "2020-01"),
        ("spot_1h", "BTCUSDT", "2020-13"),
        ("spot_1h", "BTCUSDT", "2020-00"),
        ("spot_1h", "BTCUSDT", "2020-1"),
        ("spot_1h", "BTCUSDT", "20-01"),
        ("spot_1h", "BTCUSDT", "2020-01\n"),
        ("spot_1h", "BTCUSDT", "2020/01"),
        ("spot_1h", "BTCUSDT", "../2020-01"),
        ("spot_1h", "BTCUSDT", ""),
    ],
)
def test_archive_path_refuses_an_unknown_kind_or_a_malformed_symbol_or_month(kind, symbol, month):
    with pytest.raises(ValueError):
        archive_path(kind, symbol, month)


def test_the_symbol_length_bounds_are_two_and_thirty():
    assert archive_path("spot_1d", "AB", "2020-01").startswith("/data/spot/")
    assert archive_path("spot_1d", "A" * 30, "2020-01").startswith("/data/spot/")


def test_a_manifest_entry_is_a_frozen_record_with_these_fields():
    entry = ManifestEntry("spot_1h", "BTCUSDT", "2020-01", "/p", "ab" * 32, 7)
    assert (entry.kind, entry.symbol, entry.month) == ("spot_1h", "BTCUSDT", "2020-01")
    assert (entry.path, entry.sha256, entry.bytes) == ("/p", "ab" * 32, 7)
    with pytest.raises(FrozenInstanceError):
        entry.bytes = 8  # type: ignore[misc]


# --- a verified fetch ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_a_verified_fetch_returns_the_entry_and_the_bytes(kind, config):
    content = b"synthetic archive for " + kind.encode()
    host = served(content, kind=kind)
    recorder = Recorder()

    result = fetch_verified(host, kind, "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert result is not None
    entry, data = result
    assert data == content
    assert entry == ManifestEntry(
        kind=kind,
        symbol="BTCUSDT",
        month="2020-01",
        path=archive_path(kind, "BTCUSDT", "2020-01"),
        sha256=sha(content),
        bytes=len(content),
    )
    assert host.requests == [url_of(kind), url_of(kind) + ".CHECKSUM"]
    assert recorder.sleeps == [] and recorder.logs == []


@pytest.mark.parametrize(
    "spell",
    [
        lambda digest, name: f"{digest}  {name}\n",
        lambda digest, name: f"{digest}  {name}",  # no trailing newline
        lambda digest, name: f"{digest} *{name}\n",  # sha256sum binary-mode marker
        lambda digest, name: f"{digest}\t{name}\r\n",
        lambda digest, name: f"{digest.upper()}  {name}\n",  # upper-case hex
        lambda digest, name: f"\n{digest}  {name}\n\n",
    ],
)
def test_the_accepted_checksum_spellings(spell, config):
    content = b"some archive"
    name = archive_path("spot_1h", "BTCUSDT", "2020-01").rsplit("/", 1)[1]
    url = url_of("spot_1h")
    host = FakeTransport({url: content, url + ".CHECKSUM": spell(sha(content), name).encode()})

    result = fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **Recorder().kwargs)

    assert result is not None and result[0].sha256 == sha(content)  # always stored lower-case


@pytest.mark.parametrize(
    "build",
    [
        # Review Focus 5: a checksum that names another archive ...
        lambda content, name: f"{sha(content)}  ETHUSDT-1h-2020-01.zip\n".encode(),
        lambda content, name: f"{sha(content)}  BTCUSDT-1h-2020-02.zip\n".encode(),
        lambda content, name: f"{sha(content)}  BTCUSDT-1d-2020-01.zip\n".encode(),
        lambda content, name: f"{sha(content)}  other/{name}\n".encode(),
        lambda content, name: f"{sha(content)}  {name}.CHECKSUM\n".encode(),
        # ... or says nothing usable.
        lambda content, name: b"",
        lambda content, name: b"\n",
        lambda content, name: f"{sha(content)}\n".encode(),
        lambda content, name: f"{name}\n".encode(),
        lambda content, name: f"{sha(content)[:63]}  {name}\n".encode(),
        lambda content, name: f"{sha(content)}0  {name}\n".encode(),
        lambda content, name: f"{'g' * 64}  {name}\n".encode(),
        lambda content, name: f"{sha(content)} {name} extra\n".encode(),
        lambda content, name: f"{sha(content)}  {name}\n{sha(content)}  {name}\n".encode(),
        lambda content, name: f"{sha(content)}{name}\n".encode(),
        lambda content, name: b"<html>Access Denied</html>",
        lambda content, name: f"{sha(content)}  {name}é\n".encode(),  # not ASCII
        lambda content, name: b"\xff\xfe" + f"{sha(content)}  {name}".encode(),
        lambda content, name: b"x" * 1025,  # over the 1 KiB checksum cap
    ],
)
def test_checksum_for_another_file_or_absent_is_an_error(build, config):
    content = b"the real archive bytes"
    name = archive_path("spot_1h", "BTCUSDT", "2020-01").rsplit("/", 1)[1]
    url = url_of("spot_1h")
    host = FakeTransport({url: content, url + ".CHECKSUM": build(content, name)})
    recorder = Recorder()

    with pytest.raises(ValueError, match="checksum"):
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert recorder.sleeps == []  # never retried
    assert host.requests == [url, url + ".CHECKSUM"]


def test_a_checksum_that_is_not_bytes_is_an_error(config):
    url = url_of("spot_1h")
    host = FakeTransport({url: b"archive", url + ".CHECKSUM": "not bytes"})

    with pytest.raises(ValueError, match="checksum"):
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **Recorder().kwargs)


def test_a_checksum_at_the_cap_is_still_read(config):
    content = b"archive"
    url = url_of("spot_1h")
    name = archive_path("spot_1h", "BTCUSDT", "2020-01").rsplit("/", 1)[1]
    body = f"{sha(content)}  {name}".encode().ljust(1024, b"\n")
    assert len(body) == 1024
    host = FakeTransport({url: content, url + ".CHECKSUM": body})

    assert fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **Recorder().kwargs)


def test_mismatched_checksum_is_an_error_and_not_retried(config):
    content, other = b"what the host sent", b"what the checksum was made from"
    url = url_of("spot_1h")
    host = FakeTransport({url: content, url + ".CHECKSUM": checksum_of(other)})
    recorder = Recorder()

    with pytest.raises(ValueError, match="checksum mismatch") as caught:
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert sha(content) in str(caught.value) and sha(other) in str(caught.value)
    assert recorder.sleeps == []
    assert recorder.logs == []
    assert host.requests == [url, url + ".CHECKSUM"]  # each asked for once


def test_a_404_archive_is_none_but_a_404_checksum_is_an_error(config):
    url = url_of("spot_1h")
    recorder = Recorder()

    # No archive: None, one request, no checksum asked for, nothing retried.
    absent = FakeTransport()
    assert (
        fetch_verified(absent, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs) is None
    )
    assert absent.requests == [url]

    # An archive without a checksum is an error, not a skip and not a retry.
    unchecked = FakeTransport({url: b"archive"})
    with pytest.raises(ValueError, match="checksum"):
        fetch_verified(unchecked, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)
    assert unchecked.requests == [url, url + ".CHECKSUM"]
    assert recorder.sleeps == [] and recorder.logs == []


@pytest.mark.parametrize("bad", ["a string", ["list"], 7, bytearray(b"archive")])
def test_an_archive_that_is_not_bytes_is_an_error(bad, config):
    host = FakeTransport({url_of("spot_1h"): bad})

    with pytest.raises(ValueError, match="not bytes"):
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **Recorder().kwargs)

    assert len(host.requests) == 1


def test_the_archive_cap_is_64_mib_and_a_breach_is_an_error_not_retried(monkeypatch, config):
    assert archives.MAX_ARCHIVE_BYTES == 64 * 1024 * 1024
    assert archives.MAX_CHECKSUM_BYTES == 1024
    monkeypatch.setattr(archives, "MAX_ARCHIVE_BYTES", 10)
    recorder = Recorder()

    at_cap = b"x" * 10
    assert fetch_verified(
        served(at_cap), "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs
    )

    over = b"x" * 11
    host = served(over)
    with pytest.raises(ValueError, match="size limit"):
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)
    assert host.requests == [url_of("spot_1h")]  # the checksum is never asked for
    assert recorder.sleeps == []


def test_symbol_and_month_are_validated_before_any_request(config):
    host = FakeTransport()
    for symbol, month in (("btcusdt", "2020-01"), ("BTCUSDT", "2020-13"), ("../x", "2020-01")):
        with pytest.raises(ValueError):
            fetch_verified(host, "spot_1h", symbol, month, config, **Recorder().kwargs)
    with pytest.raises(ValueError):
        fetch_verified(host, "trades", "BTCUSDT", "2020-01", config, **Recorder().kwargs)
    assert host.requests == []


# --- retries ------------------------------------------------------------------------------

TRANSPORT_FAILURES = [
    pytest.param(caused_by(NetworkBlocked("down")), id="connection error, as HttpTransport"),
    pytest.param(caused_by(TimeoutError("slow")), id="timeout, as HttpTransport"),
    pytest.param(caused_by(http.client.IncompleteRead(b"")), id="HTTPException, as HttpTransport"),
    pytest.param(ValueError("public data returned HTTP 500"), id="HTTP 500"),
    pytest.param(
        ValueError("public data returned HTTP 503; redirects are never followed"), id="503"
    ),
    pytest.param(ConnectionResetError("reset"), id="raw ConnectionResetError"),
    pytest.param(TimeoutError("timed out"), id="raw TimeoutError"),
    pytest.param(http.client.RemoteDisconnected("closed"), id="raw HTTPException"),
    pytest.param(
        urllib.error.HTTPError("u", 502, "bad gateway", {}, io.BytesIO(b"")), id="raw HTTPError 502"
    ),
]

REFUSALS = [
    pytest.param(
        ValueError("public data returned HTTP 403; redirects are never followed"), id="403"
    ),
    pytest.param(ValueError("public data returned HTTP 400"), id="400"),
    pytest.param(ValueError("public data returned HTTP 301"), id="a redirect"),
    pytest.param(ValueError("public data returned HTTP 200 where a body was expected"), id="2xx"),
    pytest.param(ValueError("response exceeded the size limit of 1024 bytes"), id="size breach"),
    pytest.param(ValueError("https://example.com/x is not an allowed URL"), id="a guard refusal"),
    pytest.param(
        caused_by(KeyError("x"), "something else"), id="a cause that is not a network one"
    ),
    pytest.param(KeyError("x"), id="an unrelated error"),
    pytest.param(
        urllib.error.HTTPError("u", 418, "teapot", {}, io.BytesIO(b"")), id="raw HTTPError 418"
    ),
]


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES)
def test_transport_failures_retry_four_times_with_1_2_4_second_sleeps(failure, config):
    assert ATTEMPTS == 4
    url = url_of("spot_1h")
    host = ScriptedTransport([failure] * 4)
    recorder = Recorder()

    with pytest.raises(type(failure)) as caught:
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert caught.value is failure  # the last failure is the one that surfaces
    assert host.requests == [url] * 4
    assert recorder.sleeps == [1, 2, 4]
    assert len(recorder.logs) == 4
    assert all(url in line for line in recorder.logs)
    assert "attempt 1 of 4" in recorder.logs[0] and "attempt 4 of 4" in recorder.logs[3]


@pytest.mark.parametrize("failure", REFUSALS)
def test_everything_else_is_never_retried(failure, config):
    host = ScriptedTransport([failure, b"never reached"])
    recorder = Recorder()

    with pytest.raises(type(failure)) as caught:
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert caught.value is failure
    assert len(host.requests) == 1
    assert recorder.sleeps == [] and recorder.logs == []


def test_a_retry_that_succeeds_is_verified_like_any_other_fetch(config):
    content = b"archive after two failures"
    down = caused_by(NetworkBlocked("down"))
    host = ScriptedTransport([down, ValueError("HTTP 503"), content, down, checksum_of(content)])
    recorder = Recorder()

    entry, data = fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert data == content and entry.sha256 == sha(content)
    url = url_of("spot_1h")
    # Three tries for the archive and two for the checksum; each request has its own tries.
    assert host.requests == [url, url, url, url + ".CHECKSUM", url + ".CHECKSUM"]
    assert recorder.sleeps == [1, 2, 1]
    assert len(recorder.logs) == 3


def test_retried_bytes_that_do_not_match_the_checksum_are_still_refused(config):
    tampered = b"tampered"
    down = caused_by(NetworkBlocked("down"))
    host = ScriptedTransport([down, tampered, checksum_of(b"the real one")])
    recorder = Recorder()

    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert recorder.sleeps == [1]


def test_the_checksum_request_is_retried_too_and_fails_after_four_tries(config):
    url = url_of("spot_1h")
    down = caused_by(NetworkBlocked("down"))
    host = ScriptedTransport([b"archive", down, down, down, down])
    recorder = Recorder()

    with pytest.raises(ValueError, match="transport failed"):
        fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert host.requests == [url] + [url + ".CHECKSUM"] * 4
    assert recorder.sleeps == [1, 2, 4]


def test_a_404_is_not_a_transport_failure_and_is_not_retried(config):
    host = ScriptedTransport([None])
    recorder = Recorder()

    assert fetch_verified(host, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs) is None

    assert len(host.requests) == 1 and recorder.sleeps == []


# --- the end-month guard ------------------------------------------------------------------


def test_months_after_end_month_are_refused_before_any_request(config):
    early = replace(config, end_month="2020-02")
    host = FakeTransport()
    recorder = Recorder()

    for month in ("2020-03", "2020-12", "2021-01", "2026-10", "9999-12"):
        with pytest.raises(ValueError, match="after end_month"):
            fetch_verified(host, "spot_1h", "BTCUSDT", month, early, **recorder.kwargs)

    assert host.requests == []
    assert recorder.sleeps == [] and recorder.logs == []


def test_the_end_month_itself_and_earlier_months_are_fetched(config):
    early = replace(config, end_month="2020-02")
    for month in ("2020-02", "2020-01", "2017-08"):
        url = url_of("spot_1h", month=month)
        name = f"BTCUSDT-1h-{month}.zip"
        content = b"archive " + month.encode()
        host = FakeTransport(
            {url: content, url + ".CHECKSUM": f"{sha(content)}  {name}\n".encode("ascii")}
        )
        assert fetch_verified(host, "spot_1h", "BTCUSDT", month, early, **Recorder().kwargs)


def test_the_guard_covers_every_kind(config):
    early = replace(config, end_month="2020-02")
    host = FakeTransport()
    for kind in KINDS:
        with pytest.raises(ValueError, match="after end_month"):
            fetch_verified(host, kind, "BTCUSDT", "2020-03", early, **Recorder().kwargs)
    assert host.requests == []


# --- a pinned re-fetch --------------------------------------------------------------------


def pinned_entry(content: bytes, **overrides) -> ManifestEntry:
    base = {
        "kind": "spot_1h",
        "symbol": "BTCUSDT",
        "month": "2020-01",
        "path": archive_path("spot_1h", "BTCUSDT", "2020-01"),
        "sha256": sha(content),
        "bytes": len(content),
    }
    return ManifestEntry(**{**base, **overrides})


def test_pinned_fetch_returns_bytes_that_match_the_pin_without_asking_for_a_checksum():
    content = b"the pinned archive"
    host = FakeTransport({url_of("spot_1h"): content})
    recorder = Recorder()

    assert fetch_pinned(host, pinned_entry(content), **recorder.kwargs) == content

    assert host.requests == [url_of("spot_1h")]  # no .CHECKSUM request
    assert recorder.sleeps == [] and recorder.logs == []


def test_pinned_fetch_refuses_bytes_whose_sha256_differs():
    good, tampered = b"the pinned archive", b"some other bytes"
    host = FakeTransport({url_of("spot_1h"): tampered})
    recorder = Recorder()

    with pytest.raises(ValueError, match="sha256") as caught:
        fetch_pinned(host, pinned_entry(good), **recorder.kwargs)

    assert sha(good) in str(caught.value) and sha(tampered) in str(caught.value)
    assert host.requests == [url_of("spot_1h")]  # never retried
    assert recorder.sleeps == []


def test_pinned_fetch_of_an_archive_that_is_gone_is_an_error():
    content = b"the pinned archive"
    host = FakeTransport()

    with pytest.raises(ValueError, match="404"):
        fetch_pinned(host, pinned_entry(content), **Recorder().kwargs)


def test_pinned_fetch_retries_transport_failures_like_any_other_fetch():
    content = b"the pinned archive"
    down = caused_by(NetworkBlocked("down"))
    recorder = Recorder()

    host = ScriptedTransport([down, ValueError("HTTP 502"), content])
    assert fetch_pinned(host, pinned_entry(content), **recorder.kwargs) == content
    assert recorder.sleeps == [1, 2]

    hopeless = ScriptedTransport([down] * 4)
    with pytest.raises(ValueError, match="transport failed"):
        fetch_pinned(hopeless, pinned_entry(content), **recorder.kwargs)
    assert len(hopeless.requests) == 4
    assert recorder.sleeps == [1, 2, 1, 2, 4]


def test_pinned_fetch_enforces_the_archive_cap_and_the_bytes_type(monkeypatch):
    monkeypatch.setattr(archives, "MAX_ARCHIVE_BYTES", 10)
    big = b"x" * 11
    with pytest.raises(ValueError, match="size limit"):
        fetch_pinned(
            FakeTransport({url_of("spot_1h"): big}), pinned_entry(big), **Recorder().kwargs
        )
    with pytest.raises(ValueError, match="not bytes"):
        fetch_pinned(
            FakeTransport({url_of("spot_1h"): "text"}), pinned_entry(b"x"), **Recorder().kwargs
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"path": "/data/spot/monthly/klines/ETHUSDT/1h/ETHUSDT-1h-2020-01.zip"},
        {"path": "https://evil.example/data/spot/monthly/klines/BTCUSDT/1h/x.zip"},
        {"path": "/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2020-01.zip.CHECKSUM"},
        {"kind": "futures_1h"},  # the path is the spot one
        {"symbol": "btcusdt"},
        {"month": "2020-13"},
        {"sha256": "AB" * 32},  # upper-case
        {"sha256": "ab" * 31},
        {"sha256": ""},
    ],
)
def test_pinned_fetch_refuses_an_inconsistent_entry_before_any_request(overrides):
    host = FakeTransport({url_of("spot_1h"): b"x"})

    with pytest.raises(ValueError):
        fetch_pinned(host, pinned_entry(b"x", **overrides), **Recorder().kwargs)

    assert host.requests == []


# --- HttpTransport: the allowlist ---------------------------------------------------------

ALLOWED = [
    *(url_of(kind) for kind in KINDS),
    *(url_of(kind) + ".CHECKSUM" for kind in KINDS),
    url_of("spot_1d", "1000SHIBUSDT", "2025-01"),
    LISTING + "?delimiter=/&prefix=data/spot/monthly/klines/",
    LISTING + "?delimiter=/&prefix=data/futures/um/monthly/fundingRate/BTCUSDT/",
    LISTING
    + "?delimiter=/&prefix=data/spot/monthly/klines/&marker=data/spot/monthly/klines/BTCUSDT/",
    LISTING + "?delimiter=/&prefix=data/spot/monthly/klines/BTCUSDT/1h/"
    "&marker=data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2020-01.zip",
    LISTING + "?delimiter=/&prefix=data/",
]

PATH = archive_path("spot_1h", "BTCUSDT", "2020-01")
BUCKET = "s3-ap-northeast-1.amazonaws.com"

REFUSED = [
    # another host, scheme or port
    "https://api.binance.com/api/v3/exchangeInfo",
    "https://fapi.binance.com/fapi/v1/exchangeInfo",
    "https://data-api.binance.vision/api/v3/exchangeInfo",
    "http://data.binance.vision" + PATH,
    "ftp://data.binance.vision" + PATH,
    "file:///etc/passwd",
    "https://data.binance.vision:8443" + PATH,
    "https://data.binance.vision:443" + PATH,
    "https://DATA.BINANCE.VISION" + PATH,
    "https://evil.example@data.binance.vision" + PATH,
    "https://data.binance.vision@evil.example" + PATH,
    "https://data.binance.vision.evil.example" + PATH,
    "https://evil.example/https://data.binance.vision" + PATH,
    "//data.binance.vision" + PATH,
    "https://data.binance.vision\\@evil.example" + PATH,
    "https://s3.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/",
    "https://data.binance.vision.s3.amazonaws.com/?delimiter=/&prefix=data/",
    f"https://{BUCKET}:8443/data.binance.vision?delimiter=/&prefix=data/",
    f"http://{BUCKET}/data.binance.vision?delimiter=/&prefix=data/",
    # the archive host: a path outside the four shapes
    "https://data.binance.vision",
    "https://data.binance.vision/",
    "https://data.binance.vision/data/",
    "https://data.binance.vision/index.html",
    HOST + PATH.replace("/monthly/", "/daily/").replace("2020-01", "2020-01-01"),
    HOST + "/data/spot/monthly/trades/BTCUSDT/BTCUSDT-trades-2020-01.zip",
    HOST + PATH.replace("1h", "1m"),
    HOST + PATH.replace("/spot/", "/futures/cm/"),
    HOST + PATH.replace("/spot/", "/futures/um/").replace("1h", "1d"),
    HOST + "/data/futures/um/monthly/premiumIndexKlines/BTCUSDT/1h/BTCUSDT-1h-2020-01.zip",
    HOST + PATH.replace("BTCUSDT-1h", "ETHUSDT-1h"),
    HOST + PATH.replace("1h/BTCUSDT-1h", "1d/BTCUSDT-1h"),
    HOST + PATH.replace("2020-01", "2020-13"),
    HOST + PATH.replace("2020-01", "2020-1"),
    HOST + PATH.replace("BTCUSDT", "btcusdt"),
    HOST + PATH.replace("BTCUSDT/1h", "B/1h").replace("BTCUSDT-1h", "B-1h"),
    HOST + PATH + "/",
    HOST + PATH.replace(".zip", ".csv"),
    HOST + PATH + ".CHECKSUM.CHECKSUM",
    HOST + PATH + ".checksum",
    HOST + PATH.replace("/1h/", "/1h/../1h/"),
    HOST + PATH.replace("/klines/", "/klines/../klines/"),
    HOST + PATH + "?x=1",
    HOST + PATH + "?",
    HOST + PATH + "#frag",
    HOST + "/" + PATH,
    HOST + PATH + "\n",
    HOST + PATH + " ",
    " " + HOST + PATH,
    HOST + PATH.replace("BTCUSDT/1h", "BTC%55SDT/1h"),
    HOST + PATH.replace(".zip", "\r\n.zip"),
    # the listing host: anything but the bucket listing query
    f"https://{BUCKET}",
    f"https://{BUCKET}/",
    f"https://{BUCKET}/data.binance.vision",
    f"https://{BUCKET}/data.binance.vision?",
    f"https://{BUCKET}/data.binance.vision/",
    f"https://{BUCKET}/data.binance.vision/?delimiter=/&prefix=data/",
    f"https://{BUCKET}/other-bucket?delimiter=/&prefix=data/",
    f"https://{BUCKET}/?delimiter=/&prefix=data/",
    f"https://{BUCKET}/data.binance.vision" + PATH,
    f"https://{BUCKET}/data.binance.vision{PATH}?delimiter=/&prefix=data/",
    LISTING + "?prefix=data/",
    LISTING + "?delimiter=/",
    LISTING + "?prefix=data/&delimiter=/",
    LISTING + "?delimiter=%2F&prefix=data/",
    LISTING + "?delimiter=/&prefix=",
    LISTING + "?delimiter=/&prefix=other/",
    LISTING + "?delimiter=/&prefix=Data/",
    LISTING + "?delimiter=/&prefix=data",
    LISTING + "?delimiter=/&prefix=data/../secret/",
    LISTING + "?delimiter=/&prefix=data/&marker=",
    LISTING + "?delimiter=/&prefix=data/&marker=other/key",
    LISTING + "?delimiter=/&prefix=data/&marker=data/a&marker=data/b",
    LISTING + "?delimiter=/&prefix=data/&max-keys=1000",
    LISTING + "?delimiter=/&prefix=data/&list-type=2",
    LISTING + "?delimiter=/&prefix=data/&uploads",
    LISTING + "?delimiter=/&prefix=data/&marker=data/a&max-keys=1",
    LISTING + "?delimiter=/&prefix=data/ &marker=data/a",
    LISTING + "?delimiter=/&prefix=data/#frag",
    LISTING + "?delimiter=/&prefix=data/\n",
    LISTING + "?delimiter=/&prefix=data/@evil.example",
    LISTING + "?delimiter=/&prefix=data/&marker=data/%zz",
    # not URLs at all
    "",
    "data.binance.vision",
    PATH,
    None,
    (HOST + PATH).encode(),
    7,
]


@pytest.mark.parametrize("url", REFUSED, ids=[repr(url)[:90] for url in REFUSED])
def test_http_transport_refuses_other_hosts_without_opening_a_socket(url, network_blocked):
    transport = HttpTransport()

    with pytest.raises(ValueError, match="not an allowed URL"):
        transport.get(url)

    # The blocked socket would have raised NetworkBlocked (an OSError, so it would have come
    # out as "transport failed"); the refusal came first and no socket call was even tried.
    assert network_blocked == []


@pytest.mark.parametrize("url", ALLOWED, ids=[url[8:100] for url in ALLOWED])
def test_http_transport_lets_the_allowed_urls_through_to_the_socket(url, network_blocked):
    transport = HttpTransport()

    with pytest.raises(ValueError, match="transport failed") as caught:
        transport.get(url)

    assert isinstance(caught.value.__cause__, OSError)
    assert network_blocked  # it got as far as the (blocked) socket


def test_the_real_transport_stays_offline_and_its_failure_is_the_one_that_is_retried(
    config, network_blocked
):
    recorder = Recorder()

    with pytest.raises(ValueError, match="transport failed") as caught:
        fetch_verified(HttpTransport(), "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert isinstance(caught.value.__cause__, OSError)
    assert recorder.sleeps == [1, 2, 4]
    assert len(recorder.logs) == 4
    assert len(network_blocked) >= 4


def test_the_timeout_is_checked():
    assert HttpTransport()._timeout == 30
    assert HttpTransport(timeout=5)._timeout == 5
    for bad in (0, -1, True, "30", None, float("nan")):
        with pytest.raises(ValueError, match="timeout"):
            HttpTransport(timeout=bad)  # type: ignore[arg-type]


# --- HttpTransport: responses -------------------------------------------------------------


class FakeResponse:
    def __init__(self, body: bytes = b"", status: int = 200):
        self.body = body
        self.status = status
        self.asked: list[int] = []
        self.closed = False

    def read(self, amount: int = -1) -> bytes:
        self.asked.append(amount)
        return self.body if amount < 0 else self.body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


class FakeOpener:
    """Stands in for the urllib opener: no socket is involved at all."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def open(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def transport_with(outcome, timeout=30) -> tuple[HttpTransport, FakeOpener]:
    transport = HttpTransport(timeout=timeout)
    opener = FakeOpener(outcome)
    transport._opener = opener
    return transport, opener


def http_error(code: int, url: str = url_of("spot_1h")) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "status", {}, io.BytesIO(b"body"))


def test_a_200_returns_the_body_through_a_plain_get_with_the_timeout():
    response = FakeResponse(b"zip bytes")
    transport, opener = transport_with(response, timeout=12)

    assert transport.get(url_of("spot_1h")) == b"zip bytes"

    (request,) = opener.requests
    assert request.full_url == url_of("spot_1h")
    assert request.get_method() == "GET"
    assert not request.has_header("Authorization") and request.data is None
    assert opener.timeouts == [12]
    assert response.closed


def test_a_404_is_none_and_any_other_status_is_a_valueerror_naming_it():
    assert transport_with(http_error(404))[0].get(url_of("spot_1h")) is None

    for code in (301, 302, 307, 400, 403, 416, 429, 500, 502, 503):
        transport, _ = transport_with(http_error(code))
        with pytest.raises(ValueError, match=f"HTTP {code}") as caught:
            transport.get(url_of("spot_1h"))
        assert caught.value.__cause__ is None

    # A 2xx other than 200 is not a body worth reading.
    transport, _ = transport_with(FakeResponse(b"x", status=206))
    with pytest.raises(ValueError, match="HTTP 206"):
        transport.get(url_of("spot_1h"))


def test_http_errors_are_classified_so_only_5xx_is_retried(config):
    for code, retried in ((500, True), (503, True), (403, False), (301, False), (416, False)):
        transport, opener = transport_with(http_error(code))
        recorder = Recorder()
        with pytest.raises(ValueError, match=f"HTTP {code}"):
            fetch_verified(transport, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)
        assert len(opener.requests) == (4 if retried else 1), code
        assert recorder.sleeps == ([1, 2, 4] if retried else []), code


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(NetworkBlocked("no route")),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        http.client.IncompleteRead(b"par"),
        http.client.RemoteDisconnected("closed"),
    ],
)
def test_connection_errors_and_timeouts_are_transport_failures(error, config):
    transport, opener = transport_with(error)
    recorder = Recorder()

    with pytest.raises(ValueError, match="transport failed") as caught:
        fetch_verified(transport, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)

    assert caught.value.__cause__ is error
    assert len(opener.requests) == 4
    assert recorder.sleeps == [1, 2, 4]


def test_the_read_is_bounded_by_the_size_cap_for_each_kind_of_url():
    assert archives.MAX_LISTING_BYTES == 4 * 1024 * 1024
    cases = (
        (url_of("spot_1h"), archives.MAX_ARCHIVE_BYTES),
        (url_of("funding"), archives.MAX_ARCHIVE_BYTES),
        (url_of("spot_1h") + ".CHECKSUM", 1024),
        (LISTING + "?delimiter=/&prefix=data/", 4 * 1024 * 1024),
    )
    for url, limit in cases:
        response = FakeResponse(b"ok")
        transport, _ = transport_with(response)
        assert transport.get(url) == b"ok"
        assert response.asked == [limit + 1]


def test_a_body_over_the_cap_is_a_size_error_that_is_not_retried(config):
    for url, limit in (
        (url_of("spot_1h") + ".CHECKSUM", 1024),
        (LISTING + "?delimiter=/&prefix=data/", archives.MAX_LISTING_BYTES),
    ):
        transport, _ = transport_with(FakeResponse(b"x" * (limit + 1)))
        with pytest.raises(ValueError, match="size limit") as caught:
            transport.get(url)
        assert caught.value.__cause__ is None

    # Through fetch_verified: the 1025-byte body is a fine archive but an oversize checksum;
    # the archive and the checksum are each asked for once, and nothing sleeps.
    transport, opener = transport_with(FakeResponse(b"x" * 1025))
    recorder = Recorder()
    with pytest.raises(ValueError, match="size limit"):
        fetch_verified(transport, "spot_1h", "BTCUSDT", "2020-01", config, **recorder.kwargs)
    assert [r.full_url for r in opener.requests] == [
        url_of("spot_1h"),
        url_of("spot_1h") + ".CHECKSUM",
    ]
    assert recorder.sleeps == [] and recorder.logs == []

    # A body exactly at the cap is fine.
    transport, _ = transport_with(FakeResponse(b"x" * 1024))
    assert transport.get(url_of("spot_1h") + ".CHECKSUM") == b"x" * 1024


def test_the_opener_never_follows_a_redirect():
    opener = HttpTransport()._opener
    redirect = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert len(redirect) == 1
    request = urllib.request.Request(url_of("spot_1h"))
    for code in (301, 302, 303, 307, 308):
        assert (
            redirect[0].redirect_request(
                request, io.BytesIO(b""), code, "moved", {}, "https://evil.example/x"
            )
            is None
        )


def test_the_opener_ignores_proxy_settings_in_the_environment(monkeypatch):
    for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://proxy.invalid:3128")

    def proxied(opener):
        return [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]

    # The default opener would route through the proxy; HttpTransport's goes to the host.
    assert proxied(urllib.request.build_opener())
    assert proxied(HttpTransport()._opener) == []


class Moved(urllib.response.addinfourl):
    msg = "Moved Permanently"


def test_a_redirect_surfaces_as_an_error_and_the_new_host_is_never_requested(
    monkeypatch, network_blocked
):
    # The real opener and its real handler chain; only the step that would open the socket
    # is replaced, by a server that answers 301 to another host.
    asked: list[str] = []

    def moved(self, request):
        asked.append(request.full_url)
        headers = http.client.HTTPMessage()
        headers["Location"] = "https://evil.example/stolen"
        return Moved(io.BytesIO(b""), headers, request.full_url, 301)

    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", moved)
    transport = HttpTransport()

    with pytest.raises(ValueError, match="HTTP 301"):
        transport.get(url_of("spot_1h"))

    assert asked == [url_of("spot_1h")]
    assert network_blocked == []
